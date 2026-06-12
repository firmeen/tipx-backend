# ============================================================
# FILE: backend/api_routes.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 3 / 20
# ============================================================

"""
backend/api_routes.py

ไฟล์นี้เป็นศูนย์กลาง API Routes ทั้งหมดของระบบ TIPX

หน้าที่หลัก:
1. Register routes ทั้งหมดให้ Flask app
2. แยก route ตาม module ของระบบ
3. เชื่อม request จาก frontend ไปยัง service layer
4. จัดการ query parameter, filter payload, pagination, force refresh
5. ส่ง response กลับเป็น JSON format มาตรฐาน
6. รองรับ API สำหรับ internal dashboard
7. รองรับ API สำหรับ external package viewer
8. รองรับ fallback กรณี service บางไฟล์ยังไม่พร้อม
9. รองรับระบบ Flood / Policy / Linkage / Company / Map / Graph / Dashboard / Package / Data Quality ครบ

โครงสร้าง API ที่ไฟล์นี้รองรับ:
- Core API
- Company API
- Policy API
- Linkage API
- Flood API
- Spatial API
- Map API
- Graph API
- Dashboard API
- Filter Builder API
- Data Quality API
- Package Export API
- Public External Package API

หมายเหตุ:
ไฟล์นี้ถูกออกแบบให้ import service แบบ lazy import
เพื่อให้ app.py สามารถ start ได้แม้ service บางไฟล์ยังอยู่ระหว่างพัฒนา
"""


from __future__ import annotations

try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from flask import Flask, Response, jsonify, request

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
# 1) RESPONSE HELPERS
# ============================================================

def now_iso() -> str:
    """
    คืนเวลาปัจจุบันแบบ ISO string
    """

    return datetime.now().isoformat(timespec="seconds")


def success_response(
    data: Optional[Any] = None,
    message: str = "OK",
    meta: Optional[Dict[str, Any]] = None,
    status_code: int = 200,
) -> Tuple[Response, int]:
    """
    ส่ง response สำเร็จใน format มาตรฐานของ TIPX

    Format:
    {
        "success": true,
        "message": "OK",
        "data": {},
        "meta": {},
        "errors": []
    }
    """

    payload = {
        "success": True,
        "message": message,
        "data": data if data is not None else {},
        "meta": {
            "timestamp": now_iso(),
            "app": APP_SHORT_NAME,
            "version": APP_VERSION,
            **(meta or {}),
        },
        "errors": [],
    }

    return jsonify(payload), status_code


def error_response(
    message: str = "ERROR",
    errors: Optional[Any] = None,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
    status_code: int = 400,
) -> Tuple[Response, int]:
    """
    ส่ง response error ใน format มาตรฐานของ TIPX
    """

    payload = {
        "success": False,
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

    return jsonify(payload), status_code


def exception_response(
    exc: Exception,
    message: str = "Unhandled API exception",
    status_code: int = 500,
    include_traceback: bool = True,
) -> Tuple[Response, int]:
    """
    แปลง exception เป็น API response
    """

    error_payload: Dict[str, Any] = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }

    if include_traceback:
        error_payload["traceback"] = traceback.format_exc()

    return error_response(
        message=message,
        errors=[error_payload],
        status_code=status_code,
    )


# ============================================================
# 2) REQUEST PARSING HELPERS
# ============================================================

