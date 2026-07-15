# ============================================================
# FILE: backend/api_routes.py
# TIPX Enterprise Intelligence Dashboard
# FastAPI API Gateway
# ============================================================

"""
backend/api_routes.py

ไฟล์นี้เป็นศูนย์กลาง API Routes ทั้งหมดของระบบ TIPX

หน้าที่หลัก:
1. สร้าง FastAPI APIRouter
2. รวม route ฐานหลักเดิม + flood route ใหม่
3. เชื่อม request จาก frontend ไปยัง service layer
4. จัดการ query parameter, filter payload, pagination, force refresh
5. ส่ง response กลับเป็น JSON format มาตรฐาน
6. รองรับ service dispatcher แบบ lazy import
7. รองรับ contract mismatch guard
8. รองรับ Excel/MySQL source switch ผ่าน config
9. รองรับ fallback กรณี service บางไฟล์ยังไม่พร้อม
"""

from __future__ import annotations

try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)

import inspect
import traceback
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

import config
from config import (
    APP_NAME,
    APP_SHORT_NAME,
    APP_VERSION,
    APP_DESCRIPTION,
    DEFAULT_ENV,
    API_PREFIX,
    PUBLIC_API_PREFIX,
    DEFAULT_TABLE_PAGE_SIZE,
    MAX_TABLE_PAGE_SIZE,
    GRAPH_DEFAULT_MODE,
    GRAPH_DEFAULT_DEPTH,
    GRAPH_DEFAULT_MAX_NODES,
    PACKAGE_COMPONENTS,
    PACKAGE_SECURITY_OPTIONS,
    validate_basic_config,
    get_config_summary,
    get_input_file_status,
    get_system_path_status,
)


# ============================================================
# 1) ROUTER
# ============================================================

def generate_operation_id(route: Any) -> str:
    methods = "_".join(
        sorted(
            method.lower()
            for method in (getattr(route, "methods", set()) or set())
            if method not in {"HEAD", "OPTIONS"}
        )
    )

    route_path = str(
        getattr(
            route,
            "path_format",
            getattr(route, "path", ""),
        )
        or ""
    )

    normalized_path = (
        route_path
        .strip("/")
        .replace("/", "_")
        .replace("{", "")
        .replace("}", "")
        .replace("-", "_")
    )

    return (
        f"{route.name}_"
        f"{methods or 'route'}_"
        f"{normalized_path or 'root'}"
    )


PUBLIC_ROUTER_PREFIX: str = (
    PUBLIC_API_PREFIX[len(API_PREFIX):]
    if PUBLIC_API_PREFIX.startswith(API_PREFIX)
    else PUBLIC_API_PREFIX
)

if not PUBLIC_ROUTER_PREFIX:
    PUBLIC_ROUTER_PREFIX = "/public"

router = APIRouter(
    prefix=API_PREFIX,
    generate_unique_id_function=generate_operation_id,
)

public_router = APIRouter(
    prefix=PUBLIC_ROUTER_PREFIX,
    generate_unique_id_function=generate_operation_id,
)


# ============================================================
# 2) RESPONSE HELPERS
# ============================================================

STANDARD_RESPONSE_KEYS = {"success", "message", "data", "meta", "errors"}


def now_iso() -> str:
    """
    คืนเวลาปัจจุบันแบบ ISO string
    """

    return datetime.now().isoformat(timespec="seconds")


def is_standard_api_payload(value: Any) -> bool:
    return isinstance(value, dict) and STANDARD_RESPONSE_KEYS.issubset(set(value.keys()))


def is_service_error_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    if value.get("__service_error__") is True:
        return True

    if is_standard_api_payload(value) and value.get("success") is False:
        return True

    meta = value.get("meta")
    if isinstance(meta, dict) and meta.get("fallback") is True:
        return True

    return False


def response_payload(
    success: bool,
    message: str,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[Any] = None,
) -> Dict[str, Any]:
    return {
        "success": bool(success),
        "message": message,
        "data": data if data is not None else {},
        "meta": {
            "timestamp": now_iso(),
            "app": APP_SHORT_NAME,
            "version": APP_VERSION,
            **(meta or {}),
        },
        "errors": errors if errors is not None else [],
    }


def success_response(
    data: Optional[Any] = None,
    message: str = "OK",
    meta: Optional[Dict[str, Any]] = None,
    status_code: int = 200,
) -> JSONResponse:
    """
    ส่ง response สำเร็จใน format มาตรฐานของ TIPX
    """

    if is_standard_api_payload(data):
        payload = dict(data)
        payload.pop("__service_error__", None)

        response_status = status_code

        if payload.get("success") is False:
            response_status = int(payload.get("meta", {}).get("status_code", 500) or 500)

        return JSONResponse(
            status_code=response_status,
            content=payload,
        )

    return JSONResponse(
        status_code=status_code,
        content=response_payload(
            success=True,
            message=message,
            data=data if data is not None else {},
            meta=meta,
            errors=[],
        ),
    )


def error_response(
    message: str = "ERROR",
    errors: Optional[Any] = None,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
    status_code: int = 400,
    legacy_error: Optional[str] = None,
) -> JSONResponse:
    """
    ส่ง response error ใน format มาตรฐานของ TIPX
    """

    payload = response_payload(
        success=False,
        message=message,
        data=data if data is not None else {},
        meta={
            **(meta or {}),
            "status_code": status_code,
        },
        errors=errors if errors is not None else [],
    )

    if legacy_error is not None:
        payload["error"] = legacy_error

    return JSONResponse(
        status_code=status_code,
        content=payload,
    )


def exception_response(
    exc: Exception,
    message: str = "Unhandled API exception",
    status_code: int = 500,
    include_traceback: bool = False,
) -> JSONResponse:
    error_payload: Dict[str, Any] = {
        "type": exc.__class__.__name__,
        "message": str(exc) if config.DEBUG else message,
    }

    if include_traceback and config.DEBUG:
        error_payload["traceback"] = traceback.format_exc()

    return error_response(
        message=message,
        errors=[error_payload],
        status_code=status_code,
        legacy_error=str(exc) if config.DEBUG else None,
    )


# ============================================================
# 3) REQUEST PARSING HELPERS
# ============================================================

def get_arg(request: Request, name: str, default: Optional[Any] = None) -> Optional[str]:
    raw = request.query_params.get(name)

    if raw is None:
        return default

    return str(raw).strip()


def get_first_arg(request: Request, names: List[str], default: Optional[Any] = None) -> Optional[str]:
    for name in names:
        raw = get_arg(request, name, None)
        if raw not in (None, ""):
            return raw

    return default


def get_bool_arg(request: Request, name: str, default: bool = False) -> bool:
    raw = request.query_params.get(name)

    if raw is None:
        return default

    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def get_first_bool_arg(request: Request, names: List[str], default: bool = False) -> bool:
    for name in names:
        if name in request.query_params:
            return get_bool_arg(request, name, default)

    return default


def parse_bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "y", "on"}:
        return True

    if text in {"0", "false", "no", "n", "off"}:
        return False

    return default


