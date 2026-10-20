from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import keyring
from cryptography.fernet import Fernet

from .contracts import now
from .grading import DomainError


def load_cipher(directory: Path, real: bool) -> Fernet:
    directory.mkdir(parents=True, exist_ok=True)
    if real:
        # 真实模式密钥由系统凭据库保护，不允许回退到明文文件。
        backend = keyring.get_keyring()
        if not type(backend).__module__.startswith(("keyring.backends.Windows", "keyring.backends.macOS",
                                                   "keyring.backends.SecretService")):
            raise DomainError("PROTECTED_KEYRING_REQUIRED")
        try:
            key = keyring.get_password("teacher-grading-assistant", "draft-encryption")
            if not key:
                if (directory / "school.db").exists():
                    raise DomainError("EXISTING_DATABASE_KEY_MISSING")
                key = Fernet.generate_key().decode()
                keyring.set_password("teacher-grading-assistant", "draft-encryption", key)
        except DomainError:
            raise
        except Exception:
            # 沙箱或非交互登录会话可能无法访问 Windows 凭据库。
            # 明确提示启动方式，绝不为了继续上传而降级保存明文密钥。
            raise DomainError("CREDENTIAL_STORE_UNAVAILABLE") from None
    else:
        # 此文件密钥仅供合成演示使用，真实学校数据使用独立数据库和系统密钥。
        path = directory / "synthetic-only.key"
        if not path.exists():
            path.write_bytes(Fernet.generate_key())
        key = path.read_bytes()
    return Fernet(key)


class Store:
    """敏感载荷加密存储；草稿和最小审计在同一事务提交，版本号防止陈旧覆盖。"""
    def __init__(self, path: Path, cipher: Fernet):
        self.cipher = cipher
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA secure_delete=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise DomainError("DATABASE_VERSION_UNSUPPORTED")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, created_at TEXT NOT NULL, payload BLOB NOT NULL);
            PRAGMA user_version=1;
        """)

    def encode(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

    def decode(self, value):
        return json.loads(self.cipher.decrypt(value))

    def get(self, run_id: str) -> dict:
        row = self.db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise DomainError("RUN_NOT_FOUND")
        return self.decode(row[0])

    def list(self) -> list[dict]:
        return [self.decode(row[0]) for row in self.db.execute("SELECT payload FROM runs ORDER BY updated_at DESC")]

    def save(self, run: dict, event: str, detail: dict | None = None):
        # 只有事务全部成功，才更新调用方内存中的版本；失败时保留原有记录。
        old = self.db.execute("SELECT payload FROM runs WHERE id=?", (run["id"],)).fetchone()
        if old and self.decode(old[0])["revision"] != run["revision"]:
            raise DomainError("REVISION_CONFLICT")
        updated = {**run, "revision": run["revision"] + 1, "updated_at": now()}
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET "
                            "updated_at=excluded.updated_at,payload=excluded.payload",
                            (run["id"], updated["updated_at"], self.encode(updated)))
            self.db.execute("INSERT INTO audit(run_id,created_at,payload) VALUES (?,?,?)",
                            (run["id"], now(), self.encode({"event": event, **(detail or {})})))
        run.update(updated)

    def audit(self, run_id: str) -> list[dict]:
        return [{"created_at": row[0], **self.decode(row[1])} for row in self.db.execute(
            "SELECT created_at,payload FROM audit WHERE run_id=? ORDER BY id", (run_id,))]

    def purge(self, days: int):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.db:
            self.db.execute("DELETE FROM audit WHERE run_id IN (SELECT id FROM runs WHERE updated_at < ?)", (cutoff,))
            self.db.execute("DELETE FROM runs WHERE updated_at < ?", (cutoff,))
            self.db.execute("DELETE FROM audit WHERE created_at < ?", (cutoff,))

    def recover(self):
        # 重启只标记暂停，不自动重放云请求，避免不知情的重复外发/计费。
        for run in self.list():
            if run["status"] in {"reading", "generating", "awaiting_login"}:
                run.update(status="paused", error_code="PROCESS_INTERRUPTED")
                self.save(run, "recovered_after_restart")

    def close(self):
        self.db.close()
