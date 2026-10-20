import asyncio
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from . import demo
from .browser import PlaywrightBrowser
from .config import Settings
from .contracts import Evidence, GradingTask, ReviewInput, now
from .grading import CloudGateway, DemoGateway, DomainError, model_request, validate_suggestion
from .storage import Store


class Orchestrator:
    """单机串行编排器：持久化事实先于执行，模型没有自由调用工具的能力。"""
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store
        self.workers: dict[str, asyncio.Task] = {}
        self.sessions: dict[str, PlaywrightBrowser] = {}
        self.emergency_errors: dict[str, str] = {}

    def get(self, run_id: str):
        run = self.store.get(run_id)
        if run_id in self.emergency_errors:
            run.update(status="paused", error_code=self.emergency_errors[run_id])
        return run

    def tasks(self):
        return [demo.TASK] + ([self.settings.site.task] if self.settings.site.enabled else [])

    def task(self, task_id: str):
        for task in self.tasks():
            if task.id == task_id:
                return task
        raise DomainError("TASK_NOT_AUTHORIZED")

    def idle(self):
        # 登录浏览器即使暂时没有读取协程，也占用执行权，防止交叉读取任务。
        if any(not worker.done() for worker in self.workers.values()) or self.sessions:
            raise DomainError("ANOTHER_RUN_ACTIVE")

    def dispatch(self, run_id, coroutine):
        self.emergency_errors.pop(run_id, None)
        self.workers[run_id] = asyncio.create_task(coroutine)

    def create(self, task_id: str):
        self.idle()
        self.store.purge(self.settings.retention_days)
        task = self.task(task_id)
        is_demo = task.id == demo.TASK.id
        run = {"schema_version": "1", "id": uuid4().hex, "revision": 0,
               "task": task.model_dump(), "mode": "demo" if is_demo else "school",
               "status": "reading" if is_demo else "awaiting_login", "created_at": now(),
               "updated_at": now(), "error_code": None, "cancel_requested": False,
               "items": [], "model_calls": 0}
        self.store.save(run, "run_created")
        self.dispatch(run["id"], self.capture(run["id"], login_only=not is_demo))
        return run

    async def capture(self, run_id: str, login_only=False):
        try:
            run = self.store.get(run_id)
            task = self.task(run["task"]["id"])
            if run["mode"] == "demo":
                await asyncio.sleep(0.2)
                entries = demo.evidence(run_id)
            else:
                if login_only:
                    browser = PlaywrightBrowser(self.settings.site, self.settings.read_interval_seconds)
                    self.sessions[run_id] = browser
                    await browser.open_login()
                    return
                entries = await self.sessions[run_id].read_submissions(run_id, task)
            # 全部分页完成身份/数量核验后整批保存，避免部分串卷数据成为有效证据。
            run = self.store.get(run_id)
            seen = set()
            items = []
            for entry in entries:
                key = (entry.source_site_id, entry.course_id, entry.assignment_id, entry.question_id, entry.submission_id)
                if key in seen or entry.run_id != run_id or key[:4] != (task.source_site_id, task.course_id, task.assignment_id, task.question_id):
                    raise DomainError("SUBMISSION_ID_CONFLICT")
                seen.add(key)
                items.append({"evidence": entry.model_dump(), "request": model_request(task, entry) if entry.quality == "complete" else None,
                              "status": "pending" if entry.quality == "complete" else "manual",
                              "draft": None, "history": [], "error_code": None})
            run.update(items=items, status="ready", error_code=None)
            self.store.save(run, "capture_completed", {"count": len(items)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.fail(run_id, exc)
        finally:
            if not login_only or self.store.get(run_id)["status"] != "awaiting_login":
                await self.close_session(run_id)

    def confirm_login(self, run_id: str):
        run = self.store.get(run_id)
        worker = self.workers.get(run_id)
        if run["status"] != "awaiting_login" or run_id not in self.sessions or (worker and not worker.done()):
            raise DomainError("LOGIN_NOT_READY")
        run["status"] = "reading"
        self.store.save(run, "teacher_confirmed_identity")
        self.dispatch(run_id, self.capture(run_id))
        return run

    def generate(self, run_id: str):
        # 该入口由教师看过外发预览后调用；读取完成不会自行发送云请求。
        self.idle()
        run = self.get(run_id)
        if run["status"] not in {"ready", "paused", "cancelled", "review"} or not run["items"]:
            raise DomainError("RUN_NOT_READY")
        if run["mode"] != "demo" and not self.settings.cloud.enabled:
            raise DomainError("CLOUD_DISABLED")
        if run["task"] != self.task(run["task"]["id"]).model_dump():
            raise DomainError("TASK_CONFIGURATION_CHANGED")
        if not any(i["status"] in {"pending", "error"} for i in run["items"]):
            raise DomainError("NO_PENDING_ITEMS")
        run.update(status="generating", cancel_requested=False, error_code=None)
        self.store.save(run, "teacher_approved_generation")
        self.dispatch(run_id, self.grade(run_id))
        return run

    async def grade(self, run_id: str):
        try:
            run = self.store.get(run_id)
            task = GradingTask.model_validate(run["task"])
            gateway = DemoGateway() if run["mode"] == "demo" else CloudGateway(self.settings.cloud)
            for index in range(len(run["items"])):
                run = self.store.get(run_id)
                if run["cancel_requested"]:
                    return
                item = run["items"][index]
                if item["status"] not in {"pending", "error"}:
                    continue
                if run["mode"] != "demo" and run["model_calls"] + 2 > self.settings.cloud.max_requests_per_run:
                    raise DomainError("MODEL_BUDGET_EXCEEDED")
                # 外发前先持久化预留最多两次调用的预算，存储失败时不继续请求。
                run["model_calls"] += 1 if run["mode"] == "demo" else 2
                self.store.save(run, "generation_started", {"object_index": index})
                try:
                    suggestion = validate_suggestion(task, item["request"], await gateway.generate(task, item["request"]))
                    run = self.store.get(run_id)
                    if run["cancel_requested"]:
                        return
                    item = run["items"][index]
                    item.update(status="draft", error_code=None,
                                draft={"version": 1, "suggestion": suggestion.model_dump(), "model": gateway.name,
                                       "prompt_version": "grading-v1", "rubric_version": task.rubric_version,
                                       "review_status": "pending", "note": "", "created_at": now()})
                    self.store.save(run, "draft_created", {"object_index": index, "version": 1})
                except DomainError as exc:
                    run = self.store.get(run_id)
                    run["items"][index].update(status="error", error_code=exc.code)
                    self.store.save(run, "generation_failed", {"object_index": index, "code": exc.code})
                await asyncio.sleep(self.settings.read_interval_seconds if run["mode"] != "demo" else 0.1)
            run = self.store.get(run_id)
            run["status"] = "review"
            self.store.save(run, "generation_completed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.fail(run_id, exc)

    def fail(self, run_id, exc):
        try:
            run = self.store.get(run_id)
            run.update(status="paused", error_code=exc.code if isinstance(exc, DomainError) else "PROCESSING_FAILED")
            self.store.save(run, "run_paused", {"code": run["error_code"]})
        except Exception:
            # 磁盘故障导致暂停状态无法落盘时，仍停止任务并暴露内存错误；重启后再次对账。
            self.emergency_errors[run_id] = "STORAGE_FAILURE"

    async def close_session(self, run_id):
        browser = self.sessions.pop(run_id, None)
        if browser:
            await browser.close()

    async def cancel(self, run_id: str):
        # 先记录取消意图，再中断协程并关闭会话；已发出的云请求无法撤回。
        run = self.get(run_id)
        if run["status"] not in {"reading", "generating", "awaiting_login", "ready", "paused"}:
            raise DomainError("RUN_NOT_CANCELLABLE")
        run.update(cancel_requested=True, status="cancelled")
        try:
            self.store.save(run, "teacher_cancelled")
        except Exception:
            self.emergency_errors[run_id] = "STORAGE_FAILURE"
        finally:
            worker = self.workers.get(run_id)
            if worker and not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            await self.close_session(run_id)
        return self.get(run_id)

    def resume(self, run_id):
        run = self.get(run_id)
        if run["status"] not in {"paused", "cancelled", "review"}:
            raise DomainError("RUN_NOT_RESUMABLE")
        if run["items"]:
            return self.generate(run_id)
        self.idle()
        self.task(run["task"]["id"])
        run.update(status="reading" if run["mode"] == "demo" else "awaiting_login",
                   cancel_requested=False, error_code=None)
        self.store.save(run, "teacher_resumed")
        self.dispatch(run_id, self.capture(run_id, login_only=run["mode"] != "demo"))
        return run

    def review(self, run_id, submission_id, review: ReviewInput):
        run = self.store.get(run_id)
        if run["status"] in {"generating", "reading", "awaiting_login"}:
            raise DomainError("RUN_BUSY")
        item = next((i for i in run["items"] if i["evidence"]["submission_id"] == submission_id), None)
        if item is None or item["draft"] is None:
            raise DomainError("DRAFT_NOT_FOUND")
        draft = item["draft"]
        if review.expected_version != draft["version"]:
            raise DomainError("REVISION_CONFLICT")
        revised = deepcopy(draft)
        if review.action == "edited":
            task = GradingTask.model_validate(run["task"])
            if set(review.scores) != {c.id for c in task.criteria}:
                raise DomainError("CRITERIA_MISMATCH")
            for criterion in revised["suggestion"]["criteria"]:
                score = review.scores[criterion["criterion_id"]]
                limit = next(c.max_score for c in task.criteria if c.id == criterion["criterion_id"])
                if not 0 <= score <= limit:
                    raise DomainError("SCORE_OUT_OF_RANGE")
                criterion["score"] = score
            revised["suggestion"]["score_suggestion"] = float(sum(Decimal(str(v)) for v in review.scores.values()))
        elif review.scores:
            raise DomainError("UNEXPECTED_REVIEW_SCORES")
        item["history"].append(deepcopy(draft))
        revised.update(version=draft["version"] + 1, review_status=review.action, note=review.note, reviewed_at=now())
        item.update(draft=revised, status=review.action)
        # 缺页/失败答卷仍保留待处理状态，不能因为其他草稿复核完成而伪装全批完成。
        run["status"] = "reviewed" if all(i["status"] in {"accepted", "edited", "rejected"} for i in run["items"]) else "review"
        self.store.save(run, "local_review", {"object_index": run["items"].index(item),
                                             "version": revised["version"], "action": review.action})
        return run

    async def shutdown(self):
        for run_id, worker in list(self.workers.items()):
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
                run = self.store.get(run_id)
                if run["status"] in {"reading", "generating", "awaiting_login"}:
                    run.update(status="paused", error_code="PROCESS_INTERRUPTED")
                    self.store.save(run, "shutdown_paused")
        for run_id in list(self.sessions):
            await self.close_session(run_id)