def clamp_int_value(
    value: int,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    if min_value is not None:
        value = max(min_value, value)

    if max_value is not None:
        value = min(max_value, value)

    return value


def get_int_arg(
    request: Request,
    name: str,
    default: int,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    raw = request.query_params.get(name)

    try:
        value = int(raw) if raw is not None and raw != "" else int(default)
    except Exception:
        value = int(default)

    return clamp_int_value(value, min_value=min_value, max_value=max_value)


def get_first_int_arg(
    request: Request,
    names: List[str],
    default: int,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    for name in names:
        if name in request.query_params:
            return get_int_arg(
                request,
                name,
                default,
                min_value=min_value,
                max_value=max_value,
            )

    return clamp_int_value(int(default), min_value=min_value, max_value=max_value)


def get_float_arg(request: Request, name: str, default: Optional[float] = None) -> Optional[float]:
    raw = request.query_params.get(name)

    if raw is None or raw == "":
        return default

    try:
        return float(raw)
    except Exception:
        return default


def get_first_float_arg(
    request: Request,
    names: List[str],
    default: Optional[float] = None,
) -> Optional[float]:
    for name in names:
        value = get_float_arg(request, name, None)
        if value is not None:
            return value

    return default


def get_str_arg(request: Request, name: str, default: str = "") -> str:
    raw = request.query_params.get(name)

    if raw is None:
        return default

    return str(raw).strip()


def get_list_arg(request: Request, name: str) -> List[str]:
    values = request.query_params.getlist(name)

    if not values:
        raw = request.query_params.get(name, "")
        values = [raw] if raw else []

    result: List[str] = []

    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                result.append(item)

    return result


async def get_json_payload(
    request: Request,
    default: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if default is None:
        default = {}

    try:
        payload = await request.json()
        if isinstance(payload, dict):
            return payload
        return dict(default)
    except Exception:
        return dict(default)


def get_pagination_params(request: Request) -> Dict[str, int]:
    page = get_int_arg(request, "page", 1, min_value=1)
    page_size = get_first_int_arg(
        request,
        ["page_size", "limit"],
        DEFAULT_TABLE_PAGE_SIZE,
        min_value=1,
        max_value=MAX_TABLE_PAGE_SIZE,
    )

    offset = get_int_arg(request, "offset", (page - 1) * page_size, min_value=0)

    return {
        "page": page,
        "page_size": page_size,
        "limit": page_size,
        "offset": offset,
    }


def get_sort_params(request: Request) -> Dict[str, str]:
    return {
        "sort_by": get_str_arg(request, "sort_by", ""),
        "sort_dir": get_str_arg(request, "sort_dir", "asc").lower(),
    }


def get_common_query_context(request: Request) -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "force_refresh": get_bool_arg(request, "force_refresh", False),
        "search": get_str_arg(request, "search", ""),
        "query": get_first_arg(request, ["query", "q", "search"], ""),
        "target": get_str_arg(request, "target", ""),
        **get_pagination_params(request),
        **get_sort_params(request),
    }

    simple_filters = {
        "province": get_list_arg(request, "province"),
        "district": get_list_arg(request, "district"),
        "subdistrict": get_list_arg(request, "subdistrict"),
        "product": get_list_arg(request, "product"),
        "subclass": get_list_arg(request, "subclass"),
        "policy_status": get_list_arg(request, "policy_status"),
        "loss_ratio_band": get_list_arg(request, "loss_ratio_band"),
        "flood_risk_level": get_list_arg(request, "flood_risk_level"),
        "risk_level": get_list_arg(request, "risk_level") or get_list_arg(request, "risk"),
        "risk_status": get_list_arg(request, "risk_status"),
        "wtip": get_list_arg(request, "wtip"),
        "company_size": get_list_arg(request, "company_size"),
        "business_type_tsic": get_list_arg(request, "business_type_tsic"),
        "director_id": get_list_arg(request, "director_id"),
        "policy_year": get_list_arg(request, "policy_year"),
        "has_policy": request.query_params.get("has_policy"),
        "has_linkage": request.query_params.get("has_linkage"),
        "has_location": request.query_params.get("has_location"),
        "has_flood_context": request.query_params.get("has_flood_context"),
        "premium_min": get_float_arg(request, "premium_min"),
        "premium_max": get_float_arg(request, "premium_max"),
        "suminsure_min": get_float_arg(request, "suminsure_min"),
        "suminsure_max": get_float_arg(request, "suminsure_max"),
        "loss_ratio_min": get_float_arg(request, "loss_ratio_min"),
        "loss_ratio_max": get_float_arg(request, "loss_ratio_max"),
    }

    context["filters"] = {
        key: value
        for key, value in simple_filters.items()
        if value not in (None, "", [], {})
    }

    return context


def get_prediction_filters(request: Request) -> Dict[str, Any]:
    aliases = getattr(config, "PREDICTION_QUERY_PARAM_ALIASES", {})

    data_date = get_first_arg(request, aliases.get("data_date", ["data_date", "predict_date", "file_date"]), None)
    province = get_first_arg(request, aliases.get("province", ["province", "province_model"]), None)
    risk_level = get_first_arg(request, aliases.get("risk_level", ["risk_level", "warning_level_predict"]), None)
    station = get_first_arg(request, aliases.get("station", ["station", "station_name", "station_id"]), None)
    base_date = get_first_arg(request, aliases.get("base_date", ["base_date"]), None)
    target_date = get_first_arg(request, aliases.get("target_date", ["target_date"]), None)
    forecast_horizon_day = get_first_int_arg(
        request,
        aliases.get("forecast_horizon_day", ["forecast_horizon_day", "horizon"]),
        0,
        min_value=0,
    )

    filters: Dict[str, Any] = {
        "data_date": data_date,
        "province": province,
        "province_model": province,
        "risk_level": risk_level,
        "risk_status": risk_level,
        "warning_level": risk_level,
        "warning_level_predict": risk_level,
        "station": station,
        "station_name": station,
        "station_id": station,
        "station_code": station,
        "base_date": base_date,
        "target_date": target_date,
        "forecast_horizon_day": forecast_horizon_day if forecast_horizon_day > 0 else None,
        "map_ready": get_first_arg(request, ["map_ready", "has_location"], None),
    }

    return {
        key: value
        for key, value in filters.items()
        if value not in (None, "", [], {})
    }


def get_dashboard_province_insight_filters(request: Request) -> Dict[str, Any]:
    return {
        "province": get_first_arg(
            request,
            ["province", "province_model", "prediction_province", "prediction_province_model"],
            None,
        ),
        "risk_level": get_first_arg(
            request,
            ["risk", "risk_level", "risk_status", "warning_level", "warning_level_predict"],
            None,
        ),
        "limit_prediction": get_first_int_arg(
            request,
            ["limit_prediction", "prediction_limit"],
            3,
            min_value=1,
            max_value=50,
        ),
        "limit_ranking": get_first_int_arg(
            request,
            ["limit_ranking", "ranking_limit", "top"],
            5,
            min_value=1,
            max_value=50,
        ),
        "force_refresh": get_bool_arg(request, "force_refresh", False),
    }


# ============================================================
# 4) SERVICE DISPATCH HELPERS
# ============================================================

SERVICE_MODULES: Dict[str, str] = {
    "company": "company_policy_service",
    "policy": "company_policy_service",
    "company_policy": "company_policy_service",
    "linkage": "linkage_service",
    "flood": "flood_spatial_service",
    "prediction": "flood_spatial_service",
    "forecast": "flood_spatial_service",
    "history": "flood_spatial_service",
    "master": "flood_spatial_service",
    "spatial": "flood_spatial_service",
    "map": "map_graph_service",
    "graph": "map_graph_service",
    "dashboard": "dashboard_package_service",
    "charts": "dashboard_package_service",
    "package": "dashboard_package_service",
    "filter": "filter_engine",
    "data_quality": "data_quality",
    "admin": "data_quality",
    "entity": "entity_upload_service",
    "upload": "entity_upload_service",
    "security": "security",
    "utils": "utils",
    "schemas": "schemas",
}

DATA_SOURCE_DOMAINS: set[str] = {
    "flood",
    "prediction",
    "forecast",
    "history",
    "master",
    "spatial",
    "map",
    "dashboard",
    "charts",
    "admin",
    "entity",
    "upload",
}


def mysql_not_implemented_payload(domain: str, function_name: str, fallback_data: Optional[Any] = None) -> Dict[str, Any]:
    return {
        "__service_error__": True,
        "success": False,
        "message": getattr(config, "DATA_SOURCE_NOT_IMPLEMENTED_MESSAGE", "MySQL data source is not implemented."),
        "data": fallback_data if fallback_data is not None else {},
        "meta": {
            "fallback": True,
            "domain": domain,
            "service": function_name,
            "source": "mysql",
            "status_code": 501,
        },
        "errors": [
            {
                "type": "NotImplementedError",
                "message": getattr(config, "DATA_SOURCE_NOT_IMPLEMENTED_MESSAGE", "MySQL data source is not implemented."),
            }
        ],
    }


def contract_mismatch_payload(
    import_path: str,
    function_name: str,
    dropped_kwargs: List[str],
    fallback_data: Optional[Any] = None,
) -> Dict[str, Any]:
    return {
        "__service_error__": True,
        "success": False,
        "message": "Service function contract mismatch.",
        "data": fallback_data if fallback_data is not None else {},
        "meta": {
            "fallback": True,
            "module": import_path,
            "service": function_name,
            "status_code": 501,
            "dropped_kwargs": dropped_kwargs,
        },
        "errors": [
            {
                "type": "ServiceContractMismatch",
                "message": f"{import_path}.{function_name} does not accept arguments: {', '.join(dropped_kwargs)}",
                "dropped_kwargs": dropped_kwargs,
            }
        ],
    }


def filter_callable_kwargs(func: Callable[..., Any], kwargs: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    signature = inspect.signature(func)

    has_var_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )

    if has_var_keyword:
        return dict(kwargs), []

    allowed_names = set(signature.parameters.keys())
    accepted: Dict[str, Any] = {}
    dropped: List[str] = []

    for key, value in kwargs.items():
        if key in allowed_names:
            accepted[key] = value
        else:
            dropped.append(key)

    return accepted, dropped


def call_data_service(
    domain: str,
    function_name: str,
    fallback_data: Optional[Any] = None,
    *args: Any,
    strict_filter_params: bool = False,
    inactive_filter_keys: Optional[List[str]] = None,
    **kwargs: Any,
) -> Any:
    if fallback_data is None:
        fallback_data = {}

    domain_key = str(domain or "").strip().lower()

    if domain_key in DATA_SOURCE_DOMAINS:
        if getattr(config, "USE_MYSQL_DATA_SOURCE", False) and not getattr(config, "USE_EXCEL_DATA_SOURCE", True):
            return mysql_not_implemented_payload(domain_key, function_name, fallback_data=fallback_data)

    import_path = SERVICE_MODULES.get(domain_key, domain_key)

    try:
        module = import_module(import_path)
        func = getattr(module, function_name)

        safe_kwargs, dropped_kwargs = filter_callable_kwargs(func, kwargs)

        inactive_set = set(inactive_filter_keys or [])
        active_dropped = [
            key
            for key in dropped_kwargs
            if key not in inactive_set
        ]

        if strict_filter_params and active_dropped:
            return contract_mismatch_payload(
                import_path=import_path,
                function_name=function_name,
                dropped_kwargs=active_dropped,
                fallback_data=fallback_data,
            )

        return func(*args, **safe_kwargs)

    except Exception as exc:
        status_code = 503 if isinstance(exc, (ImportError, AttributeError, ModuleNotFoundError)) else 500

        return {
            "__service_error__": True,
            "success": False,
            "message": (
                "Service function is not available."
                if status_code == 503
                else "Service function failed."
            ),
            "data": fallback_data,
            "meta": {
                "fallback": True,
                "module": import_path,
                "service": function_name,
                "status_code": status_code,
            },
            "errors": [
                {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            ],
        }


def safe_call(
    import_path: str,
    function_name: str,
    fallback_data: Optional[Any] = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    if fallback_data is None:
        fallback_data = {}

    try:
        module = import_module(import_path)
        func = getattr(module, function_name)
        safe_kwargs, _dropped = filter_callable_kwargs(func, kwargs)

        return func(*args, **safe_kwargs)

    except Exception as exc:
        status_code = 503 if isinstance(exc, (ImportError, AttributeError, ModuleNotFoundError)) else 500

        return {
            "__service_error__": True,
            "success": False,
            "message": (
                "Service function is not available."
                if status_code == 503
                else "Service function failed."
            ),
            "data": fallback_data,
            "meta": {
                "fallback": True,
                "module": import_path,
                "service": function_name,
                "status_code": status_code,
            },
            "errors": [
                {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            ],
        }


def service_meta(result: Any, service_name: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "service": service_name,
    }

    if isinstance(result, dict):
        if "fallback" in result:
            meta["fallback"] = result.get("fallback")

        result_meta = result.get("meta")
        if isinstance(result_meta, dict):
            for key in ["fallback", "cache_used", "cache_key", "source", "status_code"]:
                if key in result_meta:
                    meta[key] = result_meta.get(key)

        if "record_count" in result:
            meta["record_count"] = result.get("record_count")

        if "cache_used" in result:
            meta["cache_used"] = result.get("cache_used")

    return meta


def unwrap_service_result(result: Any) -> Any:
    return result


def service_response(
    result: Any,
    message: str,
    service_name: str,
    status_code: int = 200,
) -> JSONResponse:
    return success_response(
        message=message,
        data=unwrap_service_result(result),
        meta=service_meta(result, service_name),
        status_code=status_code,
    )


# ============================================================
# 5) CORE API
# ============================================================

@router.get("/health")
async def api_health() -> JSONResponse:
    validation = validate_basic_config()

    data = {
        "app": APP_NAME,
        "short_name": APP_SHORT_NAME,
        "version": APP_VERSION,
        "description": APP_DESCRIPTION,
        "environment": DEFAULT_ENV,
        "status": validation["status"],
        "validation": validation,
    }

    if validation["status"] == "error":
        return error_response(
            message="TIPX health check failed",
            data=data,
            errors=[
                {
                    "type": "ConfigurationError",
                    "message": "Backend configuration validation failed.",
                }
            ],
            meta={
                "module": "core",
            },
            status_code=500,
        )

    return success_response(
        message="TIPX health check",
        data=data,
        meta={
            "module": "core",
        },
        status_code=200,
    )

@router.get("/status")
async def api_status() -> JSONResponse:
    validation = validate_basic_config()

    return success_response(
        message="TIPX system status",
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
            "validation": validation,
            "modules": {
                "company_policy": "company_policy_service.py",
                "linkage": "linkage_service.py",
                "flood_spatial": "flood_spatial_service.py",
                "map_graph": "map_graph_service.py",
                "dashboard_package": "dashboard_package_service.py",
                "filter_engine": "filter_engine.py",
                "data_quality": "data_quality.py",
                "security": "security.py",
                "schemas": "schemas.py",
                "utils": "utils.py",
            },
        },
        meta={
            "module": "core",
        },
    )


@router.get("/config")
async def api_config() -> JSONResponse:
    return success_response(
        message="TIPX config summary",
        data=get_config_summary(),
        meta={
            "module": "core",
        },
    )


@router.get("/paths")
async def api_paths() -> JSONResponse:
    return success_response(
        message="TIPX path status",
        data={
            "paths": config.get_runtime_paths() if hasattr(config, "get_runtime_paths") else get_system_path_status(),
            "path_status": config.get_path_status() if hasattr(config, "get_path_status") else {},
            "warnings": config.validate_startup_paths() if hasattr(config, "validate_startup_paths") else [],
        },
        meta={
            "module": "core",
        },
    )


@router.get("/inputs")
async def api_inputs() -> JSONResponse:
    return success_response(
        message="TIPX input status",
        data=get_input_file_status(),
        meta={
            "module": "core",
        },
    )


@router.get("/routes")
async def api_routes(request: Request) -> JSONResponse:
    routes: List[Dict[str, Any]] = []

    for route in request.app.routes:
        route_path = getattr(route, "path", None)
        methods = sorted(
            [
                method
                for method in list(getattr(route, "methods", []) or [])
                if method not in {"HEAD", "OPTIONS"}
            ]
        )

        if route_path:
            routes.append(
                {
                    "name": getattr(route, "name", None),
                    "path": route_path,
                    "methods": methods,
                }
            )

    routes = sorted(routes, key=lambda row: row.get("path") or "")

    catalog = call_data_service(
        "schemas",
        "get_api_route_catalog",
        {},
    )

    route_list = call_data_service(
        "schemas",
        "flatten_api_route_catalog",
        [],
    )

    return success_response(
        message="TIPX registered routes",
        data={
            "routes": routes,
            "catalog": catalog if not is_service_error_payload(catalog) else {},
            "catalog_routes": route_list if not is_service_error_payload(route_list) else [],
        },
        meta={
            "module": "core",
            "record_count": len(routes),
        },
    )

@router.get("/schema")
async def api_schema() -> JSONResponse:
    result = call_data_service(
        "schemas",
        "get_frontend_schema_bundle",
        {
            "api": {
                "prefix": API_PREFIX,
                "public_prefix": PUBLIC_API_PREFIX,
            },
            "fields": {},
            "datasets": {},
            "routes": {},
        },
    )

    return service_response(result, "Frontend schema bundle", "schemas.get_frontend_schema_bundle")


# ============================================================
# 6) COMPANY API
# ============================================================

@router.get("/companies")
async def api_companies(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_company_list",
        {
            "records": [],
            "total": 0,
            "message": "company_policy_service.get_company_list not ready",
        },
        context=context,
    )

    return service_response(result, "Company list", "company_policy_service.get_company_list")


@router.get("/companies/summary")
async def api_companies_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_company_summary",
        {
            "total_companies": 0,
            "companies_with_policy": 0,
            "companies_with_linkage": 0,
            "companies_with_location": 0,
            "companies_with_flood_context": 0,
        },
        context=context,
    )

    return service_response(result, "Company summary", "company_policy_service.get_company_summary")


@router.get("/companies/ranking/income")
async def api_companies_ranking_income(
    request: Request,
) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_company_income_ranking",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(
        result,
        "Company income ranking",
        "company_policy_service.get_company_income_ranking",
    )


@router.get("/companies/ranking/capital")
async def api_companies_ranking_capital(
    request: Request,
) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_company_capital_ranking",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(
        result,
        "Company capital ranking",
        "company_policy_service.get_company_capital_ranking",
    )


@router.get("/companies/source-flags")
async def api_companies_source_flags() -> JSONResponse:
    result = call_data_service(
        "company",
        "get_company_source_flags",
        {
            "has_policy": 0,
            "has_linkage": 0,
            "has_location": 0,
            "has_flood_context": 0,
        },
    )

    return service_response(
        result,
        "Company source flags",
        "company_policy_service.get_company_source_flags",
    )


@router.get("/companies/missing-policy")
async def api_companies_missing_policy(
    request: Request,
) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_companies_missing_policy",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(
        result,
        "Companies missing policy",
        "company_policy_service.get_companies_missing_policy",
    )


@router.get("/companies/missing-linkage")
async def api_companies_missing_linkage(
    request: Request,
) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_companies_missing_linkage",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(
        result,
        "Companies missing linkage",
        "company_policy_service.get_companies_missing_linkage",
    )


