import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .contracts import Contract, GradingTask


class SiteConfig(Contract):
    """学校授权范围由维护者提供，教师页面不能修改站点白名单。"""
    enabled: bool = False
    approval_reference: str = ""
    teacher_id: str = ""
    login_url: str = ""
    login_post_urls: list[str] = Field(default_factory=list)
    # 仅接受核验过的精确 URL，不使用模型生成的链接或选择器。
    read_urls: list[str] = Field(default_factory=list)
    page_urls: list[str] = Field(default_factory=list)
    expected_submissions: int = Field(default=0, ge=0, le=10000)
    adapter_version: str = "snapshot-v1"
    task: GradingTask | None = None


class CloudConfig(Contract):
    enabled: bool = False
    approval_reference: str = ""
    endpoint: str = ""
    model: str = ""
    region: str = ""
    retention_terms: str = ""
    training_terms: str = ""
    keyring_account: str = "model-api"
    approved_fields: list[str] = Field(default_factory=list)
    max_requests_per_run: int = Field(default=100, ge=1, le=10000)


class Settings(Contract):
    site: SiteConfig = Field(default_factory=SiteConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    retention_days: int = Field(default=7, ge=1, le=365)
    retention_approval: str = ""
    read_interval_seconds: float = Field(default=2, ge=0.1, le=120)

    @model_validator(mode="after")
    def gates(self):
        # 配置能解析不等于已获授权；启用真实能力时必须同时核验审批与任务信息。
        if self.site.enabled:
            s = self.site
            if not all([s.approval_reference, s.teacher_id, s.login_url,
                        s.page_urls, s.task, s.expected_submissions, self.retention_approval]):
                raise ValueError("SITE_APPROVAL_INCOMPLETE")
            if s.task.id == "demo-biology" or s.task.source_site_id == "synthetic":
                raise ValueError("REAL_TASK_CANNOT_USE_DEMO_IDENTITY")
            if not set(s.page_urls).issubset(s.read_urls) or s.login_url not in s.read_urls:
                raise ValueError("PAGE_NOT_ALLOWLISTED")
            for url in s.read_urls + s.login_post_urls:
                p = urlsplit(url)
                if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
                    raise ValueError("SITE_URL_MUST_BE_HTTPS")
        if self.cloud.enabled:
            c = self.cloud
            required = {"question", "rubric", "answer_lines", "anonymous_ref"}
            p = urlsplit(c.endpoint)
            if not all([self.site.enabled, c.approval_reference, c.model, c.region,
                        c.retention_terms, c.training_terms]) or set(c.approved_fields) != required:
                raise ValueError("CLOUD_APPROVAL_INCOMPLETE")
            if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
                raise ValueError("CLOUD_ENDPOINT_INVALID")
        return self


def load_settings() -> Settings:
    # JSON 不包含密钥；前端保存的模型连接在应用入口单独合并。
    path = os.environ.get("GRADING_CONFIG")
    return Settings.model_validate(json.loads(Path(path).read_text("utf-8"))) if path else Settings()


def data_dir() -> Path:
    if os.environ.get("GRADING_DATA_DIR"):
        return Path(os.environ["GRADING_DATA_DIR"])
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "TeacherGradingAssistant"
