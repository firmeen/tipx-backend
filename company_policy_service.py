# ============================================================
# FILE: backend/company_policy_service.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 9 / 20
# ============================================================

"""
backend/company_policy_service.py

ไฟล์นี้เป็นศูนย์กลาง Company + Policy Pipeline ของระบบ TIPX

หน้าที่หลัก:
1. อ่าน Policy Input File
2. อ่าน Linkage Input File เฉพาะส่วน company profile ที่จำเป็น
3. สร้าง policy_fact
4. สร้าง company_location_master
5. สร้าง province_branch_coordinate_master
6. สร้าง policy_company_summary
7. สร้าง policy_product_summary
8. สร้าง policy_subclass_summary
9. สร้าง policy_yearly_summary
10. สร้าง policy_loss_ratio_summary
11. สร้าง company_unified_master
12. รวมข้อมูล policy + linkage + location + flood context
13. รองรับ Policy Dashboard
14. รองรับ Company Dashboard
15. รองรับ API routes กลุ่ม /api/companies/*
16. รองรับ API routes กลุ่ม /api/policy/*
17. เขียน cache กลางให้ module อื่นใช้ต่อ
18. เตรียมข้อมูลสำหรับ Linkage Graph, Flood Spatial Join, Map, Package Export

Data Source:
- input/policy/policy_input.xlsx
- input/linkage/linkage_input.xlsx
- cache จาก flood_spatial_service.py ถ้ามี

หลักการรวม company_unified_master:
- key หลักคือ tax_id_norm
- Company Name priority:
    1. Policy Sheet 1
    2. Linkage Input
    3. Policy Sheet 2
- Province priority:
    1. Policy Sheet 1 ถ้ามี
    2. Policy Sheet 2
    3. Sheet 3 fallback
- Location priority:
    1. exact company location จาก Policy Sheet 2
    2. approximate branch/province จาก Policy Sheet 3
- WTIP / boardlist / TSIC / company_size มาจาก Linkage Input
- Policy status มาจาก Policy Sheet 1 เท่านั้น
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import (
    POLICY_INPUT_PATH,
    LINKAGE_INPUT_PATH,
    POLICY_SHEETS,
    POLICY_SHEET_INDEX_FALLBACK,
    LINKAGE_SHEET_INDEX_FALLBACK,
    POLICY_FACT_COLUMNS,
    POLICY_LOCATION_COLUMNS,
    PROVINCE_BRANCH_COLUMNS,
    LINKAGE_COLUMNS,
    CACHE_TTL_SECONDS,
)

from utils import (
    add_tax_id_columns,
    apply_search_sort_pagination,
    build_policy_summary_from_records,
    calculate_loss_ratio,
    clean_dataframe_common,
    clean_text,
    clean_text_lower,
    combine_risk_levels,
    count_distinct,
    dataframe_to_records,
    detect_policy_status_conflict,
    first_non_empty,
    get_cache_file_path,
    get_loss_ratio_band,
    get_or_build_cache,
    group_records_by,
    is_active_policy_row,
    is_empty_value,
    make_hash_id,
    most_common_value,
    normalize_policy_status,
    normalize_province_name,
    normalize_tax_id,
    read_cache,
    read_excel_by_logical_sheet,
    rename_columns_by_candidates,
    sum_field,
    to_bool,
    to_int,
    to_jsonable,
    to_number,
    validate_coordinate,
    validate_tax_id,
    write_cache,
    write_json,
)

try:
    from data_quality import build_quality_flags_by_tax_id
except Exception:
    build_quality_flags_by_tax_id = None


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
    "policy_fact": "policy_fact",
    "company_location_master": "company_location_master",
    "province_branch_coordinate_master": "province_branch_coordinate_master",
    "policy_company_summary": "policy_company_summary",
    "policy_product_summary": "policy_product_summary",
    "policy_subclass_summary": "policy_subclass_summary",
    "policy_yearly_summary": "policy_yearly_summary",
    "policy_loss_ratio_summary": "policy_loss_ratio_summary",
    "linkage_company_profile": "linkage_company_profile",
    "company_unified_base": "company_unified_base",
    "company_unified_master": "company_unified_master",
}

POLICY_SEARCHABLE_FIELDS: List[str] = [
    "tax_id_norm",
    "company_name",
    "product",
    "subclass",
    "policy_status",
    "loss_ratio_band",
]

COMPANY_SEARCHABLE_FIELDS: List[str] = [
    "tax_id_norm",
    "company_name",
    "province",
    "district",
    "subdistrict",
    "business_type_objective",
    "business_type_tsic",
    "company_size",
    "wtip",
    "loss_ratio_band",
    "flood_risk_level",
    "linkage_risk_level",
    "flood_join_level",
    "location_quality",
]

NUMERIC_POLICY_FIELDS: List[str] = [
    "premium",
    "loss",
    "suminsure",
    "noofpol",
    "active_subs",
    "expired_subs",
    "product_holding",
    "subclass_holding",
    "most_recent_asset_val",
    "most_recent_income_val",
    "registered_capital",
]

NON_SUMMABLE_COMPANY_FIELDS: List[str] = [
    "most_recent_asset_val",
    "most_recent_income_val",
    "registered_capital",
]


# ============================================================
# 2) CONTEXT HELPERS
# ============================================================

def now_iso() -> str:
    """
    คืนเวลาปัจจุบันแบบ ISO string
    """

    return datetime.now().isoformat(timespec="seconds")

def normalize_context(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    normalize context จาก api_routes.py
    """

    result = dict(DEFAULT_CONTEXT)

    if isinstance(context, dict):
        result.update(context)

    result["force_refresh"] = bool(
        to_bool(
            result.get("force_refresh"),
            default=False,
        )
    )

    try:
        result["page"] = max(
            1,
            int(
                result.get("page", 1)
                or 1
            ),
        )
    except (TypeError, ValueError):
        result["page"] = 1

    try:
        result["page_size"] = max(
            1,
            min(
                5000,
                int(
                    result.get("page_size", 50)
                    or 50
                ),
            ),
        )
    except (TypeError, ValueError):
        result["page_size"] = 50

    result["search"] = clean_text(
        result.get("search", "")
    )
    result["sort_by"] = clean_text(
        result.get("sort_by", "")
    )
    result["sort_dir"] = (
        clean_text_lower(
            result.get("sort_dir", "asc")
        )
        or "asc"
    )

    if result["sort_dir"] not in {
        "asc",
        "desc",
    }:
        result["sort_dir"] = "asc"

    if not isinstance(
        result.get("filters"),
        dict,
    ):
        result["filters"] = {}

    return result


def get_policy_ttl() -> int:
    """
    TTL สำหรับ policy/company cache
    """

    return int(CACHE_TTL_SECONDS.get("policy", 3600))

def get_valid_tax_id(value: Any) -> str:
    validation = validate_tax_id(
        value
    )

    if not validation.get(
        "tax_id_valid",
        False,
    ):
        return ""

    return clean_text(
        validation.get("tax_id_norm")
    )


def get_company_group_key(
    record: Dict[str, Any],
) -> str:
    tax_id_norm = get_valid_tax_id(
        record.get("tax_id_norm")
        or record.get("tax_id")
        or record.get("tax_id_raw")
    )

    if tax_id_norm:
        return tax_id_norm

    company_key = clean_text(
        record.get("company_key")
    )

    if company_key:
        return company_key

    company_name = first_non_empty(
        record.get("company_name"),
        record.get("company_name_policy"),
        record.get("company_name_linkage"),
        record.get("company_name_location"),
        record.get("name_th"),
        default="",
    )

    province = normalize_province_name(
        first_non_empty(
            record.get("province"),
            record.get("company_province"),
            default="",
        )
    )

    business_type = first_non_empty(
        record.get("business_type"),
        record.get("business_type_objective"),
        record.get("business_type_tsic"),
        default="",
    )

    return make_hash_id(
        (
            f"{clean_text(company_name)}|"
            f"{province}|"
            f"{clean_text(business_type)}"
        ),
        prefix="no_tax_company",
        length=16,
    )


def count_distinct_companies(
    records: List[Dict[str, Any]],
) -> int:
    return len(
        {
            get_company_group_key(record)
            for record in records
            if get_company_group_key(record)
        }
    )