@router.get("/companies/missing-location")
async def api_companies_missing_location(
    request: Request,
) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_companies_missing_location",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(
        result,
        "Companies missing location",
        "company_policy_service.get_companies_missing_location",
    )


@router.get("/companies/{tax_id}")
async def api_company_detail(
    tax_id: str,
    request: Request,
) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_company_detail",
        {
            "tax_id": tax_id,
            "company": None,
            "message": "company detail not ready",
        },
        tax_id=tax_id,
        context=context,
    )

    return service_response(
        result,
        "Company detail",
        "company_policy_service.get_company_detail",
    )

@router.get("/companies/ranking/income")
async def api_companies_ranking_income(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_company_income_ranking",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Company income ranking", "company_policy_service.get_company_income_ranking")


@router.get("/companies/ranking/capital")
async def api_companies_ranking_capital(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_company_capital_ranking",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Company capital ranking", "company_policy_service.get_company_capital_ranking")


@router.get("/companies/source-flags")
async def api_companies_source_flags() -> JSONResponse:
    result = call_data_service(
        "company",
        "get_company_source_flags",
        {
            "has_policy": 0,
            "has_linkage": 0,
            "has_location": 0,
            "has_flood_context": 0,
        },
    )

    return service_response(result, "Company source flags", "company_policy_service.get_company_source_flags")


@router.get("/companies/missing-policy")
async def api_companies_missing_policy(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_companies_missing_policy",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Companies missing policy", "company_policy_service.get_companies_missing_policy")


@router.get("/companies/missing-linkage")
async def api_companies_missing_linkage(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_companies_missing_linkage",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Companies missing linkage", "company_policy_service.get_companies_missing_linkage")


@router.get("/companies/missing-location")
async def api_companies_missing_location(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "company",
        "get_companies_missing_location",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Companies missing location", "company_policy_service.get_companies_missing_location")


# ============================================================
# 7) POLICY API
# ============================================================

@router.get("/policy/summary")
async def api_policy_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_summary",
        {
            "total_premium": 0,
            "total_loss": 0,
            "total_suminsure": 0,
            "total_policy_count": 0,
            "average_loss_ratio": 0,
        },
        context=context,
    )

    return service_response(result, "Policy summary", "company_policy_service.get_policy_summary")


@router.get("/policy/companies")
async def api_policy_companies(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_companies",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Policy companies", "company_policy_service.get_policy_companies")


@router.get("/policy/company/{tax_id}")
async def api_policy_company(tax_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_company_detail",
        {
            "tax_id": tax_id,
            "summary": {},
            "records": [],
        },
        tax_id=tax_id,
        context=context,
    )

    return service_response(result, "Policy company detail", "company_policy_service.get_policy_company_detail")


@router.get("/policy/company/{tax_id}/summary")
async def api_policy_company_summary(tax_id: str) -> JSONResponse:
    result = call_data_service(
        "policy",
        "get_policy_company_summary",
        {
            "tax_id": tax_id,
            "summary": {},
        },
        tax_id=tax_id,
    )

    return service_response(result, "Policy company summary", "company_policy_service.get_policy_company_summary")


@router.get("/policy/company/{tax_id}/table")
async def api_policy_company_table(tax_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_company_table",
        {
            "tax_id": tax_id,
            "records": [],
            "total": 0,
        },
        tax_id=tax_id,
        context=context,
    )

    return service_response(result, "Policy company table", "company_policy_service.get_policy_company_table")


