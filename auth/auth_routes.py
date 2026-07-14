# backend/auth/auth_routes.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

try:
    from pydantic import BaseModel, Field
except Exception:
    BaseModel = object
    Field = None

import config
from auth import auth_service


# ============================================================
# 1) ROUTER
# ============================================================

"""
ไฟล์นี้เป็น API route เฉพาะระบบ Login/Auth ของ TIPX

ออกแบบให้ include จาก api_routes.py แบบนี้:

    from auth.auth_routes import router as auth_router
    router.include_router(auth_router)

เพราะ api_routes.py มี main router prefix="/api" อยู่แล้ว
ดังนั้น auth_routes.py ต้องใช้ prefix="/auth"

Final path:
    POST /api/auth/login
    GET  /api/auth/me
    POST /api/auth/logout
    GET  /api/auth/status
    GET  /api/auth/contract

ระบบนี้รองรับ fixed users เท่านั้น:
    admin
    user
    viewer

ไม่ทำ:
    user registration
    admin create user
    forgot password
    refresh token
    session table
    OAuth
    API key
"""

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

auth_router = router


# ============================================================
# 2) REQUEST MODELS
# ============================================================

if Field is not None:

    class LoginRequest(BaseModel):
        username: str = Field(..., min_length=1, max_length=80)
        password: str = Field(..., min_length=1, max_length=512)
        remember: bool = False


    class LogoutRequest(BaseModel):
        reason: Optional[str] = ""
        clear_client_token: bool = True


else:

    class LoginRequest:  # type: ignore
        def __init__(self, username: str = "", password: str = "", remember: bool = False) -> None:
            self.username = username
            self.password = password
            self.remember = remember


    class LogoutRequest:  # type: ignore
        def __init__(self, reason: str = "", clear_client_token: bool = True) -> None:
            self.reason = reason
            self.clear_client_token = clear_client_token


# ============================================================
# 3) RESPONSE HELPERS
# ============================================================

def json_safe(value: Any) -> Any:
    try:
        return auth_service.json_safe(value)
    except Exception:
        return value


def get_payload_status_code(payload: Dict[str, Any], default_success: int = 200, default_error: int = 400) -> int:
    if not isinstance(payload, dict):
        return default_error

    meta = payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}
    status_code = meta.get("status_code")

    try:
        if status_code:
            return int(status_code)
    except Exception:
        pass

    if payload.get("success") is False:
        return default_error

    return default_success


def auth_json_response(
    payload: Dict[str, Any],
    default_success: int = 200,
    default_error: int = 400,
) -> JSONResponse:
    status_code = get_payload_status_code(
        payload=payload,
        default_success=default_success,
        default_error=default_error,
    )

    return JSONResponse(
        status_code=status_code,
        content=json_safe(payload),
    )


