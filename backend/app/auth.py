"""认证：argon2 访问码哈希 + JWT + HttpOnly Cookie。明文访问码不落盘。"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, status

from app.config import Settings
from app.storage import SecretsStore

logger = logging.getLogger(__name__)

COOKIE_NAME = "session"
COOKIE_PATH = "/"
JWT_ALGORITHM = "HS256"


class Security:
    def __init__(self, secrets_store: SecretsStore, settings: Settings) -> None:
        self.secrets = secrets_store
        self.settings = settings
        self._hasher = PasswordHasher()
        # 访问码以环境变量为权威；留空 = 免认证模式（直接进入面板）
        self.auth_enabled = bool(settings.access_code)
        self._ensure()

    def _ensure(self) -> None:
        # JWT secret：环境变量优先，否则生成并持久化
        if self.settings.jwt_secret:
            self.secrets.jwt_secret = self.settings.jwt_secret
        if not self.secrets.jwt_secret:
            self.secrets.jwt_secret = secrets.token_urlsafe(32)
        # 访问码：环境变量为权威，每次运行以此为准；留空不生成随机码
        code = self.settings.access_code
        if code:
            if not self._verify_code(code):
                self.secrets.access_code_hash = self._hasher.hash(code)
                logger.info("Access code updated from env and stored as hash")
        self.secrets.save()

    def _verify_code(self, code: str) -> bool:
        try:
            return self._hasher.verify(self.secrets.access_code_hash, code)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def verify_access_code(self, code: str) -> bool:
        if not self.secrets.access_code_hash:
            return False
        try:
            ok = self._hasher.verify(self.secrets.access_code_hash, code)
            if ok:
                # 重新哈希以应对 argon2 参数升级
                self._hasher.check_needs_rehash(self.secrets.access_code_hash)
            return ok
        except (VerifyMismatchError, InvalidHashError):
            return False

    def create_token(self) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "admin",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self.settings.jwt_expire_minutes)).timestamp()),
        }
        return jwt.encode(payload, self.secrets.jwt_secret, algorithm=JWT_ALGORITHM)

    def verify_token(self, token: str) -> bool:
        try:
            jwt.decode(token, self.secrets.jwt_secret, algorithms=[JWT_ALGORITHM])
            return True
        except jwt.PyJWTError:
            return False

    def set_session_cookie(self, response: Any) -> None:
        response.set_cookie(
            COOKIE_NAME,
            self.create_token(),
            max_age=self.settings.jwt_expire_minutes * 60,
            httponly=True,
            secure=self.settings.cookie_secure,
            samesite="lax",
            path=COOKIE_PATH,
        )

    def clear_session_cookie(self, response: Any) -> None:
        response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)


def get_security(request: Request) -> Security:
    return request.app.state.security


def require_auth(request: Request) -> None:
    """JWT Cookie 或 API Token（Authorization: Bearer）校验 + 写方法要求 JSON（CSRF 纵深防御）。

    未设置访问码时为免认证模式，直接放行。API Token 存于 secrets.json 的 api_token，
    生成新 token 后旧 token 立即失效。
    """
    security = get_security(request)
    if not security.auth_enabled:
        return

    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        api_token = request.app.state.secrets_store.api_token
        authed = bool(api_token) and secrets.compare_digest(auth_header[7:], api_token)
    else:
        token = request.cookies.get(COOKIE_NAME)
        authed = bool(token) and security.verify_token(token)
    if not authed:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未授权访问")

    # 带 body 的写方法要求 JSON 内容类型（CSRF 纵深防御）。DELETE 无 body，
    # 且跨源无法通过表单/预检触发，天然安全，不受此限。
    if request.method in ("POST", "PUT", "PATCH"):
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("application/json"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="需 application/json",
            )
