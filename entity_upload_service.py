# backend/entity_upload_service.py
# -*- coding: utf-8 -*-

from __future__ import annotations
# import bootstrap
import csv
import json
import math
import uuid
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from fastapi import UploadFile

import pandas as pd

import config


# ============================================================
# BASIC HELPERS
# ============================================================

def now_dt() -> datetime:
    return datetime.now()


def now_text() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")


def compact_now_text() -> str:
    return now_dt().strftime("%Y%m%d_%H%M%S")


def safe_str(value: Any, default: str = "") -> str:
    if is_empty_value(value):
        return default
    try:
        return str(value).strip()
    except Exception:
        return default


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if is_empty_value(value):
        return default

    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if is_empty_value(value):
        return default

    try:
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return default


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True

    if isinstance(value, float):
        try:
            if math.isnan(value):
                return True
        except Exception:
            pass

    try:
        if pd.isna(value):
            return True
    except Exception:
        pass

    text = str(value).strip()

    if text in config.HIDDEN_EMPTY_VALUES:
        return True

    return False


def clean_value(value: Any) -> Any:
    if is_empty_value(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return round(value, 6)

    return value


def clean_record(record: Dict[str, Any], hide_empty: bool = True) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}

    for key, value in record.items():
        clean = clean_value(value)

        if hide_empty and clean is None:
            continue

        cleaned[str(key).strip()] = clean

    return cleaned


def clean_records(records: List[Dict[str, Any]], hide_empty: bool = True) -> List[Dict[str, Any]]:
    return [clean_record(row, hide_empty=hide_empty) for row in records]

def make_success(data: Any, message: str = "success", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "success": True,
        "message": message,
        "data": data if data is not None else {},
        "meta": {
            "timestamp": now_text(),
            "service": "entity_upload_service",
            **(meta or {}),
        },
        "errors": [],
    }

def make_error(message: str, error: Optional[str] = None, data: Any = None) -> Dict[str, Any]:
    return {
        "success": False,
        "message": message,
        "data": data if data is not None else {},
        "meta": {
            "timestamp": now_text(),
            "service": "entity_upload_service",
        },
        "errors": [
            {
                "code": "entity_upload_error",
                "message": error or message,
            }
        ],
        "error": error or message,
    }


def normalize_column_name(value: Any) -> str:
    return str(value or "").strip()


def normalize_text(value: Any) -> str:
    text = safe_str(value).lower()
    text = text.replace("จังหวัด", "")
    text = text.replace(" ", "")
    return text.strip()


def generate_upload_id() -> str:
    return f"UP_{compact_now_text()}_{uuid.uuid4().hex[:8]}"