def get_bool_arg(name: str, default: bool = False) -> bool:
    """
    อ่าน query parameter แบบ boolean

    รองรับ:
    true, 1, yes, y, on
    false, 0, no, n, off
    """

    raw = request.args.get(name)

    if raw is None:
        return default

    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def get_int_arg(name: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    """
    อ่าน query parameter แบบ integer
    """

    raw = request.args.get(name)

    try:
        value = int(raw) if raw is not None and raw != "" else int(default)
    except Exception:
        value = int(default)

    if min_value is not None:
        value = max(min_value, value)

    if max_value is not None:
        value = min(max_value, value)

    return value


def get_float_arg(name: str, default: Optional[float] = None) -> Optional[float]:
    """
    อ่าน query parameter แบบ float
    """

    raw = request.args.get(name)

    if raw is None or raw == "":
        return default

    try:
        return float(raw)
    except Exception:
        return default


def get_str_arg(name: str, default: str = "") -> str:
    """
    อ่าน query parameter แบบ string
    """

    raw = request.args.get(name)

    if raw is None:
        return default

    return str(raw).strip()


def get_list_arg(name: str) -> List[str]:
    """
    อ่าน query parameter แบบ list

    รองรับ:
    ?province=น่าน&province=แพร่
    ?province=น่าน,แพร่
    """

    values = request.args.getlist(name)

    if not values:
        raw = request.args.get(name, "")
        values = [raw] if raw else []

    result: List[str] = []

    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                result.append(item)

    return result


def get_json_payload(default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    อ่าน JSON body จาก request
    """

    if default is None:
        default = {}

    if not request.is_json:
        return dict(default)

    try:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload
        return dict(default)
    except Exception:
        return dict(default)


def get_pagination_params() -> Dict[str, int]:
    """
    อ่าน pagination params
    """

    page = get_int_arg("page", 1, min_value=1)
    page_size = get_int_arg(
        "page_size",
        DEFAULT_TABLE_PAGE_SIZE,
        min_value=1,
        max_value=MAX_TABLE_PAGE_SIZE,
    )

    offset = (page - 1) * page_size

    return {
        "page": page,
        "page_size": page_size,
        "limit": page_size,
        "offset": offset,
    }


def get_sort_params() -> Dict[str, str]:
    """
    อ่าน sort params
    """

    return {
        "sort_by": get_str_arg("sort_by", ""),
        "sort_dir": get_str_arg("sort_dir", "asc").lower(),
    }


def get_common_query_context() -> Dict[str, Any]:
    """
    รวม query parameter ที่ใช้ซ้ำในหลาย API

    ใช้สำหรับ:
    - filter
    - pagination
    - sort
    - search
    - force refresh
    """

    context: Dict[str, Any] = {
        "force_refresh": get_bool_arg("force_refresh", False),
        "search": get_str_arg("search", ""),
        "target": get_str_arg("target", ""),
        **get_pagination_params(),
        **get_sort_params(),
    }

    simple_filters = {
        "province": get_list_arg("province"),
        "district": get_list_arg("district"),
        "subdistrict": get_list_arg("subdistrict"),
        "product": get_list_arg("product"),
        "subclass": get_list_arg("subclass"),
        "policy_status": get_list_arg("policy_status"),
        "loss_ratio_band": get_list_arg("loss_ratio_band"),
        "flood_risk_level": get_list_arg("flood_risk_level"),
        "wtip": get_list_arg("wtip"),
        "company_size": get_list_arg("company_size"),
        "business_type_tsic": get_list_arg("business_type_tsic"),
        "director_id": get_list_arg("director_id"),
        "policy_year": get_list_arg("policy_year"),
        "has_policy": request.args.get("has_policy"),
        "has_linkage": request.args.get("has_linkage"),
        "has_location": request.args.get("has_location"),
        "has_flood_context": request.args.get("has_flood_context"),
        "premium_min": get_float_arg("premium_min"),
        "premium_max": get_float_arg("premium_max"),
        "suminsure_min": get_float_arg("suminsure_min"),
        "suminsure_max": get_float_arg("suminsure_max"),
        "loss_ratio_min": get_float_arg("loss_ratio_min"),
        "loss_ratio_max": get_float_arg("loss_ratio_max"),
    }

    context["filters"] = {
        key: value
        for key, value in simple_filters.items()
        if value not in (None, "", [], {})
    }

    return context


# ============================================================
# 3) LAZY SERVICE IMPORT HELPERS
# ============================================================

def safe_call(
    import_path: str,
    function_name: str,
    fallback_data: Optional[Any] = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    เรียก service function แบบปลอดภัย

    เหตุผล:
    - โครงสร้างนี้มีหลาย service
    - บางไฟล์อาจยังเขียนไม่เสร็จตอนทดสอบ app.py/api_routes.py
    - route ไม่ควรทำให้ backend ล่มทันที
    - ควรตอบ fallback พร้อม warning กลับไปแทน

    Args:
        import_path:
            ชื่อ module เช่น company_policy_service

        function_name:
            ชื่อ function ที่จะเรียก เช่น get_company_list

        fallback_data:
            data ที่จะคืนถ้า import หรือ call ไม่ได้
    """

    if fallback_data is None:
        fallback_data = {}

    try:
        module = __import__(import_path, fromlist=[function_name])
        func = getattr(module, function_name)

        return func(*args, **kwargs)

    except Exception as exc:
        return {
            "fallback": True,
            "service_module": import_path,
            "service_function": function_name,
            "error": {
                "type": exc.__class__.__name__,
                "message": str(exc),
            },
            "data": fallback_data,
        }


def service_meta(result: Any, service_name: str) -> Dict[str, Any]:
    """
    สร้าง meta สำหรับ response ที่มาจาก service
    """

    meta: Dict[str, Any] = {
        "service": service_name,
    }

    if isinstance(result, dict):
        if "fallback" in result:
            meta["fallback"] = result.get("fallback")

        if "record_count" in result:
            meta["record_count"] = result.get("record_count")

        if "cache_used" in result:
            meta["cache_used"] = result.get("cache_used")

    return meta


def unwrap_service_result(result: Any) -> Any:
    """
    ถ้า service ส่ง dict ที่มี data ซ้อนอยู่ ให้คงไว้แบบไม่ทำลาย
    แต่ถ้าเป็น fallback จาก safe_call จะส่งทั้ง object กลับไปเพื่อ debug
    """

    return result


# ============================================================
# 4) API ROUTE REGISTRATION ENTRYPOINT
# ============================================================

def register_routes(app: Flask) -> None:
    """
    ฟังก์ชันหลักที่ app.py จะเรียกเพื่อ register API routes ทั้งหมด
    """

    register_core_routes(app)
    register_company_routes(app)
    register_policy_routes(app)
    register_linkage_routes(app)
    register_flood_routes(app)
    register_spatial_routes(app)
    register_map_graph_routes(app)
    register_dashboard_routes(app)
    register_filter_routes(app)
    register_data_quality_routes(app)
    register_package_routes(app)
    register_public_package_routes(app)


# ============================================================
# 5) CORE API
# ============================================================

def register_core_routes(app: Flask) -> None:
    """
    Core API:
    - health
    - status
    - config
    - routes
    - paths
    - inputs
    """

    @app.get(f"{API_PREFIX}/health")
    def api_health() -> Tuple[Response, int]:
        validation = validate_basic_config()

        status_code = 200 if validation["status"] != "error" else 500

        return success_response(
            message="TIPX health check",
            data={
                "app": APP_NAME,
                "short_name": APP_SHORT_NAME,
                "version": APP_VERSION,
                "description": APP_DESCRIPTION,
                "environment": DEFAULT_ENV,
                "status": validation["status"],
                "validation": validation,
            },
            meta={
                "module": "core",
            },
            status_code=status_code,
        )

    @app.get(f"{API_PREFIX}/status")
    def api_status() -> Tuple[Response, int]:
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

    @app.get(f"{API_PREFIX}/config")
    def api_config() -> Tuple[Response, int]:
        return success_response(
            message="TIPX config summary",
            data=get_config_summary(),
            meta={
                "module": "core",
            },
        )

    @app.get(f"{API_PREFIX}/paths")
    def api_paths() -> Tuple[Response, int]:
        return success_response(
            message="TIPX path status",
            data=get_system_path_status(),
            meta={
                "module": "core",
            },
        )

    @app.get(f"{API_PREFIX}/inputs")
    def api_inputs() -> Tuple[Response, int]:
        return success_response(
            message="TIPX input status",
            data=get_input_file_status(),
            meta={
                "module": "core",
            },
        )

    @app.get(f"{API_PREFIX}/routes")
    def api_routes() -> Tuple[Response, int]:
        routes: List[Dict[str, Any]] = []

        for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
            routes.append(
                {
                    "endpoint": rule.endpoint,
                    "rule": str(rule),
                    "methods": sorted(
                        [
                            method
                            for method in list(rule.methods or [])
                            if method not in {"HEAD", "OPTIONS"}
                        ]
                    ),
                }
            )

        return success_response(
            message="TIPX registered routes",
            data={
                "routes": routes,
            },
            meta={
                "module": "core",
                "record_count": len(routes),
            },
        )


# ============================================================
# 6) COMPANY API
# ============================================================

def register_company_routes(app: Flask) -> None:
    """
    Company API

    ใช้ข้อมูลจาก:
    - policy_company_summary
    - linkage company data
    - company_location_master
    - spatial_join_result
    - company_unified_master

    Service:
    - company_policy_service.py
    """

    @app.get(f"{API_PREFIX}/companies")
    def api_companies() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_company_list",
            {
                "records": [],
                "total": 0,
                "message": "company_policy_service.get_company_list not ready",
            },
            context=context,
        )

        return success_response(
            message="Company list",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_company_list"),
        )

    @app.get(f"{API_PREFIX}/companies/summary")
    def api_companies_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
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

        return success_response(
            message="Company summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_company_summary"),
        )

    @app.get(f"{API_PREFIX}/companies/<tax_id>")
    def api_company_detail(tax_id: str) -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_company_detail",
            {
                "tax_id": tax_id,
                "company": None,
                "message": "company detail not ready",
            },
            tax_id=tax_id,
            context=context,
        )

        return success_response(
            message="Company detail",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_company_detail"),
        )

    @app.get(f"{API_PREFIX}/companies/ranking/income")
    def api_companies_ranking_income() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_company_income_ranking",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Company income ranking",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_company_income_ranking"),
        )

    @app.get(f"{API_PREFIX}/companies/ranking/capital")
    def api_companies_ranking_capital() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_company_capital_ranking",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Company capital ranking",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_company_capital_ranking"),
        )

    @app.get(f"{API_PREFIX}/companies/source-flags")
    def api_companies_source_flags() -> Tuple[Response, int]:
        result = safe_call(
            "company_policy_service",
            "get_company_source_flags",
            {
                "has_policy": 0,
                "has_linkage": 0,
                "has_location": 0,
                "has_flood_context": 0,
            },
        )

        return success_response(
            message="Company source flags",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_company_source_flags"),
        )

    @app.get(f"{API_PREFIX}/companies/missing-policy")
    def api_companies_missing_policy() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_companies_missing_policy",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Companies missing policy",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_companies_missing_policy"),
        )

    @app.get(f"{API_PREFIX}/companies/missing-linkage")
    def api_companies_missing_linkage() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_companies_missing_linkage",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Companies missing linkage",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_companies_missing_linkage"),
        )

    @app.get(f"{API_PREFIX}/companies/missing-location")
    def api_companies_missing_location() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_companies_missing_location",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Companies missing location",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_companies_missing_location"),
        )


