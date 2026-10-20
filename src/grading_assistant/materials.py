"""试卷资料在本机加密保存；原件与教师确认的评分内容分别保留。"""
import io
import json
import sqlite3
import zipfile
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

from pydantic import Field, model_validator
from pypdf import PdfReader

from .contracts import Contract, Criterion, now
from .grading import DomainError
from .storage import load_cipher

MAX_FILE = 15 * 1024 * 1024
MIME = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain", ".md": "text/plain", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class ExamInput(Contract):
    title: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=80)
    paper: str = Field(default="A卷", min_length=1, max_length=80)


class MaterialCriterion(Criterion):
    # 编辑中的空白允许暂存；确认版本时再要求内容完整。
    title: str = Field(max_length=200)
    description: str = Field(max_length=2000)


class Question(Contract):
    number: str = Field(max_length=80)
    prompt: str = Field(max_length=16000)
    answer: str = Field(max_length=16000)
    criteria: list[MaterialCriterion] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid_points(self):
        if len({c.id for c in self.criteria}) != len(self.criteria) or sum(c.max_score for c in self.criteria) > 1000:
            raise ValueError("INVALID_CRITERIA")
        return self


class ExamEdit(ExamInput):
    expected_version: int = Field(ge=1)
    questions: list[Question] = Field(default_factory=list, max_length=200)
    confirmed: bool = False

    @model_validator(mode="after")
    def distinct_questions(self):
        numbers = [q.number.strip() for q in self.questions if q.number.strip()]
        if len(set(numbers)) != len(numbers):
            raise ValueError("DUPLICATE_QUESTION")
        if self.confirmed and not self.questions:
            raise ValueError("NO_QUESTIONS")
        if self.confirmed and any(not q.number.strip() or not q.prompt.strip() or not q.answer.strip()
                                  for q in self.questions):
            raise ValueError("EMPTY_QUESTION")
        if self.confirmed and any(not c.title.strip() or not c.description.strip()
                                  for q in self.questions for c in q.criteria):
            raise ValueError("EMPTY_CRITERION")
        return self


def extract(name: str, raw: bytes):
    """只提取文档文字，不执行宏、外链或文档中的指令；扫描件明确转人工核对。"""
    suffix = Path(name).suffix.lower()
    if suffix not in MIME or not raw or len(raw) > MAX_FILE:
        raise DomainError("MATERIAL_FILE_INVALID")
    text, warning = "", ""
    try:
        if suffix in {".txt", ".md"}:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(i.file_size for i in entries) > 40 * 1024 * 1024:
                    raise ValueError("ARCHIVE_TOO_LARGE")
                xml = archive.read("word/document.xml")
                if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                    raise ValueError("XML_ENTITY")
                root = ElementTree.fromstring(xml)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                text = "\n".join("".join(p.itertext()) for p in root.findall(".//w:p", ns))
                warning = "Word 中的图片和公式对象可能未提取，请对照原件核对。"
        elif suffix == ".pdf":
            if not raw.startswith(b"%PDF-"):
                raise ValueError("NOT_PDF")
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or len(reader.pages) > 100:
                raise ValueError("PDF_LIMIT")
            parts = []
            for i, page in enumerate(reader.pages):
                content = page.get_contents()
                if content and len(content.get_data()) > 5 * 1024 * 1024:
                    raise ValueError("PDF_PAGE_TOO_LARGE")
                parts.append(f"—— 第 {i + 1} 页 ——\n{page.extract_text() or '（本页未提取到文字，请查看原件）'}")
            text = "\n".join(parts)
            warning = "扫描页需要人工录入；公式、上下标及文字顺序请对照原件核对。"
        else:
            if suffix == ".png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("NOT_PNG")
            if suffix in {".jpg", ".jpeg"} and not raw.startswith(b"\xff\xd8\xff"):
                raise ValueError("NOT_JPEG")
            warning = "图片已保存，尚未进行 OCR。请查看原图，在下方录入题干、答案和评分点。"
    except Exception:
        raise DomainError("MATERIAL_PARSE_FAILED") from None
    if len(text) > 100000:
        text = text[:100000]
        warning += " 提取结果已截取前 10 万字，请拆分文档以查看剩余内容。"
    return text, warning, MIME[suffix]