def make_hash(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        text = str(value)

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_filename(filename: str) -> str:
    text = safe_str(filename, "uploaded_entities.csv")
    bad_chars = ["<", ">", ":", '"', "/", "\\", "|", "?", "*", "&", "=", ","]

    for ch in bad_chars:
        text = text.replace(ch, "_")

    while "__" in text:
        text = text.replace("__", "_")

    return text.strip("_") or "uploaded_entities.csv"

def validate_upload_id(upload_id: str) -> Tuple[bool, str, Optional[str]]:
    safe_upload_id = safe_str(upload_id)

    if not safe_upload_id:
        return False, "", "upload_id is required"

    if safe_upload_id in {".", ".."}:
        return False, "", "invalid upload_id"

    if "/" in safe_upload_id or "\\" in safe_upload_id:
        return False, "", "invalid upload_id path separator"

    if safe_upload_id.startswith("."):
        return False, "", "invalid upload_id"

    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

    if any(ch not in allowed_chars for ch in safe_upload_id):
        return False, "", "invalid upload_id characters"

    if not safe_upload_id.startswith("UP_"):
        return False, "", "invalid upload_id prefix"

    upload_dir = (config.UPLOAD_ENTITY_DIR / safe_upload_id).resolve()
    upload_root = config.UPLOAD_ENTITY_DIR.resolve()

    try:
        upload_dir.relative_to(upload_root)
    except Exception:
        return False, "", "invalid upload_id path traversal"

    return True, safe_upload_id, None


def get_upload_result_file(upload_id: str) -> Tuple[Optional[Path], str, Optional[str]]:
    is_valid, safe_upload_id, error = validate_upload_id(upload_id)

    if not is_valid:
        return None, safe_upload_id, error

    return config.UPLOAD_ENTITY_DIR / safe_upload_id / "upload_result.json", safe_upload_id, None


def get_upload_error_report_file(upload_id: str) -> Dict[str, Any]:
    is_valid, safe_upload_id, error = validate_upload_id(upload_id)

    if not is_valid:
        return make_error(
            message="invalid upload_id",
            error=error,
            data={
                "upload_id": upload_id,
            },
        )

    path = config.UPLOAD_ERROR_REPORT_DIR / f"entity_upload_error_report_{safe_upload_id}.csv"

    return make_success(
        {
            "upload_id": safe_upload_id,
            "file_path": str(path),
            "error_report_file": str(path),
            "download_ready": path.exists() and path.is_file(),
            "exists": path.exists() and path.is_file(),
        },
        message="upload error report file resolved",
        meta={
            "upload_id": safe_upload_id,
            "file_path": str(path),
            "exists": path.exists() and path.is_file(),
        },
    )

def allowed_upload_file(filename: str) -> bool:
    if hasattr(config, "allowed_upload_file"):
        return config.allowed_upload_file(filename)

    allowed_extensions = getattr(
        config,
        "UPLOAD_ALLOWED_EXTENSIONS",
        getattr(config, "ALLOWED_UPLOAD_EXTENSIONS", {"csv"}),
    )

    suffix = safe_str(filename).lower().rsplit(".", 1)

    if len(suffix) < 2:
        return False

    return suffix[-1] in {
        safe_str(item).lower().replace(".", "")
        for item in allowed_extensions
    }

def dataframe_to_records(df: pd.DataFrame, hide_empty: bool = True) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []

    work = df.copy()
    work = work.where(pd.notnull(work), None)

    return clean_records(work.to_dict(orient="records"), hide_empty=hide_empty)


# ============================================================
# CSV READ
# ============================================================

def detect_csv_encoding(file_path: Path) -> str:
    for encoding in config.UPLOAD_CSV_ENCODING_CANDIDATES:
        try:
            pd.read_csv(file_path, encoding=encoding, nrows=5)
            return encoding
        except Exception:
            continue

    return "utf-8-sig"


def read_csv_file(file_path: Path) -> Tuple[pd.DataFrame, str, Optional[str]]:
    encoding = detect_csv_encoding(file_path)

    try:
        df = pd.read_csv(
            file_path,
            encoding=encoding,
            dtype=str,
            keep_default_na=False,
        )

        df.columns = [normalize_column_name(col) for col in df.columns]

        return df, encoding, None

    except Exception as exc:
        return pd.DataFrame(), encoding, str(exc)


def save_uploaded_file(file: UploadFile) -> Dict[str, Any]:
    original_filename = safe_filename(getattr(file, "filename", "") or "uploaded_entities.csv")
    upload_id = generate_upload_id()

    upload_dir = config.UPLOAD_ENTITY_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_file = upload_dir / original_filename

    if hasattr(file, "file") and file.file is not None:
        try:
            file.file.seek(0)
        except Exception:
            pass

        content = file.file.read()

        if isinstance(content, str):
            content = content.encode("utf-8")

        saved_file.write_bytes(content or b"")

    elif hasattr(file, "save"):
        file.save(str(saved_file))

    else:
        raise ValueError("unsupported upload file object")

    return {
        "upload_id": upload_id,
        "original_filename": original_filename,
        "saved_file": saved_file,
        "upload_dir": upload_dir,
        "uploaded_at": now_text(),
    }


# ============================================================
# COLUMN VALIDATION
# ============================================================

def get_missing_required_columns(columns: List[str]) -> List[str]:
    current = set(columns)

    return [
        col
        for col in config.ENTITY_REQUIRED_COLUMNS
        if col not in current
    ]


def get_extra_columns(columns: List[str]) -> List[str]:
    supported = set(config.ENTITY_SUPPORTED_COLUMNS)

    return [
        col
        for col in columns
        if col not in supported
    ]


def get_supported_columns_in_file(columns: List[str]) -> List[str]:
    supported = set(config.ENTITY_SUPPORTED_COLUMNS)

    return [
        col
        for col in columns
        if col in supported
    ]


def validate_csv_columns(df: pd.DataFrame) -> Dict[str, Any]:
    columns = list(df.columns)

    missing_required = get_missing_required_columns(columns)
    extra_columns = get_extra_columns(columns)
    supported_columns = get_supported_columns_in_file(columns)

    is_valid = len(missing_required) == 0

    return {
        "is_valid": is_valid,
        "columns": columns,
        "required_columns": config.ENTITY_REQUIRED_COLUMNS,
        "supported_columns": config.ENTITY_SUPPORTED_COLUMNS,
        "supported_columns_in_file": supported_columns,
        "missing_required_columns": missing_required,
        "extra_columns": extra_columns,
    }


# ============================================================
# ROW VALIDATION
# ============================================================

def is_valid_latitude(value: Any) -> bool:
    lat = safe_float(value)

    if lat is None:
        return False

    return -90 <= lat <= 90


def is_valid_longitude(value: Any) -> bool:
    lon = safe_float(value)

    if lon is None:
        return False

    return -180 <= lon <= 180


def validate_entity_row(row: Dict[str, Any], row_number: int) -> Dict[str, Any]:
    reasons: List[str] = []

    entity_id = safe_str(row.get("entity_id"))
    entity_type = safe_str(row.get("entity_type"))
    entity_name_th = safe_str(row.get("entity_name_th"))
    province_name_th = safe_str(row.get("province_name_th"))
    latitude = row.get("latitude")
    longitude = row.get("longitude")

    if not entity_id:
        reasons.append("missing entity_id")

    if not entity_type:
        reasons.append("missing entity_type")

    if not entity_name_th:
        reasons.append("missing entity_name_th")

    if not province_name_th:
        reasons.append("missing province_name_th")

    if not is_valid_latitude(latitude):
        reasons.append("invalid latitude")

    if not is_valid_longitude(longitude):
        reasons.append("invalid longitude")

    is_displayable = len(reasons) == 0

    return {
        "row_number": row_number,
        "is_displayable": is_displayable,
        "reasons": reasons,
    }

def normalize_entity_row(row: Dict[str, Any], upload_id: str, row_number: int) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}

    for col in config.ENTITY_SUPPORTED_COLUMNS:
        if col in row:
            normalized[col] = clean_value(row.get(col))

    normalized["entity_id"] = safe_str(
        normalized.get("entity_id"),
        f"entity_{upload_id}_{row_number}",
    )

    normalized["entity_type"] = safe_str(normalized.get("entity_type"), "Unknown")

    entity_name_th = safe_str(normalized.get("entity_name_th"))
    entity_name_en = safe_str(normalized.get("entity_name_en"))

    if not entity_name_th and not entity_name_en:
        normalized["entity_name_th"] = "No Name"
    elif not entity_name_th and entity_name_en:
        normalized["entity_name_th"] = entity_name_en

    normalized["province_name_th"] = safe_str(normalized.get("province_name_th"), "Unknown")
    normalized["latitude"] = safe_float(normalized.get("latitude"))
    normalized["longitude"] = safe_float(normalized.get("longitude"))

    if is_empty_value(normalized.get("risk_group")):
        normalized["risk_group"] = "Unknown"

    normalized["risk_status"] = normalize_entity_risk(normalized.get("risk_group"))
    normalized["risk_level"] = normalized["risk_status"]
    normalized["object_type"] = "entity"
    normalized["source_type"] = "uploaded_entity"
    normalized["source_group"] = "uploaded_entity"
    normalized["upload_id"] = upload_id
    normalized["upload_row_number"] = row_number
    normalized["uploaded_at"] = now_text()
    normalized["record_key"] = make_entity_record_key(normalized)

    return clean_record(normalized, hide_empty=True)

