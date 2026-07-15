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

import inspect
import json
import os
import shutil
import config
from collections import Counter, defaultdict
from datetime import datetime, timedelta
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
    PACKAGE_ZIP_DIR,
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
    append_jsonl,
    apply_search_sort_pagination,
    clean_text,
    clean_text_lower,
    create_zip_from_folder,
    dataframe_to_records,
    ensure_dir,
    ensure_parent_dir,
    file_info,
    file_write_lock,
    format_number,
    format_percent,
    get_cache_file_path,
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
    build_package_meta as build_security_package_meta,
    build_public_api_urls,
    build_public_error,
    build_public_package_snapshot,
    build_public_success,
    build_safe_public_meta,
    check_public_package_access,
    create_package_checksum,
    build_public_package_url_meta,
    public_access_allowed,
    extract_public_package_component,
    generate_package_id,
    sanitize_package_components,
    sanitize_public_payload,
    verify_package_checksum,
)

PANDAS_LOADED = True
CONFIG_LOADED = True
UTILS_LOADED = True
SECURITY_LOADED = True

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
        rebuild_company_policy_base_cache as rebuild_company_policy_base_service,
        rebuild_company_policy_enriched_cache as rebuild_company_policy_enriched_service,
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
    rebuild_company_policy_base_service = None
    rebuild_company_policy_enriched_service = None
    
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
    from flood_spatial_service import (
        get_latest_rainfall,
        get_latest_waterlevel,
        get_latest_dam,
        get_latest_flood_predictions,
        get_flood_prediction_summary,
        get_flood_prediction_risk_distribution,
        get_flood_prediction_map,
    )
except Exception:
    get_latest_rainfall = None
    get_latest_waterlevel = None
    get_latest_dam = None
    get_latest_flood_predictions = None
    get_flood_prediction_summary = None
    get_flood_prediction_risk_distribution = None
    get_flood_prediction_map = None


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

