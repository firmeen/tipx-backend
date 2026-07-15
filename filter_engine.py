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
import json
import math
import re

import uuid
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from config import (
        CACHE_DIR,
        FILTER_OPERATORS,
        FILTER_LOGICAL_OPERATORS,
        FILTERABLE_FIELDS,
        QUICK_FILTER_PRESETS,
        DEFAULT_TABLE_PAGE_SIZE,
        MAX_TABLE_PAGE_SIZE,
    )
    CONFIG_LOADED = True
except Exception as e:
    CONFIG_LOADED = False
    CONFIG_ERROR = str(e)
    CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
    FILTER_OPERATORS = [
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "startswith",
        "endswith",
        "in",
        "not_in",
        "gt",
        "gte",
        "lt",
        "lte",
        "between",
        "is_empty",
        "is_not_empty",
        "exists",
        "not_exists",
    ]
    FILTER_LOGICAL_OPERATORS = ["AND", "OR"]
    FILTERABLE_FIELDS: Dict[str, List[str]] = {}
    QUICK_FILTER_PRESETS: Dict[str, Dict[str, Any]] = {}
    DEFAULT_TABLE_PAGE_SIZE = 50
    MAX_TABLE_PAGE_SIZE = 500

try:
    from schemas import (
        FIELD_DEFINITIONS,
        FIELD_GROUPS,
        TABLE_VIEW_SCHEMAS,
        FILTER_PAYLOAD_EXAMPLE,
        get_filterable_fields,
        get_frontend_field_dictionary,
        validate_filter_payload,
    )
    SCHEMAS_LOADED = True
except Exception as e:
    SCHEMAS_LOADED = False
    SCHEMAS_ERROR = str(e)
    FIELD_DEFINITIONS: Dict[str, Any] = {}
    FIELD_GROUPS: List[Dict[str, Any]] = []
    TABLE_VIEW_SCHEMAS: Dict[str, Any] = {}
    FILTER_PAYLOAD_EXAMPLE: Dict[str, Any] = {}

    def get_filterable_fields(target: Optional[str] = None) -> List[Any]:
        target_key = normalize_target(target) if target else ""
        if target_key and target_key in FILTERABLE_FIELDS:
            return list(FILTERABLE_FIELDS[target_key])
        if FILTERABLE_FIELDS:
            fields = []
            for items in FILTERABLE_FIELDS.values():
                fields.extend(items)
            return sorted(set(fields))
        return []

    def get_frontend_field_dictionary() -> Dict[str, Any]:
        return {"fields": get_filterable_fields(), "groups": FIELD_GROUPS}

    def validate_filter_payload(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"valid": True, "errors": [], "warnings": []}

try:
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
    UTILS_LOADED = True