def make_entity_record_key(row: Dict[str, Any]) -> str:
    parts = [
        "uploaded_entity",
        safe_str(row.get("upload_id")),
        safe_str(row.get("entity_id")),
        safe_str(row.get("latitude")),
        safe_str(row.get("longitude")),
    ]

    return "|".join(parts)


def split_displayable_records(df: pd.DataFrame, upload_id: str) -> Dict[str, Any]:
    displayable_records: List[Dict[str, Any]] = []
    not_displayable_records: List[Dict[str, Any]] = []

    records = df.to_dict(orient="records")

    for index, row in enumerate(records, start=2):
        row = {normalize_column_name(k): v for k, v in row.items()}

        validation = validate_entity_row(row, index)

        if validation["is_displayable"]:
            normalized = normalize_entity_row(row, upload_id, index)
            displayable_records.append(normalized)
        else:
            not_displayable_records.append(
                {
                    "row_number": index,
                    "reasons": validation["reasons"],
                    "raw": clean_record(row, hide_empty=True),
                }
            )

    return {
        "displayable_records": displayable_records,
        "not_displayable_records": not_displayable_records,
    }


# ============================================================
# UPLOAD STATUS
# ============================================================

def determine_upload_status(
    column_validation: Dict[str, Any],
    displayable_count: int,
    not_displayable_count: int,
    total_rows: int,
) -> str:
    if not column_validation.get("is_valid", False):
        return config.UPLOAD_STATUS_INVALID_FILE

    if total_rows <= 0:
        return config.UPLOAD_STATUS_NO_DISPLAYABLE_RECORDS

    if displayable_count <= 0:
        return config.UPLOAD_STATUS_NO_DISPLAYABLE_RECORDS

    if not_displayable_count > 0:
        return config.UPLOAD_STATUS_PARTIAL_DATA

    return config.UPLOAD_STATUS_READY


def get_status_color(status: str) -> str:
    return config.UPLOAD_STATUS_COLORS.get(status, "gray")


# ============================================================
# SAVE RESULTS
# ============================================================

def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def save_upload_outputs(
    upload_meta: Dict[str, Any],
    column_validation: Dict[str, Any],
    status: str,
    displayable_records: List[Dict[str, Any]],
    not_displayable_records: List[Dict[str, Any]],
    encoding: str,
) -> Dict[str, Any]:
    upload_id = upload_meta["upload_id"]
    upload_dir = Path(upload_meta["upload_dir"])

    full_result_file = upload_dir / "upload_result.json"
    displayable_file = upload_dir / "displayable_records.json"
    not_displayable_file = upload_dir / "not_displayable_records.json"
    latest_entities_file = config.UPLOAD_ENTITY_DIR / "latest_entities.json"
    error_report_file = config.UPLOAD_ERROR_REPORT_DIR / f"entity_upload_error_report_{upload_id}.csv"

    result_payload = {
        "upload_id": upload_id,
        "status": status,
        "status_color": get_status_color(status),
        "original_filename": upload_meta.get("original_filename"),
        "saved_file": str(upload_meta.get("saved_file")),
        "uploaded_at": upload_meta.get("uploaded_at"),
        "encoding": encoding,
        "column_validation": column_validation,
        "summary": {
            "total_rows": len(displayable_records) + len(not_displayable_records),
            "displayable_records": len(displayable_records),
            "not_displayable_records": len(not_displayable_records),
        },
        "displayable_records": displayable_records,
        "not_displayable_records": not_displayable_records,
    }

    save_json(full_result_file, result_payload)
    save_json(displayable_file, displayable_records)
    save_json(not_displayable_file, not_displayable_records)

    if displayable_records:
        save_json(
            latest_entities_file,
            {
                "upload_id": upload_id,
                "updated_at": now_text(),
                "records": displayable_records,
            },
        )

    write_error_report_csv(error_report_file, not_displayable_records)

    log_payload = {
        "upload_id": upload_id,
        "status": status,
        "status_color": get_status_color(status),
        "original_filename": upload_meta.get("original_filename"),
        "saved_file": str(upload_meta.get("saved_file")),
        "uploaded_at": upload_meta.get("uploaded_at"),
        "encoding": encoding,
        "total_rows": len(displayable_records) + len(not_displayable_records),
        "displayable_records": len(displayable_records),
        "not_displayable_records": len(not_displayable_records),
        "missing_required_columns": column_validation.get("missing_required_columns", []),
        "result_file": str(full_result_file),
        "error_report_file": str(error_report_file),
        "created_at": now_text(),
    }

    append_jsonl(config.UPLOAD_LOG_FILE, log_payload)

    return {
        "result_file": str(full_result_file),
        "displayable_file": str(displayable_file),
        "not_displayable_file": str(not_displayable_file),
        "latest_entities_file": str(latest_entities_file),
        "error_report_file": str(error_report_file),
    }


