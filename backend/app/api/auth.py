"""认证路由：登录、登出、会话状态。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth import get_security, require_auth
from app.models import LoginRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(request: Request, body: LoginRequest, response: Response) -> dict:
    security = get_security(request)
    client = (request.client.host if request.client else "?")
    # 免认证模式（未设置访问码）下登录直接成功
    if security.auth_enabled and not security.verify_access_code(body.access_code):
        logger.warning("Login failed: wrong access code (client %s)", client)
        raise HTTPException(status_code=401, detail="访问码错误")
    security.set_session_cookie(response)
    logger.info("Login success (client %s)", client)
    return {"ok": True}


@router.post("/logout", dependencies=[Depends(require_auth)])
async def logout(request: Request, response: Response) -> dict:
    client = (request.client.host if request.client else "?")
    response.delete_cookie("session", path="/")
    logger.info("Logout (client %s)", client)
    return {"ok": True}


@router.get("/me")
async def me(request: Request) -> dict:
    security = get_security(request)
    if not security.auth_enabled:
        return {"authenticated": True}
    token = request.cookies.get("session")
    return {"authenticated": bool(token and security.verify_token(token))}
