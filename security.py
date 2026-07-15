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
from typing import Any, Dict, Iterable, List, Optional, Union
from urllib.parse import quote, unquote

from config import (
    APP_SHORT_NAME,
    APP_VERSION,
    PUBLIC_API_PREFIX,
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
    normalize_tax_id,
    now_iso,
    to_jsonable,
    to_bool,
    to_int,
    make_hash_id,
    validate_coordinate,
)

CONFIG_LOADED = True
UTILS_LOADED = True

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
MAX_PACKAGE_TOKEN_LENGTH: int = 8192
MAX_PACKAGE_TOKEN_BODY_LENGTH: int = 6144
TOKEN_CLOCK_SKEW_SECONDS: int = 300
MIN_SECURITY_SECRET_LENGTH: int = 16


# ============================================================
# 2) BASIC HASH / SIGNATURE HELPERS
# ============================================================

def get_security_secret() -> bytes:
    """
    คืน secret key สำหรับ HMAC package token
    """

    secret_key = clean_text(
        SECRET_KEY
    )
    token_salt = clean_text(
        PACKAGE_TOKEN_SALT
    )

    if (
        len(secret_key)
        < MIN_SECURITY_SECRET_LENGTH
    ):
        raise RuntimeError(
            "TIPX_SECRET_KEY is not configured "
            "or is too short."
        )

    if (
        len(token_salt)
        < MIN_SECURITY_SECRET_LENGTH
    ):
        raise RuntimeError(
            "TIPX_PACKAGE_TOKEN_SALT is not "
            "configured or is too short."
        )

    material = (
        "TIPX_PACKAGE_ACCESS"
        f"|{TOKEN_VERSION}"
        f"|{secret_key}"
        f"|{token_salt}"
    )

    return material.encode(
        "utf-8"
    )

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

def b64url_decode(
    value: str,
) -> bytes:
    """
    decode base64 url-safe string
    """

    text = clean_text(
        value
    )

    if not text:
        raise ValueError(
            "Empty base64 payload."
        )

    if (
        len(text)
        > MAX_PACKAGE_TOKEN_BODY_LENGTH
    ):
        raise ValueError(
            "Base64 payload is too large."
        )

    if any(
        not (
            character.isalnum()
            or character in {
                "-",
                "_",
            }
        )
        for character in text
    ):
        raise ValueError(
            "Invalid base64url characters."
        )

    padding = "=" * (
        -len(text) % 4
    )

    return base64.b64decode(
        (text + padding).encode(
            "ascii"
        ),
        altchars=b"-_",
        validate=True,
    )