# ============================================================
# 7) POLICY API
# ============================================================

def register_policy_routes(app: Flask) -> None:
    """
    Policy API

    ใช้ข้อมูลจาก:
    - Policy Sheet 1
    - Policy Sheet 2
    - Policy Sheet 3
    - policy_fact
    - policy_company_summary
    """

    @app.get(f"{API_PREFIX}/policy/summary")
    def api_policy_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
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

        return success_response(
            message="Policy summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_summary"),
        )

    @app.get(f"{API_PREFIX}/policy/companies")
    def api_policy_companies() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_companies",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Policy companies",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_companies"),
        )

    @app.get(f"{API_PREFIX}/policy/company/<tax_id>")
    def api_policy_company(tax_id: str) -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_company_detail",
            {
                "tax_id": tax_id,
                "summary": {},
                "records": [],
            },
            tax_id=tax_id,
            context=context,
        )

        return success_response(
            message="Policy company detail",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_company_detail"),
        )

    @app.get(f"{API_PREFIX}/policy/company/<tax_id>/summary")
    def api_policy_company_summary(tax_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "company_policy_service",
            "get_policy_company_summary",
            {
                "tax_id": tax_id,
                "summary": {},
            },
            tax_id=tax_id,
        )

        return success_response(
            message="Policy company summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_company_summary"),
        )

    @app.get(f"{API_PREFIX}/policy/company/<tax_id>/table")
    def api_policy_company_table(tax_id: str) -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_company_table",
            {
                "tax_id": tax_id,
                "records": [],
                "total": 0,
            },
            tax_id=tax_id,
            context=context,
        )

        return success_response(
            message="Policy company table",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_company_table"),
        )

    @app.get(f"{API_PREFIX}/policy/company/<tax_id>/trend")
    def api_policy_company_trend(tax_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "company_policy_service",
            "get_policy_company_trend",
            {
                "tax_id": tax_id,
                "series": [],
            },
            tax_id=tax_id,
        )

        return success_response(
            message="Policy company trend",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_company_trend"),
        )

    @app.get(f"{API_PREFIX}/policy/product-summary")
    def api_policy_product_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_product_summary",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Policy product summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_product_summary"),
        )

    @app.get(f"{API_PREFIX}/policy/subclass-summary")
    def api_policy_subclass_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_subclass_summary",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Policy subclass summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_subclass_summary"),
        )

    @app.get(f"{API_PREFIX}/policy/yearly-summary")
    def api_policy_yearly_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_yearly_summary",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Policy yearly summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_yearly_summary"),
        )

    @app.get(f"{API_PREFIX}/policy/loss-ratio-ranking")
    def api_policy_loss_ratio_ranking() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_loss_ratio_ranking",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Policy loss ratio ranking",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_loss_ratio_ranking"),
        )

    @app.get(f"{API_PREFIX}/policy/high-loss")
    def api_policy_high_loss() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_high_loss_companies",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="High loss policy companies",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_high_loss_companies"),
        )

    @app.get(f"{API_PREFIX}/policy/exposure")
    def api_policy_exposure() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "company_policy_service",
            "get_policy_exposure",
            {
                "records": [],
                "summary": {},
            },
            context=context,
        )

        return success_response(
            message="Policy exposure",
            data=unwrap_service_result(result),
            meta=service_meta(result, "company_policy_service.get_policy_exposure"),
        )


