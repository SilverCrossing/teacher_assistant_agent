"""模拟批卷的本地闭环，与学校读取、云端调用及正式成绩完全分离。"""
from copy import deepcopy
from decimal import Decimal
import json
from uuid import uuid4

from pydantic import Field, model_validator

from .contracts import Contract, now
from .grading import DomainError
from .materials import MaterialLibrary

ANSWER = "CaCO₃ + 2H⁺ = Ca²⁺ + H₂O + CO₂↑"
QUESTION = {
    "number": "15(2)", "prompt": "写出碳酸钙与足量盐酸反应的离子方程式，注明气体符号。",
    "answer": ANSWER,
    "criteria": [
        {"id": "species", "title": "反应物与产物", "description": "CaCO₃ 保留化学式；产物为 Ca²⁺、H₂O、CO₂。", "max_score": 2},
        {"id": "balance", "title": "配平与电荷", "description": "H⁺ 系数为 2，原子数及电荷守恒。", "max_score": 1},
        {"id": "gas", "title": "气体符号", "description": "CO₂ 后注明 ↑。", "max_score": 1},
    ],
}
SAMPLES = [
    ("SIM-001", ANSWER, "清晰作答"),
    ("SIM-002", "CaCO₃ + 2H⁺ = Ca²⁺ + H₂O + CO₂", "漏写气体符号"),
    ("SIM-003", "CaCO₃ + H⁺ = Ca⁺ + H₂O + CO₂↑", "系数与电荷待核对"),
    ("SIM-004", "CaCO₃ + [涂改不清] = Ca²⁺ + H₂O + CO₂↑", "涂改示例，需教师判读"),
    ("SIM-005", "", "空白答卷"),
]


class SimulationStart(Contract):
    material_id: str | None = None
    material_version: int | None = None
    question_number: str | None = None
    mapping_confirmed: bool = False

    @model_validator(mode="after")
    def complete_mapping(self):
        supplied = [self.material_id is not None, self.material_version is not None, self.question_number is not None]
        if any(supplied) and (not all(supplied) or not self.mapping_confirmed):
            raise ValueError("MAPPING_CONFIRMATION_REQUIRED")
        return self


class SimulationDraft(Contract):
    expected_version: int = Field(ge=1)
    transcript: str = Field(max_length=16000)
    transcription_confirmed: bool


class SimulationReview(Contract):
    expected_version: int = Field(ge=1)
    scores: dict[str, float]
    note: str = Field(default="", max_length=4000)


class SimulationService:
    def __init__(self, materials: MaterialLibrary):
        self.materials = materials

    def connection(self):
        db, cipher = self.materials.connect()
        db.execute("CREATE TABLE IF NOT EXISTS simulations (id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        return db, cipher

    def write(self, db, cipher, session):
        db.execute("INSERT OR REPLACE INTO simulations VALUES (?, ?)",
                   (session["id"], cipher.encrypt(json.dumps(session, ensure_ascii=False, allow_nan=False).encode())))

    def start(self, body: SimulationStart):
        question = deepcopy(QUESTION)
        source = {"title": "高一化学 · 模拟月考", "paper": "A卷", "version": 1, "id": "builtin-chemistry"}
        if body.material_id:
            exam = self.materials.get(body.material_id)
            if not exam["confirmed"] or exam["version"] != body.material_version:
                raise DomainError("MATERIAL_NOT_CONFIRMED")
            question = next((q for q in exam["questions"] if q["number"] == body.question_number), None)
            if question is None:
                raise DomainError("MATERIAL_MAPPING_INVALID")
            source = {k: exam[k] for k in ("id", "title", "paper", "version")}
        session = {"id": uuid4().hex, "version": 1, "created_at": now(), "source": source,
                   "question": question, "builtin": not body.material_id,
                   "cards": [{"id": sid, "image_text": text, "label": label,
                              "question_number": question["number"], "status": "unread",
                              "draft": None, "review": None, "history": []}
                             for sid, text, label in SAMPLES]}
        db, cipher = self.connection()
        try:
            with db:
                self.write(db, cipher, session)
        finally:
            db.close()
        return session

    def list(self):
        # 未开始模拟时不触发系统密钥创建。
        if not (self.materials.directory / "school.db").exists():
            return []
        db, cipher = self.connection()
        try:
            sessions = [json.loads(cipher.decrypt(row[0])) for row in db.execute("SELECT payload FROM simulations")]
            return sorted([{"id": s["id"], "source": s["source"], "created_at": s["created_at"],
                            "reviewed": sum(c["status"] == "reviewed" for c in s["cards"])} for s in sessions],
                          key=lambda s: s["created_at"], reverse=True)
        finally:
            db.close()

    def read(self, db, cipher, session_id):
        row = db.execute("SELECT payload FROM simulations WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise DomainError("SIMULATION_NOT_FOUND")
        return json.loads(cipher.decrypt(row[0]))

    def get(self, session_id):
        db, cipher = self.connection()
        try:
            return self.read(db, cipher, session_id)
        finally:
            db.close()

    def update(self, session_id, card_id, body, review=False):
        db, cipher = self.connection()
        try:
            with db:
                # 版本与写入在同一事务检查，过期页面不得覆盖另一份评分。
                db.execute("BEGIN IMMEDIATE")
                session = self.read(db, cipher, session_id)
                if body.expected_version != session["version"]:
                    raise DomainError("REVISION_CONFLICT")
                card = next((c for c in session["cards"] if c["id"] == card_id), None)
                if card is None:
                    raise DomainError("SIMULATION_NOT_FOUND")
                if review:
                    if card["draft"] is None:
                        raise DomainError("SIMULATION_TRANSCRIPT_REQUIRED")
                    rules = {c["id"]: c for c in session["question"]["criteria"]}
                    if set(body.scores) != set(rules) or any(
                        score < 0 or score > rules[key]["max_score"] for key, score in body.scores.items()
                    ):
                        raise DomainError("SCORE_OUT_OF_RANGE")
                    if card["review"]:
                        card["history"].append(deepcopy(card["review"]))
                    card["review"] = {"scores": body.scores, "total": float(sum(Decimal(str(s)) for s in body.scores.values())),
                                      "note": body.note, "created_at": now(),
                                      "transcript": card["draft"]["transcript"], "source": session["source"]}
                    card["status"] = "reviewed"
                else:
                    if not body.transcription_confirmed:
                        raise DomainError("SIMULATION_TRANSCRIPT_REQUIRED")
                    # 演示仅匹配明确的合成样例，不能拿字符串规则冒充通用 AI 评分。
                    key = "".join(body.transcript.split())
                    known = {
                        "".join(ANSWER.split()): {"species": 2, "balance": 1, "gas": 1},
                        "".join(SAMPLES[1][1].split()): {"species": 2, "balance": 1, "gas": 0},
                    }
                    scores = known.get(key) if session["builtin"] else None
                    if card["review"]:
                        card["history"].append(deepcopy(card["review"]))
                    card["review"] = None
                    card["draft"] = {"transcript": body.transcript, "scores": scores,
                                     "reason": "命中内置演示规则，请逐项核对。" if scores is not None else
                                               "此作答不适用内置规则，请依据右侧答案逐项人工给分。",
                                     "created_at": now()}
                    card["status"] = "draft" if scores is not None else "manual"
                session["version"] += 1
                self.write(db, cipher, session)
        finally:
            db.close()
        return session
