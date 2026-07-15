# backend/auth/auth_service.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import config


# ============================================================
# 1) MODULE CONSTANTS / CONFIG FALLBACKS
# ============================================================

AUTH_SERVICE_NAME: str = "auth_service"

MYSQL_HOST: str = getattr(config, "MYSQL_HOST", os.getenv("MYSQL_HOST", "127.0.0.1"))
MYSQL_PORT: int = int(getattr(config, "MYSQL_PORT", os.getenv("MYSQL_PORT", "3307")))
MYSQL_USER: str = getattr(config, "MYSQL_USER", os.getenv("MYSQL_USER", "tipx"))
MYSQL_PASSWORD: str = str(
    getattr(
        config,
        "MYSQL_PASSWORD",
        os.getenv("MYSQL_PASSWORD", ""),
    )
    or ""
)
MYSQL_DATABASE: str = getattr(config, "MYSQL_DATABASE", os.getenv("MYSQL_DATABASE", "tipx_login"))
MYSQL_CHARSET: str = getattr(config, "MYSQL_CHARSET", os.getenv("MYSQL_CHARSET", "utf8mb4"))
MYSQL_CONNECT_TIMEOUT_SECONDS: int = int(getattr(config, "MYSQL_CONNECT_TIMEOUT_SECONDS", 10))

AUTH_MYSQL_TABLE_USERS: str = getattr(config, "AUTH_MYSQL_TABLE_USERS", "auth_users")
AUTH_MYSQL_TABLE_AUDIT_LOGS: str = getattr(config, "AUTH_MYSQL_TABLE_AUDIT_LOGS", "auth_audit_logs")

AUTH_ENABLED: bool = bool(getattr(config, "AUTH_ENABLED", True))
AUTH_DB_AUTO_CREATE: bool = bool(getattr(config, "AUTH_DB_AUTO_CREATE", True))
AUTH_DB_AUTO_SEED: bool = bool(
    getattr(
        config,
        "AUTH_DB_AUTO_SEED",
        False,
    )
)
AUTH_SEED_OVERWRITE_PASSWORD: bool = bool(getattr(config, "AUTH_SEED_OVERWRITE_PASSWORD", False))

AUTH_ROLES: List[str] = list(getattr(config, "AUTH_ROLES", ["admin", "user", "viewer"]))
AUTH_ROLE_LEVEL: Dict[str, int] = dict(
    getattr(
        config,
        "AUTH_ROLE_LEVEL",
        {
            "viewer": 10,
            "user": 50,
            "admin": 100,
        },
    )
)

AUTH_FIXED_USERS: List[Dict[str, Any]] = list(
    getattr(
        config,
        "AUTH_FIXED_USERS",
        [],
    )
)

PASSWORD_HASH_SCHEME: str = getattr(config, "PASSWORD_HASH_SCHEME", "pbkdf2_sha256")
PASSWORD_HASH_ITERATIONS: int = int(getattr(config, "PASSWORD_HASH_ITERATIONS", 260000))
PASSWORD_HASH_SALT_BYTES: int = int(getattr(config, "PASSWORD_HASH_SALT_BYTES", 16))
PASSWORD_HASH_PEPPER: str = getattr(config, "PASSWORD_HASH_PEPPER", "")

JWT_SECRET_KEY: str = str(
    getattr(
        config,
        "JWT_SECRET_KEY",
        getattr(config, "SECRET_KEY", ""),
    )
    or ""
)

JWT_ALGORITHM: str = getattr(config, "JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES: int = int(getattr(config, "JWT_EXPIRE_MINUTES", 480))
JWT_ISSUER: str = getattr(config, "JWT_ISSUER", "TIPX")
JWT_AUDIENCE: str = getattr(config, "JWT_AUDIENCE", "tipx-web")
JWT_CLOCK_SKEW_SECONDS: int = int(getattr(config, "JWT_CLOCK_SKEW_SECONDS", 30))

AUTH_TOKEN_TYPE: str = getattr(config, "AUTH_TOKEN_TYPE", "Bearer")
AUTH_HEADER_NAME: str = getattr(config, "AUTH_HEADER_NAME", "Authorization")
AUTH_TOKEN_PREFIX: str = getattr(config, "AUTH_TOKEN_PREFIX", "Bearer ")

AUTH_PUBLIC_EXACT_PATHS: List[str] = list(
    getattr(
        config,
        "AUTH_PUBLIC_EXACT_PATHS",
        [
            "/",
            "/health",
            "/status",
            "/favicon.ico",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/health",
            "/api/status",
            "/api/auth/login",
            "/api/auth/status",
        ],
    )
)

AUTH_PUBLIC_PREFIXES: List[str] = list(
    getattr(
        config,
        "AUTH_PUBLIC_PREFIXES",
        [
            "/static",
            "/assets",
            "/frontend",
            "/external_viewer",
            "/api/public",
            "/api/api/public",
        ],
    )
)

AUTH_AUTHENTICATED_EXACT_PATHS: List[str] = list(
    getattr(
        config,
        "AUTH_AUTHENTICATED_EXACT_PATHS",
        [
            "/api/auth/me",
            "/api/auth/logout",
        ],
    )
)

AUTH_ROLE_ROUTE_RULES: List[Dict[str, Any]] = list(getattr(config, "AUTH_ROLE_ROUTE_RULES", []))

AUTH_DEFAULT_READ_ROLES: List[str] = list(getattr(config, "AUTH_DEFAULT_READ_ROLES", ["admin", "user", "viewer"]))
AUTH_DEFAULT_WRITE_ROLES: List[str] = list(getattr(config, "AUTH_DEFAULT_WRITE_ROLES", ["admin", "user"]))
AUTH_DEFAULT_ADMIN_ROLES: List[str] = list(getattr(config, "AUTH_DEFAULT_ADMIN_ROLES", ["admin"]))

AUDIT_ENABLED: bool = bool(getattr(config, "AUDIT_ENABLED", True))
AUDIT_LOG_SUCCESS_READS: bool = bool(getattr(config, "AUDIT_LOG_SUCCESS_READS", False))
AUDIT_LOG_IP_ADDRESS: bool = bool(getattr(config, "AUDIT_LOG_IP_ADDRESS", True))
AUDIT_LOG_USER_AGENT: bool = bool(getattr(config, "AUDIT_LOG_USER_AGENT", True))
AUDIT_ACTION_PATH_RULES: List[Dict[str, Any]] = list(getattr(config, "AUDIT_ACTION_PATH_RULES", []))

ERROR_LOG_PATH: Path = Path(
    getattr(
        config,
        "ERROR_LOG_PATH",
        Path(__file__).resolve().parents[1] / "output" / "logs" / "tipx_auth_error.log",
    )
)


# ============================================================
# 2) BASIC HELPERS
# ============================================================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def utc_timestamp(dt: Optional[datetime] = None) -> int:
    source = dt or now_utc()
    if source.tzinfo is None:
        source = source.replace(tzinfo=timezone.utc)
    return int(source.timestamp())


def clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default

    try:
        text = str(value).strip()
    except Exception:
        return default

    return text if text else default


def clean_lower(value: Any, default: str = "") -> str:
    return clean_text(value, default=default).lower()


def to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = clean_lower(value)

    if text in {"1", "true", "yes", "y", "on"}:
        return True

    if text in {"0", "false", "no", "n", "off"}:
        return False

    return default


def json_safe(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, bool)):
        return value

    if isinstance(value, float):
        if value != value:
            return None
        if value in {float("inf"), float("-inf")}:
            return None
        return value

    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    return clean_text(value)