# ============================================================
# 8) LINKAGE API
# ============================================================

def register_linkage_routes(app: Flask) -> None:
    """
    Linkage API

    ใช้ข้อมูลจาก:
    - Linkage Input
    - boardlist
    - director_master
    - linkage_nodes
    - linkage_edges
    """

    @app.get(f"{API_PREFIX}/linkage/summary")
    def api_linkage_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "linkage_service",
            "get_linkage_summary",
            {
                "total_companies": 0,
                "total_directors": 0,
                "total_edges": 0,
                "key_connector_count": 0,
            },
            context=context,
        )

        return success_response(
            message="Linkage summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "linkage_service.get_linkage_summary"),
        )

    @app.get(f"{API_PREFIX}/linkage/graph")
    def api_linkage_graph() -> Tuple[Response, int]:
        context = get_common_query_context()

        graph_context = {
            **context,
            "mode": get_str_arg("mode", GRAPH_DEFAULT_MODE),
            "depth": get_int_arg("depth", GRAPH_DEFAULT_DEPTH, min_value=1, max_value=5),
            "max_nodes": get_int_arg("max_nodes", GRAPH_DEFAULT_MAX_NODES, min_value=10, max_value=1500),
            "tax_id": get_str_arg("tax_id", ""),
            "director_id": get_str_arg("director_id", ""),
            "include_shared_edges": get_bool_arg("include_shared_edges", True),
            "include_policy": get_bool_arg("include_policy", True),
            "include_flood": get_bool_arg("include_flood", True),
        }

        result = safe_call(
            "linkage_service",
            "get_linkage_graph",
            {
                "nodes": [],
                "edges": [],
                "limited": False,
                "summary": {},
            },
            context=graph_context,
        )

        return success_response(
            message="Linkage graph",
            data=unwrap_service_result(result),
            meta=service_meta(result, "linkage_service.get_linkage_graph"),
        )

    @app.get(f"{API_PREFIX}/linkage/company/<tax_id>")
    def api_linkage_company(tax_id: str) -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "linkage_service",
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

        return success_response(
            message="Linkage company detail",
            data=unwrap_service_result(result),
            meta=service_meta(result, "linkage_service.get_linkage_company_detail"),
        )

    @app.get(f"{API_PREFIX}/linkage/director/<director_id>")
    def api_linkage_director(director_id: str) -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "linkage_service",
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

        return success_response(
            message="Linkage director detail",
            data=unwrap_service_result(result),
            meta=service_meta(result, "linkage_service.get_linkage_director_detail"),
        )

    @app.get(f"{API_PREFIX}/linkage/key-connectors")
    def api_linkage_key_connectors() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "linkage_service",
            "get_key_connectors",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Key connectors",
            data=unwrap_service_result(result),
            meta=service_meta(result, "linkage_service.get_key_connectors"),
        )

    @app.get(f"{API_PREFIX}/linkage/shared-directors")
    def api_linkage_shared_directors() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "linkage_service",
            "get_shared_director_links",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Shared director links",
            data=unwrap_service_result(result),
            meta=service_meta(result, "linkage_service.get_shared_director_links"),
        )

    @app.get(f"{API_PREFIX}/linkage/exposure-by-director")
    def api_linkage_exposure_by_director() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "linkage_service",
            "get_exposure_by_director",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Exposure by director",
            data=unwrap_service_result(result),
            meta=service_meta(result, "linkage_service.get_exposure_by_director"),
        )


# ============================================================
# 9) FLOOD API
# ============================================================