def write_error_report_csv(path: Path, not_displayable_records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "row_number",
        "reasons",
        "entity_id",
        "entity_type",
        "entity_name_th",
        "province_name_th",
        "latitude",
        "longitude",
    ]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for item in not_displayable_records:
            raw = item.get("raw", {}) or {}

            writer.writerow(
                {
                    "row_number": item.get("row_number"),
                    "reasons": "; ".join(item.get("reasons", [])),
                    "entity_id": raw.get("entity_id"),
                    "entity_type": raw.get("entity_type"),
                    "entity_name_th": raw.get("entity_name_th"),
                    "province_name_th": raw.get("province_name_th"),
                    "latitude": raw.get("latitude"),
                    "longitude": raw.get("longitude"),
                }
            )


# ============================================================
# PUBLIC UPLOAD SERVICE
# ============================================================

def handle_entity_csv_upload(file: UploadFile) -> Dict[str, Any]:
    if file is None:
        return make_error("No file uploaded")

    filename = getattr(file, "filename", "") or ""

    if not filename:
        return make_error("No filename provided")

    if not allowed_upload_file(filename):
        allowed_extensions = getattr(
            config,
            "UPLOAD_ALLOWED_EXTENSIONS",
            getattr(config, "ALLOWED_UPLOAD_EXTENSIONS", {"csv"}),
        )

        return make_error(
            "Invalid file extension",
            data={
                "filename": filename,
                "allowed_extensions": list(allowed_extensions),
            },
        )

    try:
        upload_meta = save_uploaded_file(file)
    except Exception as exc:
        return make_error("Failed to save uploaded file", error=str(exc))

    saved_file = Path(upload_meta["saved_file"])

    df, encoding, read_error = read_csv_file(saved_file)

    if read_error:
        upload_id = upload_meta["upload_id"]

        column_validation = {
            "is_valid": False,
            "columns": [],
            "required_columns": config.ENTITY_REQUIRED_COLUMNS,
            "supported_columns": config.ENTITY_SUPPORTED_COLUMNS,
            "supported_columns_in_file": [],
            "missing_required_columns": config.ENTITY_REQUIRED_COLUMNS,
            "extra_columns": [],
            "read_error": read_error,
        }

        status = config.UPLOAD_STATUS_INVALID_FILE

        output_files = save_upload_outputs(
            upload_meta=upload_meta,
            column_validation=column_validation,
            status=status,
            displayable_records=[],
            not_displayable_records=[],
            encoding=encoding,
        )

        return make_success(
            {
                "upload_id": upload_id,
                "status": status,
                "status_color": get_status_color(status),
                "column_validation": column_validation,
                "summary": {
                    "total_rows": 0,
                    "displayable_records": 0,
                    "not_displayable_records": 0,
                },
                "displayable_records": [],
                "not_displayable_records": [],
                "output_files": output_files,
            },
            message="csv read failed",
        )

    column_validation = validate_csv_columns(df)

    if not column_validation.get("is_valid", False):
        status = config.UPLOAD_STATUS_INVALID_FILE

        not_displayable_records = [
            {
                "row_number": None,
                "reasons": [
                    f"missing required columns: {', '.join(column_validation.get('missing_required_columns', []))}"
                ],
                "raw": {},
            }
        ]

        output_files = save_upload_outputs(
            upload_meta=upload_meta,
            column_validation=column_validation,
            status=status,
            displayable_records=[],
            not_displayable_records=not_displayable_records,
            encoding=encoding,
        )

        return make_success(
            {
                "upload_id": upload_meta["upload_id"],
                "status": status,
                "status_color": get_status_color(status),
                "column_validation": column_validation,
                "summary": {
                    "total_rows": len(df),
                    "displayable_records": 0,
                    "not_displayable_records": len(df),
                },
                "displayable_records": [],
                "not_displayable_records": not_displayable_records[:config.UPLOAD_PREVIEW_LIMIT],
                "preview_limit": config.UPLOAD_PREVIEW_LIMIT,
                "output_files": output_files,
            },
            message="invalid csv columns",
        )

    split_result = split_displayable_records(df, upload_meta["upload_id"])

    displayable_records = split_result["displayable_records"]
    not_displayable_records = split_result["not_displayable_records"]

    status = determine_upload_status(
        column_validation=column_validation,
        displayable_count=len(displayable_records),
        not_displayable_count=len(not_displayable_records),
        total_rows=len(df),
    )

    output_files = save_upload_outputs(
        upload_meta=upload_meta,
        column_validation=column_validation,
        status=status,
        displayable_records=displayable_records,
        not_displayable_records=not_displayable_records,
        encoding=encoding,
    )

    response_data = {
        "upload_id": upload_meta["upload_id"],
        "status": status,
        "status_color": get_status_color(status),
        "column_validation": column_validation,
        "summary": {
            "total_rows": len(df),
            "displayable_records": len(displayable_records),
            "not_displayable_records": len(not_displayable_records),
        },
        "displayable_records": displayable_records[:config.UPLOAD_PREVIEW_LIMIT],
        "not_displayable_records": not_displayable_records[:config.UPLOAD_PREVIEW_LIMIT],
        "preview_limit": config.UPLOAD_PREVIEW_LIMIT,
        "output_files": output_files,
    }

    return make_success(response_data, message="entity csv uploaded")

