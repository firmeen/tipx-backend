# ============================================================
# FILE: backend/filter_engine.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 8 / 20
# ============================================================

"""
backend/filter_engine.py

ไฟล์นี้เป็นศูนย์กลาง Filter Builder / Saved View / Query Engine ของระบบ TIPX

หน้าที่หลัก:
1. จัดการ field ที่สามารถ filter ได้
2. จัดการ quick filter presets
3. รองรับ simple filter จาก query parameter
4. รองรับ advanced filter แบบ AND / OR / nested group
5. รองรับ operator หลายรูปแบบ เช่น equals, contains, between, gt, gte, lt, lte
6. ใช้ filter กับข้อมูล company / policy / linkage / flood / spatial / dashboard
7. รองรับ preview filter
8. รองรับ apply filter
9. รองรับ saved filter views
10. รองรับ filter สำหรับ package export
11. รองรับ filter สำหรับ map layer / graph / dashboard summary
12. เป็นตัวกลางให้ API, dashboard, package ใช้ logic เดียวกัน

ระบบที่ไฟล์นี้ต้องทำงานร่วมกับ:
- schemas.py
- utils.py
- company_policy_service.py
- linkage_service.py
- flood_spatial_service.py
- map_graph_service.py
- dashboard_package_service.py
- data_quality.py
"""

from __future__ import annotations
try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config import (
    CACHE_DIR,
    FILTER_OPERATORS,
    FILTER_LOGICAL_OPERATORS,
    FILTERABLE_FIELDS,
    QUICK_FILTER_PRESETS,
    DEFAULT_TABLE_PAGE_SIZE,
    MAX_TABLE_PAGE_SIZE,
)

from schemas import (
    FIELD_DEFINITIONS,
    FIELD_GROUPS,
    TABLE_VIEW_SCHEMAS,
    FILTER_PAYLOAD_EXAMPLE,
    get_filterable_fields,
    get_frontend_field_dictionary,
    validate_filter_payload,
)

from utils import (
    apply_search_sort_pagination,
    clean_text,
    clean_text_lower,
    dataframe_to_records,
    get_cache_file_path,
    is_empty_value,
    module_ready_payload,
    normalize_tax_id,
    read_json,
    search_records,
    sort_records,
    paginate_records,
    to_bool,
    to_datetime,
    to_jsonable,
    to_number,
    write_json,
)


# ============================================================
# 1) CONSTANTS
# ============================================================

SAVED_VIEWS_FILENAME: str = "saved_filter_views.json"
SAVED_VIEWS_PATH: Path = CACHE_DIR / SAVED_VIEWS_FILENAME

DEFAULT_FILTER_TARGET: str = "company"

SUPPORTED_TARGETS: List[str] = [
    "company",
    "policy",
    "linkage",
    "director",
    "flood",
    "spatial",
    "map",
    "dashboard",
    "data_quality",
]

TARGET_CACHE_KEYS: Dict[str, str] = {
    "company": "company_unified_master",
    "policy": "policy_fact",
    "linkage": "linkage_edges",
    "director": "director_master",
    "flood": "flood_computed_risk",
    "spatial": "spatial_join_result",
    "map": "map_layers",
    "dashboard": "dashboard_summary",
    "data_quality": "data_quality_issues",
}


# ============================================================
# 2) BASIC PAYLOAD NORMALIZATION
# ============================================================

def now_iso() -> str:
    """
    คืนเวลาปัจจุบันแบบ ISO string
    """

    return datetime.now().isoformat(timespec="seconds")


def normalize_target(target: Any) -> str:
    """
    normalize target ของ filter

    ถ้า target ไม่ถูกต้อง ให้ fallback เป็น company
    """

    target_text = clean_text_lower(target)

    if target_text in SUPPORTED_TARGETS:
        return target_text

    return DEFAULT_FILTER_TARGET


def normalize_sort_dir(sort_dir: Any) -> str:
    """
    normalize sort direction
    """

    value = clean_text_lower(sort_dir)

    if value in {"desc", "descending"}:
        return "desc"

    return "asc"


def normalize_page(value: Any) -> int:
    """
    normalize page
    """

    try:
        page = int(value)
    except Exception:
        page = 1

    return max(1, page)


def normalize_page_size(value: Any) -> int:
    """
    normalize page_size
    """

    try:
        page_size = int(value)
    except Exception:
        page_size = DEFAULT_TABLE_PAGE_SIZE

    page_size = max(1, page_size)
    page_size = min(page_size, MAX_TABLE_PAGE_SIZE)

    return page_size