class MaterialLibrary:
    def __init__(self, directory: Path):
        self.directory = directory / "materials"

    def connect(self):
        # 即使处于演示模式，教师上传的真实资料也使用系统凭据库保护。
        cipher = load_cipher(self.directory, True)
        db = sqlite3.connect(self.directory / "school.db")
        db.execute("CREATE TABLE IF NOT EXISTS exams (id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, exam TEXT NOT NULL, payload BLOB NOT NULL)")
        return db, cipher

    def list(self):
        if not (self.directory / "school.db").exists():
            return []
        db, cipher = self.connect()
        try:
            exams = [json.loads(cipher.decrypt(row[0])) for row in db.execute("SELECT payload FROM exams")]
            return sorted(exams, key=lambda e: e["updated_at"], reverse=True)
        finally:
            db.close()

    def get(self, exam_id):
        for exam in self.list():
            if exam["id"] == exam_id:
                return exam
        raise DomainError("MATERIAL_NOT_FOUND")

    def write(self, db, cipher, exam):
        db.execute("INSERT OR REPLACE INTO exams VALUES (?, ?)",
                   (exam["id"], cipher.encrypt(json.dumps(exam, ensure_ascii=False).encode())))

    def create(self, body: ExamInput):
        exam = body.model_dump() | {"id": uuid4().hex, "version": 1, "confirmed": False,
                                   "questions": [], "files": [], "updated_at": now()}
        db, cipher = self.connect()
        try:
            with db:
                self.write(db, cipher, exam)
        finally:
            db.close()
        return exam

    def save(self, exam_id, body: ExamEdit):
        db, cipher = self.connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT payload FROM exams WHERE id=?", (exam_id,)).fetchone()
                if not row:
                    raise DomainError("MATERIAL_NOT_FOUND")
                exam = json.loads(cipher.decrypt(row[0]))
                if exam["version"] != body.expected_version:
                    raise DomainError("REVISION_CONFLICT")
                exam.update(body.model_dump(exclude={"expected_version"}))
                exam.update(version=exam["version"] + 1, updated_at=now())
                self.write(db, cipher, exam)
        finally:
            db.close()
        return exam

    def upload(self, exam_id, version, role, name, raw):
        self.get(exam_id)
        name = name.replace("\\", "/").split("/")[-1][:180]
        if role not in {"paper", "answer", "rubric"}:
            raise DomainError("MATERIAL_FILE_INVALID")
        text, warning, mime = extract(name, raw)
        file = {"id": uuid4().hex, "name": name, "role": role, "size": len(raw),
                "text": text, "warning": warning, "mime": mime}
        db, cipher = self.connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT payload FROM exams WHERE id=?", (exam_id,)).fetchone()
                if not row:
                    raise DomainError("MATERIAL_NOT_FOUND")
                exam = json.loads(cipher.decrypt(row[0]))
                if exam["version"] != version:
                    raise DomainError("REVISION_CONFLICT")
                if len(exam["files"]) >= 30:
                    raise DomainError("MATERIAL_FILE_LIMIT")
                db.execute("INSERT INTO files VALUES (?, ?, ?)", (file["id"], exam_id, cipher.encrypt(raw)))
                exam["files"].append(file)
                exam.update(version=version + 1, confirmed=False, updated_at=now())
                self.write(db, cipher, exam)
        finally:
            db.close()
        return exam

    def download(self, exam_id, file_id):
        exam = self.get(exam_id)
        meta = next((f for f in exam["files"] if f["id"] == file_id), None)
        if not meta:
            raise DomainError("MATERIAL_NOT_FOUND")
        db, cipher = self.connect()
        try:
            row = db.execute("SELECT payload FROM files WHERE id=? AND exam=?", (file_id, exam_id)).fetchone()
            if not row:
                raise DomainError("MATERIAL_NOT_FOUND")
            return meta, cipher.decrypt(row[0])
        finally:
            db.close()