def process_uploaded_entity_file(file: UploadFile) -> Dict[str, Any]:
    return handle_entity_csv_upload(file)

# ============================================================
# READ UPLOAD RESULTS
# ============================================================
def read_latest_entities() -> Dict[str, Any]:
    path = config.UPLOAD_ENTITY_DIR / "latest_entities.json"

    if not path.exists():
        return make_success(
            {
                "upload_id": None,
                "updated_at": None,
                "records": [],
                "policy": {
                    "latest_file_exists": False,
                    "retained_previous_layer": False,
                    "latest_entities_update_policy": "latest_entities.json is updated only when an upload has displayable records.",
                },
            },
            message="no latest uploaded entities",
            meta={
                "upload_id": None,
                "updated_at": None,
                "total": 0,
                "total_raw_records": 0,
                "total_displayable_records": 0,
                "latest_file_exists": False,
                "retained_previous_layer": False,
            },
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        if not isinstance(payload, dict):
            payload = {
                "upload_id": None,
                "updated_at": None,
                "records": [],
            }

        records = payload.get("records", [])
        if not isinstance(records, list):
            records = []

        payload.setdefault("upload_id", None)
        payload.setdefault("updated_at", None)
        payload["records"] = records
        payload["policy"] = {
            "latest_file_exists": True,
            "retained_previous_layer": True,
            "latest_entities_update_policy": "latest_entities.json is updated only when an upload has displayable records.",
        }

        return make_success(
            payload,
            message="latest uploaded entities loaded",
            meta={
                "upload_id": payload.get("upload_id"),
                "updated_at": payload.get("updated_at"),
                "total": len(records),
                "total_raw_records": len(records),
                "total_displayable_records": len(records),
                "latest_file_exists": True,
                "retained_previous_layer": True,
            },
        )

    except Exception as exc:
        return make_error("failed to read latest uploaded entities", error=str(exc))

def get_upload_logs(context: Optional[Dict[str, Any]] = None, limit: int = 100) -> Dict[str, Any]:
    if isinstance(context, dict):
        limit = safe_int(context.get("limit") or context.get("page_size"), limit) or limit

    return read_upload_logs(limit=limit)


def get_upload_result(upload_id: str) -> Dict[str, Any]:
    return read_upload_result(upload_id)


def get_upload_displayable_records(
    upload_id: str,
    context: Optional[Dict[str, Any]] = None,
    limit: int = 100,
    offset: int = 0,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    if isinstance(context, dict):
        limit = safe_int(context.get("limit") or context.get("page_size"), limit) or limit
        offset = safe_int(context.get("offset"), offset) or offset
        query = query or context.get("query") or context.get("search")

    return read_displayable_records(
        upload_id=upload_id,
        limit=limit,
        offset=offset,
        query=query,
    )


def get_upload_not_displayable_records(
    upload_id: str,
    context: Optional[Dict[str, Any]] = None,
    limit: int = 100,
    offset: int = 0,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    if isinstance(context, dict):
        limit = safe_int(context.get("limit") or context.get("page_size"), limit) or limit
        offset = safe_int(context.get("offset"), offset) or offset
        query = query or context.get("query") or context.get("search")

    return read_not_displayable_records(
        upload_id=upload_id,
        limit=limit,
        offset=offset,
        query=query,
    )

def read_upload_logs(limit: int = 100) -> Dict[str, Any]:
    path = config.UPLOAD_LOG_FILE

    if not path.exists():
        return make_success([], message="no upload logs", meta={"total": 0})

    logs: List[Dict[str, Any]] = []

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                text = line.strip()

                if not text:
                    continue

                try:
                    logs.append(json.loads(text))
                except Exception:
                    continue

        logs = list(reversed(logs))

        safe_limit = max(1, min(safe_int(limit, 100) or 100, 1000))

        return make_success(
            logs[:safe_limit],
            message="upload logs loaded",
            meta={
                "total": len(logs),
                "returned": min(len(logs), safe_limit),
            },
        )

    except Exception as exc:
        return make_error("failed to read upload logs", error=str(exc))


def read_upload_result(upload_id: str) -> Dict[str, Any]:
    path, safe_upload_id, error = get_upload_result_file(upload_id)

    if error:
        return make_error(
            message="invalid upload_id",
            error=error,
            data={
                "upload_id": upload_id,
            },
        )

    if path is None or not path.exists():
        return make_error(
            "upload result not found",
            data={
                "upload_id": safe_upload_id,
                "expected_file": str(path) if path else None,
            },
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        return make_success(payload, message="upload result loaded")

    except Exception as exc:
        return make_error("failed to read upload result", error=str(exc))


def read_displayable_records(
    upload_id: str,
    limit: int = 100,
    offset: int = 0,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    is_valid, safe_upload_id, error = validate_upload_id(upload_id)

    if not is_valid:
        return make_error(
            message="invalid upload_id",
            error=error,
            data={
                "upload_id": safe_upload_id,
            },
        )

    result = read_upload_result(safe_upload_id)

    if not result.get("success"):
        return result

    records = result.get("data", {}).get("displayable_records", [])

    filtered = filter_records_by_query(records, query)

    safe_offset = max(safe_int(offset, 0) or 0, 0)
    safe_limit = max(1, min(safe_int(limit, config.UPLOAD_DISPLAY_PAGE_SIZE) or config.UPLOAD_DISPLAY_PAGE_SIZE, 1000))

    page = filtered[safe_offset:safe_offset + safe_limit]

    return make_success(
        page,
        message="displayable records loaded",
        meta={
            "upload_id": safe_upload_id,
            "total": len(filtered),
            "returned": len(page),
            "limit": safe_limit,
            "offset": safe_offset,
        },
    )


def read_not_displayable_records(
    upload_id: str,
    limit: int = 100,
    offset: int = 0,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    is_valid, safe_upload_id, error = validate_upload_id(upload_id)

    if not is_valid:
        return make_error(
            message="invalid upload_id",
            error=error,
            data={
                "upload_id": safe_upload_id,
            },
        )

    result = read_upload_result(safe_upload_id)

    if not result.get("success"):
        return result

    records = result.get("data", {}).get("not_displayable_records", [])

    filtered = filter_records_by_query(records, query)

    safe_offset = max(safe_int(offset, 0) or 0, 0)
    safe_limit = max(1, min(safe_int(limit, config.UPLOAD_DISPLAY_PAGE_SIZE) or config.UPLOAD_DISPLAY_PAGE_SIZE, 1000))

    page = filtered[safe_offset:safe_offset + safe_limit]

    return make_success(
        page,
        message="not displayable records loaded",
        meta={
            "upload_id": safe_upload_id,
            "total": len(filtered),
            "returned": len(page),
            "limit": safe_limit,
            "offset": safe_offset,
        },
    )


def filter_records_by_query(records: List[Dict[str, Any]], query: Optional[str]) -> List[Dict[str, Any]]:
    q = safe_str(query).lower()

    if not q:
        return records

    result: List[Dict[str, Any]] = []

    for row in records:
        text = json.dumps(row, ensure_ascii=False, default=str).lower()

        if q in text:
            result.append(row)

    return result


def normalize_entity_risk(value: Any) -> str:
    text = safe_str(value)

    if not text:
        return "Unknown"

    key = text.strip().lower()

    mapping = {
        "normal": "Normal",
        "ปกติ": "Normal",
        "1.ปกติ": "Normal",

        "watch": "Watch",
        "เฝ้าระวัง": "Watch",
        "2.เฝ้าระวัง": "Watch",
        "น้อย": "Watch",

        "warning": "Warning",
        "เตือนภัย": "Warning",
        "เตือน": "Warning",
        "3.เตือนภัย": "Warning",
        "มาก": "Warning",

        "critical": "Critical",
        "วิกฤต": "Critical",
        "4.วิกฤต": "Critical",
        "น้อยวิกฤต": "Critical",

        "unknown": "Unknown",
        "ไม่ทราบ": "Unknown",
        "ไม่มีข้อมูล": "Unknown",
    }

    if hasattr(config, "PREDICTION_RISK_NORMALIZE_MAP"):
        mapping.update(
            {
                str(k).strip().lower(): v
                for k, v in config.PREDICTION_RISK_NORMALIZE_MAP.items()
            }
        )

    return mapping.get(key, text if text in getattr(config, "RISK_LEVELS", []) else "Unknown")


def filter_records_by_province(records: List[Dict[str, Any]], province: Optional[str]) -> List[Dict[str, Any]]:
    target = normalize_text(province)

    if not target or target in {"all", "allprovince", "allprovinces"}:
        return records

    result: List[Dict[str, Any]] = []

    for row in records:
        values = [
            row.get("province_name_th"),
            row.get("province_name_en"),
            row.get("province"),
            row.get("province_model"),
        ]

        if any(normalize_text(value) == target for value in values):
            result.append(row)

    return result


def filter_records_by_risk(records: List[Dict[str, Any]], risk_level: Optional[str]) -> List[Dict[str, Any]]:
    if not risk_level or str(risk_level).strip().lower() in {"all", "all risk"}:
        return records

    target = normalize_entity_risk(risk_level)

    result: List[Dict[str, Any]] = []

    for row in records:
        row_risk = normalize_entity_risk(
            row.get("risk_status")
            or row.get("risk_level")
            or row.get("risk_group")
            or row.get("status")
        )

        if row_risk.lower() == target.lower():
            result.append(row)

    return result


# ============================================================
# TABLE RECORD SUPPORT
# ============================================================

def get_entity_display_name(row: Dict[str, Any]) -> str:
    return safe_str(
        row.get("entity_name_display")
        or row.get("entity_name_th")
        or row.get("entity_name_en")
        or row.get("name")
        or row.get("entity_id")
        or "No Name",
        "No Name",
    )


def get_entity_display_type(row: Dict[str, Any]) -> str:
    return safe_str(
        row.get("entity_type_display")
        or row.get("entity_type")
        or row.get("object_type")
        or row.get("type")
        or "Unknown",
        "Unknown",
    )


def get_entity_display_province(row: Dict[str, Any]) -> str:
    return safe_str(
        row.get("province_display")
        or row.get("province_name_th")
        or row.get("province_name_en")
        or row.get("province")
        or row.get("province_model")
        or "Unknown",
        "Unknown",
    )


def get_entity_display_risk(row: Dict[str, Any]) -> str:
    return normalize_entity_risk(
        row.get("risk_display")
        or row.get("risk_status")
        or row.get("risk_level")
        or row.get("risk_group")
        or row.get("status")
    )


def get_entity_display_updated_at(row: Dict[str, Any]) -> Optional[Any]:
    return (
        row.get("updated_display")
        or row.get("updated_at")
        or row.get("uploaded_at")
        or row.get("created_at")
    )


def normalize_entity_table_record(row: Dict[str, Any]) -> Dict[str, Any]:
    record = clean_record(row, hide_empty=True)

    name_display = get_entity_display_name(record)
    type_display = get_entity_display_type(record)
    province_display = get_entity_display_province(record)
    risk_display = get_entity_display_risk(record)
    updated_display = get_entity_display_updated_at(record)

    record["entity_name_display"] = name_display
    record["entity_type_display"] = type_display
    record["province_display"] = province_display
    record["risk_display"] = risk_display
    record["updated_display"] = clean_value(updated_display)

    record["entity_name_th"] = safe_str(
        record.get("entity_name_th") or name_display,
        name_display,
    )
    record["entity_type"] = safe_str(
        record.get("entity_type") or type_display,
        type_display,
    )
    record["province_name_th"] = safe_str(
        record.get("province_name_th") or province_display,
        province_display,
    )

    record["risk_status"] = risk_display
    record["risk_level"] = risk_display
    record["risk_group"] = risk_display
    record["object_type"] = safe_str(record.get("object_type"), "entity")
    record["source_group"] = safe_str(record.get("source_group"), "uploaded_entity")

    if is_empty_value(record.get("record_key")):
        record["record_key"] = make_entity_record_key(record)

    return clean_record(record, hide_empty=True)


def normalize_entity_table_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        normalize_entity_table_record(row)
        for row in records
        if isinstance(row, dict)
    ]


def paginate_records(
    records: List[Dict[str, Any]],
    limit: Optional[int] = None,
    offset: int = 0,
    default_limit: int = 5000,
    max_limit: int = 20000,
) -> Tuple[List[Dict[str, Any]], int, Optional[int]]:
    safe_offset = max(safe_int(offset, 0) or 0, 0)

    if limit is None:
        return records[safe_offset:], safe_offset, None

    safe_limit = max(1, min(safe_int(limit, default_limit) or default_limit, max_limit))
    return records[safe_offset:safe_offset + safe_limit], safe_offset, safe_limit

def get_latest_entity_records(
    province: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    query: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    latest_result = read_latest_entities()

    if not latest_result.get("success"):
        return latest_result

    payload = latest_result.get("data", {}) or {}
    records = payload.get("records", []) if isinstance(payload, dict) else []

    if not isinstance(records, list):
        records = []

    if isinstance(context, dict):
        filters = context.get("filters", {}) if isinstance(context.get("filters"), dict) else {}
        province = province or filters.get("province") or filters.get("province_name_th") or context.get("province")
        risk_level = risk_level or filters.get("risk_level") or filters.get("risk") or filters.get("risk_group") or context.get("risk_level")
        query = query or context.get("query") or context.get("search")
        limit = limit if limit is not None else context.get("limit") or context.get("page_size")
        offset = offset or context.get("offset") or 0

    normalized_records = normalize_entity_table_records(records)

    filtered = filter_records_by_query(normalized_records, query)
    filtered = filter_records_by_province(filtered, province)
    filtered = filter_records_by_risk(filtered, risk_level)

    page, safe_offset, safe_limit = paginate_records(
        filtered,
        limit=limit,
        offset=offset,
        default_limit=5000,
        max_limit=20000,
    )

    map_features = [
        feature
        for feature in [
            entity_record_to_map_feature(row)
            for row in filtered
        ]
        if feature is not None
    ]

    return make_success(
        page,
        message="latest entity table records loaded",
        meta={
            "upload_id": payload.get("upload_id"),
            "updated_at": payload.get("updated_at"),
            "total_raw_records": len(records),
            "total_displayable_records": len(normalized_records),
            "total_after_filter": len(filtered),
            "map_features": len(map_features),
            "returned": len(page),
            "offset": safe_offset,
            "limit": safe_limit,
            "province": province or "All",
            "risk_level": risk_level or "All",
            "query": query,
            "policy": {
                "latest_file_exists": True,
                "retained_previous_layer": True,
                "latest_entities_update_policy": "latest_entities.json is updated only when an upload has displayable records.",
            },
        },
    )

def get_entity_detail(
    entity_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    target = safe_str(entity_id).lower()

    latest_result = get_latest_entity_records(
        limit=None,
        offset=0,
        context=context,
    )

    if not latest_result.get("success"):
        return latest_result

    records = latest_result.get("data", []) or []

    matched = [
        row
        for row in records
        if target
        and target in " ".join(
            [
                safe_str(row.get("entity_id")),
                safe_str(row.get("record_key")),
                safe_str(row.get("entity_name_th")),
                safe_str(row.get("entity_name_en")),
                safe_str(row.get("entity_name_display")),
            ]
        ).lower()
    ]

    return make_success(
        {
            "entity_id": entity_id,
            "found": len(matched) > 0,
            "record": matched[0] if matched else None,
            "records": matched,
            "total": len(matched),
        },
        message="entity detail loaded",
        meta={
            "entity_id": entity_id,
            "found": len(matched) > 0,
            "total": len(matched),
        },
    )

# ============================================================
# MAP FEATURE SUPPORT
# ============================================================

def entity_record_to_map_feature(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    row = normalize_entity_table_record(row)

    lat = safe_float(row.get("latitude"))
    lon = safe_float(row.get("longitude"))

    if lat is None or lon is None:
        return None

    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return None

    name = get_entity_display_name(row)
    province = get_entity_display_province(row)
    risk_status = get_entity_display_risk(row)

    properties = clean_record(row, hide_empty=True)
    properties["object_type"] = "entity"
    properties["source_type"] = "uploaded_entity"
    properties["feature_type"] = "entity"
    properties["entity_id"] = row.get("entity_id")
    properties["entity_type"] = row.get("entity_type")
    properties["entity_name_th"] = row.get("entity_name_th")
    properties["province_name_th"] = row.get("province_name_th")
    properties["risk_group"] = risk_status
    properties["risk_status"] = risk_status
    properties["risk_level"] = risk_status
    properties["latitude"] = lat
    properties["longitude"] = lon
    properties["entity_name_display"] = name
    properties["entity_type_display"] = get_entity_display_type(row)
    properties["province_display"] = province
    properties["risk_display"] = risk_status
    properties["updated_display"] = clean_value(get_entity_display_updated_at(row))
    properties["marker_color"] = row.get("marker_color")
    properties["marker_size"] = row.get("marker_size", 10)

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": properties,
    }

def get_latest_entity_map_features(
    province: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    query: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    records_result = get_latest_entity_records(
        province=province,
        risk_level=risk_level,
        limit=None,
        offset=0,
        query=query,
    )

    if not records_result.get("success"):
        return records_result

    records = records_result.get("data", []) or []
    records_meta = records_result.get("meta", {}) or {}

    features = [
        feature
        for feature in [
            entity_record_to_map_feature(row)
            for row in records
        ]
        if feature is not None
    ]

    page, safe_offset, safe_limit = paginate_records(
        features,
        limit=limit,
        offset=offset,
        default_limit=5000,
        max_limit=20000,
    )

    feature_collection = {
        "type": "FeatureCollection",
        "features": page,
        "total": len(features),
        "returned": len(page),
        "offset": safe_offset,
        "limit": safe_limit,
    }

    return make_success(
        feature_collection,
        message="latest entity map features loaded",
        meta={
            "upload_id": records_meta.get("upload_id"),
            "updated_at": records_meta.get("updated_at"),
            "total_raw_records": records_meta.get("total_raw_records", 0),
            "total_displayable_records": records_meta.get("total_displayable_records", 0),
            "total_after_filter": records_meta.get("total_after_filter", len(records)),
            "map_features": len(features),
            "total": len(features),
            "returned": len(page),
            "offset": safe_offset,
            "limit": safe_limit,
            "province": province or "All",
            "risk_level": risk_level or "All",
            "query": query,
            "policy": records_meta.get("policy", {}),
        },
    )

# ============================================================
# CLEAR UPLOAD
# ============================================================

def clear_latest_uploaded_entities() -> Dict[str, Any]:
    latest_file = config.UPLOAD_ENTITY_DIR / "latest_entities.json"

    if latest_file.exists():
        latest_file.unlink()

    log_payload = {
        "upload_id": None,
        "status": "Cleared",
        "status_color": "gray",
        "original_filename": None,
        "saved_file": None,
        "uploaded_at": None,
        "total_rows": 0,
        "displayable_records": 0,
        "not_displayable_records": 0,
        "created_at": now_text(),
    }

    append_jsonl(config.UPLOAD_LOG_FILE, log_payload)

    return make_success(
        {
            "cleared": True,
            "latest_entities_file": str(latest_file),
        },
        message="latest uploaded entity layer cleared",
    )

def clear_latest_entities() -> Dict[str, Any]:
    return clear_latest_uploaded_entities()