def normalize_filter_payload(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    normalize filter payload กลางของระบบ

    รองรับ payload จาก:
    - POST /api/filter/preview
    - POST /api/filter/apply
    - package export
    - frontend state
    """

    payload = deepcopy(payload or {})

    target = normalize_target(payload.get("target", DEFAULT_FILTER_TARGET))

    advanced = payload.get("advanced", {})

    if isinstance(advanced, dict):
        advanced_payload = advanced
    else:
        advanced_payload = {}

    if not advanced_payload and "conditions" in payload:
        advanced_payload = {
            "logic": payload.get("logic", "AND"),
            "conditions": payload.get("conditions", []),
            "groups": payload.get("groups", []),
        }

    normalized = {
        "target": target,
        "filters": payload.get("filters", {}) if isinstance(payload.get("filters", {}), dict) else {},
        "advanced": advanced_payload,
        "search": clean_text(payload.get("search", "")),
        "page": normalize_page(payload.get("page", 1)),
        "page_size": normalize_page_size(payload.get("page_size", DEFAULT_TABLE_PAGE_SIZE)),
        "sort_by": clean_text(payload.get("sort_by", "")),
        "sort_dir": normalize_sort_dir(payload.get("sort_dir", "asc")),
        "include_summary": bool(to_bool(payload.get("include_summary", True), default=True)),
        "include_map": bool(to_bool(payload.get("include_map", True), default=True)),
        "include_graph": bool(to_bool(payload.get("include_graph", False), default=False)),
        "force_refresh": bool(to_bool(payload.get("force_refresh", False), default=False)),
    }

    return normalized


def query_context_to_filter_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    แปลง context จาก api_routes.py เป็น filter payload

    context มักมี:
    - filters
    - search
    - page
    - page_size
    - sort_by
    - sort_dir
    """

    context = context or {}

    return normalize_filter_payload(
        {
            "target": context.get("target") or context.get("dataset") or DEFAULT_FILTER_TARGET,
            "filters": context.get("filters", {}),
            "advanced": context.get("advanced", {}),
            "search": context.get("search", ""),
            "page": context.get("page", 1),
            "page_size": context.get("page_size", DEFAULT_TABLE_PAGE_SIZE),
            "sort_by": context.get("sort_by", ""),
            "sort_dir": context.get("sort_dir", "asc"),
            "force_refresh": context.get("force_refresh", False),
        }
    )


# ============================================================
# 3) FIELD / PRESET API
# ============================================================

def get_filter_fields() -> Dict[str, Any]:
    """
    API function:
    GET /api/filter/fields

    คืน field ทั้งหมดที่ filter ได้
    พร้อม group, operator, table view schema
    """

    return {
        "fields": get_filterable_fields(),
        "field_groups": FIELD_GROUPS,
        "operators": FILTER_OPERATORS,
        "logical_operators": FILTER_LOGICAL_OPERATORS,
        "filterable_by_target": {
            target: get_filterable_fields(target)
            for target in ["company", "policy", "linkage", "flood"]
        },
        "table_views": TABLE_VIEW_SCHEMAS,
        "payload_example": FILTER_PAYLOAD_EXAMPLE,
    }


def get_quick_filter_presets() -> Dict[str, Any]:
    """
    API function:
    GET /api/filter/quick-presets

    คืน preset สำเร็จรูปสำหรับ frontend
    """

    presets: List[Dict[str, Any]] = []

    for preset_id, preset in QUICK_FILTER_PRESETS.items():
        item = dict(preset)
        item["preset_id"] = preset_id
        presets.append(item)

    return {
        "presets": presets,
        "total": len(presets),
    }


def get_field_dtype(field_name: str) -> str:
    """
    คืน dtype ของ field จาก schemas.py
    """

    field_def = FIELD_DEFINITIONS.get(field_name)

    if not field_def:
        return "string"

    return field_def.dtype


def get_field_allowed_values(field_name: str) -> List[Any]:
    """
    คืน allowed values ของ field
    """

    field_def = FIELD_DEFINITIONS.get(field_name)

    if not field_def:
        return []

    return field_def.allowed_values or []


def get_target_fields(target: str) -> List[str]:
    """
    คืน field ที่เกี่ยวข้องกับ target
    """

    target = normalize_target(target)

    if target in FILTERABLE_FIELDS:
        return list(FILTERABLE_FIELDS[target])

    if target == "director":
        return [
            "director_id",
            "director_name",
            "company_count",
            "is_key_connector",
            "total_connected_income",
            "total_connected_capital",
            "total_connected_premium",
            "total_connected_suminsure",
        ]

    if target == "data_quality":
        return [
            "issue_id",
            "category",
            "severity",
            "code",
            "message",
            "dataset",
            "field",
            "record_key",
            "suggestion",
            "created_at",
        ]

    return [
        field.name
        for field in FIELD_DEFINITIONS.values()
        if field.filterable
    ]


# ============================================================
# 4) VALUE COMPARISON HELPERS
# ============================================================

def normalize_compare_value(value: Any, dtype: str = "string") -> Any:
    """
    normalize value ก่อน compare ตาม dtype
    """

    dtype = clean_text_lower(dtype)

    if dtype in {"number", "float", "integer", "int"}:
        return to_number(value, default=None)

    if dtype in {"boolean", "bool"}:
        return to_bool(value, default=None)

    if dtype in {"date", "datetime"}:
        return to_datetime(value, default=None)

    if dtype in {"array", "list"}:
        if value is None:
            return []

        if isinstance(value, list):
            return value

        return [value]

    return clean_text(value)


def value_to_list(value: Any) -> List[Any]:
    """
    แปลง value เป็น list
    """

    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, set):
        return list(value)

    if isinstance(value, str) and "," in value:
        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    return [value]