def make_auth_response(
    success: bool,
    message: str,
    data: Optional[Any] = None,
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "success": bool(success),
        "message": message,
        "data": data if data is not None else {},
        "meta": {
            "timestamp": now_iso(),
            "service": AUTH_SERVICE_NAME,
            **(meta or {}),
        },
        "errors": errors or [],
    }


def make_auth_error(
    message: str,
    error_type: str = "AuthError",
    status_code: int = 401,
    data: Optional[Any] = None,
    field: str = "",
) -> Dict[str, Any]:
    return make_auth_response(
        success=False,
        message=message,
        data=data if data is not None else {},
        meta={
            "status_code": status_code,
            "error_type": error_type,
            "field": field,
        },
        errors=[
            {
                "type": error_type,
                "message": message,
                "field": field,
                "status_code": status_code,
            }
        ],
    )


def safe_error_log(message: str, exc: Optional[Exception] = None) -> None:
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": now_iso(),
            "service": AUTH_SERVICE_NAME,
            "message": message,
        }

        if exc is not None:
            payload["error_type"] = exc.__class__.__name__
            payload["error"] = str(exc)
            payload["traceback"] = traceback.format_exc()

        with ERROR_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(json_safe(payload), ensure_ascii=False) + "\n")

    except Exception:
        pass


# ============================================================
# 3) MYSQL DRIVER / CONNECTION
# ============================================================

def get_mysql_driver() -> Tuple[str, Any]:
    try:
        import mysql.connector  # type: ignore

        return "mysql_connector", mysql.connector

    except Exception:
        pass

    try:
        import pymysql  # type: ignore

        return "pymysql", pymysql

    except Exception:
        pass

    raise RuntimeError(
        "MySQL driver not installed. Install one of: mysql-connector-python or PyMySQL."
    )


def quote_identifier(identifier: str) -> str:
    text = clean_text(identifier)

    if not text:
        raise ValueError("empty mysql identifier")

    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")

    if any(ch not in allowed for ch in text):
        raise ValueError(f"invalid mysql identifier: {identifier}")

    return f"`{text}`"

def get_mysql_connection(
    include_database: bool = True,
) -> Any:
    driver_name, driver = get_mysql_driver()

    base_kwargs: Dict[str, Any] = {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "charset": MYSQL_CHARSET,
    }

    if include_database:
        base_kwargs["database"] = MYSQL_DATABASE

    if driver_name == "mysql_connector":
        return driver.connect(
            **base_kwargs,
            connection_timeout=MYSQL_CONNECT_TIMEOUT_SECONDS,
        )

    if driver_name == "pymysql":
        return driver.connect(
            **base_kwargs,
            connect_timeout=MYSQL_CONNECT_TIMEOUT_SECONDS,
            cursorclass=driver.cursors.DictCursor,
            autocommit=False,
        )

    raise RuntimeError("unsupported mysql driver")

@contextmanager
def mysql_cursor(
    include_database: bool = True,
    dictionary: bool = True,
) -> Generator[Tuple[Any, Any], None, None]:
    connection = None
    cursor = None

    try:
        driver_name, _ = get_mysql_driver()
        connection = get_mysql_connection(include_database=include_database)

        if driver_name == "mysql_connector":
            cursor = connection.cursor(dictionary=dictionary)
        else:
            cursor = connection.cursor()

        yield connection, cursor
        connection.commit()

    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        raise

    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass

        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def fetchone(cursor: Any) -> Optional[Dict[str, Any]]:
    row = cursor.fetchone()

    if row is None:
        return None

    if isinstance(row, dict):
        return dict(row)

    try:
        columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row))
    except Exception:
        return None


def fetchall(cursor: Any) -> List[Dict[str, Any]]:
    rows = cursor.fetchall()

    if not rows:
        return []

    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return [dict(item) for item in rows]

    try:
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception:
        return []


# ============================================================
# 4) DATABASE / TABLE SETUP
# ============================================================

def create_auth_database_if_needed() -> Dict[str, Any]:
    try:
        with mysql_cursor(include_database=False, dictionary=True) as (_, cursor):
            cursor.execute(
                f"""
                CREATE DATABASE IF NOT EXISTS {quote_identifier(MYSQL_DATABASE)}
                CHARACTER SET {MYSQL_CHARSET}
                COLLATE {MYSQL_CHARSET}_unicode_ci
                """
            )

        return {
            "created": True,
            "database": MYSQL_DATABASE,
            "error": "",
        }

    except Exception as exc:
        safe_error_log("create_auth_database_if_needed failed", exc)
        return {
            "created": False,
            "database": MYSQL_DATABASE,
            "error": str(exc),
        }


def create_auth_tables_if_needed() -> Dict[str, Any]:
    try:
        users_table = quote_identifier(AUTH_MYSQL_TABLE_USERS)
        audit_table = quote_identifier(AUTH_MYSQL_TABLE_AUDIT_LOGS)

        with mysql_cursor(include_database=True, dictionary=True) as (_, cursor):
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {users_table} (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    username VARCHAR(80) NOT NULL,
                    password_hash TEXT NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    display_name VARCHAR(160) NULL,
                    is_active TINYINT(1) NOT NULL DEFAULT 1,
                    is_fixed TINYINT(1) NOT NULL DEFAULT 1,
                    last_login_at DATETIME NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_auth_users_username (username),
                    KEY idx_auth_users_role (role),
                    KEY idx_auth_users_is_active (is_active)
                )
                CHARACTER SET {MYSQL_CHARSET}
                COLLATE {MYSQL_CHARSET}_unicode_ci
                """
            )

            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {audit_table} (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    username VARCHAR(80) NULL,
                    role VARCHAR(32) NULL,
                    action VARCHAR(120) NOT NULL,
                    method VARCHAR(16) NULL,
                    path TEXT NULL,
                    status_code INT NULL,
                    ip_address VARCHAR(80) NULL,
                    user_agent TEXT NULL,
                    request_id VARCHAR(120) NULL,
                    details_json JSON NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    KEY idx_auth_audit_username (username),
                    KEY idx_auth_audit_role (role),
                    KEY idx_auth_audit_action (action),
                    KEY idx_auth_audit_created_at (created_at)
                )
                CHARACTER SET {MYSQL_CHARSET}
                COLLATE {MYSQL_CHARSET}_unicode_ci
                """
            )

        return {
            "created": True,
            "users_table": AUTH_MYSQL_TABLE_USERS,
            "audit_logs_table": AUTH_MYSQL_TABLE_AUDIT_LOGS,
            "error": "",
        }

    except Exception as exc:
        safe_error_log("create_auth_tables_if_needed failed", exc)
        return {
            "created": False,
            "users_table": AUTH_MYSQL_TABLE_USERS,
            "audit_logs_table": AUTH_MYSQL_TABLE_AUDIT_LOGS,
            "error": str(exc),
        }

