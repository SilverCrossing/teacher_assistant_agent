"""模型连接设置：普通参数落盘，密钥只进入系统凭据库。

页面可以提前配置、测试连接；真实答卷外发仍受管理员批准的端点与模型约束。
"""
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import keyring
from pydantic import Field, SecretStr, field_validator

from .config import CloudConfig, Settings
from .contracts import Contract
from .grading import DomainError

SERVICE = "teacher-grading-assistant"


def require_protected_keyring():
    """禁止 keyring 自动回退到明文文件，避免教师误以为密钥已经安全保存。"""
    backend = keyring.get_keyring()
    if not type(backend).__module__.startswith(("keyring.backends.Windows", "keyring.backends.macOS",
                                               "keyring.backends.SecretService")):
        raise DomainError("PROTECTED_KEYRING_REQUIRED")


class ModelConnection(Contract):
    endpoint: str = Field(default="", max_length=2000)
    model: str = Field(default="", max_length=200)
    enabled: bool = False

    @field_validator("endpoint")
    @classmethod
    def endpoint_is_safe(cls, value):
        value = value.strip()
        if not value:
            return value
        p = urlsplit(value)
        if (p.scheme != "https" or not p.hostname or p.username or p.password
                or p.query or p.fragment or p.hostname == "localhost" or p.hostname.endswith(".localhost")):
            raise ValueError("HTTPS_ENDPOINT_REQUIRED")
        try:
            address = ipaddress.ip_address(p.hostname)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError("PUBLIC_ENDPOINT_REQUIRED")
        return value

    @field_validator("model")
    @classmethod
    def trim_model(cls, value):
        return value.strip()


class ModelSettingsInput(ModelConnection):
    # SecretStr 防止异常 repr/调试信息意外显示密钥；响应从不返回此字段。
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), max_length=4000)
    clear_key: bool = False


class SavedConnection(ModelConnection):
    keyring_account: str = "model-api"


class ModelSettingsService:
    def __init__(self, base: Settings, directory: Path):
        self.base = base.model_copy(deep=True)
        self.path = directory / "model-connection.json"
        self.saved = SavedConnection(endpoint=base.cloud.endpoint, model=base.cloud.model,
                                     enabled=base.cloud.enabled, keyring_account=base.cloud.keyring_account)
        if self.path.exists():
            self.saved = SavedConnection.model_validate_json(self.path.read_text("utf-8"))

    def authorized(self, connection: ModelConnection) -> bool:
        """批准与具体端点/模型绑定，改地址后不能继承旧服务商的外发许可。"""
        approved = self.base.cloud
        return bool(self.base.site.enabled and approved.enabled and connection.endpoint == approved.endpoint
                    and connection.model == approved.model)

    def effective(self) -> CloudConfig:
        values = self.base.cloud.model_dump()
        values.update(endpoint=self.saved.endpoint, model=self.saved.model,
                      keyring_account=self.saved.keyring_account,
                      enabled=self.saved.enabled and self.authorized(self.saved))
        return CloudConfig.model_validate(values)

    def read_key(self) -> str:
        try:
            require_protected_keyring()
            return keyring.get_password(SERVICE, self.saved.keyring_account) or ""
        except DomainError:
            raise
        except Exception:
            raise DomainError("CREDENTIAL_STORE_UNAVAILABLE") from None

    def public(self) -> dict:
        try:
            has_key = bool(self.read_key())
            credentials_available = True
        except DomainError:
            has_key, credentials_available = False, False
        return {"schema_version": "1", "endpoint": self.saved.endpoint, "model": self.saved.model,
                "enabled": self.saved.enabled, "effective_enabled": self.effective().enabled,
                "approved": self.authorized(self.saved), "has_key": has_key,
                "credentials_available": credentials_available,
                "school_enabled": self.base.site.enabled}

    def save(self, value: ModelSettingsInput) -> dict:
        if value.enabled and not all([value.endpoint, value.model]):
            raise DomainError("MODEL_CONNECTION_INCOMPLETE")
        secret = value.api_key.get_secret_value().strip()
        if value.clear_key and secret:
            raise DomainError("KEY_ACTION_CONFLICT")
        candidate = SavedConnection(endpoint=value.endpoint, model=value.model, enabled=value.enabled,
                                    keyring_account=self.saved.keyring_account)
        # 轮换时先创建新凭据；普通配置写入失败时可回滚，不破坏原来的可用连接。
        new_account = None
        if secret or value.clear_key or value.endpoint != self.saved.endpoint:
            if secret or value.clear_key:
                require_protected_keyring()
            candidate.keyring_account = "ui-" + uuid4().hex
            if secret:
                new_account = candidate.keyring_account
                try:
                    keyring.set_password(SERVICE, new_account, secret)
                except Exception:
                    raise DomainError("CREDENTIAL_STORE_UNAVAILABLE") from None
        temporary = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(candidate.model_dump_json(indent=2), "utf-8")
            os.replace(temporary, self.path)
        except OSError:
            if new_account:
                try:
                    keyring.delete_password(SERVICE, new_account)
                except Exception:
                    pass
            raise DomainError("SETTINGS_SAVE_FAILED") from None
        previous = self.saved.keyring_account
        self.saved = candidate
        # 只清理本模块创建的旧密钥，维护者管理的凭据不在这里删除。
        if previous != candidate.keyring_account and previous.startswith("ui-"):
            try:
                keyring.delete_password(SERVICE, previous)
            except Exception:
                pass
        return self.public()

    async def test(self, value: ModelSettingsInput) -> dict:
        """连接测试仅发送固定测试句，不读取任务、答卷或浏览器数据。"""
        if not value.endpoint or not value.model or value.clear_key:
            raise DomainError("MODEL_CONNECTION_INCOMPLETE")
        if value.endpoint != self.saved.endpoint and not value.api_key.get_secret_value().strip():
            raise DomainError("MODEL_NEW_ENDPOINT_KEY_REQUIRED")
        secret = value.api_key.get_secret_value().strip() or self.read_key()
        if not secret:
            raise DomainError("MODEL_KEY_MISSING")
        body = {"model": value.model, "messages": [{"role": "user", "content": "连接测试，请只回复 OK。"}],
                "max_tokens": 16}
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", value.endpoint, json=body,
                                         headers={"Authorization": f"Bearer {secret}"}) as response:
                    if response.status_code in {401, 403}:
                        raise DomainError("MODEL_AUTH_FAILED")
                    if response.status_code == 429:
                        raise DomainError("MODEL_RATE_LIMITED")
                    if response.status_code != 200:
                        raise DomainError("MODEL_CONNECTION_FAILED")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 32000:
                            raise DomainError("MODEL_RESPONSE_INVALID")
            reply = json.loads(data)["choices"][0]["message"]["content"]
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError("empty reply")
        except (httpx.TimeoutException, httpx.NetworkError):
            raise DomainError("MODEL_CONNECTION_TIMEOUT") from None
        except (ValueError, KeyError, TypeError, IndexError):
            raise DomainError("MODEL_RESPONSE_INVALID") from None
        # 不回显服务商回复，避免测试接口成为密钥或任意内容回显通道。
        return {"ok": True, "message": "连接成功，模型已响应。测试未发送任何答卷。"}