def compare_values(
    record_value: Any,
    operator: str,
    expected_value: Any = None,
    expected_value_to: Any = None,
    dtype: str = "string",
) -> bool:
    """
    compare ค่าเดียวตาม operator

    Operators:
    - equals
    - not_equals
    - contains
    - not_contains
    - starts_with
    - ends_with
    - in
    - not_in
    - gt
    - gte
    - lt
    - lte
    - between
    - is_empty
    - is_not_empty
    """

    operator = clean_text_lower(operator)
    dtype = clean_text_lower(dtype)

    if operator == "is_empty":
        return is_empty_value(record_value)

    if operator == "is_not_empty":
        return not is_empty_value(record_value)

    left = normalize_compare_value(record_value, dtype)
    right = normalize_compare_value(expected_value, dtype)
    right_to = normalize_compare_value(expected_value_to, dtype)

    if operator == "equals":
        if dtype in {"number", "float", "integer", "int"}:
            return left == right
        if dtype in {"boolean", "bool"}:
            return left == right
        return clean_text_lower(left) == clean_text_lower(right)

    if operator == "not_equals":
        return not compare_values(record_value, "equals", expected_value, dtype=dtype)

    if operator == "contains":
        if isinstance(record_value, list):
            expected_list = [clean_text_lower(v) for v in value_to_list(expected_value)]
            record_list = [clean_text_lower(v) for v in record_value]
            return any(v in record_list for v in expected_list)

        return clean_text_lower(expected_value) in clean_text_lower(record_value)

    if operator == "not_contains":
        return not compare_values(record_value, "contains", expected_value, dtype=dtype)

    if operator == "starts_with":
        return clean_text_lower(record_value).startswith(clean_text_lower(expected_value))

    if operator == "ends_with":
        return clean_text_lower(record_value).endswith(clean_text_lower(expected_value))

    if operator == "in":
        expected_list = value_to_list(expected_value)

        if dtype in {"number", "float", "integer", "int"}:
            expected_set = {
                to_number(item, default=None)
                for item in expected_list
            }
            return left in expected_set

        if dtype in {"boolean", "bool"}:
            expected_set = {
                to_bool(item, default=None)
                for item in expected_list
            }
            return left in expected_set

        expected_set = {
            clean_text_lower(item)
            for item in expected_list
        }
        return clean_text_lower(record_value) in expected_set

    if operator == "not_in":
        return not compare_values(record_value, "in", expected_value, dtype=dtype)

    if operator in {"gt", "gte", "lt", "lte", "between"}:
        if left is None:
            return False

        if operator == "gt":
            return right is not None and left > right

        if operator == "gte":
            return right is not None and left >= right

        if operator == "lt":
            return right is not None and left < right

        if operator == "lte":
            return right is not None and left <= right

        if operator == "between":
            if right is None or right_to is None:
                return False
            return right <= left <= right_to

    return False


# ============================================================
# 5) CONDITION / GROUP EVALUATION
# ============================================================

def evaluate_condition(record: Dict[str, Any], condition: Dict[str, Any]) -> bool:
    """
    evaluate condition 1 อันกับ record 1 แถว
    """

    if not isinstance(condition, dict):
        return True

    field_name = clean_text(condition.get("field"))
    operator = clean_text(condition.get("operator", "equals"))
    expected_value = condition.get("value")
    expected_value_to = condition.get("value_to")
    dtype = clean_text(condition.get("dtype") or get_field_dtype(field_name))

    if not field_name:
        return True

    record_value = record.get(field_name)

    return compare_values(
        record_value=record_value,
        operator=operator,
        expected_value=expected_value,
        expected_value_to=expected_value_to,
        dtype=dtype,
    )


def evaluate_filter_group(record: Dict[str, Any], group: Dict[str, Any]) -> bool:
    """
    evaluate filter group แบบ nested

    group format:
    {
        "logic": "AND",
        "conditions": [],
        "groups": []
    }
    """

    if not isinstance(group, dict) or not group:
        return True

    logic = clean_text(group.get("logic", "AND")).upper()

    if logic not in FILTER_LOGICAL_OPERATORS:
        logic = "AND"

    conditions = group.get("conditions", [])
    groups = group.get("groups", [])

    results: List[bool] = []

    if isinstance(conditions, list):
        for condition in conditions:
            results.append(evaluate_condition(record, condition))

    if isinstance(groups, list):
        for child_group in groups:
            results.append(evaluate_filter_group(record, child_group))

    if not results:
        return True

    if logic == "OR":
        return any(results)

    return all(results)