def register_flood_routes(app: Flask) -> None:
    """
    Flood API

    ใช้ข้อมูลจาก:
    - flood latest_database.xlsx
    - flood master_database.xlsx
    - flood history folder
    - flood_computed_risk
    """

    @app.get(f"{API_PREFIX}/flood/summary")
    def api_flood_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
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

        return success_response(
            message="Flood summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_flood_summary"),
        )

    @app.get(f"{API_PREFIX}/flood/rainfall/latest")
    def api_flood_rainfall_latest() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
            "get_rainfall_latest",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Rainfall latest",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_rainfall_latest"),
        )

    @app.get(f"{API_PREFIX}/flood/waterlevel/latest")
    def api_flood_waterlevel_latest() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
            "get_waterlevel_latest",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Waterlevel latest",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_waterlevel_latest"),
        )

    @app.get(f"{API_PREFIX}/flood/dam/large/latest")
    def api_flood_large_dam_latest() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
            "get_large_dam_latest",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Large dam latest",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_large_dam_latest"),
        )

    @app.get(f"{API_PREFIX}/flood/dam/medium/latest")
    def api_flood_medium_dam_latest() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
            "get_medium_dam_latest",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Medium dam latest",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_medium_dam_latest"),
        )

    @app.get(f"{API_PREFIX}/flood/computed-risk")
    def api_flood_computed_risk() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
            "get_flood_computed_risk",
            {
                "records": [],
                "total": 0,
                "risk_counts": {},
            },
            context=context,
        )

        return success_response(
            message="Flood computed risk",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_flood_computed_risk"),
        )

    @app.get(f"{API_PREFIX}/flood/boundaries/province")
    def api_flood_province_boundaries() -> Tuple[Response, int]:
        result = safe_call(
            "flood_spatial_service",
            "get_province_boundaries",
            {
                "type": "FeatureCollection",
                "features": [],
            },
        )

        return success_response(
            message="Province boundaries",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_province_boundaries"),
        )

    @app.get(f"{API_PREFIX}/flood/boundaries/basin")
    def api_flood_basin_boundaries() -> Tuple[Response, int]:
        result = safe_call(
            "flood_spatial_service",
            "get_basin_boundaries",
            {
                "type": "FeatureCollection",
                "features": [],
            },
        )

        return success_response(
            message="Basin boundaries",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_basin_boundaries"),
        )

    @app.post(f"{API_PREFIX}/flood/refresh")
    def api_flood_refresh() -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "flood_spatial_service",
            "refresh_flood_cache",
            {
                "refreshed": False,
                "message": "refresh function not ready",
            },
            payload=payload,
        )

        return success_response(
            message="Flood refresh requested",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.refresh_flood_cache"),
        )


# ============================================================
# 10) SPATIAL API
# ============================================================

def register_spatial_routes(app: Flask) -> None:
    """
    Spatial API

    ใช้ข้อมูลจาก:
    - company_unified_master
    - company_location_master
    - flood_computed_risk
    - station master
    - spatial_join_result
    """

    @app.get(f"{API_PREFIX}/spatial/company-flood-context")
    def api_spatial_company_flood_context() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
            "get_company_flood_context",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Company flood context",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_company_flood_context"),
        )

    @app.get(f"{API_PREFIX}/spatial/company/<tax_id>/flood-context")
    def api_spatial_company_single_flood_context(tax_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "flood_spatial_service",
            "get_single_company_flood_context",
            {
                "tax_id": tax_id,
                "context": {},
            },
            tax_id=tax_id,
        )

        return success_response(
            message="Single company flood context",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_single_company_flood_context"),
        )

    @app.get(f"{API_PREFIX}/spatial/policy-flood-exposure")
    def api_spatial_policy_flood_exposure() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
            "get_policy_flood_exposure",
            {
                "records": [],
                "summary": {},
            },
            context=context,
        )

        return success_response(
            message="Policy flood exposure",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_policy_flood_exposure"),
        )

    @app.get(f"{API_PREFIX}/spatial/province-risk-exposure")
    def api_spatial_province_risk_exposure() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "flood_spatial_service",
            "get_province_risk_exposure",
            {
                "records": [],
                "summary": {},
            },
            context=context,
        )

        return success_response(
            message="Province risk exposure",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_province_risk_exposure"),
        )

    @app.get(f"{API_PREFIX}/spatial/nearest-stations/<tax_id>")
    def api_spatial_nearest_stations(tax_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "flood_spatial_service",
            "get_nearest_stations_for_company",
            {
                "tax_id": tax_id,
                "rainfall": None,
                "waterlevel": None,
                "dam": None,
            },
            tax_id=tax_id,
        )

        return success_response(
            message="Nearest stations for company",
            data=unwrap_service_result(result),
            meta=service_meta(result, "flood_spatial_service.get_nearest_stations_for_company"),
        )


# ============================================================
# 11) MAP / GRAPH / CHART API
# ============================================================