def init_auth_storage() -> Dict[str, Any]:
    if not AUTH_ENABLED:
        return make_auth_response(
            success=True,
            message="Auth disabled.",
            data={
                "auth_enabled": False,
                "database": MYSQL_DATABASE,
                "tables_ready": False,
                "seeded": False,
            },
        )

    db_result: Dict[str, Any] = {
        "created": False,
        "database": MYSQL_DATABASE,
        "error": "",
        "reason": "AUTH_DB_AUTO_CREATE=false",
    }

    if AUTH_DB_AUTO_CREATE:
        db_result = create_auth_database_if_needed()

    table_result = create_auth_tables_if_needed()
    tables_ready = bool(
        table_result.get("created")
        and not table_result.get("error")
    )

    if AUTH_DB_AUTO_SEED and tables_ready:
        seed_result = seed_fixed_users()
    elif AUTH_DB_AUTO_SEED:
        seed_result = {
            "seeded": False,
            "reason": "auth tables are not ready",
            "results": [],
            "errors": [],
            "fixed_user_count": len(AUTH_FIXED_USERS),
            "overwrite_password": AUTH_SEED_OVERWRITE_PASSWORD,
        }
    else:
        seed_result = {
            "seeded": False,
            "reason": "AUTH_DB_AUTO_SEED=false",
            "results": [],
            "errors": [],
            "fixed_user_count": len(AUTH_FIXED_USERS),
            "overwrite_password": AUTH_SEED_OVERWRITE_PASSWORD,
        }

    seed_ready = (
        not AUTH_DB_AUTO_SEED
        or bool(seed_result.get("seeded"))
    )

    ok = tables_ready and seed_ready

    errors: List[Dict[str, Any]] = []

    if not tables_ready:
        errors.append(
            {
                "type": "AuthTableInitError",
                "message": (
                    table_result.get("error")
                    or db_result.get("error")
                    or "auth table initialization failed"
                ),
            }
        )

    if AUTH_DB_AUTO_SEED and not seed_ready:
        errors.append(
            {
                "type": "AuthSeedError",
                "message": "Fixed user seed failed.",
                "details": seed_result.get("errors", []),
            }
        )

    return make_auth_response(
        success=ok,
        message=(
            "Auth storage initialized."
            if ok
            else "Auth storage initialization failed."
        ),
        data={
            "auth_enabled": AUTH_ENABLED,
            "database": MYSQL_DATABASE,
            "database_result": db_result,
            "table_result": table_result,
            "seed_result": seed_result,
        },
        meta={
            "mysql_host": MYSQL_HOST,
            "mysql_port": MYSQL_PORT,
            "mysql_database": MYSQL_DATABASE,
            "status_code": 200 if ok else 503,
        },
        errors=errors,
    )

# ============================================================
# 5) PASSWORD HASH
# ============================================================

def b64url_encode_bytes(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode_bytes(value: str) -> bytes:
    text = clean_text(value)
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))

def create_password_hash(password: str) -> str:
    raw_password = (
        ""
        if password is None
        else str(password)
    )

    if raw_password == "":
        raise ValueError("password is required")

    if PASSWORD_HASH_SCHEME != "pbkdf2_sha256":
        raise ValueError(
            f"unsupported password hash scheme: {PASSWORD_HASH_SCHEME}"
        )

    if PASSWORD_HASH_ITERATIONS <= 0:
        raise ValueError(
            "PASSWORD_HASH_ITERATIONS must be greater than zero"
        )

    if PASSWORD_HASH_SALT_BYTES <= 0:
        raise ValueError(
            "PASSWORD_HASH_SALT_BYTES must be greater than zero"
        )

    salt = secrets.token_bytes(
        PASSWORD_HASH_SALT_BYTES
    )

    password_bytes = (
        raw_password + str(PASSWORD_HASH_PEPPER or "")
    ).encode("utf-8")

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password_bytes,
        salt,
        PASSWORD_HASH_ITERATIONS,
    )

    return "$".join(
        [
            PASSWORD_HASH_SCHEME,
            str(PASSWORD_HASH_ITERATIONS),
            b64url_encode_bytes(salt),
            b64url_encode_bytes(digest),
        ]
    )

def verify_password(
    password: str,
    password_hash: str,
) -> bool:
    raw_password = (
        ""
        if password is None
        else str(password)
    )

    stored = clean_text(password_hash)

    if raw_password == "" or not stored:
        return False

    try:
        scheme, iterations_text, salt_text, digest_text = stored.split(
            "$",
            3,
        )

        if scheme != PASSWORD_HASH_SCHEME:
            return False

        iterations = int(iterations_text)

        if iterations <= 0:
            return False

        salt = b64url_decode_bytes(salt_text)
        expected_digest = b64url_decode_bytes(digest_text)

        if not salt or not expected_digest:
            return False

        password_bytes = (
            raw_password + str(PASSWORD_HASH_PEPPER or "")
        ).encode("utf-8")

        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password_bytes,
            salt,
            iterations,
        )

        return hmac.compare_digest(
            actual_digest,
            expected_digest,
        )

    except Exception:
        return False

# ============================================================
# 6) USER STORAGE / SEED
# ============================================================

def sanitize_user_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None

    return {
        "id": row.get("id"),
        "username": clean_text(row.get("username")),
        "role": clean_text(row.get("role")),
        "display_name": clean_text(row.get("display_name")),
        "is_active": bool(int(row.get("is_active", 0) or 0)),
        "is_fixed": bool(int(row.get("is_fixed", 0) or 0)),
        "last_login_at": json_safe(row.get("last_login_at")),
        "created_at": json_safe(row.get("created_at")),
        "updated_at": json_safe(row.get("updated_at")),
    }


def get_user_by_username(
    username: str,
    include_password_hash: bool = False,
) -> Optional[Dict[str, Any]]:
    clean_username = clean_text(username)

    if not clean_username:
        return None

    try:
        with mysql_cursor(
            include_database=True,
            dictionary=True,
        ) as (_, cursor):
            cursor.execute(
                f"""
                SELECT
                    id,
                    username,
                    password_hash,
                    role,
                    display_name,
                    is_active,
                    is_fixed,
                    last_login_at,
                    created_at,
                    updated_at
                FROM {quote_identifier(AUTH_MYSQL_TABLE_USERS)}
                WHERE username = %s
                LIMIT 1
                """,
                (clean_username,),
            )

            row = fetchone(cursor)

        if not row:
            return None

        if not include_password_hash:
            row.pop("password_hash", None)

        return row

    except Exception as exc:
        safe_error_log(
            "get_user_by_username failed",
            exc,
        )
        raise

def list_auth_users() -> Dict[str, Any]:
    try:
        with mysql_cursor(include_database=True, dictionary=True) as (_, cursor):
            cursor.execute(
                f"""
                SELECT
                    id,
                    username,
                    role,
                    display_name,
                    is_active,
                    is_fixed,
                    last_login_at,
                    created_at,
                    updated_at
                FROM {quote_identifier(AUTH_MYSQL_TABLE_USERS)}
                ORDER BY FIELD(role, 'admin', 'user', 'viewer'), username
                """
            )

            records = [sanitize_user_row(row) for row in fetchall(cursor)]

        return make_auth_response(
            success=True,
            message="Auth users loaded.",
            data={
                "records": [record for record in records if record],
                "total": len([record for record in records if record]),
            },
        )

    except Exception as exc:
        safe_error_log("list_auth_users failed", exc)
        return make_auth_error(
            message="Cannot load auth users.",
            error_type=exc.__class__.__name__,
            status_code=500,
        )

