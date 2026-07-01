# ============================================================
# FILE: backend/dashboard_package_service.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 13 / 20
# ============================================================

"""
backend/dashboard_package_service.py

ไฟล์นี้เป็นศูนย์กลาง Dashboard Summary / Chart Payload / Package Export / External Viewer Package ของระบบ TIPX

หน้าที่หลัก:
1. สร้าง Executive Dashboard
2. สร้าง Dashboard Overview
3. สร้าง Dashboard Summary Cards
4. สร้าง Chart Payload สำหรับ frontend
5. รวมข้อมูล Company / Policy / Linkage / Flood / Map / Data Quality
6. สร้าง Package Preview
7. สร้าง Package Export Snapshot
8. สร้าง External Viewer Package
9. สร้าง public package data endpoint
10. จัดการ package list / detail / disable / delete
11. สร้างไฟล์ JSON / Excel / ZIP สำหรับส่งต่อ
12. รองรับ API กลุ่ม /api/dashboard/*
13. รองรับ API กลุ่ม /api/charts/*
14. รองรับ API กลุ่ม /api/packages/*
15. รองรับ API กลุ่ม /api/public/packages/*

Package Structure:
packages/
└── PKG_YYYYMMDD_HHMMSS_RANDOM/
    ├── package_meta.json
    ├── package_snapshot.json
    ├── public_data.json
    ├── summary.json
    ├── map.json
    ├── charts.json
    ├── tables.json
    ├── access_log.jsonl
    ├── exports/
    │   ├── company_unified_master.xlsx
    │   ├── policy_summary.xlsx
    │   ├── linkage_summary.xlsx
    │   └── data_quality.xlsx
    └── external_viewer/
        ├── index.html
        ├── data/
        │   └── public_data.json
        └── assets/
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
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import (
    APP_NAME,
    APP_SHORT_NAME,
    APP_VERSION,
    API_PREFIX,
    PUBLIC_API_PREFIX,
    PACKAGE_DIR,
    PACKAGE_COMPONENTS,
    PACKAGE_SECURITY_OPTIONS,
    PACKAGE_DEFAULT_EXPIRE_DAYS,
    PACKAGE_MAX_EXPIRE_DAYS,
    PACKAGE_INDEX_FILENAME,
    PACKAGE_META_FILENAME,
    PACKAGE_SNAPSHOT_FILENAME,
    PACKAGE_PUBLIC_DATA_FILENAME,
    PACKAGE_EXPORT_DIRNAME,
    PACKAGE_EXTERNAL_VIEWER_DIRNAME,
    OUTPUT_DIR,
    CACHE_TTL_SECONDS,
    RISK_LEVELS,
    RISK_COLORS,
    RISK_SCORE,
)

from utils import (
    apply_search_sort_pagination,
    clean_text,
    clean_text_lower,
    create_zip_from_folder,
    dataframe_to_records,
    ensure_dir,
    ensure_parent_dir,
    file_info,
    format_number,
    format_percent,
    get_or_build_cache,
    is_empty_value,
    normalize_risk_level,
    normalize_tax_id,
    read_json,
    safe_filename,
    sum_field,
    to_bool,
    to_int,
    to_jsonable,
    to_number,
    write_excel,
    write_json,
    write_text,
)

from security import (
    apply_export_field_policy_to_records,
    attach_package_checksum,
    build_access_log_record,
    build_package_meta,
    build_public_api_urls,
    build_public_error,
    build_public_package_snapshot,
    build_public_success,
    build_safe_public_meta,
    check_public_package_access,
    extract_public_package_component,
    generate_package_id,
    normalize_security_options,
    sanitize_package_components,
    sanitize_public_payload,
    verify_package_checksum,
)

try:
    from company_policy_service import (
        get_company_list,
        get_company_summary,
        get_company_detail,
        get_company_unified_records,
        get_policy_summary,
        get_policy_companies,
        get_policy_product_summary,
        get_policy_subclass_summary,
        get_policy_yearly_summary,
        get_policy_loss_ratio_ranking,
        get_policy_high_loss_companies,
        get_policy_exposure,
        get_company_policy_dashboard_payload,
        rebuild_company_policy_cache,
    )
except Exception:
    get_company_list = None
    get_company_summary = None
    get_company_detail = None
    get_company_unified_records = None
    get_policy_summary = None
    get_policy_companies = None
    get_policy_product_summary = None
    get_policy_subclass_summary = None
    get_policy_yearly_summary = None
    get_policy_loss_ratio_ranking = None
    get_policy_high_loss_companies = None
    get_policy_exposure = None
    get_company_policy_dashboard_payload = None
    rebuild_company_policy_cache = None

try:
    from linkage_service import (
        get_linkage_summary,
        get_linkage_graph,
        get_key_connectors,
        get_shared_director_links,
        get_exposure_by_director,
        get_linkage_dashboard_payload,
        rebuild_linkage_cache,
    )
except Exception:
    get_linkage_summary = None
    get_linkage_graph = None
    get_key_connectors = None
    get_shared_director_links = None
    get_exposure_by_director = None
    get_linkage_dashboard_payload = None
    rebuild_linkage_cache = None

try:
    from flood_spatial_service import (
        get_flood_summary,
        get_flood_computed_risk,
        get_policy_flood_exposure,
        get_province_risk_exposure,
        get_company_flood_context,
        get_flood_dashboard_payload,
        rebuild_flood_spatial_cache,
    )
except Exception:
    get_flood_summary = None
    get_flood_computed_risk = None
    get_policy_flood_exposure = None
    get_province_risk_exposure = None
    get_company_flood_context = None
    get_flood_dashboard_payload = None
    rebuild_flood_spatial_cache = None

try:
    from map_graph_service import (
        get_map_layers,
        get_map_dashboard_payload,
        get_external_viewer_map_payload,
        rebuild_map_cache,
    )
except Exception:
    get_map_layers = None
    get_map_dashboard_payload = None
    get_external_viewer_map_payload = None
    rebuild_map_cache = None

try:
    from data_quality import (
        get_data_quality_summary,
        build_data_quality_dashboard_payload,
    )
except Exception:
    get_data_quality_summary = None
    build_data_quality_dashboard_payload = None

try:
    from filter_engine import (
        build_filter_context_for_package,
        preview_filter,
        apply_filter,
        get_filter_options_from_records,
    )
except Exception:
    build_filter_context_for_package = None
    preview_filter = None
    apply_filter = None
    get_filter_options_from_records = None


# ============================================================
# 1) CONSTANTS
# ============================================================

DEFAULT_CONTEXT: Dict[str, Any] = {
    "force_refresh": False,
    "page": 1,
    "page_size": 50,
    "search": "",
    "sort_by": "",
    "sort_dir": "asc",
    "filters": {},
    "include_map": True,
    "include_graph": True,
    "include_data_quality": True,
}

CACHE_KEYS: Dict[str, str] = {
    "dashboard_summary": "dashboard_summary",
    "dashboard_overview": "dashboard_overview",
    "executive_dashboard": "executive_dashboard",
    "chart_summary": "chart_summary",
    "data_freshness": "data_freshness",
}

SUMMARY_STATUS_ORDER: Dict[str, int] = {
    "Normal": 1,
    "Watch": 2,
    "Warning": 3,
    "Critical": 4,
    "Unknown": 0,
}

DEFAULT_PACKAGE_COMPONENTS: List[str] = list(PACKAGE_COMPONENTS)

PUBLIC_COMPONENT_FILES: Dict[str, str] = {
    "meta": PACKAGE_META_FILENAME,
    "data": PACKAGE_PUBLIC_DATA_FILENAME,
    "summary": "summary.json",
    "map": "map.json",
    "charts": "charts.json",
    "tables": "tables.json",
}


# ============================================================
# 2) BASIC HELPERS
# ============================================================

def now_iso() -> str:
    """
    คืนเวลาปัจจุบันแบบ ISO string
    """

    return datetime.now().isoformat(timespec="seconds")


def normalize_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    normalize context จาก api_routes.py
    """

    result = dict(DEFAULT_CONTEXT)
    result.update(context or {})

    result["force_refresh"] = bool(result.get("force_refresh", False))
    result["page"] = int(result.get("page", 1) or 1)
    result["page_size"] = int(result.get("page_size", 50) or 50)
    result["search"] = clean_text(result.get("search", ""))
    result["sort_by"] = clean_text(result.get("sort_by", ""))
    result["sort_dir"] = clean_text_lower(result.get("sort_dir", "asc")) or "asc"

    if not isinstance(result.get("filters"), dict):
        result["filters"] = {}

    result["include_map"] = bool(to_bool(result.get("include_map", True), default=True))
    result["include_graph"] = bool(to_bool(result.get("include_graph", True), default=True))
    result["include_data_quality"] = bool(to_bool(result.get("include_data_quality", True), default=True))

    return result


def get_dashboard_ttl() -> int:
    """
    TTL สำหรับ dashboard cache
    """

    return int(CACHE_TTL_SECONDS.get("dashboard", 900))