def success_payload(
    data: Optional[Any] = None,
    message: str = "OK",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return auth_service.make_auth_response(
        success=True,
        message=message,
        data=data if data is not None else {},
        meta=meta or {},
    )


def error_payload(
    message: str,
    error_type: str = "AuthRouteError",
    status_code: int = 400,
    data: Optional[Any] = None,
    field: str = "",
) -> Dict[str, Any]:
    return auth_service.make_auth_error(
        message=message,
        error_type=error_type,
        status_code=status_code,
        data=data if data is not None else {},
        field=field,
    )


def exception_payload(exc: Exception, message: str = "Auth route failed.", status_code: int = 500) -> Dict[str, Any]:
    return auth_service.make_auth_response(
        success=False,
        message=message,
        data={},
        meta={
            "status_code": status_code,
            "error_type": exc.__class__.__name__,
        },
        errors=[
            {
                "type": exc.__class__.__name__,
                "message": str(exc),
                "traceback": traceback.format_exc() if getattr(config, "DEBUG", False) else "",
            }
        ],
    )


# ============================================================
# 4) REQUEST HELPERS
# ============================================================

def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    real_ip = request.headers.get("x-real-ip", "")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host or ""

    return ""


def get_user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")


def get_request_id(request: Request) -> str:
    return (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or ""
    )


def get_authorization_header(
    authorization: Optional[str],
    request: Request,
) -> str:
    if authorization:
        return authorization

    return request.headers.get(
        getattr(config, "AUTH_HEADER_NAME", "Authorization"),
        "",
    )


async def read_json_body(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()

        if isinstance(payload, dict):
            return payload

        return {}

    except Exception:
        return {}


async def read_form_body(request: Request) -> Dict[str, Any]:
    try:
        form = await request.form()
        return dict(form)

    except Exception:
        return {}


async def extract_login_payload(request: Request, body: Optional[LoginRequest]) -> Dict[str, Any]:
    if body is not None:
        username = getattr(body, "username", "")
        password = getattr(body, "password", "")
        remember = getattr(body, "remember", False)

        if username or password:
            return {
                "username": username,
                "password": password,
                "remember": remember,
                "source": "json_model",
            }

    json_body = await read_json_body(request)

    if json_body:
        return {
            "username": json_body.get("username") or json_body.get("user") or "",
            "password": json_body.get("password") or "",
            "remember": json_body.get("remember", False),
            "source": "json_body",
        }

    form_body = await read_form_body(request)

    if form_body:
        return {
            "username": form_body.get("username") or form_body.get("user") or "",
            "password": form_body.get("password") or "",
            "remember": form_body.get("remember", False),
            "source": "form_body",
        }

    return {
        "username": "",
        "password": "",
        "remember": False,
        "source": "empty",
    }


def get_state_user(request: Request) -> Optional[Dict[str, Any]]:
    try:
        user = getattr(request.state, "user", None)

        if isinstance(user, dict) and user:
            return user

    except Exception:
        pass

    return None


def get_authenticated_user_from_request(
    request: Request,
    authorization: Optional[str] = None,
    verify_db_active: bool = False,
) -> Dict[str, Any]:
    state_user = get_state_user(request)

    if state_user:
        return {
            "authenticated": True,
            "reason": "request_state_user",
            "user": state_user,
        }

    header = get_authorization_header(authorization, request)

    return auth_service.get_user_from_authorization_header(
        authorization_header=header,
        verify_db_active=verify_db_active,
    )


def require_authenticated_user(
    request: Request,
    authorization: Optional[str] = None,
    verify_db_active: bool = False,
) -> Dict[str, Any]:
    result = get_authenticated_user_from_request(
        request=request,
        authorization=authorization,
        verify_db_active=verify_db_active,
    )

    if result.get("authenticated"):
        return {
            "allowed": True,
            "user": result.get("user") or {},
            "reason": result.get("reason"),
            "status_code": 200,
        }

    return {
        "allowed": False,
        "user": None,
        "reason": result.get("reason", "not_authenticated"),
        "status_code": 401,
    }


def require_role_for_route(
    request: Request,
    authorization: Optional[str],
    allowed_roles: List[str],
    verify_db_active: bool = False,
) -> Dict[str, Any]:
    auth_result = require_authenticated_user(
        request=request,
        authorization=authorization,
        verify_db_active=verify_db_active,
    )

    if not auth_result.get("allowed"):
        return auth_result

    user = auth_result.get("user") or {}
    role_result = auth_service.require_roles(
        user=user,
        allowed_roles=allowed_roles,
    )

    if role_result.get("allowed"):
        return {
            "allowed": True,
            "user": user,
            "reason": "ok",
            "status_code": 200,
        }

    return {
        "allowed": False,
        "user": user,
        "reason": "role_forbidden",
        "status_code": 403,
        "allowed_roles": allowed_roles,
    }


def forbidden_response(reason: str = "forbidden", status_code: int = 403) -> JSONResponse:
    return auth_json_response(
        error_payload(
            message="Permission denied.",
            error_type="Forbidden",
            status_code=status_code,
            data={
                "reason": reason,
            },
        ),
        default_error=status_code,
    )


# ============================================================
# 5) STARTUP / STORAGE INITIALIZATION GUARD
# ============================================================

_AUTH_STORAGE_INIT_DONE: bool = False
_AUTH_STORAGE_INIT_RESULT: Dict[str, Any] = {}


def ensure_auth_storage_initialized(force: bool = False) -> Dict[str, Any]:
    global _AUTH_STORAGE_INIT_DONE
    global _AUTH_STORAGE_INIT_RESULT

    if not getattr(config, "AUTH_ENABLED", True):
        return success_payload(
            data={
                "enabled": False,
                "initialized": False,
            },
            message="Auth disabled.",
        )

    if _AUTH_STORAGE_INIT_DONE and not force:
        return _AUTH_STORAGE_INIT_RESULT

    result = auth_service.startup_auth()

    _AUTH_STORAGE_INIT_RESULT = result
    _AUTH_STORAGE_INIT_DONE = bool(result.get("success"))

    return result


# ============================================================
# 6) PUBLIC ROUTES
# ============================================================

@router.get("/status")
async def auth_status(
    init: bool = Query(default=False, description="Initialize auth DB/table/user seed before returning status."),
) -> JSONResponse:
    """
    Public auth status endpoint

    ใช้สำหรับ:
    - frontend ตรวจว่า auth เปิดอยู่ไหม
    - backend ตรวจ MySQL auth config
    - ไม่คืน password / secret / hash
    """

    try:
        if init:
            ensure_auth_storage_initialized(force=False)

        payload = auth_service.get_auth_status()

        return auth_json_response(
            payload,
            default_success=200,
            default_error=500,
        )

    except Exception as exc:
        auth_service.safe_error_log("auth_status route failed", exc)
        return auth_json_response(
            exception_payload(exc, "Auth status failed.", status_code=500),
            default_error=500,
        )


@router.get("/contract")
async def auth_contract() -> JSONResponse:
    """
    Public frontend auth contract

    ใช้ให้ frontend รู้:
    - login endpoint
    - me endpoint
    - logout endpoint
    - token header
    - role route rules
    """

    try:
        payload = success_payload(
            data=auth_service.get_frontend_auth_contract(),
            message="Auth frontend contract loaded.",
        )

        return auth_json_response(payload)

    except Exception as exc:
        auth_service.safe_error_log("auth_contract route failed", exc)
        return auth_json_response(
            exception_payload(exc, "Auth contract failed.", status_code=500),
            default_error=500,
        )


@router.post("/login")
async def login(
    request: Request,
    body: Optional[LoginRequest] = None,
) -> JSONResponse:
    """
    Login ด้วย fixed username/password

    Body:
        {
          "username": "admin",
          "password": "..."
        }

    Response:
        {
          "access_token": "...",
          "token_type": "Bearer",
          "expires_at": "...",
          "user": {
            "username": "...",
            "role": "admin|user|viewer"
          }
        }
    """

    login_payload = await extract_login_payload(request, body)
    username = auth_service.clean_text(login_payload.get("username"))
    password = auth_service.clean_text(login_payload.get("password"))

    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    request_id = get_request_id(request)

    try:
        ensure_auth_storage_initialized(force=False)

        result = auth_service.authenticate_user(
            username=username,
            password=password,
        )

        status_code = get_payload_status_code(
            result,
            default_success=200,
            default_error=401,
        )

        user = {}

        if result.get("success"):
            user = (
                result.get("data", {}).get("user", {})
                if isinstance(result.get("data"), dict)
                else {}
            )

        auth_service.write_login_audit(
            username=username,
            success=bool(result.get("success")),
            role=auth_service.clean_text(user.get("role")),
            method=request.method,
            path=str(request.url.path),
            status_code=status_code,
            ip_address=client_ip,
            user_agent=user_agent,
            request_id=request_id,
            reason=result.get("message", ""),
        )

        return auth_json_response(
            result,
            default_success=200,
            default_error=status_code,
        )

    except Exception as exc:
        auth_service.safe_error_log("login route failed", exc)

        auth_service.write_login_audit(
            username=username,
            success=False,
            role="",
            method=request.method,
            path=str(request.url.path),
            status_code=500,
            ip_address=client_ip,
            user_agent=user_agent,
            request_id=request_id,
            reason=str(exc),
        )

        return auth_json_response(
            exception_payload(exc, "Login failed.", status_code=500),
            default_error=500,
        )


# ============================================================
# 7) AUTHENTICATED ROUTES
# ============================================================

@router.get("/me")
async def me(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    verify_db_active: bool = Query(default=False),
) -> JSONResponse:
    """
    คืน current user จาก JWT

    ใช้โดย frontend route guard:
    - ตรวจ token ยัง valid ไหม
    - อ่าน role
    - อ่าน frontend contract
    """

    try:
        auth_result = get_authenticated_user_from_request(
            request=request,
            authorization=authorization,
            verify_db_active=verify_db_active,
        )

        if not auth_result.get("authenticated"):
            return auth_json_response(
                error_payload(
                    message="Not authenticated.",
                    error_type="NotAuthenticated",
                    status_code=401,
                    data={
                        "authenticated": False,
                        "reason": auth_result.get("reason"),
                    },
                ),
                default_error=401,
            )

        user = auth_result.get("user") or {}

        payload = success_payload(
            data={
                "authenticated": True,
                "user": user,
                "role": user.get("role"),
                "username": user.get("username"),
                "frontend_contract": auth_service.get_frontend_auth_contract(),
            },
            message="Current user loaded.",
            meta={
                "reason": auth_result.get("reason"),
            },
        )

        return auth_json_response(payload)

    except Exception as exc:
        auth_service.safe_error_log("me route failed", exc)
        return auth_json_response(
            exception_payload(exc, "Current user failed.", status_code=500),
            default_error=500,
        )


@router.post("/logout")
async def logout(
    request: Request,
    body: Optional[LogoutRequest] = None,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    """
    Logout แบบ stateless JWT

    หมายเหตุ:
    - ไม่มี session table
    - ไม่มี token blacklist
    - backend แค่เขียน audit log
    - frontend ต้องลบ token เอง
    """

    try:
        auth_result = get_authenticated_user_from_request(
            request=request,
            authorization=authorization,
            verify_db_active=False,
        )

        user = auth_result.get("user") if auth_result.get("authenticated") else None

        result = auth_service.logout_user(
            user=user,
            method=request.method,
            path=str(request.url.path),
            status_code=200,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            request_id=get_request_id(request),
        )

        if isinstance(result.get("data"), dict):
            result["data"]["client_should_clear_token"] = True
            result["data"]["reason"] = getattr(body, "reason", "") if body else ""

        return auth_json_response(result)

    except Exception as exc:
        auth_service.safe_error_log("logout route failed", exc)
        return auth_json_response(
            exception_payload(exc, "Logout failed.", status_code=500),
            default_error=500,
        )


# ============================================================
# 8) ADMIN AUTH MANAGEMENT ROUTES
# ============================================================

@router.post("/init")
async def init_auth(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    force: bool = Query(default=False),
) -> JSONResponse:
    """
    Initialize auth database/tables/fixed users

    ใช้เมื่อ:
    - เพิ่งสร้าง MySQL database ใหม่
    - ต้องการให้ระบบ create table + seed users

    ต้องเป็น admin ถ้ามี token แล้ว
    ถ้ายังไม่มี table/user เลย ควรเรียก startup ผ่าน app.py มากกว่าเปิด endpoint นี้เป็น public
    """

    try:
        auth_result = require_role_for_route(
            request=request,
            authorization=authorization,
            allowed_roles=["admin"],
            verify_db_active=False,
        )

        if not auth_result.get("allowed"):
            return forbidden_response(
                reason=auth_result.get("reason", "forbidden"),
                status_code=int(auth_result.get("status_code", 403)),
            )

        result = ensure_auth_storage_initialized(force=force)

        auth_service.write_audit_log(
            action="auth_init",
            user=auth_result.get("user"),
            method=request.method,
            path=str(request.url.path),
            status_code=200 if result.get("success") else 500,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            request_id=get_request_id(request),
            details={
                "force": force,
                "success": bool(result.get("success")),
            },
        )

        return auth_json_response(
            result,
            default_success=200,
            default_error=500,
        )

    except Exception as exc:
        auth_service.safe_error_log("init_auth route failed", exc)
        return auth_json_response(
            exception_payload(exc, "Auth init failed.", status_code=500),
            default_error=500,
        )


@router.get("/users")
async def users(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    """
    Admin-only: list fixed auth users

    ไม่คืน password_hash
    ไม่สร้าง user ใหม่
    ไม่แก้ password
    """

    try:
        auth_result = require_role_for_route(
            request=request,
            authorization=authorization,
            allowed_roles=["admin"],
            verify_db_active=False,
        )

        if not auth_result.get("allowed"):
            return forbidden_response(
                reason=auth_result.get("reason", "forbidden"),
                status_code=int(auth_result.get("status_code", 403)),
            )

        result = auth_service.list_auth_users()

        auth_service.write_audit_log(
            action="auth_users_view",
            user=auth_result.get("user"),
            method=request.method,
            path=str(request.url.path),
            status_code=200 if result.get("success") else 500,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            request_id=get_request_id(request),
        )

        return auth_json_response(
            result,
            default_success=200,
            default_error=500,
        )

    except Exception as exc:
        auth_service.safe_error_log("users route failed", exc)
        return auth_json_response(
            exception_payload(exc, "Auth users failed.", status_code=500),
            default_error=500,
        )


@router.get("/audit-logs")
async def audit_logs(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    limit: int = Query(default=100, ge=1, le=1000),
    username: str = Query(default=""),
    action: str = Query(default=""),
) -> JSONResponse:
    """
    Admin-only: list auth audit logs

    ใช้ดู:
    - login_success
    - login_failed
    - logout
    - cache_rebuild
    - upload_entities
    - package_generate
    """

    try:
        auth_result = require_role_for_route(
            request=request,
            authorization=authorization,
            allowed_roles=["admin"],
            verify_db_active=False,
        )

        if not auth_result.get("allowed"):
            return forbidden_response(
                reason=auth_result.get("reason", "forbidden"),
                status_code=int(auth_result.get("status_code", 403)),
            )

        result = auth_service.list_audit_logs(
            limit=limit,
            username=username,
            action=action,
        )

        auth_service.write_audit_log(
            action="auth_audit_logs_view",
            user=auth_result.get("user"),
            method=request.method,
            path=str(request.url.path),
            status_code=200 if result.get("success") else 500,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            request_id=get_request_id(request),
            details={
                "limit": limit,
                "username_filter": username,
                "action_filter": action,
            },
        )

        return auth_json_response(
            result,
            default_success=200,
            default_error=500,
        )

    except Exception as exc:
        auth_service.safe_error_log("audit_logs route failed", exc)
        return auth_json_response(
            exception_payload(exc, "Audit logs failed.", status_code=500),
            default_error=500,
        )


# ============================================================
# 9) ADMIN DEBUG / SELF TEST ROUTES
# ============================================================

@router.get("/self-test")
async def self_test(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    """
    Admin-only: auth self-test

    ตรวจ:
    - password hash
    - password verify
    - JWT create/decode
    - public path rule
    - protected path rule
    - viewer read allowed
    - viewer cache forbidden
    """

    try:
        auth_result = require_role_for_route(
            request=request,
            authorization=authorization,
            allowed_roles=["admin"],
            verify_db_active=False,
        )

        if not auth_result.get("allowed"):
            return forbidden_response(
                reason=auth_result.get("reason", "forbidden"),
                status_code=int(auth_result.get("status_code", 403)),
            )

        result = success_payload(
            data=auth_service.run_auth_self_test(),
            message="Auth self-test completed.",
        )

        auth_service.write_audit_log(
            action="auth_self_test",
            user=auth_result.get("user"),
            method=request.method,
            path=str(request.url.path),
            status_code=200,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            request_id=get_request_id(request),
        )

        return auth_json_response(result)

    except Exception as exc:
        auth_service.safe_error_log("self_test route failed", exc)
        return auth_json_response(
            exception_payload(exc, "Auth self-test failed.", status_code=500),
            default_error=500,
        )


# ============================================================
# 10) ROUTE CATALOG
# ============================================================

@router.get("/routes")
async def auth_routes_catalog() -> JSONResponse:
    """
    Public route catalog เฉพาะ auth module

    ไม่คืน secret/password
    """

    payload = success_payload(
        data={
            "routes": [
                {
                    "method": "GET",
                    "path": "/api/auth/status",
                    "public": True,
                    "description": "Auth status without secrets.",
                },
                {
                    "method": "GET",
                    "path": "/api/auth/contract",
                    "public": True,
                    "description": "Frontend auth contract.",
                },
                {
                    "method": "POST",
                    "path": "/api/auth/login",
                    "public": True,
                    "description": "Username/password login.",
                },
                {
                    "method": "GET",
                    "path": "/api/auth/me",
                    "public": False,
                    "roles": ["admin", "user", "viewer"],
                    "description": "Current authenticated user.",
                },
                {
                    "method": "POST",
                    "path": "/api/auth/logout",
                    "public": False,
                    "roles": ["admin", "user", "viewer"],
                    "description": "Stateless logout audit.",
                },
                {
                    "method": "POST",
                    "path": "/api/auth/init",
                    "public": False,
                    "roles": ["admin"],
                    "description": "Initialize auth DB/tables/users.",
                },
                {
                    "method": "GET",
                    "path": "/api/auth/users",
                    "public": False,
                    "roles": ["admin"],
                    "description": "List fixed users without password hash.",
                },
                {
                    "method": "GET",
                    "path": "/api/auth/audit-logs",
                    "public": False,
                    "roles": ["admin"],
                    "description": "List auth audit logs.",
                },
                {
                    "method": "GET",
                    "path": "/api/auth/self-test",
                    "public": False,
                    "roles": ["admin"],
                    "description": "Run auth self-test.",
                },
            ],
            "fixed_users": [
                "admin",
                "user",
                "viewer",
            ],
            "token_header": getattr(config, "AUTH_HEADER_NAME", "Authorization"),
            "token_prefix": getattr(config, "AUTH_TOKEN_PREFIX", "Bearer "),
        },
        message="Auth route catalog loaded.",
    )

    return auth_json_response(payload)