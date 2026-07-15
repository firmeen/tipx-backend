# ============================================================
# FILE: backend/app.py
# TIPX Enterprise Intelligence Dashboard
# FastAPI Application Factory
# ============================================================

"""
backend/app.py

ไฟล์นี้เป็นจุดเริ่มต้นของ Backend Application ทั้งหมดของระบบ TIPX

หน้าที่หลัก:
1. สร้าง FastAPI Application
2. โหลด config จาก backend/config.py
3. สร้าง folder พื้นฐานของระบบ
4. ตั้งค่า CORS
5. ตั้งค่า logging
6. register API router จาก backend/api_routes.py
7. register exception handlers
8. serve frontend static files
9. serve external package viewer
10. เป็น entrypoint สำหรับ run backend

โครงสร้างระบบที่ไฟล์นี้รองรับ:
- Flood Pipeline
- Policy Pipeline
- Linkage Pipeline
- Company Unified Master
- Flood Spatial Join
- OpenLayers Map
- Linkage Graph
- Filter Builder
- Data Quality
- Dashboard Summary
- Package Export
- External Viewer Package
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import config

try:
    from auth import auth_service
    AUTH_SERVICE_LOADED = True
    AUTH_SERVICE_IMPORT_ERROR = ""
except Exception as e:
    auth_service = None
    AUTH_SERVICE_LOADED = False
    AUTH_SERVICE_IMPORT_ERROR = str(e)

# ============================================================
# 1) CONFIG SHORTCUTS
# ============================================================

APP_NAME: str = config.APP_NAME
APP_SHORT_NAME: str = config.APP_SHORT_NAME
APP_VERSION: str = config.APP_VERSION
APP_DESCRIPTION: str = config.APP_DESCRIPTION
DEFAULT_ENV: str = config.DEFAULT_ENV
DEBUG: bool = config.DEBUG
TESTING: bool = config.TESTING
DEFAULT_TIMEZONE: str = config.DEFAULT_TIMEZONE

API_PREFIX: str = config.API_PREFIX
PUBLIC_API_PREFIX: str = config.PUBLIC_API_PREFIX

FRONTEND_DIR: Path = config.FRONTEND_DIR
PROJECT_ROOT: Path = config.PROJECT_ROOT
OUTPUT_DIR: Path = config.OUTPUT_DIR
PACKAGE_DIR: Path = config.PACKAGE_DIR
PACKAGE_ZIP_DIR: Path = config.PACKAGE_ZIP_DIR
LOG_DIR: Path = config.LOG_DIR
LOG_PATH: Path = config.LOG_PATH
LOG_LEVEL: str = config.LOG_LEVEL

ERROR_LOG_PATH: Path = getattr(config, "ERROR_LOG_PATH", LOG_DIR / "tipx_backend_error.log")

ENABLE_REQUEST_LOG: bool = config.ENABLE_REQUEST_LOG
ENABLE_PIPELINE_LOG: bool = config.ENABLE_PIPELINE_LOG

CORS_ENABLED: bool = config.CORS_ENABLED
CORS_ALLOW_ORIGINS: List[str] = getattr(config, "CORS_ALLOW_ORIGINS", ["*"])

JSON_AS_ASCII: bool = config.JSON_AS_ASCII
JSON_SORT_KEYS: bool = config.JSON_SORT_KEYS
MAX_CONTENT_LENGTH_MB: int = config.MAX_CONTENT_LENGTH_MB

HOST: str = os.getenv("APP_HOST", os.getenv("TIPX_HOST", "127.0.0.1"))
PORT: int = int(os.getenv("APP_PORT", os.getenv("TIPX_PORT", "5000")))

AUTH_ENABLED: bool = bool(getattr(config, "AUTH_ENABLED", True))
AUTH_PROTECT_INTERNAL_API: bool = bool(getattr(config, "AUTH_PROTECT_INTERNAL_API", True))
AUTH_PROTECTED_API_PREFIX: str = getattr(config, "AUTH_PROTECTED_API_PREFIX", API_PREFIX)
AUTH_HEADER_NAME: str = getattr(config, "AUTH_HEADER_NAME", "Authorization")
AUTH_TOKEN_PREFIX: str = getattr(config, "AUTH_TOKEN_PREFIX", "Bearer ")

AUTH_PUBLIC_EXACT_PATHS: List[str] = list(
    getattr(
        config,
        "AUTH_PUBLIC_EXACT_PATHS",
        [
            "/",
            "/health",
            "/status",
            "/favicon.ico",
            "/docs",
            "/redoc",
            "/openapi.json",
            f"{API_PREFIX}/health",
            f"{API_PREFIX}/status",
            f"{API_PREFIX}/auth/login",
            f"{API_PREFIX}/auth/status",
        ],
    )
)

AUTH_PUBLIC_PREFIXES: List[str] = list(
    getattr(
        config,
        "AUTH_PUBLIC_PREFIXES",
        [
            "/static",
            "/assets",
            "/frontend",
            "/external_viewer",
            PUBLIC_API_PREFIX,
            f"{API_PREFIX}/public",
            f"{API_PREFIX}{PUBLIC_API_PREFIX}",
        ],
    )
)

AUTH_SKIP_OPTIONS_REQUEST: bool = bool(getattr(config, "AUTH_SKIP_OPTIONS_REQUEST", True))
AUDIT_ENABLED: bool = bool(getattr(config, "AUDIT_ENABLED", True))


# ============================================================
# 2) LOGGING SETUP
# ============================================================

def setup_logging() -> logging.Logger:
    """
    ตั้งค่า logging กลางของ backend

    Log จะถูกเขียนลง:
    - console
    - output/logs/tipx_backend.log
    - output/logs/tipx_backend_error.log
    """

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, LOG_LEVEL, logging.INFO)

    logger = logging.getLogger(APP_SHORT_NAME)
    logger.setLevel(log_level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | %(levelname)s | %(name)s | "
            "%(module)s.%(funcName)s:%(lineno)d | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    error_handler = RotatingFileHandler(
        ERROR_LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger.propagate = False

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    return logger


logger = setup_logging()


# ============================================================
# 3) JSON RESPONSE HELPERS FOR APP LEVEL
# ============================================================

def app_json_payload(
    success: bool,
    message: str,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    response helper ระดับ app.py

    ใช้กับ:
    - fallback routes
    - exception handlers
    - startup fallback
    """

    return {
        "success": bool(success),
        "message": message,
        "data": data if data is not None else {},
        "meta": {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "app": APP_SHORT_NAME,
            "version": APP_VERSION,
            "environment": DEFAULT_ENV,
            **(meta or {}),
        },
        "errors": errors if errors is not None else [],
    }


