"""认证路由：登录、登出、会话状态。"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth import get_security, require_auth
from app.models import LoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(request: Request, body: LoginRequest, response: Response) -> dict:
    security = get_security(request)
    # 免认证模式（未设置访问码）下登录直接成功
    if security.auth_enabled and not security.verify_access_code(body.access_code):
        raise HTTPException(status_code=401, detail="访问码错误")
    security.set_session_cookie(response)
    return {"ok": True}


@router.post("/logout", dependencies=[Depends(require_auth)])
async def logout(response: Response) -> dict:
    response.delete_cookie("session", path="/")
    return {"ok": True}


@router.get("/me")
async def me(request: Request) -> dict:
    security = get_security(request)
    if not security.auth_enabled:
        return {"authenticated": True}
    token = request.cookies.get("session")
    return {"authenticated": bool(token and security.verify_token(token))}