def safe_call_service(function_ref: Any, fallback: Any = None, *args: Any, **kwargs: Any) -> Any:
    """
    เรียก service function แบบปลอดภัย
    """

    if function_ref is None:
        return fallback if fallback is not None else {}

    try:
        return function_ref(*args, **kwargs)
    except Exception as exc:
        return {
            "error": True,
            "message": str(exc),
            "function": getattr(function_ref, "__name__", "unknown"),
            "data": fallback if fallback is not None else {},
        }


def extract_records(payload: Any) -> List[Dict[str, Any]]:
    """
    ดึง records จาก payload หลายรูปแบบ
    """

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            return payload["records"]

        if isinstance(payload.get("data"), list):
            return payload["data"]

        if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("records"), list):
            return payload["data"]["records"]

    return []


def ensure_package_root() -> Path:
    """
    สร้าง package root
    """

    return ensure_dir(PACKAGE_DIR)


def get_package_folder(package_id: str) -> Path:
    """
    คืน path package folder
    """

    safe_id = safe_filename(package_id, default="package")
    return PACKAGE_DIR / safe_id


def get_package_file(package_id: str, filename: str) -> Path:
    """
    คืน path file ใน package folder
    """

    return get_package_folder(package_id) / filename


def get_package_exports_folder(package_id: str) -> Path:
    """
    คืน path exports folder ใน package
    """

    return get_package_folder(package_id) / PACKAGE_EXPORT_DIRNAME


def get_package_external_viewer_folder(package_id: str) -> Path:
    """
    คืน path external viewer folder ใน package
    """

    return get_package_folder(package_id) / PACKAGE_EXTERNAL_VIEWER_DIRNAME


def get_package_zip_path(package_id: str) -> Path:
    """
    คืน path zip package
    """

    return PACKAGE_DIR / f"{safe_filename(package_id, default='package')}.zip"


# ============================================================
# 3) SUMMARY CARD HELPERS
# ============================================================

def build_summary_card(
    key: str,
    label: str,
    value: Any,
    unit: str = "",
    status: str = "Normal",
    description: str = "",
    display_value: Optional[str] = None,
    delta: Optional[Any] = None,
    delta_label: str = "",
) -> Dict[str, Any]:
    """
    สร้าง summary card สำหรับ dashboard
    """

    if display_value is None:
        if isinstance(value, (int, float)):
            display_value = format_number(value, digits=2 if isinstance(value, float) else 0)
        else:
            display_value = clean_text(value)

    if unit and display_value not in {"", "-"}:
        display_value = f"{display_value} {unit}"

    return {
        "key": key,
        "label": label,
        "value": to_jsonable(value),
        "display_value": display_value,
        "unit": unit,
        "status": normalize_risk_level(status) if status in RISK_LEVELS else status,
        "description": description,
        "delta": to_jsonable(delta),
        "delta_label": delta_label,
    }


def get_status_from_count(value: Any, warning_min: int = 1, critical_min: int = 10) -> str:
    """
    แปลงจำนวน issue / warning เป็น status
    """

    number = to_number(value, 0) or 0

    if number >= critical_min:
        return "Critical"

    if number >= warning_min:
        return "Warning"

    return "Normal"


def get_highest_status(statuses: List[Any]) -> str:
    """
    หา status ที่สูงสุดจาก list
    """

    best = "Unknown"
    best_score = -1

    for status in statuses:
        text = clean_text(status, default="Unknown")
        score = SUMMARY_STATUS_ORDER.get(text, RISK_SCORE.get(text, 0))

        if score > best_score:
            best = text
            best_score = score

    return best


# ============================================================
# 4) CHART HELPERS
# ============================================================