def upsert_fixed_user(
    user_config: Dict[str, Any],
) -> Dict[str, Any]:
    username = clean_text(
        user_config.get("username")
    )

    raw_password = (
        ""
        if user_config.get("password") is None
        else str(user_config.get("password"))
    )

    role = clean_text(
        user_config.get("role")
    )

    display_name = clean_text(
        user_config.get("display_name"),
        username,
    )

    is_active = (
        1
        if to_bool(
            user_config.get("is_active"),
            True,
        )
        else 0
    )

    if not username:
        return {
            "username": "",
            "role": role,
            "created": False,
            "updated": False,
            "error": "username is required",
        }

    if role not in AUTH_ROLES:
        return {
            "username": username,
            "role": role,
            "created": False,
            "updated": False,
            "error": f"invalid role: {role}",
        }

    try:
        existing = get_user_by_username(
            username,
            include_password_hash=True,
        )

        with mysql_cursor(
            include_database=True,
            dictionary=True,
        ) as (_, cursor):
            if existing:
                if AUTH_SEED_OVERWRITE_PASSWORD:
                    if raw_password == "":
                        return {
                            "username": username,
                            "role": role,
                            "created": False,
                            "updated": False,
                            "password_updated": False,
                            "error": "password is required when overwrite is enabled",
                        }

                    password_hash = create_password_hash(
                        raw_password
                    )

                    cursor.execute(
                        f"""
                        UPDATE {quote_identifier(AUTH_MYSQL_TABLE_USERS)}
                        SET
                            password_hash = %s,
                            role = %s,
                            display_name = %s,
                            is_active = %s,
                            is_fixed = 1,
                            updated_at = NOW()
                        WHERE username = %s
                        """,
                        (
                            password_hash,
                            role,
                            display_name,
                            is_active,
                            username,
                        ),
                    )

                    return {
                        "username": username,
                        "role": role,
                        "created": False,
                        "updated": True,
                        "password_updated": True,
                        "error": "",
                    }

                cursor.execute(
                    f"""
                    UPDATE {quote_identifier(AUTH_MYSQL_TABLE_USERS)}
                    SET
                        role = %s,
                        display_name = %s,
                        is_active = %s,
                        is_fixed = 1,
                        updated_at = NOW()
                    WHERE username = %s
                    """,
                    (
                        role,
                        display_name,
                        is_active,
                        username,
                    ),
                )

                return {
                    "username": username,
                    "role": role,
                    "created": False,
                    "updated": True,
                    "password_updated": False,
                    "error": "",
                }

            if raw_password == "":
                return {
                    "username": username,
                    "role": role,
                    "created": False,
                    "updated": False,
                    "password_updated": False,
                    "error": "password is required for a new fixed user",
                }

            password_hash = create_password_hash(
                raw_password
            )

            cursor.execute(
                f"""
                INSERT INTO {quote_identifier(AUTH_MYSQL_TABLE_USERS)}
                    (
                        username,
                        password_hash,
                        role,
                        display_name,
                        is_active,
                        is_fixed,
                        created_at,
                        updated_at
                    )
                VALUES
                    (%s, %s, %s, %s, %s, 1, NOW(), NOW())
                """,
                (
                    username,
                    password_hash,
                    role,
                    display_name,
                    is_active,
                ),
            )

        return {
            "username": username,
            "role": role,
            "created": True,
            "updated": False,
            "password_updated": True,
            "error": "",
        }

    except Exception as exc:
        safe_error_log(
            f"upsert_fixed_user failed username={username}",
            exc,
        )

        return {
            "username": username,
            "role": role,
            "created": False,
            "updated": False,
            "password_updated": False,
            "error": str(exc),
        }

def seed_fixed_users() -> Dict[str, Any]:
    results = [upsert_fixed_user(item) for item in AUTH_FIXED_USERS]

    errors = [
        item
        for item in results
        if item.get("error")
    ]

    return {
        "seeded": not bool(errors),
        "results": results,
        "errors": errors,
        "fixed_user_count": len(AUTH_FIXED_USERS),
        "overwrite_password": AUTH_SEED_OVERWRITE_PASSWORD,
    }


def update_last_login(username: str) -> None:
    try:
        with mysql_cursor(include_database=True, dictionary=True) as (_, cursor):
            cursor.execute(
                f"""
                UPDATE {quote_identifier(AUTH_MYSQL_TABLE_USERS)}
                SET last_login_at = NOW(), updated_at = NOW()
                WHERE username = %s
                """,
                (clean_text(username),),
            )
    except Exception as exc:
        safe_error_log("update_last_login failed", exc)


# ============================================================
# 7) JWT
# ============================================================

def jwt_b64_encode(value: Any) -> str:
    raw = json.dumps(
        json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def jwt_b64_decode(value: str) -> Any:
    raw = b64url_decode_bytes(value)
    return json.loads(raw.decode("utf-8"))

def sign_jwt_message(message: str) -> str:
    if JWT_ALGORITHM != "HS256":
        raise ValueError(
            f"unsupported JWT_ALGORITHM: {JWT_ALGORITHM}"
        )

    secret_key = str(
        JWT_SECRET_KEY or ""
    )

    if secret_key == "":
        raise RuntimeError(
            "JWT_SECRET_KEY is not configured"
        )

    digest = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("ascii"),
        hashlib.sha256,
    ).digest()

    return b64url_encode_bytes(digest)