except Exception as e:
    UTILS_LOADED = False
    UTILS_ERROR = str(e)

    def clean_text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default

    def clean_text_lower(value: Any, default: str = "") -> str:
        return clean_text(value, default=default).lower()

    def is_empty_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and value.strip() in {"", "-", "N/A", "n/a", "nan", "NaN", "None", "none", "null"}:
            return True
        if isinstance(value, float) and math.isnan(value):
            return True
        if isinstance(value, (list, tuple, set, dict)) and len(value) == 0:
            return True
        return False

    def to_number(value: Any, default: Any = None) -> Any:
        if is_empty_value(value):
            return default
        if isinstance(value, bool):
            return int(value)
        try:
            text = str(value).strip().replace(",", "")
            if text.endswith("%"):
                text = text[:-1]
            number = float(text)
        except (TypeError, ValueError):
            return default
        if math.isnan(number) or math.isinf(number):
            return default
        return number

    def to_bool(value: Any, default: Optional[bool] = False) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = clean_text_lower(value)
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return default

    def to_datetime(value: Any, default: Any = None) -> Any:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if is_empty_value(value):
            return default
        text = clean_text(value)
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return default

    def to_jsonable(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return None if math.isnan(value) or math.isinf(value) else value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {clean_text(key): to_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [to_jsonable(item) for item in value]
        if hasattr(value, "to_dict"):
            try:
                return to_jsonable(value.to_dict(orient="records"))
            except TypeError:
                return to_jsonable(value.to_dict())
        if hasattr(value, "item"):
            try:
                return to_jsonable(value.item())
            except Exception:
                pass
        return clean_text(value)

    def normalize_tax_id(value: Any) -> str:
        return "".join(ch for ch in clean_text(value) if ch.isdigit())

    def dataframe_to_records(value: Any) -> List[Dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [dict(value)]
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict(orient="records")
            except TypeError:
                data = value.to_dict()
                return data if isinstance(data, list) else [data]
        return []

    def get_cache_file_path(cache_key: str) -> Path:
        return Path(CACHE_DIR) / f"{clean_text(cache_key)}.json"

    def read_json(path: Path, default: Any = None) -> Any:
        if default is None:
            default = {}
        try:
            if not Path(path).exists():
                return default
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return default

    def write_json(path: Path, data: Any) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(to_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def search_records(records: List[Dict[str, Any]], search: str = "", fields: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not clean_text(search):
            return list(records or [])
        needle = clean_text_lower(search)
        search_fields = fields or sorted({key for record in records[:100] for key in record.keys()})
        return [
            record
            for record in records or []
            if any(needle in clean_text_lower(record.get(field)) for field in search_fields)
        ]

    def sort_records(records: List[Dict[str, Any]], sort_by: str = "", sort_dir: str = "asc") -> List[Dict[str, Any]]:
        if not clean_text(sort_by):
            return list(records or [])
        reverse = clean_text_lower(sort_dir) == "desc"
        return sorted(
            list(records or []),
            key=lambda item: (is_empty_value(item.get(sort_by)), clean_text_lower(item.get(sort_by))),
            reverse=reverse,
        )

    def paginate_records(records: List[Dict[str, Any]], page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        page = max(1, int(page or 1))
        page_size = max(1, int(page_size or DEFAULT_TABLE_PAGE_SIZE))
        total = len(records or [])
        total_pages = math.ceil(total / page_size) if total else 0
        start = (page - 1) * page_size
        page_records = list(records or [])[start:start + page_size]
        return {
            "records": page_records,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "returned_count": len(page_records),
            "has_next": bool(total_pages and page < total_pages),
            "has_prev": page > 1 and bool(total_pages),
        }

    def apply_search_sort_pagination(records: List[Dict[str, Any]], *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return paginate_records(records, kwargs.get("page", 1), kwargs.get("page_size", DEFAULT_TABLE_PAGE_SIZE))

    def module_ready_payload(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"ready": True}


# ============================================================
# 1) CONSTANTS
# ============================================================

SAVED_VIEWS_FILENAME: str = "saved_filter_views.json"
SAVED_VIEWS_PATH: Path = Path(CACHE_DIR) / SAVED_VIEWS_FILENAME

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
    "package",

    "flood_rainfall_latest",
    "flood_waterlevel_latest",
    "flood_dam_latest",
    "flood_prediction_latest",
    "flood_prediction_map",
    "uploaded_entity_latest",
    "map_layers",
    "dashboard_province_insights",

    "prediction_map_view",
    "entity_overlay_view",
    "flood_dashboard_view",
    "province_insight_view",
]

TARGET_ALIASES: Dict[str, str] = {
    "companies": "company",
    "policies": "policy",
    "directors": "director",
    "graph": "linkage",
    "linkage_graph": "linkage",
    "linkage_graph_payload": "linkage",
    "quality": "data_quality",
    "data-quality": "data_quality",
    "data quality": "data_quality",
    "dataquality": "data_quality",
    "packages": "package",
    "exports": "package",

    "rainfall": "flood_rainfall_latest",
    "rainfall_latest": "flood_rainfall_latest",
    "latest_rainfall": "flood_rainfall_latest",
    "flood_rainfall": "flood_rainfall_latest",

    "waterlevel": "flood_waterlevel_latest",
    "water_level": "flood_waterlevel_latest",
    "waterlevel_latest": "flood_waterlevel_latest",
    "latest_waterlevel": "flood_waterlevel_latest",
    "flood_waterlevel": "flood_waterlevel_latest",

    "dam": "flood_dam_latest",
    "dams": "flood_dam_latest",
    "reservoir": "flood_dam_latest",
    "reservoirs": "flood_dam_latest",
    "dam_latest": "flood_dam_latest",
    "latest_dam": "flood_dam_latest",
    "flood_dam": "flood_dam_latest",

    "prediction": "flood_prediction_latest",
    "forecast": "flood_prediction_latest",
    "prediction_latest": "flood_prediction_latest",
    "forecast_latest": "flood_prediction_latest",
    "latest_prediction": "flood_prediction_latest",
    "latest_forecast": "flood_prediction_latest",

    "prediction_map": "flood_prediction_map",
    "forecast_map": "flood_prediction_map",
    "map_prediction": "flood_prediction_map",

    "entity": "uploaded_entity_latest",
    "entities": "uploaded_entity_latest",
    "uploaded_entity": "uploaded_entity_latest",
    "uploaded_entities": "uploaded_entity_latest",
    "entity_overlay": "uploaded_entity_latest",

    "layers": "map_layers",
    "map_layer": "map_layers",
    "map_layers": "map_layers",

    "province_insights": "dashboard_province_insights",
    "dashboard_insights": "dashboard_province_insights",
    "dashboard_province": "dashboard_province_insights",
    "province_insight": "dashboard_province_insights",

    "prediction_map_view": "prediction_map_view",
    "entity_overlay_view": "entity_overlay_view",
    "flood_dashboard_view": "flood_dashboard_view",
    "province_insight_view": "province_insight_view",
}

TARGET_CACHE_KEYS: Dict[str, str] = {
    "company": "company_unified_master",
    "policy": "policy_fact",
    "linkage": "linkage_graph_payload",
    "director": "director_master",
    "flood": "flood_computed_risk",
    "spatial": "spatial_join_result",
    "map": "map_layers",
    "dashboard": "dashboard_summary",
    "data_quality": "data_quality_summary",
    "package": "package_index",

    "flood_rainfall_latest": "flood_rainfall_latest",
    "flood_waterlevel_latest": "flood_waterlevel_latest",
    "flood_dam_latest": "flood_large_dam_latest",
    "flood_prediction_latest": "flood_prediction_latest",
    "flood_prediction_map": "flood_prediction_map",
    "uploaded_entity_latest": "uploaded_entity_latest",
    "map_layers": "map_layers",
    "dashboard_province_insights": "dashboard_province_insights",

    "prediction_map_view": "flood_prediction_map",
    "entity_overlay_view": "uploaded_entity_latest",
    "flood_dashboard_view": "dashboard_province_insights",
    "province_insight_view": "dashboard_province_insights",
}

TARGET_CACHE_KEY_CANDIDATES: Dict[str, List[str]] = {
    "company": ["company_unified_master", "company_unified_base"],
    "policy": ["policy_fact", "policy_company_summary", "policy_product_summary"],
    "linkage": ["linkage_graph_payload", "linkage_graph", "linkage_nodes", "linkage_edges", "shared_director_links"],
    "director": ["director_master", "director_company_pairs"],
    "flood": ["flood_computed_risk", "province_risk_summary"],
    "spatial": ["spatial_join_result", "company_flood_context", "policy_flood_exposure"],
    "map": ["map_layers", "map_companies", "map_flood", "map_policy_exposure"],
    "dashboard": ["dashboard_summary", "dashboard_province_insights", "chart_summary"],
    "data_quality": ["data_quality_summary", "data_quality_issues"],
    "package": ["package_index", "export_history"],

    "flood_rainfall_latest": ["flood_rainfall_latest"],
    "flood_waterlevel_latest": ["flood_waterlevel_latest"],
    "flood_dam_latest": ["flood_large_dam_latest", "flood_medium_dam_latest", "flood_dam_latest"],
    "flood_prediction_latest": ["flood_prediction_latest"],
    "flood_prediction_map": ["flood_prediction_map", "flood_prediction_latest"],
    "uploaded_entity_latest": ["uploaded_entity_latest"],
    "map_layers": ["map_layers"],
    "dashboard_province_insights": ["dashboard_province_insights"],

    "prediction_map_view": ["flood_prediction_map", "flood_prediction_latest"],
    "entity_overlay_view": ["uploaded_entity_latest"],
    "flood_dashboard_view": ["dashboard_province_insights", "dashboard_summary"],
    "province_insight_view": ["dashboard_province_insights"],
}

FILTER_FIELD_GROUPS: List[str] = [
    "company_identity",
    "company_financial",
    "policy",
    "linkage",
    "director",
    "location",
    "flood",
    "prediction",
    "entity",
    "spatial",
    "map",
    "dashboard",
    "data_quality",
    "package",
]

COMMON_FLOOD_RUNTIME_FIELDS: List[str] = [
    "province",
    "province_model",
    "province_name_th",
    "prediction_province",
    "prediction_province_model",
    "risk_level",
    "risk_status",
    "warning_level",
    "warning_level_predict",
    "station_id",
    "station_name",
    "station_code",
    "matched_station_id",
    "matched_station_code",
    "matched_station_name",
    "base_date",
    "target_date",
    "forecast_horizon_day",
    "prediction_horizon",
    "horizon",
    "data_date",
    "source_id",
    "source_name",
    "source_type",
    "latest_value",
    "latest_unit",
    "risk_score",
    "map_ready",
    "has_location",
    "latitude",
    "longitude",
    "lat",
    "lon",
]

ENTITY_RUNTIME_FIELDS: List[str] = [
    "entity_id",
    "entity_type",
    "entity_name_th",
    "province_name_th",
    "province",
    "risk_group",
    "risk_level",
    "source_type",
    "map_ready",
    "has_location",
    "latitude",
    "longitude",
]

DASHBOARD_INSIGHT_FIELDS: List[str] = [
    "province",
    "risk_level",
    "risk_score",
    "confidence",
    "prediction_count",
    "critical_count",
    "warning_count",
    "watch_count",
    "target_horizons",
    "target_display",
    "name",
    "value",
    "focus",
    "mode",
]

FALLBACK_FIELDS_BY_TARGET: Dict[str, List[str]] = {
    "company": [
        "tax_id_norm",
        "company_name",
        "company_name_policy",
        "company_name_linkage",
        "province",
        "district",
        "subdistrict",
        "business_type_objective",
        "business_type_tsic",
        "company_size",
        "Wtip",
        "wtip",
        "most_recent_income_val",
        "registered_capital",
        "has_policy",
        "has_linkage",
        "has_location",
        "has_flood_context",
    ],
    "policy": [
        "policy_status_now",
        "policy_status_now_new",
        "active_policy_count",
        "expired_policy_count",
        "total_premium",
        "total_loss",
        "total_suminsure",
        "total_noofpol",
        "loss_ratio",
        "loss_ratio_band",
        "product",
        "subclass",
    ],
    "linkage": [
        "director_count",
        "shared_company_count",
        "key_connector_count",
        "director_id",
        "director_name",
        "director_name_display",
        "company_count",
        "shared_director_count",
        "edge_type",
        "weight",
    ],
    "director": ["director_id", "director_name", "director_name_display", "companies", "company_count"],
    "flood": [
        "flood_risk_level",
        "flood_join_level",
        "nearest_rainfall_station_id",
        "nearest_rainfall_station_name",
        "nearest_waterlevel_station_id",
        "nearest_waterlevel_station_name",
        "nearest_dam_id",
        "nearest_dam_name",
        "province_risk_level",
        "risk_score",
        "source_id",
        "source_name",
        "station_name",
        "province",
        "basin",
        "risk_level",
    ],
    "spatial": [
        "tax_id_norm",
        "company_name",
        "province",
        "nearest_station_name",
        "flood_risk_level",
    ],
    "map": [
        "layer_id",
        "feature_type",
        "object_type",
        "marker_size",
        "marker_color",
        "location_quality",
        "lat",
        "lon",
        "latitude",
        "longitude",
        "province",
        "risk_level",
        "source_type",
    ],
    "map_layers": [
        "layer_id",
        "layer_name",
        "feature_type",
        "object_type",
        "source_type",
        "province",
        "risk_level",
        "risk_status",
        "map_ready",
        "has_location",
        "latitude",
        "longitude",
        "record_count",
    ],
    "data_quality": [
        "issue_type",
        "severity",
        "field",
        "message",
        "source",
        "record_key",
        "data_quality_flags",
    ],
    "package": ["package_id", "package_name", "created_at", "status", "owner"],
    "dashboard": ["card_id", "chart_id", "title", "metric", "value", "status", "province", "risk_level"],

    "flood_rainfall_latest": COMMON_FLOOD_RUNTIME_FIELDS,
    "flood_waterlevel_latest": COMMON_FLOOD_RUNTIME_FIELDS,
    "flood_dam_latest": COMMON_FLOOD_RUNTIME_FIELDS + ["dam_id", "dam_name", "reservoir_name", "storage_percent", "percent_storage"],
    "flood_prediction_latest": COMMON_FLOOD_RUNTIME_FIELDS + ["record_key", "focus_level", "focus_fallback"],
    "flood_prediction_map": COMMON_FLOOD_RUNTIME_FIELDS + ["record_key", "focus_level", "focus_fallback", "object_type"],
    "uploaded_entity_latest": ENTITY_RUNTIME_FIELDS,
    "dashboard_province_insights": DASHBOARD_INSIGHT_FIELDS,

    "prediction_map_view": COMMON_FLOOD_RUNTIME_FIELDS + ["record_key", "focus_level", "focus_fallback", "object_type"],
    "entity_overlay_view": ENTITY_RUNTIME_FIELDS,
    "flood_dashboard_view": DASHBOARD_INSIGHT_FIELDS,
    "province_insight_view": DASHBOARD_INSIGHT_FIELDS,
}

SEARCHABLE_FIELDS_BY_TARGET: Dict[str, List[str]] = {
    "company": ["tax_id_norm", "company_name", "company_name_policy", "company_name_linkage", "province", "district", "business_type_objective", "business_type_tsic", "Wtip", "wtip"],
    "policy": ["tax_id_norm", "company_name", "product", "subclass", "status_now", "province"],
    "linkage": ["tax_id_norm", "company_name", "director_name", "director_name_display", "shared_directors", "business_type_tsic"],
    "director": ["director_id", "director_name", "director_name_display", "companies"],
    "flood": ["source_id", "source_name", "station_name", "province", "basin", "risk_level"],
    "spatial": ["tax_id_norm", "company_name", "province", "nearest_station_name", "flood_risk_level"],
    "map": ["layer_id", "feature_type", "object_type", "company_name", "province", "marker_color", "location_quality", "source_type"],
    "map_layers": ["layer_id", "layer_name", "feature_type", "object_type", "province", "risk_level", "source_type"],
    "dashboard": ["card_id", "chart_id", "title", "metric", "status", "province"],
    "data_quality": ["issue_type", "severity", "field", "message", "source"],
    "package": ["package_id", "package_name", "status", "owner"],

    "flood_rainfall_latest": ["province", "station_id", "station_name", "station_code", "source_id", "source_name", "risk_level", "risk_status"],
    "flood_waterlevel_latest": ["province", "station_id", "station_name", "station_code", "source_id", "source_name", "risk_level", "risk_status"],
    "flood_dam_latest": ["province", "dam_id", "dam_name", "reservoir_name", "source_id", "source_name", "risk_level", "risk_status"],
    "flood_prediction_latest": ["province", "province_model", "station_id", "station_name", "station_code", "matched_station_id", "matched_station_code", "matched_station_name", "risk_level", "warning_level_predict", "record_key"],
    "flood_prediction_map": ["province", "province_model", "station_id", "station_name", "matched_station_id", "matched_station_name", "risk_level", "warning_level_predict", "record_key", "source_type"],
    "uploaded_entity_latest": ["entity_id", "entity_type", "entity_name_th", "province_name_th", "province", "risk_group", "risk_level", "source_type"],
    "dashboard_province_insights": ["province", "risk_level", "name", "target_display", "mode"],

    "prediction_map_view": ["province", "province_model", "station_id", "station_name", "matched_station_id", "matched_station_name", "risk_level", "warning_level_predict", "record_key", "source_type"],
    "entity_overlay_view": ["entity_id", "entity_type", "entity_name_th", "province_name_th", "province", "risk_group", "risk_level", "source_type"],
    "flood_dashboard_view": ["province", "risk_level", "name", "target_display", "mode"],
    "province_insight_view": ["province", "risk_level", "name", "target_display", "mode"],
}

FILTER_FIELD_ALIAS_CANDIDATES: Dict[str, List[str]] = {
    "risk": ["risk_level", "risk_status", "warning_level", "warning_level_predict", "flood_risk_level", "province_risk_level", "risk_group"],
    "risk_level": ["risk_level", "risk_status", "warning_level", "warning_level_predict", "flood_risk_level", "province_risk_level", "risk_group"],
    "risk_status": ["risk_status", "risk_level", "warning_level", "warning_level_predict", "flood_risk_level", "province_risk_level", "risk_group"],
    "warning_level": ["warning_level", "warning_level_predict", "risk_level", "risk_status", "flood_risk_level"],
    "warning_level_predict": ["warning_level_predict", "warning_level", "risk_level", "risk_status", "flood_risk_level"],

    "province": ["province", "province_model", "prediction_province", "prediction_province_model", "province_name_th"],
    "province_model": ["province_model", "prediction_province_model", "prediction_province", "province", "province_name_th"],
    "prediction_province": ["prediction_province", "province_model", "prediction_province_model", "province", "province_name_th"],
    "prediction_province_model": ["prediction_province_model", "province_model", "prediction_province", "province", "province_name_th"],

    "station": ["station_name", "station_id", "station_code", "matched_station_id", "matched_station_code", "matched_station_name", "source_name", "source_id"],
    "station_name": ["station_name", "matched_station_name", "source_name"],
    "station_id": ["station_id", "matched_station_id", "source_id"],
    "station_code": ["station_code", "matched_station_code"],
    "matched_station_id": ["matched_station_id", "station_id", "source_id"],
    "matched_station_code": ["matched_station_code", "station_code"],
    "matched_station_name": ["matched_station_name", "station_name", "source_name"],

    "horizon": ["forecast_horizon_day", "prediction_horizon", "horizon"],
    "forecast_horizon_day": ["forecast_horizon_day", "prediction_horizon", "horizon"],
    "prediction_horizon": ["prediction_horizon", "forecast_horizon_day", "horizon"],

    "lat": ["lat", "latitude"],
    "lon": ["lon", "longitude", "lng"],
    "lng": ["longitude", "lon", "lng"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lon", "lng"],

    "entity_name": ["entity_name_th", "entity_name", "name"],
    "entity_name_th": ["entity_name_th", "entity_name", "name"],
}

FIELD_DTYPE_OVERRIDES: Dict[str, str] = {
    "latest_value": "number",
    "risk_score": "number",
    "confidence": "number",
    "forecast_horizon_day": "integer",
    "prediction_horizon": "integer",
    "horizon": "integer",
    "storage_percent": "number",
    "percent_storage": "number",
    "value": "number",
    "prediction_count": "integer",
    "critical_count": "integer",
    "warning_count": "integer",
    "watch_count": "integer",
    "base_date": "date",
    "target_date": "date",
    "data_date": "date",
    "created_at": "datetime",
    "updated_at": "datetime",
    "generated_at": "datetime",
    "map_ready": "boolean",
    "has_location": "boolean",
    "has_flood_context": "boolean",
    "has_policy": "boolean",
    "has_linkage": "boolean",
}

OPERATOR_ALIASES: Dict[str, str] = {
    "eq": "equals",
    "neq": "not_equals",
    "ne": "not_equals",
    "like": "contains",
    "not_like": "not_contains",
    "starts_with": "startswith",
    "ends_with": "endswith",
    "greater_than": "gt",
    "less_than": "lt",
    "minmax": "between",
    "empty": "is_empty",
    "not_empty": "is_not_empty",
    "notempty": "is_not_empty",
    "notexists": "not_exists",
    "not_exists": "not_exists",
}


# ============================================================
# 2) BASIC PAYLOAD NORMALIZATION
# ============================================================

def now_iso() -> str:
    """
    คืนเวลาปัจจุบันแบบ ISO string
    """

    return datetime.now().isoformat(timespec="seconds")


def make_filter_response(
    data: Optional[Dict[str, Any]] = None,
    message: str = "Filter operation completed.",
    target: str = DEFAULT_FILTER_TARGET,
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    success: bool = True,
) -> Dict[str, Any]:
    """
    Standard API-compatible filter response.
    """

    normalized_target = normalize_target(target)
    response_meta = {
        "module": "filter",
        "target": normalized_target,
        "generated_at": now_iso(),
    }
    response_meta.update(meta or {})
    return to_jsonable(
        {
            "success": bool(success),
            "message": message,
            "data": data or {},
            "meta": response_meta,
            "errors": errors or [],
        }
    )


def make_filter_error(
    message: str,
    error_type: str = "ValidationError",
    field: str = "",
    target: str = DEFAULT_FILTER_TARGET,
    status_code: int = 400,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Standard validation/runtime error response for public filter facades.
    """

    return make_filter_response(
        data=data or {},
        message=message,
        target=target,
        meta={"status_code": status_code},
        errors=[
            {
                "type": error_type,
                "field": field,
                "message": message,
            }
        ],
        success=False,
    )


def make_degraded_filter_response(
    target: str,
    reason: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Success response for valid requests with empty or missing source data.
    """

    normalized = normalize_filter_payload(payload or {"target": target})
    return make_filter_response(
        data={
            "target": normalize_target(target),
            "records": [],
            "total": 0,
            "page": normalized["page"],
            "page_size": normalized["page_size"],
            "total_pages": 0,
            "returned_count": 0,
            "has_next": False,
            "has_prev": False,
            "filter_summary": build_filter_summary(normalized, {"source_record_count": 0, "filtered_record_count": 0, "returned_count": 0}),
            "warnings": normalized.get("warnings", []),
        },
        message="Filter operation completed with empty source data.",
        target=target,
        meta={
            "degraded": True,
            "reason": reason,
            "record_count": 0,
        },
        errors=[],
        success=True,
    )


def normalize_target(target: Any) -> str:
    """
    normalize target ของ filter
    """

    target_text = clean_text_lower(target)
    target_text = target_text.replace("-", "_").replace(" ", "_")
    target_text = TARGET_ALIASES.get(target_text, target_text)

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

def normalize_filter_field_name(field_name: Any) -> str:
    """
    normalize field name แบบ canonical
    """

    text = clean_text(field_name)
    text = text.replace("-", "_").replace(" ", "_")
    key = clean_text_lower(text)
    candidates = FILTER_FIELD_ALIAS_CANDIDATES.get(key)

    if candidates:
        return candidates[0]

    return text


def get_filter_field_candidates(field_name: Any) -> List[str]:
    """
    คืน field candidates จาก alias route/frontend
    """

    text = clean_text(field_name)
    if not text:
        return []

    key = clean_text_lower(text.replace("-", "_").replace(" ", "_"))
    candidates = FILTER_FIELD_ALIAS_CANDIDATES.get(key)

    if candidates:
        return list(dict.fromkeys([clean_text(item) for item in candidates if clean_text(item)]))

    normalized = normalize_filter_field_name(text)
    return [normalized] if normalized else []


def normalize_filter_dict(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    normalize simple filter keys แต่ยังรักษา value เดิม
    """

    if not isinstance(filters, dict):
        return {}

    result: Dict[str, Any] = {}

    for field_name, value in filters.items():
        if value in (None, "", [], {}):
            continue

        field_text = clean_text(field_name)

        if field_text.endswith("_min"):
            normalized = f"{normalize_filter_field_name(field_text[:-4])}_min"
        elif field_text.endswith("_max"):
            normalized = f"{normalize_filter_field_name(field_text[:-4])}_max"
        else:
            normalized = normalize_filter_field_name(field_text)

        result[normalized] = value

    return result


def normalize_filter_group_fields(group: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    normalize field ใน advanced filter group
    """

    if not isinstance(group, dict):
        return {}

    result = deepcopy(group)

    conditions = result.get("conditions", [])
    if isinstance(conditions, list):
        normalized_conditions = []
        for condition in conditions:
            if not isinstance(condition, dict):
                continue

            if "field" in condition:
                item = dict(condition)
                item["field"] = normalize_filter_field_name(item.get("field"))
                normalized_conditions.append(item)
            elif "conditions" in condition or "groups" in condition:
                normalized_conditions.append(normalize_filter_group_fields(condition))

        result["conditions"] = normalized_conditions

    groups = result.get("groups", [])
    if isinstance(groups, list):
        result["groups"] = [
            normalize_filter_group_fields(item)
            for item in groups
            if isinstance(item, dict)
        ]

    return result

def normalize_filter_payload(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Normalize the shared filter payload without mutating the caller input.
    """

    warnings: List[Dict[str, Any]] = []

    if payload is None:
        raw_payload: Dict[str, Any] = {}
    elif isinstance(payload, dict):
        raw_payload = deepcopy(payload)
    else:
        raw_payload = {}
        warnings.append(
            {
                "type": "ValidationWarning",
                "field": "payload",
                "message": "payload must be a dictionary.",
            }
        )

    raw_target = raw_payload.get("target", DEFAULT_FILTER_TARGET)
    raw_target_key = clean_text_lower(raw_target).replace("-", "_").replace(" ", "_")
    target = normalize_target(raw_target)

    if raw_target_key and raw_target_key not in SUPPORTED_TARGETS and raw_target_key not in TARGET_ALIASES:
        warnings.append(
            {
                "type": "ValidationWarning",
                "field": "target",
                "message": "unknown target fallback to company.",
            }
        )

    filters = raw_payload.get("filters", {})
    if filters is None:
        filters = {}
    elif not isinstance(filters, dict):
        filters = {}
        warnings.append(
            {
                "type": "ValidationWarning",
                "field": "filters",
                "message": "filters must be a dictionary.",
            }
        )

    advanced = raw_payload.get("advanced", {})
    if advanced is None:
        advanced = {}
    elif not isinstance(advanced, dict):
        advanced = {}
        warnings.append(
            {
                "type": "ValidationWarning",
                "field": "advanced",
                "message": "advanced must be a dictionary.",
            }
        )

    normalized = {
        "target": target,
        "filters": normalize_filter_dict(filters),
        "advanced": normalize_filter_group_fields(advanced),
        "search": clean_text(raw_payload.get("search", "")),
        "sort_by": normalize_filter_field_name(raw_payload.get("sort_by", "")) if clean_text(raw_payload.get("sort_by", "")) else "",
        "sort_dir": normalize_sort_dir(raw_payload.get("sort_dir", "asc")),
        "page": normalize_page(raw_payload.get("page", 1)),
        "page_size": normalize_page_size(raw_payload.get("page_size", DEFAULT_TABLE_PAGE_SIZE)),
        "include_meta": bool(to_bool(raw_payload.get("include_meta", True), default=True)),
        "include_summary": bool(to_bool(raw_payload.get("include_summary", True), default=True)),
        "include_map": bool(to_bool(raw_payload.get("include_map", True), default=True)),
        "include_graph": bool(to_bool(raw_payload.get("include_graph", False), default=False)),
        "force_refresh": bool(to_bool(raw_payload.get("force_refresh", False), default=False)),
        "warnings": warnings,
        "raw_payload": to_jsonable(raw_payload),
    }

    return normalized



def validate_runtime_filter_payload(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate runtime filter structure while preserving field aliases."""

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if payload is None:
        return {"valid": True, "errors": [], "warnings": []}

    if not isinstance(payload, dict):
        return {
            "valid": False,
            "errors": [{"code": "invalid_filter_payload", "field": "payload", "message": "payload must be a dictionary."}],
            "warnings": [],
        }

    if "filters" in payload and payload.get("filters") is not None and not isinstance(payload.get("filters"), dict):
        errors.append({"code": "invalid_filters", "field": "filters", "message": "filters must be a dictionary."})

    advanced = payload.get("advanced")
    if advanced is not None and not isinstance(advanced, dict):
        errors.append({"code": "invalid_advanced_filter", "field": "advanced", "message": "advanced must be a dictionary."})
        advanced = None

    def walk_group(group: Dict[str, Any], path_prefix: str, depth: int = 0) -> None:
        if depth > 5:
            errors.append({"code": "filter_group_depth_exceeded", "field": path_prefix, "message": "advanced filter nesting exceeds the supported depth."})
            return

        logic = clean_text(group.get("logic", "AND")).upper() or "AND"
        if logic not in FILTER_LOGICAL_OPERATORS:
            errors.append({"code": "invalid_filter_logic", "field": f"{path_prefix}.logic", "message": f"unsupported logical operator: {logic}"})

        conditions = group.get("conditions", [])
        groups = group.get("groups", [])
        if not isinstance(conditions, list):
            errors.append({"code": "invalid_filter_conditions", "field": f"{path_prefix}.conditions", "message": "conditions must be a list."})
            conditions = []
        if not isinstance(groups, list):
            errors.append({"code": "invalid_filter_groups", "field": f"{path_prefix}.groups", "message": "groups must be a list."})
            groups = []

        for index, condition in enumerate(conditions):
            condition_path = f"{path_prefix}.conditions[{index}]"
            if not isinstance(condition, dict):
                errors.append({"code": "invalid_filter_condition", "field": condition_path, "message": "condition must be a dictionary."})
                continue

            if not clean_text(condition.get("field")) and ("conditions" in condition or "groups" in condition):
                walk_group(condition, condition_path, depth + 1)
                continue

            field_name = clean_text(condition.get("field"))
            if not field_name:
                errors.append({"code": "filter_field_missing", "field": condition_path, "message": "filter condition requires a field."})
                continue

            operator = normalize_operator(condition.get("operator") or condition.get("op") or "equals")
            if operator not in FILTER_OPERATORS:
                errors.append({"code": "invalid_filter_operator", "field": f"{condition_path}.operator", "message": f"unsupported filter operator: {operator}"})
                continue

            if operator in {"is_empty", "is_not_empty", "exists", "not_exists"}:
                continue

            value = condition.get("value")
            value_to = condition.get("value_to")
            if operator == "between":
                if isinstance(value, dict):
                    lower = value.get("min")
                    upper = value.get("max")
                else:
                    values = as_list(value)
                    lower = condition.get("min", values[0] if values else None)
                    upper = condition.get("max", values[1] if len(values) > 1 else value_to)
                if is_empty_value(lower) or is_empty_value(upper):
                    errors.append({"code": "between_value_incomplete", "field": f"{condition_path}.value", "message": "between requires both minimum and maximum values."})
            elif is_empty_value(value):
                errors.append({"code": "filter_value_missing", "field": f"{condition_path}.value", "message": "filter condition requires a non-empty value."})

        for index, child_group in enumerate(groups):
            child_path = f"{path_prefix}.groups[{index}]"
            if not isinstance(child_group, dict):
                errors.append({"code": "invalid_filter_group", "field": child_path, "message": "nested group must be a dictionary."})
                continue
            walk_group(child_group, child_path, depth + 1)

    if isinstance(advanced, dict) and advanced:
        walk_group(advanced, "advanced")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def normalize_filter_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Normalize non-route service context into filter payload form.
    """

    return normalize_filter_payload(context)


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

def field_group_for_name(field_name: str, target: str) -> str:
    target = normalize_target(target)
    field_name = normalize_filter_field_name(field_name)

    if target in {"policy"} or field_name.startswith("policy_") or field_name in {"product", "subclass"}:
        return "policy"

    if target in {"linkage"} or "director" in field_name or "shared" in field_name or "edge" in field_name:
        return "linkage"

    if target == "director":
        return "director"

    if target in {"flood_prediction_latest", "flood_prediction_map", "prediction_map_view"}:
        return "prediction"

    if target in {"uploaded_entity_latest", "entity_overlay_view"} or field_name.startswith("entity_"):
        return "entity"

    if target in {"dashboard_province_insights", "flood_dashboard_view", "province_insight_view"}:
        return "dashboard"

    if target in {"flood", "flood_rainfall_latest", "flood_waterlevel_latest", "flood_dam_latest"}:
        return "flood"

    if "risk" in field_name or "flood" in field_name or "station" in field_name or "dam" in field_name:
        return "flood"

    if target == "spatial" or field_name in {"province", "district", "subdistrict", "lat", "lon", "latitude", "longitude"}:
        return "location"

    if target in {"map", "map_layers"} or field_name in {"layer_id", "feature_type", "marker_size", "marker_color", "object_type", "source_type"}:
        return "map"

    if target == "data_quality":
        return "data_quality"

    if target == "package":
        return "package"

    if field_name in {"total_premium", "total_loss", "total_suminsure", "loss_ratio", "registered_capital", "most_recent_income_val"}:
        return "company_financial"

    return "company_identity"

def build_field_object(field_name: str, target: str) -> Dict[str, Any]:
    field_def = FIELD_DEFINITIONS.get(field_name) if isinstance(FIELD_DEFINITIONS, dict) else None
    dtype = getattr(field_def, "dtype", None) or (field_def.get("dtype") if isinstance(field_def, dict) else None) or get_field_dtype(field_name)
    label = getattr(field_def, "label", None) or (field_def.get("label") if isinstance(field_def, dict) else None) or field_name.replace("_", " ").title()
    description = getattr(field_def, "description", None) or (field_def.get("description") if isinstance(field_def, dict) else None) or ""
    options = getattr(field_def, "allowed_values", None) or (field_def.get("allowed_values") if isinstance(field_def, dict) else None) or []
    operators = ["equals", "not_equals", "in", "not_in", "is_empty", "is_not_empty"]
    if dtype in {"number", "float", "integer", "int", "date", "datetime"}:
        operators.extend(["gt", "gte", "lt", "lte", "between"])
    if dtype in {"string", "text", ""}:
        operators.extend(["contains", "not_contains", "startswith", "endswith"])
    return {
        "name": field_name,
        "label": label,
        "description": description,
        "dtype": dtype or "string",
        "group": field_group_for_name(field_name, target),
        "target": target,
        "filterable": True,
        "sortable": True,
        "searchable": field_name in SEARCHABLE_FIELDS_BY_TARGET.get(target, []),
        "operators": sorted(set(operators), key=operators.index),
        "options": options,
        "visible_default": True,
        "source": "schemas" if field_def else "fallback",
    }


def build_filter_field_groups() -> List[Dict[str, Any]]:
    groups = []
    for index, group_id in enumerate(FILTER_FIELD_GROUPS):
        groups.append(
            {
                "group_id": group_id,
                "label": group_id.replace("_", " ").title(),
                "sort_order": index + 1,
            }
        )
    return groups


def get_filter_fields(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/filter/fields

    คืน field ทั้งหมดที่ filter ได้
    พร้อม group, operator, table view schema
    """

    ctx = normalize_filter_context(context)
    fields: List[Dict[str, Any]] = []
    targets = list(SUPPORTED_TARGETS)
    for target in targets:
        target_fields = get_target_fields(target)
        if not target_fields:
            target_fields = FALLBACK_FIELDS_BY_TARGET.get(target, [])
        for field_name in target_fields:
            fields.append(build_field_object(clean_text(field_name), target))

    data = {
        "targets": targets,
        "groups": build_filter_field_groups(),
        "fields": fields,
        "operators": list(FILTER_OPERATORS),
        "logical_operators": FILTER_LOGICAL_OPERATORS,
        "filterable_by_target": {
            target: [field["name"] for field in fields if field["target"] == target]
            for target in targets
        },
        "table_views": TABLE_VIEW_SCHEMAS,
        "payload_example": FILTER_PAYLOAD_EXAMPLE,
        "meta": {
            "field_count": len(fields),
            "group_count": len(FILTER_FIELD_GROUPS),
            "schema_loaded": SCHEMAS_LOADED,
            "config_loaded": CONFIG_LOADED,
        },
    }
    return make_filter_response(data=data, message="Filter fields loaded.", target=ctx["target"], meta={"record_count": len(fields)})


def fallback_quick_filter_presets() -> Dict[str, Dict[str, Any]]:
    def preset(preset_id: str, label: str, target: str, filters: Dict[str, Any], group: str, sort_order: int) -> Dict[str, Any]:
        return {
            "preset_id": preset_id,
            "label": label,
            "description": label,
            "target": target,
            "payload": normalize_filter_payload(
                {
                    "target": target,
                    "filters": filters,
                    "advanced": {},
                    "search": "",
                    "sort_by": "",
                    "sort_dir": "desc",
                    "page": 1,
                    "page_size": DEFAULT_TABLE_PAGE_SIZE,
                }
            ),
            "group": group,
            "enabled": True,
            "sort_order": sort_order,
        }

    return {
        "high_policy_exposure": preset("high_policy_exposure", "High Policy Exposure", "company", {"total_suminsure": {"operator": "gte", "value": 1000000}}, "policy", 10),
        "high_loss_ratio": preset("high_loss_ratio", "High Loss Ratio", "company", {"loss_ratio": {"operator": "gte", "value": 50}}, "policy", 20),
        "active_policy": preset("active_policy", "Active Policy", "policy", {"policy_status_now": "active"}, "policy", 30),
        "expired_policy": preset("expired_policy", "Expired Policy", "policy", {"policy_status_now": "expired"}, "policy", 40),
        "wtip_companies": preset("wtip_companies", "WTIP Companies", "company", {"wtip": {"operator": "is_not_empty"}}, "company", 50),
        "missing_policy": preset("missing_policy", "Missing Policy", "company", {"has_policy": False}, "data_quality", 60),
        "missing_linkage": preset("missing_linkage", "Missing Linkage", "company", {"has_linkage": False}, "data_quality", 70),
        "missing_location": preset("missing_location", "Missing Location", "company", {"has_location": False}, "data_quality", 80),
        "invalid_tax_id": preset("invalid_tax_id", "Invalid Tax ID", "data_quality", {"issue_type": "invalid_tax_id"}, "data_quality", 90),

        "critical_flood_risk": preset("critical_flood_risk", "Critical Flood Risk", "company", {"risk": ["Critical", "critical"]}, "flood", 100),
        "warning_flood_risk": preset("warning_flood_risk", "Warning Flood Risk", "company", {"risk": ["Warning", "High"]}, "flood", 110),
        "companies_in_flood_area": preset("companies_in_flood_area", "Companies In Flood Area", "company", {"has_flood_context": True}, "flood", 120),
        "high_suminsure_in_flood_risk": preset("high_suminsure_in_flood_risk", "High Sum Insure In Flood Risk", "company", {"total_suminsure": {"operator": "gte", "value": 1000000}, "risk": ["Warning", "Critical", "High"]}, "flood", 130),

        "rainfall_warning": preset("rainfall_warning", "Rainfall Warning", "flood_rainfall_latest", {"risk": ["Warning", "Critical", "High"]}, "flood", 140),
        "waterlevel_warning": preset("waterlevel_warning", "Waterlevel Warning", "flood_waterlevel_latest", {"risk": ["Warning", "Critical", "High"]}, "flood", 150),
        "dam_warning": preset("dam_warning", "Dam Warning", "flood_dam_latest", {"risk": ["Warning", "Critical", "High"]}, "flood", 160),
        "prediction_critical": preset("prediction_critical", "Prediction Critical", "flood_prediction_latest", {"risk": ["Critical", "critical"]}, "prediction", 170),
        "prediction_warning": preset("prediction_warning", "Prediction Warning", "flood_prediction_latest", {"risk": ["Warning", "High"]}, "prediction", 180),
        "prediction_map_ready": preset("prediction_map_ready", "Prediction Map Ready", "flood_prediction_map", {"map_ready": True}, "prediction", 190),
        "prediction_missing_location": preset("prediction_missing_location", "Prediction Missing Location", "flood_prediction_map", {"map_ready": False}, "prediction", 200),
        "entity_overlay_displayable": preset("entity_overlay_displayable", "Entity Overlay Displayable", "uploaded_entity_latest", {"has_location": True}, "entity", 210),
        "entity_overlay_high_risk": preset("entity_overlay_high_risk", "Entity Overlay High Risk", "uploaded_entity_latest", {"risk": ["Critical", "Warning", "High"]}, "entity", 220),
        "province_insight_prediction": preset("province_insight_prediction", "Province Insight Prediction", "dashboard_province_insights", {"mode": "prediction"}, "dashboard", 230),

        "key_connectors": preset("key_connectors", "Key Connectors", "linkage", {"is_key_connector": True}, "linkage", 240),
        "high_director_connectivity": preset("high_director_connectivity", "High Director Connectivity", "director", {"company_count": {"operator": "gte", "value": 3}}, "director", 250),
        "shared_director_network": preset("shared_director_network", "Shared Director Network", "linkage", {"shared_director_count": {"operator": "gte", "value": 1}}, "linkage", 260),
        "data_quality_critical": preset("data_quality_critical", "Data Quality Critical", "data_quality", {"severity": "critical"}, "data_quality", 270),
        "data_quality_warning": preset("data_quality_warning", "Data Quality Warning", "data_quality", {"severity": "warning"}, "data_quality", 280),
    }

def get_quick_filter_presets(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/filter/quick-presets

    คืน preset สำเร็จรูปสำหรับ frontend
    """

    ctx = normalize_filter_context(context)
    source_presets = QUICK_FILTER_PRESETS if isinstance(QUICK_FILTER_PRESETS, dict) and QUICK_FILTER_PRESETS else fallback_quick_filter_presets()
    presets: List[Dict[str, Any]] = []

    for index, (preset_id, preset_value) in enumerate(source_presets.items()):
        item = dict(preset_value or {})
        item["preset_id"] = item.get("preset_id") or preset_id
        item["label"] = item.get("label") or item["preset_id"].replace("_", " ").title()
        item["description"] = item.get("description", "")
        item["target"] = normalize_target(item.get("target", DEFAULT_FILTER_TARGET))
        item["payload"] = normalize_filter_payload(item.get("payload") or {"target": item["target"], "filters": item.get("filters", {})})
        item["group"] = item.get("group") or item["target"]
        item["enabled"] = bool(to_bool(item.get("enabled", True), default=True))
        item["sort_order"] = int(to_number(item.get("sort_order"), index + 1) or index + 1)
        presets.append(to_jsonable(item))

    presets = sorted(presets, key=lambda item: item.get("sort_order", 9999))

    return make_filter_response(
        data={"presets": presets, "total": len(presets)},
        message="Quick filter presets loaded.",
        target=ctx["target"],
        meta={"record_count": len(presets)},
    )

def get_field_dtype(field_name: str) -> str:
    """
    คืน dtype ของ field จาก schemas.py + override ของ runtime flood/entity/map
    """

    normalized_name = normalize_filter_field_name(field_name)

    if normalized_name in FIELD_DTYPE_OVERRIDES:
        return FIELD_DTYPE_OVERRIDES[normalized_name]

    field_def = FIELD_DEFINITIONS.get(normalized_name)

    if not field_def:
        return "string"

    if isinstance(field_def, dict):
        return clean_text(field_def.get("dtype"), default="string")

    return clean_text(getattr(field_def, "dtype", "string"), default="string")


def get_field_allowed_values(field_name: str) -> List[Any]:
    """
    คืน allowed values ของ field
    """

    field_def = FIELD_DEFINITIONS.get(field_name)

    if not field_def:
        return []

    if isinstance(field_def, dict):
        return field_def.get("allowed_values") or field_def.get("options") or []

    return getattr(field_def, "allowed_values", None) or []


def get_target_fields(target: str) -> List[str]:
    """
    คืน field ที่เกี่ยวข้องกับ target
    """

    target = normalize_target(target)

    if target in FILTERABLE_FIELDS:
        return list(dict.fromkeys([normalize_filter_field_name(field) for field in FILTERABLE_FIELDS[target]]))

    if target in FALLBACK_FIELDS_BY_TARGET:
        return list(dict.fromkeys([normalize_filter_field_name(field) for field in FALLBACK_FIELDS_BY_TARGET[target]]))

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

    fields = []
    for key, field in FIELD_DEFINITIONS.items():
        if isinstance(field, dict):
            if field.get("filterable", True):
                fields.append(clean_text(field.get("name") or key))
        elif getattr(field, "filterable", True):
            fields.append(clean_text(getattr(field, "name", key)))

    return fields or list(FALLBACK_FIELDS_BY_TARGET.get(DEFAULT_FILTER_TARGET, []))


# ============================================================
# 4) VALUE COMPARISON HELPERS
# ============================================================

def normalize_operator(operator: Any) -> str:
    value = clean_text_lower(operator or "equals")
    return OPERATOR_ALIASES.get(value, value)


def normalize_string(value: Any) -> str:
    return clean_text(value).strip()


def to_comparable_number(value: Any) -> Optional[float]:
    return to_number(value, default=None)


def to_comparable_datetime(value: Any) -> Any:
    return to_datetime(value, default=None)


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, str) and "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def value_to_list(value: Any) -> List[Any]:
    return as_list(value)


def normalize_value_for_compare(value: Any) -> Any:
    if is_empty_value(value):
        return None
    if isinstance(value, bool):
        return value
    number = to_comparable_number(value)
    if number is not None:
        return number
    dt_value = to_comparable_datetime(value)
    if dt_value is not None:
        return dt_value
    return normalize_string(value)


def normalize_compare_value(value: Any, dtype: str = "string") -> Any:
    dtype = clean_text_lower(dtype)
    if is_empty_value(value):
        return None
    if dtype in {"number", "float", "integer", "int"}:
        return to_comparable_number(value)
    if dtype in {"boolean", "bool"}:
        return to_bool(value, default=None)
    if dtype in {"date", "datetime"}:
        return to_comparable_datetime(value)
    if dtype in {"array", "list"}:
        return as_list(value)
    return clean_text_lower(value)



def comparable_pair(left: Any, right: Any) -> Tuple[Any, Any]:
    left_number = to_comparable_number(left)
    right_number = to_comparable_number(right)
    if left_number is not None and right_number is not None:
        return left_number, right_number

    left_dt = to_comparable_datetime(left)
    right_dt = to_comparable_datetime(right)
    if left_dt is not None and right_dt is not None:
        return left_dt, right_dt

    return clean_text_lower(left), clean_text_lower(right)


def compare_values(
    record_value: Any,
    operator: str,
    expected_value: Any = None,
    expected_value_to: Any = None,
    dtype: str = "string",
) -> bool:
    operator = normalize_operator(operator)

    if operator not in FILTER_OPERATORS:
        return False

    if operator == "is_empty":
        return is_empty_value(record_value)
    if operator in {"is_not_empty", "exists"}:
        return not is_empty_value(record_value)
    if operator == "not_exists":
        return is_empty_value(record_value)

    if operator == "equals":
        return normalize_compare_value(record_value, dtype) == normalize_compare_value(expected_value, dtype)
    if operator == "not_equals":
        return not compare_values(record_value, "equals", expected_value, dtype=dtype)

    if operator == "contains":
        if is_empty_value(record_value) or is_empty_value(expected_value):
            return False
        expected_values = [clean_text_lower(item) for item in as_list(expected_value)]
        if isinstance(record_value, (list, tuple, set)):
            record_values = [clean_text_lower(item) for item in record_value]
            return any(expected in record_values for expected in expected_values)
        haystack = clean_text_lower(record_value)
        return any(expected in haystack for expected in expected_values)
    if operator == "not_contains":
        return not compare_values(record_value, "contains", expected_value, dtype=dtype)
    if operator == "startswith":
        return not is_empty_value(expected_value) and clean_text_lower(record_value).startswith(clean_text_lower(expected_value))
    if operator == "endswith":
        return not is_empty_value(expected_value) and clean_text_lower(record_value).endswith(clean_text_lower(expected_value))

    if operator in {"in", "not_in"}:
        expected_list = as_list(expected_value)
        if not expected_list:
            return operator == "not_in"
        expected_normalized = [normalize_compare_value(item, dtype) for item in expected_list]
        if isinstance(record_value, (list, tuple, set)):
            matched = any(normalize_compare_value(item, dtype) in expected_normalized for item in record_value)
        else:
            matched = normalize_compare_value(record_value, dtype) in expected_normalized
        return matched if operator == "in" else not matched

    if operator in {"gt", "gte", "lt", "lte"}:
        left = normalize_compare_value(record_value, dtype)
        right = normalize_compare_value(expected_value, dtype)
        if left is None or right is None:
            return False
        try:
            if operator == "gt":
                return left > right
            if operator == "gte":
                return left >= right
            if operator == "lt":
                return left < right
            return left <= right
        except TypeError:
            return False

    if operator == "between":
        if isinstance(expected_value, dict):
            min_value = expected_value.get("min")
            max_value = expected_value.get("max")
        else:
            values = as_list(expected_value)
            min_value = values[0] if values else None
            max_value = values[1] if len(values) > 1 else expected_value_to
        if is_empty_value(min_value) or is_empty_value(max_value):
            return False
        left = normalize_compare_value(record_value, dtype)
        lower = normalize_compare_value(min_value, dtype)
        upper = normalize_compare_value(max_value, dtype)
        if left is None or lower is None or upper is None:
            return False
        try:
            return lower <= left <= upper
        except TypeError:
            return False

    return False



# ============================================================
# 5) CONDITION / GROUP EVALUATION
# ============================================================

def evaluate_condition(record: Dict[str, Any], condition: Dict[str, Any]) -> bool:
    """
    evaluate condition 1 อันกับ record 1 แถว
    """

    if not isinstance(condition, dict):
        return False

    field_name = clean_text(condition.get("field"))
    operator = normalize_operator(condition.get("operator") or condition.get("op") or "equals")
    expected_value = condition.get("value")
    expected_value_to = condition.get("value_to") or condition.get("max")
    dtype = clean_text(condition.get("dtype") or get_field_dtype(field_name))

    if not field_name:
        return False

    if operator == "between" and isinstance(expected_value, dict):
        expected_value_to = expected_value.get("max")
    elif operator == "between" and "min" in condition and "max" in condition:
        expected_value = condition.get("min")
        expected_value_to = condition.get("max")

    candidates = get_filter_field_candidates(field_name)

    for candidate in candidates:
        if compare_values(
            record_value=record.get(candidate),
            operator=operator,
            expected_value=expected_value,
            expected_value_to=expected_value_to,
            dtype=dtype,
        ):
            return True

    return False


def evaluate_filter_group(record: Dict[str, Any], group: Dict[str, Any], depth: int = 0, max_depth: int = 5) -> bool:
    """Evaluate a nested advanced-filter group."""

    if not isinstance(group, dict) or not group:
        return True
    if depth > max_depth:
        return False

    logic = clean_text(group.get("logic", "AND")).upper() or "AND"
    if logic not in FILTER_LOGICAL_OPERATORS:
        return False

    conditions = group.get("conditions", [])
    groups = group.get("groups", [])
    if not isinstance(conditions, list) or not isinstance(groups, list):
        return False

    results: List[bool] = []
    for condition in conditions:
        if isinstance(condition, dict) and not clean_text(condition.get("field")) and ("conditions" in condition or "groups" in condition):
            results.append(evaluate_filter_group(record, condition, depth=depth + 1, max_depth=max_depth))
        else:
            results.append(evaluate_condition(record, condition))

    for child_group in groups:
        results.append(evaluate_filter_group(record, child_group, depth=depth + 1, max_depth=max_depth))

    if not results:
        return True
    return any(results) if logic == "OR" else all(results)



def evaluate_advanced_group(record: Dict[str, Any], group: Dict[str, Any], depth: int = 0) -> bool:
    return evaluate_filter_group(record, group, depth=depth)


def evaluate_simple_filter(record: Dict[str, Any], field_name: str, value: Any) -> bool:
    key_text = clean_text(field_name)

    if key_text.endswith("_min"):
        base_field = key_text[:-4]
        return any(
            compare_values(record.get(candidate), "gte", value, dtype=get_field_dtype(candidate))
            for candidate in get_filter_field_candidates(base_field)
        )

    if key_text.endswith("_max"):
        base_field = key_text[:-4]
        return any(
            compare_values(record.get(candidate), "lte", value, dtype=get_field_dtype(candidate))
            for candidate in get_filter_field_candidates(base_field)
        )

    candidates = get_filter_field_candidates(key_text)

    if isinstance(value, dict):
        if "operator" in value or "op" in value:
            return any(
                compare_values(
                    record.get(candidate),
                    value.get("operator") or value.get("op") or "equals",
                    value.get("value"),
                    value.get("value_to") or value.get("max"),
                    dtype=get_field_dtype(candidate),
                )
                for candidate in candidates
            )

        if "min" in value or "max" in value:
            return any(
                compare_values(
                    record.get(candidate),
                    "between",
                    {"min": value.get("min"), "max": value.get("max")},
                    dtype=get_field_dtype(candidate),
                )
                for candidate in candidates
            )

    if isinstance(value, list):
        return any(
            compare_values(record.get(candidate), "in", value, dtype=get_field_dtype(candidate))
            for candidate in candidates
        )

    return any(
        compare_values(record.get(candidate), "equals", value, dtype=get_field_dtype(candidate))
        for candidate in candidates
    )


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

            if not evaluate_simple_filter(record, key, value):
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


def apply_simple_filters_to_records(records: List[Dict[str, Any]], filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return apply_simple_filters(records, filters)


def apply_advanced_filters_to_records(records: List[Dict[str, Any]], advanced: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return apply_advanced_filter(records, advanced)


def apply_search_to_records(records: List[Dict[str, Any]], search: Any, target: Optional[str] = None) -> List[Dict[str, Any]]:
    if not clean_text(search):
        return list(records or [])
    target_key = normalize_target(target)
    fields = get_searchable_fields_for_target(target_key)
    if records:
        available_fields = {key for record in records[:100] for key in record.keys()}
        fields = [field for field in fields if field in available_fields]
    if not fields and records:
        fields = sorted(
            {
                key
                for record in records[:100]
                for key, value in record.items()
                if isinstance(value, (str, int, float, bool))
            }
        )
    needle = clean_text_lower(search)
    return [
        record
        for record in records or []
        if any(needle in clean_text_lower(record.get(field)) for field in fields)
    ]


def sort_key_value(value: Any) -> Tuple[bool, int, Any]:
    if is_empty_value(value):
        return True, 3, ""
    number = to_comparable_number(value)
    if number is not None:
        return False, 0, number
    dt_value = to_comparable_datetime(value)
    if dt_value is not None:
        return False, 1, dt_value
    return False, 2, clean_text_lower(value)


def apply_sort_to_records(records: List[Dict[str, Any]], sort_by: Any, sort_dir: Any = "asc") -> List[Dict[str, Any]]:
    field_name = clean_text(sort_by)
    if not field_name:
        return list(records or [])
    reverse = normalize_sort_dir(sort_dir) == "desc"
    sortable = []
    empty = []
    for record in list(records or []):
        if is_empty_value(record.get(field_name)):
            empty.append(record)
        else:
            sortable.append(record)
    return sorted(sortable, key=lambda record: sort_key_value(record.get(field_name)), reverse=reverse) + empty


def apply_pagination_to_records(records: List[Dict[str, Any]], page: Any, page_size: Any) -> Dict[str, Any]:
    normalized_page = normalize_page(page)
    normalized_page_size = normalize_page_size(page_size)
    total = len(records or [])
    total_pages = math.ceil(total / normalized_page_size) if total else 0
    start = (normalized_page - 1) * normalized_page_size
    paged_records = list(records or [])[start:start + normalized_page_size]
    return {
        "records": paged_records,
        "total": total,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "total_pages": total_pages,
        "returned_count": len(paged_records),
        "has_next": bool(total_pages and normalized_page < total_pages),
        "has_prev": bool(total_pages and normalized_page > 1),
    }


def count_advanced_conditions(group: Any, depth: int = 0, max_depth: int = 5) -> int:
    if not isinstance(group, dict) or depth > max_depth:
        return 0
    count = 0
    for condition in group.get("conditions", []) or []:
        if isinstance(condition, dict) and "conditions" in condition and not condition.get("field"):
            count += count_advanced_conditions(condition, depth + 1, max_depth)
        elif isinstance(condition, dict):
            count += 1
    for child in group.get("groups", []) or []:
        count += count_advanced_conditions(child, depth + 1, max_depth)
    return count


def build_filter_summary(payload: Optional[Dict[str, Any]], result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = normalize_filter_payload(payload)
    filters = normalized.get("filters", {})
    advanced = normalized.get("advanced", {})
    parts = []
    for field_name, value in filters.items():
        if isinstance(value, dict):
            operator = normalize_operator(value.get("operator") or value.get("op") or ("between" if "min" in value or "max" in value else "equals"))
            display_value = value.get("value", value)
        elif isinstance(value, list):
            operator = "in"
            display_value = "/".join(clean_text(item) for item in value[:5])
        else:
            operator = "equals"
            display_value = value
        parts.append(f"{field_name} {operator} {clean_text(display_value)}")
    human_label = f"{normalized['target'].title()} filter"
    if parts:
        human_label += ": " + ", ".join(parts[:5])
    if normalized.get("search"):
        human_label += f" search '{normalized['search']}'"

    result = result or {}
    return {
        "target": normalized["target"],
        "simple_filter_count": len(filters),
        "advanced_condition_count": count_advanced_conditions(advanced),
        "search": normalized.get("search", ""),
        "sort_by": normalized.get("sort_by", ""),
        "sort_dir": normalized.get("sort_dir", "asc"),
        "page": normalized.get("page", 1),
        "page_size": normalized.get("page_size", DEFAULT_TABLE_PAGE_SIZE),
        "source_record_count": result.get("source_record_count", 0),
        "filtered_record_count": result.get("filtered_record_count", result.get("total", 0)),
        "returned_count": result.get("returned_count", len(result.get("records", []) or [])),
        "human_label": human_label,
    }


def run_filter_pipeline(records: List[Dict[str, Any]], payload: Optional[Dict[str, Any]] = None, target: Optional[str] = None) -> Dict[str, Any]:
    normalized = normalize_filter_payload(payload)
    if target:
        normalized["target"] = normalize_target(target)

    source_records = records_to_record_list(records, target=normalized["target"])
    source_record_count = len(source_records)

    filtered = apply_simple_filters_to_records(source_records, normalized.get("filters", {}))
    filtered = apply_advanced_filters_to_records(filtered, normalized.get("advanced", {}))
    filtered = apply_search_to_records(filtered, normalized.get("search", ""), normalized["target"])
    filtered = apply_sort_to_records(filtered, normalized.get("sort_by", ""), normalized.get("sort_dir", "asc"))

    filtered_record_count = len(filtered)
    page_result = apply_pagination_to_records(filtered, normalized.get("page", 1), normalized.get("page_size", DEFAULT_TABLE_PAGE_SIZE))
    result = {
        "target": normalized["target"],
        **page_result,
        "source_record_count": source_record_count,
        "filtered_record_count": filtered_record_count,
        "filter_summary": {},
        "warnings": normalized.get("warnings", []),
        "filter": normalized,
    }
    result["filter_summary"] = build_filter_summary(normalized, result)
    return to_jsonable(result)


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
    if not paginate:
        normalized["page"] = 1
        normalized["page_size"] = MAX_TABLE_PAGE_SIZE
    result = run_filter_pipeline(records, normalized, target=normalized.get("target"))
    result["filtered_total"] = result.get("filtered_record_count", result.get("total", 0))
    if not paginate:
        result["records"] = apply_sort_to_records(
            apply_search_to_records(
                apply_advanced_filters_to_records(
                    apply_simple_filters_to_records(records_to_record_list(records, target=normalized.get("target")), normalized.get("filters", {})),
                    normalized.get("advanced", {}),
                ),
                normalized.get("search", ""),
                normalized.get("target"),
            ),
            normalized.get("sort_by", ""),
            normalized.get("sort_dir", "asc"),
        )
        result["total"] = len(result["records"])
        result["returned_count"] = len(result["records"])
        result["total_pages"] = 1 if result["records"] else 0
    return result


# ============================================================
# 6) DATA LOADING FOR FILTER ENGINE
# ============================================================

def extract_records_from_cache_payload(payload: Any, target: Optional[str] = None) -> List[Dict[str, Any]]:
    """Extract record dictionaries from common service and cache wrappers."""

    records: List[Dict[str, Any]] = []

    def append_items(items: Any, record_kind: str = "") -> None:
        if isinstance(items, dict):
            iterable: Iterable[Any] = [items]
        elif isinstance(items, (list, tuple, set)):
            iterable = items
        elif isinstance(items, Iterable) and not isinstance(items, (str, bytes, bytearray)):
            iterable = items
        else:
            return
        for item in iterable:
            if not isinstance(item, dict):
                continue
            record = dict(item)
            if record_kind and "record_kind" not in record:
                record["record_kind"] = record_kind
            records.append(record)

    if isinstance(payload, (list, tuple, set)):
        append_items(payload)
        return records
    if not isinstance(payload, dict):
        return []

    for key in ["records", "items", "companies", "issues", "packages"]:
        if key in payload:
            append_items(payload.get(key), key[:-1] if key.endswith("s") else key)
            if records:
                return records

    data = payload.get("data")
    if isinstance(data, (list, tuple, set)):
        append_items(data)
        return records
    if isinstance(data, dict):
        nested = extract_records_from_cache_payload(data, target=target)
        if nested:
            return nested

    if "nodes" in payload or "edges" in payload:
        append_items(payload.get("nodes", []), "node")
        append_items(payload.get("edges", []), "edge")
        if records:
            return records

    layers = payload.get("layers")
    if isinstance(layers, dict):
        layer_iterable = layers.values()
    elif isinstance(layers, (list, tuple)):
        layer_iterable = layers
    else:
        layer_iterable = []

    for layer in layer_iterable:
        if not isinstance(layer, dict):
            continue
        layer_id = clean_text(layer.get("layer_id"))
        feature_collection = layer.get("features") or layer.get("feature_collection")
        if isinstance(feature_collection, dict) and isinstance(feature_collection.get("features"), list):
            for feature in feature_collection["features"]:
                if not isinstance(feature, dict):
                    continue
                properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                record = {"record_kind": "map_feature", "layer_id": layer_id, "feature_type": properties.get("feature_type"), **properties}
                geometry = feature.get("geometry")
                if isinstance(geometry, dict):
                    record["geometry_type"] = geometry.get("type")
                    record["coordinates"] = geometry.get("coordinates")
                records.append(record)
    if records:
        return records

    features = payload.get("features")
    if isinstance(features, dict) and features.get("type") == "FeatureCollection":
        for feature in features.get("features", []):
            if isinstance(feature, dict):
                properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                records.append({"record_kind": "map_feature", **properties})
        return records

    for key in ["cards", "charts", "summary"]:
        value = payload.get(key)
        if isinstance(value, (list, tuple)):
            append_items(value, key[:-1] if key.endswith("s") else key)
        elif isinstance(value, dict):
            for item_key, item_value in value.items():
                if isinstance(item_value, dict):
                    records.append({"record_kind": key, "key": item_key, **item_value})
                else:
                    records.append({"record_kind": key, "key": item_key, "value": item_value})
    return records



def normalize_cache_payload_to_records(payload: Any, target: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Public wrapper for cache payload extraction.
    """

    return to_jsonable(extract_records_from_cache_payload(payload, target=target))


def records_to_record_list(records: Any, target: Optional[str] = None) -> List[Dict[str, Any]]:
    """Convert supported service/cache inputs to a detached record list."""

    if records is None:
        return []
    if isinstance(records, dict):
        if not records:
            return []
        extracted = extract_records_from_cache_payload(records, target=target)
        if extracted:
            return [dict(record) for record in extracted]
        return [dict(records)]
    if isinstance(records, (list, tuple, set)):
        return [dict(record) for record in records if isinstance(record, dict)]
    if isinstance(records, Iterable) and not isinstance(records, (str, bytes, bytearray)) and not hasattr(records, "to_dict"):
        return [dict(record) for record in records if isinstance(record, dict)]
    if hasattr(records, "empty") and hasattr(records, "to_dict"):
        return [dict(record) for record in dataframe_to_records(records) if isinstance(record, dict)]
    return []


def extract_dashboard_insight_records(payload: Any) -> List[Dict[str, Any]]:
    """
    แปลง dashboard province insight payload เป็น records สำหรับ filter
    """

    records: List[Dict[str, Any]] = []

    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        source = payload["data"]
    elif isinstance(payload, dict):
        source = payload
    else:
        return records

    insight_keys = [
        "prediction_risk_top3",
        "top_prediction_risk_provinces",
        "rainfall_top5",
        "rainfall_ranking",
        "waterlevel_top5",
        "waterlevel_ranking",
        "reservoir_top5",
        "reservoir_ranking",
    ]

    for key in insight_keys:
        items = source.get(key)
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            record = deepcopy(item)
            record["record_kind"] = "dashboard_province_insight"
            record["insight_key"] = key

            focus = record.get("focus")
            if isinstance(focus, dict):
                record["mode"] = clean_text(focus.get("mode"))
                record["focus_type"] = clean_text(focus.get("type"))
                record["focus_province"] = clean_text(focus.get("province"))

            records.append(record)

    return records


def extract_map_layer_records(payload: Any) -> List[Dict[str, Any]]:
    """
    แปลง map layer payload เป็น records สำหรับ filter
    """

    records: List[Dict[str, Any]] = []

    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        source = payload["data"]
    elif isinstance(payload, dict):
        source = payload
    else:
        return records

    layers = source.get("layers")

    if isinstance(layers, dict):
        iterable = layers.items()
    elif isinstance(layers, list):
        iterable = [(clean_text(item.get("layer_id")) if isinstance(item, dict) else "", item) for item in layers]
    else:
        iterable = []

    for layer_id, layer in iterable:
        if not isinstance(layer, dict):
            continue

        record = {
            "record_kind": "map_layer",
            "layer_id": clean_text(layer.get("layer_id") or layer_id),
            "layer_name": clean_text(layer.get("layer_name") or layer.get("name") or layer_id),
            "source_type": clean_text(layer.get("source_type") or layer.get("source")),
            "record_count": to_number(layer.get("record_count") or layer.get("count"), 0) or 0,
            "feature_type": clean_text(layer.get("feature_type") or layer.get("type")),
            "enabled": to_bool(layer.get("enabled"), default=True),
            "visible": to_bool(layer.get("visible"), default=True),
        }
        records.append(record)

        feature_collection = layer.get("features") or layer.get("feature_collection")
        if isinstance(feature_collection, dict) and isinstance(feature_collection.get("features"), list):
            for feature in feature_collection["features"]:
                if not isinstance(feature, dict):
                    continue

                props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                feature_record = {
                    "record_kind": "map_feature",
                    "layer_id": record["layer_id"],
                    "layer_name": record["layer_name"],
                    **props,
                }
                records.append(feature_record)

    return records

def load_records_from_cache_key(cache_key: str) -> List[Dict[str, Any]]:
    """
    โหลด records จาก cache key

    รองรับ:
    - records/list/items
    - graph nodes/edges
    - map layers/features
    - dashboard province insights
    """

    path = get_cache_file_path(cache_key)

    if not path.exists():
        return []

    data = read_json(path, default={})

    records = normalize_cache_payload_to_records(data, target=cache_key)
    if records:
        return records

    insight_records = extract_dashboard_insight_records(data)
    if insight_records:
        return insight_records

    map_records = extract_map_layer_records(data)
    if map_records:
        return map_records

    return []


def load_target_records(target: str) -> List[Dict[str, Any]]:
    """
    โหลด records ตาม target จาก cache

    หมายเหตุ:
    filter_engine ไม่ควร import service หนักโดยตรง
    เพื่อลด circular import
    """

    target = normalize_target(target)
    cache_keys = TARGET_CACHE_KEY_CANDIDATES.get(target) or [TARGET_CACHE_KEYS.get(target, "")]

    for cache_key in cache_keys:
        if not cache_key:
            continue
        records = load_records_from_cache_key(cache_key)
        if records:
            return records

    return []


def get_searchable_fields_for_target(target: str) -> List[str]:
    """
    คืน searchable fields ตาม target
    """

    target = normalize_target(target)

    fields = get_target_fields(target)

    searchable: List[str] = []

    for field_name in fields:
        field_def = FIELD_DEFINITIONS.get(field_name)

        if isinstance(field_def, dict) and field_def.get("searchable", False):
            searchable.append(field_name)
        elif field_def and getattr(field_def, "searchable", False):
            searchable.append(field_name)

    if not searchable:
        searchable = SEARCHABLE_FIELDS_BY_TARGET.get(target, [])

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

    elif target in {"flood", "flood_rainfall_latest", "flood_waterlevel_latest", "flood_dam_latest", "flood_prediction_latest", "flood_prediction_map", "prediction_map_view"}:
        risk_counts: Dict[str, int] = {}
        province_counts: Dict[str, int] = {}

        for r in records:
            level = clean_text(
                r.get("risk_level")
                or r.get("risk_status")
                or r.get("warning_level")
                or r.get("warning_level_predict")
                or r.get("flood_risk_level"),
                default="Unknown",
            )
            province = clean_text(
                r.get("province")
                or r.get("province_model")
                or r.get("province_name_th"),
                default="Unknown",
            )
            risk_counts[level] = risk_counts.get(level, 0) + 1
            province_counts[province] = province_counts.get(province, 0) + 1

        summary.update(
            {
                "risk_counts": risk_counts,
                "province_counts": province_counts,
                "map_ready_count": sum(1 for r in records if to_bool(r.get("map_ready"), default=False)),
                "with_location_count": sum(
                    1
                    for r in records
                    if to_bool(r.get("has_location"), default=False)
                    or (not is_empty_value(r.get("latitude")) and not is_empty_value(r.get("longitude")))
                ),
            }
        )

    elif target in {"uploaded_entity_latest", "entity_overlay_view"}:
        entity_type_counts: Dict[str, int] = {}
        risk_counts: Dict[str, int] = {}

        for r in records:
            entity_type = clean_text(r.get("entity_type"), default="Unknown")
            risk = clean_text(r.get("risk_group") or r.get("risk_level"), default="Unknown")
            entity_type_counts[entity_type] = entity_type_counts.get(entity_type, 0) + 1
            risk_counts[risk] = risk_counts.get(risk, 0) + 1

        summary.update(
            {
                "entity_type_counts": entity_type_counts,
                "risk_counts": risk_counts,
                "displayable_count": sum(
                    1
                    for r in records
                    if not is_empty_value(r.get("latitude")) and not is_empty_value(r.get("longitude"))
                ),
            }
        )

    elif target in {"map", "map_layers"}:
        layer_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}

        for r in records:
            layer_id = clean_text(r.get("layer_id"), default="unknown")
            source_type = clean_text(r.get("source_type"), default="unknown")
            layer_counts[layer_id] = layer_counts.get(layer_id, 0) + 1
            source_counts[source_type] = source_counts.get(source_type, 0) + 1

        summary.update(
            {
                "layer_counts": layer_counts,
                "source_counts": source_counts,
                "feature_count": sum(1 for r in records if r.get("record_kind") == "map_feature"),
            }
        )

    elif target in {"dashboard", "dashboard_province_insights", "flood_dashboard_view", "province_insight_view"}:
        mode_counts: Dict[str, int] = {}
        province_counts: Dict[str, int] = {}

        for r in records:
            mode = clean_text(r.get("mode") or r.get("insight_key"), default="unknown")
            province = clean_text(r.get("province"), default="Unknown")
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
            province_counts[province] = province_counts.get(province, 0) + 1

        summary.update(
            {
                "mode_counts": mode_counts,
                "province_counts": province_counts,
                "critical_count": sum(1 for r in records if clean_text_lower(r.get("risk_level")) == "critical"),
                "warning_count": sum(1 for r in records if clean_text_lower(r.get("risk_level")) == "warning"),
            }
        )

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
    """Preview a filter request before applying it to the full result set."""

    validation = validate_runtime_filter_payload(payload)
    normalized = normalize_filter_payload(payload)
    target = normalized["target"]
    if not validation["valid"]:
        return make_filter_response(
            data={"target": target, "records": [], "sample_rows": [], "validation": validation},
            message="Filter payload validation failed.",
            target=target,
            meta={"status_code": 422, "record_count": 0},
            errors=validation["errors"],
            success=False,
        )

    records = load_target_records(target)
    if not records:
        return make_filter_response(
            data={
                "target": target,
                "sample_rows": [],
                "records": [],
                "source_record_count": 0,
                "filtered_record_count": 0,
                "preview_count": 0,
                "filter_summary": build_filter_summary(normalized, {}),
                "warnings": normalized.get("warnings", []) + validation.get("warnings", []),
            },
            message="Filter operation completed with empty source data.",
            target=target,
            meta={"degraded": True, "reason": "target cache missing or empty", "record_count": 0},
        )

    preview_payload = dict(normalized)
    preview_payload["page"] = 1
    preview_payload["page_size"] = min(10, normalized.get("page_size", DEFAULT_TABLE_PAGE_SIZE))
    result = run_filter_pipeline(records, preview_payload, target=target)
    sample_rows = result.get("records", [])[: min(10, preview_payload["page_size"])]
    return make_filter_response(
        data={
            "target": target,
            "sample_rows": sample_rows,
            "records": sample_rows,
            "source_record_count": result.get("source_record_count", 0),
            "filtered_record_count": result.get("filtered_record_count", 0),
            "preview_count": len(sample_rows),
            "filter_summary": result.get("filter_summary", {}),
            "warnings": result.get("warnings", []) + validation.get("warnings", []),
        },
        message="Filter preview completed.",
        target=target,
        meta={"record_count": len(sample_rows), "source_record_count": result.get("source_record_count", 0), "filtered_record_count": result.get("filtered_record_count", 0)},
    )



def apply_filter(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply a validated filter request and return a paginated result."""

    validation = validate_runtime_filter_payload(payload)
    normalized = normalize_filter_payload(payload)
    target = normalized["target"]
    if not validation["valid"]:
        return make_filter_response(
            data={"target": target, "records": [], "validation": validation},
            message="Filter payload validation failed.",
            target=target,
            meta={"status_code": 422, "record_count": 0},
            errors=validation["errors"],
            success=False,
        )

    records = load_target_records(target)
    if not records:
        return make_degraded_filter_response(target, "target cache missing or empty", normalized)

    result = run_filter_pipeline(records, normalized, target=target)
    return make_filter_response(
        data={
            "target": target,
            "records": result.get("records", []),
            "total": result.get("total", 0),
            "page": result.get("page", normalized["page"]),
            "page_size": result.get("page_size", normalized["page_size"]),
            "total_pages": result.get("total_pages", 0),
            "returned_count": result.get("returned_count", 0),
            "has_next": result.get("has_next", False),
            "has_prev": result.get("has_prev", False),
            "filter_summary": result.get("filter_summary", {}),
            "warnings": result.get("warnings", []) + validation.get("warnings", []),
        },
        message="Filter operation completed.",
        target=target,
        meta={"record_count": result.get("returned_count", 0), "source_record_count": result.get("source_record_count", 0), "filtered_record_count": result.get("filtered_record_count", 0)},
    )



# ============================================================
# 9) QUICK PRESET APPLICATION
# ============================================================

def get_preset_payload(preset_id: str) -> Optional[Dict[str, Any]]:
    """
    คืน payload ของ quick preset
    """

    source_presets = QUICK_FILTER_PRESETS if isinstance(QUICK_FILTER_PRESETS, dict) and QUICK_FILTER_PRESETS else fallback_quick_filter_presets()
    preset = source_presets.get(clean_text(preset_id))

    if not preset:
        return None

    if isinstance(preset.get("payload"), dict):
        return normalize_filter_payload(preset.get("payload"))

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

def builtin_saved_filter_views() -> List[Dict[str, Any]]:
    """
    saved view runtime default สำหรับ map/dashboard target ใหม่
    """

    definitions = [
        {
            "view_id": "prediction_map_view",
            "name": "Prediction Map View",
            "view_name": "Prediction Map View",
            "description": "Flood prediction records ready for map focus.",
            "target": "prediction_map_view",
            "payload": {
                "target": "prediction_map_view",
                "filters": {},
                "advanced": {},
                "sort_by": "risk_score",
                "sort_dir": "desc",
            },
            "tags": ["prediction", "map"],
        },
        {
            "view_id": "entity_overlay_view",
            "name": "Entity Overlay View",
            "view_name": "Entity Overlay View",
            "description": "Uploaded entity overlay records.",
            "target": "entity_overlay_view",
            "payload": {
                "target": "entity_overlay_view",
                "filters": {},
                "advanced": {},
                "sort_by": "risk_group",
                "sort_dir": "desc",
            },
            "tags": ["entity", "map"],
        },
        {
            "view_id": "flood_dashboard_view",
            "name": "Flood Dashboard View",
            "view_name": "Flood Dashboard View",
            "description": "Flood dashboard runtime insight records.",
            "target": "flood_dashboard_view",
            "payload": {
                "target": "flood_dashboard_view",
                "filters": {},
                "advanced": {},
                "sort_by": "risk_score",
                "sort_dir": "desc",
            },
            "tags": ["flood", "dashboard"],
        },
        {
            "view_id": "province_insight_view",
            "name": "Province Insight View",
            "view_name": "Province Insight View",
            "description": "Province insight ranking records.",
            "target": "province_insight_view",
            "payload": {
                "target": "province_insight_view",
                "filters": {},
                "advanced": {},
                "sort_by": "value",
                "sort_dir": "desc",
            },
            "tags": ["province", "dashboard"],
        },
    ]

    result = []

    for item in definitions:
        view = dict(item)
        view["payload"] = normalize_filter_payload(view.get("payload"))
        view["filter"] = view["payload"]
        view["created_at"] = "builtin"
        view["updated_at"] = "builtin"
        view["is_default"] = False
        view["owner"] = "system"
        view["version"] = 1
        result.append(to_jsonable(view))

    return result


def load_saved_filter_views() -> List[Dict[str, Any]]:
    """
    โหลด saved filter views
    """

    try:
        data = read_json(SAVED_VIEWS_PATH, default=[])
    except Exception:
        data = []

    if isinstance(data, list):
        saved = [view for view in data if isinstance(view, dict)]
    elif isinstance(data, dict) and isinstance(data.get("views"), list):
        saved = [view for view in data["views"] if isinstance(view, dict)]
    else:
        saved = []

    builtin = builtin_saved_filter_views()
    merged: Dict[str, Dict[str, Any]] = {}

    for view in builtin + saved:
        view_id = clean_text(view.get("view_id")) or generate_view_id(view)
        normalized_view = dict(view)
        normalized_view["view_id"] = view_id
        normalized_view["target"] = normalize_target(normalized_view.get("target"))
        normalized_view["payload"] = normalize_filter_payload(normalized_view.get("payload") or normalized_view.get("filter") or {"target": normalized_view["target"]})
        normalized_view["filter"] = normalized_view["payload"]
        merged[view_id] = normalized_view

    return list(merged.values())

def load_saved_views() -> List[Dict[str, Any]]:
    return load_saved_filter_views()


def write_saved_filter_views(views: List[Dict[str, Any]]) -> Path:
    """
    เขียน saved filter views
    """

    safe_views = [to_jsonable(view) for view in views if isinstance(view, dict)]
    payload = {
        "views": safe_views,
        "total": len(safe_views),
        "updated_at": now_iso(),
    }
    target = Path(SAVED_VIEWS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(target.suffix + ".tmp")
    write_json(temp_path, payload)
    temp_path.replace(target)
    return target


def write_saved_views(views: List[Dict[str, Any]]) -> Path:
    return write_saved_filter_views(views)


def generate_view_id(payload: Optional[Dict[str, Any]] = None) -> str:
    """
    สร้าง view id
    """

    payload = payload or {}
    provided = clean_text(payload.get("view_id"))
    if provided:
        return provided
    return f"VIEW_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8].upper()}"


def normalize_saved_view_payload(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = payload or {}
    if not isinstance(raw, dict):
        raw = {}
    view_payload = raw.get("view") if isinstance(raw.get("view"), dict) else raw
    filter_payload = view_payload.get("payload") or view_payload.get("filter") or raw.get("payload") or raw.get("filter") or view_payload
    normalized_filter = normalize_filter_payload(filter_payload)
    raw_tags = view_payload.get("tags", [])
    if isinstance(raw_tags, str):
        tags = [clean_text(item) for item in raw_tags.split(",") if clean_text(item)]
    elif isinstance(raw_tags, list):
        tags = [clean_text(item) for item in raw_tags if not is_empty_value(item)]
    else:
        tags = []
    timestamp = now_iso()
    return {
        "view_id": generate_view_id(view_payload),
        "name": clean_text(view_payload.get("name") or view_payload.get("view_name"), default="Untitled View"),
        "view_name": clean_text(view_payload.get("view_name") or view_payload.get("name"), default="Untitled View"),
        "description": clean_text(view_payload.get("description", "")),
        "target": normalize_target(view_payload.get("target") or normalized_filter.get("target")),
        "payload": normalized_filter,
        "filter": normalized_filter,
        "created_at": clean_text(view_payload.get("created_at"), default=timestamp),
        "updated_at": clean_text(view_payload.get("updated_at"), default=timestamp),
        "is_default": bool(to_bool(view_payload.get("is_default", False), default=False)),
        "tags": tags,
        "owner": clean_text(view_payload.get("owner") or view_payload.get("created_by"), default="local"),
        "version": int(to_number(view_payload.get("version"), 1) or 1),
    }


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

    view = normalize_saved_view_payload(payload)
    views = load_saved_filter_views()

    if view["is_default"]:
        for existing in views:
            if existing.get("target") == view["target"]:
                existing["is_default"] = False

    replaced = False
    for index, existing in enumerate(views):
        if existing.get("view_id") == view["view_id"]:
            view["created_at"] = existing.get("created_at", view["created_at"])
            view["updated_at"] = now_iso()
            views[index] = view
            replaced = True
            break

    if not replaced:
        views.append(view)

    try:
        write_saved_filter_views(views)
    except Exception as exc:
        return make_filter_error(
            message=str(exc),
            error_type="SavedViewWriteError",
            field="saved_filter_views",
            target=view["target"],
            status_code=500,
            data={"saved": False, "view_id": view.get("view_id")},
        )

    return make_filter_response(
        data={"saved": True, "view_id": view["view_id"], "view": view},
        message="Filter view saved.",
        target=view["target"],
        meta={"record_count": 1},
    )


def get_saved_filter_views(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/filter/saved-views
    """

    raw_context = context if isinstance(context, dict) else {}
    ctx = normalize_filter_context(context)
    views = load_saved_filter_views()
    target = normalize_target(raw_context.get("target", "")) if clean_text(raw_context.get("target")) else ""
    search = clean_text_lower(ctx.get("search", ""))
    tag = clean_text_lower(
        raw_context.get("tag")
        or ((ctx.get("filters") or {}).get("tag") if isinstance(ctx.get("filters"), dict) else "")
    )

    if target:
        views = [view for view in views if normalize_target(view.get("target")) == target]

    if search:
        views = [
            view
            for view in views
            if search in clean_text_lower(view.get("name") or view.get("view_name"))
            or search in clean_text_lower(view.get("description"))
        ]

    if tag:
        views = [
            view
            for view in views
            if tag in {clean_text_lower(item) for item in view.get("tags", []) if not is_empty_value(item)}
        ]

    views_sorted = sorted(
        views,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )

    return make_filter_response(
        data={"views": to_jsonable(views_sorted), "total": len(views_sorted)},
        message="Saved filter views loaded.",
        target=target or ctx["target"],
        meta={"record_count": len(views_sorted)},
    )


def get_saved_filter_view(view_id: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/filter/saved-views/<view_id>
    """

    view_id = clean_text(view_id)
    if not view_id:
        return make_filter_error("view_id is required.", field="view_id", target=DEFAULT_FILTER_TARGET, status_code=400)

    views = load_saved_filter_views()

    for view in views:
        if view.get("view_id") == view_id:
            return make_filter_response(
                data={"found": True, "view_id": view_id, "view": view},
                message="Saved filter view loaded.",
                target=normalize_target(view.get("target")),
                meta={"record_count": 1},
            )

    return make_filter_error(
        "Saved view not found.",
        error_type="NotFoundError",
        field="view_id",
        target=DEFAULT_FILTER_TARGET,
        status_code=404,
        data={"found": False, "view_id": view_id, "view": None},
    )


def get_saved_filter_view_detail(view_id: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_saved_filter_view(view_id, context)


def update_saved_filter_view(
    view_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update a saved filter view without mutating the loaded source payload."""

    view_id = clean_text(view_id)
    if not view_id:
        return make_filter_error("view_id is required.", field="view_id", target=DEFAULT_FILTER_TARGET, status_code=400)
    if payload is not None and not isinstance(payload, dict):
        return make_filter_error("payload must be a dictionary.", field="payload", target=DEFAULT_FILTER_TARGET, status_code=422)
    update_payload = deepcopy(payload or {})
    views = [deepcopy(view) for view in load_saved_filter_views()]
    updated_view: Optional[Dict[str, Any]] = None

    for index, current in enumerate(views):
        if current.get("view_id") != view_id:
            continue
        view = deepcopy(current)
        if "view_name" in update_payload or "name" in update_payload:
            name = clean_text(update_payload.get("view_name") or update_payload.get("name"), default=view.get("name") or view.get("view_name") or "Untitled View")
            view["view_name"] = name
            view["name"] = name
        if "description" in update_payload:
            view["description"] = clean_text(update_payload.get("description"))
        if "tags" in update_payload and isinstance(update_payload.get("tags"), list):
            view["tags"] = [clean_text(item) for item in update_payload["tags"] if not is_empty_value(item)]
        elif "tags" in update_payload and isinstance(update_payload.get("tags"), str):
            view["tags"] = [clean_text(item) for item in update_payload["tags"].split(",") if clean_text(item)]
        if "is_default" in update_payload:
            view["is_default"] = bool(to_bool(update_payload.get("is_default"), default=False))
        if "target" in update_payload and "filter" not in update_payload and "payload" not in update_payload:
            view["target"] = normalize_target(update_payload.get("target"))
            existing_payload = deepcopy(view.get("payload")) if isinstance(view.get("payload"), dict) else {}
            existing_payload["target"] = view["target"]
            normalized = normalize_filter_payload(existing_payload)
            view["filter"] = deepcopy(normalized)
            view["payload"] = deepcopy(normalized)
        if "filter" in update_payload or "payload" in update_payload:
            filter_payload = update_payload.get("filter") or update_payload.get("payload")
            validation = validate_runtime_filter_payload(filter_payload)
            if not validation["valid"]:
                return make_filter_response(data={"updated": False, "view_id": view_id, "validation": validation}, message="Filter payload validation failed.", target=normalize_target(view.get("target")), meta={"status_code": 422}, errors=validation["errors"], success=False)
            normalized = normalize_filter_payload(filter_payload)
            view["filter"] = deepcopy(normalized)
            view["payload"] = deepcopy(normalized)
            view["target"] = normalized["target"]
        view["updated_at"] = now_iso()
        views[index] = view
        updated_view = view
        break

    if updated_view is None:
        return make_filter_error("Saved view not found.", error_type="NotFoundError", field="view_id", target=DEFAULT_FILTER_TARGET, status_code=404, data={"updated": False, "view_id": view_id})
    if updated_view.get("is_default"):
        for view in views:
            if view.get("view_id") != view_id and view.get("target") == updated_view.get("target"):
                view["is_default"] = False
    try:
        write_saved_filter_views(views)
    except Exception:
        return make_filter_error("Saved filter views could not be written.", error_type="SavedViewWriteError", field="saved_filter_views", target=updated_view.get("target"), status_code=500)
    return make_filter_response(data={"updated": True, "view_id": view_id, "view": updated_view}, message="Saved filter view updated.", target=normalize_target(updated_view.get("target")), meta={"record_count": 1})



def delete_saved_filter_view(view_id: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    DELETE /api/filter/saved-views/<view_id>
    """

    view_id = clean_text(view_id)
    if not view_id:
        return make_filter_error("view_id is required.", field="view_id", target=DEFAULT_FILTER_TARGET, status_code=400)

    views = load_saved_filter_views()

    before = len(views)
    deleted_view = next((view for view in views if view.get("view_id") == view_id), None)
    views = [
        view
        for view in views
        if view.get("view_id") != view_id
    ]

    deleted = len(views) < before

    if deleted:
        try:
            write_saved_filter_views(views)
        except Exception as exc:
            return make_filter_error(str(exc), error_type="SavedViewWriteError", field="saved_filter_views", target=DEFAULT_FILTER_TARGET, status_code=500)
    else:
        return make_filter_error(
            "Saved view not found.",
            error_type="NotFoundError",
            field="view_id",
            target=DEFAULT_FILTER_TARGET,
            status_code=404,
            data={"deleted": False, "view_id": view_id},
        )

    return make_filter_response(
        data={"deleted": True, "view_id": view_id, "deleted_view": deleted_view, "remaining_count": len(views)},
        message="Saved filter view deleted.",
        target=normalize_target((deleted_view or {}).get("target")),
        meta={"record_count": 1, "remaining_count": len(views)},
    )


# ============================================================
# 11) FILTER FOR SERVICE LAYERS
# ============================================================

def filter_records_for_service(
    records: Any,
    context: Optional[Dict[str, Any]] = None,
    target: str = DEFAULT_FILTER_TARGET,
    paginate: bool = True,
) -> Dict[str, Any]:
    """
    helper สำหรับ service อื่นเรียกใช้

    ตัวอย่าง:
        result = filter_records_for_service(records, context, target="company")
    """

    context_dict = context if isinstance(context, dict) else {}
    payload = normalize_filter_payload({**context_dict, "target": target})
    if not paginate:
        payload["page"] = 1
        payload["page_size"] = MAX_TABLE_PAGE_SIZE

    source_records = records_to_record_list(records, target=target)
    result = run_filter_pipeline(source_records, payload, target=target)
    if not paginate:
        filtered_records = apply_sort_to_records(
            apply_search_to_records(
                apply_advanced_filters_to_records(
                    apply_simple_filters_to_records(source_records, payload.get("filters", {})),
                    payload.get("advanced", {}),
                ),
                payload.get("search", ""),
                target,
            ),
            payload.get("sort_by", ""),
            payload.get("sort_dir", "asc"),
        )
        result["records"] = filtered_records
        result["items"] = filtered_records
        result["total"] = len(filtered_records)
        result["returned_count"] = len(filtered_records)
    else:
        result["items"] = result.get("records", [])
    result["meta"] = {
        "source_record_count": result.get("source_record_count", 0),
        "filtered_record_count": result.get("filtered_record_count", result.get("total", 0)),
        "target": normalize_target(target),
    }
    return to_jsonable(result)


def build_filter_context_for_package(
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    เตรียม filter context สำหรับ package export

    ใช้เก็บลง package_meta.filters
    """

    normalized = normalize_filter_payload(payload)
    summary = build_filter_summary(normalized)

    return to_jsonable(
        {
            "target": normalized["target"],
            "payload": normalized,
            "summary": summary,
            "label": summary.get("human_label", ""),
            "applied": True,
            "meta": {
                "created_at": now_iso(),
                "module": "filter",
            },
            "filter": normalized,
        }
    )


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

    context = dict(payload) if isinstance(payload, dict) else {}
    if context.get("selected_province") and not context.get("filters", {}).get("province"):
        filters = dict(context.get("filters", {}))
        filters["province"] = context.get("selected_province")
        context["filters"] = filters
    result = filter_records_for_service(records, context, target="company", paginate=False)
    return result.get("records", [])


def filter_company_records_for_graph(
    records: List[Dict[str, Any]],
    payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    filter company records สำหรับ linkage graph
    """

    context = dict(payload) if isinstance(payload, dict) else {}
    filters = dict(context.get("filters", {})) if isinstance(context.get("filters", {}), dict) else {}
    if context.get("selected_province") and not filters.get("province"):
        filters["province"] = context.get("selected_province")
    if context.get("key_connector_only"):
        filters["is_key_connector"] = True
    context["filters"] = filters
    target = "linkage" if normalize_target(context.get("target")) == "linkage" else "company"
    result = filter_records_for_service(records, context, target=target, paginate=False)
    return result.get("records", [])


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
    """Run deterministic coverage for record normalization and filter ordering."""

    sample_records = [
        {"tax_id_norm": "0100000000001", "company_name": "Alpha", "province": "Nan", "total_suminsure": 1500000, "loss_ratio": 45, "flood_risk_level": "Watch", "has_policy": True, "has_linkage": True, "has_location": True, "created_at": "2026-07-01"},
        {"tax_id_norm": "0100000000002", "company_name": "Beta", "province": "Phrae", "total_suminsure": 500000, "loss_ratio": 120, "flood_risk_level": "Critical", "has_policy": True, "has_linkage": False, "has_location": True, "created_at": "01/07/2026"},
        {"tax_id_norm": "0100000000003", "company_name": "Gamma", "province": "Chiang Mai", "total_suminsure": 2500000, "loss_ratio": 10, "flood_risk_level": "Normal", "has_policy": False, "has_linkage": True, "has_location": False, "created_at": "2026/07/02"},
    ]
    prediction_records = [
        {"record_key": "prediction|1373690", "station_id": "1373690", "station_name": "Station A", "province_model": "Nan", "warning_level_predict": "Critical", "forecast_horizon_day": 2, "map_ready": True, "latitude": 18.7, "longitude": 100.7},
        {"record_key": "prediction|999", "station_id": "999", "station_name": "Station B", "province_model": "Phrae", "warning_level_predict": "Normal", "forecast_horizon_day": 2, "map_ready": False},
    ]
    company_payload = {"target": "company", "filters": {"has_policy": True}, "advanced": {"logic": "AND", "conditions": [{"field": "total_suminsure", "operator": "gte", "value": "1000000", "dtype": "number"}]}, "search": "alpha", "sort_by": "total_suminsure", "sort_dir": "desc", "page": 1, "page_size": 10}
    nested_payload = {"target": "company", "advanced": {"logic": "OR", "conditions": [], "groups": [{"logic": "AND", "conditions": [{"field": "province", "operator": "equals", "value": "Nan"}, {"field": "has_policy", "operator": "equals", "value": 1, "dtype": "boolean"}]}, {"logic": "AND", "conditions": [{"field": "province", "operator": "equals", "value": "Phrae"}]}]}}
    company_result = apply_full_filter(sample_records, company_payload, paginate=True)
    nested_result = apply_full_filter(tuple(sample_records), nested_payload, paginate=False)
    prediction_result = apply_full_filter(prediction_records, {"target": "flood_prediction_latest", "filters": {"risk": "Critical", "map_ready": "true"}, "sort_by": "horizon", "sort_dir": "asc"}, paginate=True)
    dataframe_result: List[Dict[str, Any]] = []
    try:
        import pandas as pd
        dataframe_result = records_to_record_list(pd.DataFrame(sample_records), target="company")
    except Exception:
        dataframe_result = []
    checks = {
        "list_input": len(records_to_record_list(sample_records)) == 3,
        "tuple_input": len(records_to_record_list(tuple(sample_records))) == 3,
        "iterable_input": len(records_to_record_list(iter(sample_records))) == 3,
        "dataframe_input": len(dataframe_result) == 3,
        "empty_input": records_to_record_list(None) == [],
        "simple_filter": len(apply_simple_filters(sample_records, {"has_policy": True})) == 2,
        "advanced_and": len(apply_advanced_filter(sample_records, company_payload["advanced"])) == 2,
        "advanced_or_nested": len(nested_result.get("records", [])) == 2,
        "empty_group": len(apply_advanced_filter(sample_records, {"logic": "AND", "conditions": [], "groups": []})) == 3,
        "search": len(apply_search_to_records(sample_records, "beta", "company")) == 1,
        "sort_asc": apply_sort_to_records(sample_records, "total_suminsure", "asc")[0]["company_name"] == "Beta",
        "sort_desc": apply_sort_to_records(sample_records, "total_suminsure", "desc")[0]["company_name"] == "Gamma",
        "pagination": apply_pagination_to_records(sample_records, 2, 2)["returned_count"] == 1,
        "company_target": company_result.get("filtered_record_count") == 1,
        "policy_target": normalize_target("policy") == "policy",
        "linkage_target": normalize_target("linkage") == "linkage",
        "flood_target": normalize_target("flood") == "flood",
        "prediction_target": prediction_result.get("filtered_record_count") == 1,
    }
    return {"module": "filter_engine", "ready": all(checks.values()), "checks": checks, "sample_result": company_result, "nested_result": nested_result, "prediction_result": prediction_result, "checked_at": now_iso()}


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
        "runtime_targets": [
            "flood_rainfall_latest",
            "flood_waterlevel_latest",
            "flood_dam_latest",
            "flood_prediction_latest",
            "flood_prediction_map",
            "uploaded_entity_latest",
            "map_layers",
            "dashboard_province_insights",
        ],
        "saved_view_targets": [
            "prediction_map_view",
            "entity_overlay_view",
            "flood_dashboard_view",
            "province_insight_view",
        ],
        "target_aliases": TARGET_ALIASES,
        "field_alias_candidates": FILTER_FIELD_ALIAS_CANDIDATES,
        "supported_operators": FILTER_OPERATORS,
        "supported_logical_operators": FILTER_LOGICAL_OPERATORS,
        "quick_preset_count": len(fallback_quick_filter_presets()),
        "saved_views_path": str(SAVED_VIEWS_PATH),
        "saved_views_count": len(load_saved_views()),
        "cache_key_candidates": TARGET_CACHE_KEY_CANDIDATES,
        "checked_at": now_iso(),
    }