def apply_simple_filters(
    records: List[Dict[str, Any]],
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    apply simple filters จาก query parameter

    simple filter format:
    {
        "province": ["น่าน", "แพร่"],
        "has_policy": true,
        "loss_ratio_min": 50,
        "loss_ratio_max": 100
    }
    """

    filters = filters or {}

    if not filters:
        return list(records)

    result: List[Dict[str, Any]] = []

    for record in records:
        keep = True

        for key, value in filters.items():
            if value in (None, "", [], {}):
                continue

            key_text = clean_text(key)

            if key_text.endswith("_min"):
                field_name = key_text[:-4]
                record_value = to_number(record.get(field_name), default=None)
                expected = to_number(value, default=None)

                if expected is not None and (record_value is None or record_value < expected):
                    keep = False
                    break

                continue

            if key_text.endswith("_max"):
                field_name = key_text[:-4]
                record_value = to_number(record.get(field_name), default=None)
                expected = to_number(value, default=None)

                if expected is not None and (record_value is None or record_value > expected):
                    keep = False
                    break

                continue

            dtype = get_field_dtype(key_text)

            if isinstance(value, list):
                if not compare_values(record.get(key_text), "in", value, dtype=dtype):
                    keep = False
                    break
            else:
                if dtype in {"boolean", "bool"}:
                    if not compare_values(record.get(key_text), "equals", value, dtype=dtype):
                        keep = False
                        break
                else:
                    if not compare_values(record.get(key_text), "equals", value, dtype=dtype):
                        keep = False
                        break

        if keep:
            result.append(record)

    return result


def apply_advanced_filter(
    records: List[Dict[str, Any]],
    advanced: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    apply advanced filter group
    """

    advanced = advanced or {}

    if not advanced:
        return list(records)

    return [
        record
        for record in records
        if evaluate_filter_group(record, advanced)
    ]


def apply_full_filter(
    records: List[Dict[str, Any]],
    payload: Optional[Dict[str, Any]] = None,
    searchable_fields: Optional[List[str]] = None,
    paginate: bool = True,
) -> Dict[str, Any]:
    """
    apply filter ครบชุด:
    1. simple filters
    2. advanced filters
    3. search
    4. sort
    5. pagination
    """

    normalized = normalize_filter_payload(payload)

    filtered = apply_simple_filters(
        records=list(records or []),
        filters=normalized.get("filters", {}),
    )

    filtered = apply_advanced_filter(
        records=filtered,
        advanced=normalized.get("advanced", {}),
    )

    filtered = search_records(
        records=filtered,
        search=normalized.get("search", ""),
        fields=searchable_fields,
    )

    filtered = sort_records(
        records=filtered,
        sort_by=normalized.get("sort_by", ""),
        sort_dir=normalized.get("sort_dir", "asc"),
    )

    if paginate:
        page_result = paginate_records(
            records=filtered,
            page=normalized.get("page", 1),
            page_size=normalized.get("page_size", DEFAULT_TABLE_PAGE_SIZE),
        )
    else:
        page_result = {
            "records": filtered,
            "total": len(filtered),
            "page": 1,
            "page_size": len(filtered),
            "total_pages": 1,
            "has_next": False,
            "has_prev": False,
        }

    page_result["filter"] = normalized
    page_result["filtered_total"] = len(filtered)

    return page_result


# ============================================================
# 6) DATA LOADING FOR FILTER ENGINE
# ============================================================

def load_records_from_cache_key(cache_key: str) -> List[Dict[str, Any]]:
    """
    โหลด records จาก cache key

    รองรับ format:
    - list
    - {"records": []}
    - {"data": []}
    - {"data": {"records": []}}
    """

    path = get_cache_file_path(cache_key)

    if not path.exists():
        return []

    data = read_json(path, default={})

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("records"), list):
            return data["records"]

        if isinstance(data.get("data"), list):
            return data["data"]

        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("records"), list):
            return data["data"]["records"]

    return []


def load_target_records(target: str) -> List[Dict[str, Any]]:
    """
    โหลด records ตาม target จาก cache

    หมายเหตุ:
    filter_engine ไม่ควร import service หนักโดยตรง
    เพื่อลด circular import
    """

    target = normalize_target(target)
    cache_key = TARGET_CACHE_KEYS.get(target)

    if not cache_key:
        return []

    return load_records_from_cache_key(cache_key)


def get_searchable_fields_for_target(target: str) -> List[str]:
    """
    คืน searchable fields ตาม target
    """

    target = normalize_target(target)

    fields = get_target_fields(target)

    searchable: List[str] = []

    for field_name in fields:
        field_def = FIELD_DEFINITIONS.get(field_name)

        if field_def and field_def.searchable:
            searchable.append(field_name)

    if not searchable:
        if target == "company":
            searchable = ["tax_id_norm", "company_name", "province", "business_type_tsic", "wtip"]
        elif target == "policy":
            searchable = ["tax_id_norm", "company_name", "product", "subclass", "policy_status"]
        elif target == "linkage":
            searchable = ["source", "target", "type", "shared_directors"]
        elif target == "director":
            searchable = ["director_id", "director_name"]
        elif target == "data_quality":
            searchable = ["issue_id", "code", "message", "dataset", "field", "record_key"]

    return searchable


# ============================================================
# 7) FILTER SUMMARY
# ============================================================