def normalize_context(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = dict(DEFAULT_CONTEXT)

    if isinstance(context, dict):
        result.update(context)

    result["force_refresh"] = bool(
        to_bool(
            result.get("force_refresh"),
            default=False,
        )
    )
    result["snapshot_only"] = bool(
        to_bool(
            result.get("snapshot_only"),
            default=False,
        )
    )

    try:
        result["page"] = max(
            1,
            int(
                result.get("page", 1)
                or 1
            ),
        )
    except (TypeError, ValueError):
        result["page"] = 1

    try:
        result["page_size"] = max(
            1,
            min(
                5000,
                int(
                    result.get("page_size", 50)
                    or 50
                ),
            ),
        )
    except (TypeError, ValueError):
        result["page_size"] = 50

    result["search"] = clean_text(
        result.get("search", "")
    )
    result["sort_by"] = clean_text(
        result.get("sort_by", "")
    )
    result["sort_dir"] = (
        clean_text_lower(
            result.get("sort_dir", "asc")
        )
        or "asc"
    )

    if result["sort_dir"] not in {
        "asc",
        "desc",
    }:
        result["sort_dir"] = "asc"

    if not isinstance(
        result.get("filters"),
        dict,
    ):
        result["filters"] = {}

    result["include_map"] = bool(
        to_bool(
            result.get("include_map"),
            default=True,
        )
    )
    result["include_graph"] = bool(
        to_bool(
            result.get("include_graph"),
            default=True,
        )
    )
    result["include_data_quality"] = bool(
        to_bool(
            result.get("include_data_quality"),
            default=True,
        )
    )

    return result

def get_dashboard_ttl() -> int:
    """
    TTL สำหรับ dashboard cache
    """

    return int(CACHE_TTL_SECONDS.get("dashboard", 900))


def safe_call_service(
    function_ref: Any,
    fallback: Any = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    if function_ref is None:
        return (
            fallback
            if fallback is not None
            else {}
        )

    try:
        return function_ref(
            *args,
            **kwargs,
        )
    except Exception:
        return (
            fallback
            if fallback is not None
            else {}
        )


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

def normalize_package_request(
    payload: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    request = (
        payload
        if isinstance(payload, dict)
        else {}
    )

    default_components = list(
        dict.fromkeys(
            [
                *PACKAGE_COMPONENTS,
                "prediction",
                "entity",
            ]
        )
    )

    raw_components = (
        request.get("components")
        if isinstance(
            request.get("components"),
            list,
        )
        else default_components
    )

    components = [
        component
        for component
        in sanitize_package_components(
            raw_components
        )
        if component
        in ALLOWED_PUBLIC_COMPONENTS
    ]

    components = list(
        dict.fromkeys(
            components
        )
    )

    if not components:
        components = (
            default_components
        )

    security_policy = dict(
        PACKAGE_SECURITY_OPTIONS
    )

    if isinstance(
        request.get("security"),
        dict,
    ):
        security_policy.update(
            request["security"]
        )

    security_policy["public"] = True
    security_policy[
        "remove_internal_paths"
    ] = True
    security_policy[
        "remove_debug_fields"
    ] = True

    try:
        expires_days = int(
            request.get(
                "expires_days",
                request.get(
                    "expire_days",
                    PACKAGE_DEFAULT_EXPIRE_DAYS,
                ),
            )
            or PACKAGE_DEFAULT_EXPIRE_DAYS
        )
    except (
        TypeError,
        ValueError,
    ):
        expires_days = (
            PACKAGE_DEFAULT_EXPIRE_DAYS
        )

    expires_days = max(
        1,
        min(
            expires_days,
            PACKAGE_MAX_EXPIRE_DAYS,
        ),
    )

    return {
        "package_name": clean_text(
            request.get(
                "package_name"
            )
            or request.get("name"),
            "TIPX Dashboard Package",
        ),
        "description": clean_text(
            request.get(
                "description"
            )
        ),
        "components": components,
        "security": security_policy,
        "scope": build_package_scope(
            request
        ),
        "public": bool(
            to_bool(
                request.get("public"),
                default=True,
            )
        ),
        "expires_days": expires_days,
        "filters": (
            request.get(
                "filters",
                {},
            )
            if isinstance(
                request.get("filters"),
                dict,
            )
            else {}
        ),
        "force_refresh": bool(
            to_bool(
                request.get(
                    "force_refresh"
                ),
                default=False,
            )
        ),
        "snapshot_only": True,
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

def collect_record_counts_from_snapshot(
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    data = (
        snapshot.get("data", {})
        if (
            isinstance(snapshot, dict)
            and isinstance(
                snapshot.get("data"),
                dict,
            )
        )
        else {}
    )

    counts: Dict[str, int] = {}

    tables_payload = data.get(
        "tables",
        {},
    )

    if isinstance(
        tables_payload,
        dict,
    ):
        if isinstance(
            tables_payload.get("tables"),
            list,
        ):
            table_items = (
                tables_payload["tables"]
            )
        else:
            table_items = [
                {
                    "table_id": key,
                    **value,
                }
                for key, value
                in tables_payload.items()
                if isinstance(value, dict)
            ]

    elif isinstance(
        tables_payload,
        list,
    ):
        table_items = tables_payload

    else:
        table_items = []

    for table in table_items:
        if not isinstance(table, dict):
            continue

        table_id = clean_text(
            table.get("table_id")
            or table.get("id"),
            default="table",
        )

        records = (
            table.get("records")
            if isinstance(
                table.get("records"),
                list,
            )
            else table.get("rows")
            if isinstance(
                table.get("rows"),
                list,
            )
            else []
        )

        counts[table_id] = len(
            records
        )

    map_payload = (
        data.get("map_layers")
        or data.get("map")
        or {}
    )

    map_payload = extract_payload_data(
        map_payload,
        map_payload,
    )

    layers = (
        map_payload.get("layers", {})
        if isinstance(map_payload, dict)
        else {}
    )

    if isinstance(layers, list):
        layer_items = [
            (
                clean_text(
                    layer.get("layer_id"),
                    default=f"layer_{index}",
                ),
                layer,
            )
            for index, layer
            in enumerate(layers)
            if isinstance(layer, dict)
        ]

    elif isinstance(layers, dict):
        layer_items = list(
            layers.items()
        )

    else:
        layer_items = []

    for layer_id, layer in layer_items:
        feature_collection = (
            layer.get(
                "feature_collection"
            )
            or layer.get("features")
            or {}
        )

        if (
            isinstance(
                feature_collection,
                dict,
            )
            and isinstance(
                feature_collection.get(
                    "features"
                ),
                list,
            )
        ):
            layer_count = len(
                feature_collection[
                    "features"
                ]
            )
        else:
            layer_count = (
                to_int(
                    layer.get(
                        "record_count"
                    ),
                    0,
                )
                or 0
            )

        counts[
            f"map_{layer_id}"
        ] = layer_count

    graph = data.get(
        "linkage_graph",
        {},
    )

    if isinstance(graph, dict):
        counts["graph_nodes"] = len(
            graph.get("nodes", [])
            if isinstance(
                graph.get("nodes"),
                list,
            )
            else []
        )
        counts["graph_edges"] = len(
            graph.get("edges", [])
            if isinstance(
                graph.get("edges"),
                list,
            )
            else []
        )

    for key in [
        "companies",
        "policy_summary",
        "policy_table",
        "linkage_lines",
        "prediction",
        "entity",
    ]:
        value = data.get(key)

        if isinstance(value, list):
            counts[key] = len(value)

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


def write_public_package_access_log(
    package_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compatibility wrapper for POST /api/public/packages/<package_id>/access-log.
    """

    if not isinstance(payload, dict):
        payload = {}

    try:
        action = clean_text(payload.get("action"), default="view")
        reason = clean_text(payload.get("reason"), default="")
        allowed = to_bool(payload.get("allowed"), default=True)
        remote_addr = clean_text(payload.get("remote_addr"), default="")
        user_agent = clean_text(payload.get("user_agent"), default="")

        record = log_public_access(
            package_id=package_id,
            action=action or "view",
            allowed=bool(allowed),
            reason=reason,
            remote_addr=remote_addr,
            user_agent=user_agent,
            extra={
                "payload": to_jsonable(payload),
            },
        )

        return {
            "success": True,
            "message": "Public package access log written.",
            "data": {
                "package_id": package_id,
                "logged": True,
                "record": record,
            },
            "meta": {
                "generated_at": now_iso(),
            },
            "errors": [],
        }

    except Exception as exc:
        return {
            "success": False,
            "message": "Failed to write public package access log.",
            "data": {
                "package_id": package_id,
                "logged": False,
            },
            "meta": {
                "generated_at": now_iso(),
                "status_code": 500,
            },
            "errors": [
                {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            ],
        }


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
    return {
        "module": "dashboard_package_service",
        "ready": True,
        "config_loaded": CONFIG_LOADED,
        "utils_loaded": UTILS_LOADED,
        "security_loaded": SECURITY_LOADED,
        "pandas_loaded": PANDAS_LOADED,
        "package_dir": str(PACKAGE_DIR),
        "package_dir_exists": Path(PACKAGE_DIR).exists(),
        "cache_keys": {
            **CACHE_KEYS,
            **SOURCE_CACHE_KEYS,
        },
        "runtime_contracts": {
            "dashboard_summary": True,
            "dashboard_province_insights": True,
            "risk_distribution_chart": True,
            "province_comparison_chart": True,
            "station_ranking_chart": True,
            "staged_rebuild_orchestrator": True,
            "package_snapshot_only": True,
            "public_package_snapshot_only": True,
        },
        "staged_rebuild_phases": [
            "validate_runtime_inputs",
            "company_policy_base",
            "linkage",
            "flood_excel_base",
            "spatial_prediction_entity",
            "company_policy_enriched",
            "map",
            "dashboard_charts",
            "data_quality",
            "package_snapshot",
        ],
        "supported_package_components": DEFAULT_PACKAGE_COMPONENTS,
        "public_components": sorted(ALLOWED_PUBLIC_COMPONENTS) if "ALLOWED_PUBLIC_COMPONENTS" in globals() else sorted(PUBLIC_COMPONENT_FILES.keys()),
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


# ============================================================
# 19) PHASE 12 STABLE DASHBOARD / PACKAGE API CONTRACT
# ============================================================
ALLOWED_PUBLIC_COMPONENTS = {
    "meta",
    "data",
    "summary",
    "companies",
    "policy_summary",
    "policy_table",
    "linkage_graph",
    "linkage_lines",
    "flood_summary",
    "map",
    "map_layers",
    "charts",
    "tables",
    "data_quality",
    "filter_options",
    "prediction",
    "flood_prediction",
    "flood_prediction_latest",
    "flood_prediction_map",
    "entity",
    "uploaded_entity",
    "uploaded_entity_latest",
}

PUBLIC_COMPONENT_FILES = {
    **PUBLIC_COMPONENT_FILES,
    "data_quality": "data_quality.json",
    "prediction": "prediction.json",
    "flood_prediction": "prediction.json",
    "flood_prediction_latest": "prediction.json",
    "flood_prediction_map": "prediction_map.json",
    "entity": "entity.json",
    "uploaded_entity": "entity.json",
    "uploaded_entity_latest": "entity.json",
    "map_layers": "map.json",
    "access_log": "access_log.jsonl",
}

PACKAGE_FILE_NAMES = {
    "meta": PACKAGE_META_FILENAME,
    "snapshot": PACKAGE_SNAPSHOT_FILENAME,
    "public_data": PACKAGE_PUBLIC_DATA_FILENAME,
    "summary": "summary.json",
    "map": "map.json",
    "charts": "charts.json",
    "tables": "tables.json",
    "data_quality": "data_quality.json",
    "prediction": "prediction.json",
    "prediction_map": "prediction_map.json",
    "entity": "entity.json",
    "access_log": "access_log.jsonl",
}

PACKAGE_CHECKSUM_COMPONENT_KEYS = [
    "summary",
    "companies",
    "policy_summary",
    "policy_table",
    "linkage_graph",
    "linkage_lines",
    "flood_summary",
    "map",
    "map_layers",
    "charts",
    "tables",
    "data_quality",
    "filter_options",
    "prediction",
    "flood_prediction",
    "flood_prediction_latest",
    "flood_prediction_map",
    "entity",
    "uploaded_entity",
    "uploaded_entity_latest",
]

SNAPSHOT_ONLY_PACKAGE_POLICY = {
    "package_reads_live_excel": False,
    "package_source": "cache_snapshot",
    "public_viewer_source": "public_data_json_only",
    "public_viewer_reads_raw_cache": False,
    "public_viewer_reads_raw_excel": False,
}

SOURCE_CACHE_KEYS = {
    "companies": "company_unified_master",
    "company_unified_base": "company_unified_base",
    "company_unified_master": "company_unified_master",
    "policy": "policy_fact",
    "policy_company_summary": "policy_company_summary",
    "linkage": "linkage_graph_payload",
    "linkage_graph_payload": "linkage_graph_payload",
    "directors": "director_master",
    "flood": "flood_computed_risk",
    "flood_rainfall_latest": "flood_rainfall_latest",
    "flood_waterlevel_latest": "flood_waterlevel_latest",
    "flood_large_dam_latest": "flood_large_dam_latest",
    "flood_medium_dam_latest": "flood_medium_dam_latest",
    "flood_dam_latest": "flood_dam_latest",
    "flood_prediction_latest": "flood_prediction_latest",
    "flood_prediction_summary": "flood_prediction_summary",
    "flood_prediction_map": "flood_prediction_map",
    "uploaded_entity_latest": "uploaded_entity_latest",
    "spatial": "spatial_join_result",
    "map_layers": "map_layers",
    "dashboard_summary": "dashboard_summary",
    "dashboard_province_insights": "dashboard_province_insights",
    "chart_summary": "chart_summary",
    "data_quality": "data_quality_summary",
    "filter_context": "filter_context",
    "package_index": "package_index",
}

def json_safe(value: Any) -> Any:
    return to_jsonable(value)


def safe_count(value: Any) -> int:
    if isinstance(value, dict):
        for key in ("records", "items", "features", "nodes", "edges", "packages"):
            if isinstance(value.get(key), list):
                return len(value[key])
        return len(value)
    if isinstance(value, list):
        return len(value)
    return 0


def safe_sum(records: List[Dict[str, Any]], field: str) -> float:
    return sum(to_number(record.get(field), 0.0) for record in records or [] if isinstance(record, dict))


def safe_ratio(numerator: Any, denominator: Any) -> float:
    denom = to_number(denominator, 0.0)
    if not denom:
        return 0.0
    return round(to_number(numerator, 0.0) / denom, 6)


def safe_slug(value: Any, default: str = "package") -> str:
    return safe_filename(value, default=default)


def make_dashboard_response(
    data: Optional[Dict[str, Any]] = None,
    message: str = "Dashboard payload loaded.",
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    success: bool = True,
) -> Dict[str, Any]:
    response_meta = {
        "module": "dashboard_package",
        "generated_at": now_iso(),
        "degraded": False,
    }
    response_meta.update(meta or {})
    return json_safe(
        {
            "success": bool(success),
            "message": message,
            "data": data or {},
            "meta": response_meta,
            "errors": errors or [],
        }
    )


def make_package_response(
    data: Optional[Dict[str, Any]] = None,
    message: str = "Package operation completed.",
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    success: bool = True,
) -> Dict[str, Any]:
    return make_dashboard_response(data=data, message=message, meta=meta, errors=errors, success=success)

def make_package_error(
    message: str = "Package operation failed.",
    error_type: str = "PackageError",
    status_code: int = 500,
    field: str = "",
    data: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    safe_status_code = max(
        400,
        min(
            int(status_code or 500),
            599,
        ),
    )

    public_message = clean_text(
        message,
        "Package operation failed.",
    )

    if (
        safe_status_code >= 500
        and not bool(
            getattr(
                config,
                "DEBUG",
                False,
            )
        )
    ):
        public_message = (
            "Package operation failed."
        )

    return make_package_response(
        data=data or {},
        message=public_message,
        meta={
            "status_code": safe_status_code,
            "degraded": True,
        },
        errors=[
            {
                "type": clean_text(
                    error_type,
                    "PackageError",
                ),
                "field": clean_text(
                    field
                ),
                "message": public_message,
            }
        ],
        success=False,
    )

def make_degraded_package_response(reason: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return make_package_response(
        data=data or {},
        message="Operation completed with missing source data.",
        meta={"degraded": True, "reason": reason},
        errors=[],
        success=True,
    )


def _package_root() -> Path:
    return Path(PACKAGE_DIR).resolve()


def ensure_package_dir(package_id: Optional[str] = None) -> Path:
    root = ensure_dir(_package_root())
    if not package_id:
        return root
    folder = get_package_folder(package_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder

def _safe_package_id(
    package_id: Any,
) -> str:
    text = clean_text(
        package_id
    )

    if (
        not text
        or text in {".", ".."}
        or len(text) > 128
        or Path(text).name != text
        or any(
            not (
                character.isalnum()
                or character in {
                    "-",
                    "_",
                }
            )
            for character in text
        )
    ):
        return ""

    return text


def get_package_folder(
    package_id: str,
) -> Path:
    clean_id = _safe_package_id(
        package_id
    )

    root = _package_root()

    if not clean_id:
        return root / "__invalid__"

    candidate = (
        root
        / clean_id
    ).resolve()

    if root not in candidate.parents:
        return root / "__invalid__"

    return candidate


def get_package_file(
    package_id: str,
    filename: str,
) -> Path:
    allowed = (
        set(
            PACKAGE_FILE_NAMES.values()
        )
        | {
            PACKAGE_INDEX_FILENAME,
            "access_log.json",
            "access_log.jsonl",
        }
    )

    clean_name = Path(
        clean_text(filename)
    ).name

    if clean_name not in allowed:
        return (
            get_package_folder(
                package_id
            )
            / "__invalid__"
        )

    return (
        get_package_folder(
            package_id
        )
        / clean_name
    )

def read_json_file_safe(path: Any, default: Any = None) -> Any:
    try:
        target = Path(path)
        if not target.exists() or not target.is_file():
            return default
        return json_safe(read_json(target, default=default))
    except Exception:
        return default


def write_json_file_safe(path: Any, data: Any) -> Dict[str, Any]:
    try:
        target = write_json(path, json_safe(data))
        return {"written": True, "name": target.name, "size": target.stat().st_size if target.exists() else 0}
    except Exception as exc:
        return {"written": False, "name": Path(path).name, "error": str(exc)}

def extract_payload_data(payload: Any, default: Any = None) -> Any:
    if default is None:
        default = {}

    if isinstance(payload, dict) and "success" in payload and "data" in payload:
        return payload.get("data", default)

    return payload if payload is not None else default


def remove_snapshot_internal_keys(
    payload: Any,
) -> Any:
    forbidden_keys = {
        "path",
        "source_file",
        "source_file_path",
        "source_path",
        "internal_path",
        "local_path",
        "absolute_path",
        "cache_file",
        "cache_path",
        "raw_file_path",
        "upload_dir",
        "saved_file",
        "error_report_file",
        "export_path",
        "zip_path",
        "download_path",
        "package_path",
        "package_dir",
        "viewer_dir",
        "index_path",
        "data_path",
        "assets_dir",
        "debug_traceback",
        "traceback",
        "raw_record",
        "raw_records",
        "raw_row",
        "raw_rows",
        "raw_payload",
        "raw_sheet",
        "raw_sheet_name",
    }

    if isinstance(payload, dict):
        result: Dict[
            str,
            Any,
        ] = {}

        for key, value in payload.items():
            normalized_key = (
                clean_text_lower(
                    key
                ).replace(
                    " ",
                    "_",
                )
            )

            if (
                normalized_key
                in forbidden_keys
            ):
                continue

            cleaned = (
                remove_snapshot_internal_keys(
                    value
                )
            )

            if cleaned in (
                {},
                [],
                "",
                None,
            ):
                continue

            result[key] = cleaned

        return result

    if isinstance(payload, list):
        return [
            item
            for item in (
                remove_snapshot_internal_keys(
                    item
                )
                for item in payload
            )
            if item not in (
                {},
                [],
                "",
                None,
            )
        ]

    text = clean_text(
        payload
    )
    normalized = (
        text
        .replace("\\", "/")
        .lower()
    )

    if (
        normalized.startswith(
            (
                "file://",
                "/mnt/",
                "/tmp/",
                "/home/",
                "/users/",
                "/var/",
                "/etc/",
                "/opt/",
                "/app/",
                "/workspace/",
                "/backend/",
                "/sandbox/",
            )
        )
        or "c:/users/" in normalized
    ):
        return ""

    return payload


def normalize_public_map_payload(payload: Any) -> Dict[str, Any]:
    data = extract_payload_data(payload, {})
    if not isinstance(data, dict):
        data = {}

    return json_safe(
        remove_snapshot_internal_keys(
            {
                "map": data.get("map", {}),
                "center": data.get("center") or data.get("map", {}).get("center"),
                "zoom": data.get("zoom") or data.get("map", {}).get("zoom"),
                "layers": data.get("layers", {}),
                "layers_by_id": data.get("layers_by_id", data.get("layers", {})),
                "layer_order": data.get("layer_order", []),
                "layer_list": data.get("layer_list", data.get("layers_list", data.get("legacy_layers", []))),
                "layers_list": data.get("layers_list", data.get("layer_list", [])),
                "legacy_layers": data.get("legacy_layers", data.get("layer_list", [])),
                "summary": data.get("summary", {}),
                "meta": {
                    **(data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}),
                    "snapshot_only": True,
                    "public_viewer_source": "public_data_json_only",
                },
            }
        )
    )


def normalize_public_prediction_payload(records: List[Dict[str, Any]], prediction_map: Any = None) -> Dict[str, Any]:
    prediction_records = [
        remove_snapshot_internal_keys(record)
        for record in records or []
        if isinstance(record, dict)
    ]

    map_payload = extract_payload_data(prediction_map, prediction_map or {})
    if not isinstance(map_payload, dict):
        map_payload = {
            "type": "FeatureCollection",
            "features": [],
            "total": 0,
            "meta": {},
        }

    return json_safe(
        {
            "records": prediction_records,
            "total": len(prediction_records),
            "map": remove_snapshot_internal_keys(map_payload),
            "meta": {
                "record_count": len(prediction_records),
                "map_ready_count": sum(1 for record in prediction_records if to_bool(record.get("map_ready"), default=False)),
                "generated_at": now_iso(),
                "snapshot_only": True,
            },
        }
    )


def normalize_public_entity_payload(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    displayable_records = []

    for record in records or []:
        if not isinstance(record, dict):
            continue

        is_displayable = (
            to_bool(record.get("is_displayable"), default=True)
            or to_bool(record.get("map_ready"), default=False)
            or to_bool(record.get("has_location"), default=False)
        )

        lat = record.get("latitude", record.get("lat"))
        lon = record.get("longitude", record.get("lon"))

        if not is_displayable and (is_empty_value(lat) or is_empty_value(lon)):
            continue

        displayable_records.append(remove_snapshot_internal_keys(record))

    return json_safe(
        {
            "records": displayable_records,
            "displayable_records": displayable_records,
            "total": len(displayable_records),
            "meta": {
                "record_count": len(displayable_records),
                "displayable_only": True,
                "generated_at": now_iso(),
                "snapshot_only": True,
            },
        }
    )

def normalize_records(payload: Any, source_name: Optional[str] = None) -> List[Dict[str, Any]]:
    return normalize_cache_payload_to_records(payload, source_name=source_name)


def normalize_cache_payload_to_records(payload: Any, source_name: Optional[str] = None) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    def append_items(items: Any, kind: str = "") -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                record = dict(item)
                if kind and "record_kind" not in record:
                    record["record_kind"] = kind
                if source_name and "source" not in record:
                    record["source"] = source_name
                records.append(record)

    if isinstance(payload, list):
        append_items(payload)
        return records
    if not isinstance(payload, dict):
        return []

    for key in ("records", "items", "companies", "issues", "packages", "cards", "rows"):
        if isinstance(payload.get(key), list):
            append_items(payload[key], key[:-1] if key.endswith("s") else key)
            return records

    data = payload.get("data")
    if isinstance(data, list):
        append_items(data)
        return records
    if isinstance(data, dict):
        extracted = normalize_cache_payload_to_records(data, source_name)
        if extracted:
            return extracted

    if isinstance(payload.get("nodes"), list) or isinstance(payload.get("edges"), list):
        append_items(payload.get("nodes", []), "node")
        append_items(payload.get("edges", []), "edge")
        return records

    layers = payload.get("layers")
    if isinstance(layers, dict):
        layer_iter = layers.values()
    elif isinstance(layers, list):
        layer_iter = layers
    else:
        layer_iter = []
    for layer in layer_iter:
        if not isinstance(layer, dict):
            continue
        layer_id = clean_text(layer.get("layer_id"))
        features = layer.get("features") or layer.get("feature_collection")
        if isinstance(features, dict):
            append_items(
                [
                    {
                        "layer_id": layer_id,
                        **(feature.get("properties", {}) if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else {}),
                    }
                    for feature in features.get("features", [])
                    if isinstance(feature, dict)
                ],
                "map_feature",
            )
    if records:
        return records

    features = payload.get("features")
    if isinstance(features, dict) and isinstance(features.get("features"), list):
        for feature in features["features"]:
            if isinstance(feature, dict):
                records.append({"record_kind": "feature", **(feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {})})
        return records

    summary = payload.get("summary")
    if isinstance(summary, dict):
        records.append({"record_kind": "summary", "source": source_name or "summary", **summary})
    return records


extract_records_from_payload = normalize_cache_payload_to_records

def _cache_dir() -> Path:
    return Path(
        getattr(
            config,
            "CACHE_DIR",
            Path(OUTPUT_DIR) / "cache",
        )
    )


def _load_cache_payload(
    cache_key: str,
) -> Any:
    try:
        cache_path = Path(
            get_cache_file_path(
                cache_key
            )
        )
    except Exception:
        cache_path = (
            _cache_dir()
            / (
                f"{safe_slug(cache_key, 'cache')}"
                ".json"
            )
        )

    return read_json_file_safe(
        cache_path,
        default=None,
    )

def load_company_records() -> List[Dict[str, Any]]:
    records = normalize_cache_payload_to_records(_load_cache_payload("company_unified_master"), "company_unified_master")
    if records:
        return records
    return normalize_cache_payload_to_records(safe_call_service(get_company_unified_records, fallback=[]), "company_unified_master")


def load_policy_records() -> List[Dict[str, Any]]:
    records = normalize_cache_payload_to_records(_load_cache_payload("policy_fact"), "policy_fact")
    if records:
        return records
    return normalize_cache_payload_to_records(safe_call_service(get_policy_companies, fallback=[]), "policy_fact")

def unwrap_service_payload(payload: Any, default: Any = None) -> Any:
    if default is None:
        default = {}

    if isinstance(payload, dict) and "success" in payload and "data" in payload:
        return payload.get("data", default)

    return payload if payload is not None else default


def extract_records_any(payload: Any, source_name: str = "") -> List[Dict[str, Any]]:
    return normalize_cache_payload_to_records(unwrap_service_payload(payload, payload), source_name=source_name)


def normalize_dashboard_risk(value: Any) -> str:
    risk = normalize_risk_level(value)
    if risk in {"High", "Medium", "Low"}:
        return {
            "High": "Warning",
            "Medium": "Watch",
            "Low": "Normal",
        }.get(risk, risk)
    return risk


def dashboard_risk_score(value: Any) -> int:
    risk = normalize_dashboard_risk(value)
    return RISK_SCORE.get(risk, SUMMARY_STATUS_ORDER.get(risk, 0))


def first_record_value(record: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    for key in keys:
        value = record.get(key)
        if not is_empty_value(value):
            return value
    return default


def province_value(record: Dict[str, Any]) -> str:
    return clean_text(
        first_record_value(
            record,
            [
                "province",
                "province_model",
                "province_name_th",
                "company_province",
                "location_province",
            ],
            default="Unknown",
        ),
        default="Unknown",
    )


def get_metric_value(record: Dict[str, Any], keys: List[str]) -> float:
    for key in keys:
        value = to_number(record.get(key), None)
        if value is not None:
            return value
    return 0.0


def build_top_records(
    records: List[Dict[str, Any]],
    metric_keys: List[str],
    limit: int,
    mode: str,
    label_field_candidates: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    label_field_candidates = label_field_candidates or [
        "source_name",
        "station_name",
        "dam_name",
        "province",
    ]

    items: List[Dict[str, Any]] = []

    for record in records or []:
        province = province_value(record)
        metric_value = get_metric_value(record, metric_keys)
        risk = normalize_dashboard_risk(
            first_record_value(
                record,
                [
                    "risk_level",
                    "risk_status",
                    "warning_level",
                    "warning_level_predict",
                    "flood_risk_level",
                ],
                default="Unknown",
            )
        )

        items.append(
            {
                "province": province,
                "name": clean_text(first_record_value(record, label_field_candidates, default=province)),
                "value": metric_value,
                "risk_level": risk,
                "risk_score": dashboard_risk_score(risk),
                "focus": {
                    "type": "province",
                    "province": province,
                    "mode": mode,
                },
                "raw": record,
            }
        )

    items = sorted(
        items,
        key=lambda item: (
            item.get("risk_score", 0),
            to_number(item.get("value"), 0) or 0,
        ),
        reverse=True,
    )

    return json_safe(items[:limit])


def build_top_prediction_risk_provinces(records: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}

    for record in records or []:
        province = province_value(record)
        risk = normalize_dashboard_risk(
            first_record_value(
                record,
                ["risk_level", "risk_status", "warning_level_predict", "warning_level"],
                default="Unknown",
            )
        )
        score = dashboard_risk_score(risk)
        confidence = to_number(first_record_value(record, ["confidence", "model_confidence"], default=0), 0) or 0

        item = grouped.setdefault(
            province,
            {
                "province": province,
                "risk_level": risk,
                "risk_score": score,
                "confidence": confidence,
                "prediction_count": 0,
                "critical_count": 0,
                "warning_count": 0,
                "watch_count": 0,
                "target_horizons": set(),
                "focus": {
                    "type": "province",
                    "province": province,
                    "mode": "prediction",
                },
            },
        )

        item["prediction_count"] += 1
        item["risk_score"] = max(item["risk_score"], score)
        item["confidence"] = max(item["confidence"], confidence)

        if score >= dashboard_risk_score(item["risk_level"]):
            item["risk_level"] = risk

        if risk == "Critical":
            item["critical_count"] += 1
        elif risk == "Warning":
            item["warning_count"] += 1
        elif risk == "Watch":
            item["watch_count"] += 1

        horizon = first_record_value(record, ["forecast_horizon_day", "horizon", "prediction_horizon"], default="")
        if not is_empty_value(horizon):
            item["target_horizons"].add(clean_text(horizon))

    result = []

    for item in grouped.values():
        target_horizons = sorted(item.pop("target_horizons", set()))
        item["target_horizons"] = target_horizons
        item["target_display"] = ", ".join(target_horizons) if target_horizons else ""
        result.append(item)

    result = sorted(
        result,
        key=lambda item: (
            item.get("risk_score", 0),
            item.get("critical_count", 0),
            item.get("warning_count", 0),
            item.get("prediction_count", 0),
        ),
        reverse=True,
    )

    return json_safe(result[:limit])

def call_dashboard_service_records(
    function_ref: Any,
    context: Optional[
        Dict[str, Any]
    ],
    cache_key: str,
    source_name: str,
) -> List[Dict[str, Any]]:
    ctx = normalize_context(
        context
    )

    cached_records = (
        normalize_cache_payload_to_records(
            _load_cache_payload(
                cache_key
            ),
            source_name=source_name,
        )
    )

    if cached_records:
        return cached_records

    if ctx.get("snapshot_only"):
        return []

    if function_ref is not None:
        payload = safe_call_service(
            function_ref,
            fallback={},
            context=ctx,
        )

        records = extract_records_any(
            payload,
            source_name=source_name,
        )

        if records:
            return records

    return []

def load_rainfall_latest_records(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return call_dashboard_service_records(get_latest_rainfall, context, "flood_rainfall_latest", "flood_rainfall_latest")


def load_waterlevel_latest_records(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return call_dashboard_service_records(get_latest_waterlevel, context, "flood_waterlevel_latest", "flood_waterlevel_latest")


def load_dam_latest_records(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = call_dashboard_service_records(get_latest_dam, context, "flood_large_dam_latest", "flood_dam_latest")
    if records:
        return records

    records = []
    records.extend(normalize_cache_payload_to_records(_load_cache_payload("flood_large_dam_latest"), "flood_large_dam_latest"))
    records.extend(normalize_cache_payload_to_records(_load_cache_payload("flood_medium_dam_latest"), "flood_medium_dam_latest"))
    return records


def load_prediction_latest_records(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return call_dashboard_service_records(get_latest_flood_predictions, context, "flood_prediction_latest", "flood_prediction_latest")


def load_uploaded_entity_records(
    context: Optional[
        Dict[str, Any]
    ] = None,
) -> List[Dict[str, Any]]:
    ctx = normalize_context(
        context
    )

    cached_records = (
        normalize_cache_payload_to_records(
            _load_cache_payload(
                "uploaded_entity_latest"
            ),
            "uploaded_entity_latest",
        )
    )

    if (
        cached_records
        or ctx.get("snapshot_only")
    ):
        return cached_records

    try:
        import entity_upload_service

        payload = (
            entity_upload_service
            .get_latest_entity_records(
                context=ctx,
                limit=10000,
                offset=0,
            )
        )

        return extract_records_any(
            payload,
            source_name=(
                "uploaded_entity_latest"
            ),
        )

    except Exception:
        return []


def load_prediction_map_payload(
    context: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(
        context
    )

    cached = _load_cache_payload(
        "flood_prediction_map"
    )

    if (
        isinstance(cached, dict)
        and cached
    ):
        return json_safe(
            extract_payload_data(
                cached,
                cached,
            )
        )

    if ctx.get("snapshot_only"):
        return {
            "type": "FeatureCollection",
            "features": [],
            "total": 0,
            "meta": {
                "degraded": True,
                "source": "cache_missing",
                "snapshot_only": True,
            },
        }

    payload = (
        safe_call_service(
            get_flood_prediction_map,
            fallback={},
            context=ctx,
        )
        if get_flood_prediction_map
        else {}
    )

    data = extract_payload_data(
        payload,
        payload,
    )

    if (
        isinstance(data, dict)
        and data
    ):
        return json_safe(data)

    return {
        "type": "FeatureCollection",
        "features": [],
        "total": 0,
        "meta": {
            "degraded": True,
            "source": (
                "service_unavailable"
            ),
        },
    }

def load_linkage_records() -> Dict[str, List[Dict[str, Any]]]:
    graph_payload = _load_cache_payload("linkage_graph_payload") or _load_cache_payload("linkage_graph") or safe_call_service(get_linkage_graph, fallback={})

    if isinstance(graph_payload, dict):
        data = graph_payload.get("data") if isinstance(graph_payload.get("data"), dict) else graph_payload
        return {
            "nodes": normalize_cache_payload_to_records(data.get("nodes", []), "linkage_nodes") if isinstance(data, dict) else [],
            "edges": normalize_cache_payload_to_records(data.get("edges", []), "linkage_edges") if isinstance(data, dict) else [],
        }

    return {"nodes": [], "edges": []}

def load_flood_records() -> List[Dict[str, Any]]:
    records = normalize_cache_payload_to_records(_load_cache_payload("flood_computed_risk"), "flood_computed_risk")
    if records:
        return records
    return normalize_cache_payload_to_records(safe_call_service(get_flood_computed_risk, fallback=[]), "flood_computed_risk")

def load_map_payload(
    context: Optional[
        Dict[str, Any]
    ] = None,
    public: bool = False,
) -> Dict[str, Any]:
    ctx = normalize_context(
        context
    )

    fallback = {
        "map": {
            "center": [
                100.5018,
                13.7563,
            ],
            "zoom": 6,
        },
        "layers": {},
        "layers_by_id": {},
        "layer_order": [],
        "layer_list": [],
        "layers_list": [],
        "legacy_layers": [],
        "summary": {
            "layer_count": 0,
            "feature_count": 0,
            "record_count": 0,
            "degraded": True,
        },
        "meta": {
            "degraded": True,
            "source": "fallback",
            "snapshot_only": bool(
                public
                or ctx.get(
                    "snapshot_only"
                )
            ),
        },
    }

    cached = _load_cache_payload(
        "map_layers"
    )

    if (
        isinstance(cached, dict)
        and cached
    ):
        payload = extract_payload_data(
            cached,
            cached,
        )

    elif ctx.get("snapshot_only"):
        payload = fallback

    elif (
        public
        and get_external_viewer_map_payload
    ):
        payload = safe_call_service(
            get_external_viewer_map_payload,
            fallback=fallback,
            context=ctx,
        )
        payload = extract_payload_data(
            payload,
            fallback,
        )

    elif get_map_layers:
        payload = safe_call_service(
            get_map_layers,
            fallback=fallback,
            context=ctx,
        )
        payload = extract_payload_data(
            payload,
            fallback,
        )

    else:
        payload = fallback

    if not isinstance(payload, dict):
        payload = fallback

    if isinstance(
        payload.get("layers"),
        list,
    ):
        layer_list = payload.get(
            "layers",
            [],
        )

        layers_by_id = {
            clean_text(
                layer.get("layer_id"),
                default=(
                    f"layer_{index}"
                ),
            ): layer
            for index, layer
            in enumerate(layer_list)
            if isinstance(layer, dict)
        }

        payload["layers"] = (
            layers_by_id
        )
        payload["layers_by_id"] = (
            layers_by_id
        )
        payload["layer_list"] = (
            layer_list
        )
        payload["layers_list"] = (
            layer_list
        )
        payload["legacy_layers"] = (
            layer_list
        )

    if isinstance(
        payload.get("layers"),
        dict,
    ):
        payload.setdefault(
            "layers_by_id",
            payload["layers"],
        )
        payload.setdefault(
            "layer_order",
            list(payload["layers"]),
        )
        payload.setdefault(
            "layer_list",
            [
                payload["layers"][key]
                for key
                in payload["layer_order"]
                if key
                in payload["layers"]
            ],
        )
        payload.setdefault(
            "layers_list",
            payload["layer_list"],
        )
        payload.setdefault(
            "legacy_layers",
            payload["layer_list"],
        )

    payload.setdefault(
        "map",
        {},
    )
    payload.setdefault(
        "summary",
        {},
    )
    payload.setdefault(
        "meta",
        {},
    )

    payload["meta"][
        "snapshot_only"
    ] = bool(
        public
        or ctx.get("snapshot_only")
    )

    payload["meta"][
        "public_viewer_source"
    ] = (
        "public_data_json_only"
        if public
        else "cache_snapshot"
    )

    return (
        normalize_public_map_payload(
            payload
        )
        if public
        else json_safe(payload)
    )

def get_data_quality_dashboard_function() -> Any:
    if build_data_quality_dashboard_payload is not None:
        return build_data_quality_dashboard_payload

    try:
        import data_quality

        if hasattr(data_quality, "build_data_quality_dashboard_payload"):
            return getattr(data_quality, "build_data_quality_dashboard_payload")

        if hasattr(data_quality, "get_data_quality_dashboard_payload"):
            return getattr(data_quality, "get_data_quality_dashboard_payload")

        if hasattr(data_quality, "get_data_quality_summary"):
            return getattr(data_quality, "get_data_quality_summary")

    except Exception:
        pass

    return get_data_quality_summary

def load_data_quality_payload(
    context: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(
        context
    )

    cached = _load_cache_payload(
        "data_quality_summary"
    )

    if (
        isinstance(cached, dict)
        and cached
    ):
        return json_safe(
            extract_payload_data(
                cached,
                cached,
            )
        )

    if ctx.get("snapshot_only"):
        return {
            "summary": {},
            "cards": [],
            "issues": [],
            "charts": {},
            "meta": {
                "degraded": True,
                "source": "cache_missing",
                "snapshot_only": True,
            },
        }

    function_ref = (
        get_data_quality_dashboard_function()
    )

    payload = (
        safe_call_service(
            function_ref,
            fallback={},
            context=ctx,
        )
        if function_ref is not None
        else {}
    )

    if (
        isinstance(payload, dict)
        and {
            "success",
            "data",
        }.issubset(payload)
    ):
        data = payload.get(
            "data",
            {},
        )

        return json_safe(
            data
            if isinstance(data, dict)
            else {}
        )

    if (
        isinstance(payload, dict)
        and payload
    ):
        return json_safe(payload)

    return {
        "summary": {},
        "cards": [],
        "issues": [],
        "charts": {},
        "meta": {
            "degraded": True,
            "source": (
                "service_unavailable"
            ),
        },
    }


def load_filter_context(
    context: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(
        context
    )

    cached = _load_cache_payload(
        "filter_context"
    )

    if (
        isinstance(cached, dict)
        and cached
    ):
        return json_safe(
            extract_payload_data(
                cached,
                cached,
            )
        )

    if ctx.get("snapshot_only"):
        return {
            "filters": ctx.get(
                "filters",
                {},
            ),
            "snapshot_only": True,
        }

    if build_filter_context_for_package:
        payload = safe_call_service(
            build_filter_context_for_package,
            fallback={},
            context=ctx,
        )

        return json_safe(
            payload
            if isinstance(payload, dict)
            else {}
        )

    return {
        "filters": ctx.get(
            "filters",
            {},
        )
    }

def load_dashboard_source_bundle(
    context: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(
        context
    )

    snapshot_only = bool(
        ctx.get("snapshot_only")
    )

    errors: List[
        Dict[str, Any]
    ] = []

    sources: Dict[
        str,
        Dict[str, Any],
    ] = {}

    def load_source(
        name: str,
        loader: Any,
        empty: Any,
    ) -> Any:
        try:
            value = loader()

            status = (
                "loaded"
                if safe_count(value)
                else "empty"
            )

            sources[name] = {
                "status": status,
                "record_count": (
                    safe_count(value)
                ),
            }

            return value

        except Exception as exc:
            sources[name] = {
                "status": "error",
                "record_count": 0,
            }

            errors.append(
                {
                    "source": name,
                    "type": (
                        exc.__class__.__name__
                    ),
                    "message": (
                        str(exc)
                        if bool(
                            getattr(
                                config,
                                "DEBUG",
                                False,
                            )
                        )
                        else "source_load_failed"
                    ),
                }
            )

            return empty

    def cached_records(
        cache_key: str,
        source_name: str,
    ) -> List[Dict[str, Any]]:
        return (
            normalize_cache_payload_to_records(
                _load_cache_payload(
                    cache_key
                ),
                source_name,
            )
        )

    if snapshot_only:
        linkage_payload = (
            _load_cache_payload(
                "linkage_graph_payload"
            )
            or {}
        )

        linkage_data = (
            extract_payload_data(
                linkage_payload,
                linkage_payload,
            )
        )

        linkage = {
            "nodes": (
                normalize_cache_payload_to_records(
                    linkage_data.get(
                        "nodes",
                        [],
                    )
                    if isinstance(
                        linkage_data,
                        dict,
                    )
                    else [],
                    "linkage_nodes",
                )
            ),
            "edges": (
                normalize_cache_payload_to_records(
                    linkage_data.get(
                        "edges",
                        [],
                    )
                    if isinstance(
                        linkage_data,
                        dict,
                    )
                    else [],
                    "linkage_edges",
                )
            ),
        }

        companies_loader = (
            lambda: cached_records(
                "company_unified_master",
                "company_unified_master",
            )
        )

        policy_loader = (
            lambda: cached_records(
                "policy_fact",
                "policy_fact",
            )
        )

        flood_loader = (
            lambda: cached_records(
                "flood_computed_risk",
                "flood_computed_risk",
            )
        )

        linkage_count = (
            len(linkage["nodes"])
            + len(linkage["edges"])
        )

        sources["linkage"] = {
            "status": (
                "loaded"
                if linkage_count
                else "empty"
            ),
            "record_count": (
                linkage_count
            ),
        }

    else:
        linkage = load_source(
            "linkage",
            load_linkage_records,
            {
                "nodes": [],
                "edges": [],
            },
        )

        companies_loader = (
            load_company_records
        )
        policy_loader = (
            load_policy_records
        )
        flood_loader = (
            load_flood_records
        )

    companies = load_source(
        "companies",
        companies_loader,
        [],
    )

    policy = load_source(
        "policy",
        policy_loader,
        [],
    )

    flood = load_source(
        "flood",
        flood_loader,
        [],
    )

    rainfall = load_source(
        "flood_rainfall_latest",
        lambda: (
            load_rainfall_latest_records(
                ctx
            )
        ),
        [],
    )

    waterlevel = load_source(
        "flood_waterlevel_latest",
        lambda: (
            load_waterlevel_latest_records(
                ctx
            )
        ),
        [],
    )

    dam = load_source(
        "flood_dam_latest",
        lambda: (
            load_dam_latest_records(
                ctx
            )
        ),
        [],
    )

    prediction = load_source(
        "flood_prediction_latest",
        lambda: (
            load_prediction_latest_records(
                ctx
            )
        ),
        [],
    )

    prediction_map = load_source(
        "flood_prediction_map",
        lambda: (
            load_prediction_map_payload(
                ctx
            )
        ),
        {},
    )

    entity = load_source(
        "uploaded_entity_latest",
        lambda: (
            load_uploaded_entity_records(
                ctx
            )
        ),
        [],
    )

    spatial = cached_records(
        "spatial_join_result",
        "spatial_join_result",
    )

    sources["spatial"] = {
        "status": (
            "loaded"
            if spatial
            else "empty"
        ),
        "record_count": len(
            spatial
        ),
    }

    map_payload = load_map_payload(
        ctx
    )

    map_layers = (
        map_payload.get(
            "layers",
            {},
        )
        if isinstance(
            map_payload,
            dict,
        )
        else {}
    )

    sources["map_layers"] = {
        "status": (
            "loaded"
            if map_layers
            else "empty"
        ),
        "record_count": (
            safe_count(map_layers)
        ),
    }

    data_quality_payload = (
        load_data_quality_payload(
            ctx
        )
    )

    sources["data_quality"] = {
        "status": (
            "loaded"
            if data_quality_payload
            else "empty"
        ),
        "record_count": (
            safe_count(
                data_quality_payload
            )
        ),
    }

    degraded = any(
        item.get("status")
        in {
            "empty",
            "error",
        }
        for item in sources.values()
    )

    return json_safe(
        {
            "companies": companies,
            "policy": policy,
            "policy_company_summary": (
                cached_records(
                    "policy_company_summary",
                    "policy_company_summary",
                )
            ),
            "linkage_nodes": (
                linkage.get(
                    "nodes",
                    [],
                )
            ),
            "linkage_edges": (
                linkage.get(
                    "edges",
                    [],
                )
            ),
            "directors": cached_records(
                "director_master",
                "director_master",
            ),
            "flood": flood,
            "flood_rainfall_latest": (
                rainfall
            ),
            "flood_waterlevel_latest": (
                waterlevel
            ),
            "flood_dam_latest": dam,
            "flood_prediction_latest": (
                prediction
            ),
            "flood_prediction_map": (
                prediction_map
            ),
            "uploaded_entity_latest": (
                entity
            ),
            "spatial": spatial,
            "map_layers": map_layers,
            "map": map_payload,
            "data_quality": (
                data_quality_payload
            ),
            "filter_context": (
                load_filter_context(
                    ctx
                )
            ),
            "meta": {
                "sources": sources,
                "degraded": degraded,
                "errors": errors,
                "generated_at": now_iso(),
                "source": (
                    "excel"
                    if getattr(
                        config,
                        "USE_EXCEL_DATA_SOURCE",
                        True,
                    )
                    else "mysql"
                ),
                "snapshot_only": (
                    snapshot_only
                ),
            },
        }
    )

def build_dashboard_kpis(bundle: Dict[str, Any]) -> Dict[str, Any]:
    companies = bundle.get("companies", [])
    policy = bundle.get("policy", [])
    flood = bundle.get("flood", [])
    return {
        "company_count": len(companies),
        "policy_record_count": len(policy),
        "flood_record_count": len(flood),
        "total_premium": safe_sum(companies, "total_premium") or safe_sum(policy, "premium"),
        "total_loss": safe_sum(companies, "total_loss") or safe_sum(policy, "loss"),
        "loss_ratio": safe_ratio(safe_sum(companies, "total_loss") or safe_sum(policy, "loss"), safe_sum(companies, "total_premium") or safe_sum(policy, "premium")),
        "linkage_node_count": len(bundle.get("linkage_nodes", [])),
        "linkage_edge_count": len(bundle.get("linkage_edges", [])),
    }


def build_dashboard_cards(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    kpis = build_dashboard_kpis(bundle)
    return [
        {"card_id": "companies", "label": "Companies", "value": kpis["company_count"], "status": "Normal"},
        {"card_id": "policy_records", "label": "Policy Records", "value": kpis["policy_record_count"], "status": "Normal"},
        {"card_id": "total_premium", "label": "Total Premium", "value": kpis["total_premium"], "status": "Normal"},
        {"card_id": "loss_ratio", "label": "Loss Ratio", "value": kpis["loss_ratio"], "status": "Watch" if kpis["loss_ratio"] > 0.6 else "Normal"},
        {"card_id": "linkage_edges", "label": "Linkage Edges", "value": kpis["linkage_edge_count"], "status": "Normal"},
        {"card_id": "flood_records", "label": "Flood Records", "value": kpis["flood_record_count"], "status": "Normal"},
    ]


def build_dashboard_alerts(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    for source, info in bundle.get("meta", {}).get("sources", {}).items():
        if info.get("status") in {"empty", "error"}:
            alerts.append({"alert_id": f"{source}_{info.get('status')}", "source": source, "severity": "medium" if info.get("status") == "error" else "low", "message": f"{source} source is {info.get('status')}"})
    dq_summary = bundle.get("data_quality", {}).get("summary", {}) if isinstance(bundle.get("data_quality"), dict) else {}
    if to_int(dq_summary.get("critical_count"), 0) > 0:
        alerts.append({"alert_id": "data_quality_critical", "source": "data_quality", "severity": "critical", "message": "Critical data quality issues exist."})
    return alerts


def _columns_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys = []
    for row in rows[:25]:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    return [{"key": key, "label": key.replace("_", " ").title(), "type": "number" if any(token in key for token in ("count", "total", "premium", "loss", "ratio")) else "text"} for key in keys[:24]]


def build_dashboard_tables(bundle: Dict[str, Any]) -> Dict[str, Any]:
    companies = bundle.get("companies", [])[:100]
    policy = bundle.get("policy", [])[:100]
    linkage_edges = bundle.get("linkage_edges", [])[:100]
    flood = bundle.get("flood", [])[:100]
    prediction = bundle.get("flood_prediction_latest", [])[:100]
    entity = bundle.get("uploaded_entity_latest", [])[:100]
    dq_issues = bundle.get("data_quality", {}).get("issues", []) if isinstance(bundle.get("data_quality"), dict) else []

    tables = [
        {"table_id": "companies", "title": "Companies", "columns": _columns_from_rows(companies), "rows": companies, "records": companies, "meta": {"record_count": len(companies)}},
        {"table_id": "policy_summary", "title": "Policy Summary", "columns": _columns_from_rows(policy), "rows": policy, "records": policy, "meta": {"record_count": len(policy)}},
        {"table_id": "linkage_summary", "title": "Linkage Summary", "columns": _columns_from_rows(linkage_edges), "rows": linkage_edges, "records": linkage_edges, "meta": {"record_count": len(linkage_edges)}},
        {"table_id": "flood_exposure", "title": "Flood Exposure", "columns": _columns_from_rows(flood), "rows": flood, "records": flood, "meta": {"record_count": len(flood)}},
        {"table_id": "flood_prediction_latest", "title": "Flood Prediction Latest", "columns": _columns_from_rows(prediction), "rows": prediction, "records": prediction, "meta": {"record_count": len(prediction)}},
        {"table_id": "uploaded_entity_latest", "title": "Uploaded Entity Latest", "columns": _columns_from_rows(entity), "rows": entity, "records": entity, "meta": {"record_count": len(entity)}},
        {"table_id": "data_quality_issues", "title": "Data Quality Issues", "columns": _columns_from_rows(dq_issues), "rows": dq_issues[:100], "records": dq_issues[:100], "meta": {"record_count": len(dq_issues)}},
    ]

    return {"tables": json_safe(tables), "meta": {"table_count": len(tables)}}

def build_dashboard_summary(
    context: Optional[
        Dict[str, Any]
    ] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    ctx = normalize_context(
        context
    )

    if force_refresh:
        ctx["force_refresh"] = True

    bundle = load_dashboard_source_bundle(
        ctx
    )

    kpis = build_dashboard_kpis(
        bundle
    )
    cards = build_dashboard_cards(
        bundle
    )
    alerts = build_dashboard_alerts(
        bundle
    )
    province_insights = (
        build_dashboard_province_insights(
            ctx
        )
    )

    prediction_records = bundle.get(
        "flood_prediction_latest",
        [],
    )

    entity_records = bundle.get(
        "uploaded_entity_latest",
        [],
    )

    runtime_counts = {
        "rainfall_latest": len(
            bundle.get(
                "flood_rainfall_latest",
                [],
            )
        ),
        "waterlevel_latest": len(
            bundle.get(
                "flood_waterlevel_latest",
                [],
            )
        ),
        "dam_latest": len(
            bundle.get(
                "flood_dam_latest",
                [],
            )
        ),
        "prediction_latest": len(
            prediction_records
        ),
        "uploaded_entity_latest": len(
            entity_records
        ),
    }

    cards.extend(
        [
            {
                "card_id": (
                    "prediction_latest"
                ),
                "label": (
                    "Flood Predictions"
                ),
                "value": runtime_counts[
                    "prediction_latest"
                ],
                "status": "Normal",
            },
            {
                "card_id": (
                    "uploaded_entities"
                ),
                "label": (
                    "Uploaded Entities"
                ),
                "value": runtime_counts[
                    "uploaded_entity_latest"
                ],
                "status": "Normal",
            },
        ]
    )

    if ctx.get("snapshot_only"):
        prediction_summary = (
            extract_payload_data(
                _load_cache_payload(
                    "flood_prediction_summary"
                )
                or {},
                {},
            )
        )
    else:
        prediction_summary = (
            safe_call_service(
                get_flood_prediction_summary,
                fallback={},
                context=ctx,
            )
            if get_flood_prediction_summary
            else {}
        )

        prediction_summary = (
            extract_payload_data(
                prediction_summary,
                prediction_summary,
            )
        )

    return json_safe(
        {
            "summary_cards": cards,
            "record_counts": {
                "companies": (
                    kpis[
                        "company_count"
                    ]
                ),
                "policy": (
                    kpis[
                        "policy_record_count"
                    ]
                ),
                "linkage_nodes": (
                    kpis[
                        "linkage_node_count"
                    ]
                ),
                "linkage_edges": (
                    kpis[
                        "linkage_edge_count"
                    ]
                ),
                "flood": (
                    kpis[
                        "flood_record_count"
                    ]
                ),
                **runtime_counts,
            },
            "kpis": {
                **kpis,
                **runtime_counts,
            },
            "alerts": alerts,
            "province_insights": (
                province_insights
            ),
            "prediction_summary": (
                prediction_summary
            ),
            "overall_status": (
                "Warning"
                if any(
                    alert.get(
                        "severity"
                    )
                    in {
                        "critical",
                        "high",
                    }
                    for alert in alerts
                )
                else "Normal"
            ),
            "freshness": (
                build_dashboard_freshness(
                    ctx
                )
            ),
            "meta": {
                "generated_at": now_iso(),
                "degraded": (
                    bundle.get(
                        "meta",
                        {},
                    ).get(
                        "degraded",
                        False,
                    )
                ),
                "errors": (
                    bundle.get(
                        "meta",
                        {},
                    ).get(
                        "errors",
                        [],
                    )
                ),
                "source": (
                    "excel"
                    if getattr(
                        config,
                        "USE_EXCEL_DATA_SOURCE",
                        True,
                    )
                    else "mysql"
                ),
                "snapshot_only": bool(
                    ctx.get(
                        "snapshot_only"
                    )
                ),
            },
        }
    )

def build_dashboard_overview(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    bundle = load_dashboard_source_bundle(context)
    return {
        "company": {"record_count": len(bundle.get("companies", []))},
        "policy": {"record_count": len(bundle.get("policy", [])), "total_premium": safe_sum(bundle.get("policy", []), "premium")},
        "linkage": {"nodes": len(bundle.get("linkage_nodes", [])), "edges": len(bundle.get("linkage_edges", []))},
        "flood": {"record_count": len(bundle.get("flood", []))},
        "map": {"layer_count": len(bundle.get("map_layers", []))},
        "data_quality": bundle.get("data_quality", {}).get("summary", {}) if isinstance(bundle.get("data_quality"), dict) else {},
        "meta": {"generated_at": now_iso(), "degraded": bundle.get("meta", {}).get("degraded", False)},
    }

def build_dashboard_freshness(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sources = {}

    try:
        from utils import get_cache_file_path
    except Exception:
        get_cache_file_path = None

    for key, cache_key in SOURCE_CACHE_KEYS.items():
        payload = _load_cache_payload(cache_key)

        info = {
            "cache_key": cache_key,
            "status": "loaded" if payload is not None else "missing",
            "record_count": safe_count(payload),
            "checked_at": now_iso(),
        }

        if get_cache_file_path is not None:
            try:
                cache_path = get_cache_file_path(cache_key)
                file_meta = file_info(cache_path)
                info["file"] = file_meta
                info["exists"] = file_meta.get("exists", False)
            except Exception:
                info["exists"] = False

        sources[key] = info

    missing = [
        key
        for key, item in sources.items()
        if item.get("status") == "missing"
    ]

    degraded = bool(missing)

    return {
        "sources": sources,
        "summary": {
            "cache_count": len(sources),
            "loaded_cache_count": len(sources) - len(missing),
            "missing_cache_count": len(missing),
            "missing_cache": missing,
            "status": "Warning" if degraded else "Normal",
        },
        "meta": {
            "generated_at": now_iso(),
            "degraded": degraded,
            "source": "excel" if getattr(config, "USE_EXCEL_DATA_SOURCE", True) else "mysql",
        },
    }


def build_executive_dashboard(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    bundle = load_dashboard_source_bundle(context)
    summary = build_dashboard_summary(context)
    charts = build_chart_summary(context)
    tables = build_dashboard_tables(bundle)
    return {
        "summary_cards": summary.get("summary_cards", []),
        "kpis": summary.get("kpis", {}),
        "charts": charts.get("charts", {}),
        "tables": tables.get("tables", []),
        "top_companies": bundle.get("companies", [])[:10],
        "top_directors": bundle.get("directors", [])[:10],
        "risk_insights": build_dashboard_alerts(bundle),
        "meta": {"generated_at": now_iso(), "degraded": bundle.get("meta", {}).get("degraded", False)},
    }


def normalize_chart_payload(chart_id: str, title: str, chart_type: str, data: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    records = normalize_cache_payload_to_records(data, chart_id) if not isinstance(data, list) else data
    return {"chart_id": chart_id, "title": title, "chart_type": chart_type, "data": json_safe(records), "meta": {"record_count": len(records), **(meta or {})}}


def _count_by(records: List[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    counter = Counter(clean_text(record.get(field), "Unknown") for record in records or [] if isinstance(record, dict))
    return [{"label": key, "value": value} for key, value in counter.most_common(25)]


def build_policy_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    policy = load_policy_records()
    return {
        "policy_by_status": normalize_chart_payload("policy_by_status", "Policy by Status", "bar", _count_by(policy, "status_now")),
        "policy_by_product": normalize_chart_payload("policy_by_product", "Policy by Product", "bar", _count_by(policy, "product")),
    }


def build_company_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    companies = load_company_records()
    return {
        "companies_by_province": normalize_chart_payload("companies_by_province", "Companies by Province", "bar", _count_by(companies, "province")),
        "companies_by_risk": normalize_chart_payload("companies_by_risk", "Companies by Flood Risk", "donut", _count_by(companies, "flood_risk_level")),
    }


def build_linkage_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    linkage = load_linkage_records()
    return {
        "linkage_nodes": normalize_chart_payload("linkage_nodes", "Linkage Nodes", "summary", [{"label": "nodes", "value": len(linkage.get("nodes", []))}, {"label": "edges", "value": len(linkage.get("edges", []))}]),
    }

def build_flood_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    flood = load_flood_records()
    rainfall = load_rainfall_latest_records(context)
    waterlevel = load_waterlevel_latest_records(context)
    dam = load_dam_latest_records(context)
    prediction = load_prediction_latest_records(context)

    return {
        "flood_by_risk": normalize_chart_payload("flood_by_risk", "Flood by Risk", "bar", _count_by(flood, "risk_level")),
        "flood_by_source": normalize_chart_payload("flood_by_source", "Flood by Source", "bar", _count_by(flood, "source_type")),
        "runtime_risk_distribution": build_risk_distribution_chart(context),
        "province_comparison": build_province_comparison_chart(context),
        "station_ranking": build_station_ranking_chart(context),
        "rainfall_top5": normalize_chart_payload("rainfall_top5", "Rainfall Top 5", "bar", build_top_records(rainfall, ["latest_value", "rainfall_value", "rainfall_24h", "value"], 5, "rainfall")),
        "waterlevel_top5": normalize_chart_payload("waterlevel_top5", "Waterlevel Top 5", "bar", build_top_records(waterlevel, ["latest_value", "waterlevel_value", "water_level", "value"], 5, "waterlevel")),
        "reservoir_top5": normalize_chart_payload("reservoir_top5", "Reservoir Top 5", "bar", build_top_records(dam, ["latest_value", "storage_percent", "percent_storage", "value"], 5, "dam")),
        "prediction_by_risk": normalize_chart_payload("prediction_by_risk", "Prediction by Risk", "bar", _count_by(prediction, "risk_level")),
    }


def build_quality_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    quality = load_data_quality_payload(context)
    summary = quality.get("summary", {}) if isinstance(quality, dict) else {}
    severity = summary.get("by_severity", {}) if isinstance(summary, dict) else {}
    return {"data_quality_by_severity": normalize_chart_payload("data_quality_by_severity", "Data Quality by Severity", "bar", [{"label": key, "value": value} for key, value in severity.items()])}


def build_package_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    packages = list_packages(context).get("data", {}).get("packages", [])
    return {"packages_by_status": normalize_chart_payload("packages_by_status", "Packages by Status", "bar", _count_by(packages, "status"))}

def build_chart_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    charts: Dict[str, Any] = {}

    for builder in (
        build_policy_charts,
        build_company_charts,
        build_linkage_charts,
        build_flood_charts,
        build_quality_charts,
        build_package_charts,
    ):
        try:
            charts.update(builder(context))
        except Exception as exc:
            charts[f"{builder.__name__}_error"] = normalize_chart_payload(
                builder.__name__,
                builder.__name__,
                "error",
                [{"error": str(exc)}],
            )

    charts["risk_distribution"] = build_risk_distribution_chart(context)
    charts["province_comparison"] = build_province_comparison_chart(context)
    charts["station_ranking"] = build_station_ranking_chart(context)

    return {
        "charts": charts,
        "meta": {
            "chart_count": len(charts),
            "generated_at": now_iso(),
            "degraded": any(key.endswith("_error") for key in charts),
        },
    }

def build_dashboard_province_insights(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    prediction_records = load_prediction_latest_records(ctx)
    rainfall_records = load_rainfall_latest_records(ctx)
    waterlevel_records = load_waterlevel_latest_records(ctx)
    dam_records = load_dam_latest_records(ctx)

    prediction_risk_top3 = build_top_prediction_risk_provinces(prediction_records, limit=3)
    rainfall_top5 = build_top_records(
        rainfall_records,
        metric_keys=["latest_value", "rainfall_value", "rainfall_24h", "rainfall_mm", "value"],
        limit=5,
        mode="rainfall",
        label_field_candidates=["source_name", "station_name", "station_name_th", "province"],
    )
    waterlevel_top5 = build_top_records(
        waterlevel_records,
        metric_keys=["latest_value", "waterlevel_value", "water_level", "level", "value"],
        limit=5,
        mode="waterlevel",
        label_field_candidates=["source_name", "station_name", "station_name_th", "province"],
    )
    reservoir_top5 = build_top_records(
        dam_records,
        metric_keys=["latest_value", "storage_percent", "percent_storage", "storage_pct", "value"],
        limit=5,
        mode="dam",
        label_field_candidates=["source_name", "dam_name", "reservoir_name", "province"],
    )

    return {
        "top_prediction_risk_provinces": prediction_risk_top3,
        "rainfall_ranking": rainfall_top5,
        "waterlevel_ranking": waterlevel_top5,
        "reservoir_ranking": reservoir_top5,
        "prediction_risk_top3": prediction_risk_top3,
        "rainfall_top5": rainfall_top5,
        "waterlevel_top5": waterlevel_top5,
        "reservoir_top5": reservoir_top5,
        "behavior": {
            "prediction_risk_top3": "focus province + prediction mode",
            "rainfall_top5": "focus province + rainfall mode",
            "waterlevel_top5": "focus province + waterlevel mode",
            "reservoir_top5": "focus province + dam mode",
        },
        "meta": {
            "generated_at": now_iso(),
            "source": "excel" if getattr(config, "USE_EXCEL_DATA_SOURCE", True) else "mysql",
            "counts": {
                "prediction": len(prediction_records),
                "rainfall": len(rainfall_records),
                "waterlevel": len(waterlevel_records),
                "dam": len(dam_records),
            },
        },
    }


def get_dashboard_province_insights(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_dashboard_province_insights(context)
        return make_dashboard_response(
            payload,
            "Dashboard province insights loaded.",
            {
                "degraded": False,
                "cache_key": "dashboard_province_insights",
            },
        )
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def build_risk_distribution_chart(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    bundle = load_dashboard_source_bundle(ctx)

    records: List[Dict[str, Any]] = []
    records.extend(bundle.get("flood", []))
    records.extend(bundle.get("flood_prediction_latest", []))
    records.extend(bundle.get("flood_rainfall_latest", []))
    records.extend(bundle.get("flood_waterlevel_latest", []))
    records.extend(bundle.get("flood_dam_latest", []))

    counter = Counter(
        normalize_dashboard_risk(
            first_record_value(
                record,
                ["risk_level", "risk_status", "warning_level", "warning_level_predict", "flood_risk_level"],
                default="Unknown",
            )
        )
        for record in records
        if isinstance(record, dict)
    )

    labels = ["Critical", "Warning", "Watch", "Normal", "Unknown"]
    data = [counter.get(label, 0) for label in labels]

    return build_chart_payload(
        chart_id="risk_distribution",
        chart_type="doughnut",
        title="Flood Risk Distribution",
        labels=labels,
        datasets=[
            {
                "label": "Records",
                "data": data,
            }
        ],
        meta={
            "source": "dashboard_package_service",
            "record_count": len(records),
        },
    )


def get_risk_distribution_chart(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_risk_distribution_chart(context)
        return make_dashboard_response(payload, "Risk distribution chart loaded.", {"chart_id": "risk_distribution"})
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def build_province_comparison_chart(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    bundle = load_dashboard_source_bundle(ctx)

    records: List[Dict[str, Any]] = []
    records.extend(bundle.get("flood_prediction_latest", []))
    records.extend(bundle.get("flood_rainfall_latest", []))
    records.extend(bundle.get("flood_waterlevel_latest", []))
    records.extend(bundle.get("flood_dam_latest", []))

    province_counter = Counter(province_value(record) for record in records if isinstance(record, dict))
    top = province_counter.most_common(15)

    return build_chart_payload(
        chart_id="province_comparison",
        chart_type="bar",
        title="Province Comparison",
        labels=[item[0] for item in top],
        datasets=[
            {
                "label": "Flood Runtime Records",
                "data": [item[1] for item in top],
            }
        ],
        meta={
            "source": "dashboard_package_service",
            "record_count": len(records),
        },
    )


def get_province_comparison_chart(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_province_comparison_chart(context)
        return make_dashboard_response(payload, "Province comparison chart loaded.", {"chart_id": "province_comparison"})
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def build_station_ranking_chart(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    insights = build_dashboard_province_insights(ctx)

    rows = []
    rows.extend(insights.get("rainfall_top5", []))
    rows.extend(insights.get("waterlevel_top5", []))
    rows.extend(insights.get("reservoir_top5", []))

    rows = sorted(
        rows,
        key=lambda item: (
            to_number(item.get("risk_score"), 0) or 0,
            to_number(item.get("value"), 0) or 0,
        ),
        reverse=True,
    )[:15]

    return build_chart_payload(
        chart_id="station_ranking",
        chart_type="bar",
        title="Station / Reservoir Ranking",
        labels=[item.get("name") or item.get("province") for item in rows],
        datasets=[
            {
                "label": "Value",
                "data": [item.get("value", 0) for item in rows],
            },
            {
                "label": "Risk Score",
                "data": [item.get("risk_score", 0) for item in rows],
            },
        ],
        meta={
            "source": "dashboard_package_service",
            "record_count": len(rows),
        },
    )


def get_station_ranking_chart(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_station_ranking_chart(context)
        return make_dashboard_response(payload, "Station ranking chart loaded.", {"chart_id": "station_ranking"})
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)

def get_executive_dashboard(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_executive_dashboard(context)
        return make_dashboard_response(payload, "Executive dashboard loaded.", {"degraded": payload.get("meta", {}).get("degraded", False)})
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def get_dashboard_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_dashboard_summary(context)
        return make_dashboard_response(payload, "Dashboard summary loaded.", {"degraded": payload.get("meta", {}).get("degraded", False)})
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def get_dashboard_overview(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_dashboard_overview(context)
        return make_dashboard_response(payload, "Dashboard overview loaded.", {"degraded": payload.get("meta", {}).get("degraded", False)})
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def get_dashboard_freshness(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_dashboard_freshness(context)
        return make_dashboard_response(payload, "Dashboard freshness loaded.", {"degraded": payload.get("meta", {}).get("degraded", False)})
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def get_chart_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        payload = build_chart_summary(context)
        return make_dashboard_response(payload, "Chart summary loaded.", {"chart_count": payload.get("meta", {}).get("chart_count", 0), "degraded": payload.get("meta", {}).get("degraded", False)})
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def get_dashboard_charts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_chart_summary(context)


def normalize_package_request(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    request = payload if isinstance(payload, dict) else {}

    default_components = [
        "summary",
        "map",
        "charts",
        "tables",
        "data_quality",
        "prediction",
        "entity",
    ]

    raw_components = request.get("components") if isinstance(request.get("components"), list) else default_components
    components = sanitize_package_components(raw_components)
    components = [
        component
        for component in components
        if component in ALLOWED_PUBLIC_COMPONENTS
        or component in {"companies", "policy_summary", "linkage_graph", "map_layers"}
    ]

    if not components:
        components = default_components

    security_policy = dict(PACKAGE_SECURITY_OPTIONS)
    if isinstance(request.get("security"), dict):
        security_policy.update(request["security"])

    security_policy["public"] = True
    security_policy["remove_internal_paths"] = True
    security_policy["remove_debug_fields"] = True

    return {
        "package_name": clean_text(request.get("package_name") or request.get("name"), "TIPX Dashboard Package"),
        "description": clean_text(request.get("description")),
        "components": components,
        "security": security_policy,
        "scope": build_package_scope(request),
        "public": to_bool(request.get("public"), True),
        "expires_days": max(1, min(to_int(request.get("expires_days"), PACKAGE_DEFAULT_EXPIRE_DAYS), PACKAGE_MAX_EXPIRE_DAYS)),
        "filters": request.get("filters", {}) if isinstance(request.get("filters"), dict) else {},
        "force_refresh": to_bool(request.get("force_refresh"), False),
        "snapshot_only": True,
    }


def build_package_scope(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    request = payload if isinstance(payload, dict) else {}
    scope = request.get("scope") if isinstance(request.get("scope"), dict) else {}
    return {
        "companies": scope.get("companies") or request.get("companies") or [],
        "provinces": scope.get("provinces") or request.get("provinces") or [],
        "tax_ids": scope.get("tax_ids") or request.get("tax_ids") or [],
        "filters": scope.get("filters") if isinstance(scope.get("filters"), dict) else request.get("filters", {}) if isinstance(request.get("filters"), dict) else {},
    }

def _apply_package_scope(
    records: List[
        Dict[str, Any]
    ],
    scope: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not records:
        return []

    provinces = {
        clean_text_lower(value)
        for value
        in scope.get(
            "provinces",
            [],
        )
        if clean_text(value)
    }

    tax_ids = {
        normalize_tax_id(value)
        for value
        in scope.get(
            "tax_ids",
            [],
        )
        if normalize_tax_id(value)
    }

    company_names = {
        clean_text_lower(value)
        for value
        in scope.get(
            "companies",
            [],
        )
        if clean_text(value)
    }

    if (
        not provinces
        and not tax_ids
        and not company_names
    ):
        return list(records)

    filtered: List[
        Dict[str, Any]
    ] = []

    for record in records:
        if not isinstance(
            record,
            dict,
        ):
            continue

        record_provinces = {
            clean_text_lower(
                record.get(key)
            )
            for key in [
                "province",
                "province_model",
                "province_name_th",
                "company_province",
                "source_province",
                "target_province",
            ]
            if clean_text(
                record.get(key)
            )
        }

        record_tax_ids = {
            normalize_tax_id(
                record.get(key)
            )
            for key in [
                "tax_id_norm",
                "tax_id",
                "company_tax_id",
                "source_tax_id",
                "target_tax_id",
            ]
            if normalize_tax_id(
                record.get(key)
            )
        }

        record_company_names = {
            clean_text_lower(
                record.get(key)
            )
            for key in [
                "company_name",
                "name_th",
                "source_company_name",
                "target_company_name",
                "entity_name_th",
            ]
            if clean_text(
                record.get(key)
            )
        }

        if (
            provinces
            and provinces.isdisjoint(
                record_provinces
            )
        ):
            continue

        if (
            tax_ids
            and tax_ids.isdisjoint(
                record_tax_ids
            )
        ):
            continue

        if (
            company_names
            and company_names.isdisjoint(
                record_company_names
            )
        ):
            continue

        filtered.append(record)

    return filtered

def build_package_preview(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    request = normalize_package_request(payload)
    bundle = load_dashboard_source_bundle({"filters": request.get("filters", {})})
    scoped_companies = _apply_package_scope(bundle.get("companies", []), request.get("scope", {}))

    map_payload = bundle.get("map", {}) if isinstance(bundle.get("map"), dict) else {}
    map_layers = map_payload.get("layers", {}) if isinstance(map_payload, dict) else {}

    estimated_records = {
        "companies": len(scoped_companies) if scoped_companies else len(bundle.get("companies", [])),
        "policy": len(bundle.get("policy", [])),
        "linkage_nodes": len(bundle.get("linkage_nodes", [])),
        "linkage_edges": len(bundle.get("linkage_edges", [])),
        "flood": len(bundle.get("flood", [])),
        "rainfall_latest": len(bundle.get("flood_rainfall_latest", [])),
        "waterlevel_latest": len(bundle.get("flood_waterlevel_latest", [])),
        "dam_latest": len(bundle.get("flood_dam_latest", [])),
        "prediction": len(bundle.get("flood_prediction_latest", [])),
        "entity": len(bundle.get("uploaded_entity_latest", [])),
        "map_layers": len(map_layers) if isinstance(map_layers, dict) else safe_count(map_layers),
        "data_quality": safe_count(bundle.get("data_quality", {})),
        "tables": 7,
    }

    warnings = []

    if bundle.get("meta", {}).get("degraded"):
        warnings.append("Some dashboard sources are missing or empty; generated package may be degraded.")

    if "prediction" not in request["components"] and "flood_prediction_latest" not in request["components"]:
        warnings.append("prediction component not selected")

    if "entity" not in request["components"] and "uploaded_entity_latest" not in request["components"]:
        warnings.append("entity component not selected")

    return {
        "package_name": request["package_name"],
        "description": request["description"],
        "components": request["components"],
        "security_options": request["security"],
        "scope": request["scope"],
        "estimated_records": estimated_records,
        "warnings": warnings,
        "snapshot_policy": SNAPSHOT_ONLY_PACKAGE_POLICY,
        "meta": {
            "generated_at": now_iso(),
            "degraded": bool(warnings),
            "source": "cache_snapshot",
        },
    }


def preview_package(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        return make_package_response(build_package_preview(payload), "Package preview built.")
    except Exception as exc:
        return make_package_error(str(exc), exc.__class__.__name__)


def build_package_id(payload: Optional[Dict[str, Any]] = None) -> str:
    try:
        return generate_package_id("PKG")
    except Exception:
        return f"PKG_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

def build_package_meta(
    package_id: str,
    request: Dict[str, Any],
    snapshot: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    snapshot_payload = (
        snapshot
        if isinstance(snapshot, dict)
        else {}
    )

    meta = build_security_package_meta(
        package_id,
        request,
        snapshot_payload,
    )

    if not isinstance(meta, dict):
        meta = {}

    created_at = clean_text(
        meta.get("created_at"),
        default=now_iso(),
    )

    meta.update(
        {
            "package_id": package_id,
            "package_name": (
                request.get(
                    "package_name",
                    package_id,
                )
            ),
            "name": request.get(
                "package_name",
                package_id,
            ),
            "description": (
                request.get(
                    "description",
                    "",
                )
            ),
            "created_at": created_at,
            "updated_at": created_at,
            "status": "active",
            "enabled": True,
            "public": bool(
                request.get(
                    "public",
                    True,
                )
            ),
            "components": list(
                request.get(
                    "components",
                    [],
                )
            ),
            "record_counts": (
                collect_record_counts_from_snapshot(
                    snapshot_payload
                )
            ),
            "snapshot_id": (
                snapshot_payload.get(
                    "snapshot_id"
                )
            ),
            "checksum": (
                snapshot_payload.get(
                    "checksum",
                    "",
                )
            ),
            "checksum_components": list(
                PACKAGE_CHECKSUM_COMPONENT_KEYS
            ),
            "snapshot_policy": dict(
                SNAPSHOT_ONLY_PACKAGE_POLICY
            ),
        }
    )

    return json_safe(meta)

def build_package_snapshot(
    package_id: str,
    request: Optional[
        Dict[str, Any]
    ] = None,
    context: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    req = (
        normalize_package_request(
            request
        )
        if isinstance(request, dict)
        else normalize_package_request(
            context or {}
        )
    )

    ctx = normalize_context(
        context or {}
    )

    ctx["filters"] = dict(
        req.get(
            "filters",
            {},
        )
    )
    ctx["snapshot_only"] = True
    ctx["force_refresh"] = False

    if req.get("force_refresh"):
        rebuild_result = (
            rebuild_all_runtime_cache(
                force_refresh=True
            )
        )
    else:
        rebuild_result = {
            "rebuilt": False,
            "status": "skipped",
            "reason": (
                "force_refresh_false"
            ),
            "finished_at": now_iso(),
        }

    bundle = (
        load_dashboard_source_bundle(
            ctx
        )
    )

    scope = (
        req.get("scope", {})
        if isinstance(
            req.get("scope"),
            dict,
        )
        else {}
    )

    for scoped_key in [
        "companies",
        "policy",
        "policy_company_summary",
        "linkage_edges",
        "flood",
        "flood_rainfall_latest",
        "flood_waterlevel_latest",
        "flood_dam_latest",
        "flood_prediction_latest",
        "uploaded_entity_latest",
        "spatial",
    ]:
        if isinstance(
            bundle.get(scoped_key),
            list,
        ):
            bundle[scoped_key] = (
                _apply_package_scope(
                    bundle[scoped_key],
                    scope,
                )
            )

    selected_components = set(
        req.get(
            "components",
            [],
        )
    )

    def selected(
        *component_names: str,
    ) -> bool:
        return any(
            component_name
            in selected_components
            for component_name
            in component_names
        )

    summary = build_dashboard_summary(
        ctx
    )
    dashboard = (
        build_executive_dashboard(
            ctx
        )
    )
    overview = (
        build_dashboard_overview(
            ctx
        )
    )
    province_insights = (
        build_dashboard_province_insights(
            ctx
        )
    )
    charts = build_chart_summary(
        ctx
    )
    tables = build_dashboard_tables(
        bundle
    )
    map_payload = load_map_payload(
        ctx,
        public=False,
    )
    public_map_payload = (
        load_map_payload(
            ctx,
            public=True,
        )
    )
    data_quality_payload = (
        load_data_quality_payload(
            ctx
        )
    )

    linkage_graph = {
        "nodes": bundle.get(
            "linkage_nodes",
            [],
        ),
        "edges": bundle.get(
            "linkage_edges",
            [],
        ),
        "summary": {
            "node_count": len(
                bundle.get(
                    "linkage_nodes",
                    [],
                )
            ),
            "edge_count": len(
                bundle.get(
                    "linkage_edges",
                    [],
                )
            ),
        },
    }

    if ctx.get("snapshot_only"):
        flood_summary = (
            extract_payload_data(
                _load_cache_payload(
                    "flood_summary"
                )
                or {},
                {},
            )
        )
    else:
        flood_summary = (
            unwrap_service_payload(
                safe_call_service(
                    get_flood_summary,
                    fallback={},
                    context=ctx,
                ),
                {},
            )
        )

    prediction_records = (
        bundle.get(
            "flood_prediction_latest",
            [],
        )
    )
    prediction_map = bundle.get(
        "flood_prediction_map",
        {},
    )
    entity_records = bundle.get(
        "uploaded_entity_latest",
        [],
    )

    prediction_payload = (
        normalize_public_prediction_payload(
            prediction_records,
            prediction_map,
        )
    )
    entity_payload = (
        normalize_public_entity_payload(
            entity_records
        )
    )

    data: Dict[
        str,
        Any,
    ] = {}

    if selected("summary"):
        data.update(
            {
                "summary": summary,
                "dashboard": dashboard,
                "overview": overview,
                "province_insights": (
                    province_insights
                ),
            }
        )

    if selected("companies"):
        data["companies"] = (
            bundle.get(
                "companies",
                [],
            )
        )

    if selected(
        "policy_summary"
    ):
        data["policy_summary"] = (
            bundle.get(
                "policy_company_summary",
                [],
            )
        )

    if selected(
        "policy_table"
    ):
        data["policy_table"] = (
            bundle.get(
                "policy",
                [],
            )
        )

    if selected(
        "linkage_graph"
    ):
        data["linkage_graph"] = (
            linkage_graph
        )

    if selected(
        "linkage_lines"
    ):
        data["linkage_lines"] = (
            bundle.get(
                "linkage_edges",
                [],
            )
        )

    if selected(
        "flood_summary"
    ):
        data["flood_summary"] = (
            flood_summary
        )

    if selected(
        "map",
        "map_layers",
    ):
        data["map"] = (
            public_map_payload
        )
        data["map_layers"] = (
            map_payload
        )

    if selected("charts"):
        data["charts"] = charts

    if selected("tables"):
        data["tables"] = tables

    if selected(
        "data_quality"
    ):
        data["data_quality"] = (
            data_quality_payload
        )

    if selected(
        "filter_options"
    ):
        data["filter_options"] = (
            bundle.get(
                "filter_context",
                {},
            )
        )

    if selected(
        "prediction",
        "flood_prediction",
        "flood_prediction_latest",
        "flood_prediction_map",
    ):
        data["prediction"] = (
            prediction_payload.get(
                "records",
                [],
            )
        )
        data["flood_prediction"] = (
            prediction_payload.get(
                "records",
                [],
            )
        )
        data[
            "flood_prediction_latest"
        ] = prediction_payload.get(
            "records",
            [],
        )
        data[
            "flood_prediction_map"
        ] = prediction_payload.get(
            "map",
            {},
        )

    if selected(
        "entity",
        "uploaded_entity",
        "uploaded_entity_latest",
    ):
        data["entity"] = (
            entity_payload.get(
                "records",
                [],
            )
        )
        data["uploaded_entity"] = (
            entity_payload.get(
                "records",
                [],
            )
        )
        data[
            "uploaded_entity_latest"
        ] = entity_payload.get(
            "records",
            [],
        )

    snapshot = {
        "package_id": package_id,
        "snapshot_id": (
            f"{package_id}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ),
        "request": req,
        "data": data,
        "sources": {
            "cache_keys": (
                SOURCE_CACHE_KEYS
            ),
            "bundle_meta": (
                bundle.get(
                    "meta",
                    {},
                )
            ),
            "rebuild": rebuild_result,
        },
        "created_at": now_iso(),
        "snapshot_policy": dict(
            SNAPSHOT_ONLY_PACKAGE_POLICY
        ),
        "checksum_components": list(
            PACKAGE_CHECKSUM_COMPONENT_KEYS
        ),
    }

    for key in [
        "summary",
        "dashboard",
        "overview",
        "province_insights",
        "map",
        "map_layers",
        "charts",
        "tables",
        "data_quality",
        "prediction",
        "entity",
    ]:
        if key in data:
            snapshot[key] = data[key]

    checksum_payload = {
        key: data.get(key)
        for key
        in PACKAGE_CHECKSUM_COMPONENT_KEYS
        if key in data
    }

    snapshot["checksum"] = (
        create_package_checksum(
            {
                "package_id": (
                    package_id
                ),
                "data": (
                    checksum_payload
                ),
                "created_at": (
                    snapshot[
                        "created_at"
                    ]
                ),
            }
        )
    )

    return json_safe(snapshot)

def build_public_data(
    snapshot: Dict[str, Any],
    policy: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    active_policy = dict(
        PACKAGE_SECURITY_OPTIONS
    )

    if isinstance(policy, dict):
        active_policy.update(
            policy
        )

    active_policy["public"] = True
    active_policy[
        "remove_internal_paths"
    ] = True
    active_policy[
        "remove_debug_fields"
    ] = True

    data = (
        snapshot.get(
            "data",
            {},
        )
        if isinstance(
            snapshot.get("data"),
            dict,
        )
        else {}
    )

    selected_components = set(
        (
            snapshot.get(
                "request",
                {},
            )
            if isinstance(
                snapshot.get("request"),
                dict,
            )
            else {}
        ).get(
            "components",
            [],
        )
        or []
    )

    def selected(
        *component_names: str,
    ) -> bool:
        return any(
            component_name
            in selected_components
            for component_name
            in component_names
        )

    public_data_section: Dict[
        str,
        Any,
    ] = {}

    for key, aliases in {
        "summary": (
            "summary",
        ),
        "companies": (
            "companies",
        ),
        "policy_summary": (
            "policy_summary",
        ),
        "policy_table": (
            "policy_table",
        ),
        "linkage_graph": (
            "linkage_graph",
        ),
        "linkage_lines": (
            "linkage_lines",
        ),
        "flood_summary": (
            "flood_summary",
        ),
        "charts": (
            "charts",
        ),
        "tables": (
            "tables",
        ),
        "data_quality": (
            "data_quality",
        ),
        "filter_options": (
            "filter_options",
        ),
    }.items():
        if (
            selected(*aliases)
            and key in data
        ):
            public_data_section[
                key
            ] = data[key]

    if selected("summary"):
        for key in [
            "dashboard",
            "overview",
            "province_insights",
        ]:
            if key in data:
                public_data_section[
                    key
                ] = data[key]

    if selected(
        "map",
        "map_layers",
    ):
        public_data_section[
            "map"
        ] = normalize_public_map_payload(
            data.get(
                "map",
                {},
            )
        )

        public_data_section[
            "map_layers"
        ] = normalize_public_map_payload(
            data.get(
                "map_layers",
                data.get(
                    "map",
                    {},
                ),
            )
        )

    if selected(
        "prediction",
        "flood_prediction",
        "flood_prediction_latest",
        "flood_prediction_map",
    ):
        prediction_payload = (
            normalize_public_prediction_payload(
                data.get(
                    "prediction",
                    [],
                ),
                data.get(
                    "flood_prediction_map",
                    {},
                ),
            )
        )

        public_data_section[
            "prediction"
        ] = prediction_payload.get(
            "records",
            [],
        )
        public_data_section[
            "flood_prediction"
        ] = prediction_payload.get(
            "records",
            [],
        )
        public_data_section[
            "flood_prediction_latest"
        ] = prediction_payload.get(
            "records",
            [],
        )
        public_data_section[
            "flood_prediction_map"
        ] = prediction_payload.get(
            "map",
            {},
        )

    if selected(
        "entity",
        "uploaded_entity",
        "uploaded_entity_latest",
    ):
        entity_payload = (
            normalize_public_entity_payload(
                data.get(
                    "entity",
                    [],
                )
            )
        )

        public_data_section[
            "entity"
        ] = entity_payload.get(
            "records",
            [],
        )
        public_data_section[
            "uploaded_entity"
        ] = entity_payload.get(
            "records",
            [],
        )
        public_data_section[
            "uploaded_entity_latest"
        ] = entity_payload.get(
            "records",
            [],
        )

    public_payload: Dict[
        str,
        Any,
    ] = {
        "package_meta": {
            "package_id": (
                snapshot.get(
                    "package_id"
                )
            ),
            "snapshot_id": (
                snapshot.get(
                    "snapshot_id"
                )
            ),
            "checksum": (
                snapshot.get(
                    "checksum"
                )
            ),
            "checksum_components": list(
                PACKAGE_CHECKSUM_COMPONENT_KEYS
            ),
            "components": sorted(
                selected_components
            ),
        },
        "data": (
            public_data_section
        ),
        "meta": {
            "package_id": (
                snapshot.get(
                    "package_id"
                )
            ),
            "snapshot_id": (
                snapshot.get(
                    "snapshot_id"
                )
            ),
            "generated_at": now_iso(),
            "read_only": True,
            "snapshot_only": True,
            "source": (
                "package_snapshot"
            ),
            "public_viewer_source": (
                "public_data_json_only"
            ),
            "package_reads_live_excel": (
                False
            ),
            "public_viewer_reads_raw_cache": (
                False
            ),
            "public_viewer_reads_raw_excel": (
                False
            ),
        },
    }

    for key, value in (
        public_data_section.items()
    ):
        public_payload[key] = value

    cleaned_payload = (
        remove_snapshot_internal_keys(
            public_payload
        )
    )

    return sanitize_public_payload(
        cleaned_payload,
        active_policy,
    )

def write_package_files(
    package_id: str,
    meta: Dict[str, Any],
    snapshot: Dict[str, Any],
    public_data: Dict[str, Any],
) -> Dict[str, Any]:
    clean_id = _safe_package_id(
        package_id
    )

    if not clean_id:
        raise ValueError(
            "Invalid package_id"
        )

    root = ensure_package_dir()

    final_folder = (
        get_package_folder(
            clean_id
        )
    )

    staging_folder = (
        root
        / f".{clean_id}.staging"
    )

    if final_folder.exists():
        raise FileExistsError(
            (
                "Package already exists: "
                f"{clean_id}"
            )
        )

    if staging_folder.exists():
        shutil.rmtree(
            staging_folder
        )

    staging_folder.mkdir(
        parents=True,
        exist_ok=False,
    )

    data_section = (
        public_data.get(
            "data",
            {},
        )
        if isinstance(
            public_data.get("data"),
            dict,
        )
        else {}
    )

    selected_components = set(
        meta.get(
            "components",
            [],
        )
        or []
    )

    results: Dict[
        str,
        Dict[str, Any],
    ] = {}

    def selected(
        *component_names: str,
    ) -> bool:
        return any(
            component_name
            in selected_components
            for component_name
            in component_names
        )

    def write_component(
        result_key: str,
        filename: str,
        component_payload: Any,
    ) -> None:
        result = (
            write_json_file_safe(
                staging_folder
                / filename,
                component_payload,
            )
        )

        results[
            result_key
        ] = result

        if not result.get(
            "written"
        ):
            raise OSError(
                (
                    "Failed to write "
                    "package file: "
                    f"{filename}"
                )
            )

    try:
        write_component(
            "meta",
            PACKAGE_META_FILENAME,
            meta,
        )
        write_component(
            "snapshot",
            PACKAGE_SNAPSHOT_FILENAME,
            snapshot,
        )
        write_component(
            "public_data",
            PACKAGE_PUBLIC_DATA_FILENAME,
            public_data,
        )

        component_files = [
            (
                "summary",
                (
                    "summary",
                ),
                "summary.json",
                data_section.get(
                    "summary",
                    {},
                ),
            ),
            (
                "map",
                (
                    "map",
                    "map_layers",
                ),
                "map.json",
                data_section.get(
                    "map",
                    data_section.get(
                        "map_layers",
                        {},
                    ),
                ),
            ),
            (
                "charts",
                (
                    "charts",
                ),
                "charts.json",
                data_section.get(
                    "charts",
                    {},
                ),
            ),
            (
                "tables",
                (
                    "tables",
                ),
                "tables.json",
                data_section.get(
                    "tables",
                    {},
                ),
            ),
            (
                "data_quality",
                (
                    "data_quality",
                ),
                "data_quality.json",
                data_section.get(
                    "data_quality",
                    {},
                ),
            ),
        ]

        for (
            result_key,
            aliases,
            filename,
            component_payload,
        ) in component_files:
            if selected(
                *aliases
            ):
                write_component(
                    result_key,
                    filename,
                    component_payload,
                )

        if selected(
            "prediction",
            "flood_prediction",
            "flood_prediction_latest",
            "flood_prediction_map",
        ):
            write_component(
                "prediction",
                "prediction.json",
                {
                    "records": (
                        data_section.get(
                            "prediction",
                            [],
                        )
                    ),
                    "map": (
                        data_section.get(
                            "flood_prediction_map",
                            {},
                        )
                    ),
                    "meta": {
                        "generated_at": (
                            now_iso()
                        ),
                        "snapshot_only": (
                            True
                        ),
                    },
                },
            )

            write_component(
                "prediction_map",
                "prediction_map.json",
                data_section.get(
                    "flood_prediction_map",
                    {},
                ),
            )

        if selected(
            "entity",
            "uploaded_entity",
            "uploaded_entity_latest",
        ):
            write_component(
                "entity",
                "entity.json",
                {
                    "records": (
                        data_section.get(
                            "entity",
                            [],
                        )
                    ),
                    "meta": {
                        "generated_at": (
                            now_iso()
                        ),
                        "snapshot_only": (
                            True
                        ),
                        "displayable_only": (
                            True
                        ),
                    },
                },
            )

        viewer_dir = ensure_dir(
            staging_folder
            / PACKAGE_EXTERNAL_VIEWER_DIRNAME
        )

        viewer_data_dir = (
            ensure_dir(
                viewer_dir / "data"
            )
        )

        viewer_data_result = (
            write_json_file_safe(
                viewer_data_dir
                / PACKAGE_PUBLIC_DATA_FILENAME,
                public_data,
            )
        )

        results[
            "external_viewer_data"
        ] = viewer_data_result

        if not viewer_data_result.get(
            "written"
        ):
            raise OSError(
                (
                    "Failed to write "
                    "external viewer data"
                )
            )

        write_text(
            viewer_dir
            / "index.html",
            build_external_viewer_html(
                meta
            ),
        )

        results[
            "external_viewer_html"
        ] = {
            "written": True,
            "name": (
                f"{PACKAGE_EXTERNAL_VIEWER_DIRNAME}"
                "/index.html"
            ),
        }

        access_log_path = (
            staging_folder
            / "access_log.jsonl"
        )

        write_text(
            access_log_path,
            "",
        )

        results["access_log"] = {
            "written": True,
            "name": (
                access_log_path.name
            ),
            "size": 0,
        }

        if selected(
            "tables",
            "companies",
            "policy_summary",
            "policy_table",
            "linkage_lines",
        ):
            exports_dir = ensure_dir(
                staging_folder
                / PACKAGE_EXPORT_DIRNAME
            )

            tables_payload = (
                snapshot.get(
                    "data",
                    {},
                ).get(
                    "tables",
                    {},
                )
            )

            table_items = (
                tables_payload.get(
                    "tables",
                    [],
                )
                if (
                    isinstance(
                        tables_payload,
                        dict,
                    )
                    and isinstance(
                        tables_payload.get(
                            "tables"
                        ),
                        list,
                    )
                )
                else []
            )

            export_files: List[
                str
            ] = []

            for table in table_items:
                if not isinstance(
                    table,
                    dict,
                ):
                    continue

                table_id = safe_slug(
                    table.get(
                        "table_id"
                    ),
                    "table",
                )

                records = (
                    table.get(
                        "records",
                        [],
                    )
                    if isinstance(
                        table.get(
                            "records"
                        ),
                        list,
                    )
                    else []
                )

                records = (
                    apply_export_field_policy_to_records(
                        records,
                        security_options=(
                            meta.get(
                                "security",
                                {},
                            )
                        ),
                    )
                )

                export_path = (
                    exports_dir
                    / f"{table_id}.xlsx"
                )

                write_excel(
                    export_path,
                    {
                        table_id[:31]: (
                            pd.DataFrame(
                                records
                            )
                        ),
                    },
                )

                export_files.append(
                    (
                        f"{PACKAGE_EXPORT_DIRNAME}"
                        f"/{export_path.name}"
                    )
                )

            results["exports"] = {
                "written": True,
                "name": (
                    PACKAGE_EXPORT_DIRNAME
                ),
                "count": len(
                    export_files
                ),
                "files": export_files,
            }

        os.replace(
            staging_folder,
            final_folder,
        )

        return results

    except Exception:
        if staging_folder.exists():
            shutil.rmtree(
                staging_folder,
                ignore_errors=True,
            )

        raise

def write_package_index(index: Dict[str, Any]) -> Path:
    return write_json(_package_root() / PACKAGE_INDEX_FILENAME, json_safe(index))

def update_export_history(
    meta: Dict[str, Any],
    files: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    coordination_lock = (
        _package_root()
        / (
            f".{PACKAGE_INDEX_FILENAME}"
            ".update"
        )
    )

    with file_write_lock(
        coordination_lock,
        timeout_seconds=30.0,
        stale_seconds=300.0,
    ):
        index = load_package_index()

        existing_packages = (
            index.get(
                "packages",
                [],
            )
            if (
                isinstance(index, dict)
                and isinstance(
                    index.get(
                        "packages"
                    ),
                    list,
                )
            )
            else []
        )

        packages = [
            package
            for package
            in existing_packages
            if (
                isinstance(
                    package,
                    dict,
                )
                and package.get(
                    "package_id"
                )
                != meta.get(
                    "package_id"
                )
            )
        ]

        file_summary: Dict[
            str,
            Any,
        ] = {}

        for key, value in (
            files
            or {}
        ).items():
            if not isinstance(
                value,
                dict,
            ):
                continue

            file_summary[key] = {
                summary_key: value.get(
                    summary_key
                )
                for summary_key in [
                    "name",
                    "size",
                    "count",
                    "files",
                ]
                if value.get(
                    summary_key
                )
                is not None
            }

        entry = {
            "package_id": (
                meta.get(
                    "package_id"
                )
            ),
            "name": meta.get(
                "name"
            ),
            "status": meta.get(
                "status",
                "active",
            ),
            "enabled": meta.get(
                "enabled",
                True,
            ),
            "created_at": (
                meta.get(
                    "created_at"
                )
            ),
            "updated_at": (
                meta.get(
                    "updated_at"
                )
            ),
            "expires_at": (
                meta.get(
                    "expires_at"
                )
            ),
            "components": (
                meta.get(
                    "components",
                    [],
                )
            ),
            "record_counts": (
                meta.get(
                    "record_counts",
                    {},
                )
            ),
            "files": file_summary,
        }

        packages.insert(
            0,
            entry,
        )

        updated_index = {
            "packages": packages,
            "updated_at": now_iso(),
            "total": len(packages),
        }

        write_package_index(
            updated_index
        )

        return updated_index
    
def build_download_info(
    package_id: str,
    context: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    clean_id = _safe_package_id(
        package_id
    )

    if not clean_id:
        return {
            "package_id": "",
            "download_available": False,
            "download_ready": False,
            "file_path": None,
            "zip_path": None,
            "files": [],
            "meta": {
                "file_count": 0,
                "snapshot_only": True,
                "reason": (
                    "invalid_package_id"
                ),
            },
        }

    folder = get_package_folder(
        clean_id
    )
    zip_path = get_package_zip_path(
        clean_id
    )

    files: List[
        Dict[str, Any]
    ] = []

    if (
        not folder.exists()
        or not folder.is_dir()
    ):
        return {
            "package_id": clean_id,
            "download_available": False,
            "download_ready": False,
            "file_path": None,
            "zip_path": str(
                zip_path
            ),
            "files": [],
            "meta": {
                "file_count": 0,
                "snapshot_only": True,
                "reason": (
                    "package_not_found"
                ),
            },
        }

    for item in sorted(
        folder.rglob("*")
    ):
        if not item.is_file():
            continue

        files.append(
            {
                "name": (
                    item.relative_to(
                        folder
                    ).as_posix()
                ),
                "size": (
                    item.stat().st_size
                ),
            }
        )

    latest_package_mtime = max(
        (
            item.stat().st_mtime
            for item
            in folder.rglob("*")
            if item.is_file()
        ),
        default=0,
    )

    if (
        not zip_path.exists()
        or zip_path.stat().st_mtime
        < latest_package_mtime
    ):
        create_zip_from_folder(
            folder=folder,
            zip_path=zip_path,
            include_root_folder=True,
        )

    download_ready = bool(
        zip_path.exists()
        and zip_path.is_file()
    )

    return {
        "package_id": clean_id,
        "download_available": (
            download_ready
        ),
        "download_ready": (
            download_ready
        ),
        "file_path": (
            str(zip_path)
            if download_ready
            else None
        ),
        "path": (
            str(zip_path)
            if download_ready
            else None
        ),
        "zip_path": str(
            zip_path
        ),
        "file_info": file_info(
            zip_path
        ),
        "files": files,
        "meta": {
            "file_count": len(
                files
            ),
            "snapshot_only": True,
        },
    }

def generate_package(
    payload: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    package_id = ""

    try:
        request = (
            normalize_package_request(
                payload
            )
        )

        package_id = build_package_id(
            request
        )

        if not _safe_package_id(
            package_id
        ):
            raise ValueError(
                (
                    "Invalid generated "
                    "package_id"
                )
            )

        snapshot = (
            build_package_snapshot(
                package_id,
                request,
                request,
            )
        )

        meta = build_package_meta(
            package_id,
            request,
            snapshot,
        )

        public_data = build_public_data(
            snapshot,
            request.get(
                "security",
                {},
            ),
        )

        files = write_package_files(
            package_id,
            meta,
            snapshot,
            public_data,
        )

        download = build_download_info(
            package_id
        )

        if not download.get(
            "download_ready"
        ):
            raise OSError(
                (
                    "Package ZIP could "
                    "not be created"
                )
            )

        zip_info = download.get(
            "file_info",
            {},
        )

        files["zip"] = {
            "written": bool(
                download.get(
                    "download_ready"
                )
            ),
            "name": (
                zip_info.get("name")
            ),
            "size": (
                zip_info.get(
                    "size_bytes"
                )
            ),
        }

        index = update_export_history(
            meta,
            files,
        )

        rebuild_result = (
            snapshot.get(
                "sources",
                {},
            ).get(
                "rebuild",
                {},
            )
            if isinstance(
                snapshot.get(
                    "sources"
                ),
                dict,
            )
            else {}
        )

        degraded = bool(
            snapshot.get(
                "sources",
                {},
            )
            .get(
                "bundle_meta",
                {},
            )
            .get(
                "degraded",
                False,
            )
            or rebuild_result.get(
                "status"
            )
            == "degraded"
        )

        return make_package_response(
            {
                "generated": True,
                "package_id": (
                    package_id
                ),
                "snapshot_id": (
                    snapshot.get(
                        "snapshot_id"
                    )
                ),
                "meta": (
                    build_safe_public_meta(
                        meta
                    )
                ),
                "files": files,
                "download": download,
                "rebuild": {
                    "rebuilt": (
                        rebuild_result.get(
                            "rebuilt",
                            False,
                        )
                    ),
                    "status": (
                        rebuild_result.get(
                            "status",
                            "skipped",
                        )
                    ),
                    "phase_count": (
                        rebuild_result.get(
                            "phase_count",
                            0,
                        )
                    ),
                    "failed_count": (
                        rebuild_result.get(
                            "failed_count",
                            0,
                        )
                    ),
                    "degraded_count": (
                        rebuild_result.get(
                            "degraded_count",
                            0,
                        )
                    ),
                    "finished_at": (
                        rebuild_result.get(
                            "finished_at"
                        )
                    ),
                },
                "index": {
                    "total": index.get(
                        "total",
                        0,
                    ),
                    "updated_at": (
                        index.get(
                            "updated_at"
                        )
                    ),
                },
                "public_data": {
                    "components": (
                        request.get(
                            "components",
                            [],
                        )
                    ),
                    "has_summary": (
                        "summary"
                        in public_data
                    ),
                    "has_map": (
                        "map"
                        in public_data
                    ),
                    "prediction_count": len(
                        public_data.get(
                            "prediction",
                            [],
                        )
                        if isinstance(
                            public_data.get(
                                "prediction"
                            ),
                            list,
                        )
                        else []
                    ),
                    "entity_count": len(
                        public_data.get(
                            "entity",
                            [],
                        )
                        if isinstance(
                            public_data.get(
                                "entity"
                            ),
                            list,
                        )
                        else []
                    ),
                },
            },
            "Package generated.",
            {
                "degraded": degraded,
                "package_source": (
                    "cache_snapshot"
                ),
                "snapshot_only": True,
                "public_viewer_source": (
                    "public_data_json_only"
                ),
            },
        )

    except Exception as exc:
        if package_id:
            folder = (
                get_package_folder(
                    package_id
                )
            )
            zip_path = (
                get_package_zip_path(
                    package_id
                )
            )

            if (
                folder.exists()
                and folder.is_dir()
            ):
                shutil.rmtree(
                    folder,
                    ignore_errors=True,
                )

            if (
                zip_path.exists()
                and zip_path.is_file()
            ):
                zip_path.unlink(
                    missing_ok=True
                )

        return make_package_error(
            message=str(exc),
            error_type=(
                exc.__class__.__name__
            ),
            status_code=500,
        )

def load_package_index() -> Dict[str, Any]:
    return read_json_file_safe(_package_root() / PACKAGE_INDEX_FILENAME, default={"packages": [], "total": 0}) or {"packages": [], "total": 0}


def list_packages(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    index = load_package_index()
    packages = [sanitize_public_payload(pkg, {"public": True}) for pkg in index.get("packages", []) if isinstance(pkg, dict)]
    page_result = apply_search_sort_pagination(packages, normalize_context(context), searchable_fields=["package_id", "name", "status"])
    return make_package_response({"packages": page_result.get("records", packages), "total": page_result.get("total", len(packages)), "page": page_result.get("page", 1), "page_size": page_result.get("page_size", len(packages) or 1)}, "Packages loaded.")


def get_package_meta_from_disk(package_id: str) -> Dict[str, Any]:
    clean_id = _safe_package_id(package_id)
    if not clean_id:
        return {}
    return read_json_file_safe(get_package_file(clean_id, PACKAGE_META_FILENAME), default={}) or {}


def get_package_snapshot_from_disk(package_id: str) -> Dict[str, Any]:
    clean_id = _safe_package_id(package_id)
    if not clean_id:
        return {}
    return read_json_file_safe(get_package_file(clean_id, PACKAGE_SNAPSHOT_FILENAME), default={}) or {}


def get_public_data_from_disk(package_id: str) -> Dict[str, Any]:
    clean_id = _safe_package_id(package_id)
    if not clean_id:
        return {}
    return read_json_file_safe(get_package_file(clean_id, PACKAGE_PUBLIC_DATA_FILENAME), default={}) or {}


def get_package_detail(package_id: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = get_package_meta_from_disk(package_id)
    if not meta:
        return make_package_error("Package not found.", "PackageNotFound", 404, "package_id", {"package_id": _safe_package_id(package_id)})
    snapshot = get_package_snapshot_from_disk(package_id)
    return make_package_response({"package_id": _safe_package_id(package_id), "meta": sanitize_public_payload(meta), "snapshot_summary": collect_record_counts_from_snapshot(snapshot), "download": build_download_info(package_id)}, "Package detail loaded.")


def get_package_download_info(package_id: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = get_package_meta_from_disk(package_id)
    if not meta:
        return make_package_error("Package not found.", "PackageNotFound", 404, "package_id", {"package_id": _safe_package_id(package_id)})
    return make_package_response(build_download_info(package_id, context), "Package download info loaded.")


def disable_package(package_id: str, context: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = get_package_meta_from_disk(package_id)
    if not meta:
        return make_package_error("Package not found.", "PackageNotFound", 404, "package_id", {"package_id": _safe_package_id(package_id)})
    meta.update({"enabled": False, "status": "disabled", "updated_at": now_iso()})
    write_json_file_safe(get_package_file(package_id, PACKAGE_META_FILENAME), meta)
    update_export_history(meta)
    return make_package_response({"package_id": _safe_package_id(package_id), "disabled": True, "meta": sanitize_public_payload(meta)}, "Package disabled.")


def delete_package(package_id: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = get_package_meta_from_disk(package_id)
    if not meta:
        return make_package_error("Package not found.", "PackageNotFound", 404, "package_id", {"package_id": _safe_package_id(package_id)})
    meta.update({"enabled": False, "status": "deleted", "deleted_at": now_iso(), "updated_at": now_iso()})
    write_json_file_safe(get_package_file(package_id, PACKAGE_META_FILENAME), meta)
    update_export_history(meta)
    return make_package_response({"package_id": _safe_package_id(package_id), "deleted": True, "physical_delete": False}, "Package marked deleted.")


def public_package_exists(package_id: str) -> bool:
    return bool(get_package_meta_from_disk(package_id))


def public_package_is_enabled(package_id: str) -> bool:
    meta = get_package_meta_from_disk(package_id)
    return bool(meta and meta.get("enabled", True) and clean_text_lower(meta.get("status", "active")) == "active")


def load_public_package_file(package_id: str, component: str) -> Any:
    clean_component = clean_text_lower(component)

    component_aliases = {
        "map_layers": "map",
        "flood_prediction": "prediction",
        "flood_prediction_latest": "prediction",
        "uploaded_entity": "entity",
        "uploaded_entity_latest": "entity",
    }

    clean_component = component_aliases.get(clean_component, clean_component)

    if clean_component not in ALLOWED_PUBLIC_COMPONENTS and clean_component != "access_log":
        return None

    filename = PUBLIC_COMPONENT_FILES.get(clean_component)

    if not filename:
        return None

    return read_json_file_safe(get_package_file(package_id, filename), default=None)


def sanitize_public_component(component: Any, policy: Optional[Dict[str, Any]] = None) -> Any:
    active_policy = dict(PACKAGE_SECURITY_OPTIONS)
    if isinstance(policy, dict):
        active_policy.update(policy)
    active_policy["public"] = True
    return sanitize_public_payload(component, active_policy)


def public_component_response(
    package_id: str,
    component: str,
    context: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    meta = get_package_meta_from_disk(
        package_id
    )

    if not meta:
        return make_package_error(
            "Package not found.",
            "PackageNotFound",
            404,
            "package_id",
            {
                "package_id": (
                    _safe_package_id(
                        package_id
                    )
                )
            },
        )

    clean_component = (
        clean_text_lower(
            component
        )
    )

    component_aliases = {
        "map_layers": "map",
        "flood_prediction": (
            "prediction"
        ),
        "flood_prediction_latest": (
            "prediction"
        ),
        "flood_prediction_map": (
            "prediction"
        ),
        "uploaded_entity": "entity",
        "uploaded_entity_latest": (
            "entity"
        ),
    }

    canonical_component = (
        component_aliases.get(
            clean_component,
            clean_component,
        )
    )

    selected_components = set(
        meta.get(
            "components",
            [],
        )
        or []
    )

    selected_canonical = {
        component_aliases.get(
            item,
            item,
        )
        for item
        in selected_components
    }

    if (
        canonical_component
        not in {
            "meta",
            "data",
        }
        and canonical_component
        not in selected_canonical
    ):
        return make_package_error(
            (
                "Package component "
                "was not selected."
            ),
            (
                "PackageComponentNotSelected"
            ),
            404,
            "component",
            {
                "package_id": (
                    _safe_package_id(
                        package_id
                    )
                ),
                "component": component,
            },
        )

    token = (
        clean_text(
            context.get("token")
        )
        if isinstance(
            context,
            dict,
        )
        else ""
    )

    access_meta = dict(meta)

    access_meta[
        "components"
    ] = sorted(
        selected_canonical
        | {
            "meta",
            "data",
        }
    )

    access = public_access_allowed(
        access_meta,
        component=(
            canonical_component
        ),
        token=token,
    )

    if not access.get("allowed"):
        return make_package_error(
            (
                "Public access denied: "
                f"{access.get('reason')}"
            ),
            "PackageAccessDenied",
            403,
            "package_id",
            {
                "package_id": (
                    _safe_package_id(
                        package_id
                    )
                ),
                "reason": access.get(
                    "reason"
                ),
            },
        )

    payload = (
        load_public_package_file(
            package_id,
            canonical_component,
        )
    )

    if payload is None:
        public_data = (
            get_public_data_from_disk(
                package_id
            )
        )

        if (
            canonical_component
            == "data"
        ):
            payload = public_data

        elif isinstance(
            public_data,
            dict,
        ):
            data_section = (
                public_data.get(
                    "data",
                    {},
                )
                if isinstance(
                    public_data.get(
                        "data"
                    ),
                    dict,
                )
                else {}
            )

            payload = (
                data_section.get(
                    canonical_component,
                    public_data.get(
                        canonical_component
                    ),
                )
            )

    if payload is None:
        return make_package_error(
            (
                "Package component "
                "not found."
            ),
            (
                "PackageComponentNotFound"
            ),
            404,
            "component",
            {
                "package_id": (
                    _safe_package_id(
                        package_id
                    )
                ),
                "component": component,
            },
        )

    sanitized = (
        sanitize_public_component(
            payload,
            meta.get(
                "security",
                {},
            ),
        )
    )

    return make_package_response(
        (
            sanitized
            if isinstance(
                sanitized,
                dict,
            )
            else {
                canonical_component: (
                    sanitized
                )
            }
        ),
        (
            "Public package "
            f"{canonical_component} "
            "loaded."
        ),
        {
            "package_id": (
                _safe_package_id(
                    package_id
                )
            ),
            "component": (
                canonical_component
            ),
            "requested_component": (
                component
            ),
            "snapshot_only": True,
        },
    )

def get_public_package_meta(package_id: str, context: Optional[Dict[str, Any]] = None, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = get_package_meta_from_disk(package_id)
    if not meta:
        return make_package_error("Package not found.", "PackageNotFound", 404, "package_id", {"package_id": _safe_package_id(package_id)})
    access_meta = dict(meta)
    access_meta["components"] = sorted(set(access_meta.get("components", []) or []) | ALLOWED_PUBLIC_COMPONENTS)
    access = public_access_allowed(access_meta, component="meta", token=token or ((context or {}).get("token") if isinstance(context, dict) else ""))
    if not access.get("allowed"):
        return make_package_error(f"Public access denied: {access.get('reason')}", "PackageAccessDenied", 403, "package_id", {"package_id": _safe_package_id(package_id), "reason": access.get("reason")})
    safe_meta = sanitize_public_component(meta, meta.get("security", {}))
    safe_meta["public_url_meta"] = build_public_package_url_meta(package_id, token=token or (context or {}).get("token") if isinstance(context, dict) else token)
    return make_package_response(safe_meta, "Public package meta loaded.", {"package_id": _safe_package_id(package_id)})


def get_public_package_data(package_id: str, context: Optional[Dict[str, Any]] = None, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return public_component_response(package_id, "data", context or {"token": token})


def get_public_package_summary(package_id: str, context: Optional[Dict[str, Any]] = None, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return public_component_response(package_id, "summary", context or {"token": token})


def get_public_package_map(package_id: str, context: Optional[Dict[str, Any]] = None, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return public_component_response(package_id, "map", context or {"token": token})


def get_public_package_charts(package_id: str, context: Optional[Dict[str, Any]] = None, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return public_component_response(package_id, "charts", context or {"token": token})


def get_public_package_tables(package_id: str, context: Optional[Dict[str, Any]] = None, token: str = "", request_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return public_component_response(package_id, "tables", context or {"token": token})


def get_public_package_access_log(
    package_id: str,
    context: Optional[
        Dict[str, Any]
    ] = None,
    token: str = "",
) -> Dict[str, Any]:
    meta = get_package_meta_from_disk(
        package_id
    )

    if not meta:
        return make_package_error(
            "Package not found.",
            "PackageNotFound",
            404,
            "package_id",
            {
                "package_id": (
                    _safe_package_id(
                        package_id
                    )
                )
            },
        )

    access = public_access_allowed(
        meta,
        component="admin",
        token=(
            token
            or (
                context.get(
                    "token",
                    "",
                )
                if isinstance(
                    context,
                    dict,
                )
                else ""
            )
        ),
    )

    if not access.get("allowed"):
        return make_package_error(
            (
                "Public access denied: "
                f"{access.get('reason')}"
            ),
            "PackageAccessDenied",
            403,
            "package_id",
            {
                "package_id": (
                    _safe_package_id(
                        package_id
                    )
                ),
                "reason": access.get(
                    "reason"
                ),
            },
        )

    path = get_package_file(
        package_id,
        "access_log.jsonl",
    )

    entries: List[
        Dict[str, Any]
    ] = []

    if (
        path.exists()
        and path.is_file()
    ):
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            for line in file:
                line = line.strip()

                if not line:
                    continue

                try:
                    item = json.loads(
                        line
                    )
                except json.JSONDecodeError:
                    continue

                if isinstance(
                    item,
                    dict,
                ):
                    entries.append(
                        item
                    )

    public_entries = [
        {
            key: value
            for key, value
            in entry.items()
            if key not in {
                "remote_addr",
                "user_agent",
                "ip",
                "headers",
            }
        }
        for entry in entries[-500:]
    ]

    return make_package_response(
        {
            "package_id": (
                _safe_package_id(
                    package_id
                )
            ),
            "access_log": (
                public_entries
            ),
            "total": len(entries),
            "meta": {
                "redacted": True,
            },
        },
        (
            "Public package access "
            "log loaded."
        ),
    )


def write_public_package_access_log(
    package_id: str,
    payload: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    meta = get_package_meta_from_disk(
        package_id
    )

    if not meta:
        return make_package_error(
            "Package not found.",
            "PackageNotFound",
            404,
            "package_id",
            {
                "package_id": (
                    _safe_package_id(
                        package_id
                    )
                ),
                "logged": False,
            },
        )

    request = (
        payload
        if isinstance(payload, dict)
        else {}
    )

    entry = build_access_log_record(
        package_id=(
            _safe_package_id(
                package_id
            )
        ),
        action=clean_text(
            request.get("action"),
            "view",
        ),
        allowed=to_bool(
            request.get("allowed"),
            True,
        ),
        reason=clean_text(
            request.get("reason")
        ),
        extra={
            "component": clean_text(
                request.get(
                    "component"
                ),
                "data",
            )
        },
    )

    path = get_package_file(
        package_id,
        "access_log.jsonl",
    )

    append_jsonl(
        path,
        json_safe(entry),
    )

    return make_package_response(
        {
            "package_id": (
                _safe_package_id(
                    package_id
                )
            ),
            "logged": True,
            "entry": entry,
        },
        (
            "Public package access "
            "logged."
        ),
        {
            "package_id": (
                _safe_package_id(
                    package_id
                )
            )
        },
    )

def get_package_preview(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return preview_package(payload)


def create_package(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return generate_package(payload)


def get_package_list(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return list_packages(context)


def download_package(package_id: str) -> Dict[str, Any]:
    return get_package_download_info(package_id)

def run_rebuild_phase(
    phase_id: str,
    phase_name: str,
    function_ref: Any,
    force_refresh: bool = True,
) -> Dict[str, Any]:
    started_dt = datetime.now()
    started_at = (
        started_dt.isoformat(
            timespec="seconds"
        )
    )

    if function_ref is None:
        finished_dt = datetime.now()

        return {
            "phase_id": phase_id,
            "phase": phase_name,
            "phase_name": phase_name,
            "status": "skipped",
            "started_at": started_at,
            "finished_at": (
                finished_dt.isoformat(
                    timespec="seconds"
                )
            ),
            "duration_ms": int(
                (
                    finished_dt
                    - started_dt
                ).total_seconds()
                * 1000
            ),
            "record_count": 0,
            "outputs": {},
            "errors": [],
            "warnings": [
                {
                    "code": (
                        "function_not_available"
                    ),
                    "message": (
                        "function not available"
                    ),
                }
            ],
        }

    try:
        signature = inspect.signature(
            function_ref
        )

        parameters = (
            signature.parameters
        )

        accepts_kwargs = any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter
            in parameters.values()
        )

        if (
            "force_refresh"
            in parameters
            or accepts_kwargs
        ):
            payload = function_ref(
                force_refresh=(
                    force_refresh
                )
            )

        elif "context" in parameters:
            payload = function_ref(
                context={
                    "force_refresh": (
                        force_refresh
                    )
                }
            )

        else:
            payload = function_ref()

        finished_dt = datetime.now()
        status = "success"

        errors: List[Any] = []
        warnings: List[Any] = []

        if isinstance(payload, dict):
            raw_status = (
                clean_text_lower(
                    payload.get(
                        "status"
                    )
                )
            )

            if raw_status in {
                "degraded",
                "warning",
            }:
                status = "degraded"

            elif raw_status in {
                "error",
                "failed",
                "failure",
            }:
                status = "error"

            if isinstance(
                payload.get("errors"),
                list,
            ):
                errors = payload[
                    "errors"
                ]

            if isinstance(
                payload.get(
                    "warnings"
                ),
                list,
            ):
                warnings = payload[
                    "warnings"
                ]

        output_summary = {
            "rebuilt": (
                payload.get("rebuilt")
                if isinstance(
                    payload,
                    dict,
                )
                else None
            ),
            "status": (
                payload.get("status")
                if isinstance(
                    payload,
                    dict,
                )
                else None
            ),
            "stage": (
                payload.get("stage")
                if isinstance(
                    payload,
                    dict,
                )
                else None
            ),
            "total": (
                payload.get("total")
                if isinstance(
                    payload,
                    dict,
                )
                else None
            ),
            "record_count": (
                safe_count(payload)
            ),
            "generated_at": (
                payload.get(
                    "generated_at"
                )
                if isinstance(
                    payload,
                    dict,
                )
                else None
            ),
        }

        return {
            "phase_id": phase_id,
            "phase": phase_name,
            "phase_name": phase_name,
            "status": status,
            "started_at": started_at,
            "finished_at": (
                finished_dt.isoformat(
                    timespec="seconds"
                )
            ),
            "duration_ms": int(
                (
                    finished_dt
                    - started_dt
                ).total_seconds()
                * 1000
            ),
            "record_count": (
                safe_count(payload)
            ),
            "outputs": json_safe(
                output_summary
            ),
            "errors": json_safe(
                errors
            ),
            "warnings": json_safe(
                warnings
            ),
        }

    except Exception as exc:
        finished_dt = datetime.now()

        public_message = (
            str(exc)
            if bool(
                getattr(
                    config,
                    "DEBUG",
                    False,
                )
            )
            else (
                "Runtime rebuild "
                "phase failed."
            )
        )

        return {
            "phase_id": phase_id,
            "phase": phase_name,
            "phase_name": phase_name,
            "status": "error",
            "started_at": started_at,
            "finished_at": (
                finished_dt.isoformat(
                    timespec="seconds"
                )
            ),
            "duration_ms": int(
                (
                    finished_dt
                    - started_dt
                ).total_seconds()
                * 1000
            ),
            "record_count": 0,
            "outputs": {},
            "errors": [
                {
                    "error_type": (
                        exc.__class__.__name__
                    ),
                    "message": (
                        public_message
                    ),
                }
            ],
            "warnings": [],
        }

def validate_runtime_inputs(
    force_refresh: bool = True,
) -> Dict[str, Any]:
    package_dir = ensure_package_dir()

    zip_dir = ensure_dir(
        PACKAGE_ZIP_DIR
    )

    active_source = (
        "excel"
        if getattr(
            config,
            "USE_EXCEL_DATA_SOURCE",
            True,
        )
        else "mysql"
    )

    validations = {
        "config_loaded": bool(
            CONFIG_LOADED
        ),
        "utils_loaded": bool(
            UTILS_LOADED
        ),
        "security_loaded": bool(
            SECURITY_LOADED
        ),
        "pandas_loaded": bool(
            PANDAS_LOADED
        ),
        "package_dir_exists": bool(
            package_dir.exists()
            and package_dir.is_dir()
        ),
        "package_dir_writable": (
            os.access(
                package_dir,
                os.W_OK,
            )
        ),
        "package_zip_dir_exists": bool(
            zip_dir.exists()
            and zip_dir.is_dir()
        ),
        "package_zip_dir_writable": (
            os.access(
                zip_dir,
                os.W_OK,
            )
        ),
        "excel_active": bool(
            getattr(
                config,
                "USE_EXCEL_DATA_SOURCE",
                True,
            )
        ),
        "mysql_not_selected": not bool(
            getattr(
                config,
                "USE_MYSQL_DATA_SOURCE",
                False,
            )
        ),
        "map_service_available": (
            get_map_layers
            is not None
        ),
        "prediction_latest_available": (
            get_latest_flood_predictions
            is not None
        ),
        "prediction_map_available": (
            get_flood_prediction_map
            is not None
        ),
        "snapshot_only_public_viewer": (
            True
        ),
    }

    errors = [
        {
            "code": key,
            "message": (
                f"{key} validation failed"
            ),
        }
        for key, value
        in validations.items()
        if value is False
    ]

    return {
        "valid": not errors,
        "status": (
            "success"
            if not errors
            else "degraded"
        ),
        "validations": validations,
        "active_source": (
            active_source
        ),
        "errors": errors,
        "warnings": [],
        "checked_at": now_iso(),
        "package_policy": (
            SNAPSHOT_ONLY_PACKAGE_POLICY
        ),
    }

def rebuild_company_policy_base_cache(
    force_refresh: bool = True,
) -> Dict[str, Any]:
    return safe_call_service(
        rebuild_company_policy_base_service,
        fallback={
            "rebuilt": False,
            "status": "skipped",
            "stage": "base",
        },
        force_refresh=force_refresh,
    )


def rebuild_company_policy_enriched_cache(
    force_refresh: bool = True,
) -> Dict[str, Any]:
    return safe_call_service(
        rebuild_company_policy_enriched_service,
        fallback={
            "rebuilt": False,
            "status": "skipped",
            "stage": "enriched",
        },
        force_refresh=force_refresh,
    )

def rebuild_dashboard_charts_cache(force_refresh: bool = True) -> Dict[str, Any]:
    summary = build_dashboard_summary({"force_refresh": force_refresh})
    charts = build_chart_summary({"force_refresh": force_refresh})
    province_insights = build_dashboard_province_insights({"force_refresh": force_refresh})

    write_json_file_safe(_package_root() / "_runtime" / "dashboard_summary.json", summary)
    write_json_file_safe(_package_root() / "_runtime" / "charts.json", charts)
    write_json_file_safe(_package_root() / "_runtime" / "dashboard_province_insights.json", province_insights)

    return {
        "dashboard_summary": summary,
        "charts": charts,
        "dashboard_province_insights": province_insights,
        "generated_at": now_iso(),
    }

def rebuild_package_snapshot_cache(force_refresh: bool = True) -> Dict[str, Any]:
    preview = build_package_preview(
        {
            "force_refresh": force_refresh,
            "components": [
                "summary",
                "map",
                "charts",
                "tables",
                "data_quality",
                "prediction",
                "entity",
            ],
        }
    )

    runtime_dir = ensure_dir(_package_root() / "_runtime")
    write_json_file_safe(runtime_dir / "package_preview.json", preview)

    return {
        "status": "ready",
        "package_generation_policy": "package reads cache/snapshot only",
        "public_viewer_policy": "public viewer reads public_data.json only",
        "preview": preview,
        "outputs": {
            "package_preview": str(runtime_dir / "package_preview.json"),
        },
        "generated_at": now_iso(),
    }

def rebuild_all_runtime_cache(force_refresh: bool = True) -> Dict[str, Any]:
    data_quality_function = get_data_quality_dashboard_function()

    phases = [
        ("PHASE 0", "validate_runtime_inputs", validate_runtime_inputs),
        ("PHASE 1", "company_policy_base", rebuild_company_policy_base_cache),
        ("PHASE 2", "linkage", rebuild_linkage_cache),
        ("PHASE 3", "flood_excel_base", rebuild_flood_spatial_cache),
        ("PHASE 4", "spatial_prediction_entity", rebuild_flood_spatial_cache),
        ("PHASE 5", "company_policy_enriched", rebuild_company_policy_enriched_cache),
        ("PHASE 6", "map", rebuild_map_cache),
        ("PHASE 7", "dashboard_charts", rebuild_dashboard_charts_cache),
        ("PHASE 8", "data_quality", data_quality_function),
        ("PHASE 9", "package_snapshot", rebuild_package_snapshot_cache),
    ]

    results = [
        run_rebuild_phase(
            phase_id=phase_id,
            phase_name=phase_name,
            function_ref=function_ref,
            force_refresh=force_refresh,
        )
        for phase_id, phase_name, function_ref in phases
    ]

    failed = [
        item
        for item in results
        if item.get("status") == "error"
    ]

    degraded = [
        item
        for item in results
        if item.get("status") in {"degraded", "skipped"}
    ]

    return {
        "rebuilt": not bool(failed),
        "status": "success" if not failed and not degraded else "degraded" if not failed else "error",
        "force_refresh": bool(force_refresh),
        "phase_count": len(results),
        "failed_count": len(failed),
        "degraded_count": len(degraded),
        "phases": results,
        "errors": [
            error
            for item in results
            for error in item.get("errors", [])
        ],
        "warnings": [
            warning
            for item in results
            for warning in item.get("warnings", [])
        ],
        "started_at": results[0].get("started_at") if results else now_iso(),
        "finished_at": now_iso(),
        "snapshot_policy": SNAPSHOT_ONLY_PACKAGE_POLICY,
        "data_quality_function": getattr(data_quality_function, "__name__", ""),
    }

def rebuild_runtime_cache_phase(phase_name: str, force_refresh: bool = True) -> Dict[str, Any]:
    data_quality_function = get_data_quality_dashboard_function()

    phase_map = {
        "validate_runtime_inputs": validate_runtime_inputs,
        "company_policy_base": rebuild_company_policy_base_cache,
        "linkage": rebuild_linkage_cache,
        "flood_excel_base": rebuild_flood_spatial_cache,
        "spatial_prediction_entity": rebuild_flood_spatial_cache,
        "company_policy_enriched": rebuild_company_policy_enriched_cache,
        "map": rebuild_map_cache,
        "dashboard_charts": rebuild_dashboard_charts_cache,
        "data_quality": data_quality_function,
        "package_snapshot": rebuild_package_snapshot_cache,
    }

    phase_aliases = {
        "validate": "validate_runtime_inputs",
        "company_base": "company_policy_base",
        "company_enriched": "company_policy_enriched",
        "flood": "flood_excel_base",
        "spatial": "spatial_prediction_entity",
        "prediction": "spatial_prediction_entity",
        "entity": "spatial_prediction_entity",
        "charts": "dashboard_charts",
        "dashboard": "dashboard_charts",
        "quality": "data_quality",
        "data_quality_summary": "data_quality",
        "data_quality_dashboard": "data_quality",
        "package": "package_snapshot",
    }

    clean_phase = clean_text(phase_name)
    clean_phase = phase_aliases.get(clean_phase, clean_phase)

    if clean_phase not in phase_map:
        return make_package_error(
            message=f"Unknown rebuild phase: {phase_name}",
            error_type="UnknownRebuildPhase",
            status_code=400,
            field="phase_name",
            data={
                "phase_name": phase_name,
                "supported_phases": list(phase_map.keys()),
                "aliases": phase_aliases,
            },
        )

    return make_package_response(
        run_rebuild_phase(
            clean_phase,
            clean_phase,
            phase_map[clean_phase],
            force_refresh=force_refresh,
        ),
        "Runtime cache phase rebuilt.",
        {
            "phase_name": clean_phase,
            "requested_phase_name": phase_name,
            "data_quality_function": getattr(data_quality_function, "__name__", "") if clean_phase == "data_quality" else "",
        },
    )

write_public_access_log = write_public_package_access_log
log_public_package_access = write_public_package_access_log


def get_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_dashboard_summary(context)


def get_dashboard_province_insights_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_dashboard_province_insights(context)


def get_chart_risk_distribution(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_risk_distribution_chart(context)


def get_chart_province_comparison(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_province_comparison_chart(context)


def get_chart_station_ranking(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_station_ranking_chart(context)

build_dashboard_charts = build_chart_summary