def build_chart_payload(
    chart_id: str,
    chart_type: str,
    title: str,
    labels: List[Any],
    datasets: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง chart payload กลางสำหรับ Chart.js
    """

    return {
        "chart_id": chart_id,
        "chart_type": chart_type,
        "title": title,
        "labels": to_jsonable(labels),
        "datasets": to_jsonable(datasets),
        "options": options or {},
        "meta": {
            "generated_at": now_iso(),
            **(meta or {}),
        },
    }


def make_counter_chart(
    chart_id: str,
    title: str,
    counter: Dict[str, Any],
    chart_type: str = "bar",
    dataset_label: str = "Count",
) -> Dict[str, Any]:
    """
    สร้าง chart จาก counter dict
    """

    labels = list(counter.keys())
    values = [counter[key] for key in labels]

    return build_chart_payload(
        chart_id=chart_id,
        chart_type=chart_type,
        title=title,
        labels=labels,
        datasets=[
            {
                "label": dataset_label,
                "data": values,
            }
        ],
    )


def make_table_payload(
    table_id: str,
    title: str,
    records: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    สร้าง payload table สำหรับ frontend
    """

    records = records[:limit]

    if columns is None:
        columns = sorted({key for record in records for key in record.keys()}) if records else []

    return {
        "table_id": table_id,
        "title": title,
        "columns": columns,
        "records": records,
        "total": len(records),
        "generated_at": now_iso(),
    }


# ============================================================
# 5) DATA FRESHNESS
# ============================================================

def get_data_freshness(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/dashboard/freshness

    ตรวจความสดของข้อมูลจาก cache และ package folder
    """

    ctx = normalize_context(context)

    watched_files = {
        "package_dir": PACKAGE_DIR,
        "output_dir": OUTPUT_DIR,
    }

    cache_files = {
        "company_unified_master": "company_unified_master",
        "policy_fact": "policy_fact",
        "director_master": "director_master",
        "linkage_graph_payload": "linkage_graph_payload",
        "flood_computed_risk": "flood_computed_risk",
        "spatial_join_result": "spatial_join_result",
        "map_layers": "map_layers",
        "data_quality_summary": "data_quality_summary",
    }

    freshness: Dict[str, Any] = {
        "checked_at": now_iso(),
        "files": {
            key: file_info(path)
            for key, path in watched_files.items()
        },
        "cache": {},
    }

    from utils import get_cache_file_path

    for label, cache_key in cache_files.items():
        path = get_cache_file_path(cache_key)
        info = file_info(path)

        if info.get("exists"):
            modified_at = info.get("modified_at")
            age_seconds = None

            try:
                modified_dt = datetime.fromisoformat(modified_at)
                age_seconds = round((datetime.now() - modified_dt).total_seconds(), 2)
            except Exception:
                age_seconds = None

            info["age_seconds"] = age_seconds
            info["age_minutes"] = round(age_seconds / 60, 2) if age_seconds is not None else None

        freshness["cache"][label] = info

    existing_cache = [
        item
        for item in freshness["cache"].values()
        if item.get("exists")
    ]

    missing_cache = [
        key
        for key, item in freshness["cache"].items()
        if not item.get("exists")
    ]

    freshness["summary"] = {
        "cache_count": len(freshness["cache"]),
        "existing_cache_count": len(existing_cache),
        "missing_cache_count": len(missing_cache),
        "missing_cache": missing_cache,
        "status": "Warning" if missing_cache else "Normal",
    }

    return freshness


# ============================================================
# 6) DASHBOARD SUMMARY BUILDERS
# ============================================================

def build_dashboard_summary(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง dashboard summary กลาง
    """

    def builder() -> Dict[str, Any]:
        company_summary = safe_call_service(get_company_summary, fallback={})
        policy_summary = safe_call_service(get_policy_summary, fallback={})
        linkage_summary = safe_call_service(get_linkage_summary, fallback={})
        flood_summary = safe_call_service(get_flood_summary, fallback={})
        dq_summary = safe_call_service(get_data_quality_summary, fallback={})

        total_companies = company_summary.get("total_companies", 0)
        total_suminsure = company_summary.get("total_suminsure", 0)
        total_premium = company_summary.get("total_premium", 0)
        total_loss = company_summary.get("total_loss", 0)

        flood_risk_counts = company_summary.get("flood_risk_counts", {}) or {}
        quality_score = dq_summary.get("quality_score", 100)
        total_issues = dq_summary.get("total_issues", 0)

        overall_status = get_highest_status(
            [
                "Critical" if flood_risk_counts.get("Critical", 0) else "Normal",
                "Warning" if flood_risk_counts.get("Warning", 0) else "Normal",
                get_status_from_count(total_issues, warning_min=1, critical_min=20),
            ]
        )

        summary_cards = [
            build_summary_card(
                key="total_companies",
                label="Companies",
                value=total_companies,
                status="Normal",
                description="จำนวนบริษัทใน Company Unified Master",
            ),
            build_summary_card(
                key="total_suminsure",
                label="Total Sum Insured",
                value=total_suminsure,
                unit="THB",
                status="Normal",
                description="ทุนประกันรวมของบริษัทที่มี policy",
            ),
            build_summary_card(
                key="total_premium",
                label="Total Premium",
                value=total_premium,
                unit="THB",
                status="Normal",
                description="เบี้ยประกันรวม",
            ),
            build_summary_card(
                key="total_loss",
                label="Total Loss",
                value=total_loss,
                unit="THB",
                status="Watch" if (to_number(total_loss, 0) or 0) > 0 else "Normal",
                description="ค่าสินไหมรวม",
            ),
            build_summary_card(
                key="flood_critical_companies",
                label="Flood Critical",
                value=flood_risk_counts.get("Critical", 0),
                status="Critical" if flood_risk_counts.get("Critical", 0) else "Normal",
                description="จำนวนบริษัทที่อยู่ในพื้นที่เสี่ยง Critical",
            ),
            build_summary_card(
                key="key_connectors",
                label="Key Connectors",
                value=linkage_summary.get("total_key_connectors", 0),
                status="Watch" if linkage_summary.get("total_key_connectors", 0) else "Normal",
                description="กรรมการที่เชื่อมมากกว่า 1 บริษัท",
            ),
            build_summary_card(
                key="data_quality_score",
                label="Data Quality",
                value=quality_score,
                unit="%",
                status=dq_summary.get("quality_level", "Normal"),
                description="คะแนนคุณภาพข้อมูลรวม",
                display_value=format_percent(quality_score, digits=2),
            ),
            build_summary_card(
                key="data_quality_issues",
                label="DQ Issues",
                value=total_issues,
                status=get_status_from_count(total_issues, warning_min=1, critical_min=20),
                description="จำนวน Data Quality Issues",
            ),
        ]

        charts = build_chart_summary_payload(
            company_summary=company_summary,
            policy_summary=policy_summary,
            linkage_summary=linkage_summary,
            flood_summary=flood_summary,
            data_quality_summary=dq_summary,
        )

        return {
            "overall_status": overall_status,
            "summary_cards": summary_cards,
            "company_summary": company_summary,
            "policy_summary": policy_summary,
            "linkage_summary": linkage_summary,
            "flood_summary": flood_summary,
            "data_quality_summary": dq_summary,
            "charts": charts,
            "freshness": get_data_freshness(),
            "generated_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["dashboard_summary"],
        builder=builder,
        ttl_seconds=get_dashboard_ttl(),
        force_refresh=force_refresh,
        source="dashboard_package_service.build_dashboard_summary",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def build_chart_summary_payload(
    company_summary: Optional[Dict[str, Any]] = None,
    policy_summary: Optional[Dict[str, Any]] = None,
    linkage_summary: Optional[Dict[str, Any]] = None,
    flood_summary: Optional[Dict[str, Any]] = None,
    data_quality_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง charts รวมของ dashboard
    """

    company_summary = company_summary or safe_call_service(get_company_summary, fallback={})
    policy_summary = policy_summary or safe_call_service(get_policy_summary, fallback={})
    linkage_summary = linkage_summary or safe_call_service(get_linkage_summary, fallback={})
    flood_summary = flood_summary or safe_call_service(get_flood_summary, fallback={})
    data_quality_summary = data_quality_summary or safe_call_service(get_data_quality_summary, fallback={})

    charts = {
        "company_by_province": make_counter_chart(
            chart_id="company_by_province",
            title="Companies by Province",
            counter=company_summary.get("province_counts", {}),
            chart_type="bar",
            dataset_label="Companies",
        ),
        "company_flood_risk": make_counter_chart(
            chart_id="company_flood_risk",
            title="Company Flood Risk",
            counter=company_summary.get("flood_risk_counts", {}),
            chart_type="doughnut",
            dataset_label="Companies",
        ),
        "flood_source_risk": make_counter_chart(
            chart_id="flood_source_risk",
            title="Flood Source Risk",
            counter=flood_summary.get("risk_counts", {}),
            chart_type="doughnut",
            dataset_label="Sources",
        ),
        "flood_source_type": make_counter_chart(
            chart_id="flood_source_type",
            title="Flood Source Type",
            counter=flood_summary.get("source_counts", {}),
            chart_type="bar",
            dataset_label="Sources",
        ),
        "data_quality_severity": make_counter_chart(
            chart_id="data_quality_severity",
            title="Data Quality by Severity",
            counter=data_quality_summary.get("by_severity", {}),
            chart_type="bar",
            dataset_label="Issues",
        ),
        "data_quality_category": make_counter_chart(
            chart_id="data_quality_category",
            title="Data Quality by Category",
            counter=data_quality_summary.get("by_category", {}),
            chart_type="bar",
            dataset_label="Issues",
        ),
    }

    yearly_records = policy_summary.get("yearly_summary", []) or []

    charts["policy_yearly_trend"] = build_chart_payload(
        chart_id="policy_yearly_trend",
        chart_type="line",
        title="Policy Yearly Trend",
        labels=[record.get("policy_year") for record in yearly_records],
        datasets=[
            {
                "label": "Premium",
                "data": [record.get("total_premium", 0) for record in yearly_records],
            },
            {
                "label": "Loss",
                "data": [record.get("total_loss", 0) for record in yearly_records],
            },
            {
                "label": "Sum Insured",
                "data": [record.get("total_suminsure", 0) for record in yearly_records],
            },
        ],
    )

    product_records = policy_summary.get("product_summary", []) or []

    charts["policy_product_top"] = build_chart_payload(
        chart_id="policy_product_top",
        chart_type="bar",
        title="Top Policy Products",
        labels=[record.get("product") for record in product_records[:15]],
        datasets=[
            {
                "label": "Premium",
                "data": [record.get("total_premium", 0) for record in product_records[:15]],
            }
        ],
    )

    return charts


def get_dashboard_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/dashboard/summary
    """

    ctx = normalize_context(context)
    return build_dashboard_summary(force_refresh=ctx.get("force_refresh", False))


def get_dashboard_overview(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/dashboard/overview
    """

    ctx = normalize_context(context)

    summary = build_dashboard_summary(force_refresh=ctx.get("force_refresh", False))

    company_dashboard = safe_call_service(get_company_policy_dashboard_payload, fallback={}, context=ctx)
    linkage_dashboard = safe_call_service(get_linkage_dashboard_payload, fallback={}, context=ctx)
    flood_dashboard = safe_call_service(get_flood_dashboard_payload, fallback={}, context=ctx)
    map_dashboard = safe_call_service(get_map_dashboard_payload, fallback={}, context=ctx)
    dq_dashboard = safe_call_service(build_data_quality_dashboard_payload, fallback={}, context=ctx)

    return {
        "summary": summary,
        "company_policy": company_dashboard,
        "linkage": linkage_dashboard,
        "flood": flood_dashboard,
        "map": map_dashboard,
        "data_quality": dq_dashboard,
        "generated_at": now_iso(),
    }


def get_executive_dashboard(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/dashboard/executive

    สรุปสำหรับผู้บริหาร
    """

    ctx = normalize_context(context)

    summary = build_dashboard_summary(force_refresh=ctx.get("force_refresh", False))
    policy_exposure = safe_call_service(get_policy_exposure, fallback={}, context={"page": 1, "page_size": 10})
    high_loss = safe_call_service(get_policy_high_loss_companies, fallback={}, context={"page": 1, "page_size": 10})
    key_connectors = safe_call_service(get_key_connectors, fallback={}, context={"page": 1, "page_size": 10})
    province_risk = safe_call_service(get_province_risk_exposure, fallback={}, context={"page": 1, "page_size": 10})

    executive_insights = build_executive_insights(
        summary=summary,
        high_loss_records=extract_records(high_loss),
        key_connector_records=extract_records(key_connectors),
        province_risk_records=extract_records(province_risk),
    )

    return {
        "title": "TIPX Executive Dashboard",
        "generated_at": now_iso(),
        "overall_status": summary.get("overall_status", "Unknown"),
        "summary_cards": summary.get("summary_cards", []),
        "executive_insights": executive_insights,
        "policy_exposure": policy_exposure.get("summary", policy_exposure),
        "high_loss_companies": extract_records(high_loss),
        "key_connectors": extract_records(key_connectors),
        "province_risk_exposure": extract_records(province_risk),
        "charts": summary.get("charts", {}),
        "freshness": summary.get("freshness", {}),
    }


def build_executive_insights(
    summary: Dict[str, Any],
    high_loss_records: List[Dict[str, Any]],
    key_connector_records: List[Dict[str, Any]],
    province_risk_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    สร้าง insight cards สำหรับ executive dashboard
    """

    insights: List[Dict[str, Any]] = []

    flood_summary = summary.get("flood_summary", {})
    company_summary = summary.get("company_summary", {})
    dq_summary = summary.get("data_quality_summary", {})

    critical_count = (company_summary.get("flood_risk_counts", {}) or {}).get("Critical", 0)
    warning_count = (company_summary.get("flood_risk_counts", {}) or {}).get("Warning", 0)

    if critical_count:
        insights.append(
            {
                "type": "risk",
                "severity": "Critical",
                "title": "Critical flood exposure detected",
                "message": f"พบบริษัทในระดับ Critical จำนวน {critical_count} รายการ",
                "action": "ตรวจสอบแผนที่และ policy exposure ทันที",
            }
        )

    if warning_count:
        insights.append(
            {
                "type": "risk",
                "severity": "Warning",
                "title": "Warning flood exposure detected",
                "message": f"พบบริษัทในระดับ Warning จำนวน {warning_count} รายการ",
                "action": "ติดตามสถานการณ์และรายการทุนประกันในพื้นที่",
            }
        )

    if high_loss_records:
        insights.append(
            {
                "type": "policy",
                "severity": "Warning",
                "title": "High loss-ratio companies",
                "message": f"พบบริษัท loss ratio สูง {len(high_loss_records)} รายการใน top list",
                "action": "ตรวจสอบ underwriting / claim history",
            }
        )

    if key_connector_records:
        insights.append(
            {
                "type": "linkage",
                "severity": "Watch",
                "title": "Key connectors in linkage network",
                "message": f"พบกรรมการเชื่อมโยงหลายบริษัท {len(key_connector_records)} รายการใน top list",
                "action": "ตรวจสอบ exposure และความสัมพันธ์ข้ามบริษัท",
            }
        )

    dq_issues = dq_summary.get("total_issues", 0)

    if dq_issues:
        insights.append(
            {
                "type": "data_quality",
                "severity": get_status_from_count(dq_issues, warning_min=1, critical_min=20),
                "title": "Data quality issues require review",
                "message": f"พบ data quality issue ทั้งหมด {dq_issues} รายการ",
                "action": "เปิดหน้า Data Quality เพื่อตรวจรายการที่ผิดปกติ",
            }
        )

    if not insights:
        insights.append(
            {
                "type": "overall",
                "severity": "Normal",
                "title": "No critical insight detected",
                "message": "ยังไม่พบประเด็น Critical จากข้อมูลล่าสุด",
                "action": "ติดตาม dashboard ตามรอบ update",
            }
        )

    return insights


# ============================================================
# 7) CHART API FUNCTIONS
# ============================================================

def get_chart_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/charts/summary
    """

    ctx = normalize_context(context)

    summary = build_dashboard_summary(force_refresh=ctx.get("force_refresh", False))

    return {
        "charts": summary.get("charts", {}),
        "generated_at": now_iso(),
    }


def get_policy_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API helper: policy charts
    """

    policy_summary = safe_call_service(get_policy_summary, fallback={})

    charts = {
        "yearly": build_chart_summary_payload(policy_summary=policy_summary).get("policy_yearly_trend"),
        "product": build_chart_summary_payload(policy_summary=policy_summary).get("policy_product_top"),
    }

    subclass_records = policy_summary.get("subclass_summary", []) or []

    charts["subclass"] = build_chart_payload(
        chart_id="policy_subclass_top",
        chart_type="bar",
        title="Top Policy Subclass",
        labels=[record.get("subclass") for record in subclass_records[:15]],
        datasets=[
            {
                "label": "Premium",
                "data": [record.get("total_premium", 0) for record in subclass_records[:15]],
            }
        ],
    )

    return {
        "charts": charts,
        "generated_at": now_iso(),
    }


def get_linkage_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API helper: linkage charts
    """

    linkage_summary = safe_call_service(get_linkage_summary, fallback={})
    key_connectors = extract_records(safe_call_service(get_key_connectors, fallback={}, context={"page": 1, "page_size": 15}))
    exposure = extract_records(safe_call_service(get_exposure_by_director, fallback={}, context={"page": 1, "page_size": 15}))

    charts = {
        "linkage_summary": build_chart_payload(
            chart_id="linkage_summary",
            chart_type="bar",
            title="Linkage Summary",
            labels=["Companies", "Directors", "Key Connectors", "Shared Links"],
            datasets=[
                {
                    "label": "Count",
                    "data": [
                        linkage_summary.get("total_input_companies", 0),
                        linkage_summary.get("total_directors", 0),
                        linkage_summary.get("total_key_connectors", 0),
                        linkage_summary.get("total_shared_director_links", 0),
                    ],
                }
            ],
        ),
        "key_connectors": build_chart_payload(
            chart_id="key_connectors_top",
            chart_type="bar",
            title="Top Key Connectors",
            labels=[record.get("director_name") for record in key_connectors],
            datasets=[
                {
                    "label": "Company Count",
                    "data": [record.get("company_count", 0) for record in key_connectors],
                }
            ],
        ),
        "director_exposure": build_chart_payload(
            chart_id="director_exposure",
            chart_type="bar",
            title="Exposure by Director",
            labels=[record.get("director_name") for record in exposure],
            datasets=[
                {
                    "label": "Connected Sum Insured",
                    "data": [record.get("total_connected_suminsure", 0) for record in exposure],
                }
            ],
        ),
    }

    return {
        "charts": charts,
        "generated_at": now_iso(),
    }


def get_flood_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API helper: flood charts
    """

    flood_summary = safe_call_service(get_flood_summary, fallback={})
    province_exposure = extract_records(safe_call_service(get_province_risk_exposure, fallback={}, context={"page": 1, "page_size": 15}))

    charts = {
        "risk_counts": make_counter_chart(
            chart_id="flood_risk_counts",
            title="Flood Risk Counts",
            counter=flood_summary.get("risk_counts", {}),
            chart_type="doughnut",
            dataset_label="Sources",
        ),
        "source_counts": make_counter_chart(
            chart_id="flood_source_counts",
            title="Flood Source Counts",
            counter=flood_summary.get("source_counts", {}),
            chart_type="bar",
            dataset_label="Sources",
        ),
        "province_exposure": build_chart_payload(
            chart_id="province_risk_exposure",
            chart_type="bar",
            title="Province Risk Exposure",
            labels=[record.get("province") for record in province_exposure],
            datasets=[
                {
                    "label": "Total Sum Insured",
                    "data": [record.get("total_suminsure", 0) for record in province_exposure],
                },
                {
                    "label": "Company Count",
                    "data": [record.get("company_count", 0) for record in province_exposure],
                },
            ],
        ),
    }

    return {
        "charts": charts,
        "generated_at": now_iso(),
    }


# ============================================================
# 8) PACKAGE PREVIEW
# ============================================================

def normalize_package_request(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    normalize package request
    """

    payload = payload or {}

    package_name = clean_text(payload.get("package_name") or payload.get("name"))

    if not package_name:
        package_name = f"TIPX Package {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    expire_days = to_int(payload.get("expire_days"), PACKAGE_DEFAULT_EXPIRE_DAYS) or PACKAGE_DEFAULT_EXPIRE_DAYS
    expire_days = max(1, min(expire_days, PACKAGE_MAX_EXPIRE_DAYS))

    components = sanitize_package_components(payload.get("components") or DEFAULT_PACKAGE_COMPONENTS)

    security = normalize_security_options(payload.get("security") if isinstance(payload.get("security"), dict) else {})

    return {
        "package_name": package_name,
        "description": clean_text(payload.get("description", "")),
        "filters": payload.get("filters", {}) if isinstance(payload.get("filters", {}), dict) else {},
        "components": components,
        "security": security,
        "expire_days": expire_days,
        "created_by": clean_text(payload.get("created_by"), default="system"),
        "allow_public_access": bool(to_bool(payload.get("allow_public_access", True), default=True)),
        "base_url": clean_text(payload.get("base_url", "")),
        "force_refresh": bool(to_bool(payload.get("force_refresh", False), default=False)),
    }


def preview_package(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    POST /api/packages/preview
    """

    request = normalize_package_request(payload)

    filter_context = {}

    if build_filter_context_for_package is not None:
        filter_context = safe_call_service(
            build_filter_context_for_package,
            fallback={},
            payload=request.get("filters", {}),
        )
    elif preview_filter is not None:
        filter_context = safe_call_service(
            preview_filter,
            fallback={},
            payload=request.get("filters", {}),
        )

    company_records = extract_records(safe_call_service(get_company_list, fallback={}, context={"page": 1, "page_size": 1}))
    policy_records = extract_records(safe_call_service(get_policy_companies, fallback={}, context={"page": 1, "page_size": 1}))
    key_connectors = extract_records(safe_call_service(get_key_connectors, fallback={}, context={"page": 1, "page_size": 1}))
    flood_risk = extract_records(safe_call_service(get_flood_computed_risk, fallback={}, context={"page": 1, "page_size": 1}))

    record_counts = {
        "companies": safe_call_service(get_company_summary, fallback={}).get("total_companies", len(company_records)),
        "policy_companies": safe_call_service(get_policy_companies, fallback={}, context={"page": 1, "page_size": 1}).get("total", len(policy_records)),
        "key_connectors": safe_call_service(get_key_connectors, fallback={}, context={"page": 1, "page_size": 1}).get("total", len(key_connectors)),
        "flood_sources": safe_call_service(get_flood_computed_risk, fallback={}, context={"page": 1, "page_size": 1}).get("total", len(flood_risk)),
    }

    estimated_files = [
        "package_meta.json",
        "package_snapshot.json",
        "public_data.json",
        "summary.json",
        "map.json",
        "charts.json",
        "tables.json",
        "exports/*.xlsx",
        "external_viewer/index.html",
    ]

    warnings: List[str] = []

    if not request.get("components"):
        warnings.append("no_components_selected")

    if request["security"].get("hide_financial_fields"):
        warnings.append("financial_fields_will_be_hidden")

    if request["security"].get("mask_tax_id"):
        warnings.append("tax_id_will_be_masked")

    return {
        "request": request,
        "filter_context": filter_context,
        "estimated_record_counts": record_counts,
        "estimated_files": estimated_files,
        "components": request["components"],
        "security": request["security"],
        "warnings": warnings,
        "previewed_at": now_iso(),
    }


# ============================================================
# 9) PACKAGE SNAPSHOT BUILDER
# ============================================================

def build_package_tables(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง table payload สำหรับ package
    """

    ctx = normalize_context(context)

    companies_payload = safe_call_service(get_company_list, fallback={}, context={**ctx, "page_size": 10000})
    policy_payload = safe_call_service(get_policy_companies, fallback={}, context={**ctx, "page_size": 10000})
    key_connectors_payload = safe_call_service(get_key_connectors, fallback={}, context={**ctx, "page_size": 10000})
    shared_links_payload = safe_call_service(get_shared_director_links, fallback={}, context={**ctx, "page_size": 10000})
    province_risk_payload = safe_call_service(get_province_risk_exposure, fallback={}, context={**ctx, "page_size": 10000})
    dq_payload = safe_call_service(get_data_quality_summary, fallback={}, context={**ctx, "page_size": 10000})

    companies = extract_records(companies_payload)
    policy_companies = extract_records(policy_payload)
    key_connectors = extract_records(key_connectors_payload)
    shared_links = extract_records(shared_links_payload)
    province_risk = extract_records(province_risk_payload)
    dq_issues = dq_payload.get("issues", []) if isinstance(dq_payload, dict) else []

    return {
        "companies": make_table_payload(
            table_id="companies",
            title="Company Unified Master",
            records=companies,
            limit=10000,
        ),
        "policy_companies": make_table_payload(
            table_id="policy_companies",
            title="Policy Company Summary",
            records=policy_companies,
            limit=10000,
        ),
        "key_connectors": make_table_payload(
            table_id="key_connectors",
            title="Key Connectors",
            records=key_connectors,
            limit=10000,
        ),
        "shared_director_links": make_table_payload(
            table_id="shared_director_links",
            title="Shared Director Links",
            records=shared_links,
            limit=10000,
        ),
        "province_risk_exposure": make_table_payload(
            table_id="province_risk_exposure",
            title="Province Risk Exposure",
            records=province_risk,
            limit=10000,
        ),
        "data_quality_issues": make_table_payload(
            table_id="data_quality_issues",
            title="Data Quality Issues",
            records=dq_issues,
            limit=10000,
        ),
    }


def build_package_snapshot(
    package_meta: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง package snapshot เต็ม
    """

    ctx = normalize_context(context)

    summary = get_dashboard_summary(ctx)
    executive = get_executive_dashboard(ctx)
    overview = get_dashboard_overview(ctx)

    charts = {
        "summary": get_chart_summary(ctx).get("charts", {}),
        "policy": get_policy_charts(ctx).get("charts", {}),
        "linkage": get_linkage_charts(ctx).get("charts", {}),
        "flood": get_flood_charts(ctx).get("charts", {}),
    }

    tables = build_package_tables(ctx)

    map_payload = safe_call_service(get_external_viewer_map_payload, fallback={}, context=ctx)
    graph_payload = safe_call_service(get_linkage_graph, fallback={}, context={"max_nodes": 500})

    data_quality_payload = safe_call_service(build_data_quality_dashboard_payload, fallback={}, context=ctx)

    filter_options = {}
    if get_filter_options_from_records is not None:
        company_records = tables.get("companies", {}).get("records", [])
        filter_options = safe_call_service(
            get_filter_options_from_records,
            fallback={},
            records=company_records,
            fields=[
                "province",
                "flood_risk_level",
                "loss_ratio_band",
                "company_size",
                "business_type_tsic",
                "wtip",
                "has_policy",
                "has_linkage",
                "has_location",
            ],
        )

    snapshot = {
        "package_meta": package_meta,
        "data": {
            "summary": summary,
            "executive": executive,
            "overview": overview,
            "charts": charts,
            "tables": tables,
            "map_layers": map_payload,
            "linkage_graph": graph_payload,
            "data_quality": data_quality_payload,
            "filter_options": filter_options,
        },
        "created_at": now_iso(),
    }

    snapshot = attach_package_checksum(snapshot)

    return snapshot


def build_public_data_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    สร้าง public_data.json จาก snapshot
    """

    package_meta = snapshot.get("package_meta", {})
    security_options = package_meta.get("security", PACKAGE_SECURITY_OPTIONS)

    public_result = build_public_package_snapshot(
        package_snapshot=snapshot,
        token=package_meta.get("access_token", ""),
    )

    if public_result.get("allowed"):
        public_data = public_result.get("data", {})
    else:
        public_data = sanitize_public_payload(snapshot, security_options=security_options)

    if isinstance(public_data, dict):
        public_data.setdefault("viewer", {})
        public_data["viewer"].update(
            {
                "title": package_meta.get("package_name", "TIPX External Viewer"),
                "generated_at": now_iso(),
                "read_only": True,
                "app": APP_SHORT_NAME,
                "version": APP_VERSION,
            }
        )

    return public_data


# ============================================================
# 10) EXTERNAL VIEWER HTML
# ============================================================

def build_external_viewer_html(package_meta: Dict[str, Any]) -> str:
    """
    สร้าง external viewer index.html แบบ standalone เบื้องต้น

    ใช้ข้อมูลจาก external_viewer/data/public_data.json
    """

    title = clean_text(package_meta.get("package_name"), default="TIPX External Viewer")

    return f"""<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>

  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ol@v10.3.1/ol.css" />
  <script src="https://cdn.jsdelivr.net/npm/ol@v10.3.1/dist/ol.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>

  <style>
    :root {{
      --bg: #0f172a;
      --panel: #111827;
      --panel2: #1f2937;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --border: #334155;
      --accent: #38bdf8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      background: #020617;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }}
    header h1 {{
      margin: 0;
      font-size: 20px;
    }}
    header small {{
      color: var(--muted);
    }}
    .grid {{
      display: grid;
      grid-template-columns: 360px 1fr;
      min-height: calc(100vh - 70px);
    }}
    aside {{
      border-right: 1px solid var(--border);
      padding: 16px;
      overflow: auto;
      background: var(--panel);
    }}
    main {{
      padding: 16px;
      overflow: auto;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .card {{
      background: var(--panel2);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
    }}
    .card .label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }}
    .card .value {{
      font-size: 22px;
      font-weight: bold;
    }}
    #map {{
      height: 520px;
      border-radius: 14px;
      border: 1px solid var(--border);
      overflow: hidden;
      background: #111827;
      margin-bottom: 16px;
    }}
    .section {{
      margin-bottom: 16px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
    }}
    .section h2 {{
      margin: 0 0 12px;
      font-size: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
    }}
    .pill {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      background: #334155;
      font-size: 11px;
    }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>{title}</h1>
      <small>Generated by TIPX External Viewer · Read-only Package</small>
    </div>
    <small id="generatedAt"></small>
  </header>

  <div class="grid">
    <aside>
      <div class="section">
        <h2>Package</h2>
        <div id="packageMeta" class="muted">Loading...</div>
      </div>

      <div class="section">
        <h2>Insights</h2>
        <div id="insights"></div>
      </div>
    </aside>

    <main>
      <div class="cards" id="summaryCards"></div>

      <div id="map"></div>

      <div class="section">
        <h2>Top Companies</h2>
        <div id="companyTable"></div>
      </div>

      <div class="section">
        <h2>Charts</h2>
        <canvas id="riskChart" height="110"></canvas>
      </div>
    </main>
  </div>

  <script>
    const riskColors = {{
      Normal: "#22c55e",
      Watch: "#facc15",
      Warning: "#f97316",
      Critical: "#dc2626",
      Unknown: "#64748b"
    }};

    function esc(v) {{
      return String(v ?? "").replace(/[&<>"']/g, s => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\\"": "&quot;",
        "'": "&#039;"
      }}[s]));
    }}

    function getNested(obj, path, fallback) {{
      return path.split(".").reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), obj) ?? fallback;
    }}

    async function loadData() {{
      const res = await fetch("./data/public_data.json");
      return await res.json();
    }}

    function renderMeta(data) {{
      const meta = data.package_meta || {{}};
      document.getElementById("generatedAt").textContent = meta.created_at || "";
      document.getElementById("packageMeta").innerHTML = `
        <div><b>${{esc(meta.package_name || "TIPX Package")}}</b></div>
        <div>${{esc(meta.description || "")}}</div>
        <div class="muted">Package ID: ${{esc(meta.package_id || "")}}</div>
        <div class="muted">Expire: ${{esc(meta.expire_at || "")}}</div>
      `;
    }}

    function renderCards(data) {{
      const cards = getNested(data, "data.summary.summary_cards", []);
      document.getElementById("summaryCards").innerHTML = cards.map(card => `
        <div class="card">
          <div class="label">${{esc(card.label)}}</div>
          <div class="value">${{esc(card.display_value ?? card.value)}}</div>
          <div><span class="pill">${{esc(card.status || "")}}</span></div>
        </div>
      `).join("");
    }}

    function renderInsights(data) {{
      const insights = getNested(data, "data.executive.executive_insights", []);
      document.getElementById("insights").innerHTML = insights.map(item => `
        <div class="card" style="margin-bottom:10px">
          <div><b>${{esc(item.title)}}</b></div>
          <div class="muted">${{esc(item.message)}}</div>
          <div><span class="pill">${{esc(item.severity)}}</span></div>
        </div>
      `).join("");
    }}

    function renderCompanyTable(data) {{
      const records = getNested(data, "data.tables.companies.records", []).slice(0, 20);
      const html = `
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Province</th>
              <th>Risk</th>
              <th>Sum Insured</th>
            </tr>
          </thead>
          <tbody>
            ${{records.map(r => `
              <tr>
                <td>${{esc(r.company_name)}}</td>
                <td>${{esc(r.province)}}</td>
                <td>${{esc(r.flood_risk_level)}}</td>
                <td>${{esc(r.total_suminsure)}}</td>
              </tr>
            `).join("")}}
          </tbody>
        </table>
      `;
      document.getElementById("companyTable").innerHTML = html;
    }}

    function renderRiskChart(data) {{
      const counts = getNested(data, "data.summary.company_summary.flood_risk_counts", {{}});
      const labels = Object.keys(counts);
      const values = labels.map(k => counts[k]);
      new Chart(document.getElementById("riskChart"), {{
        type: "doughnut",
        data: {{
          labels,
          datasets: [{{
            data: values,
            backgroundColor: labels.map(k => riskColors[k] || riskColors.Unknown)
          }}]
        }},
        options: {{
          plugins: {{
            legend: {{ labels: {{ color: "#e5e7eb" }} }}
          }}
        }}
      }});
    }}

    function renderMap(data) {{
      const mapCfg = getNested(data, "data.map_layers.map", {{}});
      const layerData = getNested(data, "data.map_layers.layers.company_points.feature_collection", {{
        type: "FeatureCollection",
        features: []
      }});

      const features = new ol.format.GeoJSON().readFeatures(layerData, {{
        featureProjection: "EPSG:3857"
      }});

      const vector = new ol.source.Vector({{ features }});

      const layer = new ol.layer.Vector({{
        source: vector,
        style: function(feature) {{
          const p = feature.getProperties();
          const color = p.marker_color || riskColors[p.flood_risk_level] || riskColors.Unknown;
          const size = p.marker_size || 8;
          return new ol.style.Style({{
            image: new ol.style.Circle({{
              radius: Math.max(4, Math.min(18, size / 2)),
              fill: new ol.style.Fill({{ color }}),
              stroke: new ol.style.Stroke({{ color: "#fff", width: 1 }})
            }})
          }});
        }}
      }});

      const center = mapCfg.center || [100.5, 13.7];

      const map = new ol.Map({{
        target: "map",
        layers: [
          new ol.layer.Tile({{ source: new ol.source.OSM() }}),
          layer
        ],
        view: new ol.View({{
          center: ol.proj.fromLonLat(center),
          zoom: mapCfg.zoom || 6
        }})
      }});

      if (features.length) {{
        map.getView().fit(vector.getExtent(), {{ padding: [40, 40, 40, 40], maxZoom: 11 }});
      }}
    }}

    loadData().then(data => {{
      renderMeta(data);
      renderCards(data);
      renderInsights(data);
      renderCompanyTable(data);
      renderRiskChart(data);
      renderMap(data);
    }}).catch(err => {{
      document.body.innerHTML = "<pre style='padding:20px;color:white'>Failed to load package data: " + err + "</pre>";
    }});
  </script>
</body>
</html>
"""


# ============================================================
# 11) PACKAGE FILE WRITERS
# ============================================================

def write_package_exports(
    package_id: str,
    snapshot: Dict[str, Any],
    security_options: Dict[str, Any],
) -> Dict[str, Any]:
    """
    เขียน Excel exports ใน package
    """

    exports_dir = ensure_dir(get_package_exports_folder(package_id))

    tables = snapshot.get("data", {}).get("tables", {})

    written_files: List[str] = []

    for table_key, table_payload in tables.items():
        records = table_payload.get("records", [])

        if not isinstance(records, list):
            records = []

        records = apply_export_field_policy_to_records(
            records,
            security_options=security_options,
        )

        df = pd.DataFrame(records)

        export_path = exports_dir / f"{safe_filename(table_key)}.xlsx"

        write_excel(
            export_path,
            {
                table_key[:31]: df,
            },
        )

        written_files.append(str(export_path))

    return {
        "export_dir": str(exports_dir),
        "files": written_files,
        "count": len(written_files),
    }


def write_external_viewer_files(
    package_id: str,
    package_meta: Dict[str, Any],
    public_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    เขียน external viewer folder
    """

    viewer_dir = ensure_dir(get_package_external_viewer_folder(package_id))
    data_dir = ensure_dir(viewer_dir / "data")
    assets_dir = ensure_dir(viewer_dir / "assets")

    index_path = viewer_dir / "index.html"
    data_path = data_dir / "public_data.json"

    write_text(index_path, build_external_viewer_html(package_meta))
    write_json(data_path, public_data)

    return {
        "viewer_dir": str(viewer_dir),
        "index_path": str(index_path),
        "data_path": str(data_path),
        "assets_dir": str(assets_dir),
    }


def write_package_files(
    package_id: str,
    snapshot: Dict[str, Any],
    public_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    เขียน package files ทั้งหมด
    """

    package_dir = ensure_dir(get_package_folder(package_id))
    package_meta = snapshot.get("package_meta", {})
    security_options = package_meta.get("security", PACKAGE_SECURITY_OPTIONS)

    meta_path = package_dir / PACKAGE_META_FILENAME
    snapshot_path = package_dir / PACKAGE_SNAPSHOT_FILENAME
    public_data_path = package_dir / PACKAGE_PUBLIC_DATA_FILENAME
    summary_path = package_dir / "summary.json"
    map_path = package_dir / "map.json"
    charts_path = package_dir / "charts.json"
    tables_path = package_dir / "tables.json"
    access_log_path = package_dir / "access_log.jsonl"

    write_json(meta_path, package_meta)
    write_json(snapshot_path, snapshot)
    write_json(public_data_path, public_data)

    write_json(summary_path, public_data.get("data", {}).get("summary", public_data.get("summary", {})))
    write_json(map_path, public_data.get("data", {}).get("map_layers", public_data.get("map_layers", {})))
    write_json(charts_path, public_data.get("data", {}).get("charts", public_data.get("charts", {})))
    write_json(tables_path, public_data.get("data", {}).get("tables", public_data.get("tables", {})))

    if not access_log_path.exists():
        write_text(access_log_path, "")

    exports = write_package_exports(
        package_id=package_id,
        snapshot=snapshot,
        security_options=security_options,
    )

    viewer = write_external_viewer_files(
        package_id=package_id,
        package_meta=package_meta,
        public_data=public_data,
    )

    zip_path = create_zip_from_folder(
        folder=package_dir,
        zip_path=get_package_zip_path(package_id),
        include_root_folder=True,
    )

    files = [
        str(meta_path),
        str(snapshot_path),
        str(public_data_path),
        str(summary_path),
        str(map_path),
        str(charts_path),
        str(tables_path),
        str(access_log_path),
        *exports.get("files", []),
        viewer.get("index_path"),
        viewer.get("data_path"),
        str(zip_path),
    ]

    return {
        "package_dir": str(package_dir),
        "zip_path": str(zip_path),
        "files": [file for file in files if file],
        "exports": exports,
        "viewer": viewer,
    }


# ============================================================
# 12) PACKAGE INDEX
# ============================================================

def get_package_index_path() -> Path:
    """
    คืน package index path
    """

    return PACKAGE_DIR / PACKAGE_INDEX_FILENAME


def load_package_index() -> Dict[str, Any]:
    """
    โหลด package index
    """

    ensure_package_root()

    data = read_json(get_package_index_path(), default={})

    if not isinstance(data, dict):
        data = {}

    data.setdefault("packages", [])
    data.setdefault("updated_at", now_iso())

    return data


def write_package_index(index: Dict[str, Any]) -> Path:
    """
    เขียน package index
    """

    ensure_package_root()

    index["updated_at"] = now_iso()
    index["total"] = len(index.get("packages", []))

    return write_json(get_package_index_path(), index)


def upsert_package_index(package_meta: Dict[str, Any], files: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    เพิ่มหรือ update package ใน package index
    """

    index = load_package_index()
    package_id = package_meta.get("package_id")

    packages = [
        item
        for item in index.get("packages", [])
        if item.get("package_id") != package_id
    ]

    item = {
        "package_id": package_id,
        "package_name": package_meta.get("package_name"),
        "description": package_meta.get("description"),
        "created_at": package_meta.get("created_at"),
        "created_by": package_meta.get("created_by"),
        "expire_at": package_meta.get("expire_at"),
        "status": package_meta.get("status", "active"),
        "allow_public_access": package_meta.get("allow_public_access", True),
        "public_url": package_meta.get("public_url"),
        "components": package_meta.get("components", []),
        "security": package_meta.get("security", {}),
        "record_counts": package_meta.get("record_counts", {}),
        "checksum": package_meta.get("checksum", ""),
        "files": files or package_meta.get("files", []),
        "package_dir": str(get_package_folder(package_id)),
        "zip_path": str(get_package_zip_path(package_id)),
        "updated_at": now_iso(),
    }

    packages.append(item)

    packages = sorted(
        packages,
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )

    index["packages"] = packages
    write_package_index(index)

    return item


def get_package_meta_from_disk(package_id: str) -> Dict[str, Any]:
    """
    โหลด package_meta จาก disk
    """

    path = get_package_file(package_id, PACKAGE_META_FILENAME)
    data = read_json(path, default={})

    if isinstance(data, dict):
        return data

    return {}


def get_package_snapshot_from_disk(package_id: str) -> Dict[str, Any]:
    """
    โหลด package_snapshot จาก disk
    """

    path = get_package_file(package_id, PACKAGE_SNAPSHOT_FILENAME)
    data = read_json(path, default={})

    if isinstance(data, dict):
        return data

    return {}


def get_public_data_from_disk(package_id: str) -> Dict[str, Any]:
    """
    โหลด public_data จาก disk
    """

    path = get_package_file(package_id, PACKAGE_PUBLIC_DATA_FILENAME)
    data = read_json(path, default={})

    if isinstance(data, dict):
        return data

    return {}


# ============================================================
# 13) PACKAGE GENERATE / LIST / DETAIL
# ============================================================

def generate_package(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    POST /api/packages/generate
    """

    ensure_package_root()

    request = normalize_package_request(payload)

    if request.get("force_refresh"):
        rebuild_all_runtime_cache()

    package_id = generate_package_id()

    package_meta = build_package_meta(
        package_id=package_id,
        package_name=request["package_name"],
        description=request["description"],
        filters=request["filters"],
        components=request["components"],
        security_options=request["security"],
        expire_days=request["expire_days"],
        created_by=request["created_by"],
        allow_public_access=request["allow_public_access"],
        base_url=request["base_url"],
    )

    context = {
        "filters": request["filters"],
        "force_refresh": False,
        "page": 1,
        "page_size": 10000,
    }

    snapshot = build_package_snapshot(
        package_meta=package_meta,
        context=context,
    )

    package_meta = snapshot.get("package_meta", package_meta)

    record_counts = collect_record_counts_from_snapshot(snapshot)
    package_meta["record_counts"] = record_counts
    snapshot["package_meta"]["record_counts"] = record_counts

    public_data = build_public_data_from_snapshot(snapshot)

    write_result = write_package_files(
        package_id=package_id,
        snapshot=snapshot,
        public_data=public_data,
    )

    package_meta["files"] = write_result.get("files", [])
    package_meta["zip_path"] = write_result.get("zip_path")
    package_meta["package_dir"] = write_result.get("package_dir")

    write_json(
        get_package_file(package_id, PACKAGE_META_FILENAME),
        package_meta,
    )

    snapshot["package_meta"] = package_meta

    write_json(
        get_package_file(package_id, PACKAGE_SNAPSHOT_FILENAME),
        snapshot,
    )

    index_item = upsert_package_index(
        package_meta=package_meta,
        files=write_result.get("files", []),
    )

    return {
        "generated": True,
        "package_id": package_id,
        "package_meta": package_meta,
        "index_item": index_item,
        "files": write_result,
        "public_data_preview": {
            "keys": list(public_data.keys()),
            "viewer": public_data.get("viewer", {}),
        },
        "generated_at": now_iso(),
    }


def collect_record_counts_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    สรุปจำนวน records ใน snapshot
    """

    tables = snapshot.get("data", {}).get("tables", {})

    counts = {}

    for table_key, table_payload in tables.items():
        counts[table_key] = len(table_payload.get("records", []))

    map_layers = snapshot.get("data", {}).get("map_layers", {}).get("layers", {})

    for layer_key, layer_payload in map_layers.items():
        counts[f"map_{layer_key}"] = layer_payload.get("record_count", 0)

    graph = snapshot.get("data", {}).get("linkage_graph", {})

    counts["graph_nodes"] = len(graph.get("nodes", []))
    counts["graph_edges"] = len(graph.get("edges", []))

    return counts


def list_packages(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/packages
    """

    ctx = normalize_context(context)
    index = load_package_index()

    records = index.get("packages", [])

    result = apply_search_sort_pagination(
        records=records,
        context=ctx,
        searchable_fields=[
            "package_id",
            "package_name",
            "description",
            "created_by",
            "status",
        ],
    )

    return {
        **result,
        "index_path": str(get_package_index_path()),
        "updated_at": index.get("updated_at"),
    }


def get_package_detail(package_id: str) -> Dict[str, Any]:
    """
    API:
    GET /api/packages/<package_id>
    """

    package_id = clean_text(package_id)
    meta = get_package_meta_from_disk(package_id)
    snapshot = get_package_snapshot_from_disk(package_id)

    package_dir = get_package_folder(package_id)
    zip_path = get_package_zip_path(package_id)

    checksum_result = verify_package_checksum(snapshot) if snapshot else {
        "valid": False,
        "reason": "snapshot_missing",
    }

    return {
        "package_id": package_id,
        "found": bool(meta),
        "package_meta": meta,
        "checksum": checksum_result,
        "paths": {
            "package_dir": file_info(package_dir),
            "zip": file_info(zip_path),
            "meta": file_info(get_package_file(package_id, PACKAGE_META_FILENAME)),
            "snapshot": file_info(get_package_file(package_id, PACKAGE_SNAPSHOT_FILENAME)),
            "public_data": file_info(get_package_file(package_id, PACKAGE_PUBLIC_DATA_FILENAME)),
        },
    }


def get_package_download_info(package_id: str) -> Dict[str, Any]:
    """
    API:
    GET /api/packages/<package_id>/download

    หมายเหตุ:
    api_routes.py สามารถนำ zip_path ไปส่งด้วย send_file ได้ในอนาคต
    """

    package_id = clean_text(package_id)
    zip_path = get_package_zip_path(package_id)

    if not zip_path.exists():
        package_dir = get_package_folder(package_id)

        if package_dir.exists():
            create_zip_from_folder(
                folder=package_dir,
                zip_path=zip_path,
                include_root_folder=True,
            )

    return {
        "package_id": package_id,
        "exists": zip_path.exists(),
        "zip_path": str(zip_path),
        "file_info": file_info(zip_path),
    }


def disable_package(package_id: str) -> Dict[str, Any]:
    """
    API:
    POST /api/packages/<package_id>/disable
    """

    package_id = clean_text(package_id)
    meta = get_package_meta_from_disk(package_id)

    if not meta:
        return {
            "disabled": False,
            "package_id": package_id,
            "message": "package not found",
        }

    meta["status"] = "disabled"
    meta["updated_at"] = now_iso()

    write_json(get_package_file(package_id, PACKAGE_META_FILENAME), meta)
    upsert_package_index(meta, files=meta.get("files", []))

    snapshot = get_package_snapshot_from_disk(package_id)

    if snapshot:
        snapshot.setdefault("package_meta", {})
        snapshot["package_meta"].update(meta)
        write_json(get_package_file(package_id, PACKAGE_SNAPSHOT_FILENAME), snapshot)

    return {
        "disabled": True,
        "package_id": package_id,
        "package_meta": meta,
    }


def delete_package(package_id: str) -> Dict[str, Any]:
    """
    API:
    DELETE /api/packages/<package_id>

    ลบ package folder และ zip
    แต่ยัง update index เป็น deleted
    """

    package_id = clean_text(package_id)
    meta = get_package_meta_from_disk(package_id)

    package_dir = get_package_folder(package_id)
    zip_path = get_package_zip_path(package_id)

    removed_paths: List[str] = []

    if package_dir.exists() and package_dir.is_dir():
        shutil.rmtree(package_dir)
        removed_paths.append(str(package_dir))

    if zip_path.exists() and zip_path.is_file():
        zip_path.unlink()
        removed_paths.append(str(zip_path))

    if meta:
        meta["status"] = "deleted"
        meta["updated_at"] = now_iso()
        upsert_package_index(meta, files=[])

    return {
        "deleted": True,
        "package_id": package_id,
        "removed_paths": removed_paths,
    }


# ============================================================
# 14) PUBLIC PACKAGE API
# ============================================================

def log_public_access(
    package_id: str,
    action: str,
    allowed: bool,
    reason: str,
    remote_addr: str = "",
    user_agent: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    เขียน access log สำหรับ public package
    """

    record = build_access_log_record(
        package_id=package_id,
        remote_addr=remote_addr,
        user_agent=user_agent,
        action=action,
        allowed=allowed,
        reason=reason,
        extra=extra,
    )

    log_path = get_package_file(package_id, "access_log.jsonl")
    ensure_parent_dir(log_path)

    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(to_jsonable(record), ensure_ascii=False) + "\n")

    return record


def get_public_package_meta(
    package_id: str,
    token: str = "",
    request_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/public/packages/<package_id>/meta
    """

    package_id = clean_text(package_id)
    meta = get_package_meta_from_disk(package_id)

    if not meta:
        log_public_access(package_id, "meta", False, "package_not_found", extra=request_meta)
        return build_public_error("package_not_found", package_id)

    access = check_public_package_access(meta, token=token)

    log_public_access(
        package_id,
        "meta",
        bool(access.get("allowed")),
        access.get("reason", "unknown"),
        extra=request_meta,
    )

    if not access.get("allowed"):
        return build_public_error(access.get("reason", "access_denied"), package_id)

    return build_public_success(
        data=build_safe_public_meta(meta),
        package_id=package_id,
        component="meta",
    )


def get_public_package_data(
    package_id: str,
    token: str = "",
    request_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/public/packages/<package_id>/data
    """

    package_id = clean_text(package_id)
    snapshot = get_package_snapshot_from_disk(package_id)
    meta = get_package_meta_from_disk(package_id)

    if not snapshot or not meta:
        log_public_access(package_id, "data", False, "package_not_found", extra=request_meta)
        return build_public_error("package_not_found", package_id)

    public_result = build_public_package_snapshot(snapshot, token=token)

    log_public_access(
        package_id,
        "data",
        bool(public_result.get("allowed")),
        public_result.get("reason", "unknown"),
        extra=request_meta,
    )

    if not public_result.get("allowed"):
        return build_public_error(public_result.get("reason", "access_denied"), package_id)

    return build_public_success(
        data=public_result.get("data", {}),
        package_id=package_id,
        component="data",
    )


def get_public_package_component(
    package_id: str,
    component: str,
    token: str = "",
    request_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    ดึง component เฉพาะจาก public package
    """

    package_id = clean_text(package_id)
    component = clean_text(component)

    snapshot = get_package_snapshot_from_disk(package_id)

    if not snapshot:
        log_public_access(package_id, component, False, "package_not_found", extra=request_meta)
        return build_public_error("package_not_found", package_id)

    component_result = extract_public_package_component(
        package_snapshot=snapshot,
        component=component,
        token=token,
    )

    log_public_access(
        package_id,
        component,
        bool(component_result.get("allowed")),
        component_result.get("reason", "unknown"),
        extra=request_meta,
    )

    if not component_result.get("allowed"):
        return build_public_error(component_result.get("reason", "access_denied"), package_id)

    return build_public_success(
        data=component_result.get("data", {}),
        package_id=package_id,
        component=component,
    )


def get_public_package_summary(package_id: str, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/public/packages/<package_id>/summary
    """

    return get_public_package_component(package_id, "summary", token=token, request_meta=request_meta)


def get_public_package_map(package_id: str, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/public/packages/<package_id>/map
    """

    return get_public_package_component(package_id, "map", token=token, request_meta=request_meta)


def get_public_package_charts(package_id: str, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/public/packages/<package_id>/charts
    """

    return get_public_package_component(package_id, "charts", token=token, request_meta=request_meta)


def get_public_package_tables(package_id: str, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/public/packages/<package_id>/tables
    """

    return get_public_package_component(package_id, "tables", token=token, request_meta=request_meta)


def get_public_package_access_log(package_id: str, token: str = "") -> Dict[str, Any]:
    """
    API:
    GET /api/public/packages/<package_id>/access-log

    ใช้สำหรับ owner/internal ตรวจ access log
    """

    package_id = clean_text(package_id)
    meta = get_package_meta_from_disk(package_id)

    if not meta:
        return build_public_error("package_not_found", package_id)

    access = check_public_package_access(meta, token=token)

    if not access.get("allowed"):
        return build_public_error(access.get("reason", "access_denied"), package_id)

    log_path = get_package_file(package_id, "access_log.jsonl")

    logs: List[Dict[str, Any]] = []

    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                logs.append(json.loads(line))
            except Exception:
                continue

    return build_public_success(
        data={
            "logs": logs[-500:],
            "total": len(logs),
        },
        package_id=package_id,
        component="access_log",
    )


# ============================================================
# 15) RUNTIME CACHE REBUILD
# ============================================================

def rebuild_all_runtime_cache(force_refresh: bool = True) -> Dict[str, Any]:
    """
    rebuild cache ของทุก service หลัก
    """

    results = {}

    results["company_policy"] = safe_call_service(
        rebuild_company_policy_cache,
        fallback={},
        force_refresh=force_refresh,
    )

    results["linkage"] = safe_call_service(
        rebuild_linkage_cache,
        fallback={},
        force_refresh=force_refresh,
    )

    results["flood_spatial"] = safe_call_service(
        rebuild_flood_spatial_cache,
        fallback={},
        force_refresh=force_refresh,
    )

    results["map"] = safe_call_service(
        rebuild_map_cache,
        fallback={},
        force_refresh=force_refresh,
    )

    results["dashboard_summary"] = build_dashboard_summary(force_refresh=True)

    return {
        "rebuilt": True,
        "results": results,
        "generated_at": now_iso(),
    }


# ============================================================
# 16) API COMPATIBILITY ALIASES
# ============================================================

def get_dashboard_freshness(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    alias สำหรับ api_routes.py
    """

    return get_data_freshness(context)


def get_dashboard_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    alias สำหรับ chart summary
    """

    return get_chart_summary(context)


def get_package_preview(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    alias
    """

    return preview_package(payload)


def get_package_list(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    alias
    """

    return list_packages(context)


def download_package(package_id: str) -> Dict[str, Any]:
    """
    alias
    """

    return get_package_download_info(package_id)


# ============================================================
# 17) SERVICE CLASS ADAPTER
# ============================================================

class DashboardPackageService:
    """
    Class adapter สำหรับกรณีต้องการเรียกแบบ object
    """

    def get_dashboard_summary(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_dashboard_summary(context)

    def get_dashboard_overview(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_dashboard_overview(context)

    def get_executive_dashboard(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_executive_dashboard(context)

    def get_data_freshness(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_data_freshness(context)

    def get_chart_summary(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_chart_summary(context)

    def preview_package(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return preview_package(payload)

    def generate_package(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return generate_package(payload)

    def list_packages(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return list_packages(context)

    def get_package_detail(self, package_id: str) -> Dict[str, Any]:
        return get_package_detail(package_id)

    def disable_package(self, package_id: str) -> Dict[str, Any]:
        return disable_package(package_id)

    def delete_package(self, package_id: str) -> Dict[str, Any]:
        return delete_package(package_id)


# ============================================================
# 18) MODULE STATUS / SELF TEST
# ============================================================

def get_dashboard_package_module_status() -> Dict[str, Any]:
    """
    คืนสถานะ module dashboard_package_service.py
    """

    index = load_package_index()

    return {
        "module": "dashboard_package_service",
        "ready": True,
        "app": {
            "name": APP_NAME,
            "short_name": APP_SHORT_NAME,
            "version": APP_VERSION,
        },
        "package_dir": str(PACKAGE_DIR),
        "package_dir_exists": PACKAGE_DIR.exists(),
        "package_index_path": str(get_package_index_path()),
        "package_count": len(index.get("packages", [])),
        "supported_dashboard_outputs": [
            "dashboard_summary",
            "dashboard_overview",
            "executive_dashboard",
            "data_freshness",
            "chart_summary",
        ],
        "supported_package_outputs": [
            "package_meta",
            "package_snapshot",
            "public_data",
            "summary",
            "map",
            "charts",
            "tables",
            "external_viewer",
            "excel_exports",
            "zip_package",
        ],
        "components": DEFAULT_PACKAGE_COMPONENTS,
        "security_options": PACKAGE_SECURITY_OPTIONS,
        "checked_at": now_iso(),
    }


def run_dashboard_package_self_test() -> Dict[str, Any]:
    """
    self test เบื้องต้น
    """

    summary = get_dashboard_summary({"force_refresh": False})
    preview = preview_package(
        {
            "package_name": "Self Test Preview",
            "description": "Self test package preview",
            "components": DEFAULT_PACKAGE_COMPONENTS,
            "security": PACKAGE_SECURITY_OPTIONS,
        }
    )

    return {
        "module": "dashboard_package_service",
        "self_test": True,
        "status": get_dashboard_package_module_status(),
        "dashboard_overall_status": summary.get("overall_status"),
        "summary_card_count": len(summary.get("summary_cards", [])),
        "preview_components": preview.get("components", []),
        "checked_at": now_iso(),
    }