def register_map_graph_routes(app: Flask) -> None:
    """
    Map / Graph / Chart API

    ใช้ข้อมูลจาก:
    - company_unified_master
    - policy exposure
    - flood computed risk
    - linkage graph
    - boundaries
    """

    @app.get(f"{API_PREFIX}/map/layers")
    def api_map_layers() -> Tuple[Response, int]:
        context = get_common_query_context()

        map_context = {
            **context,
            "include_companies": get_bool_arg("include_companies", True),
            "include_policy_exposure": get_bool_arg("include_policy_exposure", True),
            "include_flood": get_bool_arg("include_flood", True),
            "include_linkage_lines": get_bool_arg("include_linkage_lines", False),
            "include_branches": get_bool_arg("include_branches", True),
            "include_boundaries": get_bool_arg("include_boundaries", True),
            "cluster": get_bool_arg("cluster", True),
            "heatmap": get_bool_arg("heatmap", False),
            "zoom": get_int_arg("zoom", 6, min_value=1, max_value=20),
        }

        result = safe_call(
            "map_graph_service",
            "get_map_layers",
            {
                "layers": {},
                "summary": {},
            },
            context=map_context,
        )

        return success_response(
            message="Map layers",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_map_layers"),
        )

    @app.get(f"{API_PREFIX}/map/flood")
    def api_map_flood() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "map_graph_service",
            "get_flood_map_layer",
            {
                "type": "FeatureCollection",
                "features": [],
            },
            context=context,
        )

        return success_response(
            message="Flood map layer",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_flood_map_layer"),
        )

    @app.get(f"{API_PREFIX}/map/companies")
    def api_map_companies() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "map_graph_service",
            "get_company_map_layer",
            {
                "type": "FeatureCollection",
                "features": [],
            },
            context=context,
        )

        return success_response(
            message="Company map layer",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_company_map_layer"),
        )

    @app.get(f"{API_PREFIX}/map/policy-exposure")
    def api_map_policy_exposure() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "map_graph_service",
            "get_policy_exposure_map_layer",
            {
                "type": "FeatureCollection",
                "features": [],
            },
            context=context,
        )

        return success_response(
            message="Policy exposure map layer",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_policy_exposure_map_layer"),
        )

    @app.get(f"{API_PREFIX}/map/linkage-lines")
    def api_map_linkage_lines() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "map_graph_service",
            "get_linkage_line_layer",
            {
                "type": "FeatureCollection",
                "features": [],
            },
            context=context,
        )

        return success_response(
            message="Linkage line layer",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_linkage_line_layer"),
        )

    @app.get(f"{API_PREFIX}/map/branches")
    def api_map_branches() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "map_graph_service",
            "get_branch_map_layer",
            {
                "type": "FeatureCollection",
                "features": [],
            },
            context=context,
        )

        return success_response(
            message="Branch map layer",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_branch_map_layer"),
        )

    @app.get(f"{API_PREFIX}/map/heatmap")
    def api_map_heatmap() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "map_graph_service",
            "get_heatmap_layer",
            {
                "type": "FeatureCollection",
                "features": [],
            },
            context=context,
        )

        return success_response(
            message="Heatmap layer",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_heatmap_layer"),
        )

    @app.get(f"{API_PREFIX}/map/selected-context")
    def api_map_selected_context() -> Tuple[Response, int]:
        feature_id = get_str_arg("feature_id", "")
        feature_type = get_str_arg("feature_type", "")

        result = safe_call(
            "map_graph_service",
            "get_selected_map_context",
            {
                "feature_id": feature_id,
                "feature_type": feature_type,
                "context": {},
            },
            feature_id=feature_id,
            feature_type=feature_type,
        )

        return success_response(
            message="Selected map context",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_selected_map_context"),
        )

    @app.get(f"{API_PREFIX}/charts/summary")
    def api_charts_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "map_graph_service",
            "get_chart_summary",
            {
                "charts": {},
            },
            context=context,
        )

        return success_response(
            message="Chart summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "map_graph_service.get_chart_summary"),
        )


# ============================================================
# 12) DASHBOARD API
# ============================================================

def register_dashboard_routes(app: Flask) -> None:
    """
    Dashboard API

    ใช้สำหรับ:
    - Executive Overview
    - Dashboard Summary
    - Freshness
    - Overview payload
    """

    @app.get(f"{API_PREFIX}/dashboard/executive")
    def api_dashboard_executive() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "dashboard_package_service",
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

        return success_response(
            message="Executive dashboard",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_executive_dashboard"),
        )

    @app.get(f"{API_PREFIX}/dashboard/summary")
    def api_dashboard_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "dashboard_package_service",
            "get_dashboard_summary",
            {
                "summary_cards": {},
                "record_counts": {},
            },
            context=context,
        )

        return success_response(
            message="Dashboard summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_dashboard_summary"),
        )

    @app.get(f"{API_PREFIX}/dashboard/overview")
    def api_dashboard_overview() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "dashboard_package_service",
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

        return success_response(
            message="Dashboard overview",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_dashboard_overview"),
        )

    @app.get(f"{API_PREFIX}/dashboard/freshness")
    def api_dashboard_freshness() -> Tuple[Response, int]:
        result = safe_call(
            "dashboard_package_service",
            "get_dashboard_freshness",
            {
                "policy": {},
                "linkage": {},
                "flood": {},
                "cache": {},
            },
        )

        return success_response(
            message="Dashboard freshness",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_dashboard_freshness"),
        )


# ============================================================
# 13) FILTER BUILDER API
# ============================================================