def create_access_token(
    user: Dict[str, Any],
    expire_minutes: Optional[int] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    username = clean_text(
        user.get("username")
    )

    role = clean_text(
        user.get("role")
    )

    if not username:
        raise ValueError(
            "username is required for JWT"
        )

    if role not in AUTH_ROLES:
        raise ValueError(
            f"invalid role for JWT: {role}"
        )

    effective_expire_minutes = int(
        JWT_EXPIRE_MINUTES
        if expire_minutes is None
        else expire_minutes
    )

    if effective_expire_minutes <= 0:
        raise ValueError(
            "JWT expiration must be greater than zero"
        )

    issued_at = now_utc()
    expires_at = issued_at + timedelta(
        minutes=effective_expire_minutes
    )

    header = {
        "typ": "JWT",
        "alg": JWT_ALGORITHM,
    }

    payload: Dict[str, Any] = {
        **dict(extra_claims or {}),
        "sub": username,
        "username": username,
        "role": role,
        "display_name": clean_text(
            user.get("display_name"),
            username,
        ),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": utc_timestamp(issued_at),
        "nbf": utc_timestamp(issued_at),
        "exp": utc_timestamp(expires_at),
        "token_type": "access",
    }

    encoded_header = jwt_b64_encode(
        header
    )

    encoded_payload = jwt_b64_encode(
        payload
    )

    signing_input = (
        f"{encoded_header}.{encoded_payload}"
    )

    signature = sign_jwt_message(
        signing_input
    )

    token = (
        f"{signing_input}.{signature}"
    )

    return {
        "access_token": token,
        "token_type": AUTH_TOKEN_TYPE,
        "expires_at": expires_at.isoformat(
            timespec="seconds"
        ),
        "expires_in": int(
            (
                expires_at - issued_at
            ).total_seconds()
        ),
        "payload": payload,
    }

def decode_access_token(
    token: str,
    verify_exp: bool = True,
) -> Dict[str, Any]:
    clean_token = clean_text(token)

    if not clean_token:
        return {
            "valid": False,
            "reason": "missing_token",
            "payload": {},
        }

    if len(clean_token) > 8192:
        return {
            "valid": False,
            "reason": "token_too_large",
            "payload": {},
        }

    try:
        parts = clean_token.split(".")

        if len(parts) != 3:
            return {
                "valid": False,
                "reason": "invalid_token_format",
                "payload": {},
            }

        encoded_header, encoded_payload, signature = parts

        signing_input = (
            f"{encoded_header}.{encoded_payload}"
        )

        expected_signature = sign_jwt_message(
            signing_input
        )

        if not hmac.compare_digest(
            signature,
            expected_signature,
        ):
            return {
                "valid": False,
                "reason": "invalid_signature",
                "payload": {},
            }

        header = jwt_b64_decode(
            encoded_header
        )

        payload = jwt_b64_decode(
            encoded_payload
        )

        if not isinstance(header, dict):
            return {
                "valid": False,
                "reason": "invalid_header",
                "payload": {},
            }

        if not isinstance(payload, dict):
            return {
                "valid": False,
                "reason": "invalid_payload",
                "payload": {},
            }

        if header.get("typ") != "JWT":
            return {
                "valid": False,
                "reason": "invalid_token_type_header",
                "payload": {},
            }

        if header.get("alg") != JWT_ALGORITHM:
            return {
                "valid": False,
                "reason": "invalid_algorithm",
                "payload": {},
            }

        if payload.get("token_type") != "access":
            return {
                "valid": False,
                "reason": "invalid_token_type",
                "payload": {},
            }

        if payload.get("iss") != JWT_ISSUER:
            return {
                "valid": False,
                "reason": "invalid_issuer",
                "payload": {},
            }

        if payload.get("aud") != JWT_AUDIENCE:
            return {
                "valid": False,
                "reason": "invalid_audience",
                "payload": {},
            }

        subject = clean_text(
            payload.get("sub")
        )

        username = clean_text(
            payload.get("username")
        )

        if (
            not subject
            or not username
            or subject != username
        ):
            return {
                "valid": False,
                "reason": "invalid_subject",
                "payload": {},
            }

        role = clean_text(
            payload.get("role")
        )

        if role not in AUTH_ROLES:
            return {
                "valid": False,
                "reason": "invalid_role",
                "payload": {},
            }

        try:
            issued_at = int(
                payload.get("iat")
            )

            not_before = int(
                payload.get("nbf")
            )

            expires_at = int(
                payload.get("exp")
            )

        except Exception:
            return {
                "valid": False,
                "reason": "invalid_time_claims",
                "payload": {},
            }

        now_ts = utc_timestamp()
        skew = max(
            0,
            JWT_CLOCK_SKEW_SECONDS,
        )

        if issued_at > now_ts + skew:
            return {
                "valid": False,
                "reason": "invalid_issued_at",
                "payload": {},
            }

        if not_before > now_ts + skew:
            return {
                "valid": False,
                "reason": "token_not_active",
                "payload": {},
            }

        if verify_exp and expires_at <= now_ts - skew:
            return {
                "valid": False,
                "reason": "token_expired",
                "payload": {},
            }

        return {
            "valid": True,
            "reason": "ok",
            "payload": payload,
        }

    except Exception as exc:
        return {
            "valid": False,
            "reason": "decode_error",
            "payload": {},
            "error": (
                str(exc)
                if getattr(config, "DEBUG", False)
                else ""
            ),
        }

def extract_bearer_token(
    authorization_header: str,
) -> str:
    header = clean_text(
        authorization_header
    )

    if not header:
        return ""

    token_prefix = clean_text(
        AUTH_TOKEN_PREFIX,
        "Bearer ",
    )

    if not header.lower().startswith(
        token_prefix.lower()
    ):
        return ""

    return header[
        len(token_prefix):
    ].strip()

def get_user_from_token(token: str, verify_db_active: bool = False) -> Dict[str, Any]:
    decoded = decode_access_token(token)

    if not decoded.get("valid"):
        return {
            "authenticated": False,
            "reason": decoded.get("reason", "invalid_token"),
            "user": None,
            "payload": decoded.get("payload", {}),
        }

    payload = decoded.get("payload", {})
    username = clean_text(payload.get("username") or payload.get("sub"))
    role = clean_text(payload.get("role"))

    user = {
        "username": username,
        "role": role,
        "display_name": clean_text(payload.get("display_name"), username),
        "is_active": True,
        "token_payload": payload,
    }

    if verify_db_active:
        db_user = get_user_by_username(username, include_password_hash=False)

        if not db_user:
            return {
                "authenticated": False,
                "reason": "user_not_found",
                "user": None,
                "payload": payload,
            }

        if not db_user.get("is_active"):
            return {
                "authenticated": False,
                "reason": "user_inactive",
                "user": None,
                "payload": payload,
            }

        user.update(db_user)

    return {
        "authenticated": True,
        "reason": "ok",
        "user": user,
        "payload": payload,
    }


def get_user_from_authorization_header(
    authorization_header: str,
    verify_db_active: bool = False,
) -> Dict[str, Any]:
    token = extract_bearer_token(authorization_header)

    if not token:
        return {
            "authenticated": False,
            "reason": "missing_token",
            "user": None,
            "payload": {},
        }

    return get_user_from_token(token, verify_db_active=verify_db_active)


# ============================================================
# 8) LOGIN / ME / LOGOUT
# ============================================================

def authenticate_user(
    username: str,
    password: str,
) -> Dict[str, Any]:
    clean_username = clean_text(
        username
    )

    raw_password = (
        ""
        if password is None
        else str(password)
    )

    if not clean_username or raw_password == "":
        return make_auth_error(
            message="username and password are required.",
            error_type="InvalidCredentials",
            status_code=400,
        )

    user = get_user_by_username(
        clean_username,
        include_password_hash=True,
    )

    if not user:
        return make_auth_error(
            message="Invalid username or password.",
            error_type="InvalidCredentials",
            status_code=401,
        )

    try:
        is_active = bool(
            int(
                user.get(
                    "is_active",
                    0,
                )
                or 0
            )
        )
    except Exception:
        is_active = False

    if not is_active:
        return make_auth_error(
            message="User is inactive.",
            error_type="UserInactive",
            status_code=403,
        )

    if not verify_password(
        raw_password,
        clean_text(
            user.get("password_hash")
        ),
    ):
        return make_auth_error(
            message="Invalid username or password.",
            error_type="InvalidCredentials",
            status_code=401,
        )

    safe_user = sanitize_user_row(
        user
    ) or {}

    token_payload = create_access_token(
        safe_user
    )

    update_last_login(
        clean_username
    )

    return make_auth_response(
        success=True,
        message="Login successful.",
        data={
            "user": safe_user,
            "access_token": token_payload["access_token"],
            "token_type": token_payload["token_type"],
            "expires_at": token_payload["expires_at"],
            "expires_in": token_payload["expires_in"],
        },
        meta={
            "role": safe_user.get("role"),
            "username": safe_user.get("username"),
        },
    )

def get_current_user(authorization_header: str, verify_db_active: bool = False) -> Dict[str, Any]:
    result = get_user_from_authorization_header(
        authorization_header=authorization_header,
        verify_db_active=verify_db_active,
    )

    if not result.get("authenticated"):
        return make_auth_error(
            message=f"Not authenticated: {result.get('reason')}",
            error_type="NotAuthenticated",
            status_code=401,
            data={
                "authenticated": False,
                "reason": result.get("reason"),
            },
        )

    return make_auth_response(
        success=True,
        message="Current user loaded.",
        data={
            "authenticated": True,
            "user": result.get("user"),
        },
        meta={
            "reason": result.get("reason"),
        },
    )


def logout_user(
    user: Optional[Dict[str, Any]] = None,
    method: str = "POST",
    path: str = "/api/auth/logout",
    status_code: int = 200,
    ip_address: str = "",
    user_agent: str = "",
    request_id: str = "",
) -> Dict[str, Any]:
    write_audit_log(
        action="logout",
        user=user,
        method=method,
        path=path,
        status_code=status_code,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        details={
            "logout_type": "client_token_discard",
            "session_table": False,
            "refresh_token": False,
        },
    )

    return make_auth_response(
        success=True,
        message="Logout recorded. Please remove token on client.",
        data={
            "logged_out": True,
            "server_side_token_revoked": False,
        },
    )


# ============================================================
# 9) ROLE GUARD / ROUTE GUARD
# ============================================================

def normalize_path(path: str) -> str:
    text = clean_text(path, "/")

    if not text.startswith("/"):
        text = f"/{text}"

    while "//" in text:
        text = text.replace("//", "/")

    if len(text) > 1 and text.endswith("/"):
        text = text.rstrip("/")

    return text


def normalize_method(method: str) -> str:
    return clean_text(method, "GET").upper()


def role_allowed(user_role: str, allowed_roles: List[str]) -> bool:
    role = clean_text(user_role)

    if role == "admin":
        return True

    return role in set(allowed_roles or [])


def is_public_path(path: str, method: str = "GET") -> bool:
    clean_path = normalize_path(path)
    clean_method = normalize_method(method)

    if clean_method == "OPTIONS" and bool(getattr(config, "AUTH_SKIP_OPTIONS_REQUEST", True)):
        return True

    if clean_path in {normalize_path(item) for item in AUTH_PUBLIC_EXACT_PATHS}:
        return True

    for prefix in AUTH_PUBLIC_PREFIXES:
        clean_prefix = normalize_path(prefix)

        if clean_path == clean_prefix or clean_path.startswith(clean_prefix + "/"):
            return True

    return False


def get_default_roles_for_method(method: str) -> List[str]:
    clean_method = normalize_method(method)

    if clean_method == "GET":
        return list(AUTH_DEFAULT_READ_ROLES)

    if clean_method in {"POST", "PUT", "PATCH"}:
        return list(AUTH_DEFAULT_WRITE_ROLES)

    if clean_method == "DELETE":
        return list(AUTH_DEFAULT_ADMIN_ROLES)

    return list(AUTH_DEFAULT_ADMIN_ROLES)


def match_path_rule(
    path: str,
    method: str,
    rules: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    clean_path = normalize_path(path)
    clean_method = normalize_method(method)

    for rule in rules or AUTH_ROLE_ROUTE_RULES:
        methods = [
            normalize_method(item)
            for item in rule.get("methods", [])
        ]

        if methods and clean_method not in methods:
            continue

        path_prefix = normalize_path(rule.get("path_prefix", ""))

        if not path_prefix:
            continue

        if not (clean_path == path_prefix or clean_path.startswith(path_prefix + "/")):
            continue

        path_contains = clean_text(rule.get("path_contains"))

        if path_contains and path_contains not in clean_path:
            continue

        return dict(rule)

    return None


def get_required_roles_for_path(path: str, method: str) -> Dict[str, Any]:
    rule = match_path_rule(path, method)

    if rule:
        return {
            "roles": list(rule.get("roles", [])),
            "rule": rule,
            "rule_name": clean_text(rule.get("name")),
            "audit_action": clean_text(rule.get("audit_action")),
        }

    return {
        "roles": get_default_roles_for_method(method),
        "rule": None,
        "rule_name": "default_method_rule",
        "audit_action": clean_text(f"{normalize_method(method).lower()}_api"),
    }


def authorize_request(
    path: str,
    method: str = "GET",
    authorization_header: str = "",
    verify_db_active: bool = False,
) -> Dict[str, Any]:
    clean_path = normalize_path(path)
    clean_method = normalize_method(method)

    if not AUTH_ENABLED:
        return {
            "allowed": True,
            "public": True,
            "reason": "auth_disabled",
            "status_code": 200,
            "user": None,
            "required_roles": [],
            "rule": None,
        }

    if is_public_path(clean_path, clean_method):
        return {
            "allowed": True,
            "public": True,
            "reason": "public_path",
            "status_code": 200,
            "user": None,
            "required_roles": [],
            "rule": None,
        }

    auth_result = get_user_from_authorization_header(
        authorization_header,
        verify_db_active=verify_db_active,
    )

    if not auth_result.get("authenticated"):
        return {
            "allowed": False,
            "public": False,
            "reason": auth_result.get("reason", "not_authenticated"),
            "status_code": 401,
            "user": None,
            "required_roles": [],
            "rule": None,
        }

    user = auth_result.get("user") or {}
    user_role = clean_text(user.get("role"))

    role_rule = get_required_roles_for_path(clean_path, clean_method)
    required_roles = role_rule.get("roles", [])

    if not role_allowed(user_role, required_roles):
        return {
            "allowed": False,
            "public": False,
            "reason": "role_forbidden",
            "status_code": 403,
            "user": user,
            "required_roles": required_roles,
            "rule": role_rule.get("rule"),
            "rule_name": role_rule.get("rule_name"),
        }

    return {
        "allowed": True,
        "public": False,
        "reason": "ok",
        "status_code": 200,
        "user": user,
        "required_roles": required_roles,
        "rule": role_rule.get("rule"),
        "rule_name": role_rule.get("rule_name"),
        "audit_action": role_rule.get("audit_action"),
    }


def require_roles(user: Dict[str, Any], allowed_roles: List[str]) -> Dict[str, Any]:
    role = clean_text((user or {}).get("role"))

    if role_allowed(role, allowed_roles):
        return {
            "allowed": True,
            "reason": "ok",
            "role": role,
            "allowed_roles": allowed_roles,
        }

    return {
        "allowed": False,
        "reason": "role_forbidden",
        "role": role,
        "allowed_roles": allowed_roles,
    }


# ============================================================
# 10) AUDIT LOG
# ============================================================

def get_audit_action_for_path(path: str, method: str, default: str = "") -> str:
    clean_path = normalize_path(path)
    clean_method = normalize_method(method)

    for rule in AUDIT_ACTION_PATH_RULES:
        methods = [
            normalize_method(item)
            for item in rule.get("methods", [])
        ]

        if methods and clean_method not in methods:
            continue

        path_prefix = normalize_path(rule.get("path_prefix", ""))

        if not path_prefix:
            continue

        if not (clean_path == path_prefix or clean_path.startswith(path_prefix + "/")):
            continue

        path_contains = clean_text(rule.get("path_contains"))

        if path_contains and path_contains not in clean_path:
            continue

        return clean_text(rule.get("action"), default)

    role_rule = get_required_roles_for_path(clean_path, clean_method)

    return clean_text(role_rule.get("audit_action"), default)


def should_audit_request(
    action: str,
    method: str,
    path: str,
    status_code: Optional[int] = None,
) -> bool:
    if not AUDIT_ENABLED:
        return False

    clean_method = normalize_method(
        method
    )

    clean_action = clean_text(
        action
    )

    if not clean_action:
        return False

    if (
        clean_method == "GET"
        and not AUDIT_LOG_SUCCESS_READS
        and (
            status_code is None
            or int(status_code) < 400
        )
    ):
        return False

    if (
        is_public_path(path, method)
        and clean_action
        not in {
            "login_success",
            "login_failed",
            "logout",
        }
    ):
        return False

    return True

def write_audit_log(
    action: str,
    user: Optional[Dict[str, Any]] = None,
    method: str = "",
    path: str = "",
    status_code: Optional[int] = None,
    ip_address: str = "",
    user_agent: str = "",
    request_id: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    clean_action = clean_text(action)

    if not should_audit_request(clean_action, method, path, status_code):
        return {
            "logged": False,
            "reason": "audit_disabled_or_skipped",
        }

    user_payload = user or {}
    username = clean_text(user_payload.get("username"))
    role = clean_text(user_payload.get("role"))

    if not username:
        username = clean_text((details or {}).get("username"))

    if not role:
        role = clean_text((details or {}).get("role"))

    details_payload = json.dumps(
        json_safe(details or {}),
        ensure_ascii=False,
        sort_keys=True,
    )

    try:
        with mysql_cursor(include_database=True, dictionary=True) as (_, cursor):
            cursor.execute(
                f"""
                INSERT INTO {quote_identifier(AUTH_MYSQL_TABLE_AUDIT_LOGS)}
                    (
                        username,
                        role,
                        action,
                        method,
                        path,
                        status_code,
                        ip_address,
                        user_agent,
                        request_id,
                        details_json,
                        created_at
                    )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON), NOW())
                """,
                (
                    username or None,
                    role or None,
                    clean_action,
                    normalize_method(method) if method else None,
                    normalize_path(path) if path else None,
                    int(status_code) if status_code is not None else None,
                    clean_text(ip_address) if AUDIT_LOG_IP_ADDRESS else "",
                    clean_text(user_agent) if AUDIT_LOG_USER_AGENT else "",
                    clean_text(request_id),
                    details_payload,
                ),
            )

        return {
            "logged": True,
            "action": clean_action,
            "username": username,
            "role": role,
        }

    except Exception as exc:
        safe_error_log("write_audit_log failed", exc)
        return {
            "logged": False,
            "reason": "audit_insert_failed",
            "error": str(exc),
        }


def write_login_audit(
    username: str,
    success: bool,
    role: str = "",
    method: str = "POST",
    path: str = "/api/auth/login",
    status_code: int = 200,
    ip_address: str = "",
    user_agent: str = "",
    request_id: str = "",
    reason: str = "",
) -> Dict[str, Any]:
    return write_audit_log(
        action="login_success" if success else "login_failed",
        user={
            "username": clean_text(username),
            "role": clean_text(role),
        },
        method=method,
        path=path,
        status_code=status_code,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        details={
            "username": clean_text(username),
            "success": bool(success),
            "reason": clean_text(reason),
        },
    )


def list_audit_logs(
    limit: int = 100,
    username: str = "",
    action: str = "",
) -> Dict[str, Any]:
    clean_username = clean_text(username)
    clean_action = clean_text(action)
    clean_limit = max(1, min(int(limit or 100), 1000))

    where_parts: List[str] = []
    params: List[Any] = []

    if clean_username:
        where_parts.append("username = %s")
        params.append(clean_username)

    if clean_action:
        where_parts.append("action = %s")
        params.append(clean_action)

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    try:
        with mysql_cursor(include_database=True, dictionary=True) as (_, cursor):
            cursor.execute(
                f"""
                SELECT
                    id,
                    username,
                    role,
                    action,
                    method,
                    path,
                    status_code,
                    ip_address,
                    user_agent,
                    request_id,
                    details_json,
                    created_at
                FROM {quote_identifier(AUTH_MYSQL_TABLE_AUDIT_LOGS)}
                {where_sql}
                ORDER BY id DESC
                LIMIT %s
                """,
                tuple(params + [clean_limit]),
            )

            records = fetchall(cursor)

        return make_auth_response(
            success=True,
            message="Audit logs loaded.",
            data={
                "records": json_safe(records),
                "total": len(records),
                "limit": clean_limit,
            },
        )

    except Exception as exc:
        safe_error_log("list_audit_logs failed", exc)
        return make_auth_error(
            message="Cannot load audit logs.",
            error_type=exc.__class__.__name__,
            status_code=500,
        )


# ============================================================
# 11) FRONTEND / CLIENT CONTRACT
# ============================================================

def get_frontend_auth_contract() -> Dict[str, Any]:
    return {
        "enabled": AUTH_ENABLED,
        "token_type": AUTH_TOKEN_TYPE,
        "header_name": AUTH_HEADER_NAME,
        "token_prefix": AUTH_TOKEN_PREFIX,
        "login_endpoint": "/api/auth/login",
        "me_endpoint": "/api/auth/me",
        "logout_endpoint": "/api/auth/logout",
        "status_endpoint": "/api/auth/status",
        "roles": list(AUTH_ROLES),
        "role_level": dict(AUTH_ROLE_LEVEL),
        "frontend": {
            "enabled": bool(getattr(config, "FRONTEND_AUTH_ENABLED", AUTH_ENABLED)),
            "login_path": getattr(config, "FRONTEND_LOGIN_PATH", "/login"),
            "default_after_login_path": getattr(config, "FRONTEND_DEFAULT_AFTER_LOGIN_PATH", "/dashboard"),
            "role_home_paths": dict(getattr(config, "FRONTEND_ROLE_HOME_PATHS", {})),
            "public_routes": list(getattr(config, "FRONTEND_PUBLIC_ROUTES", [])),
            "role_route_rules": list(getattr(config, "FRONTEND_ROLE_ROUTE_RULES", [])),
        },
    }


# ============================================================
# 12) STATUS / SELF TEST
# ============================================================

def test_mysql_connection() -> Dict[str, Any]:
    driver_name = ""

    try:
        driver_name = get_mysql_driver()[0]

        with mysql_cursor(
            include_database=False,
            dictionary=True,
        ) as (_, cursor):
            cursor.execute(
                "SELECT 1 AS ok"
            )

            row = fetchone(
                cursor
            )

        return {
            "connected": bool(
                row
                and int(
                    row.get(
                        "ok",
                        0,
                    )
                )
                == 1
            ),
            "driver": driver_name,
            "host": MYSQL_HOST,
            "port": MYSQL_PORT,
            "database": MYSQL_DATABASE,
            "error": "",
        }

    except Exception as exc:
        safe_error_log(
            "test_mysql_connection failed",
            exc,
        )

        return {
            "connected": False,
            "driver": driver_name,
            "host": MYSQL_HOST if getattr(config, "DEBUG", False) else "",
            "port": MYSQL_PORT if getattr(config, "DEBUG", False) else None,
            "database": MYSQL_DATABASE if getattr(config, "DEBUG", False) else "",
            "error": (
                str(exc)
                if getattr(config, "DEBUG", False)
                else "MySQL connection unavailable."
            ),
        }

def get_auth_status() -> Dict[str, Any]:
    mysql_status = test_mysql_connection()

    fixed_usernames = [
        clean_text(
            item.get("username")
        )
        for item in AUTH_FIXED_USERS
        if (
            isinstance(item, dict)
            and clean_text(
                item.get("username")
            )
        )
    ]

    expected_fixed_user_count = len(
        set(fixed_usernames)
    )

    users_ready = False
    user_count = 0
    storage_error = ""

    if mysql_status.get("connected"):
        try:
            with mysql_cursor(
                include_database=True,
                dictionary=True,
            ) as (_, cursor):
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM {quote_identifier(AUTH_MYSQL_TABLE_USERS)}
                    WHERE is_fixed = 1
                      AND is_active = 1
                    """
                )

                row = fetchone(
                    cursor
                ) or {}

                user_count = int(
                    row.get(
                        "total",
                        0,
                    )
                    or 0
                )

                users_ready = bool(
                    expected_fixed_user_count > 0
                    and user_count
                    >= expected_fixed_user_count
                )

        except Exception as exc:
            safe_error_log(
                "get_auth_status storage check failed",
                exc,
            )

            users_ready = False

            storage_error = (
                str(exc)
                if getattr(config, "DEBUG", False)
                else "Auth storage unavailable."
            )

    jwt_ready = bool(
        str(JWT_SECRET_KEY or "")
    )

    ready = bool(
        not AUTH_ENABLED
        or (
            mysql_status.get("connected")
            and users_ready
            and jwt_ready
        )
    )

    return make_auth_response(
        success=ready,
        message=(
            "Auth status loaded."
            if ready
            else "Auth service is not ready."
        ),
        data={
            "enabled": AUTH_ENABLED,
            "ready": ready,
            "mysql": mysql_status,
            "storage": {
                "database": MYSQL_DATABASE,
                "users_table": AUTH_MYSQL_TABLE_USERS,
                "audit_logs_table": AUTH_MYSQL_TABLE_AUDIT_LOGS,
                "users_ready": users_ready,
                "user_count": user_count,
                "expected_fixed_user_count": expected_fixed_user_count,
                "auto_create": AUTH_DB_AUTO_CREATE,
                "auto_seed": AUTH_DB_AUTO_SEED,
                "error": storage_error,
            },
            "jwt": {
                "algorithm": JWT_ALGORITHM,
                "expire_minutes": JWT_EXPIRE_MINUTES,
                "issuer": JWT_ISSUER,
                "audience": JWT_AUDIENCE,
                "secret_configured": jwt_ready,
            },
            "password_hash": {
                "scheme": PASSWORD_HASH_SCHEME,
                "iterations": PASSWORD_HASH_ITERATIONS,
                "salt_bytes": PASSWORD_HASH_SALT_BYTES,
                "pepper_configured": bool(PASSWORD_HASH_PEPPER),
            },
            "roles": list(AUTH_ROLES),
            "fixed_usernames": fixed_usernames,
            "route_guard": {
                "public_exact_paths": list(AUTH_PUBLIC_EXACT_PATHS),
                "public_prefixes": list(AUTH_PUBLIC_PREFIXES),
                "role_rule_count": len(AUTH_ROLE_ROUTE_RULES),
            },
            "audit": {
                "enabled": AUDIT_ENABLED,
                "log_success_reads": AUDIT_LOG_SUCCESS_READS,
                "action_rule_count": len(AUDIT_ACTION_PATH_RULES),
            },
        },
        meta={
            "status_code": 200 if ready else 503,
        },
        errors=(
            []
            if ready
            else [
                {
                    "type": "AuthServiceNotReady",
                    "message": "Authentication service is not ready.",
                }
            ]
        ),
    )

def run_auth_self_test() -> Dict[str, Any]:
    password = f"self-test-{secrets.token_hex(8)}"
    password_hash = create_password_hash(password)
    password_ok = verify_password(password, password_hash)
    password_fail_ok = not verify_password(password + "-wrong", password_hash)

    token_payload = create_access_token(
        {
            "username": "self_test",
            "role": "viewer",
            "display_name": "Self Test",
        },
        expire_minutes=5,
    )

    token_check = decode_access_token(token_payload["access_token"])

    public_check = is_public_path("/api/auth/login", "POST")
    protected_check = not is_public_path("/api/companies", "GET")

    viewer_authorize = authorize_request(
        path="/api/companies",
        method="GET",
        authorization_header=f"Bearer {token_payload['access_token']}",
        verify_db_active=False,
    )

    viewer_forbidden = authorize_request(
        path="/api/cache/rebuild",
        method="POST",
        authorization_header=f"Bearer {token_payload['access_token']}",
        verify_db_active=False,
    )

    return {
        "password_hash_created": bool(password_hash),
        "password_verify_ok": password_ok,
        "password_verify_fail_ok": password_fail_ok,
        "jwt_created": bool(token_payload.get("access_token")),
        "jwt_decode_valid": token_check.get("valid"),
        "public_path_check": public_check,
        "protected_path_check": protected_check,
        "viewer_read_allowed": viewer_authorize.get("allowed"),
        "viewer_cache_forbidden": not viewer_forbidden.get("allowed"),
        "viewer_cache_forbidden_reason": viewer_forbidden.get("reason"),
        "auth_status": get_auth_status().get("data", {}),
    }


# ============================================================
# 13) STARTUP ENTRYPOINT
# ============================================================

def startup_auth() -> Dict[str, Any]:
    if not AUTH_ENABLED:
        return make_auth_response(
            success=True,
            message="Auth disabled.",
            data={
                "enabled": False,
            },
        )

    if not str(JWT_SECRET_KEY or ""):
        return make_auth_error(
            message="JWT_SECRET_KEY is not configured.",
            error_type="AuthConfigurationError",
            status_code=500,
            field="JWT_SECRET_KEY",
        )

    if JWT_ALGORITHM != "HS256":
        return make_auth_error(
            message="Unsupported JWT algorithm.",
            error_type="AuthConfigurationError",
            status_code=500,
            data={
                "algorithm": JWT_ALGORITHM,
            },
            field="JWT_ALGORITHM",
        )

    if JWT_EXPIRE_MINUTES <= 0:
        return make_auth_error(
            message="JWT_EXPIRE_MINUTES must be greater than zero.",
            error_type="AuthConfigurationError",
            status_code=500,
            field="JWT_EXPIRE_MINUTES",
        )

    if AUTH_DB_AUTO_SEED:
        if not AUTH_FIXED_USERS:
            return make_auth_error(
                message="AUTH_FIXED_USERS is empty while auto seed is enabled.",
                error_type="AuthConfigurationError",
                status_code=500,
                field="AUTH_FIXED_USERS",
            )

        missing_password_users = [
            clean_text(
                item.get("username")
            )
            for item in AUTH_FIXED_USERS
            if (
                isinstance(item, dict)
                and str(
                    item.get("password")
                    if item.get("password") is not None
                    else ""
                )
                == ""
            )
        ]

        if missing_password_users:
            return make_auth_error(
                message="Fixed-user passwords are not configured.",
                error_type="AuthConfigurationError",
                status_code=500,
                data={
                    "usernames": missing_password_users,
                },
                field="AUTH_FIXED_USERS",
            )

    return init_auth_storage()


if AUTH_ENABLED and bool(getattr(config, "AUTH_INIT_ON_IMPORT", False)):
    try:
        startup_auth()
    except Exception as exc:
        safe_error_log("startup_auth on import failed", exc)