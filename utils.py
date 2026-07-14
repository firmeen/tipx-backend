# ============================================================
# FILE: backend/utils.py
# TIPX Enterprise Intelligence Dashboard
# ============================================================

"""
backend/utils.py

ไฟล์นี้เป็นศูนย์กลาง Utility Functions ทั้งหมดของระบบ TIPX

หน้าที่หลัก:
1. อ่าน / เขียน Excel, CSV, JSON, Text
2. จัดการ path และ folder
3. ทำความสะอาดข้อมูล string / numeric / date
4. normalize column name
5. normalize Tax ID
6. validate Tax ID
7. validate coordinate
8. คำนวณระยะทาง Haversine
9. สร้าง GeoJSON Feature / FeatureCollection
10. คำนวณ Loss Ratio
11. คำนวณ Loss Ratio Band
12. normalize policy status
13. parse boardlist
14. normalize director name
15. สร้าง deterministic id
16. paginate / sort / search records
17. cache helper
18. response helper
19. export helper
20. data serialization helper

โครงสร้างเดิมที่รวมมาในไฟล์นี้:
- utils/response_utils.py
- utils/file_utils.py
- utils/data_utils.py
- utils/tax_id_utils.py
- utils/policy_utils.py
- utils/linkage_utils.py
- utils/geo_utils.py
- utils/flood_risk_utils.py
- utils/export_utils.py
- utils/cache_utils.py
- utils/validation_utils.py

ไฟล์นี้ถูกใช้โดย:
- company_policy_service.py
- linkage_service.py
- flood_spatial_service.py
- map_graph_service.py
- dashboard_package_service.py
- data_quality.py
- filter_engine.py
- security.py
- api_routes.py
"""

from __future__ import annotations
import csv
import hashlib
import json
import math
import os
import re
import shutil
import unicodedata
import zipfile
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import pandas as pd
import config
"""


"""
from config import (
    APP_SHORT_NAME,
    APP_VERSION,
    DEFAULT_ENCODING,
    CACHE_DIR,
    CACHE_ENABLED,
    CACHE_TTL_SECONDS,
    CACHE_METADATA_FILENAME,
    THAILAND_LAT_RANGE,
    THAILAND_LON_RANGE,
    RISK_LEVELS,
    RISK_SCORE,
    RISK_COLORS,
    LOSS_RATIO_BANDS,
    ACTIVE_POLICY_VALUES,
    EXPIRED_POLICY_VALUES,
    POLICY_ACTIVE_RULE,
    BOARDLIST_SPLIT_PATTERN,
    DIRECTOR_ID_PREFIX,
    COMPANY_NODE_PREFIX,
    DIRECTOR_NODE_PREFIX,
    EDGE_TYPE_DIRECTOR_OF,
    EDGE_TYPE_SHARED_DIRECTOR,
    FLOOD_RAINFALL_THRESHOLDS_MM,
    FLOOD_WATERLEVEL_THRESHOLDS,
    FLOOD_DAM_STORAGE_THRESHOLDS_PERCENT,
)


# ============================================================
# 1) BASIC CONSTANTS
# ============================================================

NA_VALUES = {
    "",
    "-",
    "--",
    "---",
    "n/a",
    "na",
    "nan",
    "none",
    "null",
    "nil",
    "#n/a",
    "#na",
    "ไม่ระบุ",
    "ไม่มี",
    "ไม่พบข้อมูล",
}

TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "y",
    "t",
    "on",
    "ใช่",
    "จริง",
}

FALSE_VALUES = {
    "0",
    "false",
    "no",
    "n",
    "f",
    "off",
    "ไม่",
    "เท็จ",
}


# ============================================================
# 2) RESPONSE HELPERS
# ============================================================

def now_iso() -> str:
    """
    คืนเวลาปัจจุบันแบบ ISO string
    """

    return datetime.now().isoformat(timespec="seconds")