def register_filter_routes(app: Flask) -> None:
    """
    Filter Builder API

    ใช้สำหรับ:
    - filter fields
    - quick presets
    - preview
    - apply
    - saved views
    """

    @app.get(f"{API_PREFIX}/filter/fields")
    def api_filter_fields() -> Tuple[Response, int]:
        result = safe_call(
            "filter_engine",
            "get_filter_fields",
            {
                "fields": [],
                "groups": {},
            },
        )

        return success_response(
            message="Filter fields",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.get_filter_fields"),
        )

    @app.get(f"{API_PREFIX}/filter/quick-presets")
    def api_filter_quick_presets() -> Tuple[Response, int]:
        result = safe_call(
            "filter_engine",
            "get_quick_filter_presets",
            {
                "presets": [],
            },
        )

        return success_response(
            message="Quick filter presets",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.get_quick_filter_presets"),
        )

    @app.post(f"{API_PREFIX}/filter/preview")
    def api_filter_preview() -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "filter_engine",
            "preview_filter",
            {
                "preview": {},
                "record_count": 0,
                "sample_records": [],
            },
            payload=payload,
        )

        return success_response(
            message="Filter preview",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.preview_filter"),
        )

    @app.post(f"{API_PREFIX}/filter/apply")
    def api_filter_apply() -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "filter_engine",
            "apply_filter",
            {
                "records": [],
                "total": 0,
                "summary": {},
            },
            payload=payload,
        )

        return success_response(
            message="Filter applied",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.apply_filter"),
        )

    @app.post(f"{API_PREFIX}/filter/save-view")
    def api_filter_save_view() -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "filter_engine",
            "save_filter_view",
            {
                "saved": False,
                "view_id": None,
            },
            payload=payload,
        )

        return success_response(
            message="Filter view saved",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.save_filter_view"),
        )

    @app.get(f"{API_PREFIX}/filter/saved-views")
    def api_filter_saved_views() -> Tuple[Response, int]:
        result = safe_call(
            "filter_engine",
            "get_saved_filter_views",
            {
                "views": [],
            },
        )

        return success_response(
            message="Saved filter views",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.get_saved_filter_views"),
        )

    @app.get(f"{API_PREFIX}/filter/saved-views/<view_id>")
    def api_filter_saved_view_detail(view_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "filter_engine",
            "get_saved_filter_view_detail",
            {
                "view_id": view_id,
                "view": None,
            },
            view_id=view_id,
        )

        return success_response(
            message="Saved filter view detail",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.get_saved_filter_view_detail"),
        )

    @app.put(f"{API_PREFIX}/filter/saved-views/<view_id>")
    def api_filter_saved_view_update(view_id: str) -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "filter_engine",
            "update_saved_filter_view",
            {
                "updated": False,
                "view_id": view_id,
            },
            view_id=view_id,
            payload=payload,
        )

        return success_response(
            message="Saved filter view updated",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.update_saved_filter_view"),
        )

    @app.delete(f"{API_PREFIX}/filter/saved-views/<view_id>")
    def api_filter_saved_view_delete(view_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "filter_engine",
            "delete_saved_filter_view",
            {
                "deleted": False,
                "view_id": view_id,
            },
            view_id=view_id,
        )

        return success_response(
            message="Saved filter view deleted",
            data=unwrap_service_result(result),
            meta=service_meta(result, "filter_engine.delete_saved_filter_view"),
        )


# ============================================================
# 14) DATA QUALITY API
# ============================================================

def register_data_quality_routes(app: Flask) -> None:
    """
    Data Quality API

    ใช้ตรวจ:
    - input
    - tax id
    - policy
    - linkage
    - location
    - flood
    - spatial
    - package
    """

    @app.get(f"{API_PREFIX}/data-quality/summary")
    def api_data_quality_summary() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
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

        return success_response(
            message="Data quality summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "data_quality.get_data_quality_summary"),
        )

    @app.get(f"{API_PREFIX}/data-quality/tax-id")
    def api_data_quality_tax_id() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "data_quality",
            "get_tax_id_quality",
            {
                "issues": [],
                "summary": {},
            },
            context=context,
        )

        return success_response(
            message="Tax ID data quality",
            data=unwrap_service_result(result),
            meta=service_meta(result, "data_quality.get_tax_id_quality"),
        )

    @app.get(f"{API_PREFIX}/data-quality/coordinates")
    def api_data_quality_coordinates() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "data_quality",
            "get_coordinate_quality",
            {
                "issues": [],
                "summary": {},
            },
            context=context,
        )

        return success_response(
            message="Coordinate data quality",
            data=unwrap_service_result(result),
            meta=service_meta(result, "data_quality.get_coordinate_quality"),
        )

    @app.get(f"{API_PREFIX}/data-quality/policy")
    def api_data_quality_policy() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "data_quality",
            "get_policy_quality",
            {
                "issues": [],
                "summary": {},
            },
            context=context,
        )

        return success_response(
            message="Policy data quality",
            data=unwrap_service_result(result),
            meta=service_meta(result, "data_quality.get_policy_quality"),
        )

    @app.get(f"{API_PREFIX}/data-quality/linkage")
    def api_data_quality_linkage() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "data_quality",
            "get_linkage_quality",
            {
                "issues": [],
                "summary": {},
            },
            context=context,
        )

        return success_response(
            message="Linkage data quality",
            data=unwrap_service_result(result),
            meta=service_meta(result, "data_quality.get_linkage_quality"),
        )

    @app.get(f"{API_PREFIX}/data-quality/spatial-join")
    def api_data_quality_spatial_join() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "data_quality",
            "get_spatial_join_quality",
            {
                "issues": [],
                "summary": {},
            },
            context=context,
        )

        return success_response(
            message="Spatial join data quality",
            data=unwrap_service_result(result),
            meta=service_meta(result, "data_quality.get_spatial_join_quality"),
        )

    @app.get(f"{API_PREFIX}/data-quality/status-conflicts")
    def api_data_quality_status_conflicts() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "data_quality",
            "get_policy_status_conflicts",
            {
                "records": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Policy status conflicts",
            data=unwrap_service_result(result),
            meta=service_meta(result, "data_quality.get_policy_status_conflicts"),
        )


# ============================================================
# 15) PACKAGE EXPORT API
# ============================================================