def b64url_decode_json(
    value: str,
) -> Dict[str, Any]:
    """
    decode base64 url-safe string
    เป็น JSON dict
    """

    try:
        raw = b64url_decode(
            value
        )

        if len(raw) > 4096:
            return {}

        data = json.loads(
            raw.decode("utf-8")
        )

    except (
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return {}

    return (
        data
        if isinstance(data, dict)
        else {}
    )


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


def sanitize_package_components(
    components: Optional[List[str]],
) -> List[str]:
    """
    sanitize component list สำหรับ package
    """

    if not components:
        return list(
            PUBLIC_ALLOWED_PACKAGE_COMPONENTS
        )

    allowed = set(
        PUBLIC_ALLOWED_PACKAGE_COMPONENTS
    )

    result: List[str] = []

    for component in components:
        item = (
            clean_text_lower(
                component
            )
            .replace(
                "-",
                "_",
            )
        )

        if (
            not item
            or item not in allowed
            or item in result
        ):
            continue

        result.append(item)

    return result


def sanitize_package_filters(
    filters: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    sanitize filter payload ที่บันทึกใน package
    """

    if not isinstance(
        filters,
        dict,
    ):
        return {}

    policy = normalize_security_policy(
        {
            **PACKAGE_SECURITY_OPTIONS,
            "public": True,
            "remove_internal_paths": True,
            "remove_debug_fields": True,
        }
    )

    sanitized = sanitize_public_payload(
        filters,
        policy=policy,
    )

    return (
        sanitized
        if isinstance(
            sanitized,
            dict,
        )
        else {}
    )

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

def normalize_package_status(
    status: Any,
) -> str:
    """
    normalize package status
    """

    text = clean_text_lower(
        status
    )

    if not text:
        return "active"

    if text in PACKAGE_STATUS_VALUES:
        return text

    return "disabled"


def parse_security_datetime(
    value: Any,
) -> Optional[datetime]:
    text = clean_text(
        value
    )

    if not text:
        return None

    if text.endswith("Z"):
        text = (
            text[:-1]
            + "+00:00"
        )

    try:
        return datetime.fromisoformat(
            text
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def is_package_expired(
    package_meta: Dict[str, Any],
) -> bool:
    """
    ตรวจว่า package หมดอายุหรือยัง
    """

    if not isinstance(
        package_meta,
        dict,
    ):
        return True

    expire_at_raw = (
        package_meta.get(
            "expires_at"
        )
        or package_meta.get(
            "expire_at"
        )
    )

    if not expire_at_raw:
        return False

    expire_at = (
        parse_security_datetime(
            expire_at_raw
        )
    )

    if expire_at is None:
        return True

    current_time = (
        datetime.now(
            expire_at.tzinfo
        )
        if expire_at.tzinfo
        is not None
        else datetime.now()
    )

    return (
        current_time
        >= expire_at
    )


def is_package_publicly_accessible(
    package_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """
    ตรวจว่า package สามารถเปิดใน
    external viewer ได้หรือไม่
    """

    if not isinstance(
        package_meta,
        dict,
    ) or not package_meta:
        return {
            "allowed": False,
            "reason": (
                "package_not_found"
            ),
        }

    if not to_bool(
        package_meta.get(
            "enabled",
            True,
        ),
        default=True,
    ):
        return {
            "allowed": False,
            "reason": (
                "package_disabled"
            ),
        }

    status = normalize_package_status(
        package_meta.get(
            "status",
            "active",
        )
    )

    if status != "active":
        return {
            "allowed": False,
            "reason": (
                f"package_status_{status}"
            ),
        }

    if is_package_expired(
        package_meta
    ):
        return {
            "allowed": False,
            "reason": (
                "package_expired"
            ),
        }

    allow_public_access = to_bool(
        package_meta.get(
            "allow_public_access",
            package_meta.get(
                "public",
                False,
            ),
        ),
        default=False,
    )

    if not allow_public_access:
        return {
            "allowed": False,
            "reason": (
                "public_access_disabled"
            ),
        }

    if (
        PUBLIC_PACKAGE_READ_ONLY
        and not to_bool(
            package_meta.get(
                "read_only",
                True,
            ),
            default=True,
        )
    ):
        return {
            "allowed": False,
            "reason": (
                "package_not_read_only"
            ),
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
    """

    safe_id = quote(
        clean_text(package_id),
        safe="",
    )

    if base_url:
        url = (
            f"{base_url.rstrip('/')}"
            f"/external/{safe_id}"
        )
    else:
        url = (
            f"/external/{safe_id}"
        )

    return url


def build_public_api_urls(
    package_id: str,
    public_prefix: str = (
        PUBLIC_API_PREFIX
    ),
) -> Dict[str, str]:
    """
    สร้าง public API URL ของ package
    """

    safe_id = quote(
        clean_text(package_id),
        safe="",
    )

    prefix = (
        clean_text(
            public_prefix,
            PUBLIC_API_PREFIX,
        ).rstrip("/")
    )

    base = (
        f"{prefix}/packages/"
        f"{safe_id}"
    )

    return {
        "meta": f"{base}/meta",
        "data": f"{base}/data",
        "summary": (
            f"{base}/summary"
        ),
        "map": f"{base}/map",
        "charts": f"{base}/charts",
        "tables": f"{base}/tables",
        "data_quality": (
            f"{base}/data-quality"
        ),
        "prediction": (
            f"{base}/prediction"
        ),
        "entity": (
            f"{base}/entity"
        ),
        "access_log": (
            f"{base}/access-log"
        ),
    }

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
    filters: Optional[
        Dict[str, Any]
    ] = None,
    components: Optional[
        List[str]
    ] = None,
    security_options: Optional[
        Dict[str, Any]
    ] = None,
    expire_days: Optional[int] = None,
    created_by: str = "system",
    allow_public_access: bool = True,
    base_url: str = "",
) -> Dict[str, Any]:
    """
    สร้าง package meta มาตรฐาน

    รองรับ call แบบ:
    - build_package_meta(
        package_id,
        package_name,
        description,
      )
    - build_package_meta(
        package_id,
        request_dict,
        snapshot_dict,
      )
    """

    clean_package_id = clean_text(
        package_id
    )

    if (
        not clean_package_id
        or len(clean_package_id) > 128
        or Path(
            clean_package_id
        ).name
        != clean_package_id
    ):
        raise ValueError(
            "Invalid package_id."
        )

    request: Dict[str, Any] = {}
    snapshot: Dict[str, Any] = {}

    if isinstance(
        package_name,
        dict,
    ):
        request = dict(
            package_name
        )

        if isinstance(
            description,
            dict,
        ):
            snapshot = dict(
                description
            )

        package_name = (
            request.get(
                "package_name"
            )
            or request.get("name")
            or clean_package_id
        )

        description = request.get(
            "description",
            "",
        )

        filters = request.get(
            "filters",
            filters or {},
        )

        components = request.get(
            "components",
            components,
        )

        security_options = (
            request.get(
                "security",
                security_options,
            )
        )

        expire_days = (
            request.get(
                "expire_days"
            )
            or request.get(
                "expires_days"
            )
            or expire_days
        )

        created_by = request.get(
            "created_by",
            created_by,
        )

        allow_public_access = (
            to_bool(
                request.get(
                    "allow_public_access",
                    request.get(
                        "public",
                        allow_public_access,
                    ),
                ),
                default=bool(
                    allow_public_access
                ),
            )
        )

        base_url = clean_text(
            request.get(
                "base_url",
                base_url,
            )
        )

    days = to_int(
        expire_days,
        default=(
            PACKAGE_DEFAULT_EXPIRE_DAYS
        ),
    )

    if days <= 0:
        days = (
            PACKAGE_DEFAULT_EXPIRE_DAYS
        )

    days = max(
        1,
        min(
            days,
            PACKAGE_MAX_EXPIRE_DAYS,
        ),
    )

    created_at = now_iso()

    expire_at = (
        datetime.now()
        + timedelta(days=days)
    )

    safe_security = (
        normalize_security_policy(
            security_options
        )
    )

    safe_security["public"] = True
    safe_security[
        "mask_tax_id"
    ] = True
    safe_security[
        "mask_director_name"
    ] = True
    safe_security[
        "mask_person_name"
    ] = True
    safe_security[
        "mask_address"
    ] = True
    safe_security[
        "remove_internal_paths"
    ] = True
    safe_security[
        "remove_debug_fields"
    ] = True

    safe_components = (
        sanitize_package_components(
            components
        )
    )

    safe_filters = (
        sanitize_package_filters(
            filters or {}
        )
    )

    token = ""

    if ENABLE_PACKAGE_ACCESS_TOKEN:
        token = (
            generate_package_access_token(
                package_id=(
                    clean_package_id
                ),
                expire_days=days,
                scope=["data"],
            )
        )

    public_url = (
        build_public_package_url(
            package_id=(
                clean_package_id
            ),
            base_url=base_url,
            include_token=False,
            token="",
        )
    )

    checksum = clean_text(
        snapshot.get("checksum")
        or snapshot.get(
            "package_checksum"
        )
        or snapshot.get(
            "snapshot_checksum"
        )
    )

    require_token = bool(
        ENABLE_PACKAGE_ACCESS_TOKEN
        and allow_public_access
    )

    return {
        "package_id": (
            clean_package_id
        ),
        "package_name": clean_text(
            package_name,
            default=clean_package_id,
        ),
        "name": clean_text(
            package_name,
            default=clean_package_id,
        ),
        "description": clean_text(
            description
        ),
        "created_at": created_at,
        "updated_at": created_at,
        "created_by": clean_text(
            created_by,
            default="system",
        ),
        "expire_at": (
            expire_at.isoformat(
                timespec="seconds"
            )
        ),
        "expires_at": (
            expire_at.isoformat(
                timespec="seconds"
            )
        ),
        "status": "active",
        "enabled": True,
        "allow_public_access": bool(
            allow_public_access
        ),
        "public": bool(
            allow_public_access
        ),
        "read_only": (
            PUBLIC_PACKAGE_READ_ONLY
        ),
        "snapshot_only": True,
        "package_source": (
            "cache_snapshot"
        ),
        "public_viewer_source": (
            "public_data_json_only"
        ),
        "components": safe_components,
        "filters": safe_filters,
        "security": safe_security,
        "public_url": public_url,
        "public_api_urls": (
            build_public_api_urls(
                clean_package_id
            )
        ),
        "public_urls": (
            build_public_package_url_meta(
                clean_package_id,
                base_url=base_url,
            )
        ),
        "access_token_enabled": bool(
            ENABLE_PACKAGE_ACCESS_TOKEN
        ),
        "access_token": token,
        "require_token": require_token,
        "record_counts": {},
        "files": [],
        "checksum": checksum,
        "checksum_components": (
            PACKAGE_CHECKSUM_COMPONENTS
        ),
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

# ============================================================
# 9) PACKAGE ACCESS CHECK
# ============================================================

def check_public_package_access(
    package_meta: Dict[str, Any],
    token: str = "",
    required_scope: str = "data",
) -> Dict[str, Any]:
    """
    ตรวจสิทธิ์การเปิด package
    ใน external viewer
    """

    result = public_access_allowed(
        package_meta=package_meta,
        component=required_scope,
        token=token,
    )

    token_required = bool(
        to_bool(
            (
                package_meta.get(
                    "require_token"
                )
                if isinstance(
                    package_meta,
                    dict,
                )
                else False
            ),
            default=(
                ENABLE_PACKAGE_ACCESS_TOKEN
            ),
        )
    )

    return {
        "allowed": bool(
            result.get(
                "allowed",
                False,
            )
        ),
        "reason": clean_text(
            result.get("reason"),
            "access_denied",
        ),
        "component": result.get(
            "component",
            normalize_access_scope(
                required_scope
            ),
        ),
        "token": {
            "required": token_required,
            "valid": bool(
                result.get(
                    "token_valid",
                    not token_required,
                )
            ),
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
    สร้าง public snapshot สำหรับ
    external viewer
    """

    if not isinstance(
        package_snapshot,
        dict,
    ):
        return {
            "allowed": False,
            "reason": (
                "invalid_package_snapshot"
            ),
            "data": {},
        }

    package_meta = (
        package_snapshot.get(
            "package_meta"
        )
        or package_snapshot.get(
            "meta"
        )
        or {}
    )

    if not isinstance(
        package_meta,
        dict,
    ) or not package_meta:
        return {
            "allowed": False,
            "reason": (
                "package_meta_missing"
            ),
            "data": {},
        }

    package_id = clean_text(
        package_meta.get(
            "package_id"
        )
        or package_snapshot.get(
            "package_id"
        )
    )

    if not package_id:
        return {
            "allowed": False,
            "reason": (
                "package_id_missing"
            ),
            "data": {},
        }

    snapshot_package_id = clean_text(
        package_snapshot.get(
            "package_id"
        )
    )

    if (
        snapshot_package_id
        and snapshot_package_id
        != package_id
    ):
        return {
            "allowed": False,
            "reason": (
                "package_id_mismatch"
            ),
            "data": {},
        }

    checksum = clean_text(
        package_snapshot.get(
            "checksum"
        )
        or package_meta.get(
            "checksum"
        )
    )

    if not checksum:
        return {
            "allowed": False,
            "reason": (
                "package_checksum_missing"
            ),
            "data": {},
        }

    checksum_result = (
        verify_package_checksum(
            package_snapshot,
            checksum=checksum,
        )
    )

    if not checksum_result.get(
        "valid"
    ):
        return {
            "allowed": False,
            "reason": (
                "package_checksum_invalid"
            ),
            "data": {},
        }

    access = (
        check_public_package_access(
            package_meta=package_meta,
            token=token,
            required_scope="data",
        )
    )

    if not access.get("allowed"):
        return {
            "allowed": False,
            "reason": access.get(
                "reason",
                "access_denied",
            ),
            "access": access,
            "data": {},
        }

    security_options = (
        normalize_security_policy(
            package_meta.get(
                "security",
                PACKAGE_SECURITY_OPTIONS,
            )
        )
    )

    snapshot_source = deepcopy(
        package_snapshot
    )

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
        snapshot_source.pop(
            key,
            None,
        )

    selected_components = (
        sanitize_package_components(
            package_meta.get(
                "components"
            )
        )
    )

    source_data = (
        snapshot_source.get(
            "data",
            {},
        )
        if isinstance(
            snapshot_source.get(
                "data"
            ),
            dict,
        )
        else {}
    )

    snapshot_source["data"] = (
        filter_package_data_by_components(
            source_data,
            selected_components,
        )
    )

    public_snapshot = (
        sanitize_public_payload(
            snapshot_source,
            policy=security_options,
        )
    )

    if not isinstance(
        public_snapshot,
        dict,
    ):
        return {
            "allowed": False,
            "reason": (
                "public_snapshot_invalid"
            ),
            "data": {},
        }

    safe_meta = (
        build_safe_public_meta(
            package_meta
        )
    )

    safe_meta.update(
        {
            "package_id": package_id,
            "checksum": checksum,
            "checksum_components": (
                PACKAGE_CHECKSUM_COMPONENTS
            ),
            "read_only": (
                PUBLIC_PACKAGE_READ_ONLY
            ),
            "snapshot_only": True,
        }
    )

    public_snapshot[
        "package_meta"
    ] = safe_meta

    public_snapshot.setdefault(
        "public_meta",
        {},
    )

    public_snapshot[
        "public_meta"
    ].update(
        {
            "read_only": (
                PUBLIC_PACKAGE_READ_ONLY
            ),
            "snapshot_only": True,
            "access_checked_at": (
                now_iso()
            ),
            "token_required": bool(
                to_bool(
                    package_meta.get(
                        "require_token"
                    ),
                    default=(
                        ENABLE_PACKAGE_ACCESS_TOKEN
                    ),
                )
            ),
            "components": (
                selected_components
            ),
            "checksum_components": (
                PACKAGE_CHECKSUM_COMPONENTS
            ),
            "public_viewer_source": (
                "public_data_json_only"
            ),
            "public_viewer_reads_raw_cache": (
                False
            ),
            "public_viewer_reads_raw_excel": (
                False
            ),
        }
    )

    safe_access = {
        "allowed": True,
        "reason": access.get(
            "reason",
            "ok",
        ),
        "component": access.get(
            "component",
            "data",
        ),
        "token": {
            "required": (
                access.get(
                    "token",
                    {},
                ).get(
                    "required",
                    False,
                )
            ),
            "valid": (
                access.get(
                    "token",
                    {},
                ).get(
                    "valid",
                    True,
                )
            ),
        },
    }

    return {
        "allowed": True,
        "reason": "ok",
        "access": safe_access,
        "data": public_snapshot,
    }

def extract_public_package_component(
    package_snapshot: Dict[str, Any],
    component: str,
    token: str = "",
) -> Dict[str, Any]:
    """
    ดึง component เฉพาะจาก
    package snapshot
    """

    component_key = (
        clean_text_lower(
            component,
            default="data",
        )
        .replace(
            "-",
            "_",
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
            component_key,
            component_key,
        )
    )

    package_meta = (
        package_snapshot.get(
            "package_meta"
        )
        or package_snapshot.get(
            "meta"
        )
        or {}
        if isinstance(
            package_snapshot,
            dict,
        )
        else {}
    )

    component_access = (
        public_access_allowed(
            package_meta=package_meta,
            component=(
                canonical_component
            ),
            token=token,
        )
    )

    if not component_access.get(
        "allowed"
    ):
        return {
            "allowed": False,
            "reason": (
                component_access.get(
                    "reason",
                    "access_denied",
                )
            ),
            "access": (
                component_access
            ),
            "data": {},
        }

    public_result = (
        build_public_package_snapshot(
            package_snapshot=(
                package_snapshot
            ),
            token=token,
        )
    )

    if not public_result.get(
        "allowed"
    ):
        return public_result

    data = public_result.get(
        "data",
        {},
    )

    root_data = (
        data.get(
            "data",
            {},
        )
        if (
            isinstance(data, dict)
            and isinstance(
                data.get("data"),
                dict,
            )
        )
        else {}
    )

    if component_key == "data":
        component_data = data

    elif component_key == "meta":
        component_data = (
            data.get(
                "package_meta",
                data.get("meta", {}),
            )
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    elif component_key == (
        "flood_prediction_map"
    ):
        component_data = (
            root_data.get(
                "flood_prediction_map"
            )
            or data.get(
                "flood_prediction_map"
            )
            or {}
        )

    elif canonical_component == "map":
        component_data = (
            root_data.get(
                component_key
            )
            or root_data.get("map")
            or root_data.get(
                "map_layers"
            )
            or data.get(
                component_key
            )
            or data.get("map")
            or data.get(
                "map_layers"
            )
            or {}
        )

    elif canonical_component == (
        "prediction"
    ):
        component_data = (
            root_data.get(
                component_key
            )
            or root_data.get(
                "prediction"
            )
            or root_data.get(
                "flood_prediction"
            )
            or root_data.get(
                "flood_prediction_latest"
            )
            or data.get(
                component_key
            )
            or data.get(
                "prediction"
            )
            or {}
        )

    elif canonical_component == (
        "entity"
    ):
        component_data = (
            root_data.get(
                component_key
            )
            or root_data.get("entity")
            or root_data.get(
                "uploaded_entity"
            )
            or root_data.get(
                "uploaded_entity_latest"
            )
            or data.get(
                component_key
            )
            or data.get("entity")
            or {}
        )

    else:
        component_data = (
            root_data.get(
                canonical_component
            )
            or data.get(
                canonical_component,
                {},
            )
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    security_options = (
        package_meta.get(
            "security",
            PACKAGE_SECURITY_OPTIONS,
        )
        if isinstance(
            package_meta,
            dict,
        )
        else PACKAGE_SECURITY_OPTIONS
    )

    return {
        "allowed": True,
        "reason": "ok",
        "access": {
            "allowed": True,
            "reason": (
                component_access.get(
                    "reason",
                    "ok",
                )
            ),
            "component": (
                canonical_component
            ),
        },
        "component": (
            canonical_component
        ),
        "requested_component": (
            component_key
        ),
        "data": sanitize_public_payload(
            component_data,
            policy=security_options,
        ),
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
    extra: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    """
    สร้าง access log record
    สำหรับ external package
    """

    clean_package_id = clean_text(
        package_id
    )

    clean_remote_addr = clean_text(
        remote_addr
    )

    clean_user_agent = clean_text(
        user_agent
    )[:500]

    accessed_at = now_iso()

    entropy = secrets.token_hex(
        8
    )

    key = (
        f"{clean_package_id}"
        f"|{clean_remote_addr}"
        f"|{clean_user_agent}"
        f"|{action}"
        f"|{accessed_at}"
        f"|{entropy}"
    )

    sanitized_extra = (
        remove_private_fields(
            extra or {}
        )
    )

    return {
        "log_id": make_hash_id(
            key,
            prefix="access",
            length=20,
        ),
        "package_id": (
            clean_package_id
        ),
        "action": clean_text(
            action,
            default="view",
        ),
        "allowed": bool(allowed),
        "reason": clean_text(
            reason,
            default="ok",
        )[:200],
        "remote_addr": "",
        "remote_addr_hash": (
            sha256_text(
                clean_remote_addr
            )[:16]
            if clean_remote_addr
            else ""
        ),
        "user_agent": "",
        "user_agent_hash": (
            sha256_text(
                clean_user_agent
            )[:16]
            if clean_user_agent
            else ""
        ),
        "accessed_at": (
            accessed_at
        ),
        "extra": to_jsonable(
            sanitized_extra
        ),
    }

# ============================================================
# 13) FIELD-LEVEL EXPORT POLICY
# ============================================================

def get_export_field_policy(
    security_options: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    """
    คืน policy การ export field
    """

    options = (
        normalize_security_policy(
            security_options
        )
    )

    hidden_fields: List[str] = []
    masked_fields: Dict[
        str,
        str,
    ] = {}

    if options.get("mask_tax_id"):
        for field in TAX_ID_FIELDS:
            masked_fields[
                field
            ] = "tax_id_mask"

    if options.get(
        "mask_director_name"
    ):
        for field in (
            DIRECTOR_PERSON_FIELDS
        ):
            masked_fields[
                field
            ] = (
                "director_name_mask"
            )

    if options.get("mask_address"):
        for field in ADDRESS_FIELDS:
            masked_fields[
                field
            ] = "address_mask"

    if options.get(
        "hide_financial_fields"
    ):
        hidden_fields.extend(
            FINANCIAL_FIELDS
        )

    return {
        "security_options": options,
        "hidden_fields": sorted(
            set(hidden_fields)
        ),
        "masked_fields": (
            masked_fields
        ),
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
    สร้าง error object สำหรับ
    public package API
    """

    safe_reason = clean_text(
        reason,
        default="access_denied",
    )[:200]

    if _looks_like_local_path(
        safe_reason
    ):
        safe_reason = (
            "access_denied"
        )

    return {
        "status": clean_text(
            status,
            default="denied",
        ),
        "allowed": False,
        "reason": safe_reason,
        "package_id": clean_text(
            package_id
        ),
        "timestamp": now_iso(),
    }


def build_public_success(
    data: Any,
    package_id: str = "",
    component: str = "",
) -> Dict[str, Any]:
    """
    สร้าง success object สำหรับ
    public package API
    """

    return {
        "status": "ok",
        "allowed": True,
        "package_id": clean_text(
            package_id
        ),
        "component": clean_text(
            component
        ),
        "timestamp": now_iso(),
        "data": sanitize_public_payload(
            data
        ),
    }

# ============================================================
# 15) MODULE HEALTH
# ============================================================

def get_security_summary() -> Dict[str, Any]:
    """
    คืน summary ของ security module
    """

    secret_key_configured = bool(
        len(
            clean_text(
                SECRET_KEY
            )
        )
        >= MIN_SECURITY_SECRET_LENGTH
    )

    token_salt_configured = bool(
        len(
            clean_text(
                PACKAGE_TOKEN_SALT
            )
        )
        >= MIN_SECURITY_SECRET_LENGTH
    )

    token_security_ready = bool(
        not ENABLE_PACKAGE_ACCESS_TOKEN
        or (
            secret_key_configured
            and token_salt_configured
        )
    )

    return {
        "module": "security",
        "ready": token_security_ready,
        "app": APP_SHORT_NAME,
        "version": APP_VERSION,
        "public_package_read_only": (
            PUBLIC_PACKAGE_READ_ONLY
        ),
        "snapshot_only_public_viewer": (
            True
        ),
        "public_viewer_source": (
            "public_data_json_only"
        ),
        "public_viewer_reads_raw_cache": (
            False
        ),
        "public_viewer_reads_raw_excel": (
            False
        ),
        "access_token_enabled": bool(
            ENABLE_PACKAGE_ACCESS_TOKEN
        ),
        "token_security_ready": (
            token_security_ready
        ),
        "secret_key_configured": (
            secret_key_configured
        ),
        "token_salt_configured": (
            token_salt_configured
        ),
        "token_version": TOKEN_VERSION,
        "masking": {
            "tax_id_visible_last_digits": (
                MASK_TAX_ID_VISIBLE_LAST_DIGITS
            ),
            "director_visible_first_chars": (
                MASK_DIRECTOR_VISIBLE_FIRST_CHARS
            ),
            "default_security_options": (
                normalize_security_policy(
                    PACKAGE_SECURITY_OPTIONS
                )
            ),
        },
        "public_allowed_components": (
            PUBLIC_ALLOWED_PACKAGE_COMPONENTS
        ),
        "public_prediction_allowed_fields": (
            sorted(
                PUBLIC_PREDICTION_ALLOWED_FIELDS
            )
        ),
        "public_entity_allowed_fields": (
            sorted(
                PUBLIC_ENTITY_ALLOWED_FIELDS
            )
        ),
        "forbidden_internal_keys": (
            PUBLIC_FORBIDDEN_INTERNAL_KEYS
        ),
        "internal_path_fields": sorted(
            INTERNAL_PATH_FIELDS
        ),
        "debug_private_fields": sorted(
            DEBUG_PRIVATE_FIELDS
        ),
        "checksum_components": (
            PACKAGE_CHECKSUM_COMPONENTS
        ),
        "package_status_values": (
            PACKAGE_STATUS_VALUES
        ),
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

    token = ""
    token_error = ""

    if ENABLE_PACKAGE_ACCESS_TOKEN:
        try:
            token = (
                generate_package_access_token(
                    package_id,
                    expire_days=1,
                    scope=["data"],
                )
            )

            verify = verify_access_token(
                token,
                expected_package_id=(
                    package_id
                ),
                expected_scope="data",
            )

        except Exception as exc:
            token_error = (
                exc.__class__.__name__
            )

            verify = {
                "valid": False,
                "reason": (
                    "token_configuration_error"
                ),
            }

    else:
        verify = {
            "valid": True,
            "reason": (
                "token_feature_disabled"
            ),
        }

    sample_record = {
        "tax_id_norm": (
            "0105560000000"
        ),
        "director_name": (
            "นายตัวอย่าง ทดสอบ"
        ),
        "address": (
            "99/9 ถนนตัวอย่าง "
            "กรุงเทพฯ"
        ),
        "total_premium": 1000000,
        "company_name": (
            "บริษัท ตัวอย่าง จำกัด"
        ),
        "source_file": (
            "/mnt/data/internal.xlsx"
        ),
    }

    prediction_record = {
        "object_type": "prediction",
        "source_type": (
            "flood_prediction"
        ),
        "record_key": (
            "prediction|1373690|"
            "2026-07-01|"
            "2026-07-03|2"
        ),
        "province": "น่าน",
        "station_name": (
            "สถานีตัวอย่าง"
        ),
        "risk_level": "Critical",
        "target_date": (
            "2026-07-03"
        ),
        "forecast_horizon_day": 2,
        "latest_value": 4.25,
        "latest_unit": "m",
        "map_ready": True,
        "latitude": 18.7,
        "longitude": 100.7,
        "source_file": (
            "C:\\internal\\predict.xlsx"
        ),
        "internal_path": (
            "/mnt/data/internal/"
            "predict.xlsx"
        ),
        "debug_traceback": (
            "traceback"
        ),
        "raw_record": {
            "secret": "x"
        },
    }

    entity_record = {
        "object_type": "entity",
        "source_type": (
            "uploaded_entity"
        ),
        "entity_id": "E001",
        "entity_type": "shop",
        "entity_name_th": (
            "ร้านตัวอย่าง"
        ),
        "entity_name_en": (
            "Example Shop"
        ),
        "province_name_th": "น่าน",
        "risk_group": "Watch",
        "is_displayable": True,
        "has_location": True,
        "map_ready": True,
        "latitude": 18.7,
        "longitude": 100.7,
        "saved_file": (
            "C:\\internal\\upload.csv"
        ),
        "error_report_file": (
            "/mnt/data/internal/"
            "error.csv"
        ),
    }

    masked = mask_record(
        sample_record,
        security_options={
            "mask_tax_id": True,
            "mask_director_name": True,
            "mask_address": True,
            "hide_financial_fields": True,
            "public": True,
        },
    )

    sanitized_prediction = (
        sanitize_public_payload(
            prediction_record
        )
    )

    sanitized_entity = (
        sanitize_public_payload(
            entity_record
        )
    )

    package_payload = {
        "package_id": package_id,
        "package_meta": {
            "package_id": package_id,
            "status": "active",
            "enabled": True,
            "allow_public_access": True,
            "public": True,
            "read_only": True,
            "require_token": bool(
                ENABLE_PACKAGE_ACCESS_TOKEN
            ),
            "access_token": token,
            "components": [
                "summary",
                "map",
                "data_quality",
                "prediction",
                "entity",
            ],
            "security": (
                normalize_security_policy()
            ),
        },
        "data": {
            "summary": {
                "total": 1
            },
            "map": {
                "features": []
            },
            "data_quality": {
                "issues": [
                    {
                        "issue_id": (
                            "DQ_TEST"
                        ),
                        "category": (
                            "data_quality"
                        ),
                        "severity": "low",
                        "actual": (
                            "/mnt/data/internal/"
                            "source.xlsx"
                        ),
                    }
                ]
            },
            "prediction": [
                prediction_record
            ],
            "entity": [
                entity_record
            ],
        },
    }

    package_payload = (
        attach_package_checksum(
            package_payload
        )
    )

    checksum = clean_text(
        package_payload.get(
            "package_meta",
            {},
        ).get("checksum")
    )

    public_snapshot = (
        build_public_package_snapshot(
            package_payload,
            token=token,
        )
    )

    return {
        "token_enabled": bool(
            ENABLE_PACKAGE_ACCESS_TOKEN
        ),
        "token_generated": bool(
            token
        ),
        "token_verify_valid": (
            verify.get("valid")
        ),
        "token_verify_reason": (
            verify.get("reason")
        ),
        "token_error": token_error,
        "masked_record": masked,
        "sanitized_prediction": (
            sanitized_prediction
        ),
        "sanitized_entity": (
            sanitized_entity
        ),
        "tax_id_zero_visible_safe": (
            mask_tax_id(
                "0105560000000",
                visible_last=0,
            )
            == "*************"
        ),
        "prediction_internal_removed": (
            "source_file"
            not in sanitized_prediction
            and "internal_path"
            not in sanitized_prediction
            and "debug_traceback"
            not in sanitized_prediction
            and "raw_record"
            not in sanitized_prediction
        ),
        "entity_internal_removed": (
            "saved_file"
            not in sanitized_entity
            and "error_report_file"
            not in sanitized_entity
        ),
        "local_path_removed": (
            "source_file"
            not in masked
        ),
        "checksum_generated": bool(
            checksum
        ),
        "checksum_verify_valid": (
            verify_package_checksum(
                package_payload,
                checksum=checksum,
            ).get("valid")
        ),
        "public_snapshot_allowed": (
            public_snapshot.get(
                "allowed"
            )
        ),
        "summary": (
            get_security_summary()
        ),
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
    "company_address",
    "house_no",
    "street",
}

FINANCIAL_FIELDS = {
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
    "registered_capital",
    "most_recent_income_val",
    "most_recent_asset_val",
    "most_recent_profit_val",
    "hist_premium_sum_all",
    "last_premium_active",
    "exp_premium",
    "total_connected_income",
    "total_connected_capital",
    "total_connected_premium",
    "total_connected_loss",
    "total_connected_suminsure",
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
    "password",
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

PUBLIC_COMPONENT_ALIASES = {
    "map_layers": "map",
    "flood_prediction": "prediction",
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

PUBLIC_COMPONENT_SCOPE_MAP = {
    "meta": "meta",
    "summary": "summary",
    "data": "data",
    "map": "map",
    "charts": "charts",
    "tables": "tables",
    "data_quality": (
        "data_quality"
    ),
    "prediction": "prediction",
    "entity": "entity",
    "companies": "data",
    "policy_summary": "data",
    "policy_table": "data",
    "linkage_graph": "data",
    "linkage_lines": "data",
    "flood_summary": "data",
    "filter_options": "data",
    "download": "download",
    "admin": "admin",
}

DATA_READ_SCOPES = {
    "meta",
    "summary",
    "data",
    "map",
    "charts",
    "tables",
    "data_quality",
    "prediction",
    "entity",
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

def normalize_security_policy(
    policy: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    base = dict(
        DEFAULT_MASKING_POLICY
    )

    if isinstance(
        PACKAGE_SECURITY_OPTIONS,
        dict,
    ):
        for key in base:
            if (
                key
                in PACKAGE_SECURITY_OPTIONS
            ):
                base[key] = to_bool(
                    PACKAGE_SECURITY_OPTIONS[
                        key
                    ],
                    default=bool(
                        base[key]
                    ),
                )

    if isinstance(policy, dict):
        for key in base:
            if key in policy:
                base[key] = to_bool(
                    policy[key],
                    default=bool(
                        base[key]
                    ),
                )

    base["public"] = to_bool(
        base.get("public"),
        default=True,
    )

    if base["public"]:
        base["mask_tax_id"] = True
        base[
            "mask_director_name"
        ] = True
        base["mask_person_name"] = True
        base["mask_address"] = True
        base[
            "remove_internal_paths"
        ] = True
        base[
            "remove_debug_fields"
        ] = True

    return base

def _field_name(
    value: Any,
) -> str:
    return (
        clean_text_lower(value)
        .replace(" ", "_")
        .replace("-", "_")
    )

def _looks_like_local_path(
    value: Any,
) -> bool:
    text = clean_text(
        value
    )

    if not text:
        return False

    decoded = unquote(
        text
    )

    normalized = decoded.replace(
        "\\",
        "/",
    )

    lower = normalized.lower()

    if lower.startswith(
        (
            "http://",
            "https://",
            "data:",
            "blob:",
        )
    ):
        embedded_local_markers = (
            "c:/users/",
            "/mnt/",
            "/tmp/",
            "/home/",
            "/workspace/",
            "/sandbox/",
        )

        return any(
            marker in lower
            for marker
            in embedded_local_markers
        )

    if lower.startswith(
        "file://"
    ):
        return True

    if lower.startswith(
        (
            "../",
            "./",
            "~/",
            "//",
        )
    ):
        return True

    if (
        len(normalized) > 2
        and normalized[0].isalpha()
        and normalized[1:3] == ":/"
    ):
        return True

    local_markers = (
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
        "c:/users/",
    )

    return any(
        marker in lower
        for marker in local_markers
    )

def mask_tax_id(
    value: Any,
    visible_last: int = 4,
    visible_last_digits: Optional[
        int
    ] = None,
) -> str:
    digits = "".join(
        character
        for character
        in clean_text(value)
        if character.isdigit()
    )

    if not digits:
        return ""

    requested_visible = (
        visible_last_digits
        if visible_last_digits
        is not None
        else visible_last
    )

    try:
        visible = int(
            requested_visible
        )
    except (
        TypeError,
        ValueError,
    ):
        visible = 4

    visible = max(
        0,
        min(
            len(digits),
            visible,
        ),
    )

    if visible == 0:
        return "*" * len(digits)

    if len(digits) <= visible:
        return "*" * len(digits)

    return (
        "*" * (
            len(digits)
            - visible
        )
        + digits[-visible:]
    )


def mask_person_name(
    value: Any,
    visible_first_chars: int = (
        MASK_DIRECTOR_VISIBLE_FIRST_CHARS
    ),
) -> Any:
    if isinstance(
        value,
        (list, tuple, set),
    ):
        return [
            mask_person_name(
                item,
                visible_first_chars,
            )
            for item in value
        ]

    text = clean_text(
        value
    )

    if not text:
        return ""

    for separator in [
        "\n",
        ";",
        ",",
    ]:
        if separator in text:
            names = [
                clean_text(item)
                for item
                in text.split(separator)
                if clean_text(item)
            ]

            return ", ".join(
                clean_text(
                    mask_person_name(
                        name,
                        visible_first_chars,
                    )
                )
                for name in names
            )

    try:
        visible = int(
            visible_first_chars
        )
    except (
        TypeError,
        ValueError,
    ):
        visible = 1

    visible = max(
        0,
        min(
            visible,
            max(
                0,
                len(text) - 1,
            ),
        ),
    )

    if visible == 0:
        return "*" * len(text)

    return (
        text[:visible]
        + "*" * (
            len(text)
            - visible
        )
    )


def mask_director_name(
    value: Any,
    visible_first_chars: int = (
        MASK_DIRECTOR_VISIBLE_FIRST_CHARS
    ),
) -> Any:
    return mask_person_name(
        value,
        visible_first_chars=(
            visible_first_chars
        ),
    )


def mask_address(
    value: Any,
) -> str:
    text = clean_text(
        value
    )

    if not text:
        return ""

    return "[masked address]"

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

def is_public_entity_displayable(
    record: Dict[str, Any],
) -> bool:
    if not isinstance(
        record,
        dict,
    ):
        return False

    if "is_displayable" in record:
        displayable = to_bool(
            record.get(
                "is_displayable"
            ),
            default=False,
        )

    elif "displayable" in record:
        displayable = to_bool(
            record.get(
                "displayable"
            ),
            default=False,
        )

    else:
        return False

    if not displayable:
        return False

    if to_bool(
        record.get(
            "not_displayable"
        ),
        default=False,
    ):
        return False

    map_ready = to_bool(
        record.get(
            "map_ready"
        ),
        default=False,
    )

    has_location = to_bool(
        record.get(
            "has_location"
        ),
        default=False,
    )

    if not (
        map_ready
        or has_location
    ):
        return False

    latitude = (
        record.get("latitude")
        if record.get(
            "latitude"
        )
        is not None
        else record.get("lat")
    )

    longitude = (
        record.get("longitude")
        if record.get("longitude") is not None
        else record.get("lon")
    )

    coordinate = (
        validate_coordinate(latitude,longitude,)
    )
    return bool(coordinate.get("valid"))

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
def normalize_package_checksum_payload(
    payload: Any,
) -> Any:
    value = json_safe(
        payload
    )

    if not isinstance(
        value,
        dict,
    ):
        return value

    source = deepcopy(
        value
    )

    for key in [
        "checksum",
        "package_checksum",
        "snapshot_checksum",
        "checksum_raw",
        "access_token",
        "token",
    ]:
        source.pop(
            key,
            None,
        )

    package_meta = (
        source.get(
            "package_meta"
        )
        if isinstance(
            source.get(
                "package_meta"
            ),
            dict,
        )
        else {}
    )

    meta = (
        source.get("meta")
        if isinstance(
            source.get("meta"),
            dict,
        )
        else {}
    )

    package_meta = {
        key: item
        for key, item
        in package_meta.items()
        if key
        not in {
            "checksum",
            "package_checksum",
            "snapshot_checksum",
            "checksum_raw",
            "access_token",
            "token",
            "public_url",
            "public_urls",
            "public_api_urls",
        }
    }

    meta = {
        key: item
        for key, item
        in meta.items()
        if key
        not in {
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

    data = (
        source.get("data")
        if isinstance(
            source.get("data"),
            dict,
        )
        else source
    )

    checksum_data = {
        key: data.get(key)
        for key
        in PACKAGE_CHECKSUM_COMPONENTS
        if key in data
    }

    package_id = clean_text(
        source.get(
            "package_id"
        )
        or package_meta.get(
            "package_id"
        )
        or meta.get(
            "package_id"
        )
    )

    return json_safe(
        {
            "package_id": package_id,
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


def sanitize_data_quality_public_value(
    value: Any,
    policy: Optional[
        Dict[str, Any]
    ] = None,
    field_name: str = "",
) -> Any:
    active_policy = (
        normalize_security_policy(
            policy
        )
    )

    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}

        for key, item in value.items():
            if should_remove_public_key(
                key
            ):
                continue

            sanitized = (
                sanitize_data_quality_public_value(
                    item,
                    active_policy,
                    field_name=key,
                )
            )

            if sanitized in (
                {},
                [],
                "",
                None,
            ):
                continue

            cleaned[key] = sanitized

        return json_safe(cleaned)

    if isinstance(value, list):
        cleaned_items: List[
            Any
        ] = []

        for item in value:
            sanitized = (
                sanitize_data_quality_public_value(
                    item,
                    active_policy,
                    field_name=field_name,
                )
            )

            if sanitized in (
                {},
                [],
                "",
                None,
            ):
                continue

            cleaned_items.append(
                sanitized
            )

        return json_safe(
            cleaned_items
        )

    if field_name:
        return sanitize_public_scalar(
            field_name,
            value,
            active_policy,
        )

    if _looks_like_local_path(
        value
    ):
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


def generate_package_access_token(
    package_id: str,
    scope: Optional[Any] = None,
    expires_at: Optional[Any] = None,
    expire_days: Optional[int] = None,
) -> str:
    clean_package_id = clean_text(
        package_id
    )

    if (
        not clean_package_id
        or len(clean_package_id) > 128
        or Path(
            clean_package_id
        ).name
        != clean_package_id
    ):
        raise ValueError(
            "Invalid package_id."
        )

    get_security_secret()

    scopes = normalize_access_scopes(
        scope
        if scope is not None
        else ["data"]
    )

    if not scopes:
        raise ValueError(
            "Invalid package access scope."
        )

    issued_at = datetime.now()

    if expires_at:
        expiry = (
            parse_security_datetime(
                expires_at
            )
        )

        if expiry is None:
            raise ValueError(
                "Invalid token expiry."
            )

        current_time = (
            datetime.now(
                expiry.tzinfo
            )
            if expiry.tzinfo
            is not None
            else issued_at
        )

        if expiry <= current_time:
            raise ValueError(
                "Token expiry must be "
                "in the future."
            )

        maximum_expiry = (
            current_time
            + timedelta(
                days=(
                    PACKAGE_MAX_EXPIRE_DAYS
                )
            )
        )

        if expiry > maximum_expiry:
            raise ValueError(
                "Token expiry exceeds "
                "the configured limit."
            )

    else:
        days = to_int(
            expire_days,
            default=(
                PACKAGE_DEFAULT_EXPIRE_DAYS
            ),
        )

        if days <= 0:
            days = (
                PACKAGE_DEFAULT_EXPIRE_DAYS
            )

        days = max(
            1,
            min(
                days,
                PACKAGE_MAX_EXPIRE_DAYS,
            ),
        )

        expiry = (
            issued_at
            + timedelta(days=days)
        )

    payload = {
        "version": TOKEN_VERSION,
        "package_id": (
            clean_package_id
        ),
        "scope": scopes,
        "read_only": True,
        "issued_at": (
            issued_at.isoformat(
                timespec="seconds"
            )
        ),
        "expires_at": (
            expiry.isoformat(
                timespec="seconds"
            )
        ),
        "nonce": random_token(16),
    }

    body = b64url_encode(
        payload
    )

    signature = hmac_signature(
        body
    )

    token = (
        f"{body}.{signature}"
    )

    if (
        len(token)
        > MAX_PACKAGE_TOKEN_LENGTH
    ):
        raise ValueError(
            "Generated token is too large."
        )

    return token


def verify_package_access_token(
    token: str,
    package_id: Optional[str] = None,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    token_text = clean_text(
        token
    )

    if not token_text:
        return {
            "valid": False,
            "reason": "missing_token",
        }

    if (
        len(token_text)
        > MAX_PACKAGE_TOKEN_LENGTH
    ):
        return {
            "valid": False,
            "reason": "token_too_large",
        }

    if token_text.count(".") != 1:
        return {
            "valid": False,
            "reason": (
                "invalid_token_format"
            ),
        }

    body, signature = (
        token_text.rsplit(
            ".",
            1,
        )
    )

    if (
        not body
        or not signature
        or len(signature) != 64
        or any(
            character
            not in "0123456789abcdefABCDEF"
            for character in signature
        )
    ):
        return {
            "valid": False,
            "reason": (
                "invalid_token_format"
            ),
        }

    try:
        expected_signature = (
            hmac_signature(body)
        )

    except RuntimeError:
        return {
            "valid": False,
            "reason": (
                "token_secret_not_configured"
            ),
        }

    if not constant_time_equal(
        expected_signature,
        signature,
    ):
        return {
            "valid": False,
            "reason": (
                "invalid_signature"
            ),
        }

    payload = b64url_decode_json(
        body
    )

    if not payload:
        return {
            "valid": False,
            "reason": (
                "invalid_payload"
            ),
        }

    version = clean_text(
        payload.get("version")
        or payload.get("v")
    )

    if version != TOKEN_VERSION:
        return {
            "valid": False,
            "reason": (
                "unsupported_token_version"
            ),
        }

    payload_package_id = clean_text(
        payload.get("package_id")
    )

    if not payload_package_id:
        return {
            "valid": False,
            "reason": (
                "package_id_missing"
            ),
        }

    if (
        package_id
        and payload_package_id
        != clean_text(package_id)
    ):
        return {
            "valid": False,
            "reason": (
                "package_mismatch"
            ),
        }

    issued_at = (
        parse_security_datetime(
            payload.get("issued_at")
        )
    )

    expires_at = (
        parse_security_datetime(
            payload.get("expires_at")
            or payload.get(
                "expire_at"
            )
        )
    )

    if (
        issued_at is None
        or expires_at is None
    ):
        return {
            "valid": False,
            "reason": (
                "invalid_token_time"
            ),
        }

    if (
        issued_at.tzinfo
        != expires_at.tzinfo
    ):
        return {
            "valid": False,
            "reason": (
                "inconsistent_token_timezone"
            ),
        }

    current_time = (
        datetime.now(
            expires_at.tzinfo
        )
        if expires_at.tzinfo
        is not None
        else datetime.now()
    )

    clock_skew = timedelta(
        seconds=(
            TOKEN_CLOCK_SKEW_SECONDS
        )
    )

    if issued_at > (
        current_time
        + clock_skew
    ):
        return {
            "valid": False,
            "reason": (
                "token_issued_in_future"
            ),
        }

    if expires_at <= current_time:
        return {
            "valid": False,
            "reason": (
                "token_expired"
            ),
        }

    if expires_at <= issued_at:
        return {
            "valid": False,
            "reason": (
                "invalid_token_lifetime"
            ),
        }

    if (
        expires_at
        - issued_at
        > timedelta(
            days=(
                PACKAGE_MAX_EXPIRE_DAYS
            ),
            seconds=(
                TOKEN_CLOCK_SKEW_SECONDS
            ),
        )
    ):
        return {
            "valid": False,
            "reason": (
                "token_lifetime_exceeded"
            ),
        }

    token_scopes = (
        normalize_access_scopes(
            payload.get("scope")
        )
    )

    if not token_scopes:
        return {
            "valid": False,
            "reason": (
                "token_scope_missing"
            ),
        }

    required_scope = (
        normalize_access_scope(scope)
        if scope is not None
        else ""
    )

    if (
        scope is not None
        and not required_scope
    ):
        return {
            "valid": False,
            "reason": (
                "invalid_required_scope"
            ),
        }

    if required_scope:
        allowed = bool(
            "admin" in token_scopes
            or required_scope
            in token_scopes
            or (
                "data"
                in token_scopes
                and required_scope
                in DATA_READ_SCOPES
            )
        )

        if not allowed:
            return {
                "valid": False,
                "reason": (
                    "scope_denied"
                ),
            }

    return {
        "valid": True,
        "reason": "ok",
        "payload": {
            "version": version,
            "package_id": (
                payload_package_id
            ),
            "scope": token_scopes,
            "read_only": bool(
                to_bool(
                    payload.get(
                        "read_only"
                    ),
                    default=True,
                )
            ),
            "issued_at": (
                issued_at.isoformat()
            ),
            "expires_at": (
                expires_at.isoformat()
            ),
        },
    }


def verify_access_token(
    token: str,
    expected_package_id: str = "",
    expected_scope: str = "",
) -> Dict[str, Any]:
    return verify_package_access_token(
        token,
        package_id=(
            expected_package_id
            or None
        ),
        scope=(
            expected_scope
            or None
        ),
    )


def normalize_access_scope(
    scope: Optional[Any],
) -> str:
    if isinstance(
        scope,
        (list, tuple, set),
    ):
        values = list(scope)

        if not values:
            return ""

        return normalize_access_scope(
            values[0]
        )

    value = (
        clean_text_lower(
            scope
        )
        .replace(
            "-",
            "_",
        )
    )

    if not value:
        return "data"

    canonical = (
        PUBLIC_COMPONENT_ALIASES.get(
            value,
            value,
        )
    )

    if canonical in (
        PACKAGE_ACCESS_SCOPES
    ):
        return canonical

    return (
        PUBLIC_COMPONENT_SCOPE_MAP.get(
            canonical,
            "",
        )
    )


def normalize_access_scopes(
    scopes: Optional[Any],
) -> List[str]:
    if isinstance(
        scopes,
        (list, tuple, set),
    ):
        raw_scopes = list(scopes)
    else:
        raw_scopes = [scopes]

    result: List[str] = []

    for raw_scope in raw_scopes:
        normalized = (
            normalize_access_scope(
                raw_scope
            )
        )

        if (
            not normalized
            or normalized in result
        ):
            continue

        result.append(normalized)

    return result


def validate_package_access_scope(
    scope: Any,
    allowed_scopes: Optional[
        Iterable[str]
    ] = None,
) -> Dict[str, Any]:
    normalized = (
        normalize_access_scope(
            scope
        )
    )

    if allowed_scopes is None:
        allowed = set(
            PACKAGE_ACCESS_SCOPES
        )
    else:
        allowed = set(
            normalize_access_scopes(
                list(allowed_scopes)
            )
        )

    valid = bool(
        normalized
        and normalized in allowed
    )

    return {
        "valid": valid,
        "scope": normalized,
        "allowed_scopes": sorted(
            allowed
        ),
        "reason": (
            "ok"
            if valid
            else "scope_not_allowed"
        ),
    }


def public_access_allowed(
    package_meta: Dict[str, Any],
    component: Optional[str] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    meta = (
        package_meta
        if isinstance(
            package_meta,
            dict,
        )
        else {}
    )

    accessibility = (
        is_package_publicly_accessible(
            meta
        )
    )

    if not accessibility.get(
        "allowed"
    ):
        return {
            "allowed": False,
            "reason": (
                accessibility.get(
                    "reason",
                    "access_denied",
                )
            ),
        }

    requested_component = (
        clean_text_lower(
            component,
            default="data",
        )
        .replace(
            "-",
            "_",
        )
    )

    canonical_component = (
        PUBLIC_COMPONENT_ALIASES.get(
            requested_component,
            requested_component,
        )
    )

    required_scope = (
        normalize_access_scope(
            canonical_component
        )
    )

    if not required_scope:
        return {
            "allowed": False,
            "reason": (
                "invalid_component"
            ),
            "component": (
                canonical_component
            ),
        }

    selected_components = (
        meta.get("components")
        or meta.get(
            "public_components"
        )
        or []
    )

    selected_canonical = {
        PUBLIC_COMPONENT_ALIASES.get(
            (
                clean_text_lower(item)
                .replace(
                    "-",
                    "_",
                )
            ),
            (
                clean_text_lower(item)
                .replace(
                    "-",
                    "_",
                )
            ),
        )
        for item
        in selected_components
        if clean_text(item)
    }

    if (
        canonical_component
        not in {
            "meta",
            "data",
            "admin",
            "download",
        }
        and canonical_component
        not in selected_canonical
    ):
        return {
            "allowed": False,
            "reason": (
                "component_not_allowed"
            ),
            "component": (
                canonical_component
            ),
        }

    token_required = bool(
        to_bool(
            meta.get(
                "require_token"
            ),
            default=(
                ENABLE_PACKAGE_ACCESS_TOKEN
            ),
        )
        or required_scope
        in {
            "admin",
            "download",
        }
    )

    token_text = clean_text(
        token
    )

    if (
        token_required
        and not token_text
    ):
        return {
            "allowed": False,
            "reason": "missing_token",
            "component": (
                canonical_component
            ),
            "token_valid": False,
        }

    if token_text:
        token_result = (
            verify_package_access_token(
                token_text,
                package_id=clean_text(
                    meta.get(
                        "package_id"
                    )
                ),
                scope=required_scope,
            )
        )

        if not token_result.get(
            "valid"
        ):
            return {
                "allowed": False,
                "reason": (
                    token_result.get(
                        "reason",
                        "token_denied",
                    )
                ),
                "component": (
                    canonical_component
                ),
                "token_valid": False,
            }

        return {
            "allowed": True,
            "reason": (
                "token_verified"
            ),
            "component": (
                canonical_component
            ),
            "token_valid": True,
        }

    return {
        "allowed": True,
        "reason": "ok",
        "component": (
            canonical_component
        ),
        "token_valid": (
            not token_required
        ),
    }

def build_public_package_url_meta(
    package_id: str,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    clean_package_id = clean_text(
        package_id
    )

    clean_id = quote(
        clean_package_id,
        safe="",
    )

    prefix = clean_text(
        base_url
    ).rstrip("/")

    api_prefix = (
        PUBLIC_API_PREFIX.rstrip("/")
    )

    api_base = (
        f"{prefix}{api_prefix}"
        f"/packages/{clean_id}"
        if prefix
        else (
            f"{api_prefix}"
            f"/packages/{clean_id}"
        )
    )

    return {
        "package_id": (
            clean_package_id
        ),
        "public_url": (
            f"{api_base}/data"
        ),
        "meta_url": (
            f"{api_base}/meta"
        ),
        "data_url": (
            f"{api_base}/data"
        ),
        "summary_url": (
            f"{api_base}/summary"
        ),
        "map_url": (
            f"{api_base}/map"
        ),
        "charts_url": (
            f"{api_base}/charts"
        ),
        "tables_url": (
            f"{api_base}/tables"
        ),
        "data_quality_url": (
            f"{api_base}/data-quality"
        ),
        "prediction_url": (
            f"{api_base}/prediction"
        ),
        "entity_url": (
            f"{api_base}/entity"
        ),
        "access_log_url": (
            f"{api_base}/access-log"
        ),
        "expires_at": "",
    }


def build_public_viewer_metadata(
    package_id: str,
    package_meta: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    meta = build_safe_public_meta(
        package_meta or {}
    )

    return {
        "package_id": clean_text(
            package_id
        ),
        "name": (
            meta.get("name")
            or meta.get(
                "package_name"
            )
            or clean_text(
                package_id
            )
        ),
        "description": meta.get(
            "description",
            "",
        ),
        "created_at": meta.get(
            "created_at",
            "",
        ),
        "updated_at": meta.get(
            "updated_at",
            meta.get(
                "created_at",
                "",
            ),
        ),
        "status": meta.get(
            "status",
            "active",
        ),
        "enabled": bool(
            to_bool(
                meta.get(
                    "enabled",
                    True,
                ),
                default=True,
            )
        ),
        "public": bool(
            to_bool(
                meta.get(
                    "public",
                    False,
                ),
                default=False,
            )
        ),
        "read_only": (
            PUBLIC_PACKAGE_READ_ONLY
        ),
        "snapshot_only": True,
        "expires_at": meta.get(
            "expires_at",
            "",
        ),
        "public_url_meta": (
            build_public_package_url_meta(
                package_id,
            )
        ),
    }

mask_company_tax_id = mask_tax_id
mask_director = mask_director_name
sanitize_package_payload = sanitize_public_payload
sanitize_external_payload = sanitize_public_payload
generate_access_token = generate_package_access_token
build_checksum = create_package_checksum