def summarize_filtered_records(
    records: List[Dict[str, Any]],
    target: str,
) -> Dict[str, Any]:
    """
    สร้าง summary หลัง apply filter

    summary นี้ใช้ใน:
    - filter preview
    - package preview
    - dashboard filter context
    """

    target = normalize_target(target)

    summary: Dict[str, Any] = {
        "target": target,
        "record_count": len(records),
        "generated_at": now_iso(),
    }

    if target == "company":
        total_premium = sum(to_number(r.get("total_premium"), 0) or 0 for r in records)
        total_loss = sum(to_number(r.get("total_loss"), 0) or 0 for r in records)
        total_suminsure = sum(to_number(r.get("total_suminsure"), 0) or 0 for r in records)

        provinces = sorted(
            {
                clean_text(r.get("province"))
                for r in records
                if clean_text(r.get("province"))
            }
        )

        risk_counts: Dict[str, int] = {}
        for r in records:
            level = clean_text(r.get("flood_risk_level"), default="Unknown")
            risk_counts[level] = risk_counts.get(level, 0) + 1

        summary.update(
            {
                "total_premium": total_premium,
                "total_loss": total_loss,
                "total_suminsure": total_suminsure,
                "province_count": len(provinces),
                "provinces": provinces[:50],
                "risk_counts": risk_counts,
                "companies_with_policy": sum(1 for r in records if to_bool(r.get("has_policy"), default=False)),
                "companies_with_linkage": sum(1 for r in records if to_bool(r.get("has_linkage"), default=False)),
                "companies_with_location": sum(1 for r in records if to_bool(r.get("has_location"), default=False)),
                "companies_with_flood_context": sum(1 for r in records if to_bool(r.get("has_flood_context"), default=False)),
            }
        )

    elif target == "policy":
        total_premium = sum(to_number(r.get("premium"), 0) or 0 for r in records)
        total_loss = sum(to_number(r.get("loss"), 0) or 0 for r in records)
        total_suminsure = sum(to_number(r.get("suminsure"), 0) or 0 for r in records)

        product_counts: Dict[str, int] = {}
        subclass_counts: Dict[str, int] = {}

        for r in records:
            product = clean_text(r.get("product"), default="Unknown")
            subclass = clean_text(r.get("subclass"), default="Unknown")
            product_counts[product] = product_counts.get(product, 0) + 1
            subclass_counts[subclass] = subclass_counts.get(subclass, 0) + 1

        summary.update(
            {
                "total_premium": total_premium,
                "total_loss": total_loss,
                "total_suminsure": total_suminsure,
                "product_counts": product_counts,
                "subclass_counts": subclass_counts,
            }
        )

    elif target in {"linkage", "director"}:
        summary.update(
            {
                "key_connector_count": sum(1 for r in records if to_bool(r.get("is_key_connector"), default=False)),
                "max_company_count": max([to_number(r.get("company_count"), 0) or 0 for r in records], default=0),
            }
        )

    elif target == "flood":
        risk_counts: Dict[str, int] = {}
        for r in records:
            level = clean_text(r.get("risk_level") or r.get("flood_risk_level"), default="Unknown")
            risk_counts[level] = risk_counts.get(level, 0) + 1
        summary["risk_counts"] = risk_counts

    elif target == "data_quality":
        severity_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}

        for r in records:
            severity = clean_text(r.get("severity"), default="info")
            category = clean_text(r.get("category"), default="system")
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            category_counts[category] = category_counts.get(category, 0) + 1

        summary.update(
            {
                "severity_counts": severity_counts,
                "category_counts": category_counts,
            }
        )

    return summary


# ============================================================
# 8) PREVIEW / APPLY FILTER API FUNCTIONS
# ============================================================