def register_package_routes(app: Flask) -> None:
    """
    Package API

    ใช้สำหรับ:
    - preview package
    - generate package
    - list package
    - download package
    - disable package
    - delete package
    """

    @app.post(f"{API_PREFIX}/packages/preview")
    def api_package_preview() -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "dashboard_package_service",
            "preview_package",
            {
                "components": PACKAGE_COMPONENTS,
                "security_options": PACKAGE_SECURITY_OPTIONS,
                "estimated_records": {},
                "warnings": [],
            },
            payload=payload,
        )

        return success_response(
            message="Package preview",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.preview_package"),
        )

    @app.post(f"{API_PREFIX}/packages/generate")
    def api_package_generate() -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "dashboard_package_service",
            "generate_package",
            {
                "generated": False,
                "package_id": None,
                "download_url": None,
                "public_url": None,
            },
            payload=payload,
        )

        return success_response(
            message="Package generation requested",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.generate_package"),
        )

    @app.get(f"{API_PREFIX}/packages")
    def api_package_list() -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "dashboard_package_service",
            "list_packages",
            {
                "packages": [],
                "total": 0,
            },
            context=context,
        )

        return success_response(
            message="Package list",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.list_packages"),
        )

    @app.get(f"{API_PREFIX}/packages/<package_id>")
    def api_package_detail(package_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "dashboard_package_service",
            "get_package_detail",
            {
                "package_id": package_id,
                "package": None,
            },
            package_id=package_id,
        )

        return success_response(
            message="Package detail",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_package_detail"),
        )

    @app.get(f"{API_PREFIX}/packages/<package_id>/download")
    def api_package_download(package_id: str) -> Any:
        """
        ดาวน์โหลด ZIP package

        ถ้า service ยังไม่พร้อม จะส่ง JSON fallback
        ถ้า service พร้อม สามารถ return send_file จาก service ได้
        """

        result = safe_call(
            "dashboard_package_service",
            "download_package",
            {
                "package_id": package_id,
                "download_ready": False,
                "message": "download service not ready",
            },
            package_id=package_id,
        )

        if hasattr(result, "status_code") or getattr(result, "direct_passthrough", False):
            return result

        return success_response(
            message="Package download",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.download_package"),
        )

    @app.post(f"{API_PREFIX}/packages/<package_id>/disable")
    def api_package_disable(package_id: str) -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "dashboard_package_service",
            "disable_package",
            {
                "package_id": package_id,
                "disabled": False,
            },
            package_id=package_id,
            payload=payload,
        )

        return success_response(
            message="Package disabled",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.disable_package"),
        )

    @app.delete(f"{API_PREFIX}/packages/<package_id>")
    def api_package_delete(package_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "dashboard_package_service",
            "delete_package",
            {
                "package_id": package_id,
                "deleted": False,
            },
            package_id=package_id,
        )

        return success_response(
            message="Package deleted",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.delete_package"),
        )


# ============================================================
# 16) PUBLIC EXTERNAL PACKAGE API
# ============================================================

def register_public_package_routes(app: Flask) -> None:
    """
    Public Package API

    ใช้สำหรับ external viewer

    หลักการ:
    - อ่าน package snapshot เท่านั้น
    - ไม่อ่าน internal pipeline โดยตรง
    - ไม่ expose raw internal service
    - รองรับ read-only mode
    """

    @app.get(f"{PUBLIC_API_PREFIX}/packages/<package_id>/meta")
    def public_package_meta(package_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "dashboard_package_service",
            "get_public_package_meta",
            {
                "package_id": package_id,
                "available": False,
                "meta": {},
            },
            package_id=package_id,
        )

        return success_response(
            message="Public package meta",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_public_package_meta"),
        )

    @app.get(f"{PUBLIC_API_PREFIX}/packages/<package_id>/data")
    def public_package_data(package_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "dashboard_package_service",
            "get_public_package_data",
            {
                "package_id": package_id,
                "data": {},
            },
            package_id=package_id,
        )

        return success_response(
            message="Public package data",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_public_package_data"),
        )

    @app.get(f"{PUBLIC_API_PREFIX}/packages/<package_id>/summary")
    def public_package_summary(package_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "dashboard_package_service",
            "get_public_package_summary",
            {
                "package_id": package_id,
                "summary": {},
            },
            package_id=package_id,
        )

        return success_response(
            message="Public package summary",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_public_package_summary"),
        )

    @app.get(f"{PUBLIC_API_PREFIX}/packages/<package_id>/map")
    def public_package_map(package_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "dashboard_package_service",
            "get_public_package_map",
            {
                "package_id": package_id,
                "layers": {},
            },
            package_id=package_id,
        )

        return success_response(
            message="Public package map",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_public_package_map"),
        )

    @app.get(f"{PUBLIC_API_PREFIX}/packages/<package_id>/charts")
    def public_package_charts(package_id: str) -> Tuple[Response, int]:
        result = safe_call(
            "dashboard_package_service",
            "get_public_package_charts",
            {
                "package_id": package_id,
                "charts": {},
            },
            package_id=package_id,
        )

        return success_response(
            message="Public package charts",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_public_package_charts"),
        )

    @app.get(f"{PUBLIC_API_PREFIX}/packages/<package_id>/tables")
    def public_package_tables(package_id: str) -> Tuple[Response, int]:
        context = get_common_query_context()

        result = safe_call(
            "dashboard_package_service",
            "get_public_package_tables",
            {
                "package_id": package_id,
                "tables": {},
            },
            package_id=package_id,
            context=context,
        )

        return success_response(
            message="Public package tables",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.get_public_package_tables"),
        )

    @app.post(f"{PUBLIC_API_PREFIX}/packages/<package_id>/access-log")
    def public_package_access_log(package_id: str) -> Tuple[Response, int]:
        payload = get_json_payload()

        result = safe_call(
            "dashboard_package_service",
            "write_public_package_access_log",
            {
                "package_id": package_id,
                "logged": False,
            },
            package_id=package_id,
            payload={
                **payload,
                "remote_addr": request.remote_addr,
                "user_agent": request.headers.get("User-Agent", ""),
                "accessed_at": now_iso(),
            },
        )

        return success_response(
            message="Public package access logged",
            data=unwrap_service_result(result),
            meta=service_meta(result, "dashboard_package_service.write_public_package_access_log"),
        )