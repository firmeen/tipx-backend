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
try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)
import base64
import hashlib
import hmac
import json
import re
import secrets
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import quote

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


# ============================================================
# 1) SECURITY CONSTANTS
# ============================================================

SENSITIVE_FIELD_GROUPS: Dict[str, List[str]] = {
    "tax_id": [
        "tax_id",
        "tax_id_raw",
        "tax_id_norm",
        "company_key",
        "record_key",
        "source_tax_id",
        "target_tax_id",
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
        "shared_directors",
        "shared_directors_text",
        "director_list",
        "key_connector",
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
    "charts",
    "tables",
    "data_quality",
    "filter_options",
]


PUBLIC_FORBIDDEN_INTERNAL_KEYS: List[str] = [
    "raw_file_path",
    "source_file_path",
    "internal_path",
    "cache_path",
    "cache_key",
    "local_path",
    "absolute_path",
    "path",
    "debug_raw",
    "raw_record",
    "raw_payload",
    "traceback",
    "password",
    "secret",
    "token",
    "access_token",
    "public_token",
    "token_secret",
    "package_token_salt",
    "secret_key",
    "private_key",
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

def mask_tax_id_substrings(value: Any, visible_last_digits: int = MASK_TAX_ID_VISIBLE_LAST_DIGITS) -> Any:
    """Mask 13-digit tax id substrings even when embedded in graph ids like company:<tax_id>."""

    if not isinstance(value, str):
        return value

    return re.sub(
        r"(?<!\d)(\d{13})(?!\d)",
        lambda match: mask_tax_id(match.group(1), visible_last_digits=visible_last_digits),
        value,
    )


def looks_like_thai_person_name(value: Any) -> bool:
    """Best-effort public export guard for Thai director/person labels."""

    text = clean_text(value)
    return text.startswith(("นาย", "นาง", "นางสาว", "พลเอก", "พล.ต.", "ดร."))


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

    # Frontend/API aliases. Keep config keys stable, but accept common public-package
    # request names so sanitization cannot be bypassed by naming mismatch.
    alias_map = {
        "mask_directors": "mask_director_name",
        "mask_director": "mask_director_name",
        "mask_people": "mask_director_name",
        "hide_addresses": "mask_address",
        "mask_addresses": "mask_address",
        "hide_financials": "hide_financial_fields",
        "mask_financials": "hide_financial_fields",
        "hide_financial": "hide_financial_fields",
    }

    normalized_incoming = dict(incoming)
    for alias, canonical in alias_map.items():
        if alias in incoming and canonical not in normalized_incoming:
            normalized_incoming[canonical] = incoming.get(alias)

    for key in base.keys():
        if key in normalized_incoming:
            base[key] = bool(to_bool(normalized_incoming.get(key), default=base[key]))

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
        current_type = clean_text_lower(
            payload.get("type")
            or payload.get("node_type")
            or payload.get("feature_type")
            or payload.get("entity_type")
        )

        for key, value in payload.items():
            if options.get("mask_tax_id") and is_tax_id_field(key):
                if isinstance(value, list):
                    masked[key] = [mask_tax_id(item, visible_last_digits=MASK_TAX_ID_VISIBLE_LAST_DIGITS) for item in value]
                elif isinstance(value, dict):
                    masked[key] = mask_nested_payload(value, security_options=options)
                else:
                    masked[key] = mask_tax_id(value, visible_last_digits=MASK_TAX_ID_VISIBLE_LAST_DIGITS)
                continue

            if options.get("mask_director_name") and is_director_field(key):
                if isinstance(value, list):
                    masked[key] = [mask_director_name(item) for item in value]
                elif isinstance(value, dict):
                    masked[key] = mask_nested_payload(value, security_options=options)
                else:
                    masked[key] = mask_director_name(value)
                continue

            if options.get("mask_director_name") and current_type == "director" and clean_text_lower(key) in {"label", "name", "title"}:
                masked[key] = mask_director_name(value)
                continue

            if isinstance(value, (dict, list)):
                masked[key] = mask_nested_payload(value, security_options=options)
            else:
                primitive_value = mask_record({key: value}, security_options=options).get(key)

                if isinstance(primitive_value, str):
                    if options.get("mask_tax_id"):
                        primitive_value = mask_tax_id_substrings(
                            primitive_value,
                            visible_last_digits=MASK_TAX_ID_VISIBLE_LAST_DIGITS,
                        )
                    if options.get("mask_director_name") and looks_like_thai_person_name(primitive_value):
                        primitive_value = mask_director_name(primitive_value)

                masked[key] = primitive_value

        return masked

    if isinstance(payload, str):
        result_value = payload

        if options.get("mask_tax_id"):
            result_value = mask_tax_id_substrings(
                result_value,
                visible_last_digits=MASK_TAX_ID_VISIBLE_LAST_DIGITS,
            )

        if options.get("mask_director_name") and looks_like_thai_person_name(result_value):
            result_value = mask_director_name(result_value)

        return result_value

    return payload


# ============================================================
# 5) SANITIZE INTERNAL PAYLOAD
# ============================================================

def redact_internal_string(value: Any) -> Any:
    """Redact local filesystem paths and obvious secret fragments inside public strings."""

    if not isinstance(value, str):
        return value

    lowered = value.lower()
    risky_markers = [
        "c:/users/",
        "c:\\users\\",
        "/mnt/data",
        "portable_libs",
        "private_key",
        "secret-token",
    ]

    if any(marker in lowered for marker in risky_markers):
        return "[redacted internal value]"

    return value


def remove_internal_keys(payload: Any) -> Any:
    """
    ลบ key ภายในที่ไม่ควรถูกส่งออกไปยัง external viewer

    เช่น:
    - local path
    - cache path
    - secret
    - token salt
    """

    if isinstance(payload, list):
        return [remove_internal_keys(item) for item in payload]

    if isinstance(payload, dict):
        result: Dict[str, Any] = {}

        for key, value in payload.items():
            key_lower = clean_text_lower(key)

            should_remove = False

            for forbidden in PUBLIC_FORBIDDEN_INTERNAL_KEYS:
                if forbidden in key_lower:
                    should_remove = True
                    break

            if should_remove:
                continue

            result[key] = remove_internal_keys(value)

        return result

    return redact_internal_string(payload)


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

    safe_id = quote(clean_text(package_id))

    return {
        "meta": f"{public_prefix}/packages/{safe_id}/meta",
        "data": f"{public_prefix}/packages/{safe_id}/data",
        "summary": f"{public_prefix}/packages/{safe_id}/summary",
        "map": f"{public_prefix}/packages/{safe_id}/map",
        "charts": f"{public_prefix}/packages/{safe_id}/charts",
        "tables": f"{public_prefix}/packages/{safe_id}/tables",
        "access_log": f"{public_prefix}/packages/{safe_id}/access-log",
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
    package_name: str,
    description: str = "",
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
    """

    days = to_int(expire_days, default=PACKAGE_DEFAULT_EXPIRE_DAYS) or PACKAGE_DEFAULT_EXPIRE_DAYS
    days = max(1, min(days, PACKAGE_MAX_EXPIRE_DAYS))

    expire_at = datetime.now() + timedelta(days=days)

    safe_security = normalize_security_options(security_options)
    safe_components = sanitize_package_components(components)
    safe_filters = sanitize_package_filters(filters or {})

    token = generate_package_access_token(
        package_id=package_id,
        expire_days=days,
        scope=["read"],
        read_only=True,
    )

    public_url = build_public_package_url(
        package_id=package_id,
        base_url=base_url,
        include_token=ENABLE_PACKAGE_ACCESS_TOKEN,
        token=token,
    )

    return {
        "package_id": package_id,
        "package_name": clean_text(package_name, default=package_id),
        "description": clean_text(description),
        "created_at": now_iso(),
        "created_by": clean_text(created_by, default="system"),
        "expire_at": expire_at.isoformat(timespec="seconds"),
        "status": "active",
        "allow_public_access": bool(allow_public_access),
        "read_only": PUBLIC_PACKAGE_READ_ONLY,
        "components": safe_components,
        "filters": safe_filters,
        "security": safe_security,
        "public_url": public_url,
        "public_api_urls": build_public_api_urls(package_id),
        "access_token_enabled": ENABLE_PACKAGE_ACCESS_TOKEN,
        "access_token": token if ENABLE_PACKAGE_ACCESS_TOKEN else "",
        "record_counts": {},
        "files": [],
        "checksum": "",
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

    ไม่รวม field checksum เอง
    """

    payload = deepcopy(package_payload)

    if isinstance(payload.get("package_meta"), dict):
        payload["package_meta"].pop("checksum", None)

    payload.pop("checksum", None)

    return sha256_payload(payload)


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
    required_scope: str = "read",
) -> Dict[str, Any]:
    """
    ตรวจสิทธิ์การเปิด package ใน external viewer

    Logic:
    1. ตรวจ status / expire / allow_public_access
    2. ถ้า ENABLE_PACKAGE_ACCESS_TOKEN = True ต้อง verify token
    3. ถ้า token disabled ให้ผ่านเมื่อ package active
    """

    access_status = is_package_publicly_accessible(package_meta)

    if not access_status.get("allowed"):
        return {
            "allowed": False,
            "reason": access_status.get("reason"),
            "token": {
                "required": ENABLE_PACKAGE_ACCESS_TOKEN,
                "valid": False,
            },
        }

    if not ENABLE_PACKAGE_ACCESS_TOKEN:
        return {
            "allowed": True,
            "reason": "public_access_allowed_without_token",
            "token": {
                "required": False,
                "valid": True,
            },
        }

    verification = verify_access_token(
        token,
        expected_package_id=package_meta.get("package_id"),
        required_scope=required_scope,
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
        "token": {
            "required": True,
            "valid": True,
            "verification": verification,
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

    Input:
    - package_snapshot ภายในที่ generate แล้ว

    Output:
    - snapshot ที่ sanitize แล้ว
    - masked แล้ว
    - ลบ internal key แล้ว
    - ตรวจ access แล้ว
    """

    if not isinstance(package_snapshot, dict):
        return {
            "allowed": False,
            "reason": "invalid_package_snapshot",
            "data": {},
        }

    package_meta = package_snapshot.get("package_meta", {})

    access = check_public_package_access(
        package_meta=package_meta,
        token=token,
        required_scope="read",
    )

    if not access.get("allowed"):
        return {
            "allowed": False,
            "reason": access.get("reason"),
            "access": access,
            "data": {},
        }

    security_options = package_meta.get("security", PACKAGE_SECURITY_OPTIONS)

    public_snapshot = sanitize_public_payload(
        package_snapshot,
        security_options=security_options,
    )

    if isinstance(public_snapshot, dict):
        public_snapshot.setdefault("public_meta", {})
        public_snapshot["public_meta"].update(
            {
                "read_only": PUBLIC_PACKAGE_READ_ONLY,
                "access_checked_at": now_iso(),
                "token_required": ENABLE_PACKAGE_ACCESS_TOKEN,
                "components": package_meta.get("components", []),
            }
        )

        if isinstance(public_snapshot.get("package_meta"), dict):
            public_snapshot["package_meta"].pop("access_token", None)
            public_snapshot["package_meta"].pop("checksum_raw", None)

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

    component เช่น:
    - summary
    - map
    - charts
    - tables
    """

    public_result = build_public_package_snapshot(
        package_snapshot=package_snapshot,
        token=token,
    )

    if not public_result.get("allowed"):
        return public_result

    data = public_result.get("data", {})
    component_key = clean_text(component)

    if component_key == "meta":
        component_data = data.get("package_meta", {})
    elif component_key == "summary":
        component_data = data.get("data", {}).get("summary", data.get("summary", {}))
    elif component_key == "map":
        component_data = data.get("data", {}).get("map_layers", data.get("map_layers", {}))
    elif component_key == "charts":
        component_data = data.get("data", {}).get("charts", data.get("charts", {}))
    elif component_key == "tables":
        component_data = data.get("data", {}).get("tables", data.get("tables", {}))
    else:
        component_data = data.get("data", {}).get(component_key, data.get(component_key, {}))

    return {
        "allowed": True,
        "reason": "ok",
        "access": public_result.get("access", {}),
        "data": component_data,
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

    result: Dict[str, Any] = {}

    for component in allowed:
        if component in data:
            result[component] = data[component]

    return result


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

    ต่างจาก mask_record:
    - ถ้า hide financial fields จะลบ field ออกจาก record
    - mask_record จะยังเก็บ key แต่ค่าเป็น None
    """

    options = normalize_security_options(security_options)
    policy = get_export_field_policy(options)

    result = mask_record(record, options)

    for hidden_field in policy["hidden_fields"]:
        if hidden_field in result:
            result.pop(hidden_field, None)

    return result


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

    ไม่คืน access_token
    ไม่คืน internal path
    """

    if not isinstance(package_meta, dict):
        return {}

    meta = sanitize_public_payload(package_meta, security_options=package_meta.get("security", {}))

    if isinstance(meta, dict):
        meta.pop("access_token", None)
        meta.pop("internal_path", None)
        meta.pop("cache_path", None)
        meta.pop("local_path", None)

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
        "access_token_enabled": ENABLE_PACKAGE_ACCESS_TOKEN,
        "token_version": TOKEN_VERSION,
        "masking": {
            "tax_id_visible_last_digits": MASK_TAX_ID_VISIBLE_LAST_DIGITS,
            "director_visible_first_chars": MASK_DIRECTOR_VISIBLE_FIRST_CHARS,
            "default_security_options": PACKAGE_SECURITY_OPTIONS,
        },
        "public_allowed_components": PUBLIC_ALLOWED_PACKAGE_COMPONENTS,
        "package_status_values": PACKAGE_STATUS_VALUES,
        "checked_at": now_iso(),
    }


# ============================================================
# 16) QUICK SELF TEST
# ============================================================

def run_security_self_test() -> Dict[str, Any]:
    """
    self test แบบเบื้องต้นสำหรับ security.py

    ใช้ debug ได้โดย import แล้วเรียก:
        from security import run_security_self_test
        print(run_security_self_test())
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

    return {
        "token_generated": bool(token),
        "token_verify_valid": verify.get("valid"),
        "token_verify_reason": verify.get("reason"),
        "sample_record": sample_record,
        "masked_record": masked,
        "summary": get_security_summary(),
    }