def app_json_response(
    success: bool,
    message: str,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[Any] = None,
    status_code: int = 200,
) -> JSONResponse:
    """
    คืน JSONResponse รูปแบบกลางของ TIPX
    """

    return JSONResponse(
        status_code=status_code,
        content=app_json_payload(
            success=success,
            message=message,
            data=data,
            meta=meta,
            errors=errors,
        ),
    )


def serialize_exception(exc: Exception, include_traceback: bool = False) -> Dict[str, Any]:
    """
    แปลง exception เป็น dict สำหรับส่งออก error response
    """

    error_payload: Dict[str, Any] = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }

    if include_traceback:
        error_payload["traceback"] = traceback.format_exc()

    return error_payload

# ============================================================
# 3.1) AUTH / REQUEST GUARD HELPERS
# ============================================================

def normalize_app_path(path: str) -> str:
    text = str(path or "/").strip()

    if not text.startswith("/"):
        text = f"/{text}"

    while "//" in text:
        text = text.replace("//", "/")

    if len(text) > 1 and text.endswith("/"):
        text = text.rstrip("/")

    return text


def normalize_app_method(method: str) -> str:
    return str(method or "GET").strip().upper()


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


def get_authorization_header(request: Request) -> str:
    return request.headers.get(AUTH_HEADER_NAME, "") or request.headers.get("Authorization", "")


def is_public_path_fallback(path: str, method: str = "GET") -> bool:
    clean_path = normalize_app_path(path)
    clean_method = normalize_app_method(method)

    if clean_method == "OPTIONS" and AUTH_SKIP_OPTIONS_REQUEST:
        return True

    if clean_path in {normalize_app_path(item) for item in AUTH_PUBLIC_EXACT_PATHS}:
        return True

    for prefix in AUTH_PUBLIC_PREFIXES:
        clean_prefix = normalize_app_path(prefix)

        if clean_path == clean_prefix or clean_path.startswith(clean_prefix + "/"):
            return True

    return False


def is_public_path(path: str, method: str = "GET") -> bool:
    if AUTH_SERVICE_LOADED and auth_service is not None:
        try:
            return bool(auth_service.is_public_path(path, method))
        except Exception:
            pass

    return is_public_path_fallback(path, method)


def is_auth_guard_target(path: str, method: str = "GET") -> bool:
    clean_path = normalize_app_path(path)

    if not AUTH_ENABLED:
        return False

    if not AUTH_PROTECT_INTERNAL_API:
        return False

    if not clean_path.startswith(normalize_app_path(AUTH_PROTECTED_API_PREFIX)):
        return False

    return True


def set_request_auth_state(request: Request, auth_result: Dict[str, Any]) -> None:
    try:
        request.state.auth = auth_result
        request.state.authenticated = bool(auth_result.get("allowed"))
        request.state.public = bool(auth_result.get("public"))
        request.state.auth_reason = auth_result.get("reason", "")

        user = auth_result.get("user")

        if isinstance(user, dict) and user:
            request.state.user = user
            request.state.username = user.get("username", "")
            request.state.role = user.get("role", "")

    except Exception:
        pass


def make_auth_unavailable_response(path: str, method: str) -> JSONResponse:
    return app_json_response(
        success=False,
        message="Auth service unavailable",
        data={
            "path": path,
            "method": method,
            "auth_enabled": AUTH_ENABLED,
            "auth_service_loaded": AUTH_SERVICE_LOADED,
            "auth_service_import_error": AUTH_SERVICE_IMPORT_ERROR,
        },
        errors=[
            {
                "code": "auth_service_unavailable",
                "message": "auth_service.py import failed while AUTH_ENABLED=true",
            }
        ],
        status_code=503,
    )