def preview_filter(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    POST /api/filter/preview

    ใช้สำหรับ preview ก่อน apply จริง
    """

    normalized = normalize_filter_payload(payload)
    validation = validate_filter_payload(normalized)

    target = normalized["target"]
    records = load_target_records(target)

    result = apply_full_filter(
        records=records,
        payload=normalized,
        searchable_fields=get_searchable_fields_for_target(target),
        paginate=False,
    )

    filtered_records = result["records"]

    sample_records = filtered_records[:10]
    summary = summarize_filtered_records(filtered_records, target)

    return {
        "valid": validation.get("valid", True),
        "validation": validation,
        "target": target,
        "preview": {
            "total_before_filter": len(records),
            "total_after_filter": len(filtered_records),
            "sample_size": len(sample_records),
            "sample_records": sample_records,
        },
        "summary": summary,
        "filter": normalized,
    }


def apply_filter(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    POST /api/filter/apply

    ใช้ apply filter แล้วคืน records แบบ paginate
    """

    normalized = normalize_filter_payload(payload)
    validation = validate_filter_payload(normalized)

    if not validation.get("valid", True):
        return {
            "valid": False,
            "validation": validation,
            "records": [],
            "total": 0,
            "page": normalized["page"],
            "page_size": normalized["page_size"],
            "summary": {},
            "filter": normalized,
        }

    target = normalized["target"]
    records = load_target_records(target)

    result = apply_full_filter(
        records=records,
        payload=normalized,
        searchable_fields=get_searchable_fields_for_target(target),
        paginate=True,
    )

    summary = summarize_filtered_records(
        records=apply_full_filter(
            records=records,
            payload=normalized,
            searchable_fields=get_searchable_fields_for_target(target),
            paginate=False,
        )["records"],
        target=target,
    )

    return {
        "valid": True,
        "validation": validation,
        "target": target,
        "records": result["records"],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "total_pages": result["total_pages"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
        "summary": summary,
        "filter": normalized,
    }


# ============================================================
# 9) QUICK PRESET APPLICATION
# ============================================================

def get_preset_payload(preset_id: str) -> Optional[Dict[str, Any]]:
    """
    คืน payload ของ quick preset
    """

    preset = QUICK_FILTER_PRESETS.get(clean_text(preset_id))

    if not preset:
        return None

    target = preset.get("target", DEFAULT_FILTER_TARGET)

    return normalize_filter_payload(
        {
            "target": target,
            "advanced": {
                "logic": "AND",
                "conditions": preset.get("conditions", []),
                "groups": [],
            },
            "filters": {},
            "search": "",
            "page": 1,
            "page_size": DEFAULT_TABLE_PAGE_SIZE,
            "sort_by": "",
            "sort_dir": "asc",
        }
    )


def apply_quick_preset(
    preset_id: str,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    apply quick preset พร้อม optional overrides
    """

    payload = get_preset_payload(preset_id)

    if not payload:
        return {
            "valid": False,
            "message": "Preset not found",
            "preset_id": preset_id,
            "records": [],
            "total": 0,
        }

    if overrides:
        payload.update(normalize_filter_payload({**payload, **overrides}))

    result = apply_filter(payload)
    result["preset_id"] = preset_id

    return result


# ============================================================
# 10) SAVED FILTER VIEWS
# ============================================================

def load_saved_views() -> List[Dict[str, Any]]:
    """
    โหลด saved filter views
    """

    data = read_json(SAVED_VIEWS_PATH, default=[])

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and isinstance(data.get("views"), list):
        return data["views"]

    return []


def write_saved_views(views: List[Dict[str, Any]]) -> Path:
    """
    เขียน saved filter views
    """

    return write_json(
        SAVED_VIEWS_PATH,
        {
            "views": views,
            "total": len(views),
            "updated_at": now_iso(),
        },
    )


def generate_view_id() -> str:
    """
    สร้าง view id
    """

    return f"VIEW_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8].upper()}"


def save_filter_view(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    POST /api/filter/save-view

    Payload:
    {
        "view_name": "...",
        "description": "...",
        "filter": {...}
    }
    """

    payload = payload or {}

    view_name = clean_text(payload.get("view_name") or payload.get("name"))

    if not view_name:
        view_name = f"Saved View {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    description = clean_text(payload.get("description", ""))

    filter_payload = payload.get("filter") or payload.get("payload") or payload
    normalized_filter = normalize_filter_payload(filter_payload)

    validation = validate_filter_payload(normalized_filter)

    if not validation.get("valid", True):
        return {
            "saved": False,
            "view_id": None,
            "validation": validation,
            "message": "Invalid filter payload",
        }

    views = load_saved_views()

    view_id = generate_view_id()

    view = {
        "view_id": view_id,
        "view_name": view_name,
        "description": description,
        "target": normalized_filter["target"],
        "filter": normalized_filter,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": clean_text(payload.get("created_by"), default="system"),
        "tags": payload.get("tags", []) if isinstance(payload.get("tags", []), list) else [],
        "is_default": bool(to_bool(payload.get("is_default", False), default=False)),
    }

    if view["is_default"]:
        for existing in views:
            if existing.get("target") == view["target"]:
                existing["is_default"] = False

    views.append(view)
    write_saved_views(views)

    return {
        "saved": True,
        "view_id": view_id,
        "view": view,
    }


def get_saved_filter_views() -> Dict[str, Any]:
    """
    API function:
    GET /api/filter/saved-views
    """

    views = load_saved_views()

    views_sorted = sorted(
        views,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )

    return {
        "views": views_sorted,
        "total": len(views_sorted),
    }


def get_saved_filter_view_detail(view_id: str) -> Dict[str, Any]:
    """
    API function:
    GET /api/filter/saved-views/<view_id>
    """

    view_id = clean_text(view_id)

    views = load_saved_views()

    for view in views:
        if view.get("view_id") == view_id:
            return {
                "found": True,
                "view_id": view_id,
                "view": view,
            }

    return {
        "found": False,
        "view_id": view_id,
        "view": None,
    }


def update_saved_filter_view(
    view_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API function:
    PUT /api/filter/saved-views/<view_id>
    """

    view_id = clean_text(view_id)
    payload = payload or {}

    views = load_saved_views()

    updated_view: Optional[Dict[str, Any]] = None

    for view in views:
        if view.get("view_id") != view_id:
            continue

        if "view_name" in payload or "name" in payload:
            view["view_name"] = clean_text(payload.get("view_name") or payload.get("name"))

        if "description" in payload:
            view["description"] = clean_text(payload.get("description"))

        if "tags" in payload and isinstance(payload.get("tags"), list):
            view["tags"] = payload["tags"]

        if "is_default" in payload:
            view["is_default"] = bool(to_bool(payload.get("is_default"), default=False))

        if "filter" in payload or "payload" in payload:
            filter_payload = payload.get("filter") or payload.get("payload")
            normalized = normalize_filter_payload(filter_payload)
            validation = validate_filter_payload(normalized)

            if not validation.get("valid", True):
                return {
                    "updated": False,
                    "view_id": view_id,
                    "validation": validation,
                    "message": "Invalid filter payload",
                }

            view["filter"] = normalized
            view["target"] = normalized["target"]

        view["updated_at"] = now_iso()
        updated_view = view
        break

    if updated_view is None:
        return {
            "updated": False,
            "view_id": view_id,
            "message": "Saved view not found",
        }

    if updated_view.get("is_default"):
        for view in views:
            if view.get("view_id") != view_id and view.get("target") == updated_view.get("target"):
                view["is_default"] = False

    write_saved_views(views)

    return {
        "updated": True,
        "view_id": view_id,
        "view": updated_view,
    }


def delete_saved_filter_view(view_id: str) -> Dict[str, Any]:
    """
    API function:
    DELETE /api/filter/saved-views/<view_id>
    """

    view_id = clean_text(view_id)

    views = load_saved_views()

    before = len(views)
    views = [
        view
        for view in views
        if view.get("view_id") != view_id
    ]

    deleted = len(views) < before

    if deleted:
        write_saved_views(views)

    return {
        "deleted": deleted,
        "view_id": view_id,
    }


# ============================================================
# 11) FILTER FOR SERVICE LAYERS
# ============================================================

def filter_records_for_service(
    records: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
    target: str = DEFAULT_FILTER_TARGET,
    paginate: bool = True,
) -> Dict[str, Any]:
    """
    helper สำหรับ service อื่นเรียกใช้

    ตัวอย่าง:
        result = filter_records_for_service(records, context, target="company")
    """

    payload = query_context_to_filter_payload(
        {
            **(context or {}),
            "target": target,
        }
    )

    return apply_full_filter(
        records=records,
        payload=payload,
        searchable_fields=get_searchable_fields_for_target(target),
        paginate=paginate,
    )


def build_filter_context_for_package(
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    เตรียม filter context สำหรับ package export

    ใช้เก็บลง package_meta.filters
    """

    normalized = normalize_filter_payload(payload)

    preview = preview_filter(normalized)

    return {
        "filter": normalized,
        "preview": {
            "target": preview.get("target"),
            "valid": preview.get("valid"),
            "total_before_filter": preview.get("preview", {}).get("total_before_filter", 0),
            "total_after_filter": preview.get("preview", {}).get("total_after_filter", 0),
            "summary": preview.get("summary", {}),
        },
        "created_at": now_iso(),
    }


def get_filter_options_from_records(
    records: List[Dict[str, Any]],
    fields: Optional[List[str]] = None,
    max_values_per_field: int = 300,
) -> Dict[str, Any]:
    """
    สร้าง options สำหรับ dropdown filter จาก records

    ใช้ใน:
    - frontend global filter
    - package filter options
    """

    fields = fields or []

    if not fields and records:
        fields = sorted(
            {
                key
                for record in records[:100]
                for key in record.keys()
                if key in FIELD_DEFINITIONS
            }
        )

    options: Dict[str, List[Any]] = {}

    for field_name in fields:
        values = []

        seen = set()

        for record in records:
            value = record.get(field_name)

            if is_empty_value(value):
                continue

            if isinstance(value, list):
                candidates = value
            else:
                candidates = [value]

            for item in candidates:
                display = clean_text(item)

                if not display:
                    continue

                key = display.lower()

                if key in seen:
                    continue

                seen.add(key)
                values.append(display)

                if len(values) >= max_values_per_field:
                    break

            if len(values) >= max_values_per_field:
                break

        options[field_name] = sorted(values)

    return {
        "options": options,
        "field_count": len(options),
        "generated_at": now_iso(),
    }


# ============================================================
# 12) FILTER COMPATIBILITY WITH MAP / GRAPH
# ============================================================

def build_map_filter_payload(
    base_filter: Optional[Dict[str, Any]] = None,
    include_spatial_only: bool = True,
) -> Dict[str, Any]:
    """
    สร้าง filter payload สำหรับ map

    ถ้า include_spatial_only = True
    จะบังคับ has_location = True
    """

    payload = normalize_filter_payload(base_filter)
    payload["target"] = "company"

    filters = payload.setdefault("filters", {})

    if include_spatial_only:
        filters["has_location"] = True

    return payload


def build_graph_filter_payload(
    base_filter: Optional[Dict[str, Any]] = None,
    include_linkage_only: bool = True,
) -> Dict[str, Any]:
    """
    สร้าง filter payload สำหรับ graph

    ถ้า include_linkage_only = True
    จะบังคับ has_linkage = True
    """

    payload = normalize_filter_payload(base_filter)
    payload["target"] = "company"

    filters = payload.setdefault("filters", {})

    if include_linkage_only:
        filters["has_linkage"] = True

    return payload


def filter_company_records_for_map(
    records: List[Dict[str, Any]],
    payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    filter company records สำหรับ map layer
    """

    map_payload = build_map_filter_payload(payload, include_spatial_only=True)

    result = apply_full_filter(
        records=records,
        payload=map_payload,
        searchable_fields=get_searchable_fields_for_target("company"),
        paginate=False,
    )

    return result["records"]


def filter_company_records_for_graph(
    records: List[Dict[str, Any]],
    payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    filter company records สำหรับ linkage graph
    """

    graph_payload = build_graph_filter_payload(payload, include_linkage_only=True)

    result = apply_full_filter(
        records=records,
        payload=graph_payload,
        searchable_fields=get_searchable_fields_for_target("company"),
        paginate=False,
    )

    return result["records"]


# ============================================================
# 13) FILTER DEBUG / DIAGNOSTIC
# ============================================================

def explain_filter_payload(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    อธิบาย filter payload เพื่อ debug

    ใช้ตอบ frontend หรือใช้ print debug ได้
    """

    normalized = normalize_filter_payload(payload)
    validation = validate_filter_payload(normalized)

    advanced = normalized.get("advanced", {})

    condition_count = 0
    group_count = 0

    def walk_group(group: Dict[str, Any]) -> None:
        nonlocal condition_count, group_count

        if not isinstance(group, dict):
            return

        group_count += 1
        condition_count += len(group.get("conditions", []) or [])

        for child in group.get("groups", []) or []:
            walk_group(child)

    if advanced:
        walk_group(advanced)

    return {
        "normalized": normalized,
        "validation": validation,
        "target_fields": get_target_fields(normalized["target"]),
        "searchable_fields": get_searchable_fields_for_target(normalized["target"]),
        "advanced_condition_count": condition_count,
        "advanced_group_count": group_count,
        "operators": FILTER_OPERATORS,
    }


def run_filter_self_test() -> Dict[str, Any]:
    """
    self test สำหรับ filter_engine.py
    """

    sample_records = [
        {
            "tax_id_norm": "0100000000001",
            "company_name": "บริษัท ตัวอย่างหนึ่ง จำกัด",
            "province": "น่าน",
            "total_suminsure": 1500000,
            "loss_ratio": 45,
            "flood_risk_level": "Watch",
            "has_policy": True,
            "has_linkage": True,
            "has_location": True,
        },
        {
            "tax_id_norm": "0100000000002",
            "company_name": "บริษัท ตัวอย่างสอง จำกัด",
            "province": "แพร่",
            "total_suminsure": 500000,
            "loss_ratio": 120,
            "flood_risk_level": "Critical",
            "has_policy": True,
            "has_linkage": False,
            "has_location": True,
        },
        {
            "tax_id_norm": "0100000000003",
            "company_name": "บริษัท ตัวอย่างสาม จำกัด",
            "province": "เชียงใหม่",
            "total_suminsure": 2500000,
            "loss_ratio": 10,
            "flood_risk_level": "Normal",
            "has_policy": False,
            "has_linkage": True,
            "has_location": False,
        },
    ]

    payload = {
        "target": "company",
        "filters": {
            "province": ["น่าน", "แพร่"],
            "has_policy": True,
        },
        "advanced": {
            "logic": "AND",
            "conditions": [
                {
                    "field": "total_suminsure",
                    "operator": "gte",
                    "value": 1000000,
                    "dtype": "number",
                }
            ],
            "groups": [],
        },
        "search": "",
        "page": 1,
        "page_size": 50,
        "sort_by": "total_suminsure",
        "sort_dir": "desc",
    }

    result = apply_full_filter(
        records=sample_records,
        payload=payload,
        searchable_fields=get_searchable_fields_for_target("company"),
        paginate=True,
    )

    return {
        "module": "filter_engine",
        "ready": True,
        "sample_input_count": len(sample_records),
        "sample_result": result,
        "explain": explain_filter_payload(payload),
        "checked_at": now_iso(),
    }


# ============================================================
# 14) MODULE STATUS
# ============================================================

def get_filter_engine_status() -> Dict[str, Any]:
    """
    คืนสถานะ module filter_engine.py
    """

    return {
        "module": "filter_engine",
        "ready": True,
        "supported_targets": SUPPORTED_TARGETS,
        "supported_operators": FILTER_OPERATORS,
        "supported_logical_operators": FILTER_LOGICAL_OPERATORS,
        "quick_preset_count": len(QUICK_FILTER_PRESETS),
        "saved_views_path": str(SAVED_VIEWS_PATH),
        "saved_views_count": len(load_saved_views()),
        "checked_at": now_iso(),
    }