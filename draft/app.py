# ============================================================
# FILE: backend/app.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 2 / 20

# 3.2
# ============================================================

"""
backend/app.py

ไฟล์นี้เป็นจุดเริ่มต้นของ Backend Application ทั้งหมดของระบบ TIPX

หน้าที่หลัก:
1. สร้าง Flask Application
2. โหลด config จาก backend/config.py
3. สร้าง folder พื้นฐานของระบบ
4. ตั้งค่า CORS
5. ตั้งค่า logging
6. register API routes จาก backend/api_routes.py
7. register error handlers
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
try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import Flask, Response, jsonify, request, send_from_directory

try:
    from flask_cors import CORS
except Exception:
    CORS = None


from config import (
    APP_NAME,
    APP_SHORT_NAME,
    APP_VERSION,
    APP_DESCRIPTION,
    DEFAULT_ENV,
    DEBUG,
    TESTING,
    DEFAULT_TIMEZONE,
    API_PREFIX,
    PUBLIC_API_PREFIX,
    FRONTEND_DIR,
    PROJECT_ROOT,
    OUTPUT_DIR,
    PACKAGE_DIR,
    PACKAGE_ZIP_DIR,
    LOG_DIR,
    LOG_PATH,
    LOG_LEVEL,
    ENABLE_REQUEST_LOG,
    ENABLE_PIPELINE_LOG,
    CORS_ENABLED,
    CORS_ALLOW_ORIGINS,
    JSON_AS_ASCII,
    JSON_SORT_KEYS,
    MAX_CONTENT_LENGTH_MB,
    FlaskConfig,
    CONFIG,
    ensure_directories,
    validate_basic_config,
    get_config_summary,
    get_input_file_status,
    get_system_path_status,
)


# ============================================================
# 1) LOGGING SETUP
# ============================================================

def setup_logging() -> logging.Logger:
    """
    ตั้งค่า logging กลางของ backend

    Log จะถูกเขียนลง:
    - console
    - output/logs/tipx_backend.log

    ใช้สำหรับ:
    - app startup
    - request log
    - pipeline error
    - API error
    - package export log
    """

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(APP_SHORT_NAME)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | %(levelname)s | %(name)s | "
            "%(module)s.%(funcName)s:%(lineno)d | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    logger.propagate = False

    return logger


logger = setup_logging()


# ============================================================
# 2) JSON RESPONSE HELPERS FOR APP LEVEL
# ============================================================

def app_json_response(
    success: bool,
    message: str,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[Any] = None,
    status_code: int = 200,
) -> Tuple[Response, int]:
    """
    response helper ระดับ app.py

    หมายเหตุ:
    api_routes.py และ utils.py จะมี response helper ที่ละเอียดกว่า
    แต่ app.py ต้องมี helper ของตัวเองเพื่อใช้กับ error handler
    ในกรณีที่ utils.py ยังโหลดไม่ได้หรือเกิด error ก่อน register routes
    """

    payload = {
        "success": bool(success),
        "message": message,
        "data": data if data is not None else {},
        "meta": {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "app": APP_SHORT_NAME,
            "version": APP_VERSION,
            **(meta or {}),
        },
        "errors": errors if errors is not None else [],
    }

    response = jsonify(payload)
    response.status_code = status_code

    return response, status_code


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
# 3) FRONTEND STATIC SERVING
# ============================================================

def frontend_file_exists(filename: str) -> bool:
    """
    ตรวจว่าไฟล์ frontend มีอยู่จริงไหม
    """

    if not filename:
        return False

    target = FRONTEND_DIR / filename
    return target.exists() and target.is_file()


def serve_frontend_file(filename: str) -> Response:
    """
    ส่งไฟล์จาก frontend directory
    """

    return send_from_directory(str(FRONTEND_DIR), filename)


def serve_frontend_index() -> Response:
    """
    ส่ง frontend/index.html

    ใช้ใน route:
    - /
    - /dashboard
    - /external/<package_id>
    """

    index_path = FRONTEND_DIR / "index.html"

    if index_path.exists():
        return send_from_directory(str(FRONTEND_DIR), "index.html")

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

    return Response(fallback_html, mimetype="text/html")


# ============================================================
# 4) APP FACTORY
# ============================================================

def create_app() -> Flask:
    """
    สร้าง Flask app สำหรับระบบ TIPX

    Flow การทำงาน:
    1. ensure directories
    2. create Flask app
    3. load FlaskConfig
    4. configure JSON
    5. configure CORS
    6. register hooks
    7. register frontend routes
    8. register API routes
    9. register error handlers
    10. return app
    """

    ensure_directories()

    app = Flask(
        __name__,
        static_folder=str(FRONTEND_DIR),
        static_url_path="/static",
    )

    app.config.from_object(FlaskConfig)

    app.config["JSON_AS_ASCII"] = JSON_AS_ASCII
    app.config["JSON_SORT_KEYS"] = JSON_SORT_KEYS
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_MB * 1024 * 1024

    app.config["TIPX_CONFIG"] = CONFIG

    configure_cors(app)
    register_request_hooks(app)
    register_frontend_routes(app)
    register_api_routes(app)
    register_error_handlers(app)

    startup_report = build_startup_report()
    logger.info("TIPX backend created successfully")
    logger.info(json.dumps(startup_report, ensure_ascii=False, indent=2, default=str))

    return app


# ============================================================
# 5) CORS
# ============================================================

def configure_cors(app: Flask) -> None:
    """
    ตั้งค่า CORS

    ใช้สำหรับ:
    - frontend dev server
    - local dashboard
    - external viewer local test
    """

    if not CORS_ENABLED:
        logger.info("CORS disabled")
        return

    if CORS is None:
        logger.warning("flask-cors is not installed. CORS setup skipped.")
        return

    CORS(
        app,
        resources={
            f"{API_PREFIX}/*": {
                "origins": CORS_ALLOW_ORIGINS,
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            },
            f"{PUBLIC_API_PREFIX}/*": {
                "origins": "*",
                "methods": ["GET", "POST", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            },
        },
        supports_credentials=False,
    )

    logger.info("CORS enabled")


# ============================================================
# 6) REQUEST HOOKS
# ============================================================

def register_request_hooks(app: Flask) -> None:
    """
    ลงทะเบียน before_request และ after_request

    ใช้สำหรับ:
    - request log
    - response header
    - basic request metadata
    """

    @app.before_request
    def before_request_log() -> None:
        request._tipx_started_at = datetime.now()

        if ENABLE_REQUEST_LOG:
            logger.info(
                "REQUEST | method=%s | path=%s | remote_addr=%s | query=%s",
                request.method,
                request.path,
                request.remote_addr,
                dict(request.args),
            )

    @app.after_request
    def after_request_headers(response: Response) -> Response:
        response.headers["X-TIPX-App"] = APP_SHORT_NAME
        response.headers["X-TIPX-Version"] = APP_VERSION
        response.headers["X-TIPX-Environment"] = DEFAULT_ENV

        started_at = getattr(request, "_tipx_started_at", None)

        if started_at:
            duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
            response.headers["X-TIPX-Duration-Ms"] = str(duration_ms)

            if ENABLE_REQUEST_LOG:
                logger.info(
                    "RESPONSE | method=%s | path=%s | status=%s | duration_ms=%s",
                    request.method,
                    request.path,
                    response.status_code,
                    duration_ms,
                )

        return response


# ============================================================
# 7) FRONTEND ROUTES
# ============================================================

def register_frontend_routes(app: Flask) -> None:
    """
    register route สำหรับ frontend

    Route ที่รองรับ:
    - /
    - /dashboard
    - /external/<package_id>
    - /frontend/<filename>
    - /assets/<filename>

    หมายเหตุ:
    frontend จริงจะอยู่ในไฟล์ลำดับที่ 14-18
    app.py เตรียม route ไว้ล่วงหน้า
    """

    @app.get("/")
    def index() -> Response:
        return serve_frontend_index()

    @app.get("/dashboard")
    def dashboard() -> Response:
        return serve_frontend_index()

    @app.get("/external/<package_id>")
    def external_viewer(package_id: str) -> Response:
        return serve_frontend_index()

    @app.get("/frontend/<path:filename>")
    def frontend_static(filename: str) -> Response:
        if frontend_file_exists(filename):
            return serve_frontend_file(filename)

        response, _ = app_json_response(
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
        return response

    @app.get("/assets/<path:filename>")
    def frontend_assets(filename: str) -> Response:
        assets_dir = FRONTEND_DIR / "assets"

        if (assets_dir / filename).exists():
            return send_from_directory(str(assets_dir), filename)

        response, _ = app_json_response(
            success=False,
            message="Asset file not found",
            data={
                "filename": filename,
                "assets_dir": str(assets_dir),
            },
            errors=[
                {
                    "code": "asset_file_not_found",
                    "message": f"ไม่พบไฟล์ assets/{filename}",
                }
            ],
            status_code=404,
        )
        return response


# ============================================================
# 8) API ROUTES REGISTRATION
# ============================================================

def register_api_routes(app: Flask) -> None:
    """
    Register API routes จาก api_routes.py

    api_routes.py จะเป็นไฟล์ลำดับที่ 3
    ดังนั้นในช่วงที่ยังไม่ได้สร้างไฟล์นั้น app.py ต้องไม่ crash
    ถ้า import ไม่ได้ จะลง fallback routes ให้ก่อน
    """

    try:
        from api_routes import register_routes

        register_routes(app)
        logger.info("API routes registered from api_routes.py")

    except Exception as exc:
        logger.warning("Cannot register api_routes.py. Fallback API routes enabled.")
        logger.warning("api_routes import/register error: %s", str(exc))

        register_fallback_api_routes(app, exc)


def register_fallback_api_routes(app: Flask, route_error: Exception) -> None:
    """
    fallback API routes

    ใช้ชั่วคราวในกรณี api_routes.py ยังไม่ถูกสร้าง
    หรือเกิด import error

    หลังจากสร้าง api_routes.py แล้ว routes จริงจะถูกใช้งานแทน
    """

    @app.get(f"{API_PREFIX}/health")
    def fallback_health() -> Tuple[Response, int]:
        validation = validate_basic_config()

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
            },
            meta={
                "fallback": True,
            },
            status_code=200 if validation["status"] != "error" else 500,
        )

    @app.get(f"{API_PREFIX}/status")
    def fallback_status() -> Tuple[Response, int]:
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
                "paths": get_system_path_status(),
                "inputs": get_input_file_status(),
                "validation": validate_basic_config(),
                "api_routes_registered": False,
                "route_error": str(route_error),
            },
            meta={
                "fallback": True,
            },
        )

    @app.get(f"{API_PREFIX}/config")
    def fallback_config() -> Tuple[Response, int]:
        return app_json_response(
            success=True,
            message="TIPX backend fallback config",
            data=get_config_summary(),
            meta={
                "fallback": True,
            },
        )

    @app.get(f"{API_PREFIX}/routes")
    def fallback_routes() -> Tuple[Response, int]:
        routes = []

        for rule in app.url_map.iter_rules():
            routes.append(
                {
                    "endpoint": rule.endpoint,
                    "methods": sorted(list(rule.methods or [])),
                    "rule": str(rule),
                }
            )

        return app_json_response(
            success=True,
            message="TIPX fallback route list",
            data={
                "routes": routes,
                "api_routes_registered": False,
                "route_error": str(route_error),
            },
            meta={
                "fallback": True,
                "record_count": len(routes),
            },
        )


# ============================================================
# 9) ERROR HANDLERS
# ============================================================

def register_error_handlers(app: Flask) -> None:
    """
    register error handlers ทั้งหมด

    รองรับ:
    - 400
    - 401
    - 403
    - 404
    - 405
    - 413
    - 429
    - 500
    - generic exception
    """

    @app.errorhandler(400)
    def bad_request(error: Exception) -> Tuple[Response, int]:
        return app_json_response(
            success=False,
            message="Bad request",
            errors=[
                {
                    "code": "bad_request",
                    "message": str(error),
                }
            ],
            status_code=400,
        )

    @app.errorhandler(401)
    def unauthorized(error: Exception) -> Tuple[Response, int]:
        return app_json_response(
            success=False,
            message="Unauthorized",
            errors=[
                {
                    "code": "unauthorized",
                    "message": str(error),
                }
            ],
            status_code=401,
        )

    @app.errorhandler(403)
    def forbidden(error: Exception) -> Tuple[Response, int]:
        return app_json_response(
            success=False,
            message="Forbidden",
            errors=[
                {
                    "code": "forbidden",
                    "message": str(error),
                }
            ],
            status_code=403,
        )

    @app.errorhandler(404)
    def not_found(error: Exception) -> Tuple[Response, int]:
        if request.path.startswith(API_PREFIX) or request.path.startswith(PUBLIC_API_PREFIX):
            return app_json_response(
                success=False,
                message="API route not found",
                data={
                    "path": request.path,
                    "method": request.method,
                },
                errors=[
                    {
                        "code": "api_route_not_found",
                        "message": str(error),
                    }
                ],
                status_code=404,
            )

        return serve_frontend_index()

    @app.errorhandler(405)
    def method_not_allowed(error: Exception) -> Tuple[Response, int]:
        return app_json_response(
            success=False,
            message="Method not allowed",
            data={
                "path": request.path,
                "method": request.method,
            },
            errors=[
                {
                    "code": "method_not_allowed",
                    "message": str(error),
                }
            ],
            status_code=405,
        )

    @app.errorhandler(413)
    def request_entity_too_large(error: Exception) -> Tuple[Response, int]:
        return app_json_response(
            success=False,
            message="Uploaded file too large",
            data={
                "max_content_length_mb": MAX_CONTENT_LENGTH_MB,
            },
            errors=[
                {
                    "code": "request_entity_too_large",
                    "message": str(error),
                }
            ],
            status_code=413,
        )

    @app.errorhandler(429)
    def too_many_requests(error: Exception) -> Tuple[Response, int]:
        return app_json_response(
            success=False,
            message="Too many requests",
            errors=[
                {
                    "code": "too_many_requests",
                    "message": str(error),
                }
            ],
            status_code=429,
        )

    @app.errorhandler(500)
    def internal_server_error(error: Exception) -> Tuple[Response, int]:
        logger.exception("Internal server error: %s", str(error))

        return app_json_response(
            success=False,
            message="Internal server error",
            errors=[
                serialize_exception(
                    error,
                    include_traceback=DEBUG,
                )
            ],
            status_code=500,
        )

    @app.errorhandler(Exception)
    def unhandled_exception(error: Exception) -> Tuple[Response, int]:
        logger.exception("Unhandled exception: %s", str(error))

        return app_json_response(
            success=False,
            message="Unhandled server exception",
            data={
                "path": request.path,
                "method": request.method,
            },
            errors=[
                serialize_exception(
                    error,
                    include_traceback=DEBUG,
                )
            ],
            status_code=500,
        )


# ============================================================
# 10) STARTUP REPORT
# ============================================================

def build_startup_report() -> Dict[str, Any]:
    """
    สร้าง startup report สำหรับ log ตอนเริ่มระบบ
    """

    validation = validate_basic_config()

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
        "paths": get_system_path_status(),
        "inputs": get_input_file_status(),
        "validation": validation,
        "api": {
            "api_prefix": API_PREFIX,
            "public_api_prefix": PUBLIC_API_PREFIX,
            "cors_enabled": CORS_ENABLED,
        },
        "frontend": {
            "frontend_dir": str(FRONTEND_DIR),
            "index_exists": (FRONTEND_DIR / "index.html").exists(),
        },
        "output": {
            "output_dir": str(OUTPUT_DIR),
            "package_dir": str(PACKAGE_DIR),
            "package_zip_dir": str(PACKAGE_ZIP_DIR),
        },
    }


# ============================================================
# 11) CLI / MANUAL DEBUG HELPERS
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


def list_registered_routes(app: Flask) -> None:
    """
    print route ทั้งหมดที่ Flask register ไว้
    """

    print("=" * 80)
    print("REGISTERED ROUTES")
    print("=" * 80)

    rules = sorted(app.url_map.iter_rules(), key=lambda r: str(r))

    for rule in rules:
        methods = ",".join(sorted(rule.methods or []))
        print(f"{str(rule):60s} | {methods:30s} | {rule.endpoint}")

    print("=" * 80)


# ============================================================
# 12) APPLICATION INSTANCE
# ============================================================

app = create_app()


# ============================================================
# 13) MAIN ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    print_startup_report()
    list_registered_routes(app)

    host = "127.0.0.1"
    port = 5000

    logger.info(
        "Starting TIPX backend server at http://%s:%s",
        host,
        port,
    )

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )