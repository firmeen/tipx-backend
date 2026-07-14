# ============================================================
# FILE: backend/flood_spatial_service.py
# TIPX Enterprise Intelligence Dashboard
# ============================================================

"""
backend/flood_spatial_service.py

ไฟล์นี้เป็นศูนย์กลาง Flood / Spatial Join / Flood Exposure ของระบบ TIPX

หน้าที่หลัก:
1. อ่าน Flood Output จากโครงการ ThaiWater / Flood Pipeline
2. อ่าน latest_database.xlsx
3. อ่าน master_database.xlsx
4. อ่าน history folder เท่าที่จำเป็น
5. สร้าง flood_latest payload
6. สร้าง flood_station_master
7. สร้าง flood_boundary payload
8. คำนวณ flood_computed_risk
9. คำนวณ province_risk_summary
10. เชื่อม Company Unified Master กับ Flood Risk
11. สร้าง spatial_join_result
12. หา nearest rainfall station
13. หา nearest waterlevel station
14. หา nearest dam
15. สร้าง company_flood_context
16. สร้าง policy_flood_exposure
17. สร้าง province_risk_exposure
18. รองรับ API กลุ่ม /api/flood/*
19. รองรับ API กลุ่ม /api/spatial/*
20. เขียน cache ให้ map_graph_service.py และ dashboard_package_service.py ใช้ต่อ

Data Source:
- C:/Users/afimeenu/project/flood/output_fl/latest/latest_database.xlsx
- C:/Users/afimeenu/project/flood/output_fl/master/master_database.xlsx
- C:/Users/afimeenu/project/flood/output_fl/history/

Flood Latest Sheets:
- 02_rainfall_latest
- 05_waterlevel_latest
- 07_large_dam_latest
- 09_medium_dam_latest
- 17_all_long_latest

Flood Master Sheets:
- 11_province_boundary
- 12_basin_boundary
- 13_rainfall_station_master
- 14_waterlevel_station_master
- 15_dam_reservoir_master
- 16_location_master
- 19_data_quality_log
- 20_error_log

Risk Levels:
- Normal
- Watch
- Warning
- Critical
- Unknown
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import config

from config import (
    FLOOD_OUTPUT_DIR,
    FLOOD_LATEST_DATABASE_PATH,
    FLOOD_MASTER_DATABASE_PATH,
    FLOOD_HISTORY_DIR,
    FLOOD_LATEST_SHEETS,
    FLOOD_MASTER_SHEETS,
    FLOOD_HISTORY_SHEETS,
    CACHE_TTL_SECONDS,
    RISK_LEVELS,
    RISK_COLORS,
    RISK_SCORE,
    SPATIAL_NEAREST_STATION_LIMIT_KM,
    SPATIAL_COMPANY_FLOOD_RADIUS_KM,
)

from utils import (
    apply_search_sort_pagination,
    calculate_dam_risk,
    calculate_rainfall_risk,
    calculate_waterlevel_risk,
    clean_dataframe_common,
    clean_text,
    clean_text_lower,
    combine_risk_levels,
    dataframe_to_records,
    file_info,
    find_nearest_record,
    get_or_build_cache,
    group_records_by,
    haversine_km,
    is_empty_value,
    make_feature_collection,
    make_hash_id,
    make_point_feature,
    normalize_province_name,
    normalize_risk_level,
    normalize_tax_id,
    read_cache,
    read_excel_sheet,
    read_excel_sheets,
    search_records,
    sort_records,
    to_bool,
    to_datetime,
    to_int,
    to_jsonable,
    to_number,
    validate_coordinate,
    write_cache,
    clear_excel_cache,
    clean_column_name,
    filter_by_province,
    filter_by_risk,
    filter_has_location,
    first_value_by_columns,
    find_first_existing_column,
    get_latest_prediction_file,
    limit_dataframe,
    read_history_sheet,
    read_latest_sheet,
    read_master_sheet,
    read_prediction_file,
    safe_float,
    safe_int,
    safe_str,
    safe_filename,
)

try:
    from filter_engine import filter_records_for_service
except Exception:
    filter_records_for_service = None


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
}

CACHE_KEYS: Dict[str, str] = {
    "rainfall_latest": "flood_rainfall_latest",
    "waterlevel_latest": "flood_waterlevel_latest",
    "large_dam_latest": "flood_large_dam_latest",
    "medium_dam_latest": "flood_medium_dam_latest",
    "all_long_latest": "flood_all_long_latest",
    "flood_station_master": "flood_station_master",
    "province_boundaries": "flood_province_boundaries",
    "basin_boundaries": "flood_basin_boundaries",
    "flood_computed_risk": "flood_computed_risk",
    "province_risk_summary": "province_risk_summary",
    "company_flood_context": "company_flood_context",
    "spatial_join_result": "spatial_join_result",
    "policy_flood_exposure": "policy_flood_exposure",
    "province_risk_exposure": "province_risk_exposure",
    "flood_summary": "flood_summary",
    "flood_prediction_files": "flood_prediction_files",
    "flood_prediction_latest": "flood_prediction_latest",
    "flood_prediction_summary": "flood_prediction_summary",
    "flood_prediction_map": "flood_prediction_map",
    "flood_prediction_location_debug": "flood_prediction_location_debug",
    "flood_prediction_risk_distribution": "flood_prediction_risk_distribution",
    "flood_history_index": "flood_history_index",
    "flood_master_station_index": "flood_master_station_index",
}

FLOOD_SEARCHABLE_FIELDS: List[str] = [
    "source_type",
    "source_id",
    "source_name",
    "station_id",
    "station_name",
    "dam_id",
    "dam_name",
    "province",
    "basin",
    "risk_level",
    "risk_reason",
]

PREDICTION_SEARCHABLE_FIELDS: List[str] = [
    "record_key",
    "station_id",
    "station_code",
    "station_name",
    "station_name_th",
    "matched_station_id",
    "matched_station_code",
    "matched_station_name",
    "province",
    "province_model",
    "risk_level",
    "risk_status",
    "warning_level",
    "warning_level_predict",
    "base_date",
    "target_date",
    "forecast_horizon_day",
]

SPATIAL_SEARCHABLE_FIELDS: List[str] = [
    "tax_id_norm",
    "company_name",
    "province",
    "district",
    "subdistrict",
    "final_flood_risk_level",
    "flood_risk_reason",
    "join_level",
    "location_quality",
]


# ============================================================
# 2) CONTEXT HELPERS
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

    return result


def get_flood_ttl() -> int:
    """
    TTL สำหรับ flood cache
    """

    return int(CACHE_TTL_SECONDS.get("flood", 3600))


def filter_records_api(
    records: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
    searchable_fields: Optional[List[str]] = None,
    target: str = "flood",
) -> Dict[str, Any]:
    """
    apply filter/search/sort/pagination

    รองรับ filter หลัก:
    - province
    - risk_level / risk / risk_status
    - has_location / map_ready
    """

    ctx = normalize_context(context)
    filters = ctx.get("filters", {}) if isinstance(ctx.get("filters"), dict) else {}

    result = list(records or [])

    province_value = (
        filters.get("province")
        or filters.get("province_model")
        or filters.get("province_name_th")
        or ctx.get("province")
    )

    risk_value = (
        filters.get("risk_level")
        or filters.get("risk")
        or filters.get("risk_status")
        or filters.get("warning_level")
        or filters.get("warning_level_predict")
        or ctx.get("risk_level")
        or ctx.get("risk")
    )

    has_location_value = (
        filters.get("has_location")
        if "has_location" in filters
        else filters.get("map_ready")
        if "map_ready" in filters
        else ctx.get("has_location")
        if "has_location" in ctx
        else ctx.get("map_ready")
    )

    station_value = (
        filters.get("station")
        or filters.get("station_id")
        or filters.get("station_code")
        or filters.get("station_name")
        or ctx.get("station")
    )

    if province_value not in (None, "", [], {}):
        province_norm = normalize_province_name(province_value)
        result = [
            record
            for record in result
            if normalize_province_name(
                record.get("province")
                or record.get("province_model")
                or record.get("province_name_th")
                or record.get("company_province")
            ) == province_norm
        ]

    if risk_value not in (None, "", [], {}):
        risk_norm = normalize_risk_status(risk_value)
        result = [
            record
            for record in result
            if normalize_risk_status(
                record.get("risk_level")
                or record.get("risk_status")
                or record.get("warning_level")
                or record.get("warning_level_predict")
                or record.get("final_flood_risk_level")
                or record.get("flood_risk_level")
            ) == risk_norm
        ]

    if has_location_value not in (None, "", [], {}):
        expected = to_bool(has_location_value, default=None)

        if expected is not None:
            result = [
                record
                for record in result
                if bool(
                    record.get("map_ready")
                    if "map_ready" in record
                    else record.get("has_location")
                    if "has_location" in record
                    else validate_coordinate(
                        record.get("lat") or record.get("latitude") or record.get("company_lat"),
                        record.get("lon") or record.get("longitude") or record.get("company_lon"),
                    ).get("valid")
                ) is expected
            ]

    if station_value not in (None, "", [], {}):
        station_query = clean_text_lower(station_value)
        result = [
            record
            for record in result
            if station_query in " ".join(
                [
                    clean_text(record.get("station_id")),
                    clean_text(record.get("station_code")),
                    clean_text(record.get("station_name")),
                    clean_text(record.get("station_name_th")),
                    clean_text(record.get("matched_station_id")),
                    clean_text(record.get("matched_station_code")),
                    clean_text(record.get("matched_station_name")),
                    clean_text(record.get("source_id")),
                    clean_text(record.get("source_name")),
                    clean_text(record.get("dam_id")),
                    clean_text(record.get("dam_name")),
                ]
            ).lower()
        ]

    if filter_records_for_service is not None:
        try:
            ctx_for_filter = dict(ctx)
            ctx_for_filter["filters"] = {}
            ctx_for_filter["page"] = ctx.get("page", 1)
            ctx_for_filter["page_size"] = ctx.get("page_size", 50)

            filtered = filter_records_for_service(
                records=result,
                context=ctx_for_filter,
                target=target,
                paginate=True,
            )

            if isinstance(filtered, dict) and "records" in filtered:
                return filtered
        except Exception:
            pass

    return apply_search_sort_pagination(
        records=result,
        context=ctx,
        searchable_fields=searchable_fields,
    )

# ============================================================
# 3) COLUMN DETECTION HELPERS
# ============================================================

def first_existing_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """
    หา column แรกที่มีใน DataFrame แบบ case-insensitive หลัง clean
    """

    if df is None or df.empty:
        return None

    original_cols = list(df.columns)

    clean_map = {
        clean_text_lower(col).replace(" ", "_"): col
        for col in original_cols
    }

    for candidate in candidates:
        candidate_clean = clean_text_lower(candidate).replace(" ", "_")

        if candidate in original_cols:
            return candidate

        if candidate_clean in clean_map:
            return clean_map[candidate_clean]

    return None


def get_value_by_candidates(row: Any, candidates: List[str], default: Any = None) -> Any:
    """
    อ่านค่าจาก row โดยลองหลายชื่อ column
    """

    if row is None:
        return default

    if isinstance(row, dict):
        keys = list(row.keys())
    else:
        try:
            keys = list(row.index)
        except Exception:
            keys = []

    clean_map = {
        clean_text_lower(key).replace(" ", "_"): key
        for key in keys
    }

    for candidate in candidates:
        candidate_clean = clean_text_lower(candidate).replace(" ", "_")

        if candidate in keys:
            value = row.get(candidate)
            return value if not is_empty_value(value) else default

        if candidate_clean in clean_map:
            value = row.get(clean_map[candidate_clean])
            return value if not is_empty_value(value) else default

    return default


def standardize_lat_lon(row: Any) -> Tuple[Optional[float], Optional[float]]:
    """
    ดึง lat/lon จาก row หลายรูปแบบ
    """

    lat = get_value_by_candidates(
        row,
        [
            "lat",
            "latitude",
            "tele_station_lat",
            "station_lat",
            "dam_lat",
            "Latitude",
            "LAT",
        ],
    )

    lon = get_value_by_candidates(
        row,
        [
            "lon",
            "long",
            "lng",
            "longitude",
            "tele_station_long",
            "station_long",
            "dam_long",
            "Longitude",
            "LONG",
        ],
    )

    lat_value = to_number(lat, None)
    lon_value = to_number(lon, None)

    return lat_value, lon_value


def standardize_province(row: Any) -> str:
    """
    ดึง province จาก row หลายรูปแบบ
    """

    province = get_value_by_candidates(
        row,
        [
            "province",
            "province_name",
            "province_name_th",
            "province_th",
            "จังหวัด",
            "changwat",
        ],
        default="",
    )

    return normalize_province_name(province)


def standardize_basin(row: Any) -> str:
    """
    ดึง basin จาก row หลายรูปแบบ
    """

    basin = get_value_by_candidates(
        row,
        [
            "basin",
            "basin_name",
            "basin_name_th",
            "ลุ่มน้ำ",
        ],
        default="",
    )

    return clean_text(basin)


def standardize_datetime(row: Any) -> str:
    """
    ดึง datetime จาก row หลายรูปแบบ
    """

    raw = get_value_by_candidates(
        row,
        [
            "data_datetime",
            "datetime",
            "date_time",
            "date",
            "time",
            "data_date",
            "created_at",
            "updated_at",
        ],
        default="",
    )

    dt = to_datetime(raw)

    if dt:
        return dt.isoformat(timespec="seconds")

    return clean_text(raw)


# ============================================================
# 4) FLOOD FILE LOADERS
# ============================================================

def load_flood_latest_sheets(force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    """
    อ่าน latest_database.xlsx ตาม FLOOD_LATEST_SHEETS

    Return:
    {
        "rainfall_latest": DataFrame,
        "waterlevel_latest": DataFrame,
        ...
    }
    """

    if not FLOOD_LATEST_DATABASE_PATH.exists():
        return {}

    sheets = read_excel_sheets(
        FLOOD_LATEST_DATABASE_PATH,
        sheet_names=FLOOD_LATEST_SHEETS,
        dtype=str,
    )

    return {
        key: clean_dataframe_common(df)
        for key, df in sheets.items()
    }


def load_flood_master_sheets(force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    """
    อ่าน master_database.xlsx
    """

    if not FLOOD_MASTER_DATABASE_PATH.exists():
        return {}

    sheets = read_excel_sheets(
        FLOOD_MASTER_DATABASE_PATH,
        sheet_names=None,
        dtype=str,
    )

    return {
        key: clean_dataframe_common(df)
        for key, df in sheets.items()
    }


def get_master_sheet_by_name_or_key(master_sheets: Dict[str, pd.DataFrame], target_name: str) -> pd.DataFrame:
    """
    หา sheet จาก master_sheets ด้วยชื่อ exact หรือ contains
    """

    if target_name in master_sheets:
        return master_sheets[target_name]

    target_clean = clean_text_lower(target_name)

    for name, df in master_sheets.items():
        if clean_text_lower(name) == target_clean:
            return df

    for name, df in master_sheets.items():
        if target_clean in clean_text_lower(name):
            return df

    return pd.DataFrame()


# ============================================================
# 5) STANDARDIZE FLOOD LATEST RECORDS
# ============================================================

def standardize_rainfall_latest(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    แปลง rainfall latest ให้เป็น standard records
    """

    if df is None or df.empty:
        return []

    records: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        lat, lon = standardize_lat_lon(row)

        station_id = clean_text(
            get_value_by_candidates(
                row,
                ["station_id", "tele_station_id", "id", "code", "rainfall_station_id"],
                default=f"rainfall_row_{idx}",
            )
        )

        station_name = clean_text(
            get_value_by_candidates(
                row,
                ["station_name", "tele_station_name", "name", "rainfall_station_name", "สถานี"],
                default=station_id,
            )
        )

        rainfall = get_value_by_candidates(
            row,
            [
                "rainfall_value",
                "rainfall",
                "rain_24h",
                "rainfall_24h",
                "rainfall_mm",
                "value",
                "ฝน_24_ชม",
            ],
            default=None,
        )

        rainfall_value = to_number(rainfall, None)
        risk = calculate_rainfall_risk(rainfall_value)

        record = {
            "source_type": "rainfall",
            "source_id": station_id,
            "source_key": f"rainfall:{station_id}",
            "source_name": station_name,

            "station_id": station_id,
            "station_name": station_name,

            "province": standardize_province(row),
            "basin": standardize_basin(row),
            "lat": lat,
            "lon": lon,

            "data_datetime": standardize_datetime(row),
            "rainfall_value": rainfall_value,
            "rainfall_24h": rainfall_value,

            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "risk_reason": risk["risk_reason"],
            "risk_color": risk["risk_color"],

            "source_sheet": "02_rainfall_latest",
            "source_row": int(idx) + 2,
        }

        records.append(record)

    return records


def standardize_waterlevel_latest(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    แปลง waterlevel latest ให้เป็น standard records
    """

    if df is None or df.empty:
        return []

    records: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        lat, lon = standardize_lat_lon(row)

        station_id = clean_text(
            get_value_by_candidates(
                row,
                ["station_id", "tele_station_id", "id", "code", "waterlevel_station_id"],
                default=f"waterlevel_row_{idx}",
            )
        )

        station_name = clean_text(
            get_value_by_candidates(
                row,
                ["station_name", "tele_station_name", "name", "waterlevel_station_name", "สถานี"],
                default=station_id,
            )
        )

        waterlevel = get_value_by_candidates(
            row,
            [
                "waterlevel_value",
                "waterlevel",
                "water_level",
                "level",
                "value",
                "ระดับน้ำ",
            ],
            default=None,
        )

        warning_level = get_value_by_candidates(
            row,
            [
                "warning_level",
                "warning",
                "warn_level",
                "ระดับเตือนภัย",
            ],
            default=None,
        )

        critical_level = get_value_by_candidates(
            row,
            [
                "critical_level",
                "critical",
                "danger_level",
                "ระดับวิกฤต",
            ],
            default=None,
        )

        waterlevel_value = to_number(waterlevel, None)
        warning_value = to_number(warning_level, None)
        critical_value = to_number(critical_level, None)

        risk = calculate_waterlevel_risk(
            waterlevel_value,
            warning_level=warning_value,
            critical_level=critical_value,
        )

        record = {
            "source_type": "waterlevel",
            "source_id": station_id,
            "source_key": f"waterlevel:{station_id}",
            "source_name": station_name,

            "station_id": station_id,
            "station_name": station_name,

            "province": standardize_province(row),
            "basin": standardize_basin(row),
            "lat": lat,
            "lon": lon,

            "data_datetime": standardize_datetime(row),
            "waterlevel_value": waterlevel_value,
            "warning_level": warning_value,
            "critical_level": critical_value,

            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "risk_reason": risk["risk_reason"],
            "risk_color": risk["risk_color"],

            "source_sheet": "05_waterlevel_latest",
            "source_row": int(idx) + 2,
        }

        records.append(record)

    return records


def standardize_dam_latest(df: pd.DataFrame, dam_type: str = "large_dam") -> List[Dict[str, Any]]:
    """
    แปลง dam latest ให้เป็น standard records

    dam_type:
    - large_dam
    - medium_dam
    """

    if df is None or df.empty:
        return []

    records: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        lat, lon = standardize_lat_lon(row)

        id_candidates = [
            "dam_id",
            "id",
            "code",
            "reservoir_id",
        ]

        if dam_type == "medium_dam":
            id_candidates = [
                "medium_id",
                "dam_id",
                "id",
                "code",
                "reservoir_id",
            ]

        dam_id = clean_text(
            get_value_by_candidates(
                row,
                id_candidates,
                default=f"{dam_type}_row_{idx}",
            )
        )

        name_candidates = [
            "dam_name",
            "name",
            "reservoir_name",
            "เขื่อน",
            "อ่างเก็บน้ำ",
        ]

        if dam_type == "medium_dam":
            name_candidates = [
                "medium_name",
                "dam_name",
                "name",
                "reservoir_name",
                "อ่างเก็บน้ำ",
            ]

        dam_name = clean_text(
            get_value_by_candidates(
                row,
                name_candidates,
                default=dam_id,
            )
        )

        storage_percent = get_value_by_candidates(
            row,
            [
                "storage_percent",
                "percent_storage",
                "storage_pct",
                "percent",
                "storage_percentage",
                "ปริมาณน้ำ_ร้อยละ",
            ],
            default=None,
        )

        storage = get_value_by_candidates(
            row,
            [
                "storage",
                "water_storage",
                "current_storage",
                "ปริมาณน้ำ",
            ],
            default=None,
        )

        capacity = get_value_by_candidates(
            row,
            [
                "capacity",
                "dam_capacity",
                "full_capacity",
                "ความจุ",
            ],
            default=None,
        )

        inflow = get_value_by_candidates(
            row,
            [
                "inflow",
                "water_inflow",
                "น้ำไหลเข้า",
            ],
            default=None,
        )

        release = get_value_by_candidates(
            row,
            [
                "release",
                "outflow",
                "water_release",
                "น้ำระบาย",
            ],
            default=None,
        )

        storage_percent_value = to_number(storage_percent, None)

        if storage_percent_value is None:
            storage_value = to_number(storage, None)
            capacity_value = to_number(capacity, None)

            if storage_value is not None and capacity_value not in (None, 0):
                storage_percent_value = round((storage_value / capacity_value) * 100, 4)

        risk = calculate_dam_risk(storage_percent_value)

        record = {
            "source_type": dam_type,
            "source_id": dam_id,
            "source_key": f"{dam_type}:{dam_id}",
            "source_name": dam_name,

            "dam_id": dam_id,
            "dam_name": dam_name,

            "province": standardize_province(row),
            "basin": standardize_basin(row),
            "lat": lat,
            "lon": lon,

            "data_datetime": standardize_datetime(row),
            "storage": to_number(storage, None),
            "capacity": to_number(capacity, None),
            "storage_percent": storage_percent_value,
            "inflow": to_number(inflow, None),
            "release": to_number(release, None),

            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "risk_reason": risk["risk_reason"],
            "risk_color": risk["risk_color"],

            "source_sheet": "07_large_dam_latest" if dam_type == "large_dam" else "09_medium_dam_latest",
            "source_row": int(idx) + 2,
        }

        records.append(record)

    return records


def standardize_all_long_latest(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    แปลง 17_all_long_latest เป็น standard records แบบ generic
    """

    if df is None or df.empty:
        return []

    records: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        lat, lon = standardize_lat_lon(row)

        source_type = clean_text(
            get_value_by_candidates(
                row,
                ["source_type", "type", "data_type"],
                default="all_long",
            )
        )

        source_id = clean_text(
            get_value_by_candidates(
                row,
                ["source_id", "station_id", "dam_id", "id", "code"],
                default=f"all_long_row_{idx}",
            )
        )

        source_name = clean_text(
            get_value_by_candidates(
                row,
                ["source_name", "station_name", "dam_name", "name"],
                default=source_id,
            )
        )

        risk_level = normalize_risk_level(
            get_value_by_candidates(
                row,
                ["risk_level", "status", "flood_risk_level"],
                default="Unknown",
            )
        )

        record = {
            "source_type": source_type,
            "source_id": source_id,
            "source_key": f"{source_type}:{source_id}",
            "source_name": source_name,

            "province": standardize_province(row),
            "basin": standardize_basin(row),
            "lat": lat,
            "lon": lon,

            "data_datetime": standardize_datetime(row),
            "value": to_number(
                get_value_by_candidates(row, ["value", "data_value", "measure_value"], default=None),
                None,
            ),

            "risk_level": risk_level,
            "risk_score": RISK_SCORE.get(risk_level, -1),
            "risk_reason": clean_text(
                get_value_by_candidates(
                    row,
                    ["risk_reason", "reason", "status_reason"],
                    default="from all_long_latest",
                )
            ),
            "risk_color": RISK_COLORS.get(risk_level, RISK_COLORS.get("Unknown", "#64748b")),

            "source_sheet": "17_all_long_latest",
            "source_row": int(idx) + 2,
        }

        records.append(record)

    return records


# ============================================================
# 6) FLOOD LATEST BUILDERS
# ============================================================

def build_rainfall_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง rainfall latest records
    """

    def builder() -> Dict[str, Any]:
        sheets = load_flood_latest_sheets(force_refresh=force_refresh)
        df = sheets.get("rainfall_latest", pd.DataFrame())
        records = standardize_rainfall_latest(df)

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": FLOOD_LATEST_SHEETS.get("rainfall_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["rainfall_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_rainfall_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_waterlevel_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง waterlevel latest records
    """

    def builder() -> Dict[str, Any]:
        sheets = load_flood_latest_sheets(force_refresh=force_refresh)
        df = sheets.get("waterlevel_latest", pd.DataFrame())
        records = standardize_waterlevel_latest(df)

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": FLOOD_LATEST_SHEETS.get("waterlevel_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["waterlevel_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_waterlevel_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_large_dam_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง large dam latest records
    """

    def builder() -> Dict[str, Any]:
        sheets = load_flood_latest_sheets(force_refresh=force_refresh)
        df = sheets.get("large_dam_latest", pd.DataFrame())
        records = standardize_dam_latest(df, dam_type="large_dam")

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": FLOOD_LATEST_SHEETS.get("large_dam_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["large_dam_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_large_dam_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_medium_dam_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง medium dam latest records
    """

    def builder() -> Dict[str, Any]:
        sheets = load_flood_latest_sheets(force_refresh=force_refresh)
        df = sheets.get("medium_dam_latest", pd.DataFrame())
        records = standardize_dam_latest(df, dam_type="medium_dam")

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": FLOOD_LATEST_SHEETS.get("medium_dam_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["medium_dam_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_medium_dam_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_all_long_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง all_long latest records
    """

    def builder() -> Dict[str, Any]:
        sheets = load_flood_latest_sheets(force_refresh=force_refresh)
        df = sheets.get("all_long_latest", pd.DataFrame())
        records = standardize_all_long_latest(df)

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": FLOOD_LATEST_SHEETS.get("all_long_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["all_long_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_all_long_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


# ============================================================
# 7) MASTER / BOUNDARY BUILDERS
# ============================================================

def standardize_station_master(df: pd.DataFrame, station_type: str) -> List[Dict[str, Any]]:
    """
    แปลง station master เป็น standard records
    """

    if df is None or df.empty:
        return []

    records: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        lat, lon = standardize_lat_lon(row)

        station_id = clean_text(
            get_value_by_candidates(
                row,
                ["station_id", "tele_station_id", "id", "code"],
                default=f"{station_type}_master_row_{idx}",
            )
        )

        station_name = clean_text(
            get_value_by_candidates(
                row,
                ["station_name", "tele_station_name", "name", "สถานี"],
                default=station_id,
            )
        )

        records.append(
            {
                "station_type": station_type,
                "source_type": station_type,
                "source_id": station_id,
                "source_key": f"{station_type}:{station_id}",
                "source_name": station_name,
                "station_id": station_id,
                "station_name": station_name,
                "province": standardize_province(row),
                "basin": standardize_basin(row),
                "lat": lat,
                "lon": lon,
                "coordinate_valid": validate_coordinate(lat, lon)["valid"],
                "source_row": int(idx) + 2,
            }
        )

    return records


def standardize_dam_master(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    แปลง dam master เป็น standard records
    """

    if df is None or df.empty:
        return []

    records: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        lat, lon = standardize_lat_lon(row)

        dam_id = clean_text(
            get_value_by_candidates(
                row,
                ["dam_id", "medium_id", "id", "code", "reservoir_id"],
                default=f"dam_master_row_{idx}",
            )
        )

        dam_name = clean_text(
            get_value_by_candidates(
                row,
                ["dam_name", "medium_name", "name", "reservoir_name", "เขื่อน", "อ่างเก็บน้ำ"],
                default=dam_id,
            )
        )

        dam_type = clean_text(
            get_value_by_candidates(
                row,
                ["dam_type", "type", "reservoir_type"],
                default="dam",
            )
        )

        records.append(
            {
                "station_type": "dam",
                "source_type": dam_type or "dam",
                "source_id": dam_id,
                "source_key": f"dam:{dam_id}",
                "source_name": dam_name,
                "dam_id": dam_id,
                "dam_name": dam_name,
                "province": standardize_province(row),
                "basin": standardize_basin(row),
                "lat": lat,
                "lon": lon,
                "coordinate_valid": validate_coordinate(lat, lon)["valid"],
                "source_row": int(idx) + 2,
            }
        )

    return records


def build_flood_station_master(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง flood_station_master รวม rainfall/waterlevel/dam master
    """

    def builder() -> Dict[str, Any]:
        master_sheets = load_flood_master_sheets(force_refresh=force_refresh)

        rainfall_df = get_master_sheet_by_name_or_key(
            master_sheets,
            FLOOD_MASTER_SHEETS.get("rainfall_station_master", "13_rainfall_station_master"),
        )

        waterlevel_df = get_master_sheet_by_name_or_key(
            master_sheets,
            FLOOD_MASTER_SHEETS.get("waterlevel_station_master", "14_waterlevel_station_master"),
        )

        dam_df = get_master_sheet_by_name_or_key(
            master_sheets,
            FLOOD_MASTER_SHEETS.get("dam_reservoir_master", "15_dam_reservoir_master"),
        )

        records = []
        records.extend(standardize_station_master(rainfall_df, "rainfall"))
        records.extend(standardize_station_master(waterlevel_df, "waterlevel"))
        records.extend(standardize_dam_master(dam_df))

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_MASTER_DATABASE_PATH),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["flood_station_master"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_flood_station_master",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def dataframe_to_geojson_features(df: pd.DataFrame, feature_type: str = "boundary") -> Dict[str, Any]:
    """
    แปลง boundary DataFrame เป็น GeoJSON เท่าที่ทำได้

    ถ้า sheet มี column geometry/geojson จะพยายามใช้
    ถ้าไม่มี จะคืน FeatureCollection ว่างพร้อม records fallback
    """

    if df is None or df.empty:
        return {
            "type": "FeatureCollection",
            "features": [],
            "records": [],
        }

    features: List[Dict[str, Any]] = []
    records = dataframe_to_records(df)

    for idx, row in df.iterrows():
        geometry_raw = get_value_by_candidates(
            row,
            ["geometry", "geojson", "geom"],
            default=None,
        )

        properties = {
            "feature_type": feature_type,
            "source_row": int(idx) + 2,
        }

        for key in df.columns:
            if clean_text_lower(key) not in {"geometry", "geojson", "geom"}:
                properties[clean_text(key)] = to_jsonable(row.get(key))

        if isinstance(geometry_raw, dict):
            geometry = geometry_raw
        else:
            geometry = None

            if geometry_raw:
                try:
                    import json
                    geometry_data = json.loads(str(geometry_raw))
                    if isinstance(geometry_data, dict):
                        if geometry_data.get("type") == "Feature":
                            features.append(geometry_data)
                            continue
                        geometry = geometry_data
                except Exception:
                    geometry = None

        if geometry:
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": properties,
                }
            )

    return {
        "type": "FeatureCollection",
        "features": features,
        "records": records,
    }


def build_province_boundaries(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง province boundaries payload
    """

    def builder() -> Dict[str, Any]:
        master_sheets = load_flood_master_sheets(force_refresh=force_refresh)

        df = get_master_sheet_by_name_or_key(
            master_sheets,
            FLOOD_MASTER_SHEETS.get("province_boundary", "11_province_boundary"),
        )

        geojson = dataframe_to_geojson_features(df, feature_type="province_boundary")
        geojson["created_at"] = now_iso()
        geojson["source_path"] = str(FLOOD_MASTER_DATABASE_PATH)

        return geojson

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["province_boundaries"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_province_boundaries",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_basin_boundaries(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง basin boundaries payload
    """

    def builder() -> Dict[str, Any]:
        master_sheets = load_flood_master_sheets(force_refresh=force_refresh)

        df = get_master_sheet_by_name_or_key(
            master_sheets,
            FLOOD_MASTER_SHEETS.get("basin_boundary", "12_basin_boundary"),
        )

        geojson = dataframe_to_geojson_features(df, feature_type="basin_boundary")
        geojson["created_at"] = now_iso()
        geojson["source_path"] = str(FLOOD_MASTER_DATABASE_PATH)

        return geojson

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["basin_boundaries"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_basin_boundaries",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


# ============================================================
# 8) FLOOD COMPUTED RISK
# ============================================================

def build_flood_computed_risk(force_refresh: bool = False) -> Dict[str, Any]:
    """
    รวม rainfall/waterlevel/dam latest และคำนวณ flood_computed_risk
    """

    def builder() -> Dict[str, Any]:
        rainfall = build_rainfall_latest(force_refresh=force_refresh).get("records", [])
        waterlevel = build_waterlevel_latest(force_refresh=force_refresh).get("records", [])
        large_dam = build_large_dam_latest(force_refresh=force_refresh).get("records", [])
        medium_dam = build_medium_dam_latest(force_refresh=force_refresh).get("records", [])
        all_long = build_all_long_latest(force_refresh=force_refresh).get("records", [])

        records = []
        records.extend(rainfall)
        records.extend(waterlevel)
        records.extend(large_dam)
        records.extend(medium_dam)

        if not records and all_long:
            records.extend(all_long)

        for record in records:
            record["risk_level"] = normalize_risk_level(record.get("risk_level"))
            record["risk_score"] = RISK_SCORE.get(record["risk_level"], -1)
            record["risk_color"] = RISK_COLORS.get(record["risk_level"], RISK_COLORS.get("Unknown", "#64748b"))

        records = sorted(
            records,
            key=lambda item: (
                -(to_number(item.get("risk_score"), -1) or -1),
                clean_text(item.get("province")),
                clean_text(item.get("source_name")),
            ),
        )

        risk_counts = Counter(record.get("risk_level", "Unknown") for record in records)
        source_counts = Counter(record.get("source_type", "unknown") for record in records)

        return {
            "records": records,
            "total": len(records),
            "risk_counts": dict(risk_counts),
            "source_counts": dict(source_counts),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["flood_computed_risk"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_flood_computed_risk",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_province_risk_summary(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง province_risk_summary จาก flood_computed_risk
    """

    def builder() -> Dict[str, Any]:
        risk_records = build_flood_computed_risk(force_refresh=force_refresh).get("records", [])
        groups = group_records_by(risk_records, "province")

        records: List[Dict[str, Any]] = []

        for province, group in groups.items():
            if province == "__EMPTY__":
                province = "Unknown"

            risk_level = combine_risk_levels([record.get("risk_level") for record in group])
            risk_counts = Counter(record.get("risk_level", "Unknown") for record in group)
            source_counts = Counter(record.get("source_type", "unknown") for record in group)

            records.append(
                {
                    "province": province,
                    "risk_level": risk_level,
                    "risk_score": RISK_SCORE.get(risk_level, -1),
                    "risk_color": RISK_COLORS.get(risk_level, RISK_COLORS.get("Unknown", "#64748b")),
                    "risk_counts": dict(risk_counts),
                    "source_counts": dict(source_counts),
                    "station_count": len(group),
                    "rainfall_count": source_counts.get("rainfall", 0),
                    "waterlevel_count": source_counts.get("waterlevel", 0),
                    "large_dam_count": source_counts.get("large_dam", 0),
                    "medium_dam_count": source_counts.get("medium_dam", 0),
                    "critical_count": risk_counts.get("Critical", 0),
                    "warning_count": risk_counts.get("Warning", 0),
                    "watch_count": risk_counts.get("Watch", 0),
                    "normal_count": risk_counts.get("Normal", 0),
                    "unknown_count": risk_counts.get("Unknown", 0),
                    "top_risk_sources": sorted(
                        group,
                        key=lambda item: to_number(item.get("risk_score"), -1) or -1,
                        reverse=True,
                    )[:10],
                }
            )

        records = sorted(
            records,
            key=lambda item: (
                -(to_number(item.get("risk_score"), -1) or -1),
                clean_text(item.get("province")),
            ),
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["province_risk_summary"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_province_risk_summary",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


# ============================================================
# 9) COMPANY / SPATIAL JOIN
# ============================================================

def load_company_unified_records() -> List[Dict[str, Any]]:
    """
    โหลด company_unified_master จาก cache
    """

    data = read_cache("company_unified_master", default={})

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


def split_flood_sources(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    แยก flood source ตาม source_type
    """

    result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for record in records:
        source_type = clean_text(record.get("source_type"), default="unknown")
        result[source_type].append(record)

    return dict(result)


def get_province_risk_index(force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    สร้าง index province -> risk summary
    """

    province_risk = build_province_risk_summary(force_refresh=force_refresh).get("records", [])

    return {
        normalize_province_name(record.get("province")): record
        for record in province_risk
        if normalize_province_name(record.get("province"))
    }


def build_single_company_flood_context_record(
    company: Dict[str, Any],
    flood_sources: Dict[str, List[Dict[str, Any]]],
    province_risk_index: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    สร้าง flood context ของ company 1 รายการ
    """

    tax_id_norm = normalize_tax_id(company.get("tax_id_norm") or company.get("tax_id"))
    company_name = clean_text(company.get("company_name"))
    province = normalize_province_name(company.get("province"))

    company_lat = to_number(company.get("lat"), None)
    company_lon = to_number(company.get("lon"), None)

    coord = validate_coordinate(company_lat, company_lon)

    rainfall_sources = flood_sources.get("rainfall", [])
    waterlevel_sources = flood_sources.get("waterlevel", [])
    dam_sources = flood_sources.get("large_dam", []) + flood_sources.get("medium_dam", []) + flood_sources.get("dam", [])

    nearest_rainfall = None
    nearest_waterlevel = None
    nearest_dam = None

    join_level = "none"
    risk_candidates: List[str] = []
    risk_reasons: List[str] = []

    if coord["valid"]:
        nearest_rainfall = find_nearest_record(
            company_lat,
            company_lon,
            rainfall_sources,
            max_distance_km=SPATIAL_NEAREST_STATION_LIMIT_KM,
        )

        nearest_waterlevel = find_nearest_record(
            company_lat,
            company_lon,
            waterlevel_sources,
            max_distance_km=SPATIAL_NEAREST_STATION_LIMIT_KM,
        )

        nearest_dam = find_nearest_record(
            company_lat,
            company_lon,
            dam_sources,
            max_distance_km=SPATIAL_NEAREST_STATION_LIMIT_KM,
        )

        for nearest, label in [
            (nearest_rainfall, "rainfall"),
            (nearest_waterlevel, "waterlevel"),
            (nearest_dam, "dam"),
        ]:
            if nearest:
                distance = to_number(nearest.get("_distance_km"), None)
                risk_level = normalize_risk_level(nearest.get("risk_level"))
                risk_candidates.append(risk_level)
                risk_reasons.append(
                    f"{label}:{nearest.get('source_name')} risk={risk_level} distance={distance}km"
                )

        if risk_candidates:
            join_level = "nearest_station"

    province_risk = province_risk_index.get(province)

    if province_risk:
        province_level = normalize_risk_level(province_risk.get("risk_level"))
        risk_candidates.append(province_level)
        risk_reasons.append(f"province:{province} risk={province_level}")

        if join_level == "none":
            join_level = "province"

    final_risk = combine_risk_levels(risk_candidates) if risk_candidates else "Unknown"

    has_flood_context = final_risk != "Unknown" or join_level != "none"

    return {
        "tax_id_norm": tax_id_norm,
        "company_name": company_name,

        "company_lat": company_lat,
        "company_lon": company_lon,
        "company_province": province,
        "company_district": clean_text(company.get("district")),
        "company_subdistrict": clean_text(company.get("subdistrict")),
        "location_quality": clean_text(company.get("location_quality")),

        "join_level": join_level,
        "has_flood_context": has_flood_context,

        "nearest_rainfall_station_id": nearest_rainfall.get("station_id") if nearest_rainfall else "",
        "nearest_rainfall_station_name": nearest_rainfall.get("station_name") if nearest_rainfall else "",
        "nearest_rainfall_distance_km": nearest_rainfall.get("_distance_km") if nearest_rainfall else None,
        "nearest_rainfall_risk_level": nearest_rainfall.get("risk_level") if nearest_rainfall else "Unknown",

        "nearest_waterlevel_station_id": nearest_waterlevel.get("station_id") if nearest_waterlevel else "",
        "nearest_waterlevel_station_name": nearest_waterlevel.get("station_name") if nearest_waterlevel else "",
        "nearest_waterlevel_distance_km": nearest_waterlevel.get("_distance_km") if nearest_waterlevel else None,
        "nearest_waterlevel_risk_level": nearest_waterlevel.get("risk_level") if nearest_waterlevel else "Unknown",

        "nearest_dam_id": nearest_dam.get("dam_id") if nearest_dam else "",
        "nearest_dam_name": nearest_dam.get("dam_name") if nearest_dam else "",
        "nearest_dam_distance_km": nearest_dam.get("_distance_km") if nearest_dam else None,
        "nearest_dam_risk_level": nearest_dam.get("risk_level") if nearest_dam else "Unknown",

        "province_risk_level": province_risk.get("risk_level") if province_risk else "Unknown",
        "station_risk_level": combine_risk_levels(
            [
                nearest_rainfall.get("risk_level") if nearest_rainfall else "Unknown",
                nearest_waterlevel.get("risk_level") if nearest_waterlevel else "Unknown",
                nearest_dam.get("risk_level") if nearest_dam else "Unknown",
            ]
        ),

        "final_flood_risk_level": final_risk,
        "flood_risk_level": final_risk,
        "flood_risk_score": RISK_SCORE.get(final_risk, -1),
        "flood_risk_color": RISK_COLORS.get(final_risk, RISK_COLORS.get("Unknown", "#64748b")),
        "flood_risk_reason": "; ".join(risk_reasons),

        "total_premium": company.get("total_premium", 0),
        "total_loss": company.get("total_loss", 0),
        "total_suminsure": company.get("total_suminsure", 0),
        "loss_ratio": company.get("loss_ratio"),
        "loss_ratio_band": company.get("loss_ratio_band", "Undefined"),

        "updated_at": now_iso(),
    }


def build_spatial_join_result(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง spatial_join_result

    เชื่อม:
    company_unified_master + flood_computed_risk + province_risk_summary
    """

    def builder() -> Dict[str, Any]:
        companies = load_company_unified_records()
        flood_records = build_flood_computed_risk(force_refresh=force_refresh).get("records", [])
        flood_sources = split_flood_sources(flood_records)
        province_risk_index = get_province_risk_index(force_refresh=force_refresh)

        records: List[Dict[str, Any]] = []

        for company in companies:
            record = build_single_company_flood_context_record(
                company=company,
                flood_sources=flood_sources,
                province_risk_index=province_risk_index,
            )
            records.append(record)

        records = sorted(
            records,
            key=lambda item: (
                -(to_number(item.get("flood_risk_score"), -1) or -1),
                clean_text(item.get("company_name")),
            ),
        )

        risk_counts = Counter(record.get("final_flood_risk_level", "Unknown") for record in records)
        join_counts = Counter(record.get("join_level", "none") for record in records)

        return {
            "records": records,
            "total": len(records),
            "risk_counts": dict(risk_counts),
            "join_counts": dict(join_counts),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["spatial_join_result"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_spatial_join_result",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_company_flood_context(force_refresh: bool = False) -> Dict[str, Any]:
    """
    alias สำหรับ company_flood_context
    """

    def builder() -> Dict[str, Any]:
        spatial = build_spatial_join_result(force_refresh=force_refresh)

        return {
            "records": spatial.get("records", []),
            "total": spatial.get("total", 0),
            "risk_counts": spatial.get("risk_counts", {}),
            "join_counts": spatial.get("join_counts", {}),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["company_flood_context"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_company_flood_context",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


# ============================================================
# 10) POLICY FLOOD EXPOSURE
# ============================================================

def build_policy_flood_exposure(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง policy_flood_exposure จาก spatial_join_result

    ใช้ดู exposure ตาม risk level:
    - total_suminsure
    - total_premium
    - total_loss
    - company_count
    """

    def builder() -> Dict[str, Any]:
        spatial_records = build_spatial_join_result(force_refresh=force_refresh).get("records", [])

        groups = group_records_by(spatial_records, "final_flood_risk_level")

        records: List[Dict[str, Any]] = []

        for risk_level, group in groups.items():
            if risk_level == "__EMPTY__":
                risk_level = "Unknown"

            records.append(
                {
                    "flood_risk_level": risk_level,
                    "risk_score": RISK_SCORE.get(risk_level, -1),
                    "risk_color": RISK_COLORS.get(risk_level, RISK_COLORS.get("Unknown", "#64748b")),
                    "company_count": len(group),
                    "total_premium": sum(to_number(item.get("total_premium"), 0) or 0 for item in group),
                    "total_loss": sum(to_number(item.get("total_loss"), 0) or 0 for item in group),
                    "total_suminsure": sum(to_number(item.get("total_suminsure"), 0) or 0 for item in group),
                    "company_records": group[:100],
                }
            )

        records = sorted(
            records,
            key=lambda item: to_number(item.get("risk_score"), -1) or -1,
            reverse=True,
        )

        summary = {
            "company_count": len(spatial_records),
            "total_premium": sum(to_number(item.get("total_premium"), 0) or 0 for item in spatial_records),
            "total_loss": sum(to_number(item.get("total_loss"), 0) or 0 for item in spatial_records),
            "total_suminsure": sum(to_number(item.get("total_suminsure"), 0) or 0 for item in spatial_records),
            "risk_counts": dict(Counter(item.get("final_flood_risk_level", "Unknown") for item in spatial_records)),
        }

        return {
            "records": records,
            "summary": summary,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["policy_flood_exposure"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_policy_flood_exposure",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_province_risk_exposure(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง province_risk_exposure

    group by company province
    """

    def builder() -> Dict[str, Any]:
        spatial_records = build_spatial_join_result(force_refresh=force_refresh).get("records", [])
        groups = group_records_by(spatial_records, "company_province")

        records: List[Dict[str, Any]] = []

        for province, group in groups.items():
            if province == "__EMPTY__":
                province = "Unknown"

            final_risk = combine_risk_levels([item.get("final_flood_risk_level") for item in group])
            risk_counts = Counter(item.get("final_flood_risk_level", "Unknown") for item in group)

            records.append(
                {
                    "province": province,
                    "flood_risk_level": final_risk,
                    "risk_score": RISK_SCORE.get(final_risk, -1),
                    "risk_color": RISK_COLORS.get(final_risk, RISK_COLORS.get("Unknown", "#64748b")),
                    "risk_counts": dict(risk_counts),
                    "company_count": len(group),
                    "company_with_flood_context_count": sum(1 for item in group if to_bool(item.get("has_flood_context"), default=False)),
                    "total_premium": sum(to_number(item.get("total_premium"), 0) or 0 for item in group),
                    "total_loss": sum(to_number(item.get("total_loss"), 0) or 0 for item in group),
                    "total_suminsure": sum(to_number(item.get("total_suminsure"), 0) or 0 for item in group),
                    "top_companies": sorted(
                        group,
                        key=lambda item: to_number(item.get("total_suminsure"), 0) or 0,
                        reverse=True,
                    )[:20],
                }
            )

        records = sorted(
            records,
            key=lambda item: (
                -(to_number(item.get("risk_score"), -1) or -1),
                -(to_number(item.get("total_suminsure"), 0) or 0),
            ),
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["province_risk_exposure"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_province_risk_exposure",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


# ============================================================
# 11) API FUNCTIONS - FLOOD
# ============================================================

def get_flood_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/flood/summary
    """

    ctx = normalize_context(context)

    rainfall = build_rainfall_latest(force_refresh=ctx.get("force_refresh", False))
    waterlevel = build_waterlevel_latest(force_refresh=ctx.get("force_refresh", False))
    large_dam = build_large_dam_latest(force_refresh=ctx.get("force_refresh", False))
    medium_dam = build_medium_dam_latest(force_refresh=ctx.get("force_refresh", False))
    computed = build_flood_computed_risk(force_refresh=ctx.get("force_refresh", False))
    province_risk = build_province_risk_summary(force_refresh=ctx.get("force_refresh", False))
    exposure = build_policy_flood_exposure(force_refresh=ctx.get("force_refresh", False))

    return {
        "rainfall_station_count": rainfall.get("total", 0),
        "waterlevel_station_count": waterlevel.get("total", 0),
        "large_dam_count": large_dam.get("total", 0),
        "medium_dam_count": medium_dam.get("total", 0),
        "computed_risk_count": computed.get("total", 0),
        "province_risk_count": province_risk.get("total", 0),
        "risk_counts": computed.get("risk_counts", {}),
        "source_counts": computed.get("source_counts", {}),
        "policy_flood_exposure": exposure.get("summary", {}),
        "files": {
            "flood_output_dir": file_info(FLOOD_OUTPUT_DIR),
            "latest_database": file_info(FLOOD_LATEST_DATABASE_PATH),
            "master_database": file_info(FLOOD_MASTER_DATABASE_PATH),
            "history_dir": file_info(FLOOD_HISTORY_DIR),
        },
        "generated_at": now_iso(),
    }


def get_rainfall_latest(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/flood/rainfall/latest
    """

    ctx = normalize_context(context)
    records = build_rainfall_latest(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_waterlevel_latest(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/flood/waterlevel/latest
    """

    ctx = normalize_context(context)
    records = build_waterlevel_latest(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_large_dam_latest(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/flood/dam/large/latest
    """

    ctx = normalize_context(context)
    records = build_large_dam_latest(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_medium_dam_latest(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/flood/dam/medium/latest
    """

    ctx = normalize_context(context)
    records = build_medium_dam_latest(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_flood_computed_risk(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/flood/computed-risk
    """

    ctx = normalize_context(context)
    data = build_flood_computed_risk(force_refresh=ctx.get("force_refresh", False))
    records = data.get("records", [])

    result = filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")
    result["risk_counts"] = data.get("risk_counts", {})
    result["source_counts"] = data.get("source_counts", {})

    return result


def get_province_boundaries() -> Dict[str, Any]:
    """
    API:
    GET /api/flood/boundaries/province
    """

    return build_province_boundaries(force_refresh=False)


def get_basin_boundaries() -> Dict[str, Any]:
    """
    API:
    GET /api/flood/boundaries/basin
    """

    return build_basin_boundaries(force_refresh=False)


def refresh_flood_cache(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    POST /api/flood/refresh
    """

    return rebuild_flood_spatial_cache(force_refresh=True)


# ============================================================
# 12) API FUNCTIONS - SPATIAL
# ============================================================

def get_company_flood_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/spatial/company-flood-context
    """

    ctx = normalize_context(context)
    records = build_company_flood_context(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_api(records, ctx, SPATIAL_SEARCHABLE_FIELDS, target="spatial")


def get_single_company_flood_context(tax_id: str) -> Dict[str, Any]:
    """
    API:
    GET /api/spatial/company/<tax_id>/flood-context
    """

    tax_id_norm = normalize_tax_id(tax_id)
    records = build_company_flood_context(force_refresh=False).get("records", [])

    record = next(
        (item for item in records if item.get("tax_id_norm") == tax_id_norm),
        None,
    )

    return {
        "tax_id": tax_id,
        "tax_id_norm": tax_id_norm,
        "found": record is not None,
        "context": record or {},
    }


def get_policy_flood_exposure(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/spatial/policy-flood-exposure
    """

    ctx = normalize_context(context)
    data = build_policy_flood_exposure(force_refresh=ctx.get("force_refresh", False))
    records = data.get("records", [])

    result = filter_records_api(records, ctx, ["flood_risk_level"], target="spatial")
    result["summary"] = data.get("summary", {})

    return result


def get_province_risk_exposure(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/spatial/province-risk-exposure
    """

    ctx = normalize_context(context)
    records = build_province_risk_exposure(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_api(records, ctx, ["province", "flood_risk_level"], target="spatial")


def get_nearest_stations_for_company(tax_id: str) -> Dict[str, Any]:
    """
    API:
    GET /api/spatial/nearest-stations/<tax_id>
    """

    tax_id_norm = normalize_tax_id(tax_id)
    context = get_single_company_flood_context(tax_id_norm).get("context", {})

    return {
        "tax_id": tax_id,
        "tax_id_norm": tax_id_norm,
        "rainfall": {
            "station_id": context.get("nearest_rainfall_station_id"),
            "station_name": context.get("nearest_rainfall_station_name"),
            "distance_km": context.get("nearest_rainfall_distance_km"),
            "risk_level": context.get("nearest_rainfall_risk_level"),
        },
        "waterlevel": {
            "station_id": context.get("nearest_waterlevel_station_id"),
            "station_name": context.get("nearest_waterlevel_station_name"),
            "distance_km": context.get("nearest_waterlevel_distance_km"),
            "risk_level": context.get("nearest_waterlevel_risk_level"),
        },
        "dam": {
            "dam_id": context.get("nearest_dam_id"),
            "dam_name": context.get("nearest_dam_name"),
            "distance_km": context.get("nearest_dam_distance_km"),
            "risk_level": context.get("nearest_dam_risk_level"),
        },
        "final_flood_risk_level": context.get("final_flood_risk_level"),
        "join_level": context.get("join_level"),
    }


# ============================================================
# 13) MAP SUPPORT
# ============================================================

def make_flood_point_features(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    สร้าง GeoJSON FeatureCollection จาก flood records
    """

    features: List[Dict[str, Any]] = []

    for record in records:
        feature = make_point_feature(
            lon=record.get("lon"),
            lat=record.get("lat"),
            properties={
                "feature_id": record.get("source_key"),
                "feature_type": record.get("source_type"),
                "source_type": record.get("source_type"),
                "source_id": record.get("source_id"),
                "source_name": record.get("source_name"),
                "province": record.get("province"),
                "basin": record.get("basin"),
                "risk_level": record.get("risk_level"),
                "risk_score": record.get("risk_score"),
                "risk_color": record.get("risk_color"),
                "risk_reason": record.get("risk_reason"),
                "data_datetime": record.get("data_datetime"),
                "marker_color": record.get("risk_color"),
                "marker_size": 8 + max(0, to_number(record.get("risk_score"), 0) or 0) * 3,
            },
        )

        if feature:
            features.append(feature)

    return make_feature_collection(features)


def get_flood_map_feature_collection(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    ใช้โดย map_graph_service.py เพื่อสร้าง flood layer
    """

    ctx = normalize_context(context)
    records = build_flood_computed_risk(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    result = filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")
    return make_flood_point_features(result.get("records", []))


def get_company_flood_map_feature_collection(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    ใช้โดย map_graph_service.py เพื่อสร้าง company flood exposure layer
    """

    ctx = normalize_context(context)
    records = build_company_flood_context(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    result = filter_records_api(records, ctx, SPATIAL_SEARCHABLE_FIELDS, target="spatial")

    features: List[Dict[str, Any]] = []

    for record in result.get("records", []):
        risk_level = normalize_risk_level(record.get("final_flood_risk_level"))

        feature = make_point_feature(
            lon=record.get("company_lon"),
            lat=record.get("company_lat"),
            properties={
                "feature_id": record.get("tax_id_norm"),
                "feature_type": "company_flood_context",
                "tax_id_norm": record.get("tax_id_norm"),
                "company_name": record.get("company_name"),
                "province": record.get("company_province"),
                "flood_risk_level": risk_level,
                "risk_level": risk_level,
                "risk_color": RISK_COLORS.get(risk_level, RISK_COLORS.get("Unknown", "#64748b")),
                "join_level": record.get("join_level"),
                "flood_risk_reason": record.get("flood_risk_reason"),
                "total_premium": record.get("total_premium"),
                "total_suminsure": record.get("total_suminsure"),
                "marker_color": RISK_COLORS.get(risk_level, RISK_COLORS.get("Unknown", "#64748b")),
                "marker_size": 10 + max(0, to_number(record.get("flood_risk_score"), 0) or 0) * 3,
            },
        )

        if feature:
            features.append(feature)

    return make_feature_collection(features)


# ============================================================
# 14) CACHE REBUILD / DASHBOARD SUPPORT
# ============================================================

def rebuild_flood_spatial_cache(force_refresh: bool = True) -> Dict[str, Any]:
    """
    rebuild cache ทั้งหมดของ flood_spatial_service.py
    """

    results = {
        "rainfall_latest": build_rainfall_latest(force_refresh=force_refresh),
        "waterlevel_latest": build_waterlevel_latest(force_refresh=force_refresh),
        "large_dam_latest": build_large_dam_latest(force_refresh=force_refresh),
        "medium_dam_latest": build_medium_dam_latest(force_refresh=force_refresh),
        "all_long_latest": build_all_long_latest(force_refresh=force_refresh),
        "flood_station_master": build_flood_station_master(force_refresh=force_refresh),
        "province_boundaries": build_province_boundaries(force_refresh=force_refresh),
        "basin_boundaries": build_basin_boundaries(force_refresh=force_refresh),
        "flood_computed_risk": build_flood_computed_risk(force_refresh=force_refresh),
        "province_risk_summary": build_province_risk_summary(force_refresh=force_refresh),
        "spatial_join_result": build_spatial_join_result(force_refresh=force_refresh),
        "company_flood_context": build_company_flood_context(force_refresh=force_refresh),
        "policy_flood_exposure": build_policy_flood_exposure(force_refresh=force_refresh),
        "province_risk_exposure": build_province_risk_exposure(force_refresh=force_refresh),
    }

    return {
        "rebuilt": True,
        "results": {
            key: {
                "total": value.get("total"),
                "cache_used": value.get("cache_used"),
                "created_at": value.get("created_at"),
            }
            for key, value in results.items()
        },
        "generated_at": now_iso(),
    }


def get_flood_dashboard_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง payload สำหรับ dashboard_package_service.py
    """

    ctx = normalize_context(context)

    summary = get_flood_summary(ctx)

    computed = get_flood_computed_risk(
        {
            **ctx,
            "page": 1,
            "page_size": 20,
            "sort_by": "risk_score",
            "sort_dir": "desc",
        }
    )

    province_exposure = get_province_risk_exposure(
        {
            **ctx,
            "page": 1,
            "page_size": 20,
            "sort_by": "risk_score",
            "sort_dir": "desc",
        }
    )

    policy_exposure = get_policy_flood_exposure(ctx)

    return {
        "summary": summary,
        "top_risk_sources": computed.get("records", []),
        "province_risk_exposure": province_exposure.get("records", []),
        "policy_flood_exposure": policy_exposure.get("summary", {}),
        "risk_counts": summary.get("risk_counts", {}),
        "source_counts": summary.get("source_counts", {}),
        "generated_at": now_iso(),
    }

# ============================================================
# 15) FLOOD RUNTIME OVERRIDES - LATEST / HISTORY / MASTER / PREDICTION
# ============================================================

def normalize_risk_status(value: Any) -> str:
    """
    normalize risk status สำหรับ latest/prediction display
    """

    text = clean_text(value)

    if not text:
        return "Unknown"

    lowered = text.strip().lower()

    risk_map = getattr(config, "PREDICTION_RISK_NORMALIZE_MAP", {})

    if isinstance(risk_map, dict) and lowered in risk_map:
        return risk_map[lowered]

    if lowered in {"normal", "ปกติ", "1.ปกติ"}:
        return "Normal"

    if lowered in {"watch", "เฝ้าระวัง", "2.เฝ้าระวัง"}:
        return "Watch"

    if lowered in {"warning", "เตือน", "เตือนภัย", "3.เตือนภัย"}:
        return "Warning"

    if lowered in {"critical", "วิกฤต", "4.วิกฤต"}:
        return "Critical"

    return normalize_risk_level(text)


def classify_rainfall_risk(row: Any) -> Dict[str, Any]:
    rainfall = get_value_by_candidates(
        row,
        [
            "rainfall_value",
            "rainfall",
            "rain_24h",
            "rainfall_24h",
            "rainfall_mm",
            "value",
            "latest_value",
        ],
        default=None,
    )
    return calculate_rainfall_risk(rainfall)


def classify_waterlevel_risk(row: Any) -> Dict[str, Any]:
    waterlevel = get_value_by_candidates(
        row,
        [
            "waterlevel_value",
            "waterlevel",
            "water_level",
            "level",
            "value",
            "latest_value",
        ],
        default=None,
    )

    warning_level = get_value_by_candidates(
        row,
        [
            "warning_level",
            "warning",
            "warn_level",
            "warning_level_m",
        ],
        default=None,
    )

    critical_level = get_value_by_candidates(
        row,
        [
            "critical_level",
            "critical",
            "danger_level",
            "critical_level_m",
        ],
        default=None,
    )

    return calculate_waterlevel_risk(
        waterlevel,
        warning_level=warning_level,
        critical_level=critical_level,
    )


def classify_dam_risk(row: Any) -> Dict[str, Any]:
    storage_percent = get_value_by_candidates(
        row,
        [
            "storage_percent",
            "percent_storage",
            "storage_pct",
            "storage_percentage",
            "percent",
            "latest_value",
        ],
        default=None,
    )

    if to_number(storage_percent, None) is None:
        storage = to_number(
            get_value_by_candidates(row, ["storage", "water_storage", "current_storage"], default=None),
            None,
        )
        capacity = to_number(
            get_value_by_candidates(row, ["capacity", "dam_capacity", "full_capacity"], default=None),
            None,
        )

        if storage is not None and capacity not in (None, 0):
            storage_percent = round((storage / capacity) * 100, 4)

    return calculate_dam_risk(storage_percent)


def get_display_value(row: Any, source_type: str = "") -> Any:
    source = clean_text_lower(source_type or get_value_by_candidates(row, ["source_type"], default=""))

    if source == "rainfall":
        return get_value_by_candidates(
            row,
            ["rainfall_value", "rainfall_24h", "rainfall_mm", "value", "latest_value"],
            default=None,
        )

    if source == "waterlevel":
        return get_value_by_candidates(
            row,
            ["waterlevel_value", "water_level", "level", "value", "latest_value"],
            default=None,
        )

    if source in {"dam", "large_dam", "medium_dam"}:
        return get_value_by_candidates(
            row,
            ["storage_percent", "percent_storage", "storage_pct", "value", "latest_value"],
            default=None,
        )

    return get_value_by_candidates(row, ["latest_value", "value", "measure_value"], default=None)


def get_display_unit(row: Any, source_type: str = "") -> str:
    source = clean_text_lower(source_type or get_value_by_candidates(row, ["source_type"], default=""))

    if source == "rainfall":
        return "mm"

    if source == "waterlevel":
        return "m"

    if source in {"dam", "large_dam", "medium_dam"}:
        return "%"

    return clean_text(get_value_by_candidates(row, ["unit", "latest_unit"], default=""))


def get_dam_display_name(row: Any) -> str:
    return clean_text(
        get_value_by_candidates(
            row,
            [
                "display_name",
                "dam_name",
                "medium_name",
                "reservoir_name",
                "source_name",
                "name",
            ],
            default="",
        )
    )


def normalize_latest_record_display(record: Dict[str, Any], source_type: str) -> Dict[str, Any]:
    result = dict(record)
    lat = result.get("lat") if result.get("lat") is not None else result.get("latitude")
    lon = result.get("lon") if result.get("lon") is not None else result.get("longitude")
    coord = validate_coordinate(lat, lon)

    result["source_type"] = clean_text(result.get("source_type"), default=source_type)
    result["latest_value"] = get_display_value(result, result["source_type"])
    result["latest_unit"] = get_display_unit(result, result["source_type"])
    result["display_name"] = clean_text(
        result.get("display_name")
        or result.get("source_name")
        or result.get("station_name")
        or result.get("dam_name")
        or get_dam_display_name(result)
    )
    result["latitude"] = coord.get("lat")
    result["longitude"] = coord.get("lon")
    result["lat"] = coord.get("lat")
    result["lon"] = coord.get("lon")
    result["has_location"] = bool(coord.get("valid"))
    result["map_ready"] = bool(coord.get("valid"))

    risk_level = normalize_risk_status(result.get("risk_level") or result.get("risk_status"))
    result["risk_level"] = risk_level
    result["risk_status"] = risk_level
    result["risk_score"] = RISK_SCORE.get(risk_level, -1)
    result["risk_color"] = RISK_COLORS.get(risk_level, RISK_COLORS.get("Unknown", "#64748b"))

    return result


def normalize_latest_records_display(records: List[Dict[str, Any]], source_type: str) -> List[Dict[str, Any]]:
    return [
        normalize_latest_record_display(record, source_type=source_type)
        for record in records or []
    ]


def ensure_risk_column(df: pd.DataFrame, source_type: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()

    risks: List[str] = []

    for _, row in result.iterrows():
        if source_type == "rainfall":
            risk = classify_rainfall_risk(row)
        elif source_type == "waterlevel":
            risk = classify_waterlevel_risk(row)
        elif source_type in {"dam", "large_dam", "medium_dam"}:
            risk = classify_dam_risk(row)
        else:
            risk = {"risk_level": normalize_risk_status(get_value_by_candidates(row, ["risk_level", "risk_status"], default="Unknown"))}

        risks.append(risk.get("risk_level", "Unknown"))

    result["risk_level"] = risks
    result["risk_status"] = risks

    return result

def load_flood_latest_sheets(force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    """
    อ่าน latest_database.xlsx ผ่าน Excel source layer
    """

    sheet_keys = [
        "rainfall_latest",
        "waterlevel_latest",
        "large_dam_latest",
        "medium_dam_latest",
        "all_long_latest",
    ]

    result: Dict[str, pd.DataFrame] = {}

    for key in sheet_keys:
        result[key] = clean_dataframe_common(
            read_latest_sheet(
                key,
                use_cache=not force_refresh,
                return_meta=False,
            )
        )

    return result


def load_flood_master_sheets(force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    """
    อ่าน master_database.xlsx ผ่าน Excel source layer
    """

    master_keys = [
        "province_boundary",
        "basin_boundary",
        "rainfall_station_master",
        "waterlevel_station_master",
        "dam_reservoir_master",
        "location_master",
        "data_quality_log",
        "error_log",
        "scrape_runs",
        "daily_loop_runs",
        "daily_loop_rounds",
    ]

    result: Dict[str, pd.DataFrame] = {}

    for key in master_keys:
        sheet_name = getattr(config, "MASTER_SHEETS", {}).get(key, key)
        result[key] = clean_dataframe_common(
            read_master_sheet(
                key,
                use_cache=not force_refresh,
                return_meta=False,
            )
        )
        result[sheet_name] = result[key]

    return result


def read_history_dataframe(
    data_type: Any,
    year: Any,
    month: Any,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    อ่าน history dataframe ผ่าน Excel source layer
    """

    return clean_dataframe_common(
        read_history_sheet(
            data_type=data_type,
            year=year,
            month=month,
            sheet_name=None,
            use_cache=not force_refresh,
            return_meta=False,
        )
    )

def build_rainfall_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง rainfall latest records
    """

    def builder() -> Dict[str, Any]:
        df = load_flood_latest_sheets(force_refresh=force_refresh).get("rainfall_latest", pd.DataFrame())
        records = normalize_latest_records_display(
            standardize_rainfall_latest(ensure_risk_column(df, "rainfall")),
            source_type="rainfall",
        )

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": getattr(config, "LATEST_SHEETS", {}).get("rainfall_latest", "02_rainfall_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["rainfall_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_rainfall_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_waterlevel_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง waterlevel latest records
    """

    def builder() -> Dict[str, Any]:
        df = load_flood_latest_sheets(force_refresh=force_refresh).get("waterlevel_latest", pd.DataFrame())
        records = normalize_latest_records_display(
            standardize_waterlevel_latest(ensure_risk_column(df, "waterlevel")),
            source_type="waterlevel",
        )

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": getattr(config, "LATEST_SHEETS", {}).get("waterlevel_latest", "05_waterlevel_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["waterlevel_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_waterlevel_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_large_dam_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง large dam latest records
    """

    def builder() -> Dict[str, Any]:
        df = load_flood_latest_sheets(force_refresh=force_refresh).get("large_dam_latest", pd.DataFrame())
        records = normalize_latest_records_display(
            standardize_dam_latest(ensure_risk_column(df, "large_dam"), dam_type="large_dam"),
            source_type="large_dam",
        )

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": getattr(config, "LATEST_SHEETS", {}).get("large_dam_latest", "07_large_dam_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["large_dam_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_large_dam_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_medium_dam_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง medium dam latest records
    """

    def builder() -> Dict[str, Any]:
        df = load_flood_latest_sheets(force_refresh=force_refresh).get("medium_dam_latest", pd.DataFrame())
        records = normalize_latest_records_display(
            standardize_dam_latest(ensure_risk_column(df, "medium_dam"), dam_type="medium_dam"),
            source_type="medium_dam",
        )

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": getattr(config, "LATEST_SHEETS", {}).get("medium_dam_latest", "09_medium_dam_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["medium_dam_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_medium_dam_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def build_all_long_latest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง all_long latest records
    """

    def builder() -> Dict[str, Any]:
        df = load_flood_latest_sheets(force_refresh=force_refresh).get("all_long_latest", pd.DataFrame())
        records = normalize_latest_records_display(
            standardize_all_long_latest(df),
            source_type="all_long",
        )

        return {
            "records": records,
            "total": len(records),
            "source_path": str(FLOOD_LATEST_DATABASE_PATH),
            "source_sheet": getattr(config, "LATEST_SHEETS", {}).get("all_long_latest", "17_all_long_latest"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["all_long_latest"],
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_all_long_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}

def get_latest_rainfall(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/latest/rainfall
    """

    return get_rainfall_latest(context=context)


def get_latest_waterlevel(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/latest/waterlevel
    """

    return get_waterlevel_latest(context=context)


def get_latest_large_dam(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/latest/dam/large
    """

    return get_large_dam_latest(context=context)


def get_latest_medium_dam(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/latest/dam/medium
    """

    return get_medium_dam_latest(context=context)


def get_latest_dam(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/latest/dam
    """

    ctx = normalize_context(context)
    dam_size = clean_text_lower(ctx.get("dam_size") or ctx.get("size") or "all")

    records: List[Dict[str, Any]] = []

    if dam_size in {"large", "large_dam", "all", ""}:
        records.extend(build_large_dam_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))

    if dam_size in {"medium", "medium_dam", "all", ""}:
        records.extend(build_medium_dam_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_all_long_latest(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/latest/all-long
    """

    ctx = normalize_context(context)
    records = build_all_long_latest(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")

def get_rainfall_station_master(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    df = read_master_sheet("rainfall_station_master", use_cache=not ctx.get("force_refresh", False), return_meta=False)
    records = standardize_station_master(clean_dataframe_common(df), station_type="rainfall")

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_waterlevel_station_master(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    df = read_master_sheet("waterlevel_station_master", use_cache=not ctx.get("force_refresh", False), return_meta=False)
    records = standardize_station_master(clean_dataframe_common(df), station_type="waterlevel")

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_dam_reservoir_master(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    df = read_master_sheet("dam_reservoir_master", use_cache=not ctx.get("force_refresh", False), return_meta=False)
    records = standardize_dam_master(clean_dataframe_common(df))

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_location_master(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    df = clean_dataframe_common(
        read_master_sheet(
            "location_master",
            use_cache=not ctx.get("force_refresh", False),
            return_meta=False,
        )
    )
    records = dataframe_to_records(df)

    return filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")


def get_province_boundary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_province_boundaries()


def get_basin_boundary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_basin_boundaries()

def get_history(
    data_type: str,
    year: Any,
    month: Any,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    อ่าน history ตาม data_type/year/month
    """

    ctx = normalize_context(context)
    normalized_type = config.normalize_history_data_type(data_type) if hasattr(config, "normalize_history_data_type") else clean_text(data_type)
    df = read_history_dataframe(
        data_type=normalized_type,
        year=year,
        month=month,
        force_refresh=ctx.get("force_refresh", False),
    )

    records = dataframe_to_records(df)
    result = filter_records_api(records, ctx, FLOOD_SEARCHABLE_FIELDS, target="flood")

    result["data_type"] = normalized_type
    result["year"] = year
    result["month"] = month
    result["source_file"] = str(config.get_history_file(normalized_type, year, month)) if hasattr(config, "get_history_file") else ""
    result["source_sheet"] = config.get_history_sheet(normalized_type) if hasattr(config, "get_history_sheet") else ""

    return result


def get_history_rainfall(year: Any, month: Any, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_history("rainfall", year=year, month=month, context=context)


def get_history_rain15d(year: Any, month: Any, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_history("rain15d", year=year, month=month, context=context)


def get_history_rain_yearly(year: Any, month: Any, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_history("rain_yearly", year=year, month=month, context=context)


def get_history_waterlevel(year: Any, month: Any, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_history("waterlevel", year=year, month=month, context=context)


def get_history_dam(
    data_type: str = "large_dam",
    year: Any = None,
    month: Any = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return get_history(data_type or "large_dam", year=year, month=month, context=context)


def get_history_all_long(year: Any, month: Any, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_history("all_long", year=year, month=month, context=context)

def list_prediction_files() -> List[Path]:
    prediction_dir = Path(getattr(config, "PREDICTION_DATA_DIR", getattr(config, "FLOOD_PREDICTION_DIR", "")))
    prediction_glob = getattr(config, "PREDICTION_FILE_GLOB", "predict_*.xlsx")

    if not prediction_dir.exists():
        return []

    return sorted(
        [
            path
            for path in prediction_dir.glob(prediction_glob)
            if path.is_file()
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def find_prediction_file(data_date: Optional[Any] = None) -> Optional[Path]:
    files = list_prediction_files()

    if not files:
        return None

    wanted = clean_text(data_date)

    if not wanted:
        return files[0]

    wanted_digits = "".join(ch for ch in wanted if ch.isdigit())

    for path in files:
        path_digits = "".join(ch for ch in path.stem if ch.isdigit())

        if wanted in path.name or wanted_digits and wanted_digits in path_digits:
            return path

    return files[0]


def get_prediction_file_date(path: Optional[Path]) -> str:
    if path is None:
        return ""

    if hasattr(config, "get_prediction_file_date"):
        try:
            return clean_text(config.get_prediction_file_date(path))
        except Exception:
            pass

    digits = "".join(ch if ch.isdigit() else " " for ch in path.stem).split()

    for item in digits:
        if len(item) == 8:
            return f"{item[0:4]}-{item[4:6]}-{item[6:8]}"

    return ""


def read_prediction_dataframe(
    data_date: Optional[Any] = None,
    force_refresh: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    prediction_file = find_prediction_file(data_date=data_date)

    if prediction_file is None:
        return pd.DataFrame(), {
            "source": "excel",
            "source_file": None,
            "file_name": None,
            "data_date": clean_text(data_date),
            "file_exists": False,
            "record_count": 0,
        }

    df = clean_dataframe_common(
        read_prediction_file(
            file_path=prediction_file,
            use_cache=not force_refresh,
            return_meta=False,
        )
    )

    meta = {
        "source": "excel",
        "source_file": str(prediction_file),
        "file_name": prediction_file.name,
        "data_date": get_prediction_file_date(prediction_file) or clean_text(data_date),
        "file_exists": prediction_file.exists(),
        "record_count": len(df),
        "file_modified_at": datetime.fromtimestamp(prediction_file.stat().st_mtime).isoformat(timespec="seconds"),
    }

    return df, meta


def normalize_prediction_dataframe(df: pd.DataFrame, meta: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()
    result.columns = [clean_column_name(col) for col in result.columns]

    if "province_model" not in result.columns and "province" in result.columns:
        result["province_model"] = result["province"]

    if "province" not in result.columns and "province_model" in result.columns:
        result["province"] = result["province_model"]

    if "station_name" not in result.columns:
        station_col = find_first_existing_column(
            result,
            [
                "station_name_th",
                "tele_station_name",
                "waterlevel_station_name",
                "name",
            ],
        )
        result["station_name"] = result[station_col] if station_col else ""

    if "base_date" not in result.columns:
        result["base_date"] = first_value_from_dataframe_columns(
            result,
            ["data_date", "predict_date", "file_date"],
            default=meta.get("data_date") if isinstance(meta, dict) else "",
        )

    if "target_date" not in result.columns:
        result["target_date"] = first_value_from_dataframe_columns(
            result,
            ["forecast_date", "target", "date"],
            default="",
        )

    if "forecast_horizon_day" not in result.columns:
        horizon_col = find_first_existing_column(result, ["horizon", "prediction_horizon"])
        result["forecast_horizon_day"] = result[horizon_col] if horizon_col else None

    return clean_dataframe_common(result)


def first_value_from_dataframe_columns(
    df: pd.DataFrame,
    candidates: List[str],
    default: Any = "",
) -> List[Any]:
    values: List[Any] = []

    for _, row in df.iterrows():
        values.append(
            get_value_by_candidates(
                row,
                candidates,
                default=default,
            )
        )

    return values


def normalize_prediction_risk(row: Any) -> str:
    direct = get_value_by_candidates(
        row,
        [
            "risk_level",
            "risk_status",
            "warning_level_predict",
            "warning_level",
            "status",
        ],
        default="",
    )

    if not is_empty_value(direct):
        return normalize_risk_status(direct)

    percent_to_bank = to_number(
        get_value_by_candidates(row, ["percent_to_bank"], default=None),
        None,
    )

    from_bank_m = to_number(
        get_value_by_candidates(row, ["from_bank_m", "diff_from_bank_m"], default=None),
        None,
    )

    if from_bank_m is not None:
        if from_bank_m <= 0:
            return "Critical"
        if from_bank_m <= 0.50:
            return "Warning"
        if from_bank_m <= 1.00:
            return "Watch"
        return "Normal"

    if percent_to_bank is not None:
        if percent_to_bank >= 100:
            return "Critical"
        if percent_to_bank >= 90:
            return "Warning"
        if percent_to_bank >= 80:
            return "Watch"
        return "Normal"

    return "Unknown"


def make_prediction_record_key(row: Any) -> str:
    station = clean_text(
        get_value_by_candidates(
            row,
            [
                "station_id",
                "station_code",
                "station_name",
                "station_name_th",
            ],
            default="station",
        )
    )

    base_date = clean_text(get_value_by_candidates(row, ["base_date", "data_date", "predict_date"], default=""))
    target_date = clean_text(get_value_by_candidates(row, ["target_date", "forecast_date"], default=""))
    horizon = clean_text(get_value_by_candidates(row, ["forecast_horizon_day", "horizon"], default=""))

    raw_key = f"prediction|{station}|{base_date}|{target_date}|{horizon}"
    return raw_key


def build_station_location_index(force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    cache_key = CACHE_KEYS["flood_master_station_index"]

    def builder() -> Dict[str, Any]:
        rainfall = get_rainfall_station_master({"force_refresh": force_refresh, "page_size": 100000}).get("records", [])
        waterlevel = get_waterlevel_station_master({"force_refresh": force_refresh, "page_size": 100000}).get("records", [])

        index: Dict[str, Dict[str, Any]] = {}

        for source_name, records in [
            ("waterlevel_station_master", waterlevel),
            ("rainfall_station_master", rainfall),
        ]:
            for record in records:
                keys = prediction_location_match_keys(record)

                for key in keys:
                    if key and key not in index:
                        item = dict(record)
                        item["matched_source"] = source_name
                        index[key] = item

        return {
            "index": index,
            "total": len(index),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=cache_key,
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_station_location_index",
    )

    return cache_result["data"].get("index", {})


def prediction_location_match_keys(row: Any) -> List[str]:
    values = [
        get_value_by_candidates(row, ["station_id", "matched_station_id", "source_id"], default=""),
        get_value_by_candidates(row, ["station_code", "matched_station_code", "code"], default=""),
        get_value_by_candidates(row, ["station_name", "station_name_th", "matched_station_name", "source_name"], default=""),
    ]

    province = normalize_province_name(
        get_value_by_candidates(
            row,
            ["province", "province_model", "province_name_th"],
            default="",
        )
    )

    keys: List[str] = []

    for value in values:
        text = clean_text_lower(value)

        if not text:
            continue

        keys.append(text)

        if province:
            keys.append(f"{province}|{text}".lower())

    return list(dict.fromkeys(keys))


def find_prediction_station_location_match(
    row: Any,
    station_index: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    keys = prediction_location_match_keys(row)

    for key in keys:
        if key in station_index:
            return station_index[key], {
                "location_match_status": "matched",
                "location_match_key": key,
                "location_match_candidates": keys,
                "location_match_reason": "matched by station master key",
            }

    return None, {
        "location_match_status": "not_matched",
        "location_match_key": "",
        "location_match_candidates": keys,
        "location_match_reason": "no station master key matched",
    }


def enrich_prediction_location(
    record: Dict[str, Any],
    station_index: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    result = dict(record)
    match, debug = find_prediction_station_location_match(result, station_index)

    province = normalize_province_name(
        result.get("province_model")
        or result.get("province")
        or result.get("province_name_th")
    )

    result["province"] = province
    result["province_model"] = province

    if match:
        lat = match.get("lat")
        lon = match.get("lon")
        coord = validate_coordinate(lat, lon)

        result["matched_source"] = match.get("matched_source", "")
        result["matched_station_id"] = match.get("station_id") or match.get("source_id")
        result["matched_station_code"] = match.get("station_code") or match.get("source_id")
        result["matched_station_name"] = match.get("station_name") or match.get("source_name")
        result["lat"] = coord.get("lat")
        result["lon"] = coord.get("lon")
        result["latitude"] = coord.get("lat")
        result["longitude"] = coord.get("lon")
        result["has_location"] = bool(coord.get("valid"))
        result["map_ready"] = bool(coord.get("valid"))
        result["focus_level"] = "point" if coord.get("valid") else "province_boundary"
        result["focus_fallback"] = None if coord.get("valid") else {"type": "province_boundary", "province": province}
        result["focus_fallback_reason"] = "" if coord.get("valid") else "matched station has invalid coordinate"

    else:
        result["matched_source"] = ""
        result["matched_station_id"] = ""
        result["matched_station_code"] = ""
        result["matched_station_name"] = ""
        result["lat"] = None
        result["lon"] = None
        result["latitude"] = None
        result["longitude"] = None
        result["has_location"] = False
        result["map_ready"] = False
        result["focus_level"] = "province_boundary" if province else "none"
        result["focus_fallback"] = {"type": "province_boundary", "province": province} if province else None
        result["focus_fallback_reason"] = "station location not matched; fallback to province boundary" if province else "station location and province missing"

    result.update(debug)

    return result


def normalize_prediction_records(
    df: pd.DataFrame,
    meta: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    normalized_df = normalize_prediction_dataframe(df, meta=meta or {})

    if normalized_df.empty:
        return []

    station_index = build_station_location_index(force_refresh=force_refresh)
    records: List[Dict[str, Any]] = []

    for idx, row in normalized_df.iterrows():
        record = {
            key: to_jsonable(value)
            for key, value in row.to_dict().items()
        }

        risk = normalize_prediction_risk(row)
        record["risk_level"] = risk
        record["risk_status"] = risk
        record["warning_level_predict"] = risk
        record["risk_score"] = RISK_SCORE.get(risk, -1)
        record["risk_color"] = RISK_COLORS.get(risk, RISK_COLORS.get("Unknown", "#64748b"))

        record["station_id"] = clean_text(
            record.get("station_id")
            or record.get("station_code")
            or record.get("station_name")
            or record.get("station_name_th")
        )
        record["station_name"] = clean_text(record.get("station_name") or record.get("station_name_th") or record.get("station_id"))
        record["station_name_th"] = clean_text(record.get("station_name_th") or record.get("station_name"))
        record["record_key"] = make_prediction_record_key(record)
        record["source_type"] = "prediction"
        record["source_id"] = record["record_key"]
        record["source_key"] = record["record_key"]
        record["source_name"] = record["station_name"]
        record["source_file"] = meta.get("source_file") if isinstance(meta, dict) else ""
        record["source_sheet"] = meta.get("sheet_name", 0) if isinstance(meta, dict) else 0
        record["source_row"] = int(idx) + 2
        record["data_date"] = clean_text(record.get("data_date") or meta.get("data_date") if isinstance(meta, dict) else record.get("data_date"))

        record = enrich_prediction_location(record, station_index)
        records.append(record)

    return records

def get_prediction_files(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_flood_prediction_files(context=context)


def get_flood_prediction_files(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    files = [
        {
            "file": str(path),
            "file_name": path.name,
            "data_date": get_prediction_file_date(path),
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            "modified_time": path.stat().st_mtime,
            "exists": path.exists(),
        }
        for path in list_prediction_files()
    ]

    return {
        "files": files,
        "records": files,
        "total": len(files),
        "data_dir": str(getattr(config, "PREDICTION_DATA_DIR", getattr(config, "FLOOD_PREDICTION_DIR", ""))),
        "file_pattern": getattr(config, "PREDICTION_FILE_PATTERN", "predict_YYYY_MM_DD.xlsx"),
        "file_glob": getattr(config, "PREDICTION_FILE_GLOB", "predict_*.xlsx"),
    }


def get_flood_prediction_contract(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "data_dir": str(getattr(config, "PREDICTION_DATA_DIR", getattr(config, "FLOOD_PREDICTION_DIR", ""))),
        "file_pattern": getattr(config, "PREDICTION_FILE_PATTERN", "predict_YYYY_MM_DD.xlsx"),
        "file_glob": getattr(config, "PREDICTION_FILE_GLOB", "predict_*.xlsx"),
        "file_example": getattr(config, "PREDICTION_FILE_EXAMPLE", "predict_2026_06_16.xlsx"),
        "required_columns": getattr(config, "PREDICTION_REQUIRED_COLUMNS", []),
        "supported_columns": getattr(config, "PREDICTION_SUPPORTED_COLUMNS", []),
        "numeric_columns": getattr(config, "PREDICTION_NUMERIC_COLUMNS", []),
        "date_columns": getattr(config, "PREDICTION_DATE_COLUMNS", []),
        "record_key_contract": "prediction|station|base_date|target_date|forecast_horizon_day",
        "map_location_policy": "Prediction rows do not use latitude/longitude from prediction file. Map layer enriches location only from waterlevel_station_master and rainfall_station_master. If station location is missing, frontend should focus province boundary using province_model/province_name_th.",
        "location_master_sources": getattr(
            config,
            "PREDICTION_LOCATION_MASTER_SOURCES",
            [
                "waterlevel_station_master",
                "rainfall_station_master",
            ],
        ),
        "location_debug_fields": [
            "map_ready",
            "has_location",
            "matched_source",
            "matched_station_id",
            "matched_station_code",
            "matched_station_name",
            "location_match_key",
            "location_match_candidates",
            "location_match_status",
            "location_match_reason",
            "focus_level",
            "focus_fallback",
            "focus_fallback_reason",
        ],
    }


def build_flood_prediction_latest(
    data_date: Optional[Any] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    cache_key = CACHE_KEYS["flood_prediction_latest"]

    def builder() -> Dict[str, Any]:
        df, meta = read_prediction_dataframe(data_date=data_date, force_refresh=force_refresh)
        records = normalize_prediction_records(df, meta=meta, force_refresh=force_refresh)

        return {
            "records": records,
            "total": len(records),
            "meta": meta,
            "source_path": meta.get("source_file"),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=cache_key,
        builder=builder,
        ttl_seconds=get_flood_ttl(),
        force_refresh=force_refresh,
        source="flood_spatial_service.build_flood_prediction_latest",
    )

    return {**cache_result["data"], "cache_used": cache_result["cache_used"]}


def get_latest_flood_predictions(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    filters = ctx.get("filters", {}) if isinstance(ctx.get("filters"), dict) else {}
    data_date = filters.get("data_date") or ctx.get("data_date")

    data = build_flood_prediction_latest(
        data_date=data_date,
        force_refresh=ctx.get("force_refresh", False),
    )

    records = data.get("records", [])
    result = filter_records_api(records, ctx, PREDICTION_SEARCHABLE_FIELDS, target="flood_prediction")
    result["source_path"] = data.get("source_path")
    result["prediction_meta"] = data.get("meta", {})

    return result


def get_flood_prediction_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    latest = get_latest_flood_predictions(ctx)
    records = latest.get("records", [])

    risk_counts = Counter(record.get("risk_level", "Unknown") for record in records)
    province_counts = Counter(record.get("province", "Unknown") for record in records)
    map_ready_count = sum(1 for record in records if to_bool(record.get("map_ready"), default=False))
    fallback_count = sum(1 for record in records if record.get("focus_level") == "province_boundary")

    return {
        "summary": {
            "total": len(records),
            "risk_counts": dict(risk_counts),
            "province_counts": dict(province_counts),
            "map_ready_count": map_ready_count,
            "map_ready_rate": round((map_ready_count / len(records)) * 100, 4) if records else 0,
            "province_fallback_count": fallback_count,
            "province_fallback_rate": round((fallback_count / len(records)) * 100, 4) if records else 0,
        },
        "risk_counts": dict(risk_counts),
        "province_counts": dict(province_counts),
        "total": len(records),
        "source_path": latest.get("source_path"),
        "prediction_meta": latest.get("prediction_meta", {}),
    }


def prediction_record_to_map_feature(record: Dict[str, Any]) -> Dict[str, Any]:
    properties = {
        "feature_id": record.get("record_key"),
        "feature_type": "prediction",
        "source_type": "prediction",
        "source_id": record.get("record_key"),
        "source_name": record.get("station_name"),
        "record_key": record.get("record_key"),
        "station_id": record.get("station_id"),
        "station_code": record.get("station_code"),
        "station_name": record.get("station_name"),
        "province": record.get("province"),
        "province_model": record.get("province_model"),
        "risk_level": record.get("risk_level"),
        "risk_score": record.get("risk_score"),
        "risk_color": record.get("risk_color"),
        "marker_color": record.get("risk_color"),
        "marker_size": 10 + max(0, to_number(record.get("risk_score"), 0) or 0) * 3,
        "map_ready": record.get("map_ready"),
        "has_location": record.get("has_location"),
        "focus_level": record.get("focus_level"),
        "focus_fallback": record.get("focus_fallback"),
        "focus_fallback_reason": record.get("focus_fallback_reason"),
        "matched_source": record.get("matched_source"),
        "matched_station_id": record.get("matched_station_id"),
        "matched_station_code": record.get("matched_station_code"),
        "matched_station_name": record.get("matched_station_name"),
        "base_date": record.get("base_date"),
        "target_date": record.get("target_date"),
        "forecast_horizon_day": record.get("forecast_horizon_day"),
    }

    if to_bool(record.get("map_ready"), default=False):
        feature = make_point_feature(
            lon=record.get("lon") or record.get("longitude"),
            lat=record.get("lat") or record.get("latitude"),
            properties=properties,
        )

        if feature:
            return feature

    return {
        "type": "Feature",
        "geometry": None,
        "properties": to_jsonable(properties),
    }


def get_flood_prediction_map(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    latest = get_latest_flood_predictions(ctx)
    records = latest.get("records", [])

    features = [
        prediction_record_to_map_feature(record)
        for record in records
    ]

    fallback_focus = [
        {
            "record_key": record.get("record_key"),
            "province": record.get("province"),
            "focus_level": record.get("focus_level"),
            "focus_fallback": record.get("focus_fallback"),
            "focus_fallback_reason": record.get("focus_fallback_reason"),
        }
        for record in records
        if not to_bool(record.get("map_ready"), default=False) and record.get("focus_fallback")
    ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "fallback_focus": fallback_focus,
        "total": len(records),
        "feature_count": len(features),
        "map_ready_count": sum(1 for record in records if to_bool(record.get("map_ready"), default=False)),
        "source_path": latest.get("source_path"),
        "prediction_meta": latest.get("prediction_meta", {}),
    }


def get_flood_prediction_location_debug(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    latest = get_latest_flood_predictions(ctx)
    records = latest.get("records", [])

    debug_records = [
        {
            "record_key": record.get("record_key"),
            "station_id": record.get("station_id"),
            "station_code": record.get("station_code"),
            "station_name": record.get("station_name"),
            "province": record.get("province"),
            "map_ready": record.get("map_ready"),
            "has_location": record.get("has_location"),
            "lat": record.get("lat"),
            "lon": record.get("lon"),
            "matched_source": record.get("matched_source"),
            "matched_station_id": record.get("matched_station_id"),
            "matched_station_code": record.get("matched_station_code"),
            "matched_station_name": record.get("matched_station_name"),
            "location_match_status": record.get("location_match_status"),
            "location_match_key": record.get("location_match_key"),
            "location_match_candidates": record.get("location_match_candidates"),
            "location_match_reason": record.get("location_match_reason"),
            "focus_level": record.get("focus_level"),
            "focus_fallback": record.get("focus_fallback"),
            "focus_fallback_reason": record.get("focus_fallback_reason"),
        }
        for record in records
    ]

    return {
        "records": debug_records,
        "total": len(debug_records),
        "summary": get_flood_prediction_summary(ctx).get("summary", {}),
        "source_path": latest.get("source_path"),
    }


def get_flood_prediction_station_detail(
    station_id_or_name: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)
    query = clean_text_lower(station_id_or_name)
    latest = get_latest_flood_predictions(ctx)
    records = latest.get("records", [])

    matched = [
        record
        for record in records
        if query
        and query in " ".join(
            [
                clean_text(record.get("record_key")),
                clean_text(record.get("station_id")),
                clean_text(record.get("station_code")),
                clean_text(record.get("station_name")),
                clean_text(record.get("station_name_th")),
                clean_text(record.get("matched_station_id")),
                clean_text(record.get("matched_station_code")),
                clean_text(record.get("matched_station_name")),
            ]
        ).lower()
    ]

    return {
        "station": station_id_or_name,
        "found": len(matched) > 0,
        "records": matched,
        "summary": {
            "total": len(matched),
            "risk_counts": dict(Counter(record.get("risk_level", "Unknown") for record in matched)),
        },
    }


def get_flood_prediction_risk_distribution(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    latest = get_latest_flood_predictions(ctx)
    records = latest.get("records", [])

    risk_counts = Counter(record.get("risk_level", "Unknown") for record in records)

    return {
        "records": [
            {
                "risk_level": risk_level,
                "count": count,
                "risk_score": RISK_SCORE.get(risk_level, -1),
                "risk_color": RISK_COLORS.get(risk_level, RISK_COLORS.get("Unknown", "#64748b")),
            }
            for risk_level, count in risk_counts.items()
        ],
        "risk_counts": dict(risk_counts),
        "total": len(records),
    }


def get_flood_prediction_search_results(
    query: str,
    search_type: str = "prediction",
    limit: int = 50,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)
    ctx["search"] = clean_text(query)
    ctx["page"] = 1
    ctx["page_size"] = int(limit or 50)

    return get_latest_flood_predictions(ctx)

def get_station_detail(
    station_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)
    query = clean_text_lower(station_id)

    candidates: List[Dict[str, Any]] = []
    candidates.extend(build_rainfall_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))
    candidates.extend(build_waterlevel_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))
    candidates.extend(get_rainfall_station_master({"page_size": 100000}).get("records", []))
    candidates.extend(get_waterlevel_station_master({"page_size": 100000}).get("records", []))

    matched = [
        record
        for record in candidates
        if query
        and query in " ".join(
            [
                clean_text(record.get("source_key")),
                clean_text(record.get("source_id")),
                clean_text(record.get("station_id")),
                clean_text(record.get("station_code")),
                clean_text(record.get("station_name")),
                clean_text(record.get("source_name")),
            ]
        ).lower()
    ]

    return {
        "station_id": station_id,
        "found": len(matched) > 0,
        "record": matched[0] if matched else None,
        "records": matched,
        "total": len(matched),
    }


def get_dam_detail(
    dam_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)
    query = clean_text_lower(dam_id)

    candidates: List[Dict[str, Any]] = []
    candidates.extend(build_large_dam_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))
    candidates.extend(build_medium_dam_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))
    candidates.extend(get_dam_reservoir_master({"page_size": 100000}).get("records", []))

    matched = [
        record
        for record in candidates
        if query
        and query in " ".join(
            [
                clean_text(record.get("source_key")),
                clean_text(record.get("source_id")),
                clean_text(record.get("dam_id")),
                clean_text(record.get("dam_name")),
                clean_text(record.get("source_name")),
            ]
        ).lower()
    ]

    return {
        "dam_id": dam_id,
        "found": len(matched) > 0,
        "record": matched[0] if matched else None,
        "records": matched,
        "total": len(matched),
    }


def get_detail_object(
    object_type: str,
    object_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    type_key = clean_text_lower(object_type).replace("-", "_")

    if type_key in {"station", "rainfall", "waterlevel"}:
        return get_station_detail(object_id, context=context)

    if type_key in {"dam", "large_dam", "medium_dam", "reservoir"}:
        return get_dam_detail(object_id, context=context)

    if type_key in {"prediction", "forecast", "flood_prediction", "waterlevel_prediction"}:
        return get_flood_prediction_station_detail(object_id, context=context)

    if type_key in {"entity", "uploaded_entity"}:
        try:
            import entity_upload_service
            return entity_upload_service.get_entity_detail(object_id)
        except Exception as exc:
            return {
                "found": False,
                "record": None,
                "errors": [
                    {
                        "code": "entity_detail_proxy_failed",
                        "message": str(exc),
                    }
                ],
            }

    return {
        "found": False,
        "record": None,
        "object_type": object_type,
        "object_id": object_id,
        "errors": [
            {
                "code": "unsupported_object_type",
                "message": f"Unsupported object type: {object_type}",
            }
        ],
    }


def get_search_results(
    query: str,
    search_type: str = "all",
    limit: int = 50,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)
    ctx["search"] = clean_text(query)
    ctx["page"] = 1
    ctx["page_size"] = int(limit or ctx.get("page_size", 50) or 50)

    type_key = clean_text_lower(search_type).replace("-", "_")

    records: List[Dict[str, Any]] = []

    if type_key in {"all", "rainfall"}:
        records.extend(build_rainfall_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))

    if type_key in {"all", "waterlevel"}:
        records.extend(build_waterlevel_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))

    if type_key in {"all", "dam", "large_dam"}:
        records.extend(build_large_dam_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))

    if type_key in {"all", "dam", "medium_dam"}:
        records.extend(build_medium_dam_latest(force_refresh=ctx.get("force_refresh", False)).get("records", []))

    if type_key in {"all", "prediction", "forecast", "flood_prediction"}:
        records.extend(get_latest_flood_predictions(ctx).get("records", []))

    if type_key in {"all", "entity", "uploaded_entity"}:
        try:
            import entity_upload_service
            entity_result = entity_upload_service.get_latest_entity_records(
                query=query,
                limit=limit,
                offset=0,
            )
            records.extend(entity_result.get("records", []))
        except Exception:
            pass

    return filter_records_api(
        records,
        ctx,
        FLOOD_SEARCHABLE_FIELDS + PREDICTION_SEARCHABLE_FIELDS,
        target="flood",
    )

def rebuild_flood_spatial_cache(force_refresh: bool = True) -> Dict[str, Any]:
    """
    rebuild cache ทั้งหมดของ flood_spatial_service.py
    """

    results = {
        "rainfall_latest": build_rainfall_latest(force_refresh=force_refresh),
        "waterlevel_latest": build_waterlevel_latest(force_refresh=force_refresh),
        "large_dam_latest": build_large_dam_latest(force_refresh=force_refresh),
        "medium_dam_latest": build_medium_dam_latest(force_refresh=force_refresh),
        "all_long_latest": build_all_long_latest(force_refresh=force_refresh),
        "flood_station_master": build_flood_station_master(force_refresh=force_refresh),
        "province_boundaries": build_province_boundaries(force_refresh=force_refresh),
        "basin_boundaries": build_basin_boundaries(force_refresh=force_refresh),
        "flood_prediction_files": get_flood_prediction_files(),
        "flood_prediction_latest": build_flood_prediction_latest(force_refresh=force_refresh),
        "flood_prediction_summary": get_flood_prediction_summary({"force_refresh": force_refresh}),
        "flood_prediction_map": get_flood_prediction_map({"force_refresh": force_refresh}),
        "flood_prediction_location_debug": get_flood_prediction_location_debug({"force_refresh": force_refresh}),
        "flood_computed_risk": build_flood_computed_risk(force_refresh=force_refresh),
        "province_risk_summary": build_province_risk_summary(force_refresh=force_refresh),
        "spatial_join_result": build_spatial_join_result(force_refresh=force_refresh),
        "company_flood_context": build_company_flood_context(force_refresh=force_refresh),
        "policy_flood_exposure": build_policy_flood_exposure(force_refresh=force_refresh),
        "province_risk_exposure": build_province_risk_exposure(force_refresh=force_refresh),
    }

    return {
        "rebuilt": True,
        "results": {
            key: {
                "total": value.get("total") if isinstance(value, dict) else None,
                "cache_used": value.get("cache_used") if isinstance(value, dict) else None,
                "created_at": value.get("created_at") if isinstance(value, dict) else None,
            }
            for key, value in results.items()
        },
        "generated_at": now_iso(),
    }
def get_flood_dashboard_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง payload สำหรับ dashboard_package_service.py
    """

    ctx = normalize_context(context)

    summary = get_flood_summary(ctx)

    computed = get_flood_computed_risk(
        {
            **ctx,
            "page": 1,
            "page_size": 20,
            "sort_by": "risk_score",
            "sort_dir": "desc",
        }
    )

    province_exposure = get_province_risk_exposure(
        {
            **ctx,
            "page": 1,
            "page_size": 20,
            "sort_by": "risk_score",
            "sort_dir": "desc",
        }
    )

    policy_exposure = get_policy_flood_exposure(ctx)
    prediction_summary = get_flood_prediction_summary(ctx)
    prediction_latest = get_latest_flood_predictions(
        {
            **ctx,
            "page": 1,
            "page_size": 20,
            "sort_by": "risk_score",
            "sort_dir": "desc",
        }
    )

    return {
        "summary": summary,
        "top_risk_sources": computed.get("records", []),
        "province_risk_exposure": province_exposure.get("records", []),
        "policy_flood_exposure": policy_exposure.get("summary", {}),
        "prediction_summary": prediction_summary.get("summary", {}),
        "prediction_top_risk": prediction_latest.get("records", []),
        "risk_counts": summary.get("risk_counts", {}),
        "source_counts": summary.get("source_counts", {}),
        "generated_at": now_iso(),
    }

# ============================================================
# 15) MODULE STATUS / SELF TEST
# ============================================================

def get_flood_spatial_module_status() -> Dict[str, Any]:
    """
    คืนสถานะ module flood_spatial_service.py
    """

    latest_prediction_file = find_prediction_file()

    return {
        "module": "flood_spatial_service",
        "ready": True,
        "flood_output_dir": str(FLOOD_OUTPUT_DIR),
        "flood_output_exists": FLOOD_OUTPUT_DIR.exists(),
        "latest_database_path": str(FLOOD_LATEST_DATABASE_PATH),
        "latest_database_exists": FLOOD_LATEST_DATABASE_PATH.exists(),
        "master_database_path": str(FLOOD_MASTER_DATABASE_PATH),
        "master_database_exists": FLOOD_MASTER_DATABASE_PATH.exists(),
        "history_dir": str(FLOOD_HISTORY_DIR),
        "history_exists": FLOOD_HISTORY_DIR.exists(),
        "prediction_dir": str(getattr(config, "PREDICTION_DATA_DIR", getattr(config, "FLOOD_PREDICTION_DIR", ""))),
        "latest_prediction_file": str(latest_prediction_file) if latest_prediction_file else None,
        "latest_prediction_file_exists": latest_prediction_file.exists() if latest_prediction_file else False,
        "cache_keys": CACHE_KEYS,
        "supported_outputs": [
            "rainfall_latest",
            "waterlevel_latest",
            "large_dam_latest",
            "medium_dam_latest",
            "all_long_latest",
            "flood_station_master",
            "province_boundaries",
            "basin_boundaries",
            "flood_prediction_files",
            "flood_prediction_latest",
            "flood_prediction_summary",
            "flood_prediction_map",
            "flood_prediction_location_debug",
            "flood_prediction_risk_distribution",
            "flood_computed_risk",
            "province_risk_summary",
            "spatial_join_result",
            "company_flood_context",
            "policy_flood_exposure",
            "province_risk_exposure",
            "history",
            "detail",
            "search",
        ],
        "risk_levels": RISK_LEVELS,
        "checked_at": now_iso(),
    }


def run_flood_spatial_self_test() -> Dict[str, Any]:
    """
    self test เบื้องต้น
    """

    summary = get_flood_summary({"force_refresh": False})
    computed = build_flood_computed_risk(force_refresh=False)
    spatial = build_spatial_join_result(force_refresh=False)

    return {
        "module": "flood_spatial_service",
        "self_test": True,
        "status": get_flood_spatial_module_status(),
        "summary": summary,
        "computed_risk_total": computed.get("total", 0),
        "spatial_join_total": spatial.get("total", 0),
        "checked_at": now_iso(),
    }