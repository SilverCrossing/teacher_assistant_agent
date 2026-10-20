from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Contract(BaseModel):
    # 所有边界数据拒绝未知字段与 NaN/Infinity，版本不兼容时明确失败。
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["1"] = "1"


class Criterion(Contract):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    max_score: float = Field(gt=0, le=1000)


class GradingTask(Contract):
    id: str
    source_site_id: str
    course_id: str
    assignment_id: str
    question_id: str
    title: str
    subject: str
    question: str
    rubric_version: str
    max_score: float = Field(gt=0, le=1000)
    criteria: list[Criterion] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_rubric(self):
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("DUPLICATE_CRITERION")
        if sum(Decimal(str(c.max_score)) for c in self.criteria) != Decimal(str(self.max_score)):
            raise ValueError("RUBRIC_TOTAL_MISMATCH")
        return self


class Evidence(Contract):
    """一次只读捕获的证据快照，身份字段与原文哈希必须一起保存。"""
    run_id: str
    source_site_id: str
    course_id: str
    assignment_id: str
    question_id: str
    submission_id: str = Field(min_length=1, max_length=100)
    captured_at: str = Field(default_factory=now)
    source_locator: str
    content_hash: str
    answer: str = Field(max_length=16000)
    quality: Literal["complete", "blank", "incomplete", "attachment"]
    # 直接标识仅在本地加密证据中保留，用于脱敏，不作为元数据发送给模型。
    private_identifiers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_hash(self):
        if sha256(self.answer.encode()).hexdigest() != self.content_hash:
            raise ValueError("CONTENT_HASH_MISMATCH")
        if self.quality == "complete" and not self.answer.strip():
            raise ValueError("EMPTY_COMPLETE_ANSWER")
        return self


class CriterionGrade(Contract):
    criterion_id: str
    score: float = Field(ge=0, le=1000)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(min_length=1, max_length=30)


class Suggestion(Contract):
    criteria: list[CriterionGrade]
    score_suggestion: float = Field(ge=0, le=1000)
    uncertainties: list[str] = Field(default_factory=list, max_length=30)
    review_required: Literal[True] = True


class ReviewInput(Contract):
    # 用教师看到的草稿版本防止旧页面覆盖新修改。
    expected_version: int = Field(ge=1)
    action: Literal["accepted", "edited", "rejected"]
    scores: dict[str, float] = Field(default_factory=dict)
    note: str = Field(default="", max_length=4000)


class CreateRun(Contract):
    task_id: str
