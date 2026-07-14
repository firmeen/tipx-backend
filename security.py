# ============================================================
# FILE: backend/security.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 6 / 20
# ============================================================

"""
backend/security.py

ไฟล์นี้เป็นศูนย์กลาง Security / Masking / Token / Package Access ของระบบ TIPX

หน้าที่หลัก:
1. จัดการการ mask ข้อมูลอ่อนไหวก่อนส่งออก package
2. mask Tax ID
3. mask Director Name
4. mask Address
5. ซ่อน financial fields ตาม policy ของ package
6. สร้าง package access token
7. verify package access token
8. สร้าง checksum สำหรับ package snapshot
9. sanitize payload ก่อนส่งให้ external viewer
10. ตรวจ package access scope
11. สร้าง public package URL metadata
12. เตรียมระบบ read-only สำหรับ external viewer

โครงสร้างระบบที่ไฟล์นี้รองรับ:
- Package Export
- External Viewer Package
- Public Package API
- Dashboard Sharing
- Data Masking
- Access Token
- Package Integrity
- Read-only External Snapshot

หมายเหตุสำคัญ:
ระบบ TIPX เวอร์ชันนี้เป็น local/internal dashboard เป็นหลัก
แต่มีการเตรียม security layer สำหรับการ export package ให้คนนอกดู
โดย external viewer ควรอ่านเฉพาะ snapshot JSON ที่ generate แล้วเท่านั้น
ไม่ควรเข้าถึง raw internal cache หรือ raw input file โดยตรง
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import quote

try:
    from config import (
        APP_SHORT_NAME,
        APP_VERSION,
        SECRET_KEY,
        PACKAGE_TOKEN_SALT,
        ENABLE_PACKAGE_ACCESS_TOKEN,
        PUBLIC_PACKAGE_READ_ONLY,
        MASK_TAX_ID_VISIBLE_LAST_DIGITS,
        MASK_DIRECTOR_VISIBLE_FIRST_CHARS,
        PACKAGE_SECURITY_OPTIONS,
        PACKAGE_DEFAULT_EXPIRE_DAYS,
        PACKAGE_MAX_EXPIRE_DAYS,
    )
    CONFIG_LOADED = True
except Exception as e:
    CONFIG_LOADED = False
    CONFIG_ERROR = str(e)
    APP_SHORT_NAME = "TIPX"
    APP_VERSION = "unknown"
    SECRET_KEY = "tipx-local-security-fallback"
    PACKAGE_TOKEN_SALT = "tipx-package-token"
    ENABLE_PACKAGE_ACCESS_TOKEN = True
    PUBLIC_PACKAGE_READ_ONLY = True
    MASK_TAX_ID_VISIBLE_LAST_DIGITS = 4
    MASK_DIRECTOR_VISIBLE_FIRST_CHARS = 1
    PACKAGE_SECURITY_OPTIONS = {
        "mask_tax_id": True,
        "mask_director_name": True,
        "mask_person_name": True,
        "mask_address": True,
        "hide_financial_fields": False,
        "remove_internal_paths": True,
        "remove_debug_fields": True,
        "public": True,
    }
    PACKAGE_DEFAULT_EXPIRE_DAYS = 30
    PACKAGE_MAX_EXPIRE_DAYS = 365

try:
    from utils import (
        clean_text,
        clean_text_lower,
        is_empty_value,
        mask_tax_id,
        normalize_tax_id,
        now_iso,
        to_jsonable,
        to_bool,
        to_int,
        write_json,
        read_json,
        make_hash_id,
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
        if isinstance(value, str) and value.strip() in {"", "-", "N/A", "n/a", "None", "none", "null", "nan", "NaN"}:
            return True
        if isinstance(value, float) and value != value:
            return True
        return False

    def normalize_tax_id(value: Any) -> str:
        return "".join(ch for ch in clean_text(value) if ch.isdigit())

    def now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def to_jsonable(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return None if value != value else value
        if isinstance(value, (datetime, Path)):
            return value.isoformat() if isinstance(value, datetime) else str(value)
        if isinstance(value, dict):
            return {str(k): to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [to_jsonable(item) for item in value]
        if hasattr(value, "to_dict"):
            try:
                return to_jsonable(value.to_dict("records"))
            except Exception:
                try:
                    return to_jsonable(value.to_dict())
                except Exception:
                    pass
        return clean_text(value)

    def to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if is_empty_value(value):
            return default
        return clean_text_lower(value) in {"1", "true", "yes", "y", "on"}

    def to_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(clean_text(value)))
        except Exception:
            return default

    def write_json(path: Any, data: Any, **kwargs: Any) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(to_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def read_json(path: Any, default: Any = None) -> Any:
        try:
            target = Path(path)
            if not target.exists():
                return default
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return default

    def make_hash_id(*parts: Any, length: int = 12) -> str:
        text = "|".join(clean_text(part) for part in parts)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[: max(6, int(length or 12))]

    def mask_tax_id(value: Any, visible_last: int = 4) -> str:
        digits = normalize_tax_id(value)
        if not digits:
            return ""
        visible = max(0, min(len(digits), int(visible_last or 0)))
        if len(digits) <= visible:
            return "*" * len(digits) if digits else "***"
        return "*" * (len(digits) - visible) + digits[-visible:]


# ============================================================
# 1) SECURITY CONSTANTS
# ============================================================

SENSITIVE_FIELD_GROUPS: Dict[str, List[str]] = {
    "tax_id": [
        "tax_id",
        "tax_id_raw",
        "tax_id_norm",
        "taxid",
        "Tax Id",
        "Tax ID",
        "เลขประจำตัวผู้เสียภาษี",
        "เลขทะเบียนนิติบุคคล",
    ],
    "director_name": [
        "director_name",
        "director_name_norm",
        "boardlist",
        "กรรมการ",
        "รายชื่อกรรมการ",
    ],
    "address": [
        "address",
        "Address",
        "ที่อยู่",
        "company_address",
        "full_address",
    ],
    "financial": [
        "premium",
        "loss",
        "suminsure",
        "noofpol",
        "total_premium",
        "total_loss",
        "total_suminsure",
        "total_noofpol",
        "loss_ratio",
        "loss_ratio_band",
        "most_recent_asset_val",
        "most_recent_income_val",
        "registered_capital",
        "total_connected_income",
        "total_connected_capital",
        "total_connected_premium",
        "total_connected_suminsure",
    ],
    "location_precise": [
        "lat",
        "lon",
        "latitude",
        "longitude",
        "company_lat",
        "company_lon",
    ],
}

PUBLIC_ALLOWED_PACKAGE_COMPONENTS: List[str] = [
    "summary",
    "companies",
    "policy_summary",
    "policy_table",
    "linkage_graph",
    "linkage_lines",
    "flood_summary",
    "map_layers",
    "map",
    "charts",
    "tables",
    "data_quality",
    "prediction",
    "flood_prediction",
    "flood_prediction_latest",
    "flood_prediction_map",
    "entity",
    "uploaded_entity",
    "uploaded_entity_latest",
    "filter_options",
]

PUBLIC_FORBIDDEN_INTERNAL_KEYS: List[str] = [
    "raw_file_path",
    "source_file",
    "source_file_path",
    "internal_path",
    "cache_path",
    "cache_file",
    "local_path",
    "absolute_path",
    "file_path",
    "source_path",
    "export_path",
    "zip_path",
    "download_path",
    "package_path",
    "package_dir",
    "viewer_dir",
    "index_path",
    "data_path",
    "assets_dir",
    "upload_dir",
    "saved_file",
    "error_report_file",
    "debug_traceback",
    "traceback",
    "exception",
    "raw_record",
    "raw_records",
    "raw_row",
    "raw_rows",
    "raw_payload",
    "raw_sheet",
    "raw_sheet_name",
    "not_displayable",
    "not_displayable_records",
    "invalid_records",
    "invalid_rows",
    "password",
    "secret",
    "token",
    "access_token",
    "token_secret",
    "package_token_salt",
    "secret_key",
    "private_key",
    "checksum_raw",
]

PACKAGE_STATUS_VALUES: List[str] = [
    "active",
    "disabled",
    "expired",
    "deleted",
]


TOKEN_VERSION: str = "v1"


# ============================================================
# 2) BASIC HASH / SIGNATURE HELPERS
# ============================================================

def get_security_secret() -> bytes:
    """
    คืน secret key ในรูป bytes

    ใช้สำหรับ:
    - sign token
    - verify token
    - checksum บางส่วน
    """

    secret = f"{SECRET_KEY}:{PACKAGE_TOKEN_SALT}:{APP_SHORT_NAME}:{APP_VERSION}"
    return secret.encode("utf-8")


def sha256_text(value: Any) -> str:
    """
    สร้าง SHA256 hash จากข้อความ
    """

    text = clean_text(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_payload(payload: Any) -> str:
    """
    สร้าง SHA256 hash จาก payload JSON
    """

    payload_json = json.dumps(
        to_jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def hmac_signature(message: str) -> str:
    """
    สร้าง HMAC signature จาก message
    """

    return hmac.new(
        get_security_secret(),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    """
    compare string แบบ constant-time
    """

    return hmac.compare_digest(str(a), str(b))


def random_token(length: int = 32) -> str:
    """
    สร้าง random token
    """

    length = max(16, int(length))
    return secrets.token_urlsafe(length)


# ============================================================
# 3) BASE64 URL HELPERS
# ============================================================

def b64url_encode(data: Union[str, bytes, Dict[str, Any]]) -> str:
    """
    encode เป็น base64 url-safe string
    """

    if isinstance(data, dict):
        raw = json.dumps(
            to_jsonable(data),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    elif isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = data

    encoded = base64.urlsafe_b64encode(raw).decode("utf-8")
    return encoded.rstrip("=")


def b64url_decode(value: str) -> bytes:
    """
    decode base64 url-safe string
    """

    text = clean_text(value)
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("utf-8"))


def b64url_decode_json(value: str) -> Dict[str, Any]:
    """
    decode base64 url-safe string เป็น JSON dict
    """

    raw = b64url_decode(value)

    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ============================================================
# 4) MASKING HELPERS
# ============================================================

def mask_string_keep_edges(
    value: Any,
    visible_start: int = 0,
    visible_end: int = 0,
    mask_char: str = "*",
    empty_value: str = "",
) -> str:
    """
    mask string โดยเก็บตัวอักษรต้น/ท้ายไว้บางส่วน

    ตัวอย่าง:
    value = "บริษัทตัวอย่าง"
    visible_start = 2
    visible_end = 0
    result = "บร**********"
    """

    text = clean_text(value)

    if not text:
        return empty_value

    visible_start = max(0, int(visible_start))
    visible_end = max(0, int(visible_end))

    if visible_start + visible_end >= len(text):
        return text

    start = text[:visible_start] if visible_start else ""
    end = text[-visible_end:] if visible_end else ""
    middle_len = len(text) - visible_start - visible_end

    return f"{start}{mask_char * middle_len}{end}"


def mask_director_name(
    value: Any,
    visible_first_chars: int = MASK_DIRECTOR_VISIBLE_FIRST_CHARS,
) -> str:
    """
    mask ชื่อกรรมการ

    ค่า default:
    - แสดง 2 ตัวแรก
    - ที่เหลือเป็น *
    """

    return mask_string_keep_edges(
        value,
        visible_start=visible_first_chars,
        visible_end=0,
        mask_char="*",
    )


def mask_address(value: Any) -> str:
    """
    mask ที่อยู่

    ไม่แสดงรายละเอียดที่อยู่เต็ม
    """

    text = clean_text(value)

    if not text:
        return ""

    return "[masked address]"


def mask_financial_value(value: Any) -> Optional[Any]:
    """
    ซ่อนค่าทางการเงิน
    """

    if is_empty_value(value):
        return None

    return None


def is_tax_id_field(field_name: Any) -> bool:
    """
    ตรวจว่า field เป็นกลุ่ม tax id หรือไม่
    """

    name = clean_text_lower(field_name)
    return name in {clean_text_lower(f) for f in SENSITIVE_FIELD_GROUPS["tax_id"]}


def is_director_field(field_name: Any) -> bool:
    """
    ตรวจว่า field เป็นกลุ่ม director หรือไม่
    """

    name = clean_text_lower(field_name)
    return name in {clean_text_lower(f) for f in SENSITIVE_FIELD_GROUPS["director_name"]}


def is_address_field(field_name: Any) -> bool:
    """
    ตรวจว่า field เป็นกลุ่ม address หรือไม่
    """

    name = clean_text_lower(field_name)
    return name in {clean_text_lower(f) for f in SENSITIVE_FIELD_GROUPS["address"]}


def is_financial_field(field_name: Any) -> bool:
    """
    ตรวจว่า field เป็นกลุ่ม financial หรือไม่
    """

    name = clean_text_lower(field_name)
    return name in {clean_text_lower(f) for f in SENSITIVE_FIELD_GROUPS["financial"]}


def is_precise_location_field(field_name: Any) -> bool:
    """
    ตรวจว่า field เป็นพิกัดละเอียดหรือไม่
    """

    name = clean_text_lower(field_name)
    return name in {clean_text_lower(f) for f in SENSITIVE_FIELD_GROUPS["location_precise"]}


def normalize_security_options(options: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
    """
    normalize package security options

    ถ้าไม่ได้ส่งมา ใช้ค่า default จาก config
    """

    base = dict(PACKAGE_SECURITY_OPTIONS)
    incoming = options or {}

    for key in base.keys():
        if key in incoming:
            base[key] = bool(to_bool(incoming.get(key), default=base[key]))

    return base


def mask_record(
    record: Dict[str, Any],
    security_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    mask record 1 แถว ตาม security options

    Options:
    - mask_tax_id
    - mask_director_name
    - mask_address
    - hide_financial_fields
    - allow_external_filter
    - include_data_quality
    """

    options = normalize_security_options(security_options)
    result = deepcopy(record)

    for key, value in list(result.items()):
        if options.get("mask_tax_id") and is_tax_id_field(key):
            result[key] = mask_tax_id(
                value,
                visible_last_digits=MASK_TAX_ID_VISIBLE_LAST_DIGITS,
            )

        elif options.get("mask_director_name") and is_director_field(key):
            if key == "boardlist" and isinstance(value, str):
                names = [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
                result[key] = ", ".join(mask_director_name(name) for name in names)
            else:
                result[key] = mask_director_name(value)

        elif options.get("mask_address") and is_address_field(key):
            result[key] = mask_address(value)

        elif options.get("hide_financial_fields") and is_financial_field(key):
            result[key] = mask_financial_value(value)

    return result


def mask_records(
    records: List[Dict[str, Any]],
    security_options: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    mask records หลายแถว
    """

    return [
        mask_record(record, security_options=security_options)
        for record in records
        if isinstance(record, dict)
    ]


def mask_nested_payload(
    payload: Any,
    security_options: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    mask payload แบบ nested

    รองรับ:
    - dict
    - list
    - primitive
    """

    options = normalize_security_options(security_options)

    if isinstance(payload, list):
        return [
            mask_nested_payload(item, security_options=options)
            for item in payload
        ]

    if isinstance(payload, dict):
        masked = {}

        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                masked[key] = mask_nested_payload(value, security_options=options)
            else:
                masked[key] = mask_record({key: value}, security_options=options).get(key)

        return masked

    return payload


# ============================================================
# 5) SANITIZE INTERNAL PAYLOAD
# ============================================================

def remove_internal_keys(payload: Any) -> Any:
    if isinstance(payload, list):
        return [
            item
            for item in (remove_internal_keys(item) for item in payload)
            if item not in ({}, [], "", None)
        ]

    if isinstance(payload, dict):
        result: Dict[str, Any] = {}

        for key, value in payload.items():
            if should_remove_public_key(key):
                continue

            if _looks_like_local_path(value):
                continue

            result[key] = remove_internal_keys(value)

        return result

    if _looks_like_local_path(payload):
        return ""

    return payload


def sanitize_public_payload(
    payload: Any,
    security_options: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    sanitize payload สำหรับ public package

    ขั้นตอน:
    1. ลบ internal keys
    2. mask nested payload
    3. แปลงเป็น JSON safe
    """

    cleaned = remove_internal_keys(payload)
    masked = mask_nested_payload(cleaned, security_options=security_options)
    return to_jsonable(masked)


def sanitize_package_components(components: Optional[List[str]]) -> List[str]:
    """
    sanitize component list สำหรับ package

    เอาเฉพาะ component ที่ public allowed
    """

    if not components:
        return list(PUBLIC_ALLOWED_PACKAGE_COMPONENTS)

    result: List[str] = []

    for component in components:
        item = clean_text(component)

        if not item:
            continue

        if item in PUBLIC_ALLOWED_PACKAGE_COMPONENTS and item not in result:
            result.append(item)

    return result


def sanitize_package_filters(filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    sanitize filter payload ที่บันทึกไปใน package

    ไม่ควรมีข้อมูลภายใน เช่น path หรือ token
    """

    if not isinstance(filters, dict):
        return {}

    return remove_internal_keys(filters)


# ============================================================
# 6) PACKAGE ACCESS TOKEN
# ============================================================

def build_token_payload(
    package_id: str,
    expire_at: Optional[str] = None,
    scope: Optional[List[str]] = None,
    read_only: bool = True,
) -> Dict[str, Any]:
    """
    สร้าง payload สำหรับ token
    """

    package_id = clean_text(package_id)

    if not expire_at:
        expire_at_dt = datetime.now() + timedelta(days=PACKAGE_DEFAULT_EXPIRE_DAYS)
        expire_at = expire_at_dt.isoformat(timespec="seconds")

    return {
        "version": TOKEN_VERSION,
        "package_id": package_id,
        "scope": scope or ["read"],
        "read_only": bool(read_only),
        "issued_at": now_iso(),
        "expire_at": expire_at,
        "nonce": random_token(16),
    }


def encode_access_token(payload: Dict[str, Any]) -> str:
    """
    encode access token

    Format:
    payload_base64.signature
    """

    payload_b64 = b64url_encode(payload)
    signature = hmac_signature(payload_b64)
    return f"{payload_b64}.{signature}"


def generate_package_access_token(
    package_id: str,
    expire_days: Optional[int] = None,
    scope: Optional[List[str]] = None,
    read_only: bool = True,
) -> str:
    """
    สร้าง access token สำหรับ package

    ถ้า ENABLE_PACKAGE_ACCESS_TOKEN = False
    token อาจไม่จำเป็นสำหรับ public endpoint
    แต่ยังสร้างไว้ได้เพื่อรองรับอนาคต
    """

    days = to_int(expire_days, default=PACKAGE_DEFAULT_EXPIRE_DAYS) or PACKAGE_DEFAULT_EXPIRE_DAYS
    days = max(1, min(days, PACKAGE_MAX_EXPIRE_DAYS))

    expire_at = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")

    payload = build_token_payload(
        package_id=package_id,
        expire_at=expire_at,
        scope=scope or ["read"],
        read_only=read_only,
    )

    return encode_access_token(payload)


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    decode token โดยยังไม่ verify signature
    """

    token = clean_text(token)

    if "." not in token:
        return {}

    payload_b64, _signature = token.split(".", 1)
    return b64url_decode_json(payload_b64)


def verify_access_token(
    token: str,
    expected_package_id: Optional[str] = None,
    required_scope: str = "read",
) -> Dict[str, Any]:
    """
    verify package access token

    Return:
    {
        valid: bool,
        reason: str,
        payload: dict
    }
    """

    token = clean_text(token)

    if not token:
        return {
            "valid": False,
            "reason": "missing_token",
            "payload": {},
        }

    if "." not in token:
        return {
            "valid": False,
            "reason": "invalid_token_format",
            "payload": {},
        }

    payload_b64, signature = token.split(".", 1)
    expected_signature = hmac_signature(payload_b64)

    if not constant_time_equal(signature, expected_signature):
        return {
            "valid": False,
            "reason": "invalid_signature",
            "payload": {},
        }

    payload = b64url_decode_json(payload_b64)

    if not payload:
        return {
            "valid": False,
            "reason": "invalid_payload",
            "payload": {},
        }

    if payload.get("version") != TOKEN_VERSION:
        return {
            "valid": False,
            "reason": "unsupported_token_version",
            "payload": payload,
        }

    package_id = clean_text(payload.get("package_id"))

    if expected_package_id and package_id != clean_text(expected_package_id):
        return {
            "valid": False,
            "reason": "package_id_mismatch",
            "payload": payload,
        }

    expire_at_raw = payload.get("expire_at")

    if expire_at_raw:
        try:
            expire_at = datetime.fromisoformat(expire_at_raw)
            if datetime.now() > expire_at:
                return {
                    "valid": False,
                    "reason": "token_expired",
                    "payload": payload,
                }
        except Exception:
            return {
                "valid": False,
                "reason": "invalid_expire_at",
                "payload": payload,
            }

    scope = payload.get("scope", [])

    if required_scope and required_scope not in scope:
        return {
            "valid": False,
            "reason": "missing_required_scope",
            "payload": payload,
        }

    return {
        "valid": True,
        "reason": "ok",
        "payload": payload,
    }


# ============================================================
# 7) PACKAGE METADATA SECURITY
# ============================================================

def normalize_package_status(status: Any) -> str:
    """
    normalize package status
    """

    text = clean_text_lower(status)

    if text in PACKAGE_STATUS_VALUES:
        return text

    return "active"


def is_package_expired(package_meta: Dict[str, Any]) -> bool:
    """
    ตรวจว่า package หมดอายุหรือยัง
    """

    expire_at_raw = package_meta.get("expire_at")

    if not expire_at_raw:
        return False

    try:
        expire_at = datetime.fromisoformat(str(expire_at_raw))
        return datetime.now() > expire_at
    except Exception:
        return False


def is_package_publicly_accessible(package_meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    ตรวจว่า package สามารถเปิดใน external viewer ได้ไหม
    """

    status = normalize_package_status(package_meta.get("status", "active"))

    if status != "active":
        return {
            "allowed": False,
            "reason": f"package_status_{status}",
        }

    if is_package_expired(package_meta):
        return {
            "allowed": False,
            "reason": "package_expired",
        }

    allow_public_access = to_bool(
        package_meta.get("allow_public_access", True),
        default=True,
    )

    if not allow_public_access:
        return {
            "allowed": False,
            "reason": "public_access_disabled",
        }

    return {
        "allowed": True,
        "reason": "ok",
    }


def build_public_package_url(
    package_id: str,
    base_url: str = "",
    include_token: bool = False,
    token: str = "",
) -> str:
    """
    สร้าง public package URL

    ถ้า base_url ว่าง จะใช้ path relative
    """

    safe_id = quote(clean_text(package_id))

    if base_url:
        url = f"{base_url.rstrip('/')}/external/{safe_id}"
    else:
        url = f"/external/{safe_id}"

    if include_token and token:
        url = f"{url}?token={quote(token)}"

    return url

def build_public_api_urls(
    package_id: str,
    public_prefix: str = "/api/public",
) -> Dict[str, str]:
    """
    สร้าง public API URL ของ package
    """

    safe_id = quote(clean_text(package_id), safe="")
    base = f"{public_prefix}/packages/{safe_id}"

    return {
        "meta": f"{base}/meta",
        "data": f"{base}/data",
        "summary": f"{base}/summary",
        "map": f"{base}/map",
        "charts": f"{base}/charts",
        "tables": f"{base}/tables",
        "data_quality": f"{base}/data-quality",
        "prediction": f"{base}/prediction",
        "entity": f"{base}/entity",
        "access_log": f"{base}/access-log",
    }

def generate_package_id(prefix: str = "PKG") -> str:
    """
    สร้าง package id

    Format:
    PKG_YYYYMMDD_HHMMSS_RANDOM
    """

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = secrets.token_hex(4).upper()
    return f"{prefix}_{timestamp}_{rand}"

def build_package_meta(
    package_id: str,
    package_name: Any = "",
    description: Any = "",
    filters: Optional[Dict[str, Any]] = None,
    components: Optional[List[str]] = None,
    security_options: Optional[Dict[str, Any]] = None,
    expire_days: Optional[int] = None,
    created_by: str = "system",
    allow_public_access: bool = True,
    base_url: str = "",
) -> Dict[str, Any]:
    """
    สร้าง package meta มาตรฐาน

    รองรับ call แบบ:
    - build_package_meta(package_id, package_name, description, ...)
    - build_package_meta(package_id, request_dict, snapshot_dict)
    """

    request: Dict[str, Any] = {}
    snapshot: Dict[str, Any] = {}

    if isinstance(package_name, dict):
        request = dict(package_name)
        if isinstance(description, dict):
            snapshot = dict(description)

        package_name = request.get("package_name") or request.get("name") or package_id
        description = request.get("description", "")
        filters = request.get("filters", filters or {})
        components = request.get("components", components)
        security_options = request.get("security", security_options)
        expire_days = request.get("expire_days") or request.get("expires_days") or expire_days
        created_by = request.get("created_by", created_by)
        allow_public_access = to_bool(request.get("allow_public_access", request.get("public", allow_public_access)), default=True)
        base_url = clean_text(request.get("base_url", base_url))

    days = to_int(expire_days, default=PACKAGE_DEFAULT_EXPIRE_DAYS) or PACKAGE_DEFAULT_EXPIRE_DAYS
    days = max(1, min(days, PACKAGE_MAX_EXPIRE_DAYS))

    expire_at = datetime.now() + timedelta(days=days)

    safe_security = normalize_security_policy(security_options)
    safe_security["public"] = True
    safe_security["remove_internal_paths"] = True
    safe_security["remove_debug_fields"] = True

    safe_components = sanitize_package_components(components)
    safe_filters = sanitize_package_filters(filters or {})

    token = generate_package_access_token(
        package_id=package_id,
        expire_days=days,
        scope=["data"],
    )

    public_url = build_public_package_url(
        package_id=package_id,
        base_url=base_url,
        include_token=ENABLE_PACKAGE_ACCESS_TOKEN,
        token=token,
    )

    checksum = clean_text(
        snapshot.get("checksum")
        or snapshot.get("package_checksum")
        or snapshot.get("snapshot_checksum")
    )

    return {
        "package_id": clean_text(package_id),
        "package_name": clean_text(package_name, default=package_id),
        "name": clean_text(package_name, default=package_id),
        "description": clean_text(description),
        "created_at": now_iso(),
        "created_by": clean_text(created_by, default="system"),
        "expire_at": expire_at.isoformat(timespec="seconds"),
        "expires_at": expire_at.isoformat(timespec="seconds"),
        "status": "active",
        "enabled": True,
        "allow_public_access": bool(allow_public_access),
        "public": bool(allow_public_access),
        "read_only": PUBLIC_PACKAGE_READ_ONLY,
        "snapshot_only": True,
        "package_source": "cache_snapshot",
        "public_viewer_source": "public_data_json_only",
        "components": safe_components,
        "filters": safe_filters,
        "security": safe_security,
        "public_url": public_url,
        "public_api_urls": build_public_api_urls(package_id),
        "public_urls": build_public_package_url_meta(package_id, base_url=base_url),
        "access_token_enabled": ENABLE_PACKAGE_ACCESS_TOKEN,
        "access_token": token if ENABLE_PACKAGE_ACCESS_TOKEN else "",
        "require_token": False,
        "record_counts": {},
        "files": [],
        "checksum": checksum,
        "checksum_components": PACKAGE_CHECKSUM_COMPONENTS,
        "app": {
            "name": APP_SHORT_NAME,
            "version": APP_VERSION,
        },
    }

# ============================================================
# 8) PACKAGE CHECKSUM / INTEGRITY
# ============================================================

def build_package_checksum(package_payload: Dict[str, Any]) -> str:
    """
    สร้าง checksum สำหรับ package payload

    checksum รวม summary/map/map_layers/charts/tables/data_quality/prediction/entity เท่านั้น
    """

    return sha256_payload(normalize_package_checksum_payload(package_payload))

def attach_package_checksum(package_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    เพิ่ม checksum เข้า package payload
    """

    result = deepcopy(package_payload)
    checksum = build_package_checksum(result)

    if isinstance(result.get("package_meta"), dict):
        result["package_meta"]["checksum"] = checksum
    else:
        result["checksum"] = checksum

    return result


def verify_package_checksum(package_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    verify checksum ของ package payload
    """

    if not isinstance(package_payload, dict):
        return {
            "valid": False,
            "reason": "payload_not_dict",
            "expected": "",
            "actual": "",
        }

    actual = ""

    if isinstance(package_payload.get("package_meta"), dict):
        actual = clean_text(package_payload["package_meta"].get("checksum"))
    else:
        actual = clean_text(package_payload.get("checksum"))

    expected = build_package_checksum(package_payload)

    return {
        "valid": bool(actual) and constant_time_equal(actual, expected),
        "reason": "ok" if bool(actual) and constant_time_equal(actual, expected) else "checksum_mismatch",
        "expected": expected,
        "actual": actual,
    }


# ============================================================
# 9) PACKAGE ACCESS CHECK
# ============================================================

def check_public_package_access(
    package_meta: Dict[str, Any],
    token: str = "",
    required_scope: str = "data",
) -> Dict[str, Any]:
    """
    ตรวจสิทธิ์การเปิด package ใน external viewer
    """

    meta = package_meta if isinstance(package_meta, dict) else {}

    if not meta:
        return {
            "allowed": False,
            "reason": "package_not_found",
            "token": {
                "required": ENABLE_PACKAGE_ACCESS_TOKEN,
                "valid": False,
            },
        }

    access_status = is_package_publicly_accessible(meta)

    if not access_status.get("allowed"):
        return {
            "allowed": False,
            "reason": access_status.get("reason"),
            "token": {
                "required": ENABLE_PACKAGE_ACCESS_TOKEN,
                "valid": False,
            },
        }

    scope = normalize_access_scope(required_scope)

    if ENABLE_PACKAGE_ACCESS_TOKEN and token:
        verification = verify_package_access_token(
            token,
            package_id=meta.get("package_id"),
            scope=scope,
        )

        if not verification.get("valid"):
            return {
                "allowed": False,
                "reason": verification.get("reason"),
                "token": {
                    "required": True,
                    "valid": False,
                    "verification": verification,
                },
            }

        return {
            "allowed": True,
            "reason": "token_verified",
            "component": scope,
            "token": {
                "required": True,
                "valid": True,
                "verification": verification,
            },
        }

    if to_bool(meta.get("require_token"), default=False):
        return {
            "allowed": False,
            "reason": "missing_token",
            "component": scope,
            "token": {
                "required": True,
                "valid": False,
            },
        }

    return {
        "allowed": True,
        "reason": "ok",
        "component": scope,
        "token": {
            "required": False,
            "valid": True,
        },
    }

# ============================================================
# 10) PUBLIC SNAPSHOT BUILDER
# ============================================================
def build_public_package_snapshot(
    package_snapshot: Dict[str, Any],
    token: str = "",
) -> Dict[str, Any]:
    """
    สร้าง public snapshot สำหรับ external viewer

    external viewer อ่าน snapshot ที่ generate แล้วเท่านั้น
    """

    if not isinstance(package_snapshot, dict):
        return {
            "allowed": False,
            "reason": "invalid_package_snapshot",
            "data": {},
        }

    package_meta = (
        package_snapshot.get("package_meta")
        or package_snapshot.get("meta")
        or {}
    )

    if not isinstance(package_meta, dict):
        package_meta = {}

    if not package_meta:
        package_meta = {
            "package_id": package_snapshot.get("package_id", ""),
            "package_name": package_snapshot.get("package_name", package_snapshot.get("package_id", "")),
            "status": "active",
            "enabled": True,
            "allow_public_access": True,
            "public": True,
            "security": PACKAGE_SECURITY_OPTIONS,
            "components": PUBLIC_ALLOWED_PACKAGE_COMPONENTS,
            "require_token": False,
        }

    access = check_public_package_access(
        package_meta=package_meta,
        token=token,
        required_scope="data",
    )

    if not access.get("allowed"):
        return {
            "allowed": False,
            "reason": access.get("reason"),
            "access": access,
            "data": {},
        }

    security_options = package_meta.get("security", PACKAGE_SECURITY_OPTIONS)

    snapshot_source = deepcopy(package_snapshot)

    for key in [
        "raw_cache",
        "raw_source",
        "raw_excel",
        "input_files",
        "source_files",
        "cache_files",
        "debug",
        "debug_info",
    ]:
        snapshot_source.pop(key, None)

    public_snapshot = sanitize_public_payload(
        snapshot_source,
        security_options=security_options,
    )

    if isinstance(public_snapshot, dict):
        root_data = public_snapshot.get("data", {}) if isinstance(public_snapshot.get("data"), dict) else {}

        if isinstance(root_data, dict) and "data_quality" in root_data:
            root_data["data_quality"] = sanitize_public_payload(
                root_data.get("data_quality", {}),
                security_options=security_options,
            )
            public_snapshot["data"] = root_data

        if "data_quality" in public_snapshot:
            public_snapshot["data_quality"] = sanitize_public_payload(
                public_snapshot.get("data_quality", {}),
                security_options=security_options,
            )

        safe_meta = build_safe_public_meta(package_meta)

        public_snapshot["package_meta"] = {
            **safe_meta,
            "checksum": create_package_checksum(public_snapshot),
            "checksum_components": PACKAGE_CHECKSUM_COMPONENTS,
            "read_only": PUBLIC_PACKAGE_READ_ONLY,
            "snapshot_only": True,
        }

        public_snapshot.setdefault("public_meta", {})
        public_snapshot["public_meta"].update(
            {
                "read_only": PUBLIC_PACKAGE_READ_ONLY,
                "snapshot_only": True,
                "access_checked_at": now_iso(),
                "token_required": False,
                "components": package_meta.get("components", PUBLIC_ALLOWED_PACKAGE_COMPONENTS),
                "checksum_components": PACKAGE_CHECKSUM_COMPONENTS,
                "public_viewer_source": "public_data_json_only",
                "public_viewer_reads_raw_cache": False,
                "public_viewer_reads_raw_excel": False,
            }
        )

    return {
        "allowed": True,
        "reason": "ok",
        "access": access,
        "data": public_snapshot,
    }


def extract_public_package_component(
    package_snapshot: Dict[str, Any],
    component: str,
    token: str = "",
) -> Dict[str, Any]:
    """
    ดึง component เฉพาะจาก package snapshot
    """

    public_result = build_public_package_snapshot(
        package_snapshot=package_snapshot,
        token=token,
    )

    if not public_result.get("allowed"):
        return public_result

    data = public_result.get("data", {})
    component_key = clean_text_lower(component, default="data")

    component_aliases = {
        "map_layers": "map",
        "flood_prediction": "prediction",
        "flood_prediction_latest": "prediction",
        "uploaded_entity": "entity",
        "uploaded_entity_latest": "entity",
    }

    canonical_component = component_aliases.get(component_key, component_key)

    root_data = data.get("data", {}) if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}

    if canonical_component == "data":
        component_data = data

    elif canonical_component == "meta":
        component_data = data.get("package_meta", data.get("meta", {})) if isinstance(data, dict) else {}

    elif canonical_component == "summary":
        component_data = root_data.get("summary", data.get("summary", {})) if isinstance(data, dict) else {}

    elif canonical_component == "map":
        component_data = (
            root_data.get("map")
            or root_data.get("map_layers")
            or data.get("map")
            or data.get("map_layers")
            or {}
        ) if isinstance(data, dict) else {}

    elif canonical_component == "charts":
        component_data = root_data.get("charts", data.get("charts", {})) if isinstance(data, dict) else {}

    elif canonical_component == "tables":
        component_data = root_data.get("tables", data.get("tables", {})) if isinstance(data, dict) else {}

    elif canonical_component == "data_quality":
        component_data = root_data.get("data_quality", data.get("data_quality", {})) if isinstance(data, dict) else {}
        component_data = sanitize_public_payload(component_data)

    elif canonical_component == "prediction":
        component_data = (
            root_data.get("prediction")
            or root_data.get("flood_prediction")
            or root_data.get("flood_prediction_latest")
            or data.get("prediction")
            or data.get("flood_prediction")
            or data.get("flood_prediction_latest")
            or {}
        ) if isinstance(data, dict) else {}

    elif canonical_component == "entity":
        component_data = (
            root_data.get("entity")
            or root_data.get("uploaded_entity")
            or root_data.get("uploaded_entity_latest")
            or data.get("entity")
            or data.get("uploaded_entity")
            or data.get("uploaded_entity_latest")
            or {}
        ) if isinstance(data, dict) else {}

    else:
        component_data = root_data.get(canonical_component, data.get(canonical_component, {})) if isinstance(data, dict) else {}

    return {
        "allowed": True,
        "reason": "ok",
        "access": public_result.get("access", {}),
        "component": canonical_component,
        "requested_component": component,
        "data": sanitize_public_payload(component_data),
    }

# ============================================================
# 11) SCOPE / COMPONENT PERMISSION
# ============================================================

def can_include_component(
    component: str,
    allowed_components: Optional[List[str]] = None,
) -> bool:
    """
    ตรวจว่า component สามารถอยู่ใน package ได้ไหม
    """

    component = clean_text(component)

    if not component:
        return False

    allowed = allowed_components or PUBLIC_ALLOWED_PACKAGE_COMPONENTS

    return component in allowed

def filter_package_data_by_components(
    data: Dict[str, Any],
    components: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    filter package data ตาม components
    """

    allowed = sanitize_package_components(components)

    if not isinstance(data, dict):
        return {}

    aliases = {
        "map_layers": "map",
        "flood_prediction": "prediction",
        "flood_prediction_latest": "prediction",
        "uploaded_entity": "entity",
        "uploaded_entity_latest": "entity",
    }

    result: Dict[str, Any] = {}

    for component in allowed:
        canonical = aliases.get(component, component)

        if component in data:
            result[component] = data[component]

        elif canonical in data:
            result[component] = data[canonical]

    return sanitize_public_payload(result)


def enforce_read_only_payload(payload: Any) -> Any:
    """
    เพิ่ม read-only marker ให้ payload

    External viewer ใช้เพื่อรู้ว่าไม่ควรแก้ไขข้อมูล
    """

    if isinstance(payload, dict):
        result = deepcopy(payload)
        result.setdefault("_security", {})
        result["_security"].update(
            {
                "read_only": True,
                "generated_by": APP_SHORT_NAME,
                "generated_at": now_iso(),
            }
        )
        return result

    return payload


# ============================================================
# 12) ACCESS LOG
# ============================================================

def build_access_log_record(
    package_id: str,
    remote_addr: str = "",
    user_agent: str = "",
    action: str = "view",
    allowed: bool = True,
    reason: str = "ok",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง access log record สำหรับ external package
    """

    package_id = clean_text(package_id)

    key = f"{package_id}|{remote_addr}|{user_agent}|{action}|{now_iso()}"

    return {
        "log_id": make_hash_id(key, prefix="access", length=20),
        "package_id": package_id,
        "action": clean_text(action, default="view"),
        "allowed": bool(allowed),
        "reason": clean_text(reason, default="ok"),
        "remote_addr": clean_text(remote_addr),
        "user_agent": clean_text(user_agent),
        "accessed_at": now_iso(),
        "extra": to_jsonable(extra or {}),
    }


# ============================================================
# 13) FIELD-LEVEL EXPORT POLICY
# ============================================================

def get_export_field_policy(
    security_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    คืน policy การ export field

    ใช้โดย dashboard_package_service.py
    """

    options = normalize_security_options(security_options)

    hidden_fields: List[str] = []
    masked_fields: Dict[str, str] = {}

    if options.get("mask_tax_id"):
        for field in SENSITIVE_FIELD_GROUPS["tax_id"]:
            masked_fields[field] = "tax_id_mask"

    if options.get("mask_director_name"):
        for field in SENSITIVE_FIELD_GROUPS["director_name"]:
            masked_fields[field] = "director_name_mask"

    if options.get("mask_address"):
        for field in SENSITIVE_FIELD_GROUPS["address"]:
            masked_fields[field] = "address_mask"

    if options.get("hide_financial_fields"):
        hidden_fields.extend(SENSITIVE_FIELD_GROUPS["financial"])

    return {
        "security_options": options,
        "hidden_fields": sorted(set(hidden_fields)),
        "masked_fields": masked_fields,
    }


def apply_export_field_policy_to_record(
    record: Dict[str, Any],
    security_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    apply field policy กับ record

    ลบ internal path/debug/raw field ออกจาก export เสมอ
    """

    if not isinstance(record, dict):
        return {}

    options = normalize_security_policy(security_options)
    result = sanitize_public_record(record, options)

    if options.get("hide_financial_fields"):
        for hidden_field in FINANCIAL_FIELDS:
            result.pop(hidden_field, None)

    for key in list(result.keys()):
        if should_remove_public_key(key):
            result.pop(key, None)

    return json_safe(result)


def apply_export_field_policy_to_records(
    records: List[Dict[str, Any]],
    security_options: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    apply field policy กับ records
    """

    return [
        apply_export_field_policy_to_record(record, security_options)
        for record in records
        if isinstance(record, dict)
    ]


# ============================================================
# 14) SAFE PUBLIC RESPONSE HELPERS
# ============================================================

def build_safe_public_meta(package_meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    สร้าง meta สำหรับ public API

    ไม่คืน access_token/path/debug/raw metadata
    """

    if not isinstance(package_meta, dict):
        return {}

    meta = sanitize_public_payload(package_meta, security_options=package_meta.get("security", {}))

    if isinstance(meta, dict):
        for key in list(meta.keys()):
            if should_remove_public_key(key):
                meta.pop(key, None)

        meta.pop("access_token", None)
        meta.pop("token", None)
        meta.pop("checksum_raw", None)
        meta["read_only"] = PUBLIC_PACKAGE_READ_ONLY
        meta["snapshot_only"] = True
        meta["public_viewer_source"] = "public_data_json_only"
        meta["public_viewer_reads_raw_cache"] = False
        meta["public_viewer_reads_raw_excel"] = False
        meta["checksum_components"] = PACKAGE_CHECKSUM_COMPONENTS

    return meta

def build_public_error(
    reason: str,
    package_id: str = "",
    status: str = "denied",
) -> Dict[str, Any]:
    """
    สร้าง error object สำหรับ public package API
    """

    return {
        "status": status,
        "allowed": False,
        "reason": clean_text(reason, default="unknown"),
        "package_id": clean_text(package_id),
        "timestamp": now_iso(),
    }


def build_public_success(
    data: Any,
    package_id: str = "",
    component: str = "",
) -> Dict[str, Any]:
    """
    สร้าง success object สำหรับ public package API
    """

    return {
        "status": "ok",
        "allowed": True,
        "package_id": clean_text(package_id),
        "component": clean_text(component),
        "timestamp": now_iso(),
        "data": to_jsonable(data),
    }


# ============================================================
# 15) MODULE HEALTH
# ============================================================

def get_security_summary() -> Dict[str, Any]:
    """
    คืน summary ของ security module
    """

    return {
        "module": "security",
        "ready": True,
        "app": APP_SHORT_NAME,
        "version": APP_VERSION,
        "public_package_read_only": PUBLIC_PACKAGE_READ_ONLY,
        "snapshot_only_public_viewer": True,
        "public_viewer_source": "public_data_json_only",
        "public_viewer_reads_raw_cache": False,
        "public_viewer_reads_raw_excel": False,
        "access_token_enabled": ENABLE_PACKAGE_ACCESS_TOKEN,
        "token_version": TOKEN_VERSION,
        "masking": {
            "tax_id_visible_last_digits": MASK_TAX_ID_VISIBLE_LAST_DIGITS,
            "director_visible_first_chars": MASK_DIRECTOR_VISIBLE_FIRST_CHARS,
            "default_security_options": PACKAGE_SECURITY_OPTIONS,
        },
        "public_allowed_components": PUBLIC_ALLOWED_PACKAGE_COMPONENTS,
        "public_prediction_allowed_fields": sorted(PUBLIC_PREDICTION_ALLOWED_FIELDS),
        "public_entity_allowed_fields": sorted(PUBLIC_ENTITY_ALLOWED_FIELDS),
        "forbidden_internal_keys": PUBLIC_FORBIDDEN_INTERNAL_KEYS,
        "internal_path_fields": sorted(INTERNAL_PATH_FIELDS),
        "debug_private_fields": sorted(DEBUG_PRIVATE_FIELDS),
        "checksum_components": PACKAGE_CHECKSUM_COMPONENTS,
        "package_status_values": PACKAGE_STATUS_VALUES,
        "checked_at": now_iso(),
    }

# ============================================================
# 16) QUICK SELF TEST
# ============================================================

def run_security_self_test() -> Dict[str, Any]:
    """
    self test สำหรับ security.py
    """

    package_id = "PKG_TEST"
    token = generate_package_access_token(package_id, expire_days=1)
    verify = verify_access_token(token, expected_package_id=package_id)

    sample_record = {
        "tax_id_norm": "0105560000000",
        "director_name": "นายตัวอย่าง ทดสอบ",
        "address": "99/9 ถนนตัวอย่าง แขวงตัวอย่าง เขตตัวอย่าง กรุงเทพฯ",
        "total_premium": 1000000,
        "company_name": "บริษัท ตัวอย่าง จำกัด",
        "source_file": "/mnt/data/internal.xlsx",
    }

    prediction_record = {
        "object_type": "prediction",
        "source_type": "flood_prediction",
        "record_key": "prediction|1373690|2026-07-01|2026-07-03|2",
        "province": "น่าน",
        "station_name": "สถานีตัวอย่าง",
        "risk_level": "Critical",
        "target_date": "2026-07-03",
        "forecast_horizon_day": 2,
        "latest_value": 4.25,
        "latest_unit": "m",
        "map_ready": True,
        "latitude": 18.7,
        "longitude": 100.7,
        "source_file": "C:\\internal\\predict_20260701.xlsx",
        "internal_path": "/mnt/data/C:/Users/internal/predict.xlsx",
        "debug_traceback": "traceback",
        "raw_record": {"secret": "x"},
    }

    entity_record = {
        "object_type": "entity",
        "source_type": "uploaded_entity",
        "entity_id": "E001",
        "entity_type": "shop",
        "entity_name_th": "ร้านตัวอย่าง",
        "entity_name_en": "Example Shop",
        "province_name_th": "น่าน",
        "risk_group": "Watch",
        "is_displayable": True,
        "map_ready": True,
        "latitude": 18.7,
        "longitude": 100.7,
        "saved_file": "C:\\internal\\upload.csv",
        "error_report_file": "/mnt/data/internal/error.csv",
    }

    masked = mask_record(
        sample_record,
        security_options={
            "mask_tax_id": True,
            "mask_director_name": True,
            "mask_address": True,
            "hide_financial_fields": True,
        },
    )

    sanitized_prediction = sanitize_public_payload(prediction_record)
    sanitized_entity = sanitize_public_payload(entity_record)

    package_payload = {
        "package_id": package_id,
        "package_meta": {
            "package_id": package_id,
            "checksum": "",
            "access_token": token,
            "source_file": "/mnt/data/internal.xlsx",
        },
        "data": {
            "summary": {"total": 1},
            "map": {"features": []},
            "map_layers": {"layers": {}},
            "charts": {},
            "tables": {},
            "data_quality": {
                "issues": [
                    {
                        "field": "actual",
                        "actual": "/mnt/data/C:/Users/internal/source.xlsx",
                    }
                ]
            },
            "prediction": [prediction_record],
            "entity": [entity_record],
        },
    }

    checksum = create_package_checksum(package_payload)
    public_snapshot = build_public_package_snapshot(
        {
            **package_payload,
            "package_meta": {
                **package_payload["package_meta"],
                "status": "active",
                "allow_public_access": True,
                "require_token": False,
            },
        }
    )

    return {
        "token_generated": bool(token),
        "token_verify_valid": verify.get("valid"),
        "token_verify_reason": verify.get("reason"),
        "sample_record": sample_record,
        "masked_record": masked,
        "sanitized_prediction": sanitized_prediction,
        "sanitized_entity": sanitized_entity,
        "prediction_internal_removed": (
            "source_file" not in sanitized_prediction
            and "internal_path" not in sanitized_prediction
            and "debug_traceback" not in sanitized_prediction
            and "raw_record" not in sanitized_prediction
        ),
        "entity_internal_removed": (
            "saved_file" not in sanitized_entity
            and "error_report_file" not in sanitized_entity
        ),
        "local_path_removed_from_masked": "source_file" not in masked,
        "checksum_generated": bool(checksum),
        "checksum_components": PACKAGE_CHECKSUM_COMPONENTS,
        "public_snapshot_allowed": public_snapshot.get("allowed"),
        "summary": get_security_summary(),
    }

# ============================================================
# 17) PHASE 12 STABLE SECURITY API CONTRACT
# ============================================================

TAX_ID_FIELDS = {
    "tax_id",
    "tax_id_raw",
    "tax_id_norm",
    "company_tax_id",
    "source_tax_id",
    "target_tax_id",
}
DIRECTOR_PERSON_FIELDS = {
    "director_name",
    "director_name_raw",
    "director_name_norm",
    "director_name_display",
    "person_name",
    "shared_directors",
    "boardlist",
}
ADDRESS_FIELDS = {
    "address",
    "full_address",
    "house_no",
    "street",
    "subdistrict",
    "district",
}
FINANCIAL_FIELDS = {
    "premium",
    "loss",
    "suminsure",
    "total_premium",
    "total_loss",
    "total_suminsure",
    "registered_capital",
    "most_recent_income_val",
    "most_recent_asset_val",
    "most_recent_profit_val",
    "hist_premium_sum_all",
    "last_premium_active",
    "exp_premium",
}
INTERNAL_PATH_FIELDS = {
    "_local_path",
    "absolute_path",
    "file_path",
    "path",
    "source_path",
    "source_file",
    "source_file_path",
    "cache_path",
    "cache_file",
    "raw_file_path",
    "internal_path",
    "local_path",
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
    "raw_sheet",
    "raw_sheet_name",
}
DEBUG_PRIVATE_FIELDS = {
    "debug",
    "debug_info",
    "debug_traceback",
    "traceback",
    "exception",
    "internal",
    "secret",
    "token",
    "access_token",
    "token_secret",
    "private_key",
    "package_token_salt",
    "secret_key",
    "raw_record",
    "raw_records",
    "raw_row",
    "raw_rows",
    "raw_payload",
    "raw_sheet",
    "raw_sheet_name",
    "checksum_raw",
    "not_displayable",
    "not_displayable_records",
    "invalid_records",
    "invalid_rows",
}
PACKAGE_ACCESS_SCOPES = {
    "meta",
    "summary",
    "data",
    "map",
    "charts",
    "tables",
    "data_quality",
    "prediction",
    "entity",
    "download",
    "admin",
}
DEFAULT_MASKING_POLICY = {
    "mask_tax_id": True,
    "mask_director_name": True,
    "mask_person_name": True,
    "mask_address": True,
    "hide_financial_fields": False,
    "remove_internal_paths": True,
    "remove_debug_fields": True,
    "public": True,
}


def json_safe(value: Any) -> Any:
    return to_jsonable(value)


def normalize_security_policy(policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = dict(DEFAULT_MASKING_POLICY)
    if isinstance(PACKAGE_SECURITY_OPTIONS, dict):
        for key in base:
            if key in PACKAGE_SECURITY_OPTIONS:
                base[key] = PACKAGE_SECURITY_OPTIONS[key]
    if isinstance(policy, dict):
        for key, value in policy.items():
            if key in base:
                base[key] = to_bool(value, default=bool(base[key]))
            else:
                base[key] = json_safe(value)
    if base.get("public", True):
        base["mask_tax_id"] = to_bool(base.get("mask_tax_id"), True)
        base["mask_director_name"] = to_bool(base.get("mask_director_name"), True)
        base["mask_person_name"] = to_bool(base.get("mask_person_name"), True)
        base["mask_address"] = to_bool(base.get("mask_address"), True)
        base["remove_internal_paths"] = to_bool(base.get("remove_internal_paths"), True)
        base["remove_debug_fields"] = to_bool(base.get("remove_debug_fields"), True)
    return base


def _field_name(value: Any) -> str:
    return clean_text_lower(value).replace(" ", "_")


def _looks_like_local_path(value: Any) -> bool:
    text = clean_text(value)

    if not text:
        return False

    normalized = text.replace("\\", "/")
    lower = normalized.lower()

    if lower.startswith("file://"):
        return True

    if len(normalized) > 2 and normalized[1:3] == ":/" and normalized[0].isalpha():
        return True

    if lower.startswith("//"):
        return True

    if any(f"/{drive}:/" in lower for drive in "abcdefghijklmnopqrstuvwxyz"):
        return True

    local_prefixes = (
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

    if lower.startswith(local_prefixes):
        return True

    if "c:/users/" in lower or "c:\\users\\" in text.lower():
        return True

    return False


def mask_tax_id(value: Any, visible_last: int = 4) -> str:
    digits = "".join(ch for ch in clean_text(value) if ch.isdigit())
    if not digits:
        return ""
    visible = max(0, min(len(digits), int(visible_last or 0)))
    if len(digits) <= visible:
        return "*" * len(digits) if len(digits) > 1 else "***"
    return "*" * (len(digits) - visible) + digits[-visible:]


def mask_person_name(value: Any) -> Any:
    if isinstance(value, list):
        return [mask_person_name(item) for item in value]
    text = clean_text(value)
    if not text:
        return ""
    if "," in text:
        return [mask_person_name(part) for part in text.split(",") if clean_text(part)]
    if ";" in text:
        return [mask_person_name(part) for part in text.split(";") if clean_text(part)]
    prefix = text[:1]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:4]
    return f"{prefix}***{digest}"


def mask_director_name(value: Any) -> Any:
    return mask_person_name(value)


def mask_address(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parts = [part for part in text.replace(",", " ").split() if part]
    if len(parts) <= 1:
        return "***"
    return f"{parts[-1]} ***"


def mask_phone(value: Any) -> str:
    digits = "".join(ch for ch in clean_text(value) if ch.isdigit())
    if not digits:
        return ""
    return "*" * max(0, len(digits) - 4) + digits[-4:]


def mask_email(value: Any) -> str:
    text = clean_text(value)
    if "@" not in text:
        return "***" if text else ""
    local, domain = text.split("@", 1)
    return f"{local[:1]}***@{domain}"


def hide_financial_fields(record: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result = dict(record or {})
    active_policy = normalize_security_policy(policy)
    if not to_bool(active_policy.get("hide_financial_fields"), False):
        return json_safe(result)
    for key in list(result.keys()):
        if _field_name(key) in FINANCIAL_FIELDS:
            result.pop(key, None)
    return json_safe(result)

PUBLIC_PREDICTION_ALLOWED_FIELDS = {
    "object_type",
    "source_type",
    "record_key",
    "province",
    "province_model",
    "province_name_th",
    "station_name",
    "matched_station_name",
    "risk_level",
    "risk_status",
    "warning_level",
    "warning_level_predict",
    "base_date",
    "target_date",
    "forecast_horizon_day",
    "latest_value",
    "latest_unit",
    "map_ready",
    "focus_level",
    "focus_fallback",
    "latitude",
    "longitude",
    "lat",
    "lon",
}

PUBLIC_ENTITY_ALLOWED_FIELDS = {
    "object_type",
    "source_type",
    "entity_id",
    "entity_type",
    "entity_name_th",
    "entity_name_en",
    "province",
    "province_name_th",
    "risk_group",
    "risk_level",
    "map_ready",
    "has_location",
    "is_displayable",
    "latitude",
    "longitude",
    "lat",
    "lon",
}

PUBLIC_INTERNAL_KEY_FRAGMENTS = {
    "source_file",
    "source_path",
    "internal_path",
    "cache_file",
    "cache_path",
    "raw_file_path",
    "upload_dir",
    "saved_file",
    "error_report_file",
    "debug_traceback",
    "traceback",
    "raw_record",
    "raw_records",
    "raw_row",
    "raw_rows",
    "raw_payload",
    "raw_sheet",
    "raw_sheet_name",
    "not_displayable",
    "invalid_records",
    "invalid_rows",
    "download_path",
    "export_path",
    "zip_path",
    "package_path",
    "viewer_dir",
    "assets_dir",
    "secret",
    "access_token",
    "token_secret",
    "package_token_salt",
    "secret_key",
    "private_key",
    "checksum_raw",
}

PACKAGE_CHECKSUM_COMPONENTS = [
    "summary",
    "map",
    "map_layers",
    "charts",
    "tables",
    "data_quality",
    "prediction",
    "flood_prediction",
    "flood_prediction_latest",
    "flood_prediction_map",
    "entity",
    "uploaded_entity",
    "uploaded_entity_latest",
]


def should_remove_public_key(key: Any) -> bool:
    normalized_key = _field_name(key)

    if not normalized_key:
        return False

    if normalized_key in INTERNAL_PATH_FIELDS:
        return True

    if normalized_key in DEBUG_PRIVATE_FIELDS:
        return True

    if normalized_key in {clean_text_lower(item).replace(" ", "_") for item in PUBLIC_FORBIDDEN_INTERNAL_KEYS}:
        return True

    return any(fragment in normalized_key for fragment in PUBLIC_INTERNAL_KEY_FRAGMENTS)


def is_public_prediction_record(record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False

    object_type = clean_text_lower(record.get("object_type"))
    source_type = clean_text_lower(record.get("source_type"))
    record_key = clean_text_lower(record.get("record_key"))

    return bool(
        object_type == "prediction"
        or "prediction" in source_type
        or record_key.startswith("prediction|")
        or "warning_level_predict" in record
        or "forecast_horizon_day" in record
    )


def is_public_entity_record(record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False

    object_type = clean_text_lower(record.get("object_type"))
    source_type = clean_text_lower(record.get("source_type"))

    return bool(
        object_type == "entity"
        or source_type == "uploaded_entity"
        or "entity_id" in record
        or "entity_name_th" in record
    )

def is_public_entity_displayable(record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False

    if "is_displayable" in record and to_bool(record.get("is_displayable"), default=False) is False:
        return False

    if "displayable" in record and to_bool(record.get("displayable"), default=False) is False:
        return False

    if to_bool(record.get("not_displayable"), default=False):
        return False

    lat = record.get("latitude", record.get("lat"))
    lon = record.get("longitude", record.get("lon"))

    if is_empty_value(lat) or is_empty_value(lon):
        return False

    return bool(
        to_bool(record.get("map_ready"), default=True)
        or to_bool(record.get("has_location"), default=True)
        or "latitude" in record
        or "lat" in record
    )

def sanitize_public_scalar(key: Any, value: Any, policy: Optional[Dict[str, Any]] = None) -> Any:
    active_policy = normalize_security_policy(policy)
    normalized_key = _field_name(key)

    if should_remove_public_key(key):
        return ""

    if active_policy.get("remove_internal_paths", True) and _looks_like_local_path(value):
        return ""

    if normalized_key in TAX_ID_FIELDS and active_policy.get("mask_tax_id", True):
        return mask_tax_id(value, MASK_TAX_ID_VISIBLE_LAST_DIGITS)

    if normalized_key in DIRECTOR_PERSON_FIELDS and active_policy.get("mask_director_name", True):
        return mask_director_name(value)

    if normalized_key in ADDRESS_FIELDS and active_policy.get("mask_address", True):
        return mask_address(value)

    if normalized_key in FINANCIAL_FIELDS and active_policy.get("hide_financial_fields", False):
        return None

    if isinstance(value, (dict, list)):
        return sanitize_public_payload(value, active_policy)

    return json_safe(value)


def sanitize_prediction_public_record(record: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    for key, value in record.items():
        normalized_key = _field_name(key)

        if should_remove_public_key(key):
            continue

        if normalized_key not in PUBLIC_PREDICTION_ALLOWED_FIELDS:
            continue

        sanitized = sanitize_public_scalar(key, value, policy)

        if sanitized in ("", None) and normalized_key not in {"latest_value", "latitude", "longitude", "lat", "lon"}:
            continue

        result[key] = sanitized

    result.setdefault("object_type", "prediction")
    result.setdefault("source_type", "flood_prediction")

    return json_safe(result)


def sanitize_entity_public_record(record: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not is_public_entity_displayable(record):
        return {}

    result: Dict[str, Any] = {}

    for key, value in record.items():
        normalized_key = _field_name(key)

        if should_remove_public_key(key):
            continue

        if normalized_key not in PUBLIC_ENTITY_ALLOWED_FIELDS:
            continue

        sanitized = sanitize_public_scalar(key, value, policy)

        if sanitized in ("", None) and normalized_key not in {"latitude", "longitude", "lat", "lon"}:
            continue

        result[key] = sanitized

    result.setdefault("object_type", "entity")
    result.setdefault("source_type", "uploaded_entity")
    result.setdefault("is_displayable", True)
    result.setdefault("map_ready", True)

    return json_safe(result)
def normalize_package_checksum_payload(payload: Any) -> Any:
    value = json_safe(payload)

    if not isinstance(value, dict):
        return value

    source = deepcopy(value)

    for key in [
        "checksum",
        "package_checksum",
        "snapshot_checksum",
        "checksum_raw",
        "access_token",
        "token",
    ]:
        source.pop(key, None)

    if isinstance(source.get("package_meta"), dict):
        source["package_meta"] = {
            key: item
            for key, item in source["package_meta"].items()
            if key not in {
                "checksum",
                "package_checksum",
                "snapshot_checksum",
                "checksum_raw",
                "access_token",
                "token",
            }
        }

    if isinstance(source.get("meta"), dict):
        source["meta"] = {
            key: item
            for key, item in source["meta"].items()
            if key not in {
                "checksum",
                "package_checksum",
                "snapshot_checksum",
                "checksum_raw",
                "access_token",
                "token",
                "generated_at",
                "access_checked_at",
            }
        }

    if isinstance(source.get("data"), dict):
        data = source["data"]
    else:
        data = source

    checksum_data = {
        key: data.get(key)
        for key in PACKAGE_CHECKSUM_COMPONENTS
        if isinstance(data, dict) and key in data
    }

    return json_safe(
        {
            "package_id": source.get("package_id") or source.get("package_meta", {}).get("package_id"),
            "data": checksum_data,
        }
    )

def is_data_quality_issue_record(record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False

    return bool(
        "issue_id" in record
        or "issue_type" in record
        or "severity" in record and "category" in record and ("message" in record or "code" in record)
        or clean_text_lower(record.get("category")) in {
            "data_quality",
            "map_readiness",
            "package_readiness",
            "frontend_readiness",
            "cache",
            "flood",
            "policy",
            "linkage",
            "spatial",
            "input",
        }
    )


def sanitize_data_quality_issue_record(record: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(record, dict):
        return {}

    result: Dict[str, Any] = {}

    for key, value in record.items():
        normalized_key = _field_name(key)

        if should_remove_public_key(key):
            continue

        if normalized_key in {
            "actual",
            "expected",
            "value",
            "extra",
            "meta",
            "metadata",
            "details",
            "debug",
            "debug_info",
            "source_detail",
            "source_meta",
        }:
            sanitized_value = sanitize_data_quality_public_value(value, policy)

            if sanitized_value in ({}, [], "", None):
                continue

            result[key] = sanitized_value
            continue

        sanitized = sanitize_public_scalar(key, value, policy)

        if sanitized in ({}, [], "", None) and normalized_key not in {
            "issue_count",
            "row_number",
            "total",
            "count",
        }:
            continue

        result[key] = sanitized

    return json_safe(result)


def sanitize_data_quality_public_value(value: Any, policy: Optional[Dict[str, Any]] = None) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}

        for key, item in value.items():
            if should_remove_public_key(key):
                continue

            sanitized = sanitize_data_quality_public_value(item, policy)

            if sanitized in ({}, [], "", None):
                continue

            cleaned[key] = sanitized

        return json_safe(cleaned)

    if isinstance(value, list):
        cleaned_items = []

        for item in value:
            sanitized = sanitize_data_quality_public_value(item, policy)

            if sanitized in ({}, [], "", None):
                continue

            cleaned_items.append(sanitized)

        return json_safe(cleaned_items)

    if _looks_like_local_path(value):
        return ""

    return json_safe(value)

def sanitize_public_record(record: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(record, dict):
        return {}

    active_policy = normalize_security_policy(policy)

    if is_public_prediction_record(record):
        return sanitize_prediction_public_record(record, active_policy)

    if is_public_entity_record(record):
        return sanitize_entity_public_record(record, active_policy)

    if is_data_quality_issue_record(record):
        return sanitize_data_quality_issue_record(record, active_policy)

    result: Dict[str, Any] = {}

    for key, value in record.items():
        normalized_key = _field_name(key)

        if should_remove_public_key(key):
            continue

        if active_policy.get("remove_internal_paths", True) and _looks_like_local_path(value):
            continue

        if active_policy.get("remove_debug_fields", True) and normalized_key in DEBUG_PRIVATE_FIELDS:
            continue

        if normalized_key in TAX_ID_FIELDS and active_policy.get("mask_tax_id", True):
            result[key] = mask_tax_id(value, MASK_TAX_ID_VISIBLE_LAST_DIGITS)

        elif normalized_key in DIRECTOR_PERSON_FIELDS and active_policy.get("mask_director_name", True):
            result[key] = mask_director_name(value)

        elif normalized_key in ADDRESS_FIELDS and active_policy.get("mask_address", True):
            result[key] = mask_address(value)

        elif normalized_key in FINANCIAL_FIELDS and active_policy.get("hide_financial_fields", False):
            continue

        else:
            sanitized = sanitize_public_payload(value, active_policy)

            if sanitized in ("", None) and active_policy.get("remove_internal_paths", True):
                continue

            result[key] = sanitized

    return json_safe(result)


def mask_record(record: Dict[str, Any], policy: Optional[Dict[str, Any]] = None, security_options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    active_policy = normalize_security_policy(policy or security_options)
    return sanitize_public_record(record, active_policy)


def mask_records(records: Iterable[Dict[str, Any]], policy: Optional[Dict[str, Any]] = None, security_options: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    active_policy = normalize_security_policy(policy or security_options)
    return [mask_record(record, active_policy) for record in list(records or []) if isinstance(record, dict)]

def remove_internal_paths(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: remove_internal_paths(value)
            for key, value in payload.items()
            if not should_remove_public_key(key) and not _looks_like_local_path(value)
        }

    if isinstance(payload, list):
        return [
            item
            for item in (remove_internal_paths(item) for item in payload)
            if item not in ({}, [], "", None)
        ]

    if _looks_like_local_path(payload):
        return ""

    return payload

def remove_debug_fields(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: remove_debug_fields(value)
            for key, value in payload.items()
            if not should_remove_public_key(key)
        }

    if isinstance(payload, list):
        return [
            item
            for item in (remove_debug_fields(item) for item in payload)
            if item not in ({}, [], "", None)
        ]

    return payload


def remove_private_fields(payload: Any) -> Any:
    return remove_debug_fields(remove_internal_paths(payload))

def sanitize_public_payload(payload: Any, policy: Optional[Dict[str, Any]] = None, security_options: Optional[Dict[str, Any]] = None) -> Any:
    active_policy = normalize_security_policy(policy or security_options)
    value = json_safe(payload)

    if isinstance(value, dict):
        if is_data_quality_issue_record(value):
            return sanitize_data_quality_issue_record(value, active_policy)

        return sanitize_public_record(value, active_policy)

    if isinstance(value, list):
        sanitized_items = []

        for item in value:
            sanitized = sanitize_public_payload(item, active_policy)

            if sanitized in ({}, [], "", None):
                continue

            sanitized_items.append(sanitized)

        return sanitized_items

    if active_policy.get("remove_internal_paths", True) and _looks_like_local_path(value):
        return ""

    return value

def apply_masking_policy(payload: Any, policy: Optional[Dict[str, Any]] = None) -> Any:
    return sanitize_public_payload(payload, policy)

def create_package_checksum(payload: Any) -> str:
    normalized = normalize_package_checksum_payload(payload)
    stable = json.dumps(json_safe(normalized), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()

def create_snapshot_checksum(payload: Any) -> str:
    return create_package_checksum(payload)

def verify_package_checksum(payload: Any, checksum: Optional[str] = None) -> Any:
    if checksum is None and isinstance(payload, dict):
        checksum = clean_text(
            payload.get("checksum")
            or payload.get("package_checksum")
            or payload.get("snapshot_checksum")
            or payload.get("package_meta", {}).get("checksum")
            or payload.get("meta", {}).get("checksum")
        )

    expected = create_package_checksum(payload)
    valid = bool(checksum) and constant_time_equal(expected, clean_text(checksum))

    return {
        "valid": valid,
        "reason": "ok" if valid else "checksum_mismatch",
        "expected": expected,
        "actual": clean_text(checksum),
    }


def generate_package_access_token(package_id: str, scope: Optional[Any] = None, expires_at: Optional[Any] = None, expire_days: Optional[int] = None) -> str:
    normalized_scope = normalize_access_scope(scope or "data")
    if expires_at:
        expiry = clean_text(expires_at)
    else:
        days = max(1, min(int(expire_days or PACKAGE_DEFAULT_EXPIRE_DAYS or 30), int(PACKAGE_MAX_EXPIRE_DAYS or 365)))
        expiry = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    payload = {
        "v": TOKEN_VERSION,
        "package_id": clean_text(package_id),
        "scope": normalized_scope,
        "expires_at": expiry,
    }
    body = b64url_encode(payload)
    signature = hmac_signature(body)
    return f"{body}.{signature}"


def verify_package_access_token(token: str, package_id: Optional[str] = None, scope: Optional[Any] = None) -> Dict[str, Any]:
    try:
        token_text = clean_text(token)
        if not token_text or "." not in token_text:
            return {"valid": False, "reason": "missing_or_malformed_token"}
        body, signature = token_text.rsplit(".", 1)
        if not constant_time_equal(hmac_signature(body), signature):
            return {"valid": False, "reason": "invalid_signature"}
        payload = b64url_decode_json(body)
        if package_id and clean_text(payload.get("package_id")) != clean_text(package_id):
            return {"valid": False, "reason": "package_mismatch", "payload": payload}
        expected_scope = normalize_access_scope(scope) if scope else ""
        token_scope = normalize_access_scope(payload.get("scope"))
        if expected_scope and token_scope not in {expected_scope, "admin", "data"}:
            return {"valid": False, "reason": "scope_denied", "payload": payload}
        expires_at = clean_text(payload.get("expires_at"))
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) < datetime.now():
                    return {"valid": False, "reason": "token_expired", "payload": payload}
            except Exception:
                return {"valid": False, "reason": "invalid_expiry", "payload": payload}
        return {"valid": True, "reason": "ok", "payload": payload}
    except Exception as exc:
        return {"valid": False, "reason": "token_error", "error": clean_text(exc)}


def verify_access_token(token: str, expected_package_id: str = "", expected_scope: str = "") -> Dict[str, Any]:
    return verify_package_access_token(token, package_id=expected_package_id, scope=expected_scope)


def normalize_access_scope(scope: Optional[Any]) -> str:
    if isinstance(scope, (list, tuple, set)):
        first = next(iter(scope), "data")
        return normalize_access_scope(first)
    value = clean_text_lower(scope, default="data")
    return value if value in PACKAGE_ACCESS_SCOPES else "data"


def validate_package_access_scope(scope: Any, allowed_scopes: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    normalized = normalize_access_scope(scope)
    allowed = {normalize_access_scope(item) for item in (allowed_scopes or PACKAGE_ACCESS_SCOPES)}
    allowed.add("admin")
    return {
        "valid": normalized in allowed,
        "scope": normalized,
        "allowed_scopes": sorted(allowed),
        "reason": "ok" if normalized in allowed else "scope_not_allowed",
    }


def public_access_allowed(package_meta: Dict[str, Any], component: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
    meta = package_meta if isinstance(package_meta, dict) else {}
    if not meta:
        return {"allowed": False, "reason": "package_not_found"}
    if meta.get("enabled") is False or clean_text_lower(meta.get("status")) in {"disabled", "deleted"}:
        return {"allowed": False, "reason": "package_disabled"}
    expires_at = clean_text(meta.get("expires_at"))
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.now():
                return {"allowed": False, "reason": "package_expired"}
        except Exception:
            return {"allowed": False, "reason": "invalid_expiry"}
    requested_component = normalize_access_scope(component or "data")
    components = meta.get("components") or meta.get("public_components") or list(PACKAGE_ACCESS_SCOPES)
    scope_result = validate_package_access_scope(requested_component, components)
    if not scope_result.get("valid"):
        return {"allowed": False, "reason": scope_result.get("reason"), "component": requested_component}
    if meta.get("require_token") or (ENABLE_PACKAGE_ACCESS_TOKEN and token):
        token_result = verify_package_access_token(token or "", package_id=clean_text(meta.get("package_id")), scope=requested_component)
        if not token_result.get("valid"):
            return {"allowed": False, "reason": token_result.get("reason", "token_denied"), "component": requested_component}
    return {"allowed": True, "reason": "ok", "component": requested_component}


def build_public_package_url_meta(package_id: str, base_url: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
    clean_id = quote(clean_text(package_id), safe="")
    prefix = clean_text(base_url).rstrip("/")
    api_base = f"{prefix}/api/public/packages/{clean_id}" if prefix else f"/api/public/packages/{clean_id}"
    suffix = f"?token={quote(clean_text(token), safe='')}" if token else ""

    return {
        "package_id": clean_text(package_id),
        "public_url": f"{api_base}/data{suffix}",
        "meta_url": f"{api_base}/meta{suffix}",
        "data_url": f"{api_base}/data{suffix}",
        "summary_url": f"{api_base}/summary{suffix}",
        "map_url": f"{api_base}/map{suffix}",
        "charts_url": f"{api_base}/charts{suffix}",
        "tables_url": f"{api_base}/tables{suffix}",
        "data_quality_url": f"{api_base}/data-quality{suffix}",
        "prediction_url": f"{api_base}/prediction{suffix}",
        "entity_url": f"{api_base}/entity{suffix}",
        "expires_at": "",
    }

def build_public_viewer_metadata(package_id: str, package_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = sanitize_public_record(package_meta or {})
    url_meta = build_public_package_url_meta(package_id, token=meta.get("access_token") if meta.get("include_token_in_url") else None)
    return {
        "package_id": clean_text(package_id),
        "name": meta.get("name") or meta.get("package_name") or clean_text(package_id),
        "description": meta.get("description", ""),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", meta.get("created_at", "")),
        "status": meta.get("status", "active"),
        "enabled": meta.get("enabled", True),
        "public": meta.get("public", True),
        "expires_at": meta.get("expires_at", ""),
        "public_url_meta": url_meta,
    }


mask_company_tax_id = mask_tax_id
mask_director = mask_director_name
sanitize_package_payload = sanitize_public_payload
sanitize_external_payload = sanitize_public_payload
generate_access_token = generate_package_access_token
build_checksum = create_package_checksum