def make_auth_denied_response(auth_result: Dict[str, Any], path: str, method: str) -> JSONResponse:
    status_code = int(auth_result.get("status_code", 401) or 401)
    reason = str(auth_result.get("reason", "not_authenticated"))
    required_roles = auth_result.get("required_roles", [])

    return app_json_response(
        success=False,
        message="Authentication required" if status_code == 401 else "Permission denied",
        data={
            "path": path,
            "method": method,
            "reason": reason,
            "required_roles": required_roles,
            "rule_name": auth_result.get("rule_name", ""),
        },
        errors=[
            {
                "code": "not_authenticated" if status_code == 401 else "role_forbidden",
                "message": reason,
                "status_code": status_code,
            }
        ],
        status_code=status_code,
    )


def should_skip_middleware_audit(path: str, method: str) -> bool:
    clean_path = normalize_app_path(path)

    if not AUDIT_ENABLED:
        return True

    if clean_path.startswith(f"{API_PREFIX}/auth"):
        return True

    if is_public_path(clean_path, method):
        return True

    return False


def write_auth_audit_safe(
    request: Request,
    response_status_code: int,
    auth_result: Optional[Dict[str, Any]] = None,
    action: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    if not AUDIT_ENABLED:
        return

    if not AUTH_SERVICE_LOADED or auth_service is None:
        return

    path = str(request.url.path)
    method = str(request.method)

    if should_skip_middleware_audit(path, method):
        return

    try:
        user = None

        if auth_result and isinstance(auth_result.get("user"), dict):
            user = auth_result.get("user")

        if user is None:
            user = getattr(request.state, "user", None)

        audit_action = action

        if not audit_action:
            audit_action = auth_service.get_audit_action_for_path(
                path=path,
                method=method,
                default="",
            )

        if not audit_action:
            return

        auth_service.write_audit_log(
            action=audit_action,
            user=user if isinstance(user, dict) else None,
            method=method,
            path=path,
            status_code=response_status_code,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            request_id=get_request_id(request),
            details={
                "query_params": dict(request.query_params),
                "reason": auth_result.get("reason", "") if isinstance(auth_result, dict) else "",
                "rule_name": auth_result.get("rule_name", "") if isinstance(auth_result, dict) else "",
                **(details or {}),
            },
        )

    except Exception as exc:
        logger.warning("auth audit failed: %s", str(exc))


def authorize_request_for_app(request: Request) -> Dict[str, Any]:
    path = str(request.url.path)
    method = str(request.method)

    if not is_auth_guard_target(path, method):
        return {
            "allowed": True,
            "public": True,
            "reason": "not_auth_guard_target",
            "status_code": 200,
            "user": None,
        }

    if is_public_path(path, method):
        return {
            "allowed": True,
            "public": True,
            "reason": "public_path",
            "status_code": 200,
            "user": None,
        }

    if not AUTH_SERVICE_LOADED or auth_service is None:
        return {
            "allowed": False,
            "public": False,
            "reason": "auth_service_unavailable",
            "status_code": 503,
            "user": None,
            "required_roles": [],
        }

    return auth_service.authorize_request(
        path=path,
        method=method,
        authorization_header=get_authorization_header(request),
        verify_db_active=False,
    )

# ============================================================
# 4) FRONTEND STATIC SERVING
# ============================================================

def safe_frontend_path(filename: str) -> Optional[Path]:
    """
    คืน path ของ frontend file แบบกัน path traversal
    """

    if not filename:
        return None

    frontend_root = FRONTEND_DIR.resolve()
    target = (FRONTEND_DIR / filename).resolve()

    try:
        target.relative_to(frontend_root)
    except Exception:
        return None

    return target


def frontend_file_exists(filename: str) -> bool:
    """
    ตรวจว่าไฟล์ frontend มีอยู่จริงไหม
    """

    target = safe_frontend_path(filename)

    if target is None:
        return False

    return target.exists() and target.is_file()


def serve_frontend_file(filename: str) -> FileResponse:
    """
    ส่งไฟล์จาก frontend directory
    """

    target = safe_frontend_path(filename)

    if target is None or not target.exists() or not target.is_file():
        raise FileNotFoundError(filename)

    return FileResponse(target)


def serve_frontend_index() -> HTMLResponse | FileResponse:
    """
    ส่ง frontend/index.html

    ใช้ใน route:
    - /
    - /dashboard
    - /external/{package_id}
    """

    index_path = FRONTEND_DIR / "index.html"

    if index_path.exists() and index_path.is_file():
        return FileResponse(index_path)

    fallback_html = f"""
    <!doctype html>
    <html lang="th">
    <head>
        <meta charset="utf-8">
        <title>{APP_SHORT_NAME}</title>
        <style>
            body {{
                margin: 0;
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: #e5e7eb;
                display: flex;
                min-height: 100vh;
                align-items: center;
                justify-content: center;
            }}
            .box {{
                width: min(720px, 92vw);
                padding: 32px;
                background: #111827;
                border: 1px solid #334155;
                border-radius: 18px;
                box-shadow: 0 24px 80px rgba(0,0,0,.35);
            }}
            h1 {{
                margin: 0 0 8px 0;
                font-size: 28px;
            }}
            p {{
                line-height: 1.7;
                color: #cbd5e1;
            }}
            code {{
                background: #020617;
                padding: 2px 6px;
                border-radius: 6px;
                color: #93c5fd;
            }}
            a {{
                color: #38bdf8;
            }}
        </style>
    </head>
    <body>
        <div class="box">
            <h1>{APP_NAME}</h1>
            <p>
                Backend started successfully.
            </p>
            <p>
                ไม่พบไฟล์ <code>frontend/index.html</code>
                ให้สร้างไฟล์ frontend ตามลำดับโครงสร้าง TIPX
            </p>
            <p>
                ตรวจสอบ API ได้ที่ <a href="{API_PREFIX}/health">{API_PREFIX}/health</a>
            </p>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(content=fallback_html, status_code=200)


# ============================================================
# 5) APP FACTORY
# ============================================================

def create_app() -> FastAPI:
    """
    สร้าง FastAPI app สำหรับระบบ TIPX

    Flow การทำงาน:
    1. ensure directories
    2. create FastAPI app
    3. configure CORS
    4. register middleware
    5. register exception handlers
    6. register API และ Auth router
    7. register frontend routes และ SPA fallback
    8. startup report
    9. return app
    """

    config.ensure_directories()

    app = FastAPI(
        title=APP_NAME,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        debug=DEBUG,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )

    app.state.tipx_config = config.CONFIG
    app.state.created_at = datetime.now().isoformat(timespec="seconds")

    configure_cors(app)
    register_request_middleware(app)
    register_exception_handlers(app)
    register_api_routes(app)
    register_frontend_routes(app)
    register_startup_event(app)

    startup_report = build_startup_report()
    logger.info("TIPX FastAPI backend created successfully")
    logger.info(
        json.dumps(
            startup_report,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    return app

# ============================================================
# 6) CORS
# ============================================================

def configure_cors(app: FastAPI) -> None:
    """
    ตั้งค่า CORS

    ใช้สำหรับ:
    - frontend dev server
    - local dashboard
    - external viewer local test
    - Authorization Bearer token
    - request id / correlation id สำหรับ audit log
    """

    if not CORS_ENABLED:
        logger.info("CORS disabled")
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "X-Request-ID",
            "X-Correlation-ID",
        ],
        expose_headers=[
            "X-TIPX-App",
            "X-TIPX-Version",
            "X-TIPX-Environment",
            "X-TIPX-Duration-Ms",
            "X-TIPX-Auth",
            "X-TIPX-Role",
            "X-Request-ID",
        ],
    )

    logger.info("CORS enabled")


# ============================================================
# 7) REQUEST MIDDLEWARE
# ============================================================

def register_request_middleware(app: FastAPI) -> None:
    """
    ลงทะเบียน middleware

    ใช้สำหรับ:
    - request log
    - response header
    - duration metadata
    - auth guard สำหรับ internal /api
    - skip public paths
    - role guard backend
    - simple audit log action สำคัญ
    """

    @app.middleware("http")
    async def request_log_auth_middleware(request: Request, call_next):
        started_at = perf_counter()
        path = str(request.url.path)
        method = str(request.method)
        request_id = get_request_id(request)

        auth_result: Dict[str, Any] = {
            "allowed": True,
            "public": True,
            "reason": "not_checked",
            "status_code": 200,
            "user": None,
        }

        if ENABLE_REQUEST_LOG:
            logger.info(
                "REQUEST | method=%s | path=%s | client=%s | query=%s | request_id=%s",
                method,
                path,
                request.client.host if request.client else None,
                dict(request.query_params),
                request_id,
            )

        try:
            auth_result = authorize_request_for_app(request)
            set_request_auth_state(request, auth_result)

            if not auth_result.get("allowed"):
                duration_ms = int((perf_counter() - started_at) * 1000)
                status_code = int(auth_result.get("status_code", 401) or 401)

                if auth_result.get("reason") == "auth_service_unavailable":
                    response = make_auth_unavailable_response(path, method)
                else:
                    response = make_auth_denied_response(auth_result, path, method)

                response.headers["X-TIPX-App"] = APP_SHORT_NAME
                response.headers["X-TIPX-Version"] = APP_VERSION
                response.headers["X-TIPX-Environment"] = DEFAULT_ENV
                response.headers["X-TIPX-Duration-Ms"] = str(duration_ms)
                response.headers["X-TIPX-Auth"] = "denied"
                response.headers["X-TIPX-Auth-Reason"] = str(auth_result.get("reason", "denied"))

                if request_id:
                    response.headers["X-Request-ID"] = request_id

                write_auth_audit_safe(
                    request=request,
                    response_status_code=status_code,
                    auth_result=auth_result,
                    action="auth_denied",
                    details={
                        "auth_denied": True,
                        "required_roles": auth_result.get("required_roles", []),
                    },
                )

                if ENABLE_REQUEST_LOG:
                    logger.warning(
                        "AUTH_DENIED | method=%s | path=%s | status=%s | reason=%s | duration_ms=%s",
                        method,
                        path,
                        status_code,
                        auth_result.get("reason"),
                        duration_ms,
                    )

                return response

            response = await call_next(request)

        except Exception:
            duration_ms = int((perf_counter() - started_at) * 1000)

            write_auth_audit_safe(
                request=request,
                response_status_code=500,
                auth_result=auth_result,
                action="server_exception",
                details={
                    "exception": True,
                },
            )

            if ENABLE_REQUEST_LOG:
                logger.exception(
                    "REQUEST_FAILED | method=%s | path=%s | duration_ms=%s | request_id=%s",
                    method,
                    path,
                    duration_ms,
                    request_id,
                )

            raise

        duration_ms = int((perf_counter() - started_at) * 1000)

        response.headers["X-TIPX-App"] = APP_SHORT_NAME
        response.headers["X-TIPX-Version"] = APP_VERSION
        response.headers["X-TIPX-Environment"] = DEFAULT_ENV
        response.headers["X-TIPX-Duration-Ms"] = str(duration_ms)
        response.headers["X-TIPX-Auth"] = "public" if auth_result.get("public") else "authenticated"

        user = auth_result.get("user")

        if isinstance(user, dict) and user.get("role"):
            response.headers["X-TIPX-Role"] = str(user.get("role"))

        if request_id:
            response.headers["X-Request-ID"] = request_id

        write_auth_audit_safe(
            request=request,
            response_status_code=int(getattr(response, "status_code", 200) or 200),
            auth_result=auth_result,
        )

        if ENABLE_REQUEST_LOG:
            logger.info(
                "RESPONSE | method=%s | path=%s | status=%s | duration_ms=%s | auth=%s | role=%s | request_id=%s",
                method,
                path,
                response.status_code,
                duration_ms,
                "public" if auth_result.get("public") else "authenticated",
                user.get("role") if isinstance(user, dict) else "",
                request_id,
            )

        return response


# ============================================================
# 8) FRONTEND ROUTES
# ============================================================

def register_frontend_routes(app: FastAPI) -> None:
    """
    register route สำหรับ frontend

    Route ที่รองรับ:
    - /
    - /dashboard
    - /external/{package_id}
    - /frontend/{filename}
    - /assets/{filename}
    """

    @app.get("/", include_in_schema=False)
    async def index():
        return serve_frontend_index()

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        return serve_frontend_index()

    @app.get("/external/{package_id}", include_in_schema=False)
    async def external_viewer(package_id: str):
        return serve_frontend_index()

    @app.get("/frontend/{filename:path}", include_in_schema=False)
    async def frontend_static(filename: str):
        if frontend_file_exists(filename):
            return serve_frontend_file(filename)

        return app_json_response(
            success=False,
            message="Frontend file not found",
            data={
                "filename": filename,
                "frontend_dir": str(FRONTEND_DIR),
            },
            errors=[
                {
                    "code": "frontend_file_not_found",
                    "message": f"ไม่พบไฟล์ frontend/{filename}",
                }
            ],
            status_code=404,
        )

    @app.get("/assets/{filename:path}", include_in_schema=False)
    async def frontend_assets(filename: str):
        assets_filename = f"assets/{filename}"

        if frontend_file_exists(assets_filename):
            return serve_frontend_file(assets_filename)

        return app_json_response(
            success=False,
            message="Asset file not found",
            data={
                "filename": filename,
                "assets_dir": str(FRONTEND_DIR / "assets"),
            },
            errors=[
                {
                    "code": "asset_file_not_found",
                    "message": f"ไม่พบไฟล์ assets/{filename}",
                }
            ],
            status_code=404,
        )

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa_fallback(spa_path: str):
        if spa_path.startswith("api/") or spa_path.startswith("api"):
            return app_json_response(
                success=False,
                message="API route not found",
                data={
                    "path": f"/{spa_path}",
                    "method": "GET",
                },
                errors=[
                    {
                        "code": "api_route_not_found",
                        "message": f"ไม่พบ API route /{spa_path}",
                    }
                ],
                status_code=404,
            )

        if frontend_file_exists(spa_path):
            return serve_frontend_file(spa_path)

        return serve_frontend_index()


# ============================================================
# 9) API ROUTES REGISTRATION
# ============================================================

def register_api_routes(app: FastAPI) -> None:
    """
    Register API router จาก api_routes.py
    และ Auth router จาก auth/auth_routes.py

    api_routes.py ใช้ prefix จาก config.API_PREFIX
    auth_routes.py ใช้ prefix="/auth" และถูกประกอบภายใต้ API_PREFIX
    """

    try:
        from api_routes import router as api_router

        app.include_router(api_router)
        logger.info("API router registered from api_routes.py")

    except Exception as exc:
        logger.warning(
            "Cannot register FastAPI router from api_routes.py. "
            "Fallback API routes enabled."
        )
        logger.warning(
            "api_routes import/register error: %s",
            str(exc),
        )

        register_fallback_api_routes(app, exc)

    try:
        from auth.auth_routes import router as auth_router

        app.include_router(
            auth_router,
            prefix=API_PREFIX,
        )

        logger.info(
            "Auth router registered at %s/auth",
            API_PREFIX,
        )

    except Exception as exc:
        logger.error(
            "Cannot register Auth router from auth/auth_routes.py: %s",
            str(exc),
        )

def register_fallback_api_routes(app: FastAPI, route_error: Exception) -> None:
    """
    fallback API routes

    ใช้ชั่วคราวในกรณี api_routes.py ยังไม่ถูก migrate เป็น FastAPI
    หรือเกิด import error

    หลังจากสร้าง api_routes.py แล้ว routes จริงจะถูกใช้งานแทน
    """

    @app.get(f"{API_PREFIX}/health")
    async def fallback_health():
        validation = config.validate_basic_config()

        return app_json_response(
            success=validation["status"] != "error",
            message="TIPX backend fallback health",
            data={
                "app": APP_NAME,
                "short_name": APP_SHORT_NAME,
                "version": APP_VERSION,
                "environment": DEFAULT_ENV,
                "api_routes_registered": False,
                "route_error": str(route_error),
                "validation": validation,
                "auth": {
                    "enabled": AUTH_ENABLED,
                    "auth_service_loaded": AUTH_SERVICE_LOADED,
                    "auth_service_import_error": AUTH_SERVICE_IMPORT_ERROR,
                    "protect_internal_api": AUTH_PROTECT_INTERNAL_API,
                },
            },
            meta={
                "fallback": True,
            },
            status_code=200 if validation["status"] != "error" else 500,
        )

    @app.get(f"{API_PREFIX}/status")
    async def fallback_status():
        return app_json_response(
            success=True,
            message="TIPX backend fallback status",
            data={
                "app": {
                    "name": APP_NAME,
                    "short_name": APP_SHORT_NAME,
                    "version": APP_VERSION,
                    "description": APP_DESCRIPTION,
                    "environment": DEFAULT_ENV,
                },
                "auth": {
                    "enabled": AUTH_ENABLED,
                    "auth_service_loaded": AUTH_SERVICE_LOADED,
                    "auth_service_import_error": AUTH_SERVICE_IMPORT_ERROR,
                    "protect_internal_api": AUTH_PROTECT_INTERNAL_API,
                },
                "paths": config.get_system_path_status(),
                "inputs": config.get_input_file_status(),
                "validation": config.validate_basic_config(),
                "api_routes_registered": False,
                "route_error": str(route_error),
            },
            meta={
                "fallback": True,
            },
        )

    @app.get(f"{API_PREFIX}/auth/status")
    async def fallback_auth_status():
        if AUTH_SERVICE_LOADED and auth_service is not None:
            return JSONResponse(
                status_code=200,
                content=auth_service.json_safe(auth_service.get_auth_status()),
            )

        return app_json_response(
            success=False,
            message="Auth service unavailable",
            data={
                "auth_service_loaded": AUTH_SERVICE_LOADED,
                "auth_service_import_error": AUTH_SERVICE_IMPORT_ERROR,
            },
            errors=[
                {
                    "code": "auth_service_unavailable",
                    "message": AUTH_SERVICE_IMPORT_ERROR,
                }
            ],
            status_code=503,
        )

    @app.get(f"{API_PREFIX}/auth/contract")
    async def fallback_auth_contract():
        if AUTH_SERVICE_LOADED and auth_service is not None:
            return JSONResponse(
                status_code=200,
                content=auth_service.json_safe(
                    app_json_payload(
                        success=True,
                        message="Auth frontend contract loaded.",
                        data=auth_service.get_frontend_auth_contract(),
                        meta={
                            "fallback": True,
                        },
                    )
                ),
            )

        return app_json_response(
            success=False,
            message="Auth service unavailable",
            data={
                "auth_service_loaded": AUTH_SERVICE_LOADED,
                "auth_service_import_error": AUTH_SERVICE_IMPORT_ERROR,
            },
            errors=[
                {
                    "code": "auth_service_unavailable",
                    "message": AUTH_SERVICE_IMPORT_ERROR,
                }
            ],
            status_code=503,
        )

    @app.get(f"{API_PREFIX}/config")
    async def fallback_config():
        return app_json_response(
            success=True,
            message="TIPX backend fallback config",
            data=config.get_config_summary(),
            meta={
                "fallback": True,
            },
        )

    @app.get(f"{API_PREFIX}/paths")
    async def fallback_paths():
        return app_json_response(
            success=True,
            message="TIPX backend fallback paths",
            data={
                "paths": config.get_runtime_paths() if hasattr(config, "get_runtime_paths") else config.get_system_path_status(),
                "path_status": config.get_path_status() if hasattr(config, "get_path_status") else {},
                "warnings": config.validate_startup_paths() if hasattr(config, "validate_startup_paths") else [],
            },
            meta={
                "fallback": True,
            },
        )

    @app.get(f"{API_PREFIX}/routes")
    async def fallback_routes():
        routes = []

        for route in app.routes:
            methods = sorted(list(getattr(route, "methods", []) or []))
            routes.append(
                {
                    "name": getattr(route, "name", None),
                    "path": getattr(route, "path", None),
                    "methods": methods,
                }
            )

        return app_json_response(
            success=True,
            message="TIPX fallback route list",
            data={
                "routes": routes,
                "api_routes_registered": False,
                "route_error": str(route_error),
                "auth": {
                    "enabled": AUTH_ENABLED,
                    "auth_service_loaded": AUTH_SERVICE_LOADED,
                    "protect_internal_api": AUTH_PROTECT_INTERNAL_API,
                },
            },
            meta={
                "fallback": True,
                "record_count": len(routes),
            },
        )


# ============================================================
# 10) EXCEPTION HANDLERS
# ============================================================

def register_exception_handlers(app: FastAPI) -> None:
    """
    register exception handlers ทั้งหมด

    รองรับ:
    - HTTPException
    - RequestValidationError
    - generic Exception
    """

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ):
        if exc.status_code == 404:
            if (
                request.url.path.startswith(API_PREFIX)
                or request.url.path.startswith(PUBLIC_API_PREFIX)
            ):
                return app_json_response(
                    success=False,
                    message="API route not found",
                    data={
                        "path": request.url.path,
                        "method": request.method,
                    },
                    errors=[
                        {
                            "code": "api_route_not_found",
                            "message": str(exc.detail),
                        }
                    ],
                    status_code=404,
                )

            return serve_frontend_index()

        if exc.status_code == 405:
            return app_json_response(
                success=False,
                message="Method not allowed",
                data={
                    "path": request.url.path,
                    "method": request.method,
                },
                errors=[
                    {
                        "code": "method_not_allowed",
                        "message": str(exc.detail),
                    }
                ],
                status_code=405,
            )

        if exc.status_code == 413:
            return app_json_response(
                success=False,
                message="Uploaded file too large",
                data={
                    "max_content_length_mb": MAX_CONTENT_LENGTH_MB,
                },
                errors=[
                    {
                        "code": "request_entity_too_large",
                        "message": str(exc.detail),
                    }
                ],
                status_code=413,
            )

        return app_json_response(
            success=False,
            message=str(exc.detail) if exc.detail else "HTTP error",
            data={
                "path": request.url.path,
                "method": request.method,
            },
            errors=[
                {
                    "code": f"http_{exc.status_code}",
                    "message": str(exc.detail),
                }
            ],
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ):
        return app_json_response(
            success=False,
            message="Request validation error",
            data={
                "path": request.url.path,
                "method": request.method,
            },
            errors=[
                {
                    "code": "request_validation_error",
                    "message": "Request data does not match the required schema.",
                    "details": exc.errors(),
                }
            ],
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ):
        logger.exception(
            "Unhandled exception: %s",
            str(exc),
        )

        return app_json_response(
            success=False,
            message="Unhandled server exception",
            data={
                "path": request.url.path,
                "method": request.method,
            },
            errors=[
                {
                    "code": "unhandled_server_exception",
                    "message": "Internal server error",
                }
            ],
            status_code=500,
        )

# ============================================================
# 11) STARTUP EVENT / STARTUP REPORT
# ============================================================

def register_startup_event(app: FastAPI) -> None:
    """
    register startup event

    ทำตอนเริ่มระบบ:
    - ensure directories
    - initialize auth database/table/fixed users
    - startup report
    """

    @app.on_event("startup")
    async def startup_event() -> None:
        config.ensure_directories()

        auth_startup_result: Dict[str, Any] = {
            "success": False,
            "message": "auth_service_not_loaded",
            "data": {},
        }

        if AUTH_ENABLED:
            if AUTH_SERVICE_LOADED and auth_service is not None:
                try:
                    auth_startup_result = auth_service.startup_auth()
                    app.state.auth_startup = auth_startup_result

                    if auth_startup_result.get("success"):
                        logger.info("Auth startup completed")
                    else:
                        logger.warning(
                            "Auth startup degraded: %s",
                            json.dumps(auth_startup_result, ensure_ascii=False, default=str),
                        )

                except Exception as exc:
                    app.state.auth_startup = {
                        "success": False,
                        "message": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                    logger.exception("Auth startup failed: %s", str(exc))

            else:
                app.state.auth_startup = {
                    "success": False,
                    "message": "AUTH_ENABLED=true but auth_service import failed",
                    "import_error": AUTH_SERVICE_IMPORT_ERROR,
                }
                logger.error("AUTH_ENABLED=true but auth_service import failed: %s", AUTH_SERVICE_IMPORT_ERROR)

        startup_report = build_startup_report()
        logger.info("TIPX FastAPI startup completed")
        logger.info(json.dumps(startup_report, ensure_ascii=False, indent=2, default=str))


def build_startup_report() -> Dict[str, Any]:
    """
    สร้าง startup report สำหรับ log ตอนเริ่มระบบ
    """

    validation = config.validate_basic_config()
    latest_prediction_file = (
        config.find_latest_prediction_file()
        if hasattr(config, "find_latest_prediction_file")
        else None
    )

    auth_summary: Dict[str, Any] = {
        "enabled": AUTH_ENABLED,
        "auth_service_loaded": AUTH_SERVICE_LOADED,
        "auth_service_import_error": AUTH_SERVICE_IMPORT_ERROR,
        "protect_internal_api": AUTH_PROTECT_INTERNAL_API,
        "protected_api_prefix": AUTH_PROTECTED_API_PREFIX,
    }

    if hasattr(config, "get_auth_config_summary"):
        try:
            auth_summary["config"] = config.get_auth_config_summary()
        except Exception as exc:
            auth_summary["config_error"] = str(exc)

    if AUTH_SERVICE_LOADED and auth_service is not None:
        try:
            auth_status = auth_service.get_auth_status()
            auth_summary["status"] = auth_status.get("data", {}) if isinstance(auth_status, dict) else {}
        except Exception as exc:
            auth_summary["status_error"] = str(exc)

    return {
        "app": {
            "name": APP_NAME,
            "short_name": APP_SHORT_NAME,
            "version": APP_VERSION,
            "description": APP_DESCRIPTION,
            "environment": DEFAULT_ENV,
            "debug": DEBUG,
            "testing": TESTING,
            "timezone": DEFAULT_TIMEZONE,
        },
        "auth": auth_summary,
        "data_source": (
            config.validate_data_source_config()
            if hasattr(config, "validate_data_source_config")
            else {}
        ),
        "paths": (
            config.get_runtime_paths()
            if hasattr(config, "get_runtime_paths")
            else config.get_system_path_status()
        ),
        "path_status": (
            config.get_path_status()
            if hasattr(config, "get_path_status")
            else {}
        ),
        "inputs": config.get_input_file_status(),
        "validation": validation,
        "api": {
            "api_prefix": API_PREFIX,
            "public_api_prefix": PUBLIC_API_PREFIX,
            "cors_enabled": CORS_ENABLED,
            "docs_url": f"{API_PREFIX}/docs",
            "openapi_url": f"{API_PREFIX}/openapi.json",
            "auth_protected": AUTH_ENABLED and AUTH_PROTECT_INTERNAL_API,
        },
        "frontend": {
            "frontend_dir": str(FRONTEND_DIR),
            "index_exists": (FRONTEND_DIR / "index.html").exists(),
        },
        "output": {
            "output_dir": str(OUTPUT_DIR),
            "package_dir": str(PACKAGE_DIR),
            "package_zip_dir": str(PACKAGE_ZIP_DIR),
            "log_path": str(LOG_PATH),
            "error_log_path": str(ERROR_LOG_PATH),
        },
        "flood": {
            "latest_database_path": str(getattr(config, "FLOOD_LATEST_DATABASE_PATH", "")),
            "latest_database_exists": getattr(config, "FLOOD_LATEST_DATABASE_PATH", Path()).exists()
            if hasattr(config, "FLOOD_LATEST_DATABASE_PATH")
            else False,
            "master_database_path": str(getattr(config, "FLOOD_MASTER_DATABASE_PATH", "")),
            "master_database_exists": getattr(config, "FLOOD_MASTER_DATABASE_PATH", Path()).exists()
            if hasattr(config, "FLOOD_MASTER_DATABASE_PATH")
            else False,
            "history_dir": str(getattr(config, "FLOOD_HISTORY_DIR", "")),
            "prediction_dir": str(getattr(config, "FLOOD_PREDICTION_DIR", "")),
            "latest_prediction_file": str(latest_prediction_file) if latest_prediction_file else None,
            "upload_entity_dir": str(getattr(config, "UPLOAD_ENTITY_DIR", "")),
        },
    }

# ============================================================
# 12) CLI / MANUAL DEBUG HELPERS
# ============================================================

def print_startup_report() -> None:
    """
    print startup report แบบอ่านง่าย
    """

    report = build_startup_report()

    print("=" * 80)
    print(f"{APP_NAME}")
    print(f"Version: {APP_VERSION}")
    print(f"Environment: {DEFAULT_ENV}")
    print("=" * 80)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print("=" * 80)


def list_registered_routes(app: FastAPI) -> None:
    """
    print route ทั้งหมดที่ FastAPI register ไว้
    """

    print("=" * 80)
    print("REGISTERED ROUTES")
    print("=" * 80)

    routes = sorted(app.routes, key=lambda route: getattr(route, "path", ""))

    for route in routes:
        methods = ",".join(sorted(list(getattr(route, "methods", []) or [])))
        path = getattr(route, "path", "")
        name = getattr(route, "name", "")
        print(f"{path:70s} | {methods:30s} | {name}")

    print("=" * 80)


# ============================================================
# 13) APPLICATION INSTANCE
# ============================================================

app = create_app()


# ============================================================
# 14) MAIN ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    import uvicorn

    print_startup_report()
    list_registered_routes(app)

    logger.info(
        "Starting TIPX FastAPI backend server at http://%s:%s",
        HOST,
        PORT,
    )

    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
    )