def filter_records_without_pagination(
    records: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
    searchable_fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    ctx = normalize_context(context)

    try:
        from filter_engine import apply_simple_filters

        filtered = apply_simple_filters(
            records,
            ctx.get("filters", {}),
        )
    except Exception:
        filtered = list(records)

    search_text = clean_text_lower(
        ctx.get("search")
    )

    if not search_text:
        return list(filtered)

    fields = list(
        searchable_fields
        or []
    )

    if not fields:
        return [
            record
            for record in filtered
            if search_text
            in " ".join(
                clean_text(value)
                for value in record.values()
            ).lower()
        ]

    return [
        record
        for record in filtered
        if search_text
        in " ".join(
            clean_text(
                record.get(field_name)
            )
            for field_name in fields
        ).lower()
    ]

def filter_records_for_api(
    records: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
    searchable_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    apply search / sort / pagination สำหรับ API
    """

    ctx = normalize_context(context)

    filtered = filter_records_without_pagination(
        records=records,
        context=ctx,
        searchable_fields=searchable_fields,
    )

    return apply_search_sort_pagination(
        records=filtered,
        context=ctx,
        searchable_fields=None,
    )

# ============================================================
# 3) INPUT LOADERS
# ============================================================

def load_policy_input() -> Dict[str, pd.DataFrame]:
    """
    อ่าน Policy Input ทั้ง 3 logical sheets

    รองรับชื่อชีตจริงจากไฟล์ของคุณ:
    - Policy Depth
    - latlong
    - latlong(branch)

    และ fallback จาก config.POLICY_SHEET_INDEX_FALLBACK
    """

    empty_result = {
        "policy_fact": pd.DataFrame(),
        "company_location": pd.DataFrame(),
        "province_branch_coordinate": pd.DataFrame(),
    }

    if (
        not POLICY_INPUT_PATH.exists()
        or not POLICY_INPUT_PATH.is_file()
    ):
        return empty_result

    try:
        with pd.ExcelFile(
            POLICY_INPUT_PATH
        ) as excel_file:
            sheet_names = list(
                excel_file.sheet_names
            )

            sheet_name_index = {
                clean_text_lower(
                    sheet_name
                ): sheet_name
                for sheet_name in sheet_names
            }

            def pick_sheet(
                logical_key: str,
                aliases: List[str],
            ) -> Any:
                preferred_names = [
                    POLICY_SHEETS.get(
                        logical_key,
                        "",
                    ),
                    *aliases,
                ]

                for preferred_name in preferred_names:
                    normalized_name = (
                        clean_text_lower(
                            preferred_name
                        )
                    )

                    if (
                        normalized_name
                        and normalized_name
                        in sheet_name_index
                    ):
                        return sheet_name_index[
                            normalized_name
                        ]

                fallback_index = int(
                    POLICY_SHEET_INDEX_FALLBACK.get(
                        logical_key,
                        -1,
                    )
                )

                if (
                    0
                    <= fallback_index
                    < len(sheet_names)
                ):
                    return sheet_names[
                        fallback_index
                    ]

                return None

            def read_sheet(
                sheet_name: Any,
            ) -> pd.DataFrame:
                if sheet_name is None:
                    return pd.DataFrame()

                try:
                    return pd.read_excel(
                        excel_file,
                        sheet_name=sheet_name,
                        dtype=str,
                    )
                except Exception:
                    return pd.DataFrame()

            policy_fact = read_sheet(
                pick_sheet(
                    "policy_fact",
                    [
                        "Policy Depth",
                        "policy depth",
                        "Policy_Depth",
                        "policy_fact",
                    ],
                )
            )

            company_location = read_sheet(
                pick_sheet(
                    "company_location",
                    [
                        "latlong",
                        "Latlong",
                        "LatLong",
                        "company_location",
                    ],
                )
            )

            province_branch = read_sheet(
                pick_sheet(
                    "province_branch_coordinate",
                    [
                        "latlong(branch)",
                        "latlong (branch)",
                        "Latlong(branch)",
                        "province_branch_coordinate",
                    ],
                )
            )

    except Exception:
        return empty_result

    policy_fact = rename_columns_by_candidates(
        clean_dataframe_common(
            policy_fact
        ),
        POLICY_FACT_COLUMNS,
        keep_original=True,
    )

    company_location = rename_columns_by_candidates(
        clean_dataframe_common(
            company_location
        ),
        POLICY_LOCATION_COLUMNS,
        keep_original=True,
    )

    province_branch = rename_columns_by_candidates(
        clean_dataframe_common(
            province_branch
        ),
        PROVINCE_BRANCH_COLUMNS,
        keep_original=True,
    )

    return {
        "policy_fact": policy_fact,
        "company_location": company_location,
        "province_branch_coordinate": province_branch,
    }

def load_linkage_company_input() -> pd.DataFrame:
    """
    อ่าน Linkage Input เฉพาะ company profile

    ข้อมูลนี้ใช้เติม:
    - company_name_linkage
    - business_type_objective
    - business_type_tsic
    - company_size
    - wtip
    - most_recent_income_val
    - registered_capital
    - boardlist
    """

    if not LINKAGE_INPUT_PATH.exists():
        return pd.DataFrame()

    df = read_excel_by_logical_sheet(
        LINKAGE_INPUT_PATH,
        expected_sheet_name=None,
        fallback_index=LINKAGE_SHEET_INDEX_FALLBACK,
        dtype=str,
    )

    df = clean_dataframe_common(df)
    df = rename_columns_by_candidates(
        df,
        LINKAGE_COLUMNS,
        keep_original=True,
    )

    return df


# ============================================================
# 4) POLICY FACT BUILDER
# ============================================================

def build_policy_fact(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง policy_fact จาก Policy Sheet 1

    Output:
    {
        "records": [...],
        "total": n,
        "created_at": ...
    }
    """

    def builder() -> Dict[str, Any]:
        policy_sheets = load_policy_input()
        df = policy_sheets.get(
            "policy_fact",
            pd.DataFrame(),
        )

        if df is None or df.empty:
            return {
                "records": [],
                "total": 0,
                "created_at": now_iso(),
                "source_path": str(
                    POLICY_INPUT_PATH
                ),
                "warnings": [
                    "policy_fact_empty_or_file_missing"
                ],
            }

        df = df.copy()

        if "tax_id" not in df.columns:
            df["tax_id"] = ""

        df = add_tax_id_columns(
            df,
            source_column="tax_id",
        )

        records: List[
            Dict[str, Any]
        ] = []

        for idx, row in df.iterrows():
            premium = (
                to_number(
                    row.get("premium"),
                    0.0,
                )
                or 0.0
            )

            loss = (
                to_number(
                    row.get("loss"),
                    0.0,
                )
                or 0.0
            )

            suminsure = (
                to_number(
                    row.get("suminsure"),
                    0.0,
                )
                or 0.0
            )

            noofpol = (
                to_number(
                    row.get("noofpol"),
                    0.0,
                )
                or 0.0
            )

            loss_ratio = calculate_loss_ratio(
                loss,
                premium,
                zero_policy="zero",
            )

            policy_year = to_int(
                row.get(
                    "yearmonth_year_first"
                ),
                default=None,
            )

            policy_status = normalize_policy_status(
                first_non_empty(
                    row.get(
                        "status_now_new"
                    ),
                    row.get("status_now"),
                    row.get(
                        "inforced_flag"
                    ),
                    default="",
                )
            )

            company_name = clean_text(
                row.get("company_name")
            )

            province = normalize_province_name(
                row.get("province")
            )

            business_type = clean_text(
                row.get("business_type")
            )

            tax_id_raw = clean_text(
                row.get("tax_id_raw")
            )

            tax_id_norm = clean_text(
                row.get("tax_id_norm")
            )

            tax_id_valid = bool(
                to_bool(
                    row.get("tax_id_valid"),
                    default=False,
                )
            )

            company_key = (
                tax_id_norm
                if tax_id_valid
                else make_hash_id(
                    (
                        f"{company_name}|"
                        f"{province}|"
                        f"{business_type}"
                    ),
                    prefix="no_tax_company",
                    length=16,
                )
            )

            record = {
                "source_file": str(
                    POLICY_INPUT_PATH.name
                ),
                "source_sheet": "policy_fact",
                "source_row": int(idx) + 2,
                "company_key": company_key,
                "tax_id_raw": tax_id_raw,
                "tax_id_norm": tax_id_norm,
                "tax_id_valid": tax_id_valid,
                "tax_id_issue": clean_text(
                    row.get("tax_id_issue")
                ),
                "company_name": company_name,
                "business_type": business_type,
                "income_range": clean_text(
                    row.get("income_range")
                ),
                "province": province,
                "product": clean_text(
                    row.get("product")
                ),
                "product_holding_text": clean_text(
                    row.get(
                        "product_holding_text"
                    )
                ),
                "subclass": clean_text(
                    row.get("subclass")
                ),
                "inforced_flag": clean_text(
                    row.get("inforced_flag")
                ),
                "status_now": clean_text(
                    row.get("status_now")
                ),
                "status_now_new": clean_text(
                    row.get("status_now_new")
                ),
                "policy_status": policy_status,
                "is_active_policy": bool(
                    is_active_policy_row(row)
                ),
                "is_expired_policy": (
                    policy_status == "Expired"
                ),
                "status_conflict_flag": bool(
                    detect_policy_status_conflict(
                        row
                    )
                ),
                "yearmonth_year_first": clean_text(
                    row.get(
                        "yearmonth_year_first"
                    )
                ),
                "policy_year": policy_year,
                "premium": premium,
                "loss": loss,
                "suminsure": suminsure,
                "noofpol": noofpol,
                "active_subs": (
                    to_number(
                        row.get("active_subs"),
                        0.0,
                    )
                    or 0.0
                ),
                "expired_subs": (
                    to_number(
                        row.get(
                            "expired_subs"
                        ),
                        0.0,
                    )
                    or 0.0
                ),
                "product_holding": (
                    to_number(
                        row.get(
                            "product_holding"
                        ),
                        0.0,
                    )
                    or 0.0
                ),
                "subclass_holding": (
                    to_number(
                        row.get(
                            "subclass_holding"
                        ),
                        0.0,
                    )
                    or 0.0
                ),
                "most_recent_asset_val": to_number(
                    row.get(
                        "most_recent_asset_val"
                    ),
                    None,
                ),
                "most_recent_income_val": to_number(
                    row.get(
                        "most_recent_income_val"
                    ),
                    None,
                ),
                "registered_capital": to_number(
                    row.get(
                        "registered_capital"
                    ),
                    None,
                ),
                "loss_ratio": loss_ratio,
                "loss_ratio_row": loss_ratio,
                "loss_ratio_band": get_loss_ratio_band(
                    loss_ratio,
                    premium=premium,
                    loss=loss,
                ),
                "premium_zero_with_loss": bool(
                    premium == 0
                    and loss > 0
                ),
            }

            records.append(record)

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
            "source_path": str(
                POLICY_INPUT_PATH
            ),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "policy_fact"
        ],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source=(
            "company_policy_service."
            "build_policy_fact"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }

def get_policy_fact_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน records จาก policy_fact
    """

    data = build_policy_fact(force_refresh=force_refresh)
    return data.get("records", [])


# ============================================================
# 5) LOCATION MASTER BUILDER
# ============================================================

def build_company_location_master(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง company_location_master จาก Policy Sheet 2
    """

    def builder() -> Dict[str, Any]:
        policy_sheets = load_policy_input()
        df = policy_sheets.get("company_location", pd.DataFrame())

        if df is None or df.empty:
            return {
                "records": [],
                "total": 0,
                "created_at": now_iso(),
                "warnings": ["company_location_empty_or_file_missing"],
            }

        df = df.copy()

        if "tax_id" not in df.columns:
            df["tax_id"] = ""

        df = add_tax_id_columns(df, source_column="tax_id")

        records: List[Dict[str, Any]] = []

        for idx, row in df.iterrows():
            lat = to_number(row.get("lat"), None)
            lon = to_number(row.get("lon"), None)
            coord = validate_coordinate(lat, lon)

            if coord["valid"]:
                location_quality = "exact_company_location"
                location_source = "policy_sheet_2_exact"
            elif lat is None or lon is None:
                location_quality = "missing_coordinate"
                location_source = "policy_sheet_2_missing_coordinate"
            else:
                location_quality = "invalid_coordinate"
                location_source = "policy_sheet_2_invalid_coordinate"

            record = {
                "source_file": str(POLICY_INPUT_PATH.name),
                "source_sheet": "company_location",
                "source_row": int(idx) + 2,

                "tax_id_raw": row.get("tax_id_raw", ""),
                "tax_id_norm": row.get("tax_id_norm", ""),
                "tax_id_valid": bool(row.get("tax_id_valid", False)),
                "tax_id_issue": row.get("tax_id_issue", ""),

                "company_name_location": clean_text(row.get("name_th")),
                "address": clean_text(row.get("address")),
                "province": normalize_province_name(row.get("province")),
                "district": clean_text(row.get("district")),
                "subdistrict": clean_text(row.get("subdistrict")),
                "lat": lat,
                "lon": lon,
                "point_company": clean_text(row.get("point_company")),
                "location_source": location_source,
                "location_quality": location_quality,
                "coordinate_valid": coord["valid"],
                "coordinate_issue": coord["issue"],
            }

            records.append(record)

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
            "source_path": str(POLICY_INPUT_PATH),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["company_location_master"],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source="company_policy_service.build_company_location_master",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def build_province_branch_coordinate_master(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง province_branch_coordinate_master จาก Policy Sheet 3
    """

    def builder() -> Dict[str, Any]:
        policy_sheets = load_policy_input()
        df = policy_sheets.get("province_branch_coordinate", pd.DataFrame())

        if df is None or df.empty:
            return {
                "records": [],
                "total": 0,
                "created_at": now_iso(),
                "warnings": ["province_branch_coordinate_empty_or_file_missing"],
            }

        records: List[Dict[str, Any]] = []

        for idx, row in df.iterrows():
            lat = to_number(row.get("lat"), None)
            lon = to_number(row.get("lon"), None)
            coord = validate_coordinate(lat, lon)

            province = normalize_province_name(row.get("province"))

            record = {
                "source_file": str(POLICY_INPUT_PATH.name),
                "source_sheet": "province_branch_coordinate",
                "source_row": int(idx) + 2,

                "branch_id": make_hash_id(
                    f"{province}|{row.get('branch_name')}|{row.get('district')}|{lat}|{lon}",
                    prefix="branch",
                    length=16,
                ),
                "province": province,
                "branch_name": clean_text(row.get("branch_name")),
                "region": clean_text(row.get("region")),
                "district": clean_text(row.get("district")),
                "subdistrict": clean_text(row.get("subdistrict")),
                "lat": lat,
                "lon": lon,
                "location_source": "policy_sheet_3_branch_or_province",
                "location_quality": "approximate_branch_or_province" if coord["valid"] else "invalid_coordinate",
                "coordinate_valid": coord["valid"],
                "coordinate_issue": coord["issue"],
            }

            records.append(record)

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
            "source_path": str(POLICY_INPUT_PATH),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["province_branch_coordinate_master"],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source="company_policy_service.build_province_branch_coordinate_master",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def get_location_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน company_location_master records
    """

    return build_company_location_master(force_refresh=force_refresh).get("records", [])


def get_branch_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน province_branch_coordinate_master records
    """

    return build_province_branch_coordinate_master(force_refresh=force_refresh).get("records", [])


# ============================================================
# 6) LINKAGE COMPANY PROFILE BUILDER
# ============================================================

def build_linkage_company_profile(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง linkage_company_profile จาก Linkage Input

    ใช้เฉพาะข้อมูลบริษัทสำหรับ join company_unified_master
    Linkage graph เต็มจะอยู่ใน linkage_service.py
    """

    def builder() -> Dict[str, Any]:
        df = load_linkage_company_input()

        if df is None or df.empty:
            return {
                "records": [],
                "total": 0,
                "created_at": now_iso(),
                "warnings": ["linkage_input_empty_or_file_missing"],
            }

        if "tax_id" not in df.columns:
            df["tax_id"] = ""

        df = add_tax_id_columns(df, source_column="tax_id")

        records: List[Dict[str, Any]] = []

        for idx, row in df.iterrows():
            record = {
                "source_file": str(LINKAGE_INPUT_PATH.name),
                "source_sheet": "linkage_input",
                "source_row": int(idx) + 2,

                "tax_id_raw": row.get("tax_id_raw", ""),
                "tax_id_norm": row.get("tax_id_norm", ""),
                "tax_id_valid": bool(row.get("tax_id_valid", False)),
                "tax_id_issue": row.get("tax_id_issue", ""),

                "company_name_linkage": clean_text(row.get("name_th")),
                "name_th": clean_text(row.get("name_th")),
                "boardlist": clean_text(row.get("boardlist")),

                "business_type_objective": clean_text(row.get("business_type_objective")),
                "business_type_tsic": clean_text(row.get("business_type_tsic")),
                "company_size": clean_text(row.get("company_size")),
                "wtip": clean_text(row.get("wtip")),

                "most_recent_income_val_linkage": to_number(row.get("most_recent_income_val"), None),
                "registered_capital_linkage": to_number(row.get("registered_capital"), None),
            }

            records.append(record)

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
            "source_path": str(LINKAGE_INPUT_PATH),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["linkage_company_profile"],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source="company_policy_service.build_linkage_company_profile",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def get_linkage_company_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน linkage company profile records
    """

    return build_linkage_company_profile(force_refresh=force_refresh).get("records", [])


# ============================================================
# 7) POLICY SUMMARY BUILDERS
# ============================================================

def build_policy_company_summary(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง policy_company_summary

    หลักการ:
    - group by valid tax_id_norm
    - ถ้า Tax ID ใช้ไม่ได้ ให้ใช้ company_key
    - sum เฉพาะ premium/loss/suminsure/noofpol
    - most_recent_asset_val / income / registered_capital ไม่ sum
    - loss_ratio = sum(loss) / sum(premium) * 100
    """

    def builder() -> Dict[str, Any]:
        policy_records = get_policy_fact_records(
            force_refresh=force_refresh
        )

        groups: Dict[
            str,
            List[Dict[str, Any]],
        ] = defaultdict(list)

        for policy_record in policy_records:
            company_key = get_company_group_key(
                policy_record
            )

            if company_key:
                groups[company_key].append(
                    policy_record
                )

        summary_records: List[
            Dict[str, Any]
        ] = []

        for company_key, records in groups.items():
            if (
                not company_key
                or company_key == "__EMPTY__"
            ):
                continue

            tax_id_norm = ""

            for item in records:
                tax_id_norm = get_valid_tax_id(
                    item.get("tax_id_norm")
                )

                if tax_id_norm:
                    break

            total_premium = sum_field(
                records,
                "premium",
            )
            total_loss = sum_field(
                records,
                "loss",
            )
            total_suminsure = sum_field(
                records,
                "suminsure",
            )
            total_noofpol = sum_field(
                records,
                "noofpol",
            )

            loss_ratio = calculate_loss_ratio(
                total_loss,
                total_premium,
                zero_policy="zero",
            )

            policy_years: List[int] = []

            for item in records:
                policy_year = to_int(
                    item.get("policy_year"),
                    default=None,
                )

                if policy_year is not None:
                    policy_years.append(
                        policy_year
                    )

            active_records = [
                item
                for item in records
                if bool(
                    to_bool(
                        item.get(
                            "is_active_policy"
                        ),
                        default=False,
                    )
                )
            ]

            expired_records = [
                item
                for item in records
                if bool(
                    to_bool(
                        item.get(
                            "is_expired_policy"
                        ),
                        default=False,
                    )
                )
            ]

            company_name = most_common_value(
                [
                    item.get("company_name")
                    for item in records
                ],
                default="",
            )

            province = most_common_value(
                [
                    item.get("province")
                    for item in records
                ],
                default="",
            )

            business_type = most_common_value(
                [
                    item.get("business_type")
                    for item in records
                ],
                default="",
            )

            income_range = most_common_value(
                [
                    item.get("income_range")
                    for item in records
                ],
                default="",
            )

            most_recent_asset_val = first_non_empty(
                *[
                    item.get(
                        "most_recent_asset_val"
                    )
                    for item in records
                ],
                default=None,
            )

            most_recent_income_val = first_non_empty(
                *[
                    item.get(
                        "most_recent_income_val"
                    )
                    for item in records
                ],
                default=None,
            )

            registered_capital = first_non_empty(
                *[
                    item.get(
                        "registered_capital"
                    )
                    for item in records
                ],
                default=None,
            )

            active_subs = max(
                [
                    (
                        to_number(
                            item.get("active_subs"),
                            0,
                        )
                        or 0
                    )
                    for item in records
                ],
                default=0,
            )

            expired_subs = max(
                [
                    (
                        to_number(
                            item.get(
                                "expired_subs"
                            ),
                            0,
                        )
                        or 0
                    )
                    for item in records
                ],
                default=0,
            )

            product_holding = max(
                [
                    (
                        to_number(
                            item.get(
                                "product_holding"
                            ),
                            0,
                        )
                        or 0
                    )
                    for item in records
                ],
                default=0,
            )

            subclass_holding = max(
                [
                    (
                        to_number(
                            item.get(
                                "subclass_holding"
                            ),
                            0,
                        )
                        or 0
                    )
                    for item in records
                ],
                default=0,
            )

            tax_validation = validate_tax_id(
                tax_id_norm
            )

            summary_records.append(
                {
                    "company_key": company_key,
                    "tax_id_raw": first_non_empty(
                        *[
                            item.get(
                                "tax_id_raw"
                            )
                            for item in records
                        ],
                        default="",
                    ),
                    "tax_id_norm": tax_id_norm,
                    "tax_id_valid": bool(
                        tax_validation.get(
                            "tax_id_valid",
                            False,
                        )
                    ),
                    "tax_id_issue": tax_validation.get(
                        "tax_id_issue",
                        "",
                    ),
                    "company_name_policy": company_name,
                    "company_name": company_name,
                    "province": province,
                    "business_type": business_type,
                    "income_range": income_range,
                    "total_premium": total_premium,
                    "total_loss": total_loss,
                    "total_suminsure": total_suminsure,
                    "total_noofpol": total_noofpol,
                    "active_policy_count": len(
                        active_records
                    ),
                    "expired_policy_count": len(
                        expired_records
                    ),
                    "policy_record_count": len(
                        records
                    ),
                    "product_count": count_distinct(
                        records,
                        "product",
                    ),
                    "subclass_count": count_distinct(
                        records,
                        "subclass",
                    ),
                    "active_subs": active_subs,
                    "expired_subs": expired_subs,
                    "product_holding": product_holding,
                    "subclass_holding": subclass_holding,
                    "most_recent_asset_val": (
                        most_recent_asset_val
                    ),
                    "most_recent_income_val": (
                        most_recent_income_val
                    ),
                    "registered_capital": registered_capital,
                    "loss_ratio": loss_ratio,
                    "loss_ratio_band": get_loss_ratio_band(
                        loss_ratio,
                        premium=total_premium,
                        loss=total_loss,
                    ),
                    "premium_zero_with_loss_count": sum(
                        1
                        for item in records
                        if bool(
                            to_bool(
                                item.get(
                                    "premium_zero_with_loss"
                                ),
                                default=False,
                            )
                        )
                    ),
                    "status_conflict_count": sum(
                        1
                        for item in records
                        if bool(
                            to_bool(
                                item.get(
                                    "status_conflict_flag"
                                ),
                                default=False,
                            )
                        )
                    ),
                    "first_policy_year": (
                        min(policy_years)
                        if policy_years
                        else None
                    ),
                    "latest_policy_year": (
                        max(policy_years)
                        if policy_years
                        else None
                    ),
                }
            )

        summary_records = sorted(
            summary_records,
            key=lambda item: (
                to_number(
                    item.get(
                        "total_suminsure"
                    ),
                    0,
                )
                or 0
            ),
            reverse=True,
        )

        return {
            "records": summary_records,
            "total": len(
                summary_records
            ),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "policy_company_summary"
        ],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source=(
            "company_policy_service."
            "build_policy_company_summary"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }

def build_policy_product_summary(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง policy_product_summary
    """

    def builder() -> Dict[str, Any]:
        policy_records = get_policy_fact_records(
            force_refresh=force_refresh
        )
        groups = group_records_by(
            policy_records,
            "product",
        )

        records: List[Dict[str, Any]] = []

        for product, group in groups.items():
            if product == "__EMPTY__":
                product = "Unknown"

            summary = build_policy_summary_from_records(
                group
            )

            records.append(
                {
                    "product": product,
                    "company_count": count_distinct_companies(
                        group
                    ),
                    "subclass_count": count_distinct(
                        group,
                        "subclass",
                    ),
                    **summary,
                }
            )

        records = sorted(
            records,
            key=lambda item: (
                to_number(
                    item.get("total_premium"),
                    0,
                )
                or 0
            ),
            reverse=True,
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "policy_product_summary"
        ],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source=(
            "company_policy_service."
            "build_policy_product_summary"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }


def build_policy_subclass_summary(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง policy_subclass_summary
    """

    def builder() -> Dict[str, Any]:
        policy_records = get_policy_fact_records(
            force_refresh=force_refresh
        )
        groups = group_records_by(
            policy_records,
            "subclass",
        )

        records: List[Dict[str, Any]] = []

        for subclass, group in groups.items():
            if subclass == "__EMPTY__":
                subclass = "Unknown"

            summary = build_policy_summary_from_records(
                group
            )

            records.append(
                {
                    "subclass": subclass,
                    "company_count": count_distinct_companies(
                        group
                    ),
                    "product_count": count_distinct(
                        group,
                        "product",
                    ),
                    **summary,
                }
            )

        records = sorted(
            records,
            key=lambda item: (
                to_number(
                    item.get("total_premium"),
                    0,
                )
                or 0
            ),
            reverse=True,
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "policy_subclass_summary"
        ],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source=(
            "company_policy_service."
            "build_policy_subclass_summary"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }


def build_policy_yearly_summary(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง policy_yearly_summary
    """

    def builder() -> Dict[str, Any]:
        policy_records = get_policy_fact_records(
            force_refresh=force_refresh
        )

        records_with_year = [
            record
            for record in policy_records
            if record.get("policy_year")
            is not None
        ]

        groups = group_records_by(
            records_with_year,
            "policy_year",
        )

        records: List[Dict[str, Any]] = []

        for year, group in groups.items():
            if year == "__EMPTY__":
                continue

            summary = build_policy_summary_from_records(
                group
            )

            records.append(
                {
                    "policy_year": to_int(
                        year,
                        default=None,
                    ),
                    "company_count": count_distinct_companies(
                        group
                    ),
                    "product_count": count_distinct(
                        group,
                        "product",
                    ),
                    "subclass_count": count_distinct(
                        group,
                        "subclass",
                    ),
                    **summary,
                }
            )

        records = sorted(
            records,
            key=lambda item: (
                item.get("policy_year")
                or 0
            ),
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "policy_yearly_summary"
        ],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source=(
            "company_policy_service."
            "build_policy_yearly_summary"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }

def build_policy_loss_ratio_summary(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง policy_loss_ratio_summary ตาม band
    """

    def builder() -> Dict[str, Any]:
        company_summary = build_policy_company_summary(force_refresh=force_refresh).get("records", [])
        groups = group_records_by(company_summary, "loss_ratio_band")

        records: List[Dict[str, Any]] = []

        for band, group in groups.items():
            if band == "__EMPTY__":
                band = "Undefined"

            records.append(
                {
                    "loss_ratio_band": band,
                    "company_count": len(group),
                    "total_premium": sum_field(group, "total_premium"),
                    "total_loss": sum_field(group, "total_loss"),
                    "total_suminsure": sum_field(group, "total_suminsure"),
                    "average_loss_ratio": (
                        sum(to_number(r.get("loss_ratio"), 0) or 0 for r in group) / len(group)
                        if group
                        else 0
                    ),
                }
            )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["policy_loss_ratio_summary"],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source="company_policy_service.build_policy_loss_ratio_summary",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


# ============================================================
# 8) COMPANY UNIFIED MASTER BUILDER
# ============================================================

def index_records_by_tax_id(
    records: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    index records ด้วย valid tax_id_norm

    ถ้ามีซ้ำ:
    - ให้ record ที่มี coordinate valid ก่อน
    - จากนั้นเลือก record ที่มีข้อมูลครบกว่า
    """

    result: Dict[
        str,
        Dict[str, Any],
    ] = {}

    def record_score(
        record: Dict[str, Any],
    ) -> int:
        coordinate = validate_coordinate(
            first_non_empty(
                record.get("lat"),
                record.get("latitude"),
                record.get("company_lat"),
                default=None,
            ),
            first_non_empty(
                record.get("lon"),
                record.get("longitude"),
                record.get("company_lon"),
                default=None,
            ),
        )

        coordinate_score = (
            10000
            if coordinate.get("valid")
            else 0
        )

        explicit_coordinate_score = (
            1000
            if bool(
                to_bool(
                    record.get(
                        "coordinate_valid"
                    ),
                    default=False,
                )
            )
            else 0
        )

        completeness_score = sum(
            1
            for value in record.values()
            if not is_empty_value(value)
        )

        return (
            coordinate_score
            + explicit_coordinate_score
            + completeness_score
        )

    for record in records:
        tax_id_norm = get_valid_tax_id(
            record.get("tax_id_norm")
            or record.get("tax_id")
            or record.get("tax_id_raw")
        )

        if not tax_id_norm:
            continue

        if tax_id_norm not in result:
            result[tax_id_norm] = record
            continue

        if (
            record_score(record)
            > record_score(
                result[tax_id_norm]
            )
        ):
            result[tax_id_norm] = record

    return result

def build_branch_index_by_province(branch_records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    สร้าง index พิกัด fallback ระดับจังหวัด/สาขา

    เลือก record แรกที่ coordinate valid
    """

    result: Dict[str, Dict[str, Any]] = {}

    for record in branch_records:
        province = normalize_province_name(record.get("province"))

        if not province:
            continue

        coord = validate_coordinate(record.get("lat"), record.get("lon"))

        if not coord["valid"]:
            continue

        if province not in result:
            result[province] = record

    return result


def extract_cached_records(
    payload: Any,
) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [
            record
            for record in payload
            if isinstance(record, dict)
        ]

    if not isinstance(payload, dict):
        return []

    for key in [
        "records",
        "items",
    ]:
        value = payload.get(key)

        if isinstance(value, list):
            return [
                record
                for record in value
                if isinstance(record, dict)
            ]

    data = payload.get("data")

    if isinstance(data, list):
        return [
            record
            for record in data
            if isinstance(record, dict)
        ]

    if isinstance(data, dict):
        return extract_cached_records(data)

    return []


def load_spatial_context_index() -> Dict[str, Dict[str, Any]]:
    """
    โหลด spatial_join_result จาก cache ถ้ามี

    ใช้เติม:
    - has_flood_context
    - flood_risk_level
    - flood_join_level
    - flood_risk_reason
    - nearest station
    """

    records = extract_cached_records(
        read_cache(
            "spatial_join_result",
            default={},
        )
    )

    return index_records_by_tax_id(
        records
    )


def load_linkage_summary_index() -> Dict[str, Dict[str, Any]]:
    """
    โหลด linkage company summary จาก cache

    ใช้เติม:
    - director_count
    - shared_company_count
    - key_connector_count
    - linkage_risk_level
    """

    result: Dict[
        str,
        Dict[str, Any],
    ] = {}

    summary_records = extract_cached_records(
        read_cache(
            "linkage_company_summary",
            default={},
        )
    )

    for record in summary_records:
        tax_id_norm = get_valid_tax_id(
            record.get("tax_id_norm")
            or record.get("tax_id")
        )

        if not tax_id_norm:
            continue

        result[tax_id_norm] = {
            "director_count": (
                to_int(
                    record.get(
                        "director_count"
                    ),
                    0,
                )
                or 0
            ),
            "shared_company_count": (
                to_int(
                    record.get(
                        "shared_company_count"
                    ),
                    0,
                )
                or 0
            ),
            "key_connector_count": (
                to_int(
                    record.get(
                        "key_connector_count"
                    ),
                    0,
                )
                or 0
            ),
            "has_linkage": bool(
                to_bool(
                    record.get(
                        "has_linkage"
                    ),
                    default=False,
                )
            ),
            "linkage_risk_level": clean_text(
                record.get(
                    "linkage_risk_level"
                )
            ),
        }

    pair_records = extract_cached_records(
        read_cache(
            "director_company_pairs",
            default={},
        )
    )

    director_records = extract_cached_records(
        read_cache(
            "director_master",
            default={},
        )
    )

    key_connector_director_ids = {
        clean_text(
            record.get("director_id")
            or record.get("person_id")
        )
        for record in director_records
        if bool(
            to_bool(
                record.get(
                    "is_key_connector"
                ),
                default=False,
            )
        )
        and clean_text(
            record.get("director_id")
            or record.get("person_id")
        )
    }

    directors_by_tax_id: Dict[
        str,
        set,
    ] = defaultdict(set)

    key_connectors_by_tax_id: Dict[
        str,
        set,
    ] = defaultdict(set)

    for pair in pair_records:
        tax_id_norm = get_valid_tax_id(
            pair.get("tax_id_norm")
            or pair.get("tax_id")
        )

        director_id = clean_text(
            pair.get("director_id")
            or pair.get("person_id")
        )

        if not tax_id_norm:
            continue

        if director_id:
            directors_by_tax_id[
                tax_id_norm
            ].add(director_id)

            if (
                director_id
                in key_connector_director_ids
            ):
                key_connectors_by_tax_id[
                    tax_id_norm
                ].add(director_id)

    shared_company_by_tax_id: Dict[
        str,
        set,
    ] = defaultdict(set)

    shared_links = extract_cached_records(
        read_cache(
            "shared_director_links",
            default={},
        )
    )

    for link in shared_links:
        source_tax_id = get_valid_tax_id(
            link.get("source_tax_id")
            or link.get(
                "source_tax_id_norm"
            )
            or link.get(
                "company_a_tax_id"
            )
        )

        target_tax_id = get_valid_tax_id(
            link.get("target_tax_id")
            or link.get(
                "target_tax_id_norm"
            )
            or link.get(
                "company_b_tax_id"
            )
        )

        if (
            not source_tax_id
            or not target_tax_id
            or source_tax_id
            == target_tax_id
        ):
            continue

        shared_company_by_tax_id[
            source_tax_id
        ].add(target_tax_id)

        shared_company_by_tax_id[
            target_tax_id
        ].add(source_tax_id)

    all_tax_ids = (
        set(result)
        | set(directors_by_tax_id)
        | set(shared_company_by_tax_id)
        | set(key_connectors_by_tax_id)
    )

    for tax_id_norm in all_tax_ids:
        item = result.setdefault(
            tax_id_norm,
            {
                "director_count": 0,
                "shared_company_count": 0,
                "key_connector_count": 0,
                "has_linkage": False,
                "linkage_risk_level": "",
            },
        )

        item["director_count"] = max(
            to_int(
                item.get("director_count"),
                0,
            )
            or 0,
            len(
                directors_by_tax_id.get(
                    tax_id_norm,
                    set(),
                )
            ),
        )

        item["shared_company_count"] = max(
            to_int(
                item.get(
                    "shared_company_count"
                ),
                0,
            )
            or 0,
            len(
                shared_company_by_tax_id.get(
                    tax_id_norm,
                    set(),
                )
            ),
        )

        item["key_connector_count"] = max(
            to_int(
                item.get(
                    "key_connector_count"
                ),
                0,
            )
            or 0,
            len(
                key_connectors_by_tax_id.get(
                    tax_id_norm,
                    set(),
                )
            ),
        )

        item["has_linkage"] = bool(
            item["director_count"]
            or item[
                "shared_company_count"
            ]
            or item[
                "key_connector_count"
            ]
        )

        if (
            item["key_connector_count"] > 0
            or item[
                "shared_company_count"
            ]
            >= 5
        ):
            item["linkage_risk_level"] = (
                "Warning"
            )
        elif (
            item[
                "shared_company_count"
            ]
            > 0
            or item["director_count"] > 0
        ):
            item["linkage_risk_level"] = (
                "Watch"
            )
        else:
            item["linkage_risk_level"] = (
                "Normal"
            )

    return result

def index_records_by_company_key(
    records: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    index records โดยใช้ valid tax_id_norm ก่อน
    ถ้าไม่มี valid tax_id_norm ให้ใช้ company_key
    """

    result: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for record in records:
        key = get_company_group_key(
            record
        )

        if not key:
            continue

        if key not in result:
            result[key] = record
            continue

        old_score = sum(
            1
            for value in result[
                key
            ].values()
            if not is_empty_value(value)
        )

        new_score = sum(
            1
            for value in record.values()
            if not is_empty_value(value)
        )

        if new_score > old_score:
            result[key] = record

    return result

def build_company_base_record(
    company_key: str,
    policy: Dict[str, Any],
    location: Dict[str, Any],
    linkage: Dict[str, Any],
    branch_by_province: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    สร้าง 1 record สำหรับ company_unified_base

    base ห้ามรอ spatial_join_result
    และห้ามรอ linkage graph summary
    """

    tax_id_norm = ""

    for candidate in [
        (
            company_key
            if company_key.isdigit()
            else ""
        ),
        policy.get("tax_id_norm"),
        linkage.get("tax_id_norm"),
        location.get("tax_id_norm"),
    ]:
        tax_id_norm = get_valid_tax_id(
            candidate
        )

        if tax_id_norm:
            break

    tax_validation = validate_tax_id(
        tax_id_norm
    )

    tax_id_raw = first_non_empty(
        policy.get("tax_id_raw"),
        linkage.get("tax_id_raw"),
        location.get("tax_id_raw"),
        tax_id_norm,
        default="",
    )

    company_name = first_non_empty(
        policy.get(
            "company_name_policy"
        ),
        policy.get("company_name"),
        linkage.get(
            "company_name_linkage"
        ),
        linkage.get("name_th"),
        location.get(
            "company_name_location"
        ),
        default="",
    )

    province = normalize_province_name(
        first_non_empty(
            policy.get("province"),
            location.get("province"),
            default="",
        )
    )

    lat = location.get("lat")
    lon = location.get("lon")

    location_source = clean_text(
        location.get(
            "location_source",
            "",
        )
    )

    location_quality = clean_text(
        location.get(
            "location_quality",
            "missing_coordinate",
        ),
        default="missing_coordinate",
    )

    coordinate = validate_coordinate(
        lat,
        lon,
    )

    if (
        not coordinate.get("valid")
        and province
        in branch_by_province
    ):
        branch = branch_by_province[
            province
        ]

        lat = branch.get("lat")
        lon = branch.get("lon")

        location_source = clean_text(
            branch.get(
                "location_source",
                (
                    "policy_sheet_3_"
                    "branch_or_province"
                ),
            )
        )

        location_quality = (
            "approximate_branch_or_province"
        )

    final_coordinate = validate_coordinate(
        lat,
        lon,
    )

    if not final_coordinate.get("valid"):
        if (
            is_empty_value(lat)
            or is_empty_value(lon)
        ):
            location_quality = (
                "missing_coordinate"
            )
        else:
            location_quality = (
                "invalid_coordinate"
            )

    has_policy = bool(policy)
    has_linkage = bool(linkage)
    has_location = bool(
        final_coordinate.get("valid")
    )

    active_policy_count = (
        to_number(
            policy.get(
                "active_policy_count"
            ),
            0,
        )
        or 0
    )

    expired_policy_count = (
        to_number(
            policy.get(
                "expired_policy_count"
            ),
            0,
        )
        or 0
    )

    if active_policy_count > 0:
        policy_status = "Active"
    elif expired_policy_count > 0:
        policy_status = "Expired"
    else:
        policy_status = "Unknown"

    record = {
        "tax_id_raw": tax_id_raw,
        "tax_id_norm": tax_id_norm,
        "tax_id_valid": bool(
            tax_validation.get(
                "tax_id_valid",
                False,
            )
        ),
        "tax_id_issue": tax_validation.get(
            "tax_id_issue",
            "",
        ),
        "company_key": company_key,
        "company_name": company_name,
        "company_name_policy": policy.get(
            "company_name_policy",
            "",
        ),
        "company_name_linkage": linkage.get(
            "company_name_linkage",
            "",
        ),
        "company_name_location": location.get(
            "company_name_location",
            "",
        ),
        "business_type": policy.get(
            "business_type",
            "",
        ),
        "business_type_objective": linkage.get(
            "business_type_objective",
            "",
        ),
        "business_type_tsic": linkage.get(
            "business_type_tsic",
            "",
        ),
        "company_size": linkage.get(
            "company_size",
            "",
        ),
        "wtip": linkage.get(
            "wtip",
            "",
        ),
        "boardlist": linkage.get(
            "boardlist",
            "",
        ),
        "boardlist_raw": linkage.get(
            "boardlist",
            "",
        ),
        "boardlist_profile": {
            "raw": linkage.get(
                "boardlist",
                "",
            ),
            "has_boardlist": bool(
                clean_text(
                    linkage.get(
                        "boardlist"
                    )
                )
            ),
        },
        "most_recent_asset_val": policy.get(
            "most_recent_asset_val"
        ),
        "most_recent_income_val": first_non_empty(
            policy.get(
                "most_recent_income_val"
            ),
            policy.get(
                "most_recent_income_val_policy"
            ),
            linkage.get(
                "most_recent_income_val_linkage"
            ),
            default=None,
        ),
        "registered_capital": first_non_empty(
            policy.get(
                "registered_capital"
            ),
            policy.get(
                "registered_capital_policy"
            ),
            linkage.get(
                "registered_capital_linkage"
            ),
            default=None,
        ),
        "address": location.get(
            "address",
            "",
        ),
        "province": province,
        "district": location.get(
            "district",
            "",
        ),
        "subdistrict": location.get(
            "subdistrict",
            "",
        ),
        "lat": final_coordinate.get(
            "lat"
        ),
        "lon": final_coordinate.get(
            "lon"
        ),
        "latitude": final_coordinate.get(
            "lat"
        ),
        "longitude": final_coordinate.get(
            "lon"
        ),
        "location_source": location_source,
        "location_quality": location_quality,
        "coordinate_valid": bool(
            final_coordinate.get("valid")
        ),
        "coordinate_issue": final_coordinate.get(
            "issue",
            "",
        ),
        "has_policy": has_policy,
        "has_linkage": has_linkage,
        "has_location": has_location,
        "has_flood_context": False,
        "policy_status": policy_status,
        "premium": policy.get(
            "total_premium",
            0,
        ),
        "loss": policy.get(
            "total_loss",
            0,
        ),
        "suminsure": policy.get(
            "total_suminsure",
            0,
        ),
        "total_premium": policy.get(
            "total_premium",
            0,
        ),
        "total_loss": policy.get(
            "total_loss",
            0,
        ),
        "total_suminsure": policy.get(
            "total_suminsure",
            0,
        ),
        "total_noofpol": policy.get(
            "total_noofpol",
            0,
        ),
        "active_policy_count": active_policy_count,
        "expired_policy_count": expired_policy_count,
        "policy_record_count": policy.get(
            "policy_record_count",
            0,
        ),
        "product_count": policy.get(
            "product_count",
            0,
        ),
        "subclass_count": policy.get(
            "subclass_count",
            0,
        ),
        "product_summary": {
            "product_count": policy.get(
                "product_count",
                0,
            ),
            "product_holding": policy.get(
                "product_holding",
                0,
            ),
        },
        "subclass_summary": {
            "subclass_count": policy.get(
                "subclass_count",
                0,
            ),
            "subclass_holding": policy.get(
                "subclass_holding",
                0,
            ),
        },
        "first_policy_year": policy.get(
            "first_policy_year"
        ),
        "latest_policy_year": policy.get(
            "latest_policy_year"
        ),
        "loss_ratio": policy.get(
            "loss_ratio"
        ),
        "loss_ratio_band": policy.get(
            "loss_ratio_band",
            "Undefined",
        ),
        "premium_zero_with_loss_count": policy.get(
            "premium_zero_with_loss_count",
            0,
        ),
        "status_conflict_count": policy.get(
            "status_conflict_count",
            0,
        ),
        "director_count": 0,
        "shared_company_count": 0,
        "key_connector_count": 0,
        "linkage_risk_level": "Unknown",
        "flood_risk_level": "Unknown",
        "flood_join_level": "none",
        "flood_risk_reason": "",
        "nearest_rainfall_station_id": "",
        "nearest_waterlevel_station_id": "",
        "nearest_dam_id": "",
        "data_quality_flags": [],
        "source_flags": {
            "has_policy": has_policy,
            "has_linkage": has_linkage,
            "has_location": has_location,
            "has_flood_context": False,
            "is_base_record": True,
            "is_enriched_record": False,
        },
        "record_stage": "base",
        "updated_at": now_iso(),
    }

    return to_jsonable(record)

def enrich_company_base_record(
    base_record: Dict[str, Any],
    spatial: Dict[str, Any],
    linkage_summary: Dict[str, Any],
    quality_flags: List[str],
) -> Dict[str, Any]:
    """
    เติม enrichment หลัง linkage/flood/spatial/data_quality พร้อมแล้ว
    """

    record = dict(base_record)

    has_flood_context = bool(
        to_bool(
            spatial.get("has_flood_context"),
            default=False,
        )
    )

    flood_risk_level = first_non_empty(
        spatial.get("final_flood_risk_level"),
        spatial.get("flood_risk_level"),
        spatial.get("province_risk_level"),
        default="Unknown",
    )

    director_count = to_int(linkage_summary.get("director_count"), 0)
    shared_company_count = to_int(linkage_summary.get("shared_company_count"), 0)
    key_connector_count = to_int(linkage_summary.get("key_connector_count"), 0)

    record.update(
        {
            "has_linkage": bool(record.get("has_linkage")) or bool(linkage_summary.get("has_linkage")),
            "has_flood_context": has_flood_context,

            "director_count": director_count,
            "shared_company_count": shared_company_count,
            "key_connector_count": key_connector_count,
            "linkage_risk_level": linkage_summary.get("linkage_risk_level", "Unknown"),

            "flood_risk_level": flood_risk_level,
            "flood_join_level": first_non_empty(
                spatial.get("join_level"),
                spatial.get("flood_join_level"),
                default="none",
            ),
            "flood_risk_reason": first_non_empty(
                spatial.get("flood_risk_reason"),
                spatial.get("risk_reason"),
                default="",
            ),
            "nearest_rainfall_station_id": spatial.get("nearest_rainfall_station_id", ""),
            "nearest_waterlevel_station_id": spatial.get("nearest_waterlevel_station_id", ""),
            "nearest_dam_id": spatial.get("nearest_dam_id", ""),
            "data_quality_flags": quality_flags or [],
            "record_stage": "enriched",
            "updated_at": now_iso(),
        }
    )

    record["source_flags"] = {
        **(record.get("source_flags") if isinstance(record.get("source_flags"), dict) else {}),
        "has_policy": bool(record.get("has_policy")),
        "has_linkage": bool(record.get("has_linkage")),
        "has_location": bool(record.get("has_location")),
        "has_flood_context": has_flood_context,
        "is_base_record": False,
        "is_enriched_record": True,
    }

    return to_jsonable(record)


def build_company_unified_base(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง company_unified_base

    base รวมเฉพาะ policy + location + branch/province fallback + linkage company profile
    ไม่อ่าน spatial_join_result
    ไม่อ่าน linkage graph summary
    """

    def builder() -> Dict[str, Any]:
        policy_company = build_policy_company_summary(force_refresh=force_refresh).get("records", [])
        location_records = build_company_location_master(force_refresh=force_refresh).get("records", [])
        branch_records = build_province_branch_coordinate_master(force_refresh=force_refresh).get("records", [])
        linkage_records = build_linkage_company_profile(force_refresh=force_refresh).get("records", [])

        policy_index = index_records_by_company_key(policy_company)
        location_index = index_records_by_tax_id(location_records)
        linkage_index = index_records_by_tax_id(linkage_records)
        branch_by_province = build_branch_index_by_province(branch_records)

        all_company_keys = sorted(
            set(policy_index.keys())
            | set(location_index.keys())
            | set(linkage_index.keys())
        )

        base_records: List[Dict[str, Any]] = []

        for company_key in all_company_keys:
            policy = policy_index.get(company_key, {})

            tax_id_norm = normalize_tax_id(
                first_non_empty(
                    company_key if company_key.isdigit() else "",
                    policy.get("tax_id_norm"),
                    default="",
                )
            )

            location = location_index.get(tax_id_norm, {}) if tax_id_norm else {}
            linkage = linkage_index.get(tax_id_norm, {}) if tax_id_norm else {}

            base_records.append(
                build_company_base_record(
                    company_key=company_key,
                    policy=policy,
                    location=location,
                    linkage=linkage,
                    branch_by_province=branch_by_province,
                )
            )

        base_records = sorted(
            base_records,
            key=lambda item: clean_text(item.get("company_name")),
        )

        return {
            "records": base_records,
            "total": len(base_records),
            "created_at": now_iso(),
            "stage": "base",
            "source": {
                "policy_company_count": len(policy_company),
                "location_count": len(location_records),
                "branch_count": len(branch_records),
                "linkage_company_count": len(linkage_records),
                "spatial_context_count": 0,
                "linkage_summary_count": 0,
            },
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["company_unified_base"],
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source="company_policy_service.build_company_unified_base",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }

def build_company_unified_master(
    force_refresh: bool = False,
    enrichment_mode: str = "full",
) -> Dict[str, Any]:
    """
    สร้าง company_unified_master enriched

    enriched = company_unified_base
    + linkage summary
    + flood/spatial context
    + data quality flags
    """

    normalized_mode = clean_text_lower(
        enrichment_mode,
        default="full",
    )

    allowed_modes = {
        "full",
        "spatial",
        "flood",
        "linkage",
        "data_quality",
    }

    if normalized_mode not in allowed_modes:
        normalized_mode = "full"

    def builder() -> Dict[str, Any]:
        base_payload = build_company_unified_base(
            force_refresh=force_refresh
        )

        base_records = base_payload.get(
            "records",
            [],
        )

        spatial_index = (
            load_spatial_context_index()
            if normalized_mode
            in {
                "full",
                "spatial",
                "flood",
            }
            else {}
        )

        linkage_summary_index = (
            load_linkage_summary_index()
            if normalized_mode
            in {
                "full",
                "linkage",
            }
            else {}
        )

        quality_flags_by_tax_id: Dict[
            str,
            List[str],
        ] = {}

        if (
            normalized_mode
            in {
                "full",
                "data_quality",
            }
            and build_quality_flags_by_tax_id
            is not None
        ):
            try:
                quality_flags_by_tax_id = (
                    build_quality_flags_by_tax_id()
                )
            except Exception:
                quality_flags_by_tax_id = {}

        enriched_records: List[
            Dict[str, Any]
        ] = []

        for base_record in base_records:
            tax_id_norm = get_valid_tax_id(
                base_record.get(
                    "tax_id_norm"
                )
            )

            spatial = (
                spatial_index.get(
                    tax_id_norm,
                    {},
                )
                if tax_id_norm
                else {}
            )

            linkage_summary = (
                linkage_summary_index.get(
                    tax_id_norm,
                    {},
                )
                if tax_id_norm
                else {}
            )

            quality_flags = (
                quality_flags_by_tax_id.get(
                    tax_id_norm,
                    [],
                )
                if tax_id_norm
                else []
            )

            enriched_records.append(
                enrich_company_base_record(
                    base_record=base_record,
                    spatial=spatial,
                    linkage_summary=linkage_summary,
                    quality_flags=quality_flags,
                )
            )

        enriched_records = sorted(
            enriched_records,
            key=lambda item: clean_text(
                item.get("company_name")
            ),
        )

        return {
            "records": enriched_records,
            "total": len(
                enriched_records
            ),
            "created_at": now_iso(),
            "stage": "enriched",
            "enrichment_mode": normalized_mode,
            "source": {
                "base_count": len(
                    base_records
                ),
                "spatial_context_count": len(
                    spatial_index
                ),
                "linkage_summary_count": len(
                    linkage_summary_index
                ),
                "quality_flag_company_count": len(
                    quality_flags_by_tax_id
                ),
            },
        }

    cache_key = (
        CACHE_KEYS[
            "company_unified_master"
        ]
        if normalized_mode == "full"
        else (
            f"{CACHE_KEYS['company_unified_master']}_"
            f"{normalized_mode}"
        )
    )

    cache_result = get_or_build_cache(
        cache_key=cache_key,
        builder=builder,
        ttl_seconds=get_policy_ttl(),
        force_refresh=force_refresh,
        source=(
            "company_policy_service."
            "build_company_unified_master."
            f"{normalized_mode}"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
        "cache_key": cache_key,
    }

def get_company_unified_base_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน company_unified_base records

    flood_spatial_service.py ใช้ตัวนี้เพื่อตัด circular dependency
    """

    return build_company_unified_base(force_refresh=force_refresh).get("records", [])

def get_company_unified_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน company_unified_master enriched records

    dashboard/map/package ใช้ตัวนี้
    """

    return build_company_unified_master(force_refresh=force_refresh, enrichment_mode="full").get("records", [])


# ============================================================
# 9) COMPANY API FUNCTIONS
# ============================================================

def get_company_list(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/companies
    """

    ctx = normalize_context(context)
    records = get_company_unified_records(force_refresh=ctx.get("force_refresh", False))

    result = filter_records_for_api(
        records=records,
        context=ctx,
        searchable_fields=COMPANY_SEARCHABLE_FIELDS,
    )

    return {
        **result,
        "cache_key": CACHE_KEYS["company_unified_master"],
    }

def get_company_summary(
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ctx = normalize_context(context)

        records = get_company_unified_records(
            force_refresh=ctx.get(
                "force_refresh",
                False,
            )
        )

        filtered_records = filter_records_without_pagination(
            records=records,
            context=ctx,
            searchable_fields=COMPANY_SEARCHABLE_FIELDS,
        )

        total_companies = len(
            filtered_records
        )

        companies_with_policy = sum(
            1
            for record in filtered_records
            if bool(
                to_bool(
                    record.get("has_policy"),
                    default=False,
                )
            )
        )

        companies_with_linkage = sum(
            1
            for record in filtered_records
            if bool(
                to_bool(
                    record.get("has_linkage"),
                    default=False,
                )
            )
        )

        companies_with_location = sum(
            1
            for record in filtered_records
            if bool(
                to_bool(
                    record.get("has_location"),
                    default=False,
                )
            )
        )

        companies_with_flood_context = sum(
            1
            for record in filtered_records
            if bool(
                to_bool(
                    record.get(
                        "has_flood_context"
                    ),
                    default=False,
                )
            )
        )

        flood_risk_counts = Counter(
            clean_text(
                record.get(
                    "flood_risk_level"
                ),
                default="Unknown",
            )
            for record in filtered_records
        )

        province_counts = Counter(
            clean_text(
                record.get("province"),
                default="Unknown",
            )
            for record in filtered_records
        )

        loss_ratio_values = [
            to_number(
                record.get("loss_ratio"),
                None,
            )
            for record in filtered_records
        ]

        loss_ratio_values = [
            value
            for value in loss_ratio_values
            if value is not None
        ]

        return {
            "total_companies": total_companies,
            "companies_with_policy": companies_with_policy,
            "companies_with_linkage": companies_with_linkage,
            "companies_with_location": companies_with_location,
            "companies_with_flood_context": (
                companies_with_flood_context
            ),
            "total_premium": sum_field(
                filtered_records,
                "total_premium",
            ),
            "total_loss": sum_field(
                filtered_records,
                "total_loss",
            ),
            "total_suminsure": sum_field(
                filtered_records,
                "total_suminsure",
            ),
            "average_loss_ratio": (
                sum(loss_ratio_values)
                / len(loss_ratio_values)
                if loss_ratio_values
                else 0
            ),
            "flood_risk_counts": dict(
                flood_risk_counts
            ),
            "province_counts": dict(
                province_counts
            ),
            "generated_at": now_iso(),
        }

def get_company_detail(
    tax_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/companies/<tax_id>
    """

    tax_validation = validate_tax_id(
        tax_id
    )

    tax_id_norm = clean_text(
        tax_validation.get(
            "tax_id_norm"
        )
    )

    if not tax_validation.get(
        "tax_id_valid",
        False,
    ):
        return {
            "tax_id": tax_id,
            "tax_id_norm": tax_id_norm,
            "found": False,
            "company": None,
            "policy": {
                "records": [],
                "total": 0,
            },
        }

    ctx = normalize_context(context)

    company_records = get_company_unified_records(
        force_refresh=ctx.get(
            "force_refresh",
            False,
        )
    )

    company = next(
        (
            record
            for record in company_records
            if get_valid_tax_id(
                record.get("tax_id_norm")
            )
            == tax_id_norm
        ),
        None,
    )

    policy_context = {
        **ctx,
        "page": 1,
        "page_size": 500,
    }

    policy_table = get_policy_company_table(
        tax_id_norm,
        context=policy_context,
    ).get(
        "records",
        [],
    )

    return {
        "tax_id": tax_id,
        "tax_id_norm": tax_id_norm,
        "found": company is not None,
        "company": company,
        "policy": {
            "records": policy_table,
            "total": len(policy_table),
        },
    }

def get_company_income_ranking(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/companies/ranking/income
    """

    ctx = normalize_context(context)
    ctx["sort_by"] = "most_recent_income_val"
    ctx["sort_dir"] = "desc"

    return get_company_list(ctx)


def get_company_capital_ranking(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/companies/ranking/capital
    """

    ctx = normalize_context(context)
    ctx["sort_by"] = "registered_capital"
    ctx["sort_dir"] = "desc"

    return get_company_list(ctx)


def get_company_source_flags() -> Dict[str, Any]:
    """
    API:
    GET /api/companies/source-flags
    """

    records = get_company_unified_records(force_refresh=False)

    return {
        "has_policy": sum(1 for r in records if to_bool(r.get("has_policy"), default=False)),
        "has_linkage": sum(1 for r in records if to_bool(r.get("has_linkage"), default=False)),
        "has_location": sum(1 for r in records if to_bool(r.get("has_location"), default=False)),
        "has_flood_context": sum(1 for r in records if to_bool(r.get("has_flood_context"), default=False)),
        "missing_policy": sum(1 for r in records if not to_bool(r.get("has_policy"), default=False)),
        "missing_linkage": sum(1 for r in records if not to_bool(r.get("has_linkage"), default=False)),
        "missing_location": sum(1 for r in records if not to_bool(r.get("has_location"), default=False)),
        "missing_flood_context": sum(1 for r in records if not to_bool(r.get("has_flood_context"), default=False)),
    }


def get_companies_missing_policy(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/companies/missing-policy
    """

    ctx = normalize_context(context)
    records = [
        record
        for record in get_company_unified_records(force_refresh=ctx.get("force_refresh", False))
        if not to_bool(record.get("has_policy"), default=False)
    ]

    return filter_records_for_api(records, ctx, COMPANY_SEARCHABLE_FIELDS)


def get_companies_missing_linkage(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/companies/missing-linkage
    """

    ctx = normalize_context(context)
    records = [
        record
        for record in get_company_unified_records(force_refresh=ctx.get("force_refresh", False))
        if not to_bool(record.get("has_linkage"), default=False)
    ]

    return filter_records_for_api(records, ctx, COMPANY_SEARCHABLE_FIELDS)


def get_companies_missing_location(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/companies/missing-location
    """

    ctx = normalize_context(context)
    records = [
        record
        for record in get_company_unified_records(force_refresh=ctx.get("force_refresh", False))
        if not to_bool(record.get("has_location"), default=False)
    ]

    return filter_records_for_api(records, ctx, COMPANY_SEARCHABLE_FIELDS)


# ============================================================
# 10) POLICY API FUNCTIONS
# ============================================================

def get_policy_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/summary
    """

    ctx = normalize_context(context)
    policy_records = get_policy_fact_records(force_refresh=ctx.get("force_refresh", False))
    company_summary = build_policy_company_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])
    product_summary = build_policy_product_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])
    subclass_summary = build_policy_subclass_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])
    yearly_summary = build_policy_yearly_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])
    loss_ratio_summary = build_policy_loss_ratio_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    total_premium = sum_field(policy_records, "premium")
    total_loss = sum_field(policy_records, "loss")
    total_suminsure = sum_field(policy_records, "suminsure")
    total_noofpol = sum_field(policy_records, "noofpol")

    loss_ratio = calculate_loss_ratio(total_loss, total_premium, zero_policy="zero")

    return {
        "total_policy_records": len(policy_records),
        "total_companies": len(company_summary),
        "total_products": len(product_summary),
        "total_subclasses": len(subclass_summary),
        "total_premium": total_premium,
        "total_loss": total_loss,
        "total_suminsure": total_suminsure,
        "total_noofpol": total_noofpol,
        "average_loss_ratio": loss_ratio,
        "loss_ratio_band": get_loss_ratio_band(loss_ratio, premium=total_premium, loss=total_loss),
        "active_policy_record_count": sum(1 for r in policy_records if to_bool(r.get("is_active_policy"), default=False)),
        "expired_policy_record_count": sum(1 for r in policy_records if to_bool(r.get("is_expired_policy"), default=False)),
        "premium_zero_with_loss_count": sum(1 for r in policy_records if to_bool(r.get("premium_zero_with_loss"), default=False)),
        "status_conflict_count": sum(1 for r in policy_records if to_bool(r.get("status_conflict_flag"), default=False)),
        "product_summary": product_summary[:20],
        "subclass_summary": subclass_summary[:20],
        "yearly_summary": yearly_summary,
        "loss_ratio_summary": loss_ratio_summary,
        "generated_at": now_iso(),
    }


def get_policy_companies(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/companies
    """

    ctx = normalize_context(context)
    records = build_policy_company_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_for_api(
        records=records,
        context=ctx,
        searchable_fields=["tax_id_norm", "company_name", "company_name_policy", "loss_ratio_band"],
    )

def get_policy_company_detail(
    tax_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/company/<tax_id>
    """

    tax_validation = validate_tax_id(
        tax_id
    )

    tax_id_norm = clean_text(
        tax_validation.get(
            "tax_id_norm"
        )
    )

    if not tax_validation.get(
        "tax_id_valid",
        False,
    ):
        return {
            "tax_id": tax_id,
            "tax_id_norm": tax_id_norm,
            "summary": {},
            "records": [],
            "table": {
                "records": [],
                "total": 0,
                "page": 1,
                "page_size": 0,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
                "tax_id": tax_id,
                "tax_id_norm": tax_id_norm,
            },
            "trend": {
                "tax_id": tax_id,
                "tax_id_norm": tax_id_norm,
                "series": [],
                "total_points": 0,
            },
        }

    summary = get_policy_company_summary(
        tax_id_norm
    )

    table = get_policy_company_table(
        tax_id_norm,
        context=context,
    )

    trend = get_policy_company_trend(
        tax_id_norm
    )

    return {
        "tax_id": tax_id,
        "tax_id_norm": tax_id_norm,
        "summary": summary.get(
            "summary",
            {},
        ),
        "records": table.get(
            "records",
            [],
        ),
        "table": table,
        "trend": trend,
    }


def get_policy_company_summary(
    tax_id: str,
) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/company/<tax_id>/summary
    """

    tax_validation = validate_tax_id(
        tax_id
    )

    tax_id_norm = clean_text(
        tax_validation.get(
            "tax_id_norm"
        )
    )

    if not tax_validation.get(
        "tax_id_valid",
        False,
    ):
        return {
            "tax_id": tax_id,
            "tax_id_norm": tax_id_norm,
            "found": False,
            "summary": {},
        }

    records = build_policy_company_summary(
        force_refresh=False
    ).get(
        "records",
        [],
    )

    summary = next(
        (
            record
            for record in records
            if get_valid_tax_id(
                record.get("tax_id_norm")
            )
            == tax_id_norm
        ),
        None,
    )

    return {
        "tax_id": tax_id,
        "tax_id_norm": tax_id_norm,
        "found": summary is not None,
        "summary": summary or {},
    }


def get_policy_company_table(
    tax_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/company/<tax_id>/table
    """

    tax_validation = validate_tax_id(
        tax_id
    )

    tax_id_norm = clean_text(
        tax_validation.get(
            "tax_id_norm"
        )
    )

    ctx = normalize_context(context)

    if not tax_validation.get(
        "tax_id_valid",
        False,
    ):
        result = apply_search_sort_pagination(
            records=[],
            context=ctx,
            searchable_fields=None,
        )

        result["tax_id"] = tax_id
        result["tax_id_norm"] = tax_id_norm

        return result

    records = [
        record
        for record in get_policy_fact_records(
            force_refresh=ctx.get(
                "force_refresh",
                False,
            )
        )
        if (
            bool(
                to_bool(
                    record.get(
                        "tax_id_valid"
                    ),
                    default=False,
                )
            )
            and get_valid_tax_id(
                record.get("tax_id_norm")
            )
            == tax_id_norm
        )
    ]

    result = filter_records_for_api(
        records=records,
        context=ctx,
        searchable_fields=POLICY_SEARCHABLE_FIELDS,
    )

    result["tax_id"] = tax_id
    result["tax_id_norm"] = tax_id_norm

    return result


def get_policy_company_trend(
    tax_id: str,
) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/company/<tax_id>/trend
    """

    tax_validation = validate_tax_id(
        tax_id
    )

    tax_id_norm = clean_text(
        tax_validation.get(
            "tax_id_norm"
        )
    )

    if not tax_validation.get(
        "tax_id_valid",
        False,
    ):
        return {
            "tax_id": tax_id,
            "tax_id_norm": tax_id_norm,
            "series": [],
            "total_points": 0,
        }

    records = [
        record
        for record in get_policy_fact_records(
            force_refresh=False
        )
        if (
            bool(
                to_bool(
                    record.get(
                        "tax_id_valid"
                    ),
                    default=False,
                )
            )
            and get_valid_tax_id(
                record.get("tax_id_norm")
            )
            == tax_id_norm
        )
    ]

    records_with_year = [
        record
        for record in records
        if record.get("policy_year")
        is not None
    ]

    groups = group_records_by(
        records_with_year,
        "policy_year",
    )

    series: List[Dict[str, Any]] = []

    for year, group in groups.items():
        total_premium = sum_field(
            group,
            "premium",
        )
        total_loss = sum_field(
            group,
            "loss",
        )
        total_suminsure = sum_field(
            group,
            "suminsure",
        )

        loss_ratio = calculate_loss_ratio(
            total_loss,
            total_premium,
            zero_policy="zero",
        )

        series.append(
            {
                "policy_year": to_int(
                    year,
                    default=None,
                ),
                "total_premium": total_premium,
                "total_loss": total_loss,
                "total_suminsure": total_suminsure,
                "loss_ratio": loss_ratio,
                "loss_ratio_band": get_loss_ratio_band(
                    loss_ratio,
                    premium=total_premium,
                    loss=total_loss,
                ),
                "record_count": len(group),
            }
        )

    series = sorted(
        series,
        key=lambda item: (
            item.get("policy_year")
            or 0
        ),
    )

    return {
        "tax_id": tax_id,
        "tax_id_norm": tax_id_norm,
        "series": series,
        "total_points": len(series),
    }

def get_policy_product_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/product-summary
    """

    ctx = normalize_context(context)
    records = build_policy_product_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_for_api(
        records=records,
        context=ctx,
        searchable_fields=["product", "loss_ratio_band"],
    )


def get_policy_subclass_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/subclass-summary
    """

    ctx = normalize_context(context)
    records = build_policy_subclass_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_for_api(
        records=records,
        context=ctx,
        searchable_fields=["subclass", "loss_ratio_band"],
    )


def get_policy_yearly_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/yearly-summary
    """

    ctx = normalize_context(context)
    records = build_policy_yearly_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_for_api(
        records=records,
        context=ctx,
        searchable_fields=["policy_year", "loss_ratio_band"],
    )


def get_policy_loss_ratio_ranking(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/loss-ratio-ranking
    """

    ctx = normalize_context(context)
    ctx["sort_by"] = "loss_ratio"
    ctx["sort_dir"] = "desc"

    records = build_policy_company_summary(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    return filter_records_for_api(
        records=records,
        context=ctx,
        searchable_fields=["tax_id_norm", "company_name", "loss_ratio_band"],
    )


def get_policy_high_loss_companies(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/high-loss
    """

    ctx = normalize_context(context)

    records = [
        record
        for record in build_policy_company_summary(
            force_refresh=ctx.get(
                "force_refresh",
                False,
            )
        ).get(
            "records",
            [],
        )
        if (
            (
                to_number(
                    record.get("loss_ratio"),
                    0,
                )
                or 0
            )
            >= 80
            or clean_text(
                record.get(
                    "loss_ratio_band"
                )
            )
            in {
                "Warning",
                "Critical",
            }
        )
    ]

    if not ctx.get("sort_by"):
        ctx["sort_by"] = "loss_ratio"

    if (
        not isinstance(context, dict)
        or not clean_text(
            context.get("sort_dir")
        )
    ):
        ctx["sort_dir"] = "desc"

    return filter_records_for_api(
        records=records,
        context=ctx,
        searchable_fields=[
            "tax_id_norm",
            "company_name",
            "loss_ratio_band",
        ],
    )

def get_policy_exposure(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/policy/exposure

    ใช้ company_unified_master
    เพื่อดู exposure พร้อม flood context
    """

    ctx = normalize_context(context)

    records = [
        record
        for record in get_company_unified_records(
            force_refresh=ctx.get(
                "force_refresh",
                False,
            )
        )
        if bool(
            to_bool(
                record.get("has_policy"),
                default=False,
            )
        )
    ]

    filtered_records = filter_records_without_pagination(
        records=records,
        context=ctx,
        searchable_fields=COMPANY_SEARCHABLE_FIELDS,
    )

    paginated = apply_search_sort_pagination(
        records=filtered_records,
        context=ctx,
        searchable_fields=None,
    )

    exposure_summary = {
        "total_companies": len(
            filtered_records
        ),
        "total_premium": sum_field(
            filtered_records,
            "total_premium",
        ),
        "total_loss": sum_field(
            filtered_records,
            "total_loss",
        ),
        "total_suminsure": sum_field(
            filtered_records,
            "total_suminsure",
        ),
        "risk_counts": dict(
            Counter(
                clean_text(
                    record.get(
                        "flood_risk_level"
                    ),
                    default="Unknown",
                )
                for record in filtered_records
            )
        ),
        "loss_ratio_band_counts": dict(
            Counter(
                clean_text(
                    record.get(
                        "loss_ratio_band"
                    ),
                    default="Undefined",
                )
                for record in filtered_records
            )
        ),
    }

    return {
        **paginated,
        "summary": exposure_summary,
    }

# ============================================================
# 11) DASHBOARD SUPPORT FUNCTIONS
# ============================================================

def get_company_policy_dashboard_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง payload สำหรับ dashboard_package_service.py

    รวม company + policy summary
    """

    ctx = normalize_context(context)

    company_summary = get_company_summary(ctx)
    policy_summary = get_policy_summary(ctx)

    top_income = get_company_income_ranking(
        {
            **ctx,
            "page": 1,
            "page_size": 10,
        }
    ).get("records", [])

    top_capital = get_company_capital_ranking(
        {
            **ctx,
            "page": 1,
            "page_size": 10,
        }
    ).get("records", [])

    high_loss = get_policy_high_loss_companies(
        {
            **ctx,
            "page": 1,
            "page_size": 10,
        }
    ).get("records", [])

    exposure = get_policy_exposure(
        {
            **ctx,
            "page": 1,
            "page_size": 10,
        }
    )

    return {
        "company_summary": company_summary,
        "policy_summary": policy_summary,
        "top_income_companies": top_income,
        "top_capital_companies": top_capital,
        "high_loss_companies": high_loss,
        "policy_exposure": exposure.get("summary", {}),
        "generated_at": now_iso(),
    }

def rebuild_company_policy_base_cache(force_refresh: bool = False) -> Dict[str, Any]:
    """
    PHASE company_policy_base

    สร้างเฉพาะ base dependencies ที่ linkage/flood/spatial ใช้ต่อได้
    """

    results = {
        "policy_fact": build_policy_fact(force_refresh=force_refresh),
        "company_location_master": build_company_location_master(force_refresh=force_refresh),
        "province_branch_coordinate_master": build_province_branch_coordinate_master(force_refresh=force_refresh),
        "linkage_company_profile": build_linkage_company_profile(force_refresh=force_refresh),
        "policy_company_summary": build_policy_company_summary(force_refresh=force_refresh),
        "policy_product_summary": build_policy_product_summary(force_refresh=force_refresh),
        "policy_subclass_summary": build_policy_subclass_summary(force_refresh=force_refresh),
        "policy_yearly_summary": build_policy_yearly_summary(force_refresh=force_refresh),
        "policy_loss_ratio_summary": build_policy_loss_ratio_summary(force_refresh=force_refresh),
        "company_unified_base": build_company_unified_base(force_refresh=force_refresh),
    }

    return {
        "rebuilt": True,
        "stage": "base",
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


def rebuild_company_policy_enriched_cache(force_refresh: bool = False) -> Dict[str, Any]:
    """
    PHASE company_policy_enriched

    เติม linkage/flood/spatial/data_quality หลัง upstream cache พร้อมแล้ว
    """

    results = {
        "company_unified_master": build_company_unified_master(
            force_refresh=force_refresh,
            enrichment_mode="full",
        ),
    }

    return {
        "rebuilt": True,
        "stage": "enriched",
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

def rebuild_company_policy_cache(force_refresh: bool = True) -> Dict[str, Any]:
    """
    rebuild cache ทั้งหมดของ company/policy แบบ staged

    ลำดับ:
    1. company_unified_base
    2. company_unified_master enriched
    """

    base_result = rebuild_company_policy_base_cache(force_refresh=force_refresh)
    enriched_result = rebuild_company_policy_enriched_cache(force_refresh=force_refresh)

    return {
        "rebuilt": True,
        "staged": True,
        "stages": {
            "company_policy_base": base_result,
            "company_policy_enriched": enriched_result,
        },
        "results": {
            **base_result.get("results", {}),
            **enriched_result.get("results", {}),
        },
        "generated_at": now_iso(),
    }

# ============================================================
# 12) MODULE STATUS / SELF TEST
# ============================================================

def get_company_policy_module_status() -> Dict[str, Any]:
    """
    คืนสถานะ module company_policy_service.py
    """

    return {
        "module": "company_policy_service",
        "ready": True,
        "policy_input_path": str(POLICY_INPUT_PATH),
        "policy_input_exists": POLICY_INPUT_PATH.exists(),
        "linkage_input_path": str(LINKAGE_INPUT_PATH),
        "linkage_input_exists": LINKAGE_INPUT_PATH.exists(),
        "cache_keys": CACHE_KEYS,
        "dependency_contract": {
            "flood_spatial_reads": "company_unified_base",
            "dashboard_map_package_reads": "company_unified_master",
            "company_unified_base_waits_for_spatial": False,
            "company_unified_master_enriches_spatial": True,
        },
        "supported_outputs": [
            "policy_fact",
            "company_location_master",
            "province_branch_coordinate_master",
            "policy_company_summary",
            "policy_product_summary",
            "policy_subclass_summary",
            "policy_yearly_summary",
            "policy_loss_ratio_summary",
            "linkage_company_profile",
            "company_unified_base",
            "company_unified_master",
        ],
        "supported_rebuild_phases": [
            "company_policy_base",
            "company_policy_enriched",
        ],
        "checked_at": now_iso(),
    }


def run_company_policy_self_test() -> Dict[str, Any]:
    """
    self test เบื้องต้น
    """

    status = get_company_policy_module_status()

    policy_fact = build_policy_fact(force_refresh=False)
    company_base = build_company_unified_base(force_refresh=False)
    company_master = build_company_unified_master(force_refresh=False)

    return {
        "module": "company_policy_service",
        "self_test": True,
        "status": status,
        "policy_fact_total": policy_fact.get("total", 0),
        "company_unified_base_total": company_base.get("total", 0),
        "company_unified_master_total": company_master.get("total", 0),
        "checked_at": now_iso(),
    }