@router.get("/policy/company/{tax_id}/trend")
async def api_policy_company_trend(tax_id: str) -> JSONResponse:
    result = call_data_service(
        "policy",
        "get_policy_company_trend",
        {
            "tax_id": tax_id,
            "series": [],
        },
        tax_id=tax_id,
    )

    return service_response(result, "Policy company trend", "company_policy_service.get_policy_company_trend")


@router.get("/policy/product-summary")
async def api_policy_product_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_product_summary",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Policy product summary", "company_policy_service.get_policy_product_summary")


@router.get("/policy/subclass-summary")
async def api_policy_subclass_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_subclass_summary",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Policy subclass summary", "company_policy_service.get_policy_subclass_summary")


@router.get("/policy/yearly-summary")
async def api_policy_yearly_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_yearly_summary",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Policy yearly summary", "company_policy_service.get_policy_yearly_summary")


@router.get("/policy/loss-ratio-ranking")
async def api_policy_loss_ratio_ranking(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_loss_ratio_ranking",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Policy loss ratio ranking", "company_policy_service.get_policy_loss_ratio_ranking")


@router.get("/policy/high-loss")
async def api_policy_high_loss(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_high_loss_companies",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "High loss policy companies", "company_policy_service.get_policy_high_loss_companies")


@router.get("/policy/exposure")
async def api_policy_exposure(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "policy",
        "get_policy_exposure",
        {
            "records": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Policy exposure", "company_policy_service.get_policy_exposure")


# ============================================================
# 8) LINKAGE API
# ============================================================

@router.get("/linkage/summary")
async def api_linkage_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "linkage",
        "get_linkage_summary",
        {
            "total_companies": 0,
            "total_directors": 0,
            "total_edges": 0,
            "key_connector_count": 0,
        },
        context=context,
    )

    return service_response(result, "Linkage summary", "linkage_service.get_linkage_summary")


@router.get("/linkage/graph")
async def api_linkage_graph(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    graph_context = {
        **context,
        "mode": get_str_arg(request, "mode", GRAPH_DEFAULT_MODE),
        "depth": get_int_arg(request, "depth", GRAPH_DEFAULT_DEPTH, min_value=1, max_value=5),
        "max_nodes": get_int_arg(request, "max_nodes", GRAPH_DEFAULT_MAX_NODES, min_value=10, max_value=1500),
        "tax_id": get_str_arg(request, "tax_id", ""),
        "director_id": get_str_arg(request, "director_id", ""),
        "include_shared_edges": get_bool_arg(request, "include_shared_edges", True),
        "include_policy": get_bool_arg(request, "include_policy", True),
        "include_flood": get_bool_arg(request, "include_flood", True),
    }

    result = call_data_service(
        "linkage",
        "get_linkage_graph",
        {
            "nodes": [],
            "edges": [],
            "limited": False,
            "summary": {},
        },
        context=graph_context,
    )

    return service_response(result, "Linkage graph", "linkage_service.get_linkage_graph")


@router.get("/linkage/company/{tax_id}")
async def api_linkage_company(tax_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "linkage",
        "get_linkage_company_detail",
        {
            "tax_id": tax_id,
            "directors": [],
            "connected_companies": [],
            "edges": [],
        },
        tax_id=tax_id,
        context=context,
    )

    return service_response(result, "Linkage company detail", "linkage_service.get_linkage_company_detail")


@router.get("/linkage/director/{director_id}")
async def api_linkage_director(director_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "linkage",
        "get_linkage_director_detail",
        {
            "director_id": director_id,
            "director": {},
            "companies": [],
            "edges": [],
        },
        director_id=director_id,
        context=context,
    )

    return service_response(result, "Linkage director detail", "linkage_service.get_linkage_director_detail")


@router.get("/linkage/key-connectors")
async def api_linkage_key_connectors(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "linkage",
        "get_key_connectors",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Key connectors", "linkage_service.get_key_connectors")


@router.get("/linkage/shared-directors")
async def api_linkage_shared_directors(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "linkage",
        "get_shared_director_links",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Shared director links", "linkage_service.get_shared_director_links")


@router.get("/linkage/exposure-by-director")
async def api_linkage_exposure_by_director(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "linkage",
        "get_exposure_by_director",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Exposure by director", "linkage_service.get_exposure_by_director")


# ============================================================
# 9) FLOOD / LATEST / MASTER / HISTORY API
# ============================================================

@router.get("/flood/summary")
@router.get("/summary")
async def api_flood_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_flood_summary",
        {
            "rainfall_station_count": 0,
            "waterlevel_station_count": 0,
            "large_dam_count": 0,
            "medium_dam_count": 0,
            "risk_counts": {},
        },
        context=context,
    )

    return service_response(result, "Flood summary", "flood_spatial_service.get_flood_summary")


@router.get("/flood/rainfall/latest")
@router.get("/latest/rainfall")
async def api_flood_rainfall_latest(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_latest_rainfall",
        {
            "records": [],
            "total": 0,
        },
        context=context,
        strict_filter_params=True,
    )

    return service_response(result, "Rainfall latest", "flood_spatial_service.get_latest_rainfall")


@router.get("/flood/waterlevel/latest")
@router.get("/latest/waterlevel")
async def api_flood_waterlevel_latest(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_latest_waterlevel",
        {
            "records": [],
            "total": 0,
        },
        context=context,
        strict_filter_params=True,
    )

    return service_response(result, "Waterlevel latest", "flood_spatial_service.get_latest_waterlevel")


@router.get("/flood/dam/large/latest")
@router.get("/latest/dam/large")
async def api_flood_large_dam_latest(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_latest_large_dam",
        {
            "records": [],
            "total": 0,
        },
        context=context,
        strict_filter_params=True,
    )

    return service_response(result, "Large dam latest", "flood_spatial_service.get_latest_large_dam")


@router.get("/flood/dam/medium/latest")
@router.get("/latest/dam/medium")
async def api_flood_medium_dam_latest(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_latest_medium_dam",
        {
            "records": [],
            "total": 0,
        },
        context=context,
        strict_filter_params=True,
    )

    return service_response(result, "Medium dam latest", "flood_spatial_service.get_latest_medium_dam")


@router.get("/latest/dam")
async def api_latest_dam(request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    dam_size = get_first_arg(request, ["dam_size", "size"], "all")

    result = call_data_service(
        "flood",
        "get_latest_dam",
        {
            "records": [],
            "total": 0,
        },
        context={
            **context,
            "dam_size": dam_size,
        },
        strict_filter_params=True,
    )

    return service_response(result, "Dam latest", "flood_spatial_service.get_latest_dam")


@router.get("/latest/all-long")
@router.get("/latest/all_long")
async def api_latest_all_long(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_all_long_latest",
        {
            "records": [],
            "total": 0,
        },
        context=context,
        strict_filter_params=True,
    )

    return service_response(result, "All long latest", "flood_spatial_service.get_all_long_latest")


@router.get("/flood/computed-risk")
async def api_flood_computed_risk(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_flood_computed_risk",
        {
            "records": [],
            "total": 0,
            "risk_counts": {},
        },
        context=context,
    )

    return service_response(result, "Flood computed risk", "flood_spatial_service.get_flood_computed_risk")


@router.get("/master/rainfall-stations")
async def api_master_rainfall_stations(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "master",
        "get_rainfall_station_master",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Rainfall station master", "flood_spatial_service.get_rainfall_station_master")


@router.get("/master/waterlevel-stations")
async def api_master_waterlevel_stations(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "master",
        "get_waterlevel_station_master",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Waterlevel station master", "flood_spatial_service.get_waterlevel_station_master")


@router.get("/master/dams")
async def api_master_dams(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "master",
        "get_dam_reservoir_master",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Dam reservoir master", "flood_spatial_service.get_dam_reservoir_master")


@router.get("/master/locations")
async def api_master_locations(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "master",
        "get_location_master",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Location master", "flood_spatial_service.get_location_master")


@router.get("/history/rainfall")
async def api_history_rainfall(request: Request) -> JSONResponse:
    return await api_history_by_type("rainfall", request)


@router.get("/history/rain15d")
@router.get("/history/rain-15d")
async def api_history_rain15d(request: Request) -> JSONResponse:
    return await api_history_by_type("rain15d", request)


@router.get("/history/rain-yearly")
@router.get("/history/rain_yearly")
@router.get("/history/rainfall-yearly")
async def api_history_rain_yearly(request: Request) -> JSONResponse:
    return await api_history_by_type("rain_yearly", request)


@router.get("/history/waterlevel")
async def api_history_waterlevel(request: Request) -> JSONResponse:
    return await api_history_by_type("waterlevel", request)


@router.get("/history/dam")
async def api_history_dam(request: Request) -> JSONResponse:
    data_type = get_first_arg(request, ["data_type", "dam_type", "size"], "large_dam")
    return await api_history_by_type(str(data_type), request)


@router.get("/history/all-long")
@router.get("/history/all_long")
async def api_history_all_long(request: Request) -> JSONResponse:
    return await api_history_by_type("all_long", request)


@router.get("/history/{data_type}")
async def api_history_by_type(data_type: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    year = get_first_int_arg(request, ["year", "data_year"], 0, min_value=0)
    month = get_first_int_arg(request, ["month", "data_month"], 0, min_value=0)

    result = call_data_service(
        "history",
        "get_history",
        {
            "records": [],
            "total": 0,
        },
        data_type=data_type,
        year=year,
        month=month,
        context=context,
        strict_filter_params=True,
    )

    return service_response(result, f"History {data_type}", "flood_spatial_service.get_history")


# ============================================================
# 10) PREDICTION / FORECAST API
# ============================================================

@router.get("/prediction/files")
@router.get("/forecast/files")
async def api_prediction_files(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "prediction",
        "get_prediction_files",
        {
            "files": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Prediction files", "flood_spatial_service.get_prediction_files")


@router.get("/prediction/contract")
@router.get("/forecast/contract")
async def api_prediction_contract() -> JSONResponse:
    result = call_data_service(
        "prediction",
        "get_flood_prediction_contract",
        {
            "location_contract": {
                "prediction_lat_lon_source": "station_master",
                "fallback_focus": "province_boundary",
            },
            "required_columns": getattr(config, "PREDICTION_REQUIRED_COLUMNS", []),
            "supported_columns": getattr(config, "PREDICTION_SUPPORTED_COLUMNS", []),
        },
    )

    return service_response(result, "Prediction contract", "flood_spatial_service.get_flood_prediction_contract")


@router.get("/prediction/latest")
@router.get("/forecast/latest")
@router.get("/prediction/waterlevel")
@router.get("/forecast/waterlevel")
async def api_prediction_latest(request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    prediction_filters = get_prediction_filters(request)

    result = call_data_service(
        "prediction",
        "get_latest_flood_predictions",
        {
            "records": [],
            "total": 0,
        },
        context={
            **context,
            "filters": {
                **context.get("filters", {}),
                **prediction_filters,
            },
        },
        strict_filter_params=True,
    )

    return service_response(result, "Prediction latest", "flood_spatial_service.get_latest_flood_predictions")


@router.get("/prediction/summary")
@router.get("/forecast/summary")
async def api_prediction_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    prediction_filters = get_prediction_filters(request)

    result = call_data_service(
        "prediction",
        "get_flood_prediction_summary",
        {
            "summary": {},
            "risk_counts": {},
            "total": 0,
        },
        context={
            **context,
            "filters": {
                **context.get("filters", {}),
                **prediction_filters,
            },
        },
        strict_filter_params=True,
    )

    return service_response(result, "Prediction summary", "flood_spatial_service.get_flood_prediction_summary")


@router.get("/prediction/map")
@router.get("/forecast/map")
async def api_prediction_map(request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    prediction_filters = get_prediction_filters(request)

    result = call_data_service(
        "prediction",
        "get_flood_prediction_map",
        {
            "type": "FeatureCollection",
            "features": [],
            "fallback_focus": [],
        },
        context={
            **context,
            "filters": {
                **context.get("filters", {}),
                **prediction_filters,
            },
        },
        strict_filter_params=True,
    )

    return service_response(result, "Prediction map", "flood_spatial_service.get_flood_prediction_map")


@router.get("/prediction/location-debug")
@router.get("/forecast/location-debug")
async def api_prediction_location_debug(request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    prediction_filters = get_prediction_filters(request)

    result = call_data_service(
        "prediction",
        "get_flood_prediction_location_debug",
        {
            "records": [],
            "summary": {},
            "total": 0,
        },
        context={
            **context,
            "filters": {
                **context.get("filters", {}),
                **prediction_filters,
            },
        },
        strict_filter_params=True,
    )

    return service_response(result, "Prediction location debug", "flood_spatial_service.get_flood_prediction_location_debug")


@router.get("/prediction/station/{station_id_or_name}")
@router.get("/forecast/station/{station_id_or_name}")
async def api_prediction_station_detail(station_id_or_name: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    prediction_filters = get_prediction_filters(request)

    result = call_data_service(
        "prediction",
        "get_flood_prediction_station_detail",
        {
            "station": station_id_or_name,
            "records": [],
            "summary": {},
        },
        station_id_or_name=station_id_or_name,
        context={
            **context,
            "filters": {
                **context.get("filters", {}),
                **prediction_filters,
            },
        },
        strict_filter_params=True,
    )

    return service_response(result, "Prediction station detail", "flood_spatial_service.get_flood_prediction_station_detail")


@router.get("/prediction/risk-distribution")
@router.get("/forecast/risk-distribution")
async def api_prediction_risk_distribution(request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    prediction_filters = get_prediction_filters(request)

    result = call_data_service(
        "prediction",
        "get_flood_prediction_risk_distribution",
        {
            "records": [],
            "risk_counts": {},
            "total": 0,
        },
        context={
            **context,
            "filters": {
                **context.get("filters", {}),
                **prediction_filters,
            },
        },
        strict_filter_params=True,
    )

    return service_response(result, "Prediction risk distribution", "flood_spatial_service.get_flood_prediction_risk_distribution")


# ============================================================
# 11) SPATIAL API
# ============================================================

@router.get("/spatial/company-flood-context")
async def api_spatial_company_flood_context(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "spatial",
        "get_company_flood_context",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Company flood context", "flood_spatial_service.get_company_flood_context")


@router.get("/spatial/company/{tax_id}/flood-context")
async def api_spatial_company_single_flood_context(tax_id: str) -> JSONResponse:
    result = call_data_service(
        "spatial",
        "get_single_company_flood_context",
        {
            "tax_id": tax_id,
            "context": {},
        },
        tax_id=tax_id,
    )

    return service_response(result, "Single company flood context", "flood_spatial_service.get_single_company_flood_context")


@router.get("/spatial/policy-flood-exposure")
async def api_spatial_policy_flood_exposure(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "spatial",
        "get_policy_flood_exposure",
        {
            "records": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Policy flood exposure", "flood_spatial_service.get_policy_flood_exposure")


@router.get("/spatial/province-risk-exposure")
async def api_spatial_province_risk_exposure(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "spatial",
        "get_province_risk_exposure",
        {
            "records": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Province risk exposure", "flood_spatial_service.get_province_risk_exposure")


@router.get("/spatial/nearest-stations/{tax_id}")
async def api_spatial_nearest_stations(tax_id: str) -> JSONResponse:
    result = call_data_service(
        "spatial",
        "get_nearest_stations_for_company",
        {
            "tax_id": tax_id,
            "rainfall": None,
            "waterlevel": None,
            "dam": None,
        },
        tax_id=tax_id,
    )

    return service_response(result, "Nearest stations for company", "flood_spatial_service.get_nearest_stations_for_company")


# ============================================================
# 12) MAP / GRAPH / CHART API
# ============================================================

@router.get("/map/layers")
async def api_map_layers(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    include_policy = get_first_bool_arg(request, ["include_policy", "include_policy_exposure"], True)
    include_linkage = get_first_bool_arg(request, ["include_linkage", "include_linkage_lines"], False)
    include_heatmap = get_first_bool_arg(request, ["include_heatmap", "heatmap"], False)
    include_boundary = get_first_bool_arg(request, ["include_boundary", "include_boundaries"], True)
    include_prediction = get_first_bool_arg(request, ["include_prediction", "prediction"], True)
    include_entity = get_first_bool_arg(request, ["include_entity", "entity"], True)

    map_context = {
        **context,
        "include_companies": get_bool_arg(request, "include_companies", True),
        "include_policy": include_policy,
        "include_policy_exposure": include_policy,
        "include_flood": get_bool_arg(request, "include_flood", True),
        "include_linkage": include_linkage,
        "include_linkage_lines": include_linkage,
        "include_branches": get_bool_arg(request, "include_branches", True),
        "include_boundaries": include_boundary,
        "include_boundary": include_boundary,
        "include_prediction": include_prediction,
        "include_entity": include_entity,
        "include_heatmap": include_heatmap,
        "heatmap": include_heatmap,
        "cluster": get_bool_arg(request, "cluster", True),
        "zoom": get_int_arg(request, "zoom", 6, min_value=1, max_value=20),
        "entity_limit": get_first_int_arg(request, ["entity_limit", "upload_entity_limit"], 500, min_value=1, max_value=5000),
        "entity_offset": get_first_int_arg(request, ["entity_offset", "upload_entity_offset"], 0, min_value=0),
        "entity_query": get_first_arg(request, ["entity_query", "upload_entity_query"], ""),
        "prediction_limit": get_first_int_arg(request, ["prediction_limit", "forecast_limit"], 500, min_value=1, max_value=5000),
        "prediction_offset": get_first_int_arg(request, ["prediction_offset", "forecast_offset"], 0, min_value=0),
    }

    result = call_data_service(
        "map",
        "get_map_layers",
        {
            "layers": {},
            "summary": {},
        },
        context=map_context,
    )

    return service_response(result, "Map layers", "map_graph_service.get_map_layers")


@router.get("/map/flood")
async def api_map_flood(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "map",
        "get_map_flood",
        {
            "type": "FeatureCollection",
            "features": [],
        },
        context=context,
    )

    return service_response(result, "Flood map layer", "map_graph_service.get_map_flood")


@router.get("/map/entities")
async def api_map_entities(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "entity",
        "get_latest_entity_map_features",
        {
            "type": "FeatureCollection",
            "features": [],
        },
        province=get_first_arg(request, ["province", "province_name_th"], None),
        risk_level=get_first_arg(request, ["risk", "risk_level", "risk_group"], None),
        query=get_first_arg(request, ["query", "q", "search", "entity_query"], None),
        limit=get_first_int_arg(request, ["limit", "entity_limit"], 500, min_value=1, max_value=5000),
        offset=get_first_int_arg(request, ["offset", "entity_offset"], 0, min_value=0),
        context=context,
        strict_filter_params=True,
    )

    return service_response(result, "Entity map layer", "entity_upload_service.get_latest_entity_map_features")


@router.get("/map/boundary/province")
@router.get("/map/boundary/provinces")
@router.get("/flood/boundaries/province")
async def api_flood_province_boundaries() -> JSONResponse:
    result = call_data_service(
        "flood",
        "get_province_boundaries",
        {
            "type": "FeatureCollection",
            "features": [],
        },
    )

    return service_response(result, "Province boundaries", "flood_spatial_service.get_province_boundaries")


@router.get("/map/boundary/basin")
@router.get("/map/boundary/basins")
@router.get("/flood/boundaries/basin")
async def api_flood_basin_boundaries() -> JSONResponse:
    result = call_data_service(
        "flood",
        "get_basin_boundaries",
        {
            "type": "FeatureCollection",
            "features": [],
        },
    )

    return service_response(result, "Basin boundaries", "flood_spatial_service.get_basin_boundaries")


@router.get("/map/companies")
async def api_map_companies(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "map",
        "get_map_companies",
        {
            "type": "FeatureCollection",
            "features": [],
        },
        context=context,
    )

    return service_response(result, "Company map layer", "map_graph_service.get_map_companies")


@router.get("/map/policy-exposure")
async def api_map_policy_exposure(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "map",
        "get_map_policy_exposure",
        {
            "type": "FeatureCollection",
            "features": [],
        },
        context=context,
    )

    return service_response(result, "Policy exposure map layer", "map_graph_service.get_map_policy_exposure")


@router.get("/map/linkage-lines")
async def api_map_linkage_lines(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "map",
        "get_map_linkage_lines",
        {
            "type": "FeatureCollection",
            "features": [],
        },
        context=context,
    )

    return service_response(result, "Linkage line layer", "map_graph_service.get_map_linkage_lines")


@router.get("/map/branches")
async def api_map_branches(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "map",
        "get_map_branches",
        {
            "type": "FeatureCollection",
            "features": [],
        },
        context=context,
    )

    return service_response(result, "Branch map layer", "map_graph_service.get_map_branches")


@router.get("/map/heatmap")
async def api_map_heatmap(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "map",
        "get_map_heatmap",
        {
            "type": "FeatureCollection",
            "features": [],
        },
        context=context,
    )

    return service_response(result, "Heatmap layer", "map_graph_service.get_map_heatmap")


@router.get("/map/selected-context")
async def api_map_selected_context(request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    feature_id = get_str_arg(request, "feature_id", "")
    feature_type = get_str_arg(request, "feature_type", "")
    selected_tax_id = get_str_arg(request, "selected_tax_id", "")

    if not selected_tax_id and feature_type in {"company", "company_points"}:
        selected_tax_id = feature_id

    map_context = {
        **context,
        "feature_id": feature_id,
        "feature_type": feature_type,
        "selected_tax_id": selected_tax_id,
        "selected_director_id": get_str_arg(request, "selected_director_id", ""),
        "selected_province": get_str_arg(request, "selected_province", ""),
    }

    result = call_data_service(
        "map",
        "get_selected_context",
        {
            "feature_id": feature_id,
            "feature_type": feature_type,
            "context": {},
        },
        context=map_context,
    )

    return service_response(result, "Selected map context", "map_graph_service.get_selected_context")


@router.get("/charts/summary")
async def api_charts_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "charts",
        "get_chart_summary",
        {
            "charts": {},
        },
        context=context,
    )

    return service_response(result, "Chart summary", "dashboard_package_service.get_chart_summary")


@router.get("/charts/dashboard")
async def api_charts_dashboard(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "charts",
        "get_dashboard_charts",
        {
            "charts": {},
        },
        context=context,
    )

    return service_response(result, "Dashboard charts", "dashboard_package_service.get_dashboard_charts")


@router.get("/charts/risk-distribution")
async def api_charts_risk_distribution(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "charts",
        "get_risk_distribution_chart",
        {
            "chart": {},
            "records": [],
        },
        context=context,
    )

    return service_response(result, "Risk distribution chart", "dashboard_package_service.get_risk_distribution_chart")


@router.get("/charts/province-comparison")
async def api_charts_province_comparison(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "charts",
        "get_province_comparison_chart",
        {
            "chart": {},
            "records": [],
        },
        context=context,
    )

    return service_response(result, "Province comparison chart", "dashboard_package_service.get_province_comparison_chart")


@router.get("/charts/station-ranking")
async def api_charts_station_ranking(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "charts",
        "get_station_ranking_chart",
        {
            "chart": {},
            "records": [],
        },
        context=context,
    )

    return service_response(result, "Station ranking chart", "dashboard_package_service.get_station_ranking_chart")


# ============================================================
# 13) DASHBOARD API
# ============================================================

@router.get("/dashboard/executive")
async def api_dashboard_executive(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "dashboard",
        "get_executive_dashboard",
        {
            "summary_cards": {},
            "charts": {},
            "top_companies": [],
            "top_directors": [],
            "risk_insights": [],
            "data_quality": {},
        },
        context=context,
    )

    return service_response(result, "Executive dashboard", "dashboard_package_service.get_executive_dashboard")


@router.get("/dashboard/summary")
async def api_dashboard_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "dashboard",
        "get_dashboard_summary",
        {
            "summary_cards": {},
            "record_counts": {},
        },
        context=context,
    )

    return service_response(result, "Dashboard summary", "dashboard_package_service.get_dashboard_summary")


@router.get("/dashboard/overview")
async def api_dashboard_overview(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "dashboard",
        "get_dashboard_overview",
        {
            "company": {},
            "policy": {},
            "linkage": {},
            "flood": {},
            "map": {},
            "quality": {},
        },
        context=context,
    )

    return service_response(result, "Dashboard overview", "dashboard_package_service.get_dashboard_overview")


@router.get("/dashboard/freshness")
async def api_dashboard_freshness() -> JSONResponse:
    result = call_data_service(
        "dashboard",
        "get_dashboard_freshness",
        {
            "policy": {},
            "linkage": {},
            "flood": {},
            "cache": {},
        },
    )

    return service_response(result, "Dashboard freshness", "dashboard_package_service.get_dashboard_freshness")


@router.get("/dashboard/province-insights")
async def api_dashboard_province_insights(request: Request) -> JSONResponse:
    filters = get_dashboard_province_insight_filters(request)

    result = call_data_service(
        "dashboard",
        "get_dashboard_province_insights",
        {
            "prediction_risk_top3": [],
            "rainfall_top5": [],
            "waterlevel_top5": [],
            "reservoir_top5": [],
        },
        context=filters,
        strict_filter_params=True,
    )

    return service_response(result, "Dashboard province insights", "dashboard_package_service.get_dashboard_province_insights")


# ============================================================
# 14) DETAIL / SEARCH API
# ============================================================

@router.get("/detail/station/{station_id}")
async def api_detail_station(station_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_station_detail",
        {
            "station_id": station_id,
            "record": None,
        },
        station_id=station_id,
        context=context,
    )

    return service_response(result, "Station detail", "flood_spatial_service.get_station_detail")


@router.get("/detail/dam/{dam_id}")
async def api_detail_dam(dam_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "flood",
        "get_dam_detail",
        {
            "dam_id": dam_id,
            "record": None,
        },
        dam_id=dam_id,
        context=context,
    )

    return service_response(result, "Dam detail", "flood_spatial_service.get_dam_detail")


@router.get("/detail/entity/{entity_id}")
async def api_detail_entity(entity_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "entity",
        "get_entity_detail",
        {
            "entity_id": entity_id,
            "record": None,
        },
        entity_id=entity_id,
        context=context,
    )

    return service_response(result, "Entity detail", "entity_upload_service.get_entity_detail")


@router.get("/detail/object")
async def api_detail_object(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    object_type = get_first_arg(request, ["type", "object_type", "source_type"], "")
    object_id = get_first_arg(request, ["id", "object_id", "feature_id", "record_key"], "")

    object_type_key = str(object_type or "").strip().lower()

    if object_type_key in {"station", "rainfall", "waterlevel"}:
        result = call_data_service(
            "flood",
            "get_station_detail",
            {
                "object_type": object_type,
                "object_id": object_id,
                "record": None,
            },
            station_id=object_id,
            context=context,
        )
        return service_response(result, "Object detail", "flood_spatial_service.get_station_detail")

    if object_type_key in {"dam", "large_dam", "medium_dam", "reservoir"}:
        result = call_data_service(
            "flood",
            "get_dam_detail",
            {
                "object_type": object_type,
                "object_id": object_id,
                "record": None,
            },
            dam_id=object_id,
            context=context,
        )
        return service_response(result, "Object detail", "flood_spatial_service.get_dam_detail")

    if object_type_key in {"entity", "uploaded_entity"}:
        result = call_data_service(
            "entity",
            "get_entity_detail",
            {
                "object_type": object_type,
                "object_id": object_id,
                "record": None,
            },
            entity_id=object_id,
            context=context,
        )
        return service_response(result, "Object detail", "entity_upload_service.get_entity_detail")

    if object_type_key in {"prediction", "forecast", "flood_prediction"}:
        result = call_data_service(
            "prediction",
            "get_flood_prediction_station_detail",
            {
                "object_type": object_type,
                "object_id": object_id,
                "records": [],
            },
            station_id_or_name=object_id,
            context=context,
        )
        return service_response(result, "Object detail", "flood_spatial_service.get_flood_prediction_station_detail")

    return error_response(
        message="Unsupported object type",
        data={
            "object_type": object_type,
            "object_id": object_id,
        },
        errors=[
            {
                "code": "unsupported_object_type",
                "message": f"Unsupported object type: {object_type}",
            }
        ],
        status_code=400,
        legacy_error="unsupported_object_type",
    )


@router.get("/search")
async def api_search(request: Request) -> JSONResponse:
    context = get_common_query_context(request)
    search_type = get_first_arg(request, ["type", "search_type", "target"], "all")
    query = get_first_arg(request, ["query", "q", "search"], "")

    result = call_data_service(
        "flood",
        "get_search_results",
        {
            "records": [],
            "total": 0,
        },
        query=query,
        search_type=search_type,
        context=context,
        strict_filter_params=True,
    )

    return service_response(result, "Search results", "flood_spatial_service.get_search_results")


# ============================================================
# 15) ENTITY UPLOAD API
# ============================================================

@router.post("/upload/entities")
async def api_upload_entities(file: UploadFile = File(...)) -> JSONResponse:
    result = call_data_service(
        "entity",
        "process_uploaded_entity_file",
        {
            "upload_id": None,
            "displayable_records": [],
            "not_displayable_records": [],
            "summary": {},
        },
        file=file,
        strict_filter_params=True,
    )

    return service_response(result, "Entity upload processed", "entity_upload_service.process_uploaded_entity_file")


@router.get("/upload/entities/latest")
async def api_upload_entities_latest(request: Request) -> JSONResponse:
    result = call_data_service(
        "entity",
        "get_latest_entity_records",
        {
            "records": [],
            "total": 0,
        },
        province=get_first_arg(request, ["province", "province_name_th"], None),
        risk_level=get_first_arg(request, ["risk", "risk_level", "risk_group"], None),
        query=get_first_arg(request, ["query", "q", "search", "entity_query"], None),
        limit=get_first_int_arg(request, ["limit", "entity_limit"], 500, min_value=1, max_value=5000),
        offset=get_first_int_arg(request, ["offset", "entity_offset"], 0, min_value=0),
        strict_filter_params=True,
    )

    return service_response(result, "Latest uploaded entities", "entity_upload_service.get_latest_entity_records")


@router.get("/upload/entities/map")
async def api_upload_entities_map(request: Request) -> JSONResponse:
    return await api_map_entities(request)


@router.delete("/upload/entities/latest")
@router.post("/upload/entities/clear")
async def api_upload_entities_clear() -> JSONResponse:
    result = call_data_service(
        "entity",
        "clear_latest_entities",
        {
            "cleared": False,
        },
    )

    return service_response(result, "Latest uploaded entities cleared", "entity_upload_service.clear_latest_entities")


@router.get("/upload/logs")
async def api_upload_logs(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "entity",
        "get_upload_logs",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Upload logs", "entity_upload_service.get_upload_logs")


@router.get("/upload/result/{upload_id}")
async def api_upload_result(upload_id: str) -> JSONResponse:
    result = call_data_service(
        "entity",
        "get_upload_result",
        {
            "upload_id": upload_id,
            "result": None,
        },
        upload_id=upload_id,
    )

    return service_response(result, "Upload result", "entity_upload_service.get_upload_result")


@router.get("/upload/result/{upload_id}/displayable")
async def api_upload_result_displayable(upload_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "entity",
        "get_upload_displayable_records",
        {
            "upload_id": upload_id,
            "records": [],
            "total": 0,
        },
        upload_id=upload_id,
        context=context,
    )

    return service_response(result, "Upload displayable records", "entity_upload_service.get_upload_displayable_records")


@router.get("/upload/result/{upload_id}/not-displayable")
async def api_upload_result_not_displayable(upload_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "entity",
        "get_upload_not_displayable_records",
        {
            "upload_id": upload_id,
            "records": [],
            "total": 0,
        },
        upload_id=upload_id,
        context=context,
    )

    return service_response(result, "Upload not displayable records", "entity_upload_service.get_upload_not_displayable_records")


@router.get("/upload/result/{upload_id}/error-report", response_model=None)
async def api_upload_result_error_report(upload_id: str) -> Response:
    result = call_data_service(
        "entity",
        "get_upload_error_report_file",
        {
            "upload_id": upload_id,
            "download_ready": False,
        },
        upload_id=upload_id,
    )

    if isinstance(result, (str, Path)):
        path = Path(result)
        if path.exists() and path.is_file():
            return FileResponse(path, filename=path.name)

    result_data = result.get("data") if is_standard_api_payload(result) else result

    if isinstance(result_data, dict):
        file_path = result_data.get("file_path") or result_data.get("path") or result_data.get("error_report_file")
        if file_path:
            path = Path(str(file_path))
            if path.exists() and path.is_file():
                return FileResponse(path, filename=path.name)

    return service_response(result, "Upload error report", "entity_upload_service.get_upload_error_report_file")

# ============================================================
# 16) FILTER BUILDER API
# ============================================================

@router.get("/filter/fields")
async def api_filter_fields() -> JSONResponse:
    result = call_data_service(
        "filter",
        "get_filter_fields",
        {
            "fields": [],
            "groups": {},
        },
    )

    return service_response(result, "Filter fields", "filter_engine.get_filter_fields")


@router.get("/filter/quick-presets")
async def api_filter_quick_presets() -> JSONResponse:
    result = call_data_service(
        "filter",
        "get_quick_filter_presets",
        {
            "presets": [],
        },
    )

    return service_response(result, "Quick filter presets", "filter_engine.get_quick_filter_presets")


@router.post("/filter/preview")
async def api_filter_preview(request: Request) -> JSONResponse:
    payload = await get_json_payload(request)

    result = call_data_service(
        "filter",
        "preview_filter",
        {
            "preview": {},
            "record_count": 0,
            "sample_records": [],
        },
        payload=payload,
    )

    return service_response(result, "Filter preview", "filter_engine.preview_filter")


@router.post("/filter/apply")
async def api_filter_apply(request: Request) -> JSONResponse:
    payload = await get_json_payload(request)

    result = call_data_service(
        "filter",
        "apply_filter",
        {
            "records": [],
            "total": 0,
            "summary": {},
        },
        payload=payload,
    )

    return service_response(result, "Filter applied", "filter_engine.apply_filter")


@router.post("/filter/save-view")
async def api_filter_save_view(request: Request) -> JSONResponse:
    payload = await get_json_payload(request)

    result = call_data_service(
        "filter",
        "save_filter_view",
        {
            "saved": False,
            "view_id": None,
        },
        payload=payload,
    )

    return service_response(result, "Filter view saved", "filter_engine.save_filter_view")


@router.get("/filter/saved-views")
async def api_filter_saved_views() -> JSONResponse:
    result = call_data_service(
        "filter",
        "get_saved_filter_views",
        {
            "views": [],
        },
    )

    return service_response(result, "Saved filter views", "filter_engine.get_saved_filter_views")


@router.get("/filter/saved-views/{view_id}")
async def api_filter_saved_view_detail(view_id: str) -> JSONResponse:
    result = call_data_service(
        "filter",
        "get_saved_filter_view",
        {
            "view_id": view_id,
            "view": None,
        },
        view_id=view_id,
    )

    return service_response(result, "Saved filter view detail", "filter_engine.get_saved_filter_view")


@router.put("/filter/saved-views/{view_id}")
async def api_filter_saved_view_update(view_id: str, request: Request) -> JSONResponse:
    payload = await get_json_payload(request)

    result = call_data_service(
        "filter",
        "update_saved_filter_view",
        {
            "updated": False,
            "view_id": view_id,
        },
        view_id=view_id,
        payload=payload,
    )

    return service_response(result, "Saved filter view updated", "filter_engine.update_saved_filter_view")


@router.delete("/filter/saved-views/{view_id}")
async def api_filter_saved_view_delete(view_id: str) -> JSONResponse:
    result = call_data_service(
        "filter",
        "delete_saved_filter_view",
        {
            "deleted": False,
            "view_id": view_id,
        },
        view_id=view_id,
    )

    return service_response(result, "Saved filter view deleted", "filter_engine.delete_saved_filter_view")


# ============================================================
# 17) DATA QUALITY / ADMIN API
# ============================================================

@router.get("/data-quality/summary")
@router.get("/admin/data-quality")
async def api_data_quality_summary(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_data_quality_summary",
        {
            "total_issues": 0,
            "by_severity": {},
            "by_category": {},
            "issues": [],
        },
        context=context,
    )

    return service_response(result, "Data quality summary", "data_quality.get_data_quality_summary")


@router.get("/data-quality/tax-id")
async def api_data_quality_tax_id(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_tax_id_quality",
        {
            "issues": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Tax ID data quality", "data_quality.get_tax_id_quality")


@router.get("/data-quality/coordinates")
async def api_data_quality_coordinates(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_coordinate_quality",
        {
            "issues": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Coordinate data quality", "data_quality.get_coordinate_quality")


@router.get("/data-quality/policy")
async def api_data_quality_policy(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_policy_quality",
        {
            "issues": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Policy data quality", "data_quality.get_policy_quality")


@router.get("/data-quality/linkage")
async def api_data_quality_linkage(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_linkage_quality",
        {
            "issues": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Linkage data quality", "data_quality.get_linkage_quality")


@router.get("/data-quality/flood")
async def api_data_quality_flood(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_flood_quality",
        {
            "issues": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Flood data quality", "data_quality.get_flood_quality")


@router.get("/data-quality/spatial")
@router.get("/data-quality/spatial-join")
async def api_data_quality_spatial(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_spatial_join_quality",
        {
            "issues": [],
            "summary": {},
        },
        context=context,
    )

    return service_response(result, "Spatial data quality", "data_quality.get_spatial_join_quality")


@router.get("/data-quality/status-conflicts")
async def api_data_quality_status_conflicts(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_policy_status_conflicts",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Policy status conflicts", "data_quality.get_policy_status_conflicts")


@router.get("/data-quality/issues")
async def api_data_quality_issues(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_data_quality_issues",
        {
            "issues": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Data quality issues", "data_quality.get_data_quality_issues")


@router.get("/data-quality/company-flags")
async def api_data_quality_company_flags(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "data_quality",
        "get_company_quality_flags",
        {
            "flags_by_tax_id": {},
            "summary_by_tax_id": {},
        },
        context=context,
    )

    return service_response(result, "Company quality flags", "data_quality.get_company_quality_flags")


@router.get("/admin/errors")
async def api_admin_errors(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "admin",
        "get_admin_errors",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    if is_service_error_payload(result):
        result = call_data_service(
            "admin",
            "get_error_log",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

    return service_response(result, "Admin error log", "data_quality.get_admin_errors")


@router.get("/admin/scrape-runs")
async def api_admin_scrape_runs(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "admin",
        "get_admin_scrape_runs",
        {
            "records": [],
            "total": 0,
        },
        context=context,
    )

    if is_service_error_payload(result):
        result = call_data_service(
            "admin",
            "get_scrape_runs",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

    return service_response(result, "Admin scrape runs", "data_quality.get_admin_scrape_runs")


# ============================================================
# 18) CACHE / REBUILD API
# ============================================================

async def api_cache_status() -> JSONResponse:
    cache_files = getattr(config, "CACHE_FILES", {})
    cache_registry = getattr(config, "CACHE_REGISTRY", {})

    return success_response(
        message="Cache status",
        data={
            "cache_files": cache_files,
            "cache_registry": cache_registry,
            "summary": {
                "cache_file_count": len(cache_files) if isinstance(cache_files, dict) else 0,
                "registry_count": len(cache_registry) if isinstance(cache_registry, dict) else 0,
            },
        },
        meta={
            "module": "cache",
            "source": "config",
        },
    )


@router.get("/cache/manifest")
async def api_cache_manifest() -> JSONResponse:
    return success_response(
        message="Cache manifest",
        data={
            "cache_files": getattr(config, "CACHE_FILES", {}),
            "cache_registry": getattr(config, "CACHE_REGISTRY", {}),
        },
        meta={
            "module": "cache",
        },
    )


@router.get("/cache/dependency-graph")
async def api_cache_dependency_graph() -> JSONResponse:
    registry = getattr(config, "CACHE_REGISTRY", {})
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    for cache_key, item in registry.items():
        nodes.append(
            {
                "id": cache_key,
                "owner_service": item.get("owner_service"),
                "payload_type": item.get("payload_type"),
                "critical": item.get("critical", False),
            }
        )

        for dependency in item.get("depends_on", []):
            edges.append(
                {
                    "source": dependency,
                    "target": cache_key,
                    "type": "depends_on",
                }
            )

    return success_response(
        message="Cache dependency graph",
        data={
            "nodes": nodes,
            "edges": edges,
        },
        meta={
            "module": "cache",
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    )


@router.post("/cache/clear")
async def api_cache_clear(request: Request) -> JSONResponse:
    payload = await get_json_payload(request)
    cache_key = str(payload.get("cache_key") or get_str_arg(request, "cache_key", "")).strip() or None

    result = call_data_service(
        "utils",
        "clear_cache",
        {
            "removed": [],
            "count": 0,
        },
        cache_key=cache_key,
    )

    return service_response(result, "Cache clear requested", "utils.clear_cache")

@router.post("/cache/rebuild")
async def api_cache_rebuild(request: Request) -> JSONResponse:
    payload = await get_json_payload(request)
    force_refresh = parse_bool_value(
        payload.get("force_refresh", get_bool_arg(request, "force_refresh", True)),
        default=True,
    )

    result = call_data_service(
        "dashboard",
        "rebuild_all_runtime_cache",
        {
            "rebuilt": False,
            "phases": [],
            "message": "rebuild_all_runtime_cache not ready",
        },
        force_refresh=force_refresh,
    )

    return service_response(result, "Cache rebuild requested", "dashboard_package_service.rebuild_all_runtime_cache")


@router.post("/cache/rebuild-phase")
async def api_cache_rebuild_phase(request: Request) -> JSONResponse:
    payload = await get_json_payload(request)
    phase = str(payload.get("phase") or get_str_arg(request, "phase", "")).strip()
    force_refresh = parse_bool_value(
        payload.get("force_refresh", get_bool_arg(request, "force_refresh", True)),
        default=True,
    )

    if not phase:
        return error_response(
            message="Missing rebuild phase",
            errors=[
                {
                    "code": "missing_phase",
                    "message": "phase is required",
                }
            ],
            data={
                "phase": phase,
            },
            status_code=400,
            legacy_error="missing_phase",
        )

    result = call_data_service(
        "dashboard",
        "rebuild_runtime_cache_phase",
        {
            "phase": phase,
            "rebuilt": False,
            "message": "rebuild_runtime_cache_phase not ready",
        },
        phase_name=phase,
        force_refresh=force_refresh,
    )

    return service_response(result, "Cache rebuild phase requested", "dashboard_package_service.rebuild_runtime_cache_phase")


# ============================================================
# 19) PACKAGE EXPORT API
# ============================================================

@router.post("/packages/preview")
async def api_package_preview(request: Request) -> JSONResponse:
    payload = await get_json_payload(request)

    result = call_data_service(
        "package",
        "preview_package",
        {
            "components": PACKAGE_COMPONENTS,
            "security_options": PACKAGE_SECURITY_OPTIONS,
            "estimated_records": {},
            "warnings": [],
        },
        payload=payload,
    )

    return service_response(result, "Package preview", "dashboard_package_service.preview_package")


@router.post("/packages/generate")
async def api_package_generate(request: Request) -> JSONResponse:
    payload = await get_json_payload(request)

    result = call_data_service(
        "package",
        "generate_package",
        {
            "generated": False,
            "package_id": None,
            "download_url": None,
            "public_url": None,
        },
        payload=payload,
    )

    return service_response(result, "Package generation requested", "dashboard_package_service.generate_package")


@router.get("/packages")
async def api_package_list(request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "package",
        "list_packages",
        {
            "packages": [],
            "total": 0,
        },
        context=context,
    )

    return service_response(result, "Package list", "dashboard_package_service.list_packages")


@router.get("/packages/{package_id}")
async def api_package_detail(package_id: str) -> JSONResponse:
    result = call_data_service(
        "package",
        "get_package_detail",
        {
            "package_id": package_id,
            "package": None,
        },
        package_id=package_id,
    )

    return service_response(result, "Package detail", "dashboard_package_service.get_package_detail")


@router.get("/packages/{package_id}/download", response_model=None)
async def api_package_download(package_id: str) -> Response:
    result = call_data_service(
        "package",
        "get_package_download_info",
        {
            "package_id": package_id,
            "download_ready": False,
            "message": "download service not ready",
        },
        package_id=package_id,
    )

    if isinstance(result, (str, Path)):
        path = Path(result)
        if path.exists() and path.is_file():
            return FileResponse(path, filename=path.name)

    result_data = result.get("data") if is_standard_api_payload(result) else result

    if isinstance(result_data, dict):
        file_path = result_data.get("file_path") or result_data.get("path") or result_data.get("zip_path")
        if file_path:
            path = Path(str(file_path))
            if path.exists() and path.is_file():
                return FileResponse(path, filename=path.name)

    return service_response(result, "Package download", "dashboard_package_service.get_package_download_info")


@router.post("/packages/{package_id}/disable")
async def api_package_disable(package_id: str, request: Request) -> JSONResponse:
    payload = await get_json_payload(request)

    result = call_data_service(
        "package",
        "disable_package",
        {
            "package_id": package_id,
            "disabled": False,
        },
        package_id=package_id,
        payload=payload,
    )

    return service_response(result, "Package disabled", "dashboard_package_service.disable_package")


@router.delete("/packages/{package_id}")
async def api_package_delete(package_id: str) -> JSONResponse:
    result = call_data_service(
        "package",
        "delete_package",
        {
            "package_id": package_id,
            "deleted": False,
        },
        package_id=package_id,
    )

    return service_response(result, "Package deleted", "dashboard_package_service.delete_package")


# ============================================================
# 20) PUBLIC EXTERNAL PACKAGE API
# ============================================================

@public_router.get("/packages/{package_id}/meta")
async def public_package_meta(package_id: str) -> JSONResponse:
    result = call_data_service(
        "package",
        "get_public_package_meta",
        {
            "package_id": package_id,
            "available": False,
            "meta": {},
        },
        package_id=package_id,
    )

    return service_response(result, "Public package meta", "dashboard_package_service.get_public_package_meta")


@public_router.get("/packages/{package_id}/data")
async def public_package_data(package_id: str) -> JSONResponse:
    result = call_data_service(
        "package",
        "get_public_package_data",
        {
            "package_id": package_id,
            "data": {},
        },
        package_id=package_id,
    )

    return service_response(result, "Public package data", "dashboard_package_service.get_public_package_data")


@public_router.get("/packages/{package_id}/summary")
async def public_package_summary(package_id: str) -> JSONResponse:
    result = call_data_service(
        "package",
        "get_public_package_summary",
        {
            "package_id": package_id,
            "summary": {},
        },
        package_id=package_id,
    )

    return service_response(result, "Public package summary", "dashboard_package_service.get_public_package_summary")


@public_router.get("/packages/{package_id}/map")
async def public_package_map(package_id: str) -> JSONResponse:
    result = call_data_service(
        "package",
        "get_public_package_map",
        {
            "package_id": package_id,
            "layers": {},
        },
        package_id=package_id,
    )

    return service_response(result, "Public package map", "dashboard_package_service.get_public_package_map")


@public_router.get("/packages/{package_id}/charts")
async def public_package_charts(package_id: str) -> JSONResponse:
    result = call_data_service(
        "package",
        "get_public_package_charts",
        {
            "package_id": package_id,
            "charts": {},
        },
        package_id=package_id,
    )

    return service_response(result, "Public package charts", "dashboard_package_service.get_public_package_charts")


@public_router.get("/packages/{package_id}/tables")
async def public_package_tables(package_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "package",
        "get_public_package_tables",
        {
            "package_id": package_id,
            "tables": {},
        },
        package_id=package_id,
        context=context,
    )

    return service_response(result, "Public package tables", "dashboard_package_service.get_public_package_tables")


@public_router.get("/packages/{package_id}/access-log")
async def public_package_access_log_read(package_id: str, request: Request) -> JSONResponse:
    context = get_common_query_context(request)

    result = call_data_service(
        "package",
        "get_public_package_access_log",
        {
            "package_id": package_id,
            "access_log": [],
            "total": 0,
        },
        package_id=package_id,
        context=context,
    )

    return service_response(result, "Public package access log", "dashboard_package_service.get_public_package_access_log")


@public_router.post("/packages/{package_id}/access-log")
async def public_package_access_log(package_id: str, request: Request) -> JSONResponse:
    payload = await get_json_payload(request)

    result = call_data_service(
        "package",
        "write_public_package_access_log",
        {
            "package_id": package_id,
            "logged": False,
        },
        package_id=package_id,
        payload={
            **payload,
            "remote_addr": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent", ""),
            "accessed_at": now_iso(),
        },
    )

    return service_response(result, "Public package access logged", "dashboard_package_service.write_public_package_access_log")


router.include_router(public_router)