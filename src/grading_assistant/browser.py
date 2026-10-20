import asyncio
from hashlib import sha256
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .config import SiteConfig
from .contracts import Evidence, GradingTask
from .grading import DomainError


class IGradingBrowser(Protocol):
    async def open_login(self) -> None: ...
    async def read_submissions(self, run_id: str, task: GradingTask) -> list[Evidence]: ...
    async def close(self) -> None: ...


def normalized_url(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


class ReadPolicy:
    """请求拦截与业务核验共同限制权限；登录 POST 例外在读取前失效。"""
    def __init__(self, config: SiteConfig):
        self.config = config
        self.login_phase = True

    def allows(self, url: str, method: str) -> bool:
        url = normalized_url(url)
        if method in {"GET", "HEAD"}:
            return url in self.config.read_urls
        return self.login_phase and method == "POST" and url in self.config.login_post_urls


class PlaywrightBrowser:
    """版本化只读快照适配器，不提供点击、填表、任意脚本或提交接口。

    站点 DOM 契约见 docs/site-adapter.md，实际页面变化需维护者重新适配验收。
    """
    def __init__(self, config: SiteConfig, interval: float = 2, headless: bool = False):
        if not config.enabled or config.adapter_version != "snapshot-v1":
            raise DomainError("SITE_ADAPTER_DISABLED")
        self.config, self.interval, self.headless = config, interval, headless
        self.policy = ReadPolicy(config)
        self.runtime = self.browser = self.context = self.page = None
        self.blocked_count = 0
        self.violation = False

    async def open_login(self):
        from playwright.async_api import async_playwright
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(accept_downloads=False, service_workers="block")
        await self.context.route("**/*", self._route)
        await self.context.route_web_socket("**/*", lambda ws: ws.close())
        self.page = await self.context.new_page()
        self.page.set_default_timeout(8000)
        await self.page.goto(self.config.login_url, wait_until="domcontentloaded")
        if normalized_url(self.page.url) not in self.config.read_urls:
            raise DomainError("NAVIGATION_DENIED")

    async def _route(self, route):
        if self.policy.allows(route.request.url, route.request.method):
            # 禁止自动跟随跳转；先检查 Location，防止初始 URL 合法但实际目标越界。
            try:
                response = await route.fetch(max_redirects=0, timeout=15000)
                if 300 <= response.status < 400:
                    from urllib.parse import urljoin
                    target = urljoin(route.request.url, response.headers.get("location", ""))
                    if not self.policy.allows(target, "GET"):
                        self.violation = True
                        await route.abort()
                        return
                await route.fulfill(response=response)
            except Exception:
                self.violation = True
                await route.abort()
        else:
            self.blocked_count += 1
            self.violation = True
            await route.abort()

    async def _identity(self, task: GradingTask):
        # 每次读取前后都核验真实页面身份，配置中的预期教师 ID 不能替代登录证明。
        if not self.page or normalized_url(self.page.url) not in self.config.page_urls:
            raise DomainError("NAVIGATION_DENIED")
        if self.violation:
            raise DomainError("UNEXPECTED_NETWORK_REQUEST")
        root = self.page.locator('[data-grading-root="snapshot-v1"]')
        if await root.count() != 1 or not await root.is_visible():
            raise DomainError("PAGE_STRUCTURE_CHANGED")
        expected = {"data-teacher-id": self.config.teacher_id, "data-course-id": task.course_id,
                    "data-assignment-id": task.assignment_id, "data-question-id": task.question_id,
                    "data-rubric-version": task.rubric_version}
        for attr, value in expected.items():
            if await root.get_attribute(attr) != value:
                raise DomainError("IDENTITY_MISMATCH")
        if await root.get_attribute("data-complete") != "true":
            raise DomainError("PAGE_INCOMPLETE")
        question = root.locator("[data-question-text]")
        if await question.count() != 1 or (await question.inner_text()).strip() != task.question:
            raise DomainError("QUESTION_CHANGED")
        rubric = root.locator("[data-rubric-json]")
        if await rubric.count() != 1:
            raise DomainError("RUBRIC_MISSING")
        import json
        try:
            if json.loads(await rubric.inner_text()) != [c.model_dump() for c in task.criteria]:
                raise DomainError("RUBRIC_CHANGED")
        except ValueError:
            raise DomainError("RUBRIC_INVALID") from None
        return root

    async def read_submissions(self, run_id: str, task: GradingTask) -> list[Evidence]:
        if task != self.config.task:
            raise DomainError("TASK_NOT_AUTHORIZED")
        # 教师先手动进入任务页并确认身份；之后收紧为完全只读的网络策略。
        await self._identity(task)
        self.policy.login_phase = False
        results, seen = [], set()
        for index, url in enumerate(self.config.page_urls):
            if index:
                await asyncio.sleep(self.interval)
            await self.page.goto(url, wait_until="domcontentloaded")
            root = await self._identity(task)
            if await root.get_attribute("data-page-number") != str(index + 1):
                raise DomainError("PAGE_ORDER_MISMATCH")
            if await root.get_attribute("data-page-count") != str(len(self.config.page_urls)):
                raise DomainError("PAGE_COUNT_MISMATCH")
            rows = root.locator("[data-submission-id]")
            for i in range(await rows.count()):
                await self._identity(task)
                row = rows.nth(i)
                sid = await row.get_attribute("data-submission-id")
                if not sid or sid in seen:
                    raise DomainError("SUBMISSION_ID_CONFLICT")
                seen.add(sid)
                answer_node = row.locator("[data-answer]")
                if await answer_node.count() != 1 or not await answer_node.is_visible():
                    raise DomainError("ANSWER_STRUCTURE_CHANGED")
                before = await row.get_attribute("data-submission-id")
                answer = (await answer_node.inner_text()).strip()
                if before != await row.get_attribute("data-submission-id"):
                    raise DomainError("IDENTITY_CHANGED_DURING_READ")
                quality = await row.get_attribute("data-quality")
                attachments = await row.get_attribute("data-attachment-count")
                if attachments is None or not attachments.isdigit():
                    raise DomainError("ATTACHMENT_COUNT_MISSING")
                if int(attachments):
                    quality = "attachment"
                if not answer:
                    quality = "blank"
                identifiers = await row.locator("[data-private-identifier]").all_text_contents()
                results.append(Evidence(
                    run_id=run_id, source_site_id=task.source_site_id, course_id=task.course_id,
                    assignment_id=task.assignment_id, question_id=task.question_id, submission_id=sid,
                    source_locator=f"{url}#submission={sid}", answer=answer, quality=quality,
                    content_hash=sha256(answer.encode()).hexdigest(), private_identifiers=identifiers,
                ))
                await self._identity(task)
            await self._identity(task)
        if len(results) != self.config.expected_submissions:
            raise DomainError("SUBMISSION_COUNT_MISMATCH")
        return results

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            if self.runtime:
                await self.runtime.stop()
            self.runtime = self.browser = self.context = self.page = None
