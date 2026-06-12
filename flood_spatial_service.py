# ============================================================
# FILE: backend/flood_spatial_service.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 11 / 20
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
try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

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
    """

    ctx = normalize_context(context)

    if filter_records_for_service is not None:
        try:
            return filter_records_for_service(
                records=records,
                context=ctx,
                target=target,
                paginate=True,
            )
        except Exception:
            pass

    return apply_search_sort_pagination(
        records=records,
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
# 15) MODULE STATUS / SELF TEST
# ============================================================

def get_flood_spatial_module_status() -> Dict[str, Any]:
    """
    คืนสถานะ module flood_spatial_service.py
    """

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
            "flood_computed_risk",
            "province_risk_summary",
            "spatial_join_result",
            "company_flood_context",
            "policy_flood_exposure",
            "province_risk_exposure",
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