def build_response_payload(
    success: bool,
    message: str,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    สร้าง payload มาตรฐานของ TIPX API

    ใช้ใน service ที่ต้องส่งข้อมูลกลับให้ api_routes.py
    """

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


def ok_payload(
    data: Optional[Any] = None,
    message: str = "OK",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง success payload
    """

    return build_response_payload(
        success=True,
        message=message,
        data=data,
        meta=meta,
        errors=[],
    )


def error_payload(
    message: str = "ERROR",
    errors: Optional[Any] = None,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง error payload
    """

    return build_response_payload(
        success=False,
        message=message,
        data=data,
        meta=meta,
        errors=errors or [],
    )


# ============================================================
# 3) PATH / FILE HELPERS
# ============================================================

def ensure_dir(path: Union[str, Path]) -> Path:
    """
    สร้าง folder ถ้ายังไม่มี และคืน Path
    """

    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_parent_dir(path: Union[str, Path]) -> Path:
    """
    สร้าง parent folder ของไฟล์
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def path_exists(path: Union[str, Path]) -> bool:
    """
    ตรวจ path exists
    """

    return Path(path).exists()


def file_exists(path: Union[str, Path]) -> bool:
    """
    ตรวจไฟล์ exists
    """

    return Path(path).exists() and Path(path).is_file()


def folder_exists(path: Union[str, Path]) -> bool:
    """
    ตรวจ folder exists
    """

    return Path(path).exists() and Path(path).is_dir()


def safe_filename(value: Any, default: str = "file") -> str:
    """
    แปลงข้อความเป็นชื่อไฟล์ที่ปลอดภัย
    """

    text = clean_text(value)

    if not text:
        text = default

    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("._ ")

    return text or default


def list_files(
    folder: Union[str, Path],
    pattern: str = "*",
    recursive: bool = False,
) -> List[Path]:
    """
    list file ใน folder
    """

    base = Path(folder)

    if not base.exists():
        return []

    if recursive:
        return sorted([p for p in base.rglob(pattern) if p.is_file()])

    return sorted([p for p in base.glob(pattern) if p.is_file()])


def file_info(path: Union[str, Path]) -> Dict[str, Any]:
    """
    คืนข้อมูลพื้นฐานของไฟล์
    """

    p = Path(path)

    if not p.exists():
        return {
            "path": str(p),
            "exists": False,
        }

    stat = p.stat()

    return {
        "path": str(p),
        "exists": True,
        "is_file": p.is_file(),
        "is_dir": p.is_dir(),
        "name": p.name,
        "suffix": p.suffix,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
    }


def copy_file(src: Union[str, Path], dst: Union[str, Path], overwrite: bool = True) -> Path:
    """
    copy file
    """

    src_path = Path(src)
    dst_path = ensure_parent_dir(dst)

    if dst_path.exists() and not overwrite:
        raise FileExistsError(f"Destination already exists: {dst_path}")

    shutil.copy2(src_path, dst_path)
    return dst_path


def remove_file(path: Union[str, Path], missing_ok: bool = True) -> bool:
    """
    ลบไฟล์
    """

    target = Path(path)

    if not target.exists():
        if missing_ok:
            return False
        raise FileNotFoundError(str(target))

    if target.is_file():
        target.unlink()
        return True

    return False


# ============================================================
# 4) JSON / TEXT / CSV / EXCEL HELPERS
# ============================================================

def to_jsonable(value: Any) -> Any:
    """
    แปลง object ให้เป็น JSON serializable

    รองรับ:
    - pandas NaN / NaT
    - datetime / date
    - Decimal
    - Path
    - set / tuple
    - DataFrame / Series
    """

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]

    if isinstance(value, pd.DataFrame):
        return dataframe_to_records(value)

    if isinstance(value, pd.Series):
        return to_jsonable(value.to_dict())

    try:
        import numpy as np

        if isinstance(value, np.integer):
            return int(value)

        if isinstance(value, np.floating):
            return float(value)

        if isinstance(value, np.ndarray):
            return value.tolist()

        if isinstance(value, np.bool_):
            return bool(value)
    except Exception:
        pass

    return value


def read_text(path: Union[str, Path], encoding: str = DEFAULT_ENCODING) -> str:
    """
    อ่าน text file
    """

    return Path(path).read_text(encoding=encoding)


def write_text(path: Union[str, Path], content: str, encoding: str = DEFAULT_ENCODING) -> Path:
    """
    เขียน text file
    """

    target = ensure_parent_dir(path)
    target.write_text(content, encoding=encoding)
    return target


def read_json(path: Union[str, Path], default: Optional[Any] = None, encoding: str = DEFAULT_ENCODING) -> Any:
    """
    อ่าน JSON file
    """

    p = Path(path)

    if not p.exists():
        return deepcopy(default)

    try:
        with p.open("r", encoding=encoding) as f:
            return json.load(f)
    except Exception:
        return deepcopy(default)


def write_json(
    path: Union[str, Path],
    data: Any,
    encoding: str = DEFAULT_ENCODING,
    indent: int = 2,
) -> Path:
    """
    เขียน JSON file
    """

    target = ensure_parent_dir(path)

    with target.open("w", encoding=encoding) as f:
        json.dump(
            to_jsonable(data),
            f,
            ensure_ascii=False,
            indent=indent,
        )

    return target


def append_jsonl(path: Union[str, Path], record: Dict[str, Any], encoding: str = DEFAULT_ENCODING) -> Path:
    """
    append JSON Lines
    """

    target = ensure_parent_dir(path)

    with target.open("a", encoding=encoding) as f:
        f.write(json.dumps(to_jsonable(record), ensure_ascii=False) + "\n")

    return target


def read_csv(path: Union[str, Path], **kwargs: Any) -> pd.DataFrame:
    """
    อ่าน CSV เป็น DataFrame
    """

    p = Path(path)

    if not p.exists():
        return pd.DataFrame()

    default_kwargs = {
        "encoding": kwargs.pop("encoding", DEFAULT_ENCODING),
    }

    default_kwargs.update(kwargs)

    try:
        return pd.read_csv(p, **default_kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(p, encoding="utf-8-sig", **kwargs)
    except Exception:
        try:
            return pd.read_csv(p, encoding="cp874", **kwargs)
        except Exception:
            return pd.DataFrame()


def write_csv(path: Union[str, Path], df: pd.DataFrame, encoding: str = "utf-8-sig", index: bool = False) -> Path:
    """
    เขียน DataFrame เป็น CSV
    """

    target = ensure_parent_dir(path)
    df.to_csv(target, encoding=encoding, index=index)
    return target

def read_excel_sheet(
    path: Union[str, Path],
    sheet_name: Union[str, int, None] = 0,
    dtype: Optional[Any] = None,
    use_cache: bool = False,
    return_meta: bool = False,
) -> Union[pd.DataFrame, Dict[str, Any]]:
    """
    อ่าน Excel sheet แบบปลอดภัย

    Default behavior เดิม:
    - คืน DataFrame
    - ถ้าอ่านไม่ได้คืน DataFrame ว่าง

    Source behavior ใหม่:
    - use_cache=True ใช้ file modified time เป็น cache key
    - return_meta=True คืน dict พร้อม df/meta/errors
    """

    p = Path(path)

    source_meta: Dict[str, Any] = {
        "source": "excel",
        "source_file": str(p),
        "sheet_name": sheet_name,
        "file_exists": p.exists(),
        "file_modified_at": None,
        "file_modified_time": None,
        "cache_used": False,
        "record_count": 0,
    }

    if p.exists():
        try:
            stat = p.stat()
            source_meta["file_modified_time"] = stat.st_mtime
            source_meta["file_modified_at"] = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        except Exception:
            pass

    if not p.exists():
        empty_df = pd.DataFrame()

        if return_meta:
            return {
                "df": empty_df,
                "meta": source_meta,
                "errors": [
                    {
                        "code": "excel_file_not_found",
                        "message": f"ไม่พบไฟล์ Excel: {p}",
                        "path": str(p),
                    }
                ],
            }

        return empty_df

    cache_key = make_excel_cache_key(p, sheet_name=sheet_name, file_modified_time=source_meta.get("file_modified_time"))

    if use_cache and is_cache_valid(cache_key):
        cached_payload = read_cache(cache_key, default={})

        if isinstance(cached_payload, dict) and isinstance(cached_payload.get("records"), list):
            cached_df = pd.DataFrame(cached_payload.get("records", []))
            source_meta.update(cached_payload.get("meta", {}))
            source_meta["cache_used"] = True
            source_meta["record_count"] = len(cached_df)

            if return_meta:
                return {
                    "df": cached_df,
                    "meta": source_meta,
                    "errors": [],
                }

            return cached_df

    try:
        df = pd.read_excel(p, sheet_name=sheet_name, dtype=dtype)
        df = clean_dataframe_common(df)
        source_meta["record_count"] = len(df)

        if use_cache:
            write_cache(
                cache_key,
                {
                    "records": dataframe_to_records(df),
                    "meta": source_meta,
                },
                ttl_seconds=int(CACHE_TTL_SECONDS.get("flood", 3600) if isinstance(CACHE_TTL_SECONDS, dict) else 3600),
                source="excel_source",
            )

        if return_meta:
            return {
                "df": df,
                "meta": source_meta,
                "errors": [],
            }

        return df

    except Exception as exc:
        empty_df = pd.DataFrame()

        if return_meta:
            return {
                "df": empty_df,
                "meta": source_meta,
                "errors": [
                    {
                        "code": "excel_read_failed",
                        "message": str(exc),
                        "type": exc.__class__.__name__,
                        "path": str(p),
                        "sheet_name": sheet_name,
                    }
                ],
            }

        return empty_df


def read_excel_sheets(
    path: Union[str, Path],
    sheet_names: Optional[Union[List[str], Dict[str, str]]] = None,
    dtype: Optional[Any] = None,
) -> Dict[str, pd.DataFrame]:
    """
    อ่าน Excel หลาย sheet

    Args:
        path:
            path ไฟล์ Excel

        sheet_names:
            - None = อ่านทุก sheet
            - list[str] = อ่านตามชื่อ sheet
            - dict[key, sheet_name] = คืนตาม key
    """

    p = Path(path)

    if not p.exists():
        return {}

    result: Dict[str, pd.DataFrame] = {}

    try:
        if sheet_names is None:
            sheets = pd.read_excel(p, sheet_name=None, dtype=dtype)
            return {str(k): v for k, v in sheets.items()}

        if isinstance(sheet_names, dict):
            for key, sheet in sheet_names.items():
                result[str(key)] = read_excel_sheet(p, sheet_name=sheet, dtype=dtype)
            return result

        for sheet in sheet_names:
            result[str(sheet)] = read_excel_sheet(p, sheet_name=sheet, dtype=dtype)

        return result

    except Exception:
        return result


def get_excel_sheet_names(path: Union[str, Path]) -> List[str]:
    """
    คืนรายชื่อ sheet ใน Excel
    """

    p = Path(path)

    if not p.exists():
        return []

    try:
        excel_file = pd.ExcelFile(p)
        return list(excel_file.sheet_names)
    except Exception:
        return []


def read_excel_by_logical_sheet(
    path: Union[str, Path],
    expected_sheet_name: Optional[str],
    fallback_index: int = 0,
    dtype: Optional[Any] = None,
) -> pd.DataFrame:
    """
    อ่าน Excel โดยพยายามอ่านจากชื่อ sheet ก่อน
    ถ้าไม่เจอใช้ fallback index

    ใช้กับ Policy Input ที่ชื่อ sheet อาจไม่แน่นอน
    """

    p = Path(path)

    if not p.exists():
        return pd.DataFrame()

    sheet_names = get_excel_sheet_names(p)

    if expected_sheet_name and expected_sheet_name in sheet_names:
        return read_excel_sheet(p, sheet_name=expected_sheet_name, dtype=dtype)

    if 0 <= fallback_index < len(sheet_names):
        return read_excel_sheet(p, sheet_name=fallback_index, dtype=dtype)

    return pd.DataFrame()

def file_modified_time(path: Union[str, Path]) -> Optional[float]:
    """
    คืนค่า modified time ของไฟล์
    """

    p = Path(path)

    if not p.exists() or not p.is_file():
        return None

    try:
        return p.stat().st_mtime
    except Exception:
        return None


def file_modified_at(path: Union[str, Path]) -> Optional[str]:
    """
    คืนค่า modified time ของไฟล์แบบ ISO string
    """

    mtime = file_modified_time(path)

    if mtime is None:
        return None

    try:
        return datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
    except Exception:
        return None


def make_excel_cache_key(
    path: Union[str, Path],
    sheet_name: Union[str, int, None] = 0,
    file_modified_time: Optional[float] = None,
) -> str:
    """
    สร้าง cache key สำหรับ Excel sheet โดยผูกกับ file modified time
    """

    p = Path(path)
    mtime = file_modified_time

    if mtime is None:
        mtime = globals()["file_modified_time"](p)

    raw_key = f"excel|{p.resolve() if p.exists() else p}|{sheet_name}|{mtime}"
    return make_hash_id(raw_key, prefix="excel_cache", length=24)


def normalize_column_name(value: Any) -> str:
    """
    alias สำหรับ clean_column_name เพื่อรองรับ excel_service contract
    """

    return clean_column_name(value)


def normalize_text(value: Any, default: str = "") -> str:
    """
    alias สำหรับ clean_text เพื่อรองรับ excel_service contract
    """

    return clean_text(value, default=default)


def safe_str(value: Any, default: str = "") -> str:
    """
    แปลงค่าเป็น string แบบปลอดภัย
    """

    return clean_text(value, default=default)


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """
    แปลงค่าเป็น float แบบปลอดภัย
    """

    return to_number(value, default=default)


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """
    แปลงค่าเป็น int แบบปลอดภัย
    """

    return to_int(value, default=default)


def clean_value(value: Any) -> Any:
    """
    clean ค่าเดี่ยวสำหรับ serialize records จาก Excel
    """

    return to_jsonable(value)


def clean_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    clean record 1 แถว
    """

    return {
        clean_column_name(key): clean_value(value)
        for key, value in dict(record or {}).items()
    }


def clean_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    clean records หลายแถว
    """

    return [
        clean_record(record)
        for record in records or []
        if isinstance(record, dict)
    ]


def find_first_existing_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """
    หา column แรกที่มีอยู่จริงจาก candidates
    """

    if df is None or df.empty:
        return None

    columns = list(df.columns)
    clean_to_original = {
        clean_column_name(col): col
        for col in columns
    }

    for candidate in candidates:
        if candidate in columns:
            return candidate

        candidate_clean = clean_column_name(candidate)
        if candidate_clean in clean_to_original:
            return clean_to_original[candidate_clean]

    return None


def first_value_by_columns(row: Union[pd.Series, Dict[str, Any]], candidates: List[str], default: Any = None) -> Any:
    """
    คืนค่าแรกที่ไม่ว่างจาก column candidates
    """

    if row is None:
        return default

    for candidate in candidates:
        try:
            value = row.get(candidate)
        except Exception:
            value = None

        if not is_empty_value(value):
            return value

    return default


def limit_dataframe(df: pd.DataFrame, limit: Optional[int] = None, offset: int = 0) -> pd.DataFrame:
    """
    จำกัดจำนวนแถว DataFrame ด้วย offset/limit
    """

    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()

    try:
        safe_offset = max(0, int(offset or 0))
    except Exception:
        safe_offset = 0

    if limit is None:
        return result.iloc[safe_offset:].copy()

    try:
        safe_limit = max(0, int(limit or 0))
    except Exception:
        safe_limit = 0

    if safe_limit <= 0:
        return result.iloc[safe_offset:].copy()

    return result.iloc[safe_offset:safe_offset + safe_limit].copy()


def filter_by_province(df: pd.DataFrame, province: Optional[Any] = None) -> pd.DataFrame:
    """
    filter DataFrame ตาม province/province_model/province_name_th
    """

    if df is None or df.empty or is_empty_value(province):
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    province_value = normalize_province_name(province)

    if not province_value:
        return df.copy()

    province_columns = [
        "province",
        "province_name",
        "province_name_th",
        "province_model",
        "changwat",
        "province_th",
    ]

    result = df.copy()
    mask = pd.Series([False] * len(result), index=result.index)

    for col in province_columns:
        if col not in result.columns:
            continue

        mask = mask | result[col].apply(lambda value: normalize_province_name(value) == province_value)

    return result[mask].copy()


def filter_by_risk(df: pd.DataFrame, risk_level: Optional[Any] = None) -> pd.DataFrame:
    """
    filter DataFrame ตาม risk level/risk status/warning level
    """

    if df is None or df.empty or is_empty_value(risk_level):
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    risk_value = normalize_risk_level(risk_level)

    risk_columns = [
        "risk_level",
        "risk_status",
        "flood_risk_level",
        "warning_level",
        "warning_level_predict",
        "risk_group",
    ]

    result = df.copy()
    mask = pd.Series([False] * len(result), index=result.index)

    for col in risk_columns:
        if col not in result.columns:
            continue

        mask = mask | result[col].apply(lambda value: normalize_risk_level(value) == risk_value)

    return result[mask].copy()


def filter_has_location(df: pd.DataFrame, has_location: Optional[Any] = None) -> pd.DataFrame:
    """
    filter DataFrame ตามสถานะพิกัด
    """

    if df is None or df.empty or has_location in (None, ""):
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    expected = to_bool(has_location, default=None)

    if expected is None:
        return df.copy()

    result = df.copy()

    lat_col = find_first_existing_column(result, ["lat", "latitude"])
    lon_col = find_first_existing_column(result, ["lon", "longitude"])

    if not lat_col or not lon_col:
        if expected is False:
            return result.copy()
        return result.iloc[0:0].copy()

    mask = result.apply(
        lambda row: validate_coordinate(row.get(lat_col), row.get(lon_col)).get("valid") is expected,
        axis=1,
    )

    return result[mask].copy()

def read_latest_sheet(
    sheet_name: Union[str, int],
    use_cache: bool = True,
    return_meta: bool = False,
) -> Union[pd.DataFrame, Dict[str, Any]]:
    """
    อ่าน sheet จาก latest_database.xlsx
    """

    logical_sheet = str(sheet_name or "").strip()
    actual_sheet = getattr(config, "LATEST_SHEETS", {}).get(logical_sheet, sheet_name)

    return read_excel_sheet(
        getattr(config, "LATEST_EXCEL_FILE", getattr(config, "FLOOD_LATEST_DATABASE_PATH")),
        sheet_name=actual_sheet,
        dtype=None,
        use_cache=use_cache,
        return_meta=return_meta,
    )


def read_master_sheet(
    sheet_name: Union[str, int],
    use_cache: bool = True,
    return_meta: bool = False,
) -> Union[pd.DataFrame, Dict[str, Any]]:
    """
    อ่าน sheet จาก master_database.xlsx
    """

    logical_sheet = str(sheet_name or "").strip()
    actual_sheet = getattr(config, "MASTER_SHEETS", {}).get(logical_sheet, sheet_name)

    return read_excel_sheet(
        getattr(config, "MASTER_EXCEL_FILE", getattr(config, "FLOOD_MASTER_DATABASE_PATH")),
        sheet_name=actual_sheet,
        dtype=None,
        use_cache=use_cache,
        return_meta=return_meta,
    )


def read_history_sheet(
    data_type: Any,
    year: Union[int, str],
    month: Union[int, str],
    sheet_name: Optional[Union[str, int]] = None,
    use_cache: bool = True,
    return_meta: bool = False,
) -> Union[pd.DataFrame, Dict[str, Any]]:
    """
    อ่าน history Excel ตาม data_type/year/month
    """

    history_file = config.get_history_file(data_type, year, month)
    actual_sheet = sheet_name if sheet_name is not None else config.get_history_sheet(data_type)

    return read_excel_sheet(
        history_file,
        sheet_name=actual_sheet,
        dtype=None,
        use_cache=use_cache,
        return_meta=return_meta,
    )


def get_latest_prediction_file() -> Optional[Path]:
    """
    คืนไฟล์ prediction ล่าสุด
    """

    if hasattr(config, "find_latest_prediction_file"):
        return config.find_latest_prediction_file()

    prediction_dir = getattr(config, "PREDICTION_DATA_DIR", None)
    prediction_glob = getattr(config, "PREDICTION_FILE_GLOB", "predict_*.xlsx")

    if prediction_dir is None:
        return None

    base_dir = Path(prediction_dir)

    if not base_dir.exists():
        return None

    files = sorted(
        [
            path
            for path in base_dir.glob(prediction_glob)
            if path.is_file()
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    return files[0] if files else None


def read_prediction_file(
    file_path: Optional[Union[str, Path]] = None,
    use_cache: bool = True,
    return_meta: bool = False,
) -> Union[pd.DataFrame, Dict[str, Any]]:
    """
    อ่าน prediction Excel file
    """

    target_file = Path(file_path) if file_path else get_latest_prediction_file()

    if target_file is None:
        empty_df = pd.DataFrame()
        meta = {
            "source": "excel",
            "source_file": None,
            "sheet_name": 0,
            "file_exists": False,
            "cache_used": False,
            "record_count": 0,
        }

        if return_meta:
            return {
                "df": empty_df,
                "meta": meta,
                "errors": [
                    {
                        "code": "prediction_file_not_found",
                        "message": "ไม่พบไฟล์ prediction",
                    }
                ],
            }

        return empty_df

    sheet_name = 0

    try:
        sheet_names = get_excel_sheet_names(target_file)
        if sheet_names:
            sheet_name = sheet_names[0]
    except Exception:
        sheet_name = 0

    return read_excel_sheet(
        target_file,
        sheet_name=sheet_name,
        dtype=None,
        use_cache=use_cache,
        return_meta=return_meta,
    )


def excel_source_payload(
    df: pd.DataFrame,
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    message: str = "Excel source records",
) -> Dict[str, Any]:
    """
    สร้าง payload มาตรฐานสำหรับ Excel source
    """

    records = dataframe_to_records(df)

    return ok_payload(
        data={
            "records": records,
            "total": len(records),
        },
        message=message,
        meta={
            "source": "excel",
            "record_count": len(records),
            **(meta or {}),
        },
    ) if not errors else error_payload(
        message=message,
        errors=errors,
        data={
            "records": records,
            "total": len(records),
        },
        meta={
            "source": "excel",
            "record_count": len(records),
            **(meta or {}),
        },
    )


def clear_excel_cache() -> Dict[str, Any]:
    """
    ลบ cache ที่เกี่ยวกับ Excel source
    """

    removed: List[str] = []

    patterns = [
        "excel_cache_*.json",
        "excel_cache_*_cache_meta.json",
        "excel_cache_*__cache_meta.json",
    ]

    ensure_dir(CACHE_DIR)

    for pattern in patterns:
        for path in CACHE_DIR.glob(pattern):
            if path.exists() and path.is_file():
                path.unlink()
                removed.append(str(path))

    return {
        "cleared": True,
        "removed": removed,
        "count": len(removed),
        "source": "excel",
    }

def write_excel(
    path: Union[str, Path],
    sheets: Dict[str, pd.DataFrame],
    index: bool = False,
) -> Path:
    """
    เขียน Excel หลาย sheet
    """

    target = ensure_parent_dir(path)

    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_sheet = str(sheet_name)[:31] or "Sheet1"

            if isinstance(df, pd.DataFrame):
                df.to_excel(writer, sheet_name=safe_sheet, index=index)
            else:
                pd.DataFrame(df).to_excel(writer, sheet_name=safe_sheet, index=index)

    return target


# ============================================================
# 5) DATA CLEANING HELPERS
# ============================================================

def is_empty_value(value: Any) -> bool:
    """
    ตรวจค่าว่างแบบรวมหลายรูปแบบ
    """

    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except Exception:
        pass

    text = str(value).strip()

    if text == "":
        return True

    return text.lower() in NA_VALUES


def clean_text(value: Any, default: str = "") -> str:
    """
    ทำความสะอาดข้อความพื้นฐาน

    - handle None / NaN
    - strip
    - normalize unicode
    - collapse whitespace
    """

    if is_empty_value(value):
        return default

    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "")
    text = text.replace("\ufeff", "")
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    return text if text else default


def clean_text_lower(value: Any, default: str = "") -> str:
    """
    clean text แล้ว lower
    """

    return clean_text(value, default=default).lower()


def clean_column_name(value: Any) -> str:
    """
    normalize column name ให้เป็น snake_case แบบง่าย
    """

    text = clean_text(value)

    if not text:
        return ""

    text = text.replace("%", " percent ")
    text = re.sub(r"[^\w\u0E00-\u0E7F]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    text = text.strip("_").lower()

    return text


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    normalize ชื่อ column ของ DataFrame เป็น snake_case

    หมายเหตุ:
    ไม่ได้ rename ตาม schema synonym
    แค่ทำ column เดิมให้สะอาดขึ้น
    """

    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()
    result.columns = [clean_column_name(col) for col in result.columns]
    return result


def rename_columns_by_candidates(
    df: pd.DataFrame,
    candidates: Dict[str, List[str]],
    keep_original: bool = True,
) -> pd.DataFrame:
    """
    rename columns จาก candidate names ไปเป็น internal field name

    Args:
        df:
            DataFrame ต้นฉบับ

        candidates:
            dict internal_name -> list possible column names

        keep_original:
            ถ้า True column ที่ไม่ match จะยังอยู่
    """

    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()

    original_columns = list(result.columns)
    clean_to_original: Dict[str, str] = {
        clean_column_name(col): col
        for col in original_columns
    }

    rename_map: Dict[str, str] = {}

    for internal_name, possible_names in candidates.items():
        for possible in possible_names:
            possible_clean = clean_column_name(possible)

            if possible in original_columns:
                rename_map[possible] = internal_name
                break

            if possible_clean in clean_to_original:
                rename_map[clean_to_original[possible_clean]] = internal_name
                break

    result = result.rename(columns=rename_map)

    if not keep_original:
        keep_cols = [col for col in result.columns if col in candidates.keys()]
        result = result[keep_cols]

    return result


def to_number(value: Any, default: Optional[float] = None) -> Optional[float]:
    """
    แปลงค่าเป็น float

    รองรับ:
    - comma
    - currency symbols
    - dash / empty
    - percentage sign
    """

    if is_empty_value(value):
        return default

    if isinstance(value, (int, float)):
        try:
            if math.isnan(float(value)):
                return default
        except Exception:
            pass
        return float(value)

    text = clean_text(value)

    if not text:
        return default

    text = text.replace(",", "")
    text = text.replace("฿", "")
    text = text.replace("บาท", "")
    text = text.replace("%", "")
    text = text.strip()

    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]

    text = re.sub(r"[^0-9.\-]", "", text)

    if text in {"", "-", ".", "-."}:
        return default

    try:
        return float(text)
    except Exception:
        try:
            return float(Decimal(text))
        except (InvalidOperation, ValueError):
            return default


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """
    แปลงค่าเป็น int
    """

    number = to_number(value, default=None)

    if number is None:
        return default

    try:
        return int(round(number))
    except Exception:
        return default


def to_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    """
    แปลงค่าเป็น boolean
    """

    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = clean_text_lower(value)

    if text in TRUE_VALUES:
        return True

    if text in FALSE_VALUES:
        return False

    return default


def to_datetime(value: Any, default: Optional[datetime] = None) -> Optional[datetime]:
    """
    แปลงค่าเป็น datetime
    """

    if is_empty_value(value):
        return default

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)

    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return default

        if hasattr(parsed, "to_pydatetime"):
            return parsed.to_pydatetime()

        return parsed
    except Exception:
        return default


def dataframe_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    แปลง DataFrame เป็น list dict แบบ JSON safe
    """

    if df is None or df.empty:
        return []

    clean_df = df.copy()
    clean_df = clean_df.where(pd.notnull(clean_df), None)

    return [
        to_jsonable(record)
        for record in clean_df.to_dict(orient="records")
    ]


def records_to_dataframe(records: Any) -> pd.DataFrame:
    """
    แปลง records เป็น DataFrame
    """

    if records is None:
        return pd.DataFrame()

    if isinstance(records, pd.DataFrame):
        return records.copy()

    if isinstance(records, dict):
        if "records" in records and isinstance(records["records"], list):
            return pd.DataFrame(records["records"])
        return pd.DataFrame([records])

    if isinstance(records, list):
        return pd.DataFrame(records)

    return pd.DataFrame()


def clean_dataframe_common(df: pd.DataFrame) -> pd.DataFrame:
    """
    clean DataFrame แบบพื้นฐาน

    - replace NaN with None ในระดับ serialization ภายหลัง
    - trim string cells
    - drop empty columns ที่ชื่อว่าง
    """

    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()

    result = result.loc[:, [clean_text(col) != "" for col in result.columns]]

    for col in result.columns:
        if result[col].dtype == "object":
            result[col] = result[col].apply(lambda x: clean_text(x, default="") if not is_empty_value(x) else None)

    return result


# ============================================================
# 6) TAX ID HELPERS
# ============================================================

def normalize_tax_id(value: Any) -> str:
    """
    normalize Tax ID ให้ใช้ join ข้ามไฟล์ได้

    รองรับ:
    - None / NaN / empty
    - Excel float เช่น 505532000000.0
    - scientific notation เช่น 5.05532E+11
    - comma / space / dash / punctuation
    - เลขเกิน 13 หลัก ให้ใช้ 13 หลักท้าย
    - เลขน้อยกว่า 13 หลัก เติม 0 ด้านหน้า
    """

    if is_empty_value(value):
        return ""

    text = clean_text(value)

    if not text:
        return ""

    text = text.replace(",", "")
    text = text.replace(" ", "")
    text = text.replace("\t", "")

    try:
        if isinstance(value, float):
            if math.isfinite(value):
                text = str(int(value))

        elif re.search(r"[eE][+-]?\d+", text):
            text = str(int(float(text)))

        elif re.fullmatch(r"\d+\.0+", text):
            text = text.split(".")[0]

        elif re.fullmatch(r"\d+\.\d+", text):
            number = float(text)
            if number.is_integer():
                text = str(int(number))

    except Exception:
        pass

    digits = re.sub(r"\D", "", text)

    if not digits:
        return ""

    if len(digits) > 13:
        digits = digits[-13:]

    if len(digits) < 13:
        digits = digits.zfill(13)

    return digits


def validate_tax_id(tax_id: Any) -> Dict[str, Any]:
    """
    validate Tax ID แบบใช้งานจริง

    หมายเหตุ:
    ใช้ logic basic:
    - ต้องมีค่า
    - ต้องเป็นตัวเลข 13 หลัก
    """

    raw = clean_text(tax_id)
    norm = normalize_tax_id(tax_id)

    issues: List[str] = []

    if not raw:
        issues.append("missing_tax_id")

    if not norm:
        issues.append("empty_after_normalize")

    if norm and not norm.isdigit():
        issues.append("not_numeric")

    if norm and len(norm) != 13:
        issues.append("not_13_digits")

    return {
        "tax_id_raw": raw,
        "tax_id_norm": norm,
        "tax_id_valid": len(issues) == 0,
        "tax_id_issue": "|".join(issues) if issues else "",
        "issues": issues,
    }


def add_tax_id_columns(df: pd.DataFrame, source_column: str = "tax_id") -> pd.DataFrame:
    """
    เพิ่ม column tax_id_raw, tax_id_norm, tax_id_valid, tax_id_issue
    """

    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()

    if source_column not in result.columns:
        result["tax_id_raw"] = ""
        result["tax_id_norm"] = ""
        result["tax_id_valid"] = False
        result["tax_id_issue"] = "source_column_missing"
        return result

    validations = result[source_column].apply(validate_tax_id)

    result["tax_id_raw"] = validations.apply(lambda x: x["tax_id_raw"])
    result["tax_id_norm"] = validations.apply(lambda x: x["tax_id_norm"])
    result["tax_id_valid"] = validations.apply(lambda x: x["tax_id_valid"])
    result["tax_id_issue"] = validations.apply(lambda x: x["tax_id_issue"])

    return result


def mask_tax_id(tax_id: Any, visible_last_digits: int = 4) -> str:
    """
    mask Tax ID สำหรับ external package
    """

    norm = normalize_tax_id(tax_id)

    if not norm:
        return ""

    visible_last_digits = max(0, min(int(visible_last_digits), len(norm)))

    if visible_last_digits == 0:
        return "*" * len(norm)

    return "*" * (len(norm) - visible_last_digits) + norm[-visible_last_digits:]


# ============================================================
# 7) POLICY HELPERS
# ============================================================

def normalize_policy_status(value: Any) -> str:
    """
    normalize policy status เป็น Active / Expired / Unknown / Other
    """

    text = clean_text_lower(value)

    if not text:
        return "Unknown"

    if text in ACTIVE_POLICY_VALUES:
        return "Active"

    if text in EXPIRED_POLICY_VALUES:
        return "Expired"

    if "active" in text and "inactive" not in text:
        return "Active"

    if "expired" in text or "cancel" in text:
        return "Expired"

    return clean_text(value, default="Other")


def is_active_policy_row(row: Union[pd.Series, Dict[str, Any]]) -> bool:
    """
    ตรวจ active policy ตาม rule:

    Active เมื่อ:
    - inforced_flag = Inforced
    - status_now_new = Active
    """

    inforced_flag = clean_text_lower(row.get("inforced_flag", ""))
    status_now_new = clean_text_lower(row.get("status_now_new", ""))

    expected_inforced = clean_text_lower(POLICY_ACTIVE_RULE.get("inforced_flag_should_equal", "Inforced"))
    expected_status = clean_text_lower(POLICY_ACTIVE_RULE.get("status_now_new_should_equal", "Active"))

    return inforced_flag == expected_inforced and status_now_new == expected_status


def detect_policy_status_conflict(row: Union[pd.Series, Dict[str, Any]]) -> bool:
    """
    ตรวจ conflict ของสถานะกรมธรรม์

    ตัวอย่าง conflict:
    - Inforced Flag บอก Inforced แต่ status_new ไม่ Active
    - status_new Active แต่ inforced flag ไม่ Inforced
    """

    inforced_flag = clean_text_lower(row.get("inforced_flag", ""))
    status_now_new = clean_text_lower(row.get("status_now_new", ""))

    if not inforced_flag and not status_now_new:
        return False

    inforced_is_active = inforced_flag in {"inforced", "inforce", "active"}
    status_is_active = status_now_new in {"active", "inforced", "inforce"}

    return inforced_is_active != status_is_active


def calculate_loss_ratio(
    loss: Any,
    premium: Any,
    zero_policy: str = "none",
) -> Optional[float]:
    """
    คำนวณ Loss Ratio = Loss / Premium * 100

    Args:
        loss:
            ค่าสินไหม

        premium:
            เบี้ยประกัน

        zero_policy:
            - "none": ถ้า premium = 0 คืน None
            - "zero": ถ้า premium = 0 และ loss = 0 คืน 0
    """

    loss_value = to_number(loss, default=0.0) or 0.0
    premium_value = to_number(premium, default=0.0) or 0.0

    if premium_value == 0:
        if zero_policy == "zero" and loss_value == 0:
            return 0.0
        return None

    return round((loss_value / premium_value) * 100.0, 4)


def get_loss_ratio_band(loss_ratio: Any, premium: Any = None, loss: Any = None) -> str:
    """
    คืน band ของ Loss Ratio

    ถ้า premium = 0 แต่ loss > 0 ให้ Undefined
    """

    lr = to_number(loss_ratio, default=None)

    premium_value = to_number(premium, default=None)
    loss_value = to_number(loss, default=None)

    if lr is None:
        if premium_value == 0 and loss_value and loss_value > 0:
            return "Undefined"
        return "Undefined"

    for band, config in LOSS_RATIO_BANDS.items():
        if band == "Undefined":
            continue

        min_value = config.get("min")
        max_value = config.get("max")

        if min_value is not None and lr < min_value:
            continue

        if max_value is not None and lr >= max_value:
            continue

        return band

    return "Undefined"


def build_policy_summary_from_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    สร้าง policy summary จาก records
    """

    total_premium = sum(to_number(r.get("premium"), 0.0) or 0.0 for r in records)
    total_loss = sum(to_number(r.get("loss"), 0.0) or 0.0 for r in records)
    total_suminsure = sum(to_number(r.get("suminsure"), 0.0) or 0.0 for r in records)
    total_noofpol = sum(to_number(r.get("noofpol"), 0.0) or 0.0 for r in records)

    loss_ratio = calculate_loss_ratio(total_loss, total_premium, zero_policy="zero")

    return {
        "total_premium": total_premium,
        "total_loss": total_loss,
        "total_suminsure": total_suminsure,
        "total_noofpol": total_noofpol,
        "loss_ratio": loss_ratio,
        "loss_ratio_band": get_loss_ratio_band(loss_ratio, premium=total_premium, loss=total_loss),
        "record_count": len(records),
    }


# ============================================================
# 8) LINKAGE HELPERS
# ============================================================

def normalize_director_name(value: Any) -> str:
    """
    normalize ชื่อกรรมการ

    - clean text
    - normalize whitespace
    - ลบ prefix/suffix ที่ซ้ำเกินจำเป็นแบบเบื้องต้น
    """

    text = clean_text(value)

    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ,;|")

    return text


def normalize_director_name_for_id(value: Any) -> str:
    """
    normalize ชื่อกรรมการสำหรับสร้าง id
    """

    text = normalize_director_name(value).lower()
    text = re.sub(r"[\s\.\-_/\\]+", "", text)
    return text


def make_hash_id(value: Any, prefix: str = "", length: int = 16) -> str:
    """
    สร้าง deterministic hash id
    """

    text = clean_text(value)

    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]

    if prefix:
        return f"{prefix}_{digest}"

    return digest


def make_director_id(director_name: Any) -> str:
    """
    สร้าง director_id จากชื่อกรรมการ
    """

    norm = normalize_director_name_for_id(director_name)

    if not norm:
        return ""

    return make_hash_id(norm, prefix=DIRECTOR_ID_PREFIX, length=16)


def make_company_node_id(tax_id: Any) -> str:
    """
    สร้าง company node id สำหรับ graph
    """

    tax_id_norm = normalize_tax_id(tax_id)

    if not tax_id_norm:
        return ""

    return f"{COMPANY_NODE_PREFIX}:{tax_id_norm}"


def make_director_node_id(director_id: Any) -> str:
    """
    สร้าง director node id สำหรับ graph
    """

    director_id_text = clean_text(director_id)

    if not director_id_text:
        return ""

    return f"{DIRECTOR_NODE_PREFIX}:{director_id_text}"


def make_edge_id(source: Any, target: Any, edge_type: str) -> str:
    """
    สร้าง edge id แบบ deterministic
    """

    source_text = clean_text(source)
    target_text = clean_text(target)
    edge_type_text = clean_text(edge_type)

    key = f"{edge_type_text}|{source_text}|{target_text}"
    return make_hash_id(key, prefix="edge", length=20)


def parse_boardlist(value: Any) -> List[str]:
    """
    แยก boardlist เป็นรายชื่อกรรมการ

    รองรับตัวคั่น:
    - comma
    - newline
    - semicolon
    - pipe
    """

    text = clean_text(value)

    if not text:
        return []

    parts = re.split(BOARDLIST_SPLIT_PATTERN, text)

    names: List[str] = []

    seen = set()

    for part in parts:
        name = normalize_director_name(part)

        if not name:
            continue

        name_key = normalize_director_name_for_id(name)

        if not name_key or name_key in seen:
            continue

        seen.add(name_key)
        names.append(name)

    return names


def build_director_company_pairs_from_record(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    สร้าง director-company pairs จาก linkage record 1 แถว
    """

    tax_id_norm = normalize_tax_id(record.get("tax_id_norm") or record.get("tax_id"))
    company_name = clean_text(record.get("company_name") or record.get("name_th"))
    boardlist = record.get("boardlist")

    director_names = parse_boardlist(boardlist)

    pairs: List[Dict[str, Any]] = []

    for director_name in director_names:
        director_id = make_director_id(director_name)

        if not director_id:
            continue

        pairs.append(
            {
                "director_id": director_id,
                "director_name": director_name,
                "director_name_norm": normalize_director_name_for_id(director_name),
                "tax_id_norm": tax_id_norm,
                "company_name": company_name,
            }
        )

    return pairs


# ============================================================
# 9) GEO / SPATIAL HELPERS
# ============================================================

def validate_coordinate(lat: Any, lon: Any) -> Dict[str, Any]:
    """
    validate coordinate ว่าเป็นตัวเลขและอยู่ในช่วงประเทศไทย
    """

    lat_value = to_number(lat, default=None)
    lon_value = to_number(lon, default=None)

    issues: List[str] = []

    if lat_value is None or lon_value is None:
        issues.append("missing_coordinate")
        return {
            "valid": False,
            "lat": lat_value,
            "lon": lon_value,
            "issue": "|".join(issues),
            "issues": issues,
        }

    if not (THAILAND_LAT_RANGE[0] <= lat_value <= THAILAND_LAT_RANGE[1]):
        issues.append("lat_outside_thailand_range")

    if not (THAILAND_LON_RANGE[0] <= lon_value <= THAILAND_LON_RANGE[1]):
        issues.append("lon_outside_thailand_range")

    return {
        "valid": len(issues) == 0,
        "lat": lat_value,
        "lon": lon_value,
        "issue": "|".join(issues),
        "issues": issues,
    }


def haversine_km(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> Optional[float]:
    """
    คำนวณระยะทาง Haversine เป็นกิโลเมตร
    """

    p1 = validate_coordinate(lat1, lon1)
    p2 = validate_coordinate(lat2, lon2)

    if p1["lat"] is None or p1["lon"] is None or p2["lat"] is None or p2["lon"] is None:
        return None

    r = 6371.0088

    phi1 = math.radians(float(p1["lat"]))
    phi2 = math.radians(float(p2["lat"]))
    delta_phi = math.radians(float(p2["lat"]) - float(p1["lat"]))
    delta_lambda = math.radians(float(p2["lon"]) - float(p1["lon"]))

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(r * c, 4)


def find_nearest_record(
    origin_lat: Any,
    origin_lon: Any,
    candidates: List[Dict[str, Any]],
    lat_key: str = "lat",
    lon_key: str = "lon",
    max_distance_km: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    หา record ที่ใกล้ที่สุดจาก candidates
    """

    nearest: Optional[Dict[str, Any]] = None
    nearest_distance: Optional[float] = None

    for candidate in candidates:
        distance = haversine_km(
            origin_lat,
            origin_lon,
            candidate.get(lat_key),
            candidate.get(lon_key),
        )

        if distance is None:
            continue

        if max_distance_km is not None and distance > max_distance_km:
            continue

        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest = dict(candidate)
            nearest["_distance_km"] = distance

    return nearest


def normalize_province_name(value: Any) -> str:
    """
    normalize ชื่อจังหวัดแบบเบื้องต้น
    """

    text = clean_text(value)

    if not text:
        return ""

    text = text.replace("จังหวัด", "")
    text = re.sub(r"\s+", "", text)

    bangkok_names = {"กรุงเทพ", "กรุงเทพฯ", "กรุงเทพมหานคร", "กทม"}
    if text in bangkok_names:
        return "กรุงเทพมหานคร"

    return text


def make_point_feature(
    lon: Any,
    lat: Any,
    properties: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    สร้าง GeoJSON Point Feature
    """

    coord = validate_coordinate(lat, lon)

    if not coord["valid"]:
        return None

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [coord["lon"], coord["lat"]],
        },
        "properties": to_jsonable(properties or {}),
    }


def make_line_feature(
    coordinates: List[Tuple[float, float]],
    properties: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    สร้าง GeoJSON LineString Feature

    coordinates:
        list of (lon, lat)
    """

    if not coordinates or len(coordinates) < 2:
        return None

    clean_coords: List[List[float]] = []

    for lon, lat in coordinates:
        coord = validate_coordinate(lat, lon)

        if not coord["valid"]:
            continue

        clean_coords.append([float(coord["lon"]), float(coord["lat"])])

    if len(clean_coords) < 2:
        return None

    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": clean_coords,
        },
        "properties": to_jsonable(properties or {}),
    }


def make_feature_collection(features: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    สร้าง GeoJSON FeatureCollection
    """

    clean_features = [
        feature
        for feature in (features or [])
        if isinstance(feature, dict)
        and feature.get("type") == "Feature"
    ]

    return {
        "type": "FeatureCollection",
        "features": clean_features,
    }


# ============================================================
# 10) FLOOD RISK HELPERS
# ============================================================

def normalize_risk_level(value: Any) -> str:
    """
    normalize risk level
    """

    text = clean_text(value)

    if not text:
        return "Unknown"

    for level in RISK_LEVELS:
        if text.lower() == level.lower():
            return level

    thai_mapping = {
        "ปกติ": "Normal",
        "เฝ้าระวัง": "Watch",
        "เตือนภัย": "Warning",
        "วิกฤต": "Critical",
        "ไม่ทราบ": "Unknown",
    }

    return thai_mapping.get(text, "Unknown")


def get_risk_color(risk_level: Any) -> str:
    """
    คืนสีของ risk level
    """

    level = normalize_risk_level(risk_level)
    return RISK_COLORS.get(level, RISK_COLORS["Unknown"])


def get_risk_score(risk_level: Any) -> int:
    """
    คืน score ของ risk level
    """

    level = normalize_risk_level(risk_level)
    return RISK_SCORE.get(level, -1)


def combine_risk_levels(levels: Iterable[Any]) -> str:
    """
    รวม risk levels โดยเลือกตัวที่รุนแรงที่สุด
    """

    best_level = "Unknown"
    best_score = -1

    for level in levels:
        norm = normalize_risk_level(level)
        score = get_risk_score(norm)

        if score > best_score:
            best_level = norm
            best_score = score

    return best_level


def calculate_rainfall_risk(rainfall_mm: Any) -> Dict[str, Any]:
    """
    คำนวณ rainfall risk จากปริมาณฝน
    """

    value = to_number(rainfall_mm, default=None)

    if value is None:
        return {
            "risk_level": "Unknown",
            "risk_score": -1,
            "risk_reason": "missing rainfall value",
            "risk_color": get_risk_color("Unknown"),
        }

    if value >= FLOOD_RAINFALL_THRESHOLDS_MM["critical_min"]:
        level = "Critical"
    elif value > FLOOD_RAINFALL_THRESHOLDS_MM["warning_max"]:
        level = "Critical"
    elif value > FLOOD_RAINFALL_THRESHOLDS_MM["watch_max"]:
        level = "Warning"
    elif value > FLOOD_RAINFALL_THRESHOLDS_MM["normal_max"]:
        level = "Watch"
    else:
        level = "Normal"

    return {
        "risk_level": level,
        "risk_score": get_risk_score(level),
        "risk_reason": f"rainfall={value} mm",
        "risk_color": get_risk_color(level),
    }


def calculate_waterlevel_risk(
    waterlevel: Any,
    warning_level: Any = None,
    critical_level: Any = None,
) -> Dict[str, Any]:
    """
    คำนวณ waterlevel risk
    """

    value = to_number(waterlevel, default=None)
    warning = to_number(warning_level, default=None)
    critical = to_number(critical_level, default=None)

    if value is None:
        return {
            "risk_level": "Unknown",
            "risk_score": -1,
            "risk_reason": "missing waterlevel value",
            "risk_color": get_risk_color("Unknown"),
        }

    if critical is not None and value >= critical:
        level = "Critical"
        reason = f"waterlevel={value} >= critical={critical}"
    elif warning is not None and value >= warning:
        level = "Warning"
        reason = f"waterlevel={value} >= warning={warning}"
    elif warning is not None and value >= warning * FLOOD_WATERLEVEL_THRESHOLDS["watch_ratio"]:
        level = "Watch"
        reason = f"waterlevel={value} near warning={warning}"
    else:
        level = "Normal"
        reason = f"waterlevel={value}"

    return {
        "risk_level": level,
        "risk_score": get_risk_score(level),
        "risk_reason": reason,
        "risk_color": get_risk_color(level),
    }


def calculate_dam_risk(storage_percent: Any) -> Dict[str, Any]:
    """
    คำนวณ dam risk จาก storage percent
    """

    value = to_number(storage_percent, default=None)

    if value is None:
        return {
            "risk_level": "Unknown",
            "risk_score": -1,
            "risk_reason": "missing storage percent",
            "risk_color": get_risk_color("Unknown"),
        }

    if value >= FLOOD_DAM_STORAGE_THRESHOLDS_PERCENT["critical_min"]:
        level = "Critical"
    elif value > FLOOD_DAM_STORAGE_THRESHOLDS_PERCENT["warning_max"]:
        level = "Critical"
    elif value > FLOOD_DAM_STORAGE_THRESHOLDS_PERCENT["watch_max"]:
        level = "Warning"
    elif value > FLOOD_DAM_STORAGE_THRESHOLDS_PERCENT["normal_max"]:
        level = "Watch"
    else:
        level = "Normal"

    return {
        "risk_level": level,
        "risk_score": get_risk_score(level),
        "risk_reason": f"dam storage={value}%",
        "risk_color": get_risk_color(level),
    }


# ============================================================
# 11) SEARCH / SORT / PAGINATION HELPERS
# ============================================================

def search_records(
    records: List[Dict[str, Any]],
    search: str,
    fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    search records แบบ contains
    """

    query = clean_text_lower(search)

    if not query:
        return records

    result: List[Dict[str, Any]] = []

    for record in records:
        search_values: List[str] = []

        if fields:
            for field in fields:
                search_values.append(clean_text(record.get(field)))
        else:
            search_values = [clean_text(v) for v in record.values()]

        haystack = " ".join(search_values).lower()

        if query in haystack:
            result.append(record)

    return result


def sort_records(
    records: List[Dict[str, Any]],
    sort_by: str = "",
    sort_dir: str = "asc",
) -> List[Dict[str, Any]]:
    """
    sort records
    """

    sort_by = clean_text(sort_by)

    if not sort_by:
        return records

    reverse = clean_text_lower(sort_dir) == "desc"

    def sort_key(record: Dict[str, Any]) -> Tuple[int, Any]:
        value = record.get(sort_by)

        if value is None:
            return (1, "")

        number = to_number(value, default=None)

        if number is not None:
            return (0, number)

        return (0, clean_text(value).lower())

    try:
        return sorted(records, key=sort_key, reverse=reverse)
    except Exception:
        return records


def paginate_records(
    records: List[Dict[str, Any]],
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """
    paginate records
    """

    page = max(1, int(page or 1))
    page_size = max(1, int(page_size or 50))

    total = len(records)
    offset = (page - 1) * page_size
    end = offset + page_size

    page_records = records[offset:end]

    total_pages = math.ceil(total / page_size) if page_size else 1

    return {
        "records": page_records,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


def apply_search_sort_pagination(
    records: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
    searchable_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    apply search + sort + pagination ตาม context จาก api_routes
    """

    context = context or {}

    result = list(records)

    result = search_records(
        result,
        context.get("search", ""),
        fields=searchable_fields,
    )

    result = sort_records(
        result,
        sort_by=context.get("sort_by", ""),
        sort_dir=context.get("sort_dir", "asc"),
    )

    return paginate_records(
        result,
        page=int(context.get("page", 1) or 1),
        page_size=int(context.get("page_size", 50) or 50),
    )


# ============================================================
# 12) CACHE HELPERS
# ============================================================

def get_cache_file_path(cache_key: str) -> Path:
    """
    คืน path cache file จาก cache_key
    """

    if hasattr(config, "get_cache_path"):
        return config.get_cache_path(cache_key)

    safe_key = safe_filename(cache_key, default="cache")
    return CACHE_DIR / f"{safe_key}.json"


def get_cache_meta_path(cache_key: str) -> Path:
    """
    คืน path cache metadata
    """

    cache_path = get_cache_file_path(cache_key)
    stem = cache_path.stem
    return cache_path.with_name(f"{stem}_{CACHE_METADATA_FILENAME}")


def is_cache_valid(cache_key: str, ttl_seconds: Optional[int] = None) -> bool:
    """
    ตรวจว่า cache ยัง valid หรือไม่
    """

    if not CACHE_ENABLED:
        return False

    cache_path = get_cache_file_path(cache_key)
    meta_path = get_cache_meta_path(cache_key)

    if not cache_path.exists() or not meta_path.exists():
        return False

    meta = read_json(meta_path, default={})

    created_at_raw = meta.get("created_at")

    if not created_at_raw:
        return False

    try:
        created_at = datetime.fromisoformat(created_at_raw)
    except Exception:
        return False

    if ttl_seconds is None:
        ttl_seconds = int(meta.get("ttl_seconds", 0) or 0)

    if ttl_seconds <= 0:
        return False

    return datetime.now() - created_at <= timedelta(seconds=ttl_seconds)


def read_cache(cache_key: str, default: Optional[Any] = None) -> Any:
    """
    อ่าน cache
    """

    return read_json(get_cache_file_path(cache_key), default=default)


def write_cache(
    cache_key: str,
    data: Any,
    ttl_seconds: int = 3600,
    source: str = "",
) -> Dict[str, Any]:
    """
    เขียน cache พร้อม metadata
    """

    ensure_dir(CACHE_DIR)

    cache_path = get_cache_file_path(cache_key)
    meta_path = get_cache_meta_path(cache_key)

    temp_cache_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temp_meta_path = meta_path.with_suffix(meta_path.suffix + ".tmp")

    write_json(temp_cache_path, data)

    temp_cache_path.replace(cache_path)

    registry = getattr(config, "CACHE_REGISTRY", {})
    registry_item = registry.get(cache_key, {}) if isinstance(registry, dict) else {}

    meta = {
        "cache_key": cache_key,
        "created_at": now_iso(),
        "ttl_seconds": ttl_seconds,
        "source": source,
        "path": str(cache_path),
        "owner_service": registry_item.get("owner_service"),
        "payload_type": registry_item.get("payload_type"),
        "depends_on": registry_item.get("depends_on", []),
        "consumed_by": registry_item.get("consumed_by", []),
        "critical": registry_item.get("critical", False),
        "allow_stale": registry_item.get("allow_stale", True),
        "aliases": registry_item.get("aliases", []),
    }

    write_json(temp_meta_path, meta)
    temp_meta_path.replace(meta_path)

    return {
        "cache_key": cache_key,
        "cache_path": str(cache_path),
        "meta_path": str(meta_path),
        "meta": meta,
    }


def get_or_build_cache(
    cache_key: str,
    builder: Callable[[], Any],
    ttl_seconds: int = 3600,
    force_refresh: bool = False,
    source: str = "",
) -> Dict[str, Any]:
    """
    อ่าน cache ถ้า valid
    ถ้าไม่ valid ให้ build ใหม่
    """

    if not force_refresh and is_cache_valid(cache_key, ttl_seconds=ttl_seconds):
        data = read_cache(cache_key, default={})
        return {
            "data": data,
            "cache_used": True,
            "cache_key": cache_key,
        }

    data = builder()
    write_cache(cache_key, data, ttl_seconds=ttl_seconds, source=source)

    return {
        "data": data,
        "cache_used": False,
        "cache_key": cache_key,
    }


def clear_cache(cache_key: Optional[str] = None) -> Dict[str, Any]:
    """
    ลบ cache

    ถ้า cache_key เป็น None จะลบ cache ทั้งหมดใน CACHE_DIR
    """

    removed: List[str] = []

    if cache_key:
        paths = [
            get_cache_file_path(cache_key),
            get_cache_meta_path(cache_key),
        ]
    else:
        paths = list(CACHE_DIR.glob("*.json"))

    for path in paths:
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(str(path))

    return {
        "removed": removed,
        "count": len(removed),
    }


# ============================================================
# 13) EXPORT / ZIP HELPERS
# ============================================================

def create_zip_from_folder(
    folder: Union[str, Path],
    zip_path: Union[str, Path],
    include_root_folder: bool = False,
) -> Path:
    """
    สร้าง ZIP จาก folder
    """

    folder_path = Path(folder)
    target_zip = ensure_parent_dir(zip_path)

    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in folder_path.rglob("*"):
            if not file_path.is_file():
                continue

            if include_root_folder:
                arcname = file_path.relative_to(folder_path.parent)
            else:
                arcname = file_path.relative_to(folder_path)

            zipf.write(file_path, arcname)

    return target_zip


def write_records_export(
    path: Union[str, Path],
    records: List[Dict[str, Any]],
    file_format: str = "json",
) -> Path:
    """
    export records เป็น json/csv/xlsx
    """

    file_format = clean_text_lower(file_format)

    target = Path(path)

    if file_format == "json":
        return write_json(target, records)

    df = records_to_dataframe(records)

    if file_format == "csv":
        return write_csv(target, df)

    if file_format in {"xlsx", "excel"}:
        return write_excel(target, {"data": df})

    raise ValueError(f"Unsupported export format: {file_format}")


# ============================================================
# 14) VALIDATION HELPERS
# ============================================================

def validate_required_fields(record: Dict[str, Any], required_fields: List[str]) -> Dict[str, Any]:
    """
    ตรวจ required fields ใน record
    """

    missing = [
        field
        for field in required_fields
        if is_empty_value(record.get(field))
    ]

    return {
        "valid": len(missing) == 0,
        "missing_fields": missing,
    }


def validate_required_columns_df(df: pd.DataFrame, required_columns: List[str]) -> Dict[str, Any]:
    """
    ตรวจ required columns ใน DataFrame
    """

    columns = set(df.columns) if df is not None else set()
    missing = [col for col in required_columns if col not in columns]

    return {
        "valid": len(missing) == 0,
        "missing_columns": missing,
        "available_columns": list(columns),
    }


def build_issue(
    code: str,
    message: str,
    category: str = "system",
    severity: str = "warning",
    dataset: str = "",
    field: str = "",
    record_key: str = "",
    value: Any = None,
    suggestion: str = "",
) -> Dict[str, Any]:
    """
    สร้าง data quality issue
    """

    key = f"{category}|{severity}|{code}|{dataset}|{field}|{record_key}|{clean_text(value)}"
    issue_id = make_hash_id(key, prefix="issue", length=20)

    return {
        "issue_id": issue_id,
        "category": category,
        "severity": severity,
        "code": code,
        "message": message,
        "dataset": dataset,
        "field": field,
        "record_key": record_key,
        "value": to_jsonable(value),
        "suggestion": suggestion,
        "created_at": now_iso(),
    }


# ============================================================
# 15) AGGREGATION HELPERS
# ============================================================

def group_records_by(records: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    group records ตาม key
    """

    groups: Dict[str, List[Dict[str, Any]]] = {}

    for record in records:
        group_key = clean_text(record.get(key), default="__EMPTY__")
        groups.setdefault(group_key, []).append(record)

    return groups


def sum_field(records: List[Dict[str, Any]], field_name: str) -> float:
    """
    sum numeric field
    """

    return sum(to_number(record.get(field_name), 0.0) or 0.0 for record in records)


def count_distinct(records: List[Dict[str, Any]], field_name: str) -> int:
    """
    count distinct non-empty values
    """

    values = {
        clean_text(record.get(field_name))
        for record in records
        if not is_empty_value(record.get(field_name))
    }

    return len(values)


def first_non_empty(*values: Any, default: Any = None) -> Any:
    """
    คืนค่าแรกที่ไม่ว่าง
    """

    for value in values:
        if not is_empty_value(value):
            return value

    return default


def most_common_value(values: Iterable[Any], default: Any = None) -> Any:
    """
    คืนค่าที่พบมากที่สุด
    """

    counts: Dict[str, int] = {}
    original: Dict[str, Any] = {}

    for value in values:
        if is_empty_value(value):
            continue

        key = clean_text(value)
        counts[key] = counts.get(key, 0) + 1
        original[key] = value

    if not counts:
        return default

    best_key = max(counts, key=counts.get)
    return original.get(best_key, best_key)


# ============================================================
# 16) MISC HELPERS
# ============================================================

def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    deep merge dict
    """

    result = deepcopy(base)

    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)

    return result


def chunk_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    แบ่ง list เป็น chunk
    """

    chunk_size = max(1, int(chunk_size))

    return [
        items[i:i + chunk_size]
        for i in range(0, len(items), chunk_size)
    ]


def clamp(value: Any, min_value: float, max_value: float, default: float = 0.0) -> float:
    """
    จำกัดค่าให้อยู่ในช่วง min/max
    """

    number = to_number(value, default=default)

    if number is None:
        number = default

    return max(min_value, min(max_value, number))


def format_number(value: Any, digits: int = 2, default: str = "-") -> str:
    """
    format number สำหรับ display
    """

    number = to_number(value, default=None)

    if number is None:
        return default

    return f"{number:,.{digits}f}"


def format_percent(value: Any, digits: int = 2, default: str = "-") -> str:
    """
    format percent สำหรับ display
    """

    number = to_number(value, default=None)

    if number is None:
        return default

    return f"{number:,.{digits}f}%"


def module_ready_payload(module_name: str) -> Dict[str, Any]:
    """
    payload สำหรับ module health
    """

    return {
        "module": module_name,
        "ready": True,
        "checked_at": now_iso(),
    }

# ============================================================
# 17) DATA SOURCE DISPATCHER HELPERS
# ============================================================

def get_active_data_source_name() -> str:
    """
    คืนชื่อ active data source จาก config
    """

    if hasattr(config, "get_active_data_source"):
        return config.get_active_data_source()

    if getattr(config, "USE_EXCEL_DATA_SOURCE", True) and not getattr(config, "USE_MYSQL_DATA_SOURCE", False):
        return "excel"

    if getattr(config, "USE_MYSQL_DATA_SOURCE", False) and not getattr(config, "USE_EXCEL_DATA_SOURCE", True):
        return "mysql"

    return "invalid"


def source_not_implemented_payload(source_name: str, function_name: str) -> Dict[str, Any]:
    """
    payload สำหรับ source ที่ยังไม่ implement
    """

    return error_payload(
        message=f"{source_name} data source is not implemented.",
        data={
            "source": source_name,
            "function_name": function_name,
        },
        meta={
            "source": source_name,
            "function_name": function_name,
            "status_code": 501,
        },
        errors=[
            {
                "code": "source_not_implemented",
                "message": f"{source_name} data source is not implemented for {function_name}",
            }
        ],
    )


def get_active_flood_source() -> Dict[str, Any]:
    """
    คืน active flood source contract

    ตอนนี้ Excel ใช้งานจริง
    MySQL เป็น placeholder เท่านั้น
    """

    source_name = get_active_data_source_name()

    if source_name == "excel":
        return {
            "source": "excel",
            "implemented": True,
            "read_excel_sheet": read_excel_sheet,
            "read_latest_sheet": read_latest_sheet,
            "read_master_sheet": read_master_sheet,
            "read_history_sheet": read_history_sheet,
            "read_prediction_file": read_prediction_file,
            "clear_excel_cache": clear_excel_cache,
        }

    if source_name == "mysql":
        return {
            "source": "mysql",
            "implemented": False,
            "message": getattr(config, "DATA_SOURCE_NOT_IMPLEMENTED_MESSAGE", "MySQL data source is not implemented."),
        }

    return {
        "source": "invalid",
        "implemented": False,
        "message": "Invalid data source configuration.",
    }

# ============================================================
# 17) MODULE SUMMARY
# ============================================================

def get_utils_summary() -> Dict[str, Any]:
    """
    คืน summary ของ utils.py
    """

    return {
        "module": "utils",
        "ready": True,
        "active_data_source": get_active_data_source_name(),
        "groups": [
            "response",
            "file",
            "json",
            "excel",
            "excel_source",
            "data_source_dispatcher",
            "cleaning",
            "tax_id",
            "policy",
            "linkage",
            "geo",
            "flood_risk",
            "search_sort_pagination",
            "cache",
            "export",
            "validation",
            "aggregation",
        ],
        "excel_source_functions": [
            "read_excel_sheet",
            "read_latest_sheet",
            "read_master_sheet",
            "read_history_sheet",
            "read_prediction_file",
            "get_latest_prediction_file",
            "clear_excel_cache",
        ],
        "timestamp": now_iso(),
    }