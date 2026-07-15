# ============================================================
# FILE: backend/data_quality.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 7 / 20
# ============================================================

"""
backend/data_quality.py

ไฟล์นี้เป็นศูนย์กลาง Data Quality ของระบบ TIPX

หน้าที่หลัก:
1. ตรวจคุณภาพข้อมูล input ทั้ง Policy / Linkage / Flood
2. ตรวจ Tax ID
3. ตรวจข้อมูลกรมธรรม์
4. ตรวจข้อมูลกรรมการและ linkage
5. ตรวจข้อมูลพิกัดบริษัท
6. ตรวจข้อมูล flood source
7. ตรวจผลลัพธ์ spatial join
8. ตรวจ conflict ของ policy status
9. รวม issue ทั้งหมดเป็น data quality summary
10. สร้าง payload สำหรับ Data Quality Dashboard
11. สร้าง data quality flags กลับไปผูกกับ company_unified_master
12. รองรับ API กลุ่ม /api/data-quality/*

ไฟล์นี้รองรับโครงสร้าง Enterprise TIPX แบบ compact:
- Policy Input File
- Linkage Input File
- Flood Output Folder
- Company Unified Master
- Policy Dashboard
- Linkage Graph
- Flood Spatial Join
- OpenLayers Map
- Filter Builder
- Dashboard Package Export
- External Viewer Package

แนวคิด:
Data Quality ไม่ควรทำให้ระบบล่ม
ถ้ามีข้อมูลผิด ระบบควร:
1. เก็บ issue
2. ระบุ severity
3. ระบุ category
4. ระบุ dataset
5. ระบุ field
6. ระบุ record_key
7. เสนอ suggestion
8. ส่ง summary ให้ dashboard แสดงผล
"""

from __future__ import annotations
import hashlib

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import config as runtime_config

from config import (
    POLICY_INPUT_PATH,
    LINKAGE_INPUT_PATH,
    FLOOD_OUTPUT_DIR,
    FLOOD_LATEST_DATABASE_PATH,
    FLOOD_MASTER_DATABASE_PATH,
    FLOOD_HISTORY_DIR,
    POLICY_SHEETS,
    POLICY_SHEET_INDEX_FALLBACK,
    LINKAGE_SHEET_INDEX_FALLBACK,
    FLOOD_LATEST_SHEETS,
    FLOOD_MASTER_SHEETS,
    DATA_QUALITY_RULES,
    DATA_QUALITY_SEVERITIES,
    DATA_QUALITY_CATEGORIES,
    CACHE_TTL_SECONDS,
    POLICY_FACT_COLUMNS,
    POLICY_LOCATION_COLUMNS,
    PROVINCE_BRANCH_COLUMNS,
    LINKAGE_COLUMNS,
)

from utils import (
    add_tax_id_columns,
    apply_search_sort_pagination,
    build_issue,
    clean_dataframe_common,
    clean_text,
    clean_text_lower,
    combine_risk_levels,
    count_distinct,
    dataframe_to_records,
    detect_policy_status_conflict,
    file_info,
    get_cache_file_path,
    get_cache_meta_path,
    get_or_build_cache,
    get_excel_sheet_names,
    group_records_by,
    is_empty_value,
    normalize_columns,
    normalize_province_name,
    normalize_tax_id,
    read_cache,
    read_excel_by_logical_sheet,
    read_excel_sheet,
    read_excel_sheets,
    read_json,
    rename_columns_by_candidates,
    to_bool,
    to_datetime,
    to_jsonable,
    to_number,
    validate_coordinate,
    validate_required_columns_df,
    validate_tax_id,
    write_cache,
    write_json,
)

from schemas import (
    POLICY_INPUT_SCHEMA,
    LINKAGE_INPUT_SCHEMA,
    FLOOD_INPUT_SCHEMA,
    DATA_QUALITY_SUMMARY_SCHEMA,
)

PANDAS_LOADED = True
CONFIG_LOADED = True
UTILS_LOADED = True
SCHEMAS_LOADED = True
CONFIG_COLUMN_MAPPINGS_LOADED = True


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

DATA_QUALITY_CACHE_KEY: str = "data_quality_summary"
DATA_QUALITY_ISSUES_CACHE_KEY: str = "data_quality_issues"

STALE_FLOOD_HOURS: int = 3

QUALITY_SCORE_WEIGHT: Dict[str, int] = {
    "critical": 40,
    "error": 25,
    "warning": 10,
    "info": 2,
}


# ============================================================
# 2) CONTEXT HELPERS
# ============================================================

def normalize_context(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    normalize context จาก api_routes.py

    context ใช้ควบคุม:
    - force_refresh
    - pagination
    - search
    - sort
    - filter
    """

    raw_context = (
        dict(context)
        if isinstance(context, dict)
        else {}
    )

    result = dict(DEFAULT_CONTEXT)
    result.update(raw_context)

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

def issue_matches_context(issue: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """
    ตรวจว่า issue ตรงกับ filter context หรือไม่
    """

    filters = context.get("filters", {}) or {}

    severity_filter = filters.get("severity")
    category_filter = filters.get("category")
    dataset_filter = filters.get("dataset")
    code_filter = filters.get("code")

    if severity_filter:
        if isinstance(severity_filter, list):
            if issue.get("severity") not in severity_filter:
                return False
        elif issue.get("severity") != severity_filter:
            return False

    if category_filter:
        if isinstance(category_filter, list):
            if issue.get("category") not in category_filter:
                return False
        elif issue.get("category") != category_filter:
            return False

    if dataset_filter:
        if isinstance(dataset_filter, list):
            if issue.get("dataset") not in dataset_filter:
                return False
        elif issue.get("dataset") != dataset_filter:
            return False

    if code_filter:
        if isinstance(code_filter, list):
            if issue.get("code") not in code_filter:
                return False
        elif issue.get("code") != code_filter:
            return False

    return True


def apply_issue_context(
    issues: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    apply search / sort / pagination กับ issues
    """

    ctx = normalize_context(context)

    filtered = [
        issue
        for issue in issues
        if issue_matches_context(issue, ctx)
    ]

    return apply_search_sort_pagination(
        records=filtered,
        context=ctx,
        searchable_fields=[
            "issue_id",
            "category",
            "severity",
            "code",
            "message",
            "dataset",
            "field",
            "record_key",
            "suggestion",
        ],
    )


# ============================================================
# 3) ISSUE HELPERS
# ============================================================

def make_issue(
    code: str,
    message: str,
    category: str = "system",
    severity: str = "warning",
    dataset: str = "",
    field: str = "",
    record_key: str = "",
    value: Any = None,
    suggestion: str = "",
    source: str = "",
    row_number: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง data quality issue ตาม format กลาง
    """

    base = build_issue(
        code=code,
        message=message,
        category=category,
        severity=severity,
        dataset=dataset,
        field=field,
        record_key=record_key,
        value=value,
        suggestion=suggestion,
    )

    base["source"] = source
    base["row_number"] = row_number
    base["extra"] = to_jsonable(extra or {})

    return base


def make_issue_from_rule(
    rule_code: str,
    dataset: str = "",
    field: str = "",
    record_key: str = "",
    value: Any = None,
    suggestion: str = "",
    source: str = "",
    row_number: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง issue จาก DATA_QUALITY_RULES ใน config
    """

    rule = DATA_QUALITY_RULES.get(rule_code, {})

    return make_issue(
        code=rule_code,
        message=rule.get("description", rule_code),
        category=rule.get("category", "system"),
        severity=rule.get("severity", "warning"),
        dataset=dataset,
        field=field,
        record_key=record_key,
        value=value,
        suggestion=suggestion,
        source=source,
        row_number=row_number,
        extra=extra,
    )


def deduplicate_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    ลบ issue ซ้ำโดยใช้ issue_id
    """

    seen = set()
    result: List[Dict[str, Any]] = []

    for issue in issues:
        issue_id = issue.get("issue_id")

        if not issue_id:
            key = (
                issue.get("category"),
                issue.get("severity"),
                issue.get("code"),
                issue.get("dataset"),
                issue.get("field"),
                issue.get("record_key"),
                str(issue.get("value")),
            )
        else:
            key = issue_id

        if key in seen:
            continue

        seen.add(key)
        result.append(issue)

    return result


# ============================================================
# 4) SUMMARY HELPERS
# ============================================================

def summarize_issues(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    สรุป issues เป็น summary สำหรับ dashboard
    """

    clean_issues = deduplicate_issues(issues)

    severity_counter = Counter()
    category_counter = Counter()
    dataset_counter = Counter()
    code_counter = Counter()

    for issue in clean_issues:
        severity_counter[issue.get("severity", "info")] += 1
        category_counter[issue.get("category", "system")] += 1
        dataset_counter[issue.get("dataset", "unknown")] += 1
        code_counter[issue.get("code", "unknown")] += 1

    by_severity = {
        severity: severity_counter.get(severity, 0)
        for severity in DATA_QUALITY_SEVERITIES
    }

    by_category = {
        category: category_counter.get(category, 0)
        for category in DATA_QUALITY_CATEGORIES
    }

    quality_score = calculate_quality_score(clean_issues)

    top_issues = [
        {
            "code": code,
            "count": count,
        }
        for code, count in code_counter.most_common(15)
    ]

    top_datasets = [
        {
            "dataset": dataset,
            "count": count,
        }
        for dataset, count in dataset_counter.most_common(15)
    ]

    return {
        "total_issues": len(clean_issues),
        "quality_score": quality_score,
        "quality_level": quality_score_to_level(quality_score),
        "by_severity": by_severity,
        "by_category": by_category,
        "by_dataset": dict(dataset_counter),
        "top_issues": top_issues,
        "top_datasets": top_datasets,
        "issues": clean_issues,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def calculate_quality_score(issues: List[Dict[str, Any]]) -> float:
    """
    คำนวณคะแนนคุณภาพข้อมูล 0-100

    แนวคิด:
    - เริ่มที่ 100
    - หักคะแนนตาม severity
    - critical หักมากที่สุด
    - error รองลงมา
    - warning น้อยกว่า
    - info หักน้อยมาก
    """

    if not issues:
        return 100.0

    penalty = 0

    for issue in issues:
        severity = clean_text_lower(issue.get("severity", "info"))
        penalty += QUALITY_SCORE_WEIGHT.get(severity, 2)

    score = max(0.0, 100.0 - float(penalty))
    return round(score, 2)


def quality_score_to_level(score: Any) -> str:
    """
    แปลง score เป็น level
    """

    value = to_number(score, default=0.0) or 0.0

    if value >= 90:
        return "Excellent"

    if value >= 75:
        return "Good"

    if value >= 60:
        return "Watch"

    if value >= 40:
        return "Warning"

    return "Critical"


# ============================================================
# 5) INPUT FILE QUALITY
# ============================================================



def get_input_file_quality_status() -> Dict[str, Any]:
    """
    คืนสถานะไฟล์ input แบบละเอียด
    """

    return {
        "policy_input": file_info(POLICY_INPUT_PATH),
        "linkage_input": file_info(LINKAGE_INPUT_PATH),
        "flood_output_dir": file_info(FLOOD_OUTPUT_DIR),
        "flood_latest_database": file_info(FLOOD_LATEST_DATABASE_PATH),
        "flood_master_database": file_info(FLOOD_MASTER_DATABASE_PATH),
        "flood_history_dir": file_info(FLOOD_HISTORY_DIR),
    }


# ============================================================
# 6) POLICY INPUT QUALITY
# ============================================================

def load_policy_input_for_quality() -> Dict[str, pd.DataFrame]:
    """
    โหลด Policy Input ทั้ง 3 logical sheet เพื่อใช้ตรวจ data quality
    """

    if not POLICY_INPUT_PATH.exists():
        return {
            "policy_fact": pd.DataFrame(),
            "company_location": pd.DataFrame(),
            "province_branch_coordinate": pd.DataFrame(),
        }

    policy_fact = read_excel_by_logical_sheet(
        POLICY_INPUT_PATH,
        expected_sheet_name=POLICY_SHEETS.get("policy_fact"),
        fallback_index=POLICY_SHEET_INDEX_FALLBACK.get("policy_fact", 0),
        dtype=str,
    )

    company_location = read_excel_by_logical_sheet(
        POLICY_INPUT_PATH,
        expected_sheet_name=POLICY_SHEETS.get("company_location"),
        fallback_index=POLICY_SHEET_INDEX_FALLBACK.get("company_location", 1),
        dtype=str,
    )

    province_branch = read_excel_by_logical_sheet(
        POLICY_INPUT_PATH,
        expected_sheet_name=POLICY_SHEETS.get("province_branch_coordinate"),
        fallback_index=POLICY_SHEET_INDEX_FALLBACK.get("province_branch_coordinate", 2),
        dtype=str,
    )

    policy_fact = rename_columns_by_candidates(
        clean_dataframe_common(policy_fact),
        POLICY_FACT_COLUMNS,
        keep_original=True,
    )

    company_location = rename_columns_by_candidates(
        clean_dataframe_common(company_location),
        POLICY_LOCATION_COLUMNS,
        keep_original=True,
    )

    province_branch = rename_columns_by_candidates(
        clean_dataframe_common(province_branch),
        PROVINCE_BRANCH_COLUMNS,
        keep_original=True,
    )

    return {
        "policy_fact": policy_fact,
        "company_location": company_location,
        "province_branch_coordinate": province_branch,
    }


def check_policy_sheet_structure(policy_sheets: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """
    ตรวจโครงสร้าง sheet ของ Policy Input
    """

    issues: List[Dict[str, Any]] = []

    policy_fact = policy_sheets.get("policy_fact", pd.DataFrame())
    company_location = policy_sheets.get("company_location", pd.DataFrame())
    province_branch = policy_sheets.get("province_branch_coordinate", pd.DataFrame())

    if policy_fact.empty:
        issues.append(
            make_issue(
                code="policy_fact_sheet_empty",
                message="Policy Fact Sheet ว่างหรืออ่านไม่ได้",
                category="input",
                severity="error",
                dataset="policy_fact",
                field="sheet",
                value="policy_fact",
                suggestion="ตรวจสอบ Sheet 1 ของ Policy Input",
                source="policy_input",
            )
        )
    else:
        required = [
            "tax_id",
            "company_name",
            "product",
            "subclass",
            "premium",
            "loss",
            "suminsure",
        ]
        validation = validate_required_columns_df(policy_fact, required)

        for missing in validation["missing_columns"]:
            issues.append(
                make_issue(
                    code="policy_required_column_missing",
                    message=f"Policy Fact ขาด column สำคัญ: {missing}",
                    category="input",
                    severity="error",
                    dataset="policy_fact",
                    field=missing,
                    value=None,
                    suggestion=f"ตรวจสอบ column mapping ของ {missing}",
                    source="policy_input",
                )
            )

    if company_location.empty:
        issues.append(
            make_issue(
                code="company_location_sheet_empty",
                message="Company Location Sheet ว่างหรืออ่านไม่ได้",
                category="input",
                severity="warning",
                dataset="company_location",
                field="sheet",
                value="company_location",
                suggestion="ตรวจสอบ Sheet 2 ของ Policy Input ถ้าไม่มีพิกัด ระบบจะใช้ fallback ได้จำกัด",
                source="policy_input",
            )
        )
    else:
        required = [
            "tax_id",
            "province",
        ]
        validation = validate_required_columns_df(company_location, required)

        for missing in validation["missing_columns"]:
            issues.append(
                make_issue(
                    code="location_required_column_missing",
                    message=f"Company Location ขาด column สำคัญ: {missing}",
                    category="input",
                    severity="warning",
                    dataset="company_location",
                    field=missing,
                    value=None,
                    suggestion=f"ตรวจสอบ column mapping ของ {missing}",
                    source="policy_input",
                )
            )

    if province_branch.empty:
        issues.append(
            make_issue(
                code="province_branch_sheet_empty",
                message="Province / Branch Coordinate Sheet ว่างหรืออ่านไม่ได้",
                category="input",
                severity="warning",
                dataset="province_branch_coordinate",
                field="sheet",
                value="province_branch_coordinate",
                suggestion="ตรวจสอบ Sheet 3 ถ้าต้องใช้ fallback coordinate ระดับจังหวัด/สาขา",
                source="policy_input",
            )
        )
    else:
        required = [
            "province",
            "lat",
            "lon",
        ]
        validation = validate_required_columns_df(province_branch, required)

        for missing in validation["missing_columns"]:
            issues.append(
                make_issue(
                    code="province_branch_required_column_missing",
                    message=f"Province Branch ขาด column สำคัญ: {missing}",
                    category="input",
                    severity="warning",
                    dataset="province_branch_coordinate",
                    field=missing,
                    value=None,
                    suggestion=f"ตรวจสอบ column mapping ของ {missing}",
                    source="policy_input",
                )
            )

    return issues


def check_policy_tax_id_quality(policy_fact: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    ตรวจ Tax ID ใน Policy Fact
    """

    issues: List[Dict[str, Any]] = []

    if policy_fact is None or policy_fact.empty:
        return issues

    if "tax_id" not in policy_fact.columns:
        issues.append(
            make_issue(
                code="tax_id_column_missing",
                message="Policy Fact ไม่มี column tax_id",
                category="tax_id",
                severity="error",
                dataset="policy_fact",
                field="tax_id",
                suggestion="ตรวจสอบ column Tax Id ใน Policy Sheet 1",
                source="policy_input",
            )
        )
        return issues

    seen: Dict[str, int] = {}

    for idx, row in policy_fact.iterrows():
        row_number = int(idx) + 2
        raw_tax_id = row.get("tax_id")
        validation = validate_tax_id(raw_tax_id)
        tax_id_norm = validation["tax_id_norm"]

        if not validation["tax_id_valid"]:
            code = "missing_tax_id" if "missing_tax_id" in validation["issues"] else "invalid_tax_id"
            issues.append(
                make_issue_from_rule(
                    rule_code=code,
                    dataset="policy_fact",
                    field="tax_id",
                    record_key=tax_id_norm,
                    value=raw_tax_id,
                    suggestion="ตรวจสอบเลขประจำตัวผู้เสียภาษีให้เป็นตัวเลข 13 หลัก",
                    source="policy_input",
                    row_number=row_number,
                    extra={
                        "issues": validation["issues"],
                    },
                )
            )

        if tax_id_norm:
            seen[tax_id_norm] = seen.get(tax_id_norm, 0) + 1

    duplicate_tax_ids = {
        tax_id: count
        for tax_id, count in seen.items()
        if count > 1
    }

    for tax_id, count in duplicate_tax_ids.items():
        issues.append(
            make_issue_from_rule(
                rule_code="duplicate_tax_id",
                dataset="policy_fact",
                field="tax_id",
                record_key=tax_id,
                value=tax_id,
                suggestion="Policy Fact อาจมีหลายกรมธรรม์ต่อบริษัทได้ ถ้าเป็นรายการจริงไม่จำเป็นต้องแก้ แต่ควรตรวจ aggregation",
                source="policy_input",
                extra={
                    "duplicate_count": count,
                    "note": "duplicate in policy_fact may be normal because one company can have many policies",
                },
            )
        )

    return issues


def check_policy_numeric_quality(policy_fact: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    ตรวจค่าตัวเลขสำคัญใน Policy Fact
    """

    issues: List[Dict[str, Any]] = []

    if policy_fact is None or policy_fact.empty:
        return issues

    numeric_fields = [
        "premium",
        "loss",
        "suminsure",
        "noofpol",
        "most_recent_asset_val",
        "most_recent_income_val",
        "registered_capital",
    ]

    for idx, row in policy_fact.iterrows():
        row_number = int(idx) + 2
        tax_id_norm = normalize_tax_id(row.get("tax_id"))

        for field_name in numeric_fields:
            if field_name not in policy_fact.columns:
                continue

            value = row.get(field_name)

            if is_empty_value(value):
                continue

            number = to_number(value, default=None)

            if number is None:
                issues.append(
                    make_issue(
                        code="numeric_parse_failed",
                        message=f"ไม่สามารถแปลงค่า {field_name} เป็นตัวเลขได้",
                        category="policy",
                        severity="warning",
                        dataset="policy_fact",
                        field=field_name,
                        record_key=tax_id_norm,
                        value=value,
                        suggestion="ตรวจสอบ format ตัวเลข เช่น comma, เครื่องหมาย currency หรือข้อความปน",
                        source="policy_input",
                        row_number=row_number,
                    )
                )
                continue

            if field_name in {"premium", "loss", "suminsure", "noofpol"} and number < 0:
                issues.append(
                    make_issue(
                        code="policy_negative_value",
                        message=f"{field_name} มีค่าติดลบ",
                        category="policy",
                        severity="warning",
                        dataset="policy_fact",
                        field=field_name,
                        record_key=tax_id_norm,
                        value=value,
                        suggestion="ตรวจสอบว่าค่าติดลบเป็นรายการปรับปรุงจริงหรือข้อมูลผิด",
                        source="policy_input",
                        row_number=row_number,
                    )
                )

        premium = to_number(row.get("premium"), default=0.0) or 0.0
        loss = to_number(row.get("loss"), default=0.0) or 0.0

        if premium == 0 and loss > 0:
            issues.append(
                make_issue_from_rule(
                    rule_code="premium_zero_with_loss",
                    dataset="policy_fact",
                    field="premium/loss",
                    record_key=tax_id_norm,
                    value={
                        "premium": premium,
                        "loss": loss,
                    },
                    suggestion="ตรวจสอบว่ามี premium หายหรือเป็นรายการเคลมที่ไม่มีเบี้ย",
                    source="policy_input",
                    row_number=row_number,
                )
            )

    return issues


def check_policy_status_quality(policy_fact: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    ตรวจ policy status conflict
    """

    issues: List[Dict[str, Any]] = []

    if policy_fact is None or policy_fact.empty:
        return issues

    status_columns = {"inforced_flag", "status_now_new"}

    if not status_columns.intersection(set(policy_fact.columns)):
        issues.append(
            make_issue(
                code="policy_status_columns_missing",
                message="ไม่พบ column สำหรับตรวจสถานะกรมธรรม์",
                category="policy",
                severity="warning",
                dataset="policy_fact",
                field="inforced_flag/status_now_new",
                suggestion="ตรวจสอบ column Inforced Flag และ status now (new)",
                source="policy_input",
            )
        )
        return issues

    for idx, row in policy_fact.iterrows():
        row_number = int(idx) + 2
        tax_id_norm = normalize_tax_id(row.get("tax_id"))

        if detect_policy_status_conflict(row):
            issues.append(
                make_issue_from_rule(
                    rule_code="policy_status_conflict",
                    dataset="policy_fact",
                    field="inforced_flag/status_now_new",
                    record_key=tax_id_norm,
                    value={
                        "inforced_flag": row.get("inforced_flag"),
                        "status_now_new": row.get("status_now_new"),
                    },
                    suggestion="ตรวจสอบว่าทั้งสอง field ใช้ logic เดียวกันหรือไม่",
                    source="policy_input",
                    row_number=row_number,
                )
            )

    return issues


def check_location_quality(company_location: pd.DataFrame, province_branch: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    ตรวจคุณภาพพิกัดจาก Policy Sheet 2 และ Sheet 3
    """

    issues: List[Dict[str, Any]] = []

    if company_location is not None and not company_location.empty:
        for idx, row in company_location.iterrows():
            row_number = int(idx) + 2
            tax_id_norm = normalize_tax_id(row.get("tax_id"))

            lat = row.get("lat")
            lon = row.get("lon")

            if is_empty_value(lat) or is_empty_value(lon):
                issues.append(
                    make_issue_from_rule(
                        rule_code="missing_coordinate",
                        dataset="company_location",
                        field="lat/lon",
                        record_key=tax_id_norm,
                        value={
                            "lat": lat,
                            "lon": lon,
                        },
                        suggestion="เติมพิกัดบริษัท หรือให้ระบบ fallback จากจังหวัด/สาขา",
                        source="policy_input",
                        row_number=row_number,
                    )
                )
                continue

            validation = validate_coordinate(lat, lon)

            if not validation["valid"]:
                issues.append(
                    make_issue_from_rule(
                        rule_code="invalid_coordinate",
                        dataset="company_location",
                        field="lat/lon",
                        record_key=tax_id_norm,
                        value={
                            "lat": lat,
                            "lon": lon,
                        },
                        suggestion="ตรวจสอบว่าค่าพิกัดอยู่ในช่วงประเทศไทยและ lat/lon ไม่สลับกัน",
                        source="policy_input",
                        row_number=row_number,
                        extra={
                            "issues": validation["issues"],
                        },
                    )
                )

            province = normalize_province_name(row.get("province"))

            if not province:
                issues.append(
                    make_issue(
                        code="company_location_missing_province",
                        message="Company Location ไม่มีจังหวัด",
                        category="location",
                        severity="warning",
                        dataset="company_location",
                        field="province",
                        record_key=tax_id_norm,
                        suggestion="เติมจังหวัดเพื่อให้ spatial fallback ทำงานได้",
                        source="policy_input",
                        row_number=row_number,
                    )
                )

    if province_branch is not None and not province_branch.empty:
        for idx, row in province_branch.iterrows():
            row_number = int(idx) + 2
            province = normalize_province_name(row.get("province"))
            lat = row.get("lat")
            lon = row.get("lon")

            if not province:
                issues.append(
                    make_issue(
                        code="province_branch_missing_province",
                        message="Province Branch ไม่มีจังหวัด",
                        category="location",
                        severity="warning",
                        dataset="province_branch_coordinate",
                        field="province",
                        value=row.get("province"),
                        suggestion="เติมชื่อจังหวัดใน Sheet 3",
                        source="policy_input",
                        row_number=row_number,
                    )
                )

            validation = validate_coordinate(lat, lon)

            if not validation["valid"]:
                issues.append(
                    make_issue_from_rule(
                        rule_code="invalid_coordinate",
                        dataset="province_branch_coordinate",
                        field="lat/lon",
                        record_key=province,
                        value={
                            "lat": lat,
                            "lon": lon,
                        },
                        suggestion="ตรวจสอบพิกัดสาขาหรือจังหวัด",
                        source="policy_input",
                        row_number=row_number,
                        extra={
                            "issues": validation["issues"],
                        },
                    )
                )

    return issues


def check_policy_input_quality() -> List[Dict[str, Any]]:
    """
    ตรวจคุณภาพ Policy Input ทั้งหมด
    """

    policy_sheets = load_policy_input_for_quality()

    issues: List[Dict[str, Any]] = []

    issues.extend(check_policy_sheet_structure(policy_sheets))
    issues.extend(check_policy_tax_id_quality(policy_sheets.get("policy_fact", pd.DataFrame())))
    issues.extend(check_policy_numeric_quality(policy_sheets.get("policy_fact", pd.DataFrame())))
    issues.extend(check_policy_status_quality(policy_sheets.get("policy_fact", pd.DataFrame())))
    issues.extend(
        check_location_quality(
            policy_sheets.get("company_location", pd.DataFrame()),
            policy_sheets.get("province_branch_coordinate", pd.DataFrame()),
        )
    )

    return issues


# ============================================================
# 7) LINKAGE QUALITY
# ============================================================

def load_linkage_input_for_quality() -> pd.DataFrame:
    """
    โหลด Linkage Input เพื่อใช้ตรวจ data quality
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


def check_linkage_structure(linkage_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    ตรวจโครงสร้าง Linkage Input
    """

    issues: List[Dict[str, Any]] = []

    if linkage_df is None or linkage_df.empty:
        issues.append(
            make_issue(
                code="linkage_input_empty",
                message="Linkage Input ว่างหรืออ่านไม่ได้",
                category="input",
                severity="error",
                dataset="linkage_input",
                field="sheet",
                suggestion="ตรวจสอบไฟล์ linkage_input.xlsx",
                source="linkage_input",
            )
        )
        return issues

    required = [
        "tax_id",
        "name_th",
        "boardlist",
    ]

    validation = validate_required_columns_df(linkage_df, required)

    for missing in validation["missing_columns"]:
        issues.append(
            make_issue(
                code="linkage_required_column_missing",
                message=f"Linkage Input ขาด column สำคัญ: {missing}",
                category="input",
                severity="error",
                dataset="linkage_input",
                field=missing,
                suggestion=f"ตรวจสอบ column mapping ของ {missing}",
                source="linkage_input",
            )
        )

    return issues


def check_linkage_tax_id_quality(linkage_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    ตรวจ Tax ID ใน Linkage Input
    """

    issues: List[Dict[str, Any]] = []

    if linkage_df is None or linkage_df.empty:
        return issues

    if "tax_id" not in linkage_df.columns:
        issues.append(
            make_issue(
                code="tax_id_column_missing",
                message="Linkage Input ไม่มี column tax_id",
                category="tax_id",
                severity="error",
                dataset="linkage_input",
                field="tax_id",
                suggestion="ตรวจสอบ column tax_id ใน Linkage Input",
                source="linkage_input",
            )
        )
        return issues

    seen: Dict[str, int] = {}

    for idx, row in linkage_df.iterrows():
        row_number = int(idx) + 2
        raw_tax_id = row.get("tax_id")
        validation = validate_tax_id(raw_tax_id)
        tax_id_norm = validation["tax_id_norm"]

        if not validation["tax_id_valid"]:
            code = "missing_tax_id" if "missing_tax_id" in validation["issues"] else "invalid_tax_id"
            issues.append(
                make_issue_from_rule(
                    rule_code=code,
                    dataset="linkage_input",
                    field="tax_id",
                    record_key=tax_id_norm,
                    value=raw_tax_id,
                    suggestion="ตรวจสอบเลขประจำตัวผู้เสียภาษีให้เป็นตัวเลข 13 หลัก",
                    source="linkage_input",
                    row_number=row_number,
                    extra={
                        "issues": validation["issues"],
                    },
                )
            )

        if tax_id_norm:
            seen[tax_id_norm] = seen.get(tax_id_norm, 0) + 1

    for tax_id, count in seen.items():
        if count > 1:
            issues.append(
                make_issue_from_rule(
                    rule_code="duplicate_tax_id",
                    dataset="linkage_input",
                    field="tax_id",
                    record_key=tax_id,
                    value=tax_id,
                    suggestion="Linkage Input ควรมีบริษัท 1 แถวต่อ Tax ID ถ้าไม่ใช่ ให้รวม boardlist ก่อน",
                    source="linkage_input",
                    extra={
                        "duplicate_count": count,
                    },
                )
            )

    return issues


def check_linkage_boardlist_quality(linkage_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    ตรวจ boardlist ใน Linkage Input
    """

    issues: List[Dict[str, Any]] = []

    if linkage_df is None or linkage_df.empty:
        return issues

    if "boardlist" not in linkage_df.columns:
        return issues

    for idx, row in linkage_df.iterrows():
        row_number = int(idx) + 2
        tax_id_norm = normalize_tax_id(row.get("tax_id"))
        company_name = clean_text(row.get("name_th"))
        boardlist = row.get("boardlist")

        if is_empty_value(boardlist):
            issues.append(
                make_issue_from_rule(
                    rule_code="empty_boardlist",
                    dataset="linkage_input",
                    field="boardlist",
                    record_key=tax_id_norm,
                    value=boardlist,
                    suggestion="ถ้าบริษัทไม่มีข้อมูลกรรมการจริง สามารถปล่อยไว้ได้ แต่ graph จะไม่มี director node",
                    source="linkage_input",
                    row_number=row_number,
                    extra={
                        "company_name": company_name,
                    },
                )
            )
            continue

        boardlist_text = clean_text(boardlist)

        if len(boardlist_text) < 3:
            issues.append(
                make_issue(
                    code="boardlist_too_short",
                    message="boardlist สั้นผิดปกติ",
                    category="linkage",
                    severity="warning",
                    dataset="linkage_input",
                    field="boardlist",
                    record_key=tax_id_norm,
                    value=boardlist_text,
                    suggestion="ตรวจสอบชื่อกรรมการ",
                    source="linkage_input",
                    row_number=row_number,
                )
            )

        if len(boardlist_text) > 5000:
            issues.append(
                make_issue(
                    code="boardlist_too_long",
                    message="boardlist ยาวผิดปกติ",
                    category="linkage",
                    severity="warning",
                    dataset="linkage_input",
                    field="boardlist",
                    record_key=tax_id_norm,
                    value=boardlist_text[:200],
                    suggestion="ตรวจสอบว่าข้อมูลหลายบริษัทถูกรวมผิดแถวหรือไม่",
                    source="linkage_input",
                    row_number=row_number,
                )
            )

    return issues


def check_linkage_financial_quality(linkage_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    ตรวจ financial field ใน Linkage Input
    """

    issues: List[Dict[str, Any]] = []

    if linkage_df is None or linkage_df.empty:
        return issues

    numeric_fields = [
        "most_recent_income_val",
        "registered_capital",
    ]

    for idx, row in linkage_df.iterrows():
        row_number = int(idx) + 2
        tax_id_norm = normalize_tax_id(row.get("tax_id"))

        for field_name in numeric_fields:
            if field_name not in linkage_df.columns:
                continue

            value = row.get(field_name)

            if is_empty_value(value):
                continue

            number = to_number(value, default=None)

            if number is None:
                issues.append(
                    make_issue(
                        code="linkage_numeric_parse_failed",
                        message=f"ไม่สามารถแปลงค่า {field_name} เป็นตัวเลขได้",
                        category="linkage",
                        severity="warning",
                        dataset="linkage_input",
                        field=field_name,
                        record_key=tax_id_norm,
                        value=value,
                        suggestion="ตรวจสอบ format ตัวเลขใน Linkage Input",
                        source="linkage_input",
                        row_number=row_number,
                    )
                )

            elif number < 0:
                issues.append(
                    make_issue(
                        code="linkage_negative_financial_value",
                        message=f"{field_name} มีค่าติดลบ",
                        category="linkage",
                        severity="warning",
                        dataset="linkage_input",
                        field=field_name,
                        record_key=tax_id_norm,
                        value=value,
                        suggestion="ตรวจสอบว่าค่าติดลบเป็นข้อมูลจริงหรือไม่",
                        source="linkage_input",
                        row_number=row_number,
                    )
                )

    return issues


def check_linkage_input_quality() -> List[Dict[str, Any]]:
    """
    ตรวจคุณภาพ Linkage Input ทั้งหมด
    """

    linkage_df = load_linkage_input_for_quality()

    issues: List[Dict[str, Any]] = []

    issues.extend(check_linkage_structure(linkage_df))
    issues.extend(check_linkage_tax_id_quality(linkage_df))
    issues.extend(check_linkage_boardlist_quality(linkage_df))
    issues.extend(check_linkage_financial_quality(linkage_df))

    return issues


# ============================================================
# 8) FLOOD QUALITY
# ============================================================

def load_flood_latest_for_quality() -> Dict[str, pd.DataFrame]:
    """
    โหลด flood latest sheets เพื่อใช้ตรวจ data quality
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


def load_flood_master_for_quality() -> Dict[str, pd.DataFrame]:
    """
    โหลด flood master sheets เพื่อใช้ตรวจ data quality
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


def check_flood_sheet_structure(flood_latest: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """
    ตรวจว่ามี sheet flood latest สำคัญหรือไม่
    """

    issues: List[Dict[str, Any]] = []

    if not FLOOD_LATEST_DATABASE_PATH.exists():
        return issues

    sheet_names = get_excel_sheet_names(FLOOD_LATEST_DATABASE_PATH)

    for logical_key, sheet_name in FLOOD_LATEST_SHEETS.items():
        if sheet_name not in sheet_names:
            issues.append(
                make_issue(
                    code="flood_latest_sheet_missing",
                    message=f"ไม่พบ sheet {sheet_name} ใน latest_database.xlsx",
                    category="flood",
                    severity="warning",
                    dataset="flood_latest",
                    field="sheet",
                    value=sheet_name,
                    suggestion="ตรวจสอบ flood pipeline ว่าสร้าง sheet ล่าสุดครบหรือไม่",
                    source="flood_latest_database",
                    extra={
                        "logical_key": logical_key,
                    },
                )
            )

    for logical_key, df in flood_latest.items():
        if df is None or df.empty:
            issues.append(
                make_issue(
                    code="flood_latest_sheet_empty",
                    message=f"Flood latest sheet ว่าง: {logical_key}",
                    category="flood",
                    severity="warning",
                    dataset=logical_key,
                    field="sheet",
                    value=logical_key,
                    suggestion="ตรวจสอบว่า flood pipeline มีข้อมูลล่าสุดหรือไม่",
                    source="flood_latest_database",
                )
            )

    return issues


def detect_possible_datetime_columns(df: pd.DataFrame) -> List[str]:
    """
    หา column ที่น่าจะเป็น datetime
    """

    if df is None or df.empty:
        return []

    candidates: List[str] = []

    for col in df.columns:
        col_lower = clean_text_lower(col)

        if any(keyword in col_lower for keyword in ["date", "time", "datetime", "data_datetime", "created_at", "updated_at"]):
            candidates.append(col)

    return candidates


def check_flood_freshness(flood_latest: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """
    ตรวจความสดของ flood latest

    ถ้าหา datetime column ได้และข้อมูลเก่ากว่า STALE_FLOOD_HOURS จะสร้าง warning
    """

    issues: List[Dict[str, Any]] = []

    now = datetime.now()

    for dataset, df in flood_latest.items():
        if df is None or df.empty:
            continue

        datetime_cols = detect_possible_datetime_columns(df)

        if not datetime_cols:
            issues.append(
                make_issue(
                    code="flood_datetime_column_missing",
                    message=f"ไม่พบ column เวลาใน {dataset}",
                    category="flood",
                    severity="info",
                    dataset=dataset,
                    field="data_datetime",
                    suggestion="ถ้ามี column เวลา ควรตั้งชื่อให้มี date/time/datetime เพื่อใช้ตรวจ freshness",
                    source="flood_latest_database",
                )
            )
            continue

        latest_dt: Optional[datetime] = None
        latest_col = ""

        for col in datetime_cols:
            parsed_values = [
                to_datetime(value)
                for value in df[col].dropna().tolist()
            ]
            parsed_values = [value for value in parsed_values if value is not None]

            if not parsed_values:
                continue

            col_latest = max(parsed_values)

            if latest_dt is None or col_latest > latest_dt:
                latest_dt = col_latest
                latest_col = col

        if latest_dt is None:
            issues.append(
                make_issue(
                    code="flood_datetime_parse_failed",
                    message=f"ไม่สามารถ parse datetime ใน {dataset}",
                    category="flood",
                    severity="info",
                    dataset=dataset,
                    field="data_datetime",
                    suggestion="ตรวจสอบ format datetime ใน flood latest",
                    source="flood_latest_database",
                )
            )
            continue

        age_hours = (now - latest_dt).total_seconds() / 3600

        if age_hours > STALE_FLOOD_HOURS:
            issues.append(
                make_issue_from_rule(
                    rule_code="flood_data_stale",
                    dataset=dataset,
                    field=latest_col,
                    value=latest_dt.isoformat(timespec="seconds"),
                    suggestion=f"ข้อมูลเก่ากว่า {STALE_FLOOD_HOURS} ชั่วโมง ควรตรวจรอบ update flood pipeline",
                    source="flood_latest_database",
                    extra={
                        "age_hours": round(age_hours, 2),
                        "stale_threshold_hours": STALE_FLOOD_HOURS,
                    },
                )
            )

    return issues


def check_flood_coordinate_quality(flood_latest: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """
    ตรวจ coordinate ใน flood latest
    """

    issues: List[Dict[str, Any]] = []

    lat_candidates = ["lat", "latitude", "tele_station_lat", "station_lat"]
    lon_candidates = ["lon", "long", "lng", "longitude", "tele_station_long", "station_long"]

    for dataset, df in flood_latest.items():
        if df is None or df.empty:
            continue

        df_norm = normalize_columns(df)

        lat_col = next((col for col in lat_candidates if col in df_norm.columns), None)
        lon_col = next((col for col in lon_candidates if col in df_norm.columns), None)

        if not lat_col or not lon_col:
            issues.append(
                make_issue(
                    code="flood_coordinate_columns_missing",
                    message=f"ไม่พบ lat/lon columns ใน {dataset}",
                    category="flood",
                    severity="info",
                    dataset=dataset,
                    field="lat/lon",
                    suggestion="ตรวจสอบชื่อ column พิกัดใน flood latest",
                    source="flood_latest_database",
                )
            )
            continue

        for idx, row in df_norm.iterrows():
            row_number = int(idx) + 2
            lat = row.get(lat_col)
            lon = row.get(lon_col)
            validation = validate_coordinate(lat, lon)

            if not validation["valid"]:
                issues.append(
                    make_issue(
                        code="flood_invalid_coordinate",
                        message=f"พิกัด flood ไม่ถูกต้องใน {dataset}",
                        category="flood",
                        severity="warning",
                        dataset=dataset,
                        field="lat/lon",
                        record_key=clean_text(row.get("station_id") or row.get("dam_id") or row.get("source_id")),
                        value={
                            "lat": lat,
                            "lon": lon,
                        },
                        suggestion="ตรวจสอบ lat/lon ของสถานีหรือเขื่อน",
                        source="flood_latest_database",
                        row_number=row_number,
                        extra={
                            "issues": validation["issues"],
                        },
                    )
                )

    return issues


def check_flood_history_quality() -> List[Dict[str, Any]]:
    """
    ตรวจ flood history folder แบบเบื้องต้น
    """

    issues: List[Dict[str, Any]] = []

    if not FLOOD_HISTORY_DIR.exists():
        issues.append(
            make_issue(
                code="flood_history_dir_missing",
                message="ไม่พบ flood history directory",
                category="flood",
                severity="warning",
                dataset="flood_history",
                field="folder_path",
                value=str(FLOOD_HISTORY_DIR),
                suggestion="ถ้าต้องใช้ trend/history ให้ตรวจสอบ history folder จาก flood pipeline",
                source="file_system",
            )
        )
        return issues

    expected_subdirs = [
        "rainfall",
        "rain15d",
        "rain_yearly",
        "waterlevel",
        "dam",
        "all_long",
    ]

    for subdir in expected_subdirs:
        path = FLOOD_HISTORY_DIR / subdir

        if not path.exists():
            issues.append(
                make_issue(
                    code="flood_history_subdir_missing",
                    message=f"ไม่พบ flood history subdir: {subdir}",
                    category="flood",
                    severity="info",
                    dataset="flood_history",
                    field="folder_path",
                    value=str(path),
                    suggestion="ตรวจสอบว่าต้องใช้ history กลุ่มนี้หรือไม่",
                    source="file_system",
                )
            )

    return issues

# ============================================================
# 10) SPATIAL JOIN QUALITY
# ============================================================

def check_spatial_join_quality_internal() -> List[Dict[str, Any]]:
    """
    ตรวจ spatial_join_result จาก cache ถ้ามี
    """

    issues: List[Dict[str, Any]] = []

    records = load_cached_records("spatial_join_result")

    if not records:
        issues.append(
            make_issue(
                code="spatial_join_cache_missing",
                message="ยังไม่พบ spatial_join_result cache",
                category="spatial",
                severity="info",
                dataset="spatial_join_result",
                field="cache",
                suggestion="run flood_spatial_service เพื่อสร้าง spatial_join_result",
                source="cache",
            )
        )
        return issues

    for record in records:
        tax_id_norm = normalize_tax_id(record.get("tax_id_norm") or record.get("tax_id"))
        has_flood_context = to_bool(record.get("has_flood_context"), default=False)

        if not has_flood_context:
            issues.append(
                make_issue_from_rule(
                    rule_code="spatial_join_failed",
                    dataset="spatial_join_result",
                    field="has_flood_context",
                    record_key=tax_id_norm,
                    value=record.get("has_flood_context"),
                    suggestion="ตรวจสอบพิกัดบริษัท จังหวัด หรือ flood station master",
                    source="cache",
                    extra={
                        "join_level": record.get("join_level"),
                        "location_quality": record.get("location_quality"),
                    },
                )
            )

    return issues

# ============================================================
# 16) PHASE 11 STABLE DATA QUALITY API CONTRACT
# ============================================================

SEVERITY_LEVELS: List[str] = ["critical", "high", "medium", "low", "info"]
SEVERITY_ALIASES: Dict[str, str] = {
    "error": "high",
    "warning": "medium",
    "warn": "medium",
    "normal": "info",
}
ISSUE_CATEGORIES: List[str] = [
    "input_file",
    "schema",
    "required_column",
    "missing_value",
    "tax_id",
    "coordinate",
    "duplicate",
    "policy",
    "linkage",
    "flood",
    "spatial",
    "company_unified",
    "status_conflict",
    "cache",
    "runtime",
    "json_safety",
    "package_readiness",
    "map_readiness",
    "frontend_readiness",
    "data_quality",
]
SOURCE_NAMES: List[str] = [
    "policy_input",
    "linkage_input",
    "flood_output",
    "company_unified_master",
    "policy_fact",
    "linkage_graph",
    "director_master",
    "flood_computed_risk",
    "spatial_join_result",
    "policy_flood_exposure",
    "map_layers",
    "dashboard_summary",
    "package_export",
    "system",
    "unknown",
]
QUALITY_PENALTY: Dict[str, int] = {
    "critical": 25,
    "high": 10,
    "medium": 4,
    "low": 1,
    "info": 0,
}

POST_REBUILD_CRITICAL_CACHE_KEYS: List[str] = [
    "company_unified_base",
    "company_unified_master",
    "policy_fact",
    "policy_company_summary",
    "linkage_graph_payload",
    "flood_rainfall_latest",
    "flood_waterlevel_latest",
    "flood_large_dam_latest",
    "flood_medium_dam_latest",
    "flood_dam_latest",
    "flood_prediction_latest",
    "flood_prediction_map",
    "uploaded_entity_latest",
    "spatial_join_result",
    "map_layers",
    "dashboard_summary",
    "dashboard_province_insights",
    "chart_summary",
    "package_preview",
]

POST_REBUILD_DEPENDENCY_ORDER: List[Tuple[str, str]] = [
    ("company_unified_base", "linkage_graph_payload"),
    ("company_unified_base", "spatial_join_result"),
    ("linkage_graph_payload", "company_unified_master"),
    ("spatial_join_result", "company_unified_master"),
    ("flood_rainfall_latest", "map_layers"),
    ("flood_waterlevel_latest", "map_layers"),
    ("flood_large_dam_latest", "map_layers"),
    ("flood_medium_dam_latest", "map_layers"),
    ("flood_prediction_latest", "map_layers"),
    ("flood_prediction_map", "map_layers"),
    ("uploaded_entity_latest", "map_layers"),
    ("company_unified_master", "map_layers"),
    ("map_layers", "dashboard_summary"),
    ("map_layers", "dashboard_province_insights"),
    ("dashboard_summary", "chart_summary"),
    ("dashboard_province_insights", "chart_summary"),
    ("chart_summary", "package_preview"),
]

FLOOD_PREDICTION_REQUIRED_COLUMNS: List[str] = [
    "record_key",
    "station_name",
    "station_id",
    "province",
    "target_date",
    "forecast_horizon_day",
    "risk_level",
    "warning_level_predict",
    "map_ready",
    "focus_level",
]

SOURCE_READINESS_CHECKS: List[str] = [
    "check_data_source_config",
    "check_excel_source_paths",
    "check_mysql_source_placeholder",
    "check_latest_excel_file",
    "check_master_excel_file",
    "check_history_dir",
    "check_prediction_dir",
    "check_upload_dir",
]

FLOOD_PREDICTION_CHECKS: List[str] = [
    "check_latest_rainfall_sheet",
    "check_latest_waterlevel_sheet",
    "check_latest_dam_sheet",
    "check_prediction_file_exists",
    "check_prediction_required_columns",
    "check_prediction_location_match_rate",
    "check_prediction_map_ready_rate",
    "check_prediction_province_fallback_rate",
]

ENTITY_UPLOAD_CHECKS: List[str] = [
    "check_latest_entity_upload_exists",
    "check_entity_displayable_count",
    "check_entity_not_displayable_count",
    "check_entity_invalid_coordinate_count",
    "check_entity_error_report_exists",
]

CACHE_REGISTRY_CHECKS: List[str] = [
    "check_cache_registry",
    "check_missing_critical_cache",
    "check_stale_cache",
    "check_degraded_cache",
    "check_cache_dependency_order",
]

REQUIRED_FIELDS_BY_SOURCE: Dict[str, List[str]] = {
    "company_unified_base": [
        "tax_id_norm",
        "company_name",
    ],
    "company_unified_master": [
        "tax_id_norm",
        "company_name",
        "province",
        "has_policy",
        "has_linkage",
        "has_location",
    ],
    "policy_fact": [
        "tax_id_norm",
        "company_name",
        "premium",
        "loss",
        "suminsure",
    ],
    "policy_company_summary": [
        "tax_id_norm",
        "company_name",
    ],
    "linkage_graph": [
        "record_kind",
    ],
    "linkage_graph_payload": [
        "record_kind",
    ],
    "flood_computed_risk": [
        "source_id",
        "source_type",
        "risk_level",
    ],
    "flood_rainfall_latest": [
        "source_type",
        "source_id",
        "risk_level",
    ],
    "flood_waterlevel_latest": [
        "source_type",
        "source_id",
        "risk_level",
    ],
    "flood_dam_latest": [
        "source_type",
        "source_id",
        "risk_level",
    ],
    "flood_prediction_latest": [
        "record_key",
        "target_date",
        "forecast_horizon_day",
        "risk_level",
        "map_ready",
    ],
    "uploaded_entity_latest": [
        "entity_id",
        "entity_type",
        "entity_name_th",
        "province_name_th",
    ],
    "spatial_join_result": [
        "tax_id_norm",
        "company_name",
        "flood_risk_level",
        "flood_join_level",
    ],
    "map_layers": [
        "layers",
        "layer_order",
        "summary",
        "meta",
    ],
    "dashboard_summary": [
        "summary",
        "cards",
        "meta",
    ],
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def json_safe(value: Any) -> Any:
    return to_jsonable(value)


def safe_len(value: Any) -> int:
    try:
        return len(value or [])
    except Exception:
        return 0

def coerce_records(
    value: Any,
    source_name: str = "",
) -> List[Dict[str, Any]]:
    if value is None:
        return []

    if isinstance(value, list):
        return [
            dict(item)
            for item in value
            if isinstance(item, dict)
        ]

    if isinstance(value, dict):
        return normalize_source_payload_to_records(
            value,
            source_name=source_name or None,
        )

    if isinstance(value, pd.DataFrame):
        return dataframe_to_records(value)

    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict(
                orient="records"
            )

            if isinstance(records, list):
                return [
                    dict(item)
                    for item in records
                    if isinstance(item, dict)
                ]

        except Exception:
            return []

    return []


def safe_record_preview(
    records: Any,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    safe_limit = max(
        0,
        int(limit or 0),
    )

    return json_safe(
        coerce_records(records)[:safe_limit]
    )

def normalize_severity(severity: Any) -> str:
    value = clean_text_lower(severity, default="info")
    value = SEVERITY_ALIASES.get(value, value)
    return value if value in SEVERITY_LEVELS else "info"


def normalize_category(category: Any, issue_type: Any = "") -> str:
    value = clean_text_lower(category, default="")
    issue_text = clean_text_lower(issue_type)
    if value in ISSUE_CATEGORIES:
        return value
    if value in {"input", "file"}:
        return "input_file"
    if value in {"location"} or "coordinate" in issue_text or "lat" in issue_text or "lon" in issue_text:
        return "coordinate"
    if value in {"system"}:
        return "cache"
    if value in {"spatial_join"}:
        return "spatial"
    if "status_conflict" in issue_text:
        return "status_conflict"
    return "data_quality"


def normalize_source(source: Any, dataset: Any = "") -> str:
    value = clean_text_lower(source or dataset, default="unknown")
    if value == "cache":
        value = clean_text_lower(dataset, default="unknown")
    return value if value in SOURCE_NAMES else clean_text_lower(dataset, default=value or "unknown") or "unknown"

def issue_key(
    issue: Dict[str, Any],
) -> str:
    meta = (
        issue.get("meta", {})
        if isinstance(
            issue.get("meta"),
            dict,
        )
        else {}
    )

    parts = [
        issue.get("source"),
        issue.get("source_file"),
        issue.get("source_sheet"),
        issue.get("category"),
        issue.get("issue_type"),
        issue.get("record_key"),
        issue.get("tax_id_norm"),
        issue.get("field"),
        issue.get("row_number"),
        meta.get("checker"),
        issue.get("message"),
    ]

    return "|".join(
        clean_text(part)
        for part in parts
    )

def make_quality_issue(
    issue_type: str,
    message: str,
    severity: str = "medium",
    category: str = "data_quality",
    source: str = "unknown",
    source_file: str = "",
    source_sheet: str = "",
    record_key: str = "",
    row_number: Optional[int] = None,
    tax_id_norm: str = "",
    company_name: str = "",
    field: str = "",
    expected: Any = None,
    actual: Any = None,
    suggestion: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_severity = (
        normalize_severity(severity)
    )

    normalized_tax_id = normalize_tax_id(
        tax_id_norm
    )

    issue = {
        "severity": normalized_severity,
        "category": normalize_category(
            category,
            issue_type,
        ),
        "source": normalize_source(
            source
        ),
        "source_file": clean_text(
            source_file
        ),
        "source_sheet": clean_text(
            source_sheet
        ),
        "record_key": clean_text(
            record_key
        ),
        "row_number": row_number,
        "tax_id_norm": normalized_tax_id,
        "company_name": clean_text(
            company_name
        ),
        "field": clean_text(field),
        "issue_type": clean_text(
            issue_type,
            default="data_quality_issue",
        ),
        "message": clean_text(
            message,
            default=issue_type,
        ),
        "expected": expected,
        "actual": actual,
        "suggestion": clean_text(
            suggestion
        ),
        "is_blocker": (
            normalized_severity
            == "critical"
        ),
        "created_at": now_iso(),
        "meta": dict(meta or {}),
    }

    key = issue_key(issue)

    issue["issue_key"] = key
    issue["issue_id"] = (
        "DQ_"
        + hashlib.sha1(
            key.encode("utf-8")
        ).hexdigest()[:16].upper()
    )
    issue["code"] = issue[
        "issue_type"
    ]
    issue["dataset"] = issue[
        "source"
    ]
    issue["value"] = actual

    return json_safe(issue)

def normalize_issue(issue: Any) -> Dict[str, Any]:
    if not isinstance(issue, dict):
        return make_quality_issue(
            issue_type="malformed_issue",
            message="Malformed quality issue was normalized.",
            severity="low",
            category="json_safety",
            source="unknown",
            actual=issue,
        )
    return make_quality_issue(
        issue_type=issue.get("issue_type") or issue.get("code") or "data_quality_issue",
        message=issue.get("message") or issue.get("description") or issue.get("code") or "Data quality issue.",
        severity=issue.get("severity", "info"),
        category=issue.get("category", "data_quality"),
        source=issue.get("source") or issue.get("dataset") or "unknown",
        source_file=issue.get("source_file", ""),
        source_sheet=issue.get("source_sheet", ""),
        record_key=issue.get("record_key", ""),
        row_number=issue.get("row_number"),
        tax_id_norm=issue.get("tax_id_norm") or issue.get("record_key") or "",
        company_name=issue.get("company_name", ""),
        field=issue.get("field", ""),
        expected=issue.get("expected"),
        actual=issue.get("actual", issue.get("value")),
        suggestion=issue.get("suggestion", ""),
        meta=issue.get("meta") or issue.get("extra") or {},
    )


def dedupe_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for raw_issue in issues or []:
        issue = normalize_issue(raw_issue)
        key = issue.get("issue_key") or issue_key(issue)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


def group_issues(issues: List[Dict[str, Any]], field: str) -> Dict[str, int]:
    counter = Counter(clean_text(issue.get(field), default="unknown") for issue in issues or [])
    return dict(counter)


def score_quality(issues: List[Dict[str, Any]], source_record_count: int = 0) -> Dict[str, Any]:
    normalized = dedupe_issues(issues or [])
    severity_counts = {severity: 0 for severity in SEVERITY_LEVELS}
    for issue in normalized:
        severity_counts[normalize_severity(issue.get("severity"))] += 1
    if not normalized and not source_record_count:
        return {
            "score": 0.0,
            "grade": "unknown",
            "severity_counts": severity_counts,
            "issue_count": 0,
            "record_count": 0,
        }
    penalty = sum(QUALITY_PENALTY[severity] * count for severity, count in severity_counts.items())
    score = max(0.0, min(100.0, 100.0 - float(penalty)))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"
    return {
        "score": round(score, 2),
        "grade": grade,
        "severity_counts": severity_counts,
        "issue_count": len(normalized),
        "record_count": int(source_record_count or 0),
    }

def summarize_issues_v2(
    issues: List[Dict[str, Any]],
    source_record_count: int = 0,
) -> Dict[str, Any]:
    normalized = dedupe_issues(
        issues or []
    )

    score = score_quality(
        normalized,
        source_record_count,
    )

    by_source = group_issues(
        normalized,
        "source",
    )
    by_category = group_issues(
        normalized,
        "category",
    )
    by_severity = {
        severity: score[
            "severity_counts"
        ].get(
            severity,
            0,
        )
        for severity
        in SEVERITY_LEVELS
    }

    degraded = any(
        issue.get("severity")
        in {
            "critical",
            "high",
        }
        or issue.get("issue_type")
        in {
            "missing_source",
            "checker_failed",
            "import_fallback_active",
        }
        for issue in normalized
    )

    return {
        "overall_score": score["score"],
        "overall_grade": score["grade"],
        "issue_count": len(normalized),
        "critical_count": (
            by_severity.get(
                "critical",
                0,
            )
        ),
        "high_count": (
            by_severity.get(
                "high",
                0,
            )
        ),
        "medium_count": (
            by_severity.get(
                "medium",
                0,
            )
        ),
        "low_count": (
            by_severity.get(
                "low",
                0,
            )
        ),
        "info_count": (
            by_severity.get(
                "info",
                0,
            )
        ),
        "source_count": len(
            by_source
        ),
        "degraded": degraded,
        "by_source": by_source,
        "by_category": by_category,
        "by_severity": by_severity,
    }

def make_quality_response(
    data: Optional[Dict[str, Any]] = None,
    message: str = "Data quality operation completed.",
    meta: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    success: bool = True,
) -> Dict[str, Any]:
    response_meta = {
        "module": "data_quality",
        "generated_at": now_iso(),
        "source_count": 0,
        "issue_count": 0,
        "degraded": False,
    }
    response_meta.update(meta or {})
    return json_safe(
        {
            "success": bool(success),
            "message": message,
            "data": data or {},
            "meta": response_meta,
            "errors": errors or [],
        }
    )

def make_quality_error(
    message: str = "Data quality operation failed.",
    error_type: str = "RuntimeError",
    status_code: int = 500,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    safe_status_code = max(
        400,
        min(
            int(status_code or 500),
            599,
        ),
    )

    public_message = clean_text(
        message,
        "Data quality operation failed.",
    )

    if (
        safe_status_code >= 500
        and not bool(
            getattr(
                runtime_config,
                "DEBUG",
                False,
            )
        )
    ):
        public_message = (
            "Data quality operation failed."
        )

    return make_quality_response(
        data=data or {},
        message=public_message,
        meta={
            "status_code": safe_status_code,
            "degraded": True,
        },
        errors=[
            {
                "type": clean_text(
                    error_type,
                    "RuntimeError",
                ),
                "message": public_message,
            }
        ],
        success=False,
    )


def safe_exception_message(
    exc: Exception,
    default: str,
) -> str:
    if bool(
        getattr(
            runtime_config,
            "DEBUG",
            False,
        )
    ):
        return clean_text(
            str(exc),
            default,
        )

    return default

def make_degraded_quality_response(reason: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return make_quality_response(
        data=data or {"issues": [], "summary": {}},
        message="Data quality operation completed with missing source data.",
        meta={"degraded": True, "reason": reason},
        errors=[],
        success=True,
    )

def normalize_source_payload_to_records(payload: Any, source_name: Optional[str] = None) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    def append_items(items: Any, record_kind: str = "") -> None:
        if not isinstance(items, list):
            return

        for item in items:
            if not isinstance(item, dict):
                continue

            record = dict(item)

            if record_kind and "record_kind" not in record:
                record["record_kind"] = record_kind

            if source_name and "source" not in record:
                record["source"] = source_name

            records.append(record)

    if isinstance(payload, list):
        append_items(payload)
        return records

    if not isinstance(payload, dict):
        return []

    if "success" in payload and isinstance(payload.get("data"), (dict, list)):
        extracted = normalize_source_payload_to_records(payload.get("data"), source_name=source_name)
        if extracted:
            return extracted

    for key in [
        "records",
        "items",
        "companies",
        "issues",
        "packages",
        "displayable_records",
        "not_displayable_records",
        "prediction",
        "entity",
        "uploaded_entity_latest",
        "flood_prediction_latest",
    ]:
        if isinstance(payload.get(key), list):
            append_items(payload[key], key[:-1] if key.endswith("s") else key)
            return records

    data = payload.get("data")

    if isinstance(data, list):
        append_items(data)
        return records

    if isinstance(data, dict):
        for key in [
            "records",
            "items",
            "issues",
            "companies",
            "prediction",
            "entity",
            "uploaded_entity_latest",
            "flood_prediction_latest",
        ]:
            if isinstance(data.get(key), list):
                append_items(data[key], key[:-1] if key.endswith("s") else key)
                return records

        extracted = normalize_source_payload_to_records(data, source_name=source_name)

        if extracted:
            return extracted

    if isinstance(payload.get("nodes"), list) or isinstance(payload.get("edges"), list):
        append_items(payload.get("nodes", []), "node")
        append_items(payload.get("edges", []), "edge")
        return records

    layers = payload.get("layers")

    if isinstance(layers, dict):
        layer_iterable = layers.values()
    elif isinstance(layers, list):
        layer_iterable = layers
    else:
        layer_iterable = []

    for layer in layer_iterable:
        if not isinstance(layer, dict):
            continue

        layer_id = clean_text(layer.get("layer_id"))
        layer_records = layer.get("records")

        if isinstance(layer_records, list):
            for item in layer_records:
                if isinstance(item, dict):
                    records.append(
                        {
                            "record_kind": "map_record",
                            "source": source_name or "map_layers",
                            "layer_id": layer_id,
                            **item,
                        }
                    )

        feature_collection = layer.get("features") or layer.get("feature_collection")

        if isinstance(feature_collection, dict) and isinstance(feature_collection.get("features"), list):
            for feature in feature_collection["features"]:
                if not isinstance(feature, dict):
                    continue

                properties = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}

                records.append(
                    {
                        "record_kind": "map_feature",
                        "source": source_name or "map_layers",
                        "layer_id": layer_id,
                        "feature_type": properties.get("feature_type"),
                        **properties,
                    }
                )

    if records:
        return records

    features = payload.get("features")

    if isinstance(features, list):
        for feature in features:
            if not isinstance(feature, dict):
                continue

            properties = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else feature

            records.append(
                {
                    "record_kind": "feature",
                    "source": source_name or "feature_collection",
                    **properties,
                }
            )

        return records

    if isinstance(features, dict) and isinstance(features.get("features"), list):
        for feature in features["features"]:
            if not isinstance(feature, dict):
                continue

            properties = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}

            records.append(
                {
                    "record_kind": "map_feature",
                    "source": source_name or "map_layers",
                    **properties,
                }
            )

        return records

    for key in ["summary", "cards", "charts", "tables", "cache_status", "readiness"]:
        value = payload.get(key)

        if isinstance(value, list):
            append_items(value, key[:-1] if key.endswith("s") else key)

        elif isinstance(value, dict):
            for item_key, item_value in value.items():
                if isinstance(item_value, dict):
                    records.append(
                        {
                            "record_kind": key,
                            "source": source_name or key,
                            "key": item_key,
                            **item_value,
                        }
                    )
                else:
                    records.append(
                        {
                            "record_kind": key,
                            "source": source_name or key,
                            "key": item_key,
                            "value": item_value,
                        }
                    )

    return records

def get_runtime_config_value(name: str, default: Any = None) -> Any:
    if runtime_config is None:
        return globals().get(name, default)
    return getattr(runtime_config, name, globals().get(name, default))


def get_runtime_path(name: str, default: Any = None) -> Optional[Path]:
    value = get_runtime_config_value(name, default)
    if value is None:
        return None

    try:
        return Path(value)
    except Exception:
        return None


def path_exists(path: Any) -> bool:
    try:
        return Path(path).exists()
    except Exception:
        return False


def normalize_cache_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload

    if isinstance(payload, list):
        return {
            "records": payload,
            "total": len(payload),
        }

    return {}


def cache_record_count(cache_key: str) -> int:
    payload = read_cache(cache_key, default={})
    records = normalize_source_payload_to_records(payload, source_name=cache_key)

    if records:
        return len(records)

    if isinstance(payload, dict):
        for key in ["total", "record_count", "node_count", "edge_count", "feature_count"]:
            value = to_number(payload.get(key), None)
            if value is not None:
                return int(value)

        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        for key in ["total", "record_count", "node_count", "edge_count", "feature_count"]:
            value = to_number(meta.get(key), None)
            if value is not None:
                return int(value)

    return 0

def get_cache_meta(
    cache_key: str,
) -> Dict[str, Any]:
    meta_path = get_cache_meta_path(
        cache_key
    )

    if not meta_path.exists():
        return {}

    meta = read_json(
        meta_path,
        default={},
    )

    return (
        meta
        if isinstance(meta, dict)
        else {}
    )

def get_cache_created_at(cache_key: str) -> Optional[datetime]:
    meta = get_cache_meta(cache_key)
    created_at = to_datetime(meta.get("created_at"))

    if created_at is not None:
        return created_at

    try:
        cache_path = get_cache_file_path(cache_key)
        if cache_path.exists():
            return datetime.fromtimestamp(cache_path.stat().st_mtime)
    except Exception:
        return None

    return None


def make_missing_path_issue(
    issue_type: str,
    message: str,
    path_name: str,
    path_value: Any,
    severity: str = "high",
    source: str = "system",
) -> Dict[str, Any]:
    return make_quality_issue(
        issue_type=issue_type,
        message=message,
        severity=severity,
        category="input_file",
        source=source,
        field=path_name,
        actual=str(path_value),
        suggestion=f"ตรวจสอบ config path: {path_name}",
        meta={
            "path_name": path_name,
            "path": str(path_value),
        },
    )


def make_cache_issue(
    issue_type: str,
    message: str,
    cache_key: str,
    severity: str = "medium",
    category: str = "cache",
    actual: Any = None,
    suggestion: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return make_quality_issue(
        issue_type=issue_type,
        message=message,
        severity=severity,
        category=category,
        source=cache_key,
        field="cache",
        record_key=cache_key,
        actual=actual,
        suggestion=suggestion,
        meta={
            "cache_key": cache_key,
            **(meta or {}),
        },
    )

def get_source_records_from_service(
    module_name: str,
    function_name: str,
    cache_key: str,
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    try:
        module = __import__(module_name)
        function_ref = getattr(module, function_name)

        call_attempts = [
            lambda: function_ref(context=context or {}),
            lambda: function_ref(context or {}),
            lambda: function_ref(),
        ]

        for call in call_attempts:
            try:
                payload = call()
                records = normalize_source_payload_to_records(payload, source_name=cache_key)

                if records:
                    return records
            except TypeError:
                continue

    except Exception:
        pass

    return load_cache_records(cache_key)


def get_source_payload_from_service(
    module_name: str,
    function_name: str,
    default: Any = None,
    context: Optional[Dict[str, Any]] = None,
) -> Any:
    fallback = default if default is not None else {}

    try:
        module = __import__(module_name)
        function_ref = getattr(module, function_name)

        call_attempts = [
            lambda: function_ref(context=context or {}),
            lambda: function_ref(context or {}),
            lambda: function_ref(),
        ]

        for call in call_attempts:
            try:
                return call()
            except TypeError:
                continue

    except Exception:
        return fallback

    return fallback

def load_cache_records(cache_key: str, source_name: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        payload = read_json(get_cache_file_path(cache_key), default={})
    except Exception:
        return []
    return json_safe(normalize_source_payload_to_records(payload, source_name=source_name or cache_key))

def load_policy_records() -> List[Dict[str, Any]]:
    records = load_cache_records(
        "policy_fact",
        "policy_fact",
    )

    if records:
        return records

    try:
        import company_policy_service

        payload = (
            company_policy_service
            .get_policy_fact_records(
                force_refresh=False
            )
        )

        return coerce_records(
            payload,
            source_name="policy_fact",
        )

    except Exception:
        return []


def load_linkage_records() -> List[Dict[str, Any]]:
    records = load_cache_records(
        "linkage_graph_payload",
        "linkage_graph_payload",
    )

    if records:
        return records

    combined: List[
        Dict[str, Any]
    ] = []

    for cache_key, record_kind in [
        ("linkage_nodes", "node"),
        ("linkage_edges", "edge"),
    ]:
        for record in load_cache_records(
            cache_key,
            cache_key,
        ):
            item = dict(record)
            item.setdefault(
                "record_kind",
                record_kind,
            )
            combined.append(item)

    if combined:
        return combined

    try:
        import linkage_service

        payload = (
            linkage_service
            .build_linkage_graph_payload(
                force_refresh=False
            )
        )

        return (
            normalize_source_payload_to_records(
                payload,
                source_name=(
                    "linkage_graph_payload"
                ),
            )
        )

    except Exception:
        return []


def load_flood_records() -> List[Dict[str, Any]]:
    combined: List[
        Dict[str, Any]
    ] = []

    for cache_key in [
        "flood_computed_risk",
        "flood_rainfall_latest",
        "flood_waterlevel_latest",
        "flood_large_dam_latest",
        "flood_medium_dam_latest",
        "flood_prediction_latest",
    ]:
        records = load_cache_records(
            cache_key,
            cache_key,
        )

        if records:
            combined.extend(records)

    return combined


def load_company_unified_records() -> List[Dict[str, Any]]:
    records = load_cache_records(
        "company_unified_master",
        "company_unified_master",
    )

    if records:
        return records

    return load_cache_records(
        "company_unified_base",
        "company_unified_base",
    )


def load_spatial_records() -> List[Dict[str, Any]]:
    return load_cache_records(
        "spatial_join_result",
        "spatial_join_result",
    )

def check_input_file_exists(
    path: Optional[Any] = None,
    source_name: str = "",
    required: bool = True,
) -> List[Dict[str, Any]]:
    if isinstance(path, dict):
        path = None

    if path is None:
        issues: List[
            Dict[str, Any]
        ] = []

        issues.extend(
            check_policy_input_file()
        )
        issues.extend(
            check_linkage_input_file()
        )
        issues.extend(
            check_flood_source_paths()
        )

        return issues

    target = Path(path)

    if target.exists():
        return []

    return [
        make_quality_issue(
            issue_type=(
                "missing_"
                + clean_text(
                    source_name,
                    default="input_file",
                )
            ),
            message=(
                "Missing required "
                "input/source path: "
                f"{target}"
            ),
            severity=(
                "critical"
                if required
                else "medium"
            ),
            category="input_file",
            source=(
                source_name
                or "unknown"
            ),
            source_file=str(target),
            field="path",
            expected=(
                "existing file or "
                "directory"
            ),
            actual=str(target),
            suggestion=(
                "Verify configured "
                "input/source path before "
                "running data-dependent "
                "phases."
            ),
        )
    ]

def check_data_source_config(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    use_excel = bool(get_runtime_config_value("USE_EXCEL_DATA_SOURCE", True))
    use_mysql = bool(get_runtime_config_value("USE_MYSQL_DATA_SOURCE", False))

    issues: List[Dict[str, Any]] = []

    if use_excel and use_mysql:
        issues.append(
            make_quality_issue(
                issue_type="multiple_data_sources_enabled",
                message="เปิด Excel และ MySQL data source พร้อมกัน",
                severity="critical",
                category="runtime",
                source="system",
                field="USE_EXCEL_DATA_SOURCE/USE_MYSQL_DATA_SOURCE",
                expected="only one active source",
                actual={"excel": use_excel, "mysql": use_mysql},
                suggestion="เปิดใช้งาน data source ได้ทีละชนิดเท่านั้น",
            )
        )

    if not use_excel and not use_mysql:
        issues.append(
            make_quality_issue(
                issue_type="no_data_source_enabled",
                message="ยังไม่ได้เปิด data source สำหรับ runtime",
                severity="critical",
                category="runtime",
                source="system",
                field="USE_EXCEL_DATA_SOURCE/USE_MYSQL_DATA_SOURCE",
                expected="one active source",
                actual={"excel": use_excel, "mysql": use_mysql},
                suggestion="ตั้ง USE_EXCEL_DATA_SOURCE=True ในรอบนี้",
            )
        )

    return issues


def check_excel_source_paths(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if not bool(get_runtime_config_value("USE_EXCEL_DATA_SOURCE", True)):
        return []

    checks = [
        ("FLOOD_OUTPUT_DIR", get_runtime_path("FLOOD_OUTPUT_DIR", FLOOD_OUTPUT_DIR), "flood_output"),
        ("FLOOD_LATEST_DATABASE_PATH", get_runtime_path("FLOOD_LATEST_DATABASE_PATH", FLOOD_LATEST_DATABASE_PATH), "flood_latest"),
        ("FLOOD_MASTER_DATABASE_PATH", get_runtime_path("FLOOD_MASTER_DATABASE_PATH", FLOOD_MASTER_DATABASE_PATH), "flood_master"),
        ("FLOOD_HISTORY_DIR", get_runtime_path("FLOOD_HISTORY_DIR", FLOOD_HISTORY_DIR), "flood_history"),
        ("PREDICTION_DATA_DIR", get_runtime_path("PREDICTION_DATA_DIR", get_runtime_config_value("FLOOD_PREDICTION_DIR")), "flood_prediction"),
        ("UPLOAD_ENTITY_DIR", get_runtime_path("UPLOAD_ENTITY_DIR", get_runtime_config_value("ENTITY_UPLOAD_DIR")), "uploaded_entity"),
    ]

    issues: List[Dict[str, Any]] = []

    for path_name, path_value, source_name in checks:
        if path_value is None:
            issues.append(
                make_missing_path_issue(
                    issue_type="excel_source_path_not_configured",
                    message=f"ยังไม่ได้กำหนด {path_name}",
                    path_name=path_name,
                    path_value="",
                    severity="high",
                    source=source_name,
                )
            )
            continue

        if not path_exists(path_value):
            issues.append(
                make_missing_path_issue(
                    issue_type="excel_source_path_missing",
                    message=f"ไม่พบ path: {path_name}",
                    path_name=path_name,
                    path_value=path_value,
                    severity="high" if path_name in {"FLOOD_LATEST_DATABASE_PATH", "FLOOD_MASTER_DATABASE_PATH"} else "medium",
                    source=source_name,
                )
            )

    return issues


def check_mysql_source_placeholder(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if not bool(get_runtime_config_value("USE_MYSQL_DATA_SOURCE", False)):
        return []

    return [
        make_quality_issue(
            issue_type="mysql_source_placeholder_active",
            message="MySQL data source ยังเป็น placeholder",
            severity="high",
            category="runtime",
            source="system",
            field="USE_MYSQL_DATA_SOURCE",
            actual=True,
            suggestion="รอบนี้ให้ใช้ Excel source เท่านั้นจนกว่า MySQL source จะถูก implement",
        )
    ]


def check_latest_excel_file(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    path = get_runtime_path("FLOOD_LATEST_DATABASE_PATH", FLOOD_LATEST_DATABASE_PATH)

    if path is not None and path_exists(path):
        return []

    return [
        make_missing_path_issue(
            issue_type="latest_excel_file_missing",
            message="ไม่พบ latest_database.xlsx",
            path_name="FLOOD_LATEST_DATABASE_PATH",
            path_value=path,
            severity="high",
            source="flood_latest",
        )
    ]


def check_master_excel_file(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    path = get_runtime_path("FLOOD_MASTER_DATABASE_PATH", FLOOD_MASTER_DATABASE_PATH)

    if path is not None and path_exists(path):
        return []

    return [
        make_missing_path_issue(
            issue_type="master_excel_file_missing",
            message="ไม่พบ master_database.xlsx",
            path_name="FLOOD_MASTER_DATABASE_PATH",
            path_value=path,
            severity="high",
            source="flood_master",
        )
    ]


def check_history_dir(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    path = get_runtime_path("FLOOD_HISTORY_DIR", FLOOD_HISTORY_DIR)

    if path is not None and path_exists(path):
        return []

    return [
        make_missing_path_issue(
            issue_type="history_dir_missing",
            message="ไม่พบ flood history directory",
            path_name="FLOOD_HISTORY_DIR",
            path_value=path,
            severity="medium",
            source="flood_history",
        )
    ]


def check_prediction_dir(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    path = get_runtime_path("PREDICTION_DATA_DIR", get_runtime_config_value("FLOOD_PREDICTION_DIR"))

    if path is not None and path_exists(path):
        return []

    return [
        make_missing_path_issue(
            issue_type="prediction_dir_missing",
            message="ไม่พบ prediction directory",
            path_name="PREDICTION_DATA_DIR",
            path_value=path,
            severity="medium",
            source="flood_prediction_latest",
        )
    ]


def check_upload_dir(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    path = get_runtime_path("UPLOAD_ENTITY_DIR", get_runtime_config_value("ENTITY_UPLOAD_DIR"))

    if path is not None and path_exists(path):
        return []

    return [
        make_missing_path_issue(
            issue_type="upload_dir_missing",
            message="ไม่พบ uploaded entity directory",
            path_name="UPLOAD_ENTITY_DIR",
            path_value=path,
            severity="low",
            source="uploaded_entity_latest",
        )
    ]


def check_policy_input_file(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return check_input_file_exists(POLICY_INPUT_PATH, "policy_input", required=True)


def check_linkage_input_file(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return check_input_file_exists(LINKAGE_INPUT_PATH, "linkage_input", required=True)


def check_flood_source_paths(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    issues.extend(check_input_file_exists(FLOOD_OUTPUT_DIR, "flood_output", required=True))
    issues.extend(check_input_file_exists(FLOOD_LATEST_DATABASE_PATH, "flood_output", required=True))
    issues.extend(check_input_file_exists(FLOOD_MASTER_DATABASE_PATH, "flood_output", required=True))
    return issues


def check_required_columns(
    records: Any,
    required_fields: List[str],
    source_name: str,
) -> List[Dict[str, Any]]:
    record_list = coerce_records(
        records,
        source_name=source_name,
    )

    if not record_list:
        return [
            make_quality_issue(
                issue_type="missing_source",
                message=(
                    f"{source_name} source "
                    "is missing or empty."
                ),
                severity="high",
                category="cache",
                source=source_name,
                field="records",
                expected=(
                    "non-empty records"
                ),
                actual=0,
            )
        ]

    available = {
        key
        for record
        in record_list[:200]
        for key
        in record.keys()
    }

    return [
        make_quality_issue(
            issue_type=(
                "missing_required_column"
            ),
            message=(
                f"{source_name} is missing "
                f"required field {field}."
            ),
            severity="high",
            category="required_column",
            source=source_name,
            field=field,
            expected=field,
            actual="missing",
        )
        for field in required_fields
        if field not in available
    ]


def check_missing_values(
    records: Any,
    fields: List[str],
    source_name: str,
    severity: str = "medium",
) -> List[Dict[str, Any]]:
    record_list = coerce_records(
        records,
        source_name=source_name,
    )

    total = len(record_list)

    if not total:
        return []

    issues: List[
        Dict[str, Any]
    ] = []

    for field in fields:
        missing_count = sum(
            1
            for record in record_list
            if is_empty_value(
                record.get(field)
            )
        )

        if not missing_count:
            continue

        ratio = (
            missing_count
            / total
        )

        issue_severity = (
            "high"
            if (
                field
                in {
                    "tax_id_norm",
                    "company_name",
                    "province",
                    "risk_level",
                    "status_now",
                    "director_name",
                }
                and ratio >= 0.25
            )
            else severity
        )

        issues.append(
            make_quality_issue(
                issue_type=(
                    "missing_value"
                ),
                message=(
                    f"{source_name}.{field} "
                    "has missing values."
                ),
                severity=(
                    issue_severity
                ),
                category=(
                    "missing_value"
                ),
                source=source_name,
                field=field,
                expected=(
                    "non-empty value"
                ),
                actual=(
                    f"{missing_count}/"
                    f"{total}"
                ),
                meta={
                    "missing_count": (
                        missing_count
                    ),
                    "missing_ratio": (
                        round(
                            ratio,
                            4,
                        )
                    ),
                    "record_count": total,
                },
            )
        )

    return issues


def check_duplicate_keys(
    records: Any,
    key_fields: Any,
    source_name: str,
) -> List[Dict[str, Any]]:
    record_list = coerce_records(
        records,
        source_name=source_name,
    )

    fields = (
        [key_fields]
        if isinstance(
            key_fields,
            str,
        )
        else list(
            key_fields
            or []
        )
    )

    counter: Dict[str, int] = {}

    for record in record_list:
        parts = [
            clean_text(
                record.get(field)
            )
            for field in fields
        ]

        if not any(parts):
            continue

        key = "|".join(parts)
        counter[key] = (
            counter.get(key, 0)
            + 1
        )

    duplicates = {
        key: count
        for key, count
        in counter.items()
        if count > 1
    }

    if not duplicates:
        return []

    return [
        make_quality_issue(
            issue_type="duplicate_key",
            message=(
                f"{source_name} has "
                "duplicate key values."
            ),
            severity="high",
            category="duplicate",
            source=source_name,
            field="|".join(fields),
            expected="unique key",
            actual=len(duplicates),
            meta={
                "duplicate_count": (
                    len(duplicates)
                ),
                "sample_keys": list(
                    duplicates.keys()
                )[:20],
            },
        )
    ]

def check_tax_id_quality(
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    issues: List[
        Dict[str, Any]
    ] = []

    company_records = (
        load_company_unified_records()
    )
    policy_records = (
        load_policy_records()
    )
    linkage_records = (
        load_linkage_records()
    )
    spatial_records = (
        load_spatial_records()
    )

    company_tax_ids = {
        normalize_tax_id(
            record.get("tax_id_norm")
            or record.get("tax_id")
        )
        for record
        in company_records
    }
    company_tax_ids.discard("")

    source_records = [
        (
            "company_unified_master",
            company_records,
            "high",
        ),
        (
            "policy_fact",
            policy_records,
            "medium",
        ),
        (
            "linkage_graph",
            linkage_records,
            "medium",
        ),
        (
            "spatial_join_result",
            spatial_records,
            "medium",
        ),
    ]

    for (
        source_name,
        records,
        default_severity,
    ) in source_records:
        for index, record in enumerate(
            records[:5000],
            start=1,
        ):
            if source_name == "linkage_graph":
                record_kind = clean_text_lower(
                    record.get(
                        "record_kind"
                    )
                )

                node_type = clean_text_lower(
                    record.get("type")
                    or record.get(
                        "node_type"
                    )
                )

                if (
                    record_kind
                    in {
                        "edge",
                        "edges",
                    }
                    or node_type
                    == "director"
                ):
                    continue

                if not any(
                    not is_empty_value(
                        record.get(field)
                    )
                    for field in [
                        "tax_id_norm",
                        "tax_id",
                        "tax_id_raw",
                    ]
                ):
                    continue

            raw_value = (
                record.get("tax_id_norm")
                or record.get("tax_id")
                or record.get("tax_id_raw")
            )

            validation = validate_tax_id(
                raw_value
            )

            tax_id = clean_text(
                validation.get(
                    "tax_id_norm"
                )
            ) or normalize_tax_id(
                raw_value
            )

            tax_id_valid = bool(
                validation.get(
                    "tax_id_valid",
                    validation.get(
                        "valid",
                        False,
                    ),
                )
            )

            if not tax_id:
                issues.append(
                    make_quality_issue(
                        issue_type=(
                            "missing_tax_id"
                        ),
                        message=(
                            f"{source_name} "
                            "record is missing "
                            "tax_id_norm."
                        ),
                        severity=(
                            default_severity
                        ),
                        category="tax_id",
                        source=source_name,
                        record_key=clean_text(
                            raw_value
                        ),
                        row_number=index,
                        field="tax_id_norm",
                        actual=raw_value,
                    )
                )

                continue

            if not tax_id_valid:
                validation_issues = (
                    validation.get(
                        "issues",
                        [],
                    )
                    if isinstance(
                        validation.get(
                            "issues"
                        ),
                        list,
                    )
                    else [
                        clean_text(
                            validation.get(
                                "tax_id_issue"
                            )
                        )
                    ]
                )

                issues.append(
                    make_quality_issue(
                        issue_type=(
                            "invalid_tax_id_format"
                        ),
                        message=(
                            f"{source_name} has "
                            "invalid tax_id_norm."
                        ),
                        severity=(
                            default_severity
                        ),
                        category="tax_id",
                        source=source_name,
                        record_key=tax_id,
                        row_number=index,
                        tax_id_norm=tax_id,
                        field="tax_id_norm",
                        expected=(
                            "13 digit tax id"
                        ),
                        actual=raw_value,
                        meta={
                            "issues": [
                                item
                                for item
                                in validation_issues
                                if clean_text(
                                    item
                                )
                            ]
                        },
                    )
                )

            if (
                source_name
                in {
                    "policy_fact",
                    "linkage_graph",
                    "spatial_join_result",
                }
                and company_tax_ids
                and tax_id
                not in company_tax_ids
            ):
                issues.append(
                    make_quality_issue(
                        issue_type=(
                            "tax_id_join_loss"
                        ),
                        message=(
                            f"{source_name} "
                            "tax_id_norm is not "
                            "found in "
                            "company_unified_master."
                        ),
                        severity=(
                            default_severity
                        ),
                        category="tax_id",
                        source=source_name,
                        record_key=tax_id,
                        row_number=index,
                        tax_id_norm=tax_id,
                        field="tax_id_norm",
                        expected=(
                            "tax id exists in "
                            "company_unified_master"
                        ),
                        actual=tax_id,
                    )
                )

    issues.extend(
        check_duplicate_keys(
            company_records,
            "tax_id_norm",
            "company_unified_master",
        )
    )

    return issues

def get_lat_lon(record: Dict[str, Any]) -> Tuple[Any, Any]:
    pairs = [
        ("lat", "lon"),
        ("latitude", "longitude"),
        ("company_lat", "company_lon"),
        ("company_latitude", "company_longitude"),
        ("station_latitude", "station_longitude"),
        ("dam_latitude", "dam_longitude"),
        ("medium_latitude", "medium_longitude"),
    ]
    for lat_key, lon_key in pairs:
        if not is_empty_value(record.get(lat_key)) or not is_empty_value(record.get(lon_key)):
            return record.get(lat_key), record.get(lon_key)
    return None, None

def check_coordinate_quality(
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    issues: List[
        Dict[str, Any]
    ] = []

    sources = [
        (
            "company_unified_master",
            load_company_unified_records(),
            "high",
        ),
        (
            "flood_computed_risk",
            load_cache_records(
                "flood_computed_risk",
                "flood_computed_risk",
            ),
            "high",
        ),
        (
            "spatial_join_result",
            load_spatial_records(),
            "medium",
        ),
    ]

    for (
        source_name,
        records,
        severity,
    ) in sources:
        for index, record in enumerate(
            records[:5000],
            start=1,
        ):
            lat, lon = get_lat_lon(
                record
            )

            if (
                is_empty_value(lat)
                and is_empty_value(lon)
            ):
                if (
                    to_bool(
                        record.get(
                            "has_location"
                        ),
                        default=False,
                    )
                    or source_name
                    == "flood_computed_risk"
                ):
                    issues.append(
                        make_quality_issue(
                            issue_type=(
                                "missing_coordinate"
                            ),
                            message=(
                                f"{source_name} "
                                "record is missing "
                                "coordinates."
                            ),
                            severity=severity,
                            category="coordinate",
                            source=source_name,
                            row_number=index,
                            tax_id_norm=(
                                record.get(
                                    "tax_id_norm",
                                    "",
                                )
                            ),
                            company_name=(
                                record.get(
                                    "company_name",
                                    "",
                                )
                            ),
                            field="lat/lon",
                            expected=(
                                "valid latitude "
                                "and longitude"
                            ),
                            actual={
                                "lat": lat,
                                "lon": lon,
                            },
                        )
                    )

                continue

            validation = (
                validate_coordinate(
                    lat,
                    lon,
                )
            )

            if validation.get("valid"):
                continue

            validation_issues = (
                validation.get(
                    "issues",
                    [],
                )
                if isinstance(
                    validation.get(
                        "issues"
                    ),
                    list,
                )
                else [
                    clean_text(
                        validation.get(
                            "issue"
                        )
                    )
                ]
            )

            lat_number = to_number(
                lat,
                None,
            )
            lon_number = to_number(
                lon,
                None,
            )

            if (
                lat_number == 0
                and lon_number == 0
            ):
                issue_type = (
                    "zero_coordinate"
                )

            elif any(
                "outside_thailand"
                in clean_text_lower(
                    issue
                )
                for issue
                in validation_issues
            ):
                issue_type = (
                    "outside_thailand_coordinate"
                )

            elif any(
                "missing_coordinate"
                in clean_text_lower(
                    issue
                )
                for issue
                in validation_issues
            ):
                issue_type = (
                    "missing_coordinate"
                )

            else:
                issue_type = (
                    "invalid_coordinate"
                )

            issues.append(
                make_quality_issue(
                    issue_type=issue_type,
                    message=(
                        f"{source_name} "
                        "record has invalid "
                        "coordinates."
                    ),
                    severity=severity,
                    category="coordinate",
                    source=source_name,
                    row_number=index,
                    tax_id_norm=(
                        record.get(
                            "tax_id_norm",
                            "",
                        )
                    ),
                    company_name=(
                        record.get(
                            "company_name",
                            "",
                        )
                    ),
                    field="lat/lon",
                    expected=(
                        "valid Thailand "
                        "coordinate"
                    ),
                    actual={
                        "lat": lat,
                        "lon": lon,
                    },
                    meta={
                        "issues": [
                            issue
                            for issue
                            in validation_issues
                            if clean_text(
                                issue
                            )
                        ]
                    },
                )
            )

    return issues

def check_policy_quality(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = load_policy_records()
    issues: List[Dict[str, Any]] = []

    if not records:
        return [
            make_quality_issue(
                issue_type="policy_source_empty",
                message="policy source cache is missing or empty.",
                severity="medium",
                category="policy",
                source="policy_fact",
                field="records",
                expected="non-empty records",
                actual=0,
                suggestion="ตรวจ PHASE company_policy_base หรือ policy_fact cache",
            )
        ]

    required_fields = [
        field
        for field in REQUIRED_FIELDS_BY_SOURCE.get("policy_fact", [])
        if field in {"tax_id_norm", "company_name", "premium", "loss", "suminsure"}
    ]

    issues.extend(check_required_columns(records, required_fields, "policy_fact"))
    issues.extend(
        check_missing_values(
            records,
            [
                field
                for field in ["tax_id_norm", "company_name"]
                if any(field in record for record in records[:200])
            ],
            "policy_fact",
            severity="medium",
        )
    )

    for index, record in enumerate(records[:5000], start=1):
        for field in [
            "premium",
            "loss",
            "suminsure",
            "total_premium",
            "total_loss",
            "total_suminsure",
            "exp_premium",
        ]:
            if field not in record:
                continue

            value = to_number(record.get(field), None)

            if value is None:
                continue

            if value < 0:
                issues.append(
                    make_quality_issue(
                        issue_type="invalid_policy_numeric",
                        message=f"Policy numeric field {field} is negative.",
                        severity="medium",
                        category="policy",
                        source="policy_fact",
                        row_number=index,
                        tax_id_norm=record.get("tax_id_norm", ""),
                        company_name=record.get("company_name", ""),
                        field=field,
                        expected="number >= 0",
                        actual=record.get(field),
                    )
                )

    return issues

def check_policy_status_conflicts(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = load_policy_records() or load_company_unified_records()
    issues: List[Dict[str, Any]] = []
    for index, record in enumerate(records[:5000], start=1):
        status_now = clean_text_lower(record.get("status_now") or record.get("policy_status_now"))
        status_new = clean_text_lower(record.get("status_now_new") or record.get("policy_status_now_new"))
        inforced = to_bool(record.get("inforced_flag"), default=None)
        active_count = to_number(record.get("active_subs") or record.get("active_policy_count"), 0) or 0
        expired_count = to_number(record.get("expired_subs") or record.get("expired_policy_count"), 0) or 0
        conflict = bool(status_now and status_new and status_now != status_new)
        conflict = conflict or bool(inforced is True and expired_count > active_count and active_count == 0)
        if conflict:
            issues.append(make_quality_issue("policy_status_conflict", "Policy status fields appear inconsistent.", "medium", "status_conflict", "policy_fact", row_number=index, tax_id_norm=record.get("tax_id_norm", ""), company_name=record.get("company_name", ""), field="status_now/status_now_new", expected="consistent status", actual={"status_now": status_now, "status_now_new": status_new, "inforced_flag": inforced, "active_subs": active_count, "expired_subs": expired_count}))
    return issues

def check_linkage_quality(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = load_linkage_records()
    issues: List[Dict[str, Any]] = []

    if not records:
        return [
            make_quality_issue(
                issue_type="missing_linkage_source",
                message="linkage_graph_payload cache is missing or empty.",
                severity="high",
                category="linkage",
                source="linkage_graph_payload",
                field="records",
                suggestion="ตรวจ PHASE linkage และ cache key linkage_graph_payload",
            )
        ]

    node_records = [
        record
        for record in records
        if clean_text_lower(record.get("record_kind")) in {"node", "nodes"}
        or clean_text(record.get("id")).startswith(("company:", "director:"))
    ]

    edge_records = [
        record
        for record in records
        if clean_text_lower(record.get("record_kind")) in {"edge", "edges"}
        or clean_text(record.get("edge_type"))
    ]

    if not node_records and not edge_records:
        issues.append(
            make_quality_issue(
                issue_type="linkage_graph_shape_unknown",
                message="linkage graph payload has records but no node/edge shape.",
                severity="medium",
                category="linkage",
                source="linkage_graph_payload",
                field="nodes/edges",
                actual={
                    "record_count": len(records),
                },
                suggestion="ตรวจ normalize_source_payload_to_records หรือ linkage_service graph contract",
            )
        )

    for index, record in enumerate(edge_records[:5000], start=1):
        source = clean_text(record.get("source"))
        target = clean_text(record.get("target"))

        if not source or not target:
            issues.append(
                make_quality_issue(
                    issue_type="edge_missing_source_or_target",
                    message="Linkage edge is missing source or target.",
                    severity="high",
                    category="linkage",
                    source="linkage_graph_payload",
                    row_number=index,
                    field="source/target",
                    actual={
                        "source": record.get("source"),
                        "target": record.get("target"),
                    },
                )
            )

        if clean_text(record.get("edge_type")) == "SHARED_DIRECTOR" and is_empty_value(record.get("shared_directors")):
            issues.append(
                make_quality_issue(
                    issue_type="empty_shared_directors",
                    message="SHARED_DIRECTOR edge has no shared_directors value.",
                    severity="medium",
                    category="linkage",
                    source="linkage_graph_payload",
                    row_number=index,
                    field="shared_directors",
                )
            )

    return issues

def check_latest_rainfall_sheet(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_source_records_from_service(
        module_name="flood_spatial_service",
        function_name="get_latest_rainfall",
        cache_key="flood_rainfall_latest",
        context=context,
    )

    if records:
        return []

    return [
        make_cache_issue(
            issue_type="latest_rainfall_missing",
            message="ไม่พบ rainfall latest records หลัง rebuild",
            cache_key="flood_rainfall_latest",
            severity="high",
            category="flood",
            suggestion="ตรวจ PHASE flood_excel_base และ latest rainfall sheet",
        )
    ]


def check_latest_waterlevel_sheet(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_source_records_from_service(
        module_name="flood_spatial_service",
        function_name="get_latest_waterlevel",
        cache_key="flood_waterlevel_latest",
        context=context,
    )

    if records:
        return []

    return [
        make_cache_issue(
            issue_type="latest_waterlevel_missing",
            message="ไม่พบ waterlevel latest records หลัง rebuild",
            cache_key="flood_waterlevel_latest",
            severity="high",
            category="flood",
            suggestion="ตรวจ PHASE flood_excel_base และ latest waterlevel sheet",
        )
    ]

def check_latest_dam_sheet(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    dam_records = []

    for cache_key in [
        "flood_dam_latest",
        "flood_large_dam_latest",
        "flood_medium_dam_latest",
        "large_dam_latest",
        "medium_dam_latest",
    ]:
        dam_records.extend(load_cache_records(cache_key, cache_key))

    if not dam_records:
        dam_records = get_source_records_from_service(
            module_name="flood_spatial_service",
            function_name="get_latest_dam",
            cache_key="flood_dam_latest",
            context=context,
        )

    if dam_records:
        return []

    return [
        make_cache_issue(
            issue_type="latest_dam_missing",
            message="ไม่พบ dam latest records หลัง rebuild",
            cache_key="flood_dam_latest/flood_large_dam_latest/flood_medium_dam_latest",
            severity="medium",
            category="flood",
            suggestion="ตรวจ PHASE flood_excel_base และ latest dam sheets",
        )
    ]

def get_prediction_records_for_quality(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_source_records_from_service(
        module_name="flood_spatial_service",
        function_name="get_latest_flood_predictions",
        cache_key="flood_prediction_latest",
        context=context,
    )

    if records:
        return records

    cached_records = load_cache_records("flood_prediction_latest", "flood_prediction_latest")

    if cached_records:
        return cached_records

    map_records = get_source_records_from_service(
        module_name="flood_spatial_service",
        function_name="get_flood_prediction_map",
        cache_key="flood_prediction_map",
        context=context,
    )

    if map_records:
        return map_records

    return load_cache_records("flood_prediction_map", "flood_prediction_map")


def check_prediction_file_exists(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_prediction_records_for_quality(context)

    if records:
        return []

    prediction_dir = get_runtime_path("PREDICTION_DATA_DIR", get_runtime_config_value("FLOOD_PREDICTION_DIR"))

    if prediction_dir and prediction_dir.exists():
        files = sorted(prediction_dir.glob("predict_*.xlsx"))
        if files:
            return []

    return [
        make_quality_issue(
            issue_type="prediction_file_missing",
            message="ไม่พบ prediction file หรือ flood_prediction_latest records",
            severity="medium",
            category="flood",
            source="flood_prediction_latest",
            field="prediction_file",
            actual=str(prediction_dir),
            suggestion="ตรวจ predict_*.xlsx หรือ PHASE spatial_prediction_entity",
        )
    ]


def check_prediction_required_columns(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_prediction_records_for_quality(context)

    if not records:
        return []

    columns = {key for record in records[:200] for key in record.keys()}
    missing = [
        column
        for column in FLOOD_PREDICTION_REQUIRED_COLUMNS
        if column not in columns
    ]

    return [
        make_quality_issue(
            issue_type="prediction_required_column_missing",
            message=f"Prediction records ขาด column สำคัญ: {column}",
            severity="high",
            category="schema",
            source="flood_prediction_latest",
            field=column,
            expected=FLOOD_PREDICTION_REQUIRED_COLUMNS,
            actual=sorted(columns),
            suggestion="ตรวจ normalize prediction columns ใน flood_spatial_service",
        )
        for column in missing
    ]


def check_prediction_location_match_rate(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_prediction_records_for_quality(context)

    if not records:
        return []

    matched = [
        record
        for record in records
        if not is_empty_value(record.get("matched_station_id"))
        or not is_empty_value(record.get("matched_station_code"))
        or not is_empty_value(record.get("matched_station_name"))
    ]

    rate = len(matched) / max(1, len(records))

    if rate >= 0.7:
        return []

    return [
        make_quality_issue(
            issue_type="prediction_location_match_rate_low",
            message="Prediction station location match rate ต่ำ",
            severity="high" if rate < 0.3 else "medium",
            category="flood",
            source="flood_prediction_latest",
            field="matched_station_id",
            expected=">= 0.70",
            actual=round(rate, 4),
            suggestion="ตรวจ station_id/station_code mapping กับ rainfall/waterlevel station master",
            meta={
                "record_count": len(records),
                "matched_count": len(matched),
            },
        )
    ]

def check_prediction_map_ready_rate(
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    records = (
        get_prediction_records_for_quality(
            context
        )
    )

    if not records:
        return []

    ready: List[
        Dict[str, Any]
    ] = []

    for record in records:
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
            if record.get(
                "longitude"
            )
            is not None
            else record.get("lon")
        )

        coordinate_valid = bool(
            validate_coordinate(
                latitude,
                longitude,
            ).get("valid")
        )

        if (
            to_bool(
                record.get("map_ready"),
                default=False,
            )
            and coordinate_valid
        ):
            ready.append(record)

    rate = (
        len(ready)
        / max(
            1,
            len(records),
        )
    )

    if rate >= 0.7:
        return []

    return [
        make_quality_issue(
            issue_type=(
                "prediction_map_ready_rate_low"
            ),
            message=(
                "Prediction map_ready "
                "rate ต่ำ"
            ),
            severity=(
                "high"
                if rate < 0.3
                else "medium"
            ),
            category="map_readiness",
            source=(
                "flood_prediction_latest"
            ),
            field="map_ready",
            expected=">= 0.70",
            actual=round(
                rate,
                4,
            ),
            suggestion=(
                "เติมพิกัดจาก station "
                "master และใช้ province "
                "fallback สำหรับ record "
                "ที่ไม่มีพิกัด"
            ),
            meta={
                "record_count": len(
                    records
                ),
                "map_ready_count": len(
                    ready
                ),
            },
        )
    ]

def check_prediction_province_fallback_rate(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_prediction_records_for_quality(context)

    if not records:
        return []

    not_ready_with_province = [
        record
        for record in records
        if not to_bool(record.get("map_ready"), default=False)
        and (
            not is_empty_value(record.get("province"))
            or not is_empty_value(record.get("province_model"))
            or not is_empty_value(record.get("province_name_th"))
        )
    ]

    fallback_ready = [
        record
        for record in not_ready_with_province
        if record.get("focus_fallback")
        or clean_text(record.get("focus_level")) == "province_boundary"
    ]

    if not not_ready_with_province:
        return []

    rate = len(fallback_ready) / max(1, len(not_ready_with_province))

    if rate >= 0.8:
        return []

    return [
        make_quality_issue(
            issue_type="prediction_province_fallback_rate_low",
            message="Prediction province fallback rate ต่ำ",
            severity="medium",
            category="map_readiness",
            source="flood_prediction_latest",
            field="focus_fallback",
            expected=">= 0.80",
            actual=round(rate, 4),
            suggestion="ส่ง focus_fallback = province_boundary เมื่อ map_ready=false แต่มี province",
            meta={
                "not_ready_with_province_count": len(not_ready_with_province),
                "fallback_ready_count": len(fallback_ready),
            },
        )
    ]

def check_flood_quality(
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    issues: List[
        Dict[str, Any]
    ] = []

    checker_plan = [
        (
            "latest_excel_file",
            check_latest_excel_file,
        ),
        (
            "master_excel_file",
            check_master_excel_file,
        ),
        (
            "history_dir",
            check_history_dir,
        ),
        (
            "latest_rainfall_sheet",
            check_latest_rainfall_sheet,
        ),
        (
            "latest_waterlevel_sheet",
            check_latest_waterlevel_sheet,
        ),
        (
            "latest_dam_sheet",
            check_latest_dam_sheet,
        ),
        (
            "prediction_file_exists",
            check_prediction_file_exists,
        ),
        (
            "prediction_required_columns",
            check_prediction_required_columns,
        ),
        (
            "prediction_location_match_rate",
            check_prediction_location_match_rate,
        ),
        (
            "prediction_map_ready_rate",
            check_prediction_map_ready_rate,
        ),
        (
            "prediction_province_fallback_rate",
            check_prediction_province_fallback_rate,
        ),
    ]

    for checker_name, checker in checker_plan:
        try:
            checker_issues = checker(
                context
            )

        except TypeError:
            try:
                checker_issues = checker()

            except Exception as exc:
                checker_issues = [
                    make_quality_issue(
                        issue_type=(
                            "flood_checker_failed"
                        ),
                        message=(
                            safe_exception_message(
                                exc,
                                (
                                    f"{checker_name} "
                                    "failed."
                                ),
                            )
                        ),
                        severity="high",
                        category="flood",
                        source="flood_output",
                        suggestion=(
                            "ตรวจ "
                            "flood_spatial_service "
                            "และ source layer"
                        ),
                        meta={
                            "checker": (
                                checker_name
                            ),
                            "exception_type": (
                                exc.__class__.__name__
                            ),
                        },
                    )
                ]

        except Exception as exc:
            checker_issues = [
                make_quality_issue(
                    issue_type=(
                        "flood_checker_failed"
                    ),
                    message=(
                        safe_exception_message(
                            exc,
                            (
                                f"{checker_name} "
                                "failed."
                            ),
                        )
                    ),
                    severity="high",
                    category="flood",
                    source="flood_output",
                    suggestion=(
                        "ตรวจ "
                        "flood_spatial_service "
                        "และ source layer"
                    ),
                    meta={
                        "checker": checker_name,
                        "exception_type": (
                            exc.__class__.__name__
                        ),
                    },
                )
            ]

        if isinstance(
            checker_issues,
            list,
        ):
            issues.extend(
                checker_issues
            )

    try:
        flood_latest = (
            load_flood_latest_for_quality()
        )

        issues.extend(
            check_flood_sheet_structure(
                flood_latest
            )
        )
        issues.extend(
            check_flood_freshness(
                flood_latest
            )
        )
        issues.extend(
            check_flood_coordinate_quality(
                flood_latest
            )
        )
        issues.extend(
            check_flood_history_quality()
        )

    except Exception as exc:
        issues.append(
            make_quality_issue(
                issue_type=(
                    "flood_source_quality_failed"
                ),
                message=(
                    safe_exception_message(
                        exc,
                        (
                            "Flood source quality "
                            "check failed."
                        ),
                    )
                ),
                severity="high",
                category="flood",
                source="flood_output",
                meta={
                    "checker": (
                        "legacy_flood_source_checks"
                    ),
                    "exception_type": (
                        exc.__class__.__name__
                    ),
                },
            )
        )

    return dedupe_issues(issues)

def check_spatial_join_quality_internal(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = load_spatial_records()
    company_records = load_company_unified_records()
    issues: List[Dict[str, Any]] = []
    if not records:
        issues.append(make_quality_issue("missing_spatial_join", "spatial_join_result cache is missing or empty.", "high", "spatial", "spatial_join_result"))
        return issues
    issues.extend(check_missing_values(records, ["tax_id_norm", "flood_risk_level", "flood_join_level"], "spatial_join_result", severity="medium"))
    spatial_tax_ids = {normalize_tax_id(record.get("tax_id_norm")) for record in records}
    for record in company_records[:5000]:
        tax_id = normalize_tax_id(record.get("tax_id_norm"))
        if tax_id and to_bool(record.get("has_location"), default=False) and tax_id not in spatial_tax_ids:
            issues.append(make_quality_issue("company_spatial_join_loss", "Company has location but no spatial join record.", "medium", "spatial", "spatial_join_result", record_key=tax_id, tax_id_norm=tax_id, company_name=record.get("company_name", "")))
    return issues

def get_latest_entity_records_for_quality(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    try:
        import entity_upload_service

        payload = entity_upload_service.get_latest_entity_records(
            context=context or {},
            limit=20000,
            offset=0,
        )
        records = normalize_source_payload_to_records(payload, source_name="uploaded_entity_latest")
        if records:
            return records
    except Exception:
        pass

    return load_cache_records("uploaded_entity_latest")


def get_latest_entity_raw_payload() -> Dict[str, Any]:
    try:
        import entity_upload_service

        payload = entity_upload_service.read_latest_entities()
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    return normalize_cache_payload(read_cache("uploaded_entity_latest", default={}))


def check_latest_entity_upload_exists(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    payload = get_latest_entity_raw_payload()
    records = get_latest_entity_records_for_quality(context)

    if payload or records:
        return []

    return [
        make_cache_issue(
            issue_type="latest_entity_upload_missing",
            message="ยังไม่พบ uploaded entity latest layer",
            cache_key="uploaded_entity_latest",
            severity="low",
            category="map_readiness",
            suggestion="upload entity CSV เมื่อต้องการ overlay user entity บนแผนที่",
        )
    ]


def check_entity_displayable_count(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_latest_entity_records_for_quality(context)

    if records:
        return []

    payload = get_latest_entity_raw_payload()
    if payload:
        return [
            make_quality_issue(
                issue_type="entity_displayable_count_zero",
                message="Uploaded entity มี payload แต่ไม่มี displayable records",
                severity="medium",
                category="map_readiness",
                source="uploaded_entity_latest",
                field="displayable_records",
                actual=0,
                suggestion="ตรวจ column required และ latitude/longitude ของ upload file",
            )
        ]

    return []


def check_entity_not_displayable_count(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    try:
        import entity_upload_service

        logs_payload = entity_upload_service.get_upload_logs(context=context or {}, limit=50)
        logs = normalize_source_payload_to_records(logs_payload, source_name="uploaded_entity_logs")
    except Exception:
        logs = []

    invalid_count = 0

    for item in logs:
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        invalid_count += int(to_number(summary.get("not_displayable_records"), 0) or 0)

    if invalid_count <= 0:
        return []

    return [
        make_quality_issue(
            issue_type="entity_not_displayable_records_found",
            message="พบ uploaded entity not-displayable records",
            severity="low",
            category="map_readiness",
            source="uploaded_entity_latest",
            field="not_displayable_records",
            actual=invalid_count,
            suggestion="เปิด error report เพื่อตรวจ row ที่แสดงบน map ไม่ได้",
        )
    ]


def check_entity_invalid_coordinate_count(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = get_latest_entity_records_for_quality(context)
    invalid = []

    for record in records:
        validation = validate_coordinate(record.get("latitude"), record.get("longitude"))
        if not validation.get("valid"):
            invalid.append(record)

    if not invalid:
        return []

    return [
        make_quality_issue(
            issue_type="entity_invalid_coordinate_count",
            message="พบ uploaded entity coordinate ไม่ถูกต้อง",
            severity="medium",
            category="coordinate",
            source="uploaded_entity_latest",
            field="latitude/longitude",
            actual=len(invalid),
            suggestion="ตรวจ latitude/longitude ของ uploaded entity",
            meta={
                "invalid_coordinate_count": len(invalid),
                "record_count": len(records),
            },
        )
    ]

def check_entity_error_report_exists(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    try:
        import entity_upload_service

        logs_payload = entity_upload_service.get_upload_logs(context=context or {}, limit=20)
        logs = normalize_source_payload_to_records(logs_payload, source_name="uploaded_entity_logs")
    except Exception:
        logs = []

    missing_reports = []

    for item in logs:
        upload_id = clean_text(item.get("upload_id"))
        status = clean_text_lower(item.get("status"))

        if not upload_id:
            continue

        if status in {"success", "completed", "ok"}:
            continue

        try:
            report_payload = entity_upload_service.get_upload_error_report_file(upload_id)
        except Exception:
            missing_reports.append(upload_id)
            continue

        exists = False

        if isinstance(report_payload, (str, Path)):
            exists = Path(report_payload).exists()

        elif isinstance(report_payload, tuple):
            report_path = report_payload[0] if len(report_payload) > 0 else None
            exists = bool(report_path and Path(report_path).exists())

        elif isinstance(report_payload, dict):
            data = report_payload.get("data", {}) if isinstance(report_payload.get("data"), dict) else report_payload
            exists = bool(
                data.get("exists")
                or data.get("download_ready")
                or data.get("file_exists")
            )

            for key in ["file_path", "path", "error_report_file"]:
                if data.get(key):
                    try:
                        exists = exists or Path(str(data.get(key))).exists()
                    except Exception:
                        pass

        if not exists:
            missing_reports.append(upload_id)

    if not missing_reports:
        return []

    return [
        make_quality_issue(
            issue_type="entity_error_report_missing",
            message="พบ upload ที่มี error แต่ไม่มี error report",
            severity="low",
            category="map_readiness",
            source="uploaded_entity_latest",
            field="error_report_file",
            actual=missing_reports,
            suggestion="ตรวจ save_upload_outputs ใน entity_upload_service",
        )
    ]

def check_company_unified_quality(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    records = load_company_unified_records()
    issues: List[Dict[str, Any]] = []
    if not records:
        return [make_quality_issue("missing_company_unified_master", "company_unified_master cache is missing or empty.", "critical", "company_unified", "company_unified_master")]
    issues.extend(check_required_columns(records, REQUIRED_FIELDS_BY_SOURCE["company_unified_master"], "company_unified_master"))
    issues.extend(check_missing_values(records, ["tax_id_norm", "company_name", "province"], "company_unified_master", severity="medium"))
    issues.extend(check_duplicate_keys(records, "tax_id_norm", "company_unified_master"))
    for index, record in enumerate(records[:5000], start=1):
        if to_bool(record.get("has_location"), default=False):
            lat, lon = get_lat_lon(record)
            if not validate_coordinate(lat, lon).get("valid"):
                issues.append(make_quality_issue("location_flag_mismatch", "Company has_location is true but coordinate is invalid or missing.", "medium", "company_unified", "company_unified_master", row_number=index, tax_id_norm=record.get("tax_id_norm", ""), company_name=record.get("company_name", ""), field="has_location/lat/lon", actual={"has_location": record.get("has_location"), "lat": lat, "lon": lon}))
        total_loss = to_number(record.get("total_loss"), None)
        total_premium = to_number(record.get("total_premium"), None)
        if total_loss is not None and total_loss < 0 or total_premium is not None and total_premium < 0:
            issues.append(make_quality_issue("invalid_company_financial", "Company financial aggregate is negative.", "medium", "company_unified", "company_unified_master", row_number=index, tax_id_norm=record.get("tax_id_norm", ""), field="total_loss/total_premium"))
    return issues

def check_cache_registry(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    registry = get_runtime_config_value("CACHE_REGISTRY", None)

    if isinstance(registry, dict) and registry:
        return []

    return [
        make_quality_issue(
            issue_type="cache_registry_missing_or_empty",
            message="CACHE_REGISTRY ยังไม่มีข้อมูลหรือยังไม่ได้ config",
            severity="low",
            category="cache",
            source="system",
            field="CACHE_REGISTRY",
            actual=registry,
            suggestion="เพิ่ม cache registry ใน config.py เพื่อให้ rebuild dependency ตรวจได้ครบ",
        )
    ]


def check_missing_critical_cache(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []

    optional_when_alias_exists = {
        "flood_dam_latest": [
            "flood_large_dam_latest",
            "flood_medium_dam_latest",
        ],
        "package_preview": [
            "dashboard_summary",
            "chart_summary",
        ],
    }

    for cache_key in POST_REBUILD_CRITICAL_CACHE_KEYS:
        alias_keys = optional_when_alias_exists.get(cache_key, [])

        try:
            exists = get_cache_file_path(cache_key).exists()
        except Exception:
            exists = False

        if not exists and alias_keys:
            exists = any(path_exists(get_cache_file_path(alias_key)) for alias_key in alias_keys)

        if exists:
            continue

        issues.append(
            make_cache_issue(
                issue_type="critical_cache_missing",
                message=f"ไม่พบ critical cache หลัง rebuild: {cache_key}",
                cache_key=cache_key,
                severity="high" if cache_key in {"company_unified_base", "company_unified_master", "linkage_graph_payload", "map_layers"} else "medium",
                suggestion="ตรวจ staged rebuild phase ที่สร้าง cache นี้",
            )
        )

    return issues


def check_stale_cache(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    max_age_minutes = int(to_number(get_runtime_config_value("DATA_QUALITY_MAX_CACHE_AGE_MINUTES", 1440), 1440) or 1440)
    now = datetime.now()
    issues: List[Dict[str, Any]] = []

    for cache_key in POST_REBUILD_CRITICAL_CACHE_KEYS:
        created_at = get_cache_created_at(cache_key)

        if created_at is None:
            continue

        age_minutes = (now - created_at).total_seconds() / 60

        if age_minutes <= max_age_minutes:
            continue

        issues.append(
            make_cache_issue(
                issue_type="stale_cache",
                message=f"cache เก่ากว่า threshold: {cache_key}",
                cache_key=cache_key,
                severity="low",
                actual=round(age_minutes, 2),
                suggestion="run staged rebuild ใหม่",
                meta={
                    "age_minutes": round(age_minutes, 2),
                    "max_age_minutes": max_age_minutes,
                },
            )
        )

    return issues


def check_degraded_cache(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []

    for cache_key in POST_REBUILD_CRITICAL_CACHE_KEYS:
        payload = normalize_cache_payload(read_cache(cache_key, default={}))

        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        degraded = bool(
            to_bool(payload.get("degraded"), default=False)
            or to_bool(meta.get("degraded"), default=False)
        )

        if not degraded:
            continue

        issues.append(
            make_cache_issue(
                issue_type="degraded_cache",
                message=f"cache อยู่ในสถานะ degraded: {cache_key}",
                cache_key=cache_key,
                severity="medium",
                actual={
                    "payload_degraded": payload.get("degraded"),
                    "meta_degraded": meta.get("degraded"),
                },
                suggestion="ตรวจ upstream service ที่สร้าง cache นี้",
                meta={
                    "cache_meta": meta,
                },
            )
        )

    return issues


def check_cache_dependency_order(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []

    for upstream_key, downstream_key in POST_REBUILD_DEPENDENCY_ORDER:
        upstream_time = get_cache_created_at(upstream_key)
        downstream_time = get_cache_created_at(downstream_key)

        if upstream_time is None or downstream_time is None:
            continue

        if downstream_time >= upstream_time:
            continue

        issues.append(
            make_quality_issue(
                issue_type="cache_dependency_order_invalid",
                message=f"cache dependency order ผิด: {downstream_key} เก่ากว่า {upstream_key}",
                severity="medium",
                category="cache",
                source=downstream_key,
                field="created_at",
                expected=f"{downstream_key} >= {upstream_key}",
                actual={
                    "upstream": upstream_key,
                    "upstream_created_at": upstream_time.isoformat(timespec="seconds"),
                    "downstream": downstream_key,
                    "downstream_created_at": downstream_time.isoformat(timespec="seconds"),
                },
                suggestion="run staged rebuild ตาม phase order ใหม่",
            )
        )

    return issues

def check_map_readiness(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []

    companies = load_company_unified_records()
    valid_location_count = 0

    for record in companies[:5000]:
        lat, lon = get_lat_lon(record)

        if validate_coordinate(lat, lon).get("valid"):
            valid_location_count += 1

    if companies and valid_location_count == 0:
        issues.append(
            make_quality_issue(
                issue_type="map_no_valid_company_coordinates",
                message="No company records have valid map coordinates.",
                severity="high",
                category="map_readiness",
                source="company_unified_master",
                field="latitude/longitude",
            )
        )

    map_payload = read_cache("map_layers", default={})
    map_records = normalize_source_payload_to_records(map_payload, source_name="map_layers")

    if not map_records:
        issues.append(
            make_quality_issue(
                issue_type="map_layer_cache_missing",
                message="map_layers cache is missing or empty; map can degrade to dynamic layers.",
                severity="low",
                category="map_readiness",
                source="map_layers",
                field="cache",
            )
        )

    layers = map_payload.get("layers") if isinstance(map_payload, dict) else {}
    layer_ids = set(layers.keys()) if isinstance(layers, dict) else {
        clean_text(layer.get("layer_id"))
        for layer in layers
        if isinstance(layer, dict)
    } if isinstance(layers, list) else set()

    required_layers = {
        "rainfall",
        "waterlevel",
        "dam",
        "prediction",
        "entity",
        "company_points",
    }

    missing_layers = sorted(required_layers - layer_ids)

    if missing_layers and map_payload:
        issues.append(
            make_quality_issue(
                issue_type="map_required_layers_missing",
                message="merged map payload ขาด layer สำคัญ",
                severity="medium",
                category="map_readiness",
                source="map_layers",
                field="layers",
                expected=sorted(required_layers),
                actual=sorted(layer_ids),
                suggestion="ตรวจ map_graph_service.get_map_layers runtime definition ตัวท้าย",
                meta={
                    "missing_layers": missing_layers,
                },
            )
        )

    prediction_records = get_prediction_records_for_quality(context)
    entity_records = get_latest_entity_records_for_quality(context)

    if prediction_records and not any(to_bool(record.get("map_ready"), default=False) for record in prediction_records):
        issues.append(
            make_quality_issue(
                issue_type="prediction_layer_not_map_ready",
                message="มี prediction records แต่ไม่มี record ที่ map_ready",
                severity="medium",
                category="map_readiness",
                source="flood_prediction_latest",
                field="map_ready",
                actual=len(prediction_records),
                suggestion="ตรวจ location matching และ province fallback",
            )
        )

    if entity_records and not any(to_bool(record.get("is_displayable"), default=False) or to_bool(record.get("map_ready"), default=False) for record in entity_records):
        issues.append(
            make_quality_issue(
                issue_type="entity_layer_not_displayable",
                message="มี uploaded entity records แต่ไม่มี displayable/map_ready record",
                severity="medium",
                category="map_readiness",
                source="uploaded_entity_latest",
                field="is_displayable/map_ready",
                actual=len(entity_records),
                suggestion="ตรวจ entity_upload_service validation และ latitude/longitude",
            )
        )

    return issues

def check_package_readiness(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []

    if not load_company_unified_records():
        issues.append(
            make_quality_issue(
                issue_type="package_missing_company_master",
                message="Package export needs company_unified_master or a degraded empty snapshot.",
                severity="high",
                category="package_readiness",
                source="company_unified_master",
                field="cache",
            )
        )

    if not load_cache_records("dashboard_summary", "dashboard_summary"):
        issues.append(
            make_quality_issue(
                issue_type="package_dashboard_summary_missing",
                message="dashboard_summary cache is missing; package dashboard cards may degrade.",
                severity="low",
                category="package_readiness",
                source="dashboard_summary",
                field="cache",
            )
        )

    if not load_cache_records("map_layers", "map_layers"):
        issues.append(
            make_quality_issue(
                issue_type="package_map_layers_missing",
                message="map_layers cache is missing; public package map may degrade.",
                severity="medium",
                category="package_readiness",
                source="map_layers",
                field="cache",
            )
        )

    if not load_cache_records("flood_prediction_latest", "flood_prediction_latest"):
        issues.append(
            make_quality_issue(
                issue_type="package_prediction_component_empty",
                message="flood_prediction_latest cache is empty; package prediction component will be empty.",
                severity="low",
                category="package_readiness",
                source="flood_prediction_latest",
                field="cache",
            )
        )

    if not load_cache_records("uploaded_entity_latest", "uploaded_entity_latest"):
        issues.append(
            make_quality_issue(
                issue_type="package_entity_component_empty",
                message="uploaded_entity_latest cache is empty; package entity component will be empty.",
                severity="info",
                category="package_readiness",
                source="uploaded_entity_latest",
                field="cache",
            )
        )

    return issues


def check_frontend_readiness(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    required_facades = [
        "get_data_quality_summary",
        "get_tax_id_quality",
        "get_coordinate_quality",
        "get_policy_quality",
        "get_linkage_quality",
        "get_flood_quality",
        "get_spatial_join_quality",
        "get_policy_status_conflicts",
        "get_data_quality_issues",
        "get_company_quality_flags",
    ]
    for function_name in required_facades:
        if callable(globals().get(function_name)):
            continue
        issues.append(
            make_quality_issue(
                "frontend_quality_facade_missing",
                "Data quality frontend facade is missing.",
                "high",
                "frontend_readiness",
                "dashboard_summary",
                field=function_name,
            )
        )
    return issues


def build_quality_flags_by_company(issues: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    normalized = dedupe_issues(issues if issues is not None else build_all_data_quality_issues())
    flags_by_tax_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    summary_by_tax_id: Dict[str, Dict[str, int]] = {}
    for issue in normalized:
        tax_id = normalize_tax_id(issue.get("tax_id_norm") or issue.get("record_key")) or "__unknown__"
        if tax_id == "__unknown__" and not issue.get("tax_id_norm"):
            continue
        flag = {
            "severity": issue.get("severity"),
            "category": issue.get("category"),
            "issue_type": issue.get("issue_type"),
            "message": issue.get("message"),
            "field": issue.get("field"),
        }
        if flag not in flags_by_tax_id[tax_id]:
            flags_by_tax_id[tax_id].append(flag)
        summary = summary_by_tax_id.setdefault(tax_id, {severity: 0 for severity in SEVERITY_LEVELS} | {"total": 0})
        severity = normalize_severity(issue.get("severity"))
        summary[severity] += 1
        summary["total"] += 1
    return json_safe({"flags_by_tax_id": dict(flags_by_tax_id), "summary_by_tax_id": summary_by_tax_id})


def build_quality_flags_by_tax_id(issues: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[str]]:
    grouped = build_quality_flags_by_company(issues).get("flags_by_tax_id", {})
    return {
        tax_id: sorted({clean_text(flag.get("issue_type")) for flag in flags if clean_text(flag.get("issue_type"))})
        for tax_id, flags in grouped.items()
    }


def check_import_fallback_quality(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    checks = [
        ("bootstrap", globals().get("BOOTSTRAP_LOADED", True), globals().get("BOOTSTRAP_ERROR", "")),
        ("pandas", globals().get("PANDAS_LOADED", True), globals().get("PANDAS_ERROR", "")),
        ("config", globals().get("CONFIG_LOADED", True), globals().get("CONFIG_ERROR", "")),
        ("utils", globals().get("UTILS_LOADED", True), globals().get("UTILS_ERROR", "")),
        ("schemas", globals().get("SCHEMAS_LOADED", True), globals().get("SCHEMAS_ERROR", "")),
        ("config_column_mappings", globals().get("CONFIG_COLUMN_MAPPINGS_LOADED", True), globals().get("CONFIG_COLUMN_MAPPINGS_ERROR", "")),
    ]
    issues: List[Dict[str, Any]] = []
    for component, loaded, error in checks:
        if loaded:
            continue
        issues.append(
            make_quality_issue(
                issue_type="import_fallback_active",
                message=f"{component} import fallback is active.",
                severity="medium" if component in {"bootstrap", "pandas", "utils"} else "low",
                category="runtime",
                source="system",
                suggestion="Review the Python environment or missing optional config/schema dependency before production release.",
                actual={"component": component, "error": clean_text(error)},
                meta={"component": component},
            )
        )
    return issues

def build_all_data_quality_issues(
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    checker_plan = [
        (
            "import_fallbacks",
            check_import_fallback_quality,
        ),
        (
            "data_source_config",
            check_data_source_config,
        ),
        (
            "excel_source_paths",
            check_excel_source_paths,
        ),
        (
            "mysql_source_placeholder",
            check_mysql_source_placeholder,
        ),
        (
            "latest_excel_file",
            check_latest_excel_file,
        ),
        (
            "master_excel_file",
            check_master_excel_file,
        ),
        (
            "history_dir",
            check_history_dir,
        ),
        (
            "prediction_dir",
            check_prediction_dir,
        ),
        (
            "upload_dir",
            check_upload_dir,
        ),
        (
            "input_file",
            check_input_file_exists,
        ),
        (
            "policy",
            check_policy_quality,
        ),
        (
            "policy_status_conflicts",
            check_policy_status_conflicts,
        ),
        (
            "linkage",
            check_linkage_quality,
        ),
        (
            "flood",
            check_flood_quality,
        ),
        (
            "entity_latest_upload_exists",
            check_latest_entity_upload_exists,
        ),
        (
            "entity_displayable_count",
            check_entity_displayable_count,
        ),
        (
            "entity_not_displayable_count",
            check_entity_not_displayable_count,
        ),
        (
            "entity_invalid_coordinate_count",
            check_entity_invalid_coordinate_count,
        ),
        (
            "entity_error_report_exists",
            check_entity_error_report_exists,
        ),
        (
            "tax_id",
            check_tax_id_quality,
        ),
        (
            "coordinate",
            check_coordinate_quality,
        ),
        (
            "company_unified",
            check_company_unified_quality,
        ),
        (
            "spatial",
            check_spatial_join_quality_internal,
        ),
        (
            "map_readiness",
            check_map_readiness,
        ),
        (
            "package_readiness",
            check_package_readiness,
        ),
        (
            "frontend_readiness",
            check_frontend_readiness,
        ),
        (
            "cache_registry",
            check_cache_registry,
        ),
        (
            "missing_critical_cache",
            check_missing_critical_cache,
        ),
        (
            "stale_cache",
            check_stale_cache,
        ),
        (
            "degraded_cache",
            check_degraded_cache,
        ),
        (
            "cache_dependency_order",
            check_cache_dependency_order,
        ),
    ]

    issues: List[
        Dict[str, Any]
    ] = []

    for (
        checker_name,
        checker,
    ) in checker_plan:
        try:
            checker_issues = checker(
                context
            )

        except TypeError:
            try:
                checker_issues = checker()

            except Exception as exc:
                checker_issues = [
                    make_quality_issue(
                        issue_type=(
                            "checker_failed"
                        ),
                        message=(
                            safe_exception_message(
                                exc,
                                (
                                    f"{checker_name} "
                                    "failed."
                                ),
                            )
                        ),
                        severity="high",
                        category=(
                            "data_quality"
                        ),
                        source="unknown",
                        meta={
                            "checker": (
                                checker_name
                            ),
                            "exception_type": (
                                exc.__class__.__name__
                            ),
                        },
                    )
                ]

        except Exception as exc:
            checker_issues = [
                make_quality_issue(
                    issue_type=(
                        "checker_failed"
                    ),
                    message=(
                        safe_exception_message(
                            exc,
                            (
                                f"{checker_name} "
                                "failed."
                            ),
                        )
                    ),
                    severity="high",
                    category=(
                        "data_quality"
                    ),
                    source="unknown",
                    meta={
                        "checker": (
                            checker_name
                        ),
                        "exception_type": (
                            exc.__class__.__name__
                        ),
                    },
                )
            ]

        if isinstance(
            checker_issues,
            list,
        ):
            issues.extend(
                checker_issues
            )

        elif isinstance(
            checker_issues,
            dict,
        ):
            issues.extend(
                normalize_source_payload_to_records(
                    checker_issues,
                    source_name=(
                        checker_name
                    ),
                )
            )

    return dedupe_issues(issues)

def build_quality_by_source(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    return group_issues(issues, "source")


def build_quality_by_severity(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = group_issues(issues, "severity")
    return {severity: counts.get(severity, 0) for severity in SEVERITY_LEVELS}


def build_data_quality_cards(summary: Dict[str, Any], issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_category = summary.get("by_category", {})
    return [
        {"card_id": "overall_score", "label": "Overall Score", "value": summary.get("overall_score", 0), "severity": "info", "description": summary.get("overall_grade", "unknown")},
        {"card_id": "critical_issues", "label": "Critical Issues", "value": summary.get("critical_count", 0), "severity": "critical", "description": ""},
        {"card_id": "high_issues", "label": "High Issues", "value": summary.get("high_count", 0), "severity": "high", "description": ""},
        {"card_id": "tax_id_issues", "label": "Tax ID Issues", "value": by_category.get("tax_id", 0), "severity": "high", "description": ""},
        {"card_id": "coordinate_issues", "label": "Coordinate Issues", "value": by_category.get("coordinate", 0), "severity": "high", "description": ""},
        {"card_id": "policy_issues", "label": "Policy Issues", "value": by_category.get("policy", 0), "severity": "medium", "description": ""},
        {"card_id": "linkage_issues", "label": "Linkage Issues", "value": by_category.get("linkage", 0), "severity": "medium", "description": ""},
        {"card_id": "flood_issues", "label": "Flood Issues", "value": by_category.get("flood", 0), "severity": "medium", "description": ""},
        {"card_id": "spatial_join_issues", "label": "Spatial Join Issues", "value": by_category.get("spatial", 0), "severity": "medium", "description": ""},
        {"card_id": "map_readiness", "label": "Map Readiness", "value": by_category.get("map_readiness", 0), "severity": "low", "description": ""},
        {"card_id": "package_readiness", "label": "Package Readiness", "value": by_category.get("package_readiness", 0), "severity": "low", "description": ""},
    ]

def build_data_quality_summary(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)

    issues = build_all_data_quality_issues(
        ctx
    )

    source_record_count = (
        safe_len(
            load_company_unified_records()
        )
        + safe_len(
            load_policy_records()
        )
        + safe_len(
            load_linkage_records()
        )
        + safe_len(
            load_flood_records()
        )
        + safe_len(
            load_spatial_records()
        )
        + safe_len(
            get_prediction_records_for_quality(
                ctx
            )
        )
        + safe_len(
            get_latest_entity_records_for_quality(
                ctx
            )
        )
    )

    summary = summarize_issues_v2(
        issues,
        source_record_count=(
            source_record_count
        ),
    )

    cards = build_data_quality_cards(
        summary,
        issues,
    )

    flags = build_quality_flags_by_company(
        issues
    )

    readiness = {
        "source": {
            "checks": (
                SOURCE_READINESS_CHECKS
            ),
            "issue_count": sum(
                1
                for issue in issues
                if issue.get(
                    "issue_type"
                )
                in set(
                    SOURCE_READINESS_CHECKS
                )
            ),
        },
        "flood_prediction": {
            "checks": (
                FLOOD_PREDICTION_CHECKS
            ),
            "issue_count": sum(
                1
                for issue in issues
                if issue.get("source")
                in {
                    "flood_prediction_latest",
                    "flood_prediction_map",
                    "flood_output",
                    "flood_latest",
                }
            ),
        },
        "entity": {
            "checks": (
                ENTITY_UPLOAD_CHECKS
            ),
            "issue_count": sum(
                1
                for issue in issues
                if issue.get("source")
                == "uploaded_entity_latest"
            ),
        },
        "cache": {
            "checks": (
                CACHE_REGISTRY_CHECKS
            ),
            "issue_count": sum(
                1
                for issue in issues
                if issue.get("category")
                == "cache"
            ),
        },
        "map": {
            "issue_count": (
                summary.get(
                    "by_category",
                    {},
                ).get(
                    "map_readiness",
                    0,
                )
            ),
        },
        "package": {
            "issue_count": (
                summary.get(
                    "by_category",
                    {},
                ).get(
                    "package_readiness",
                    0,
                )
            ),
        },
        "frontend": {
            "issue_count": (
                summary.get(
                    "by_category",
                    {},
                ).get(
                    "frontend_readiness",
                    0,
                )
            ),
        },
    }

    cache_status: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for cache_key in (
        POST_REBUILD_CRITICAL_CACHE_KEYS
    ):
        created_at = get_cache_created_at(
            cache_key
        )

        cache_status[cache_key] = {
            "exists": path_exists(
                get_cache_file_path(
                    cache_key
                )
            ),
            "record_count": (
                cache_record_count(
                    cache_key
                )
            ),
            "created_at": (
                created_at.isoformat(
                    timespec="seconds"
                )
                if created_at
                else None
            ),
            "meta": get_cache_meta(
                cache_key
            ),
        }

    degraded = bool(
        summary.get(
            "degraded",
            False,
        )
        or any(
            issue.get("severity")
            in {
                "critical",
                "high",
            }
            for issue in issues
        )
    )

    return json_safe(
        {
            "summary": {
                **summary,
                "degraded": degraded,
                "status": (
                    "degraded"
                    if degraded
                    else "success"
                ),
            },
            "cards": cards,
            "issues": issues,
            "issue_count": len(issues),
            "by_source": (
                summary.get(
                    "by_source",
                    {},
                )
            ),
            "by_category": (
                summary.get(
                    "by_category",
                    {},
                )
            ),
            "by_severity": (
                summary.get(
                    "by_severity",
                    {},
                )
            ),
            "company_flags": flags,
            "readiness": readiness,
            "cache_status": cache_status,
            "input_file_status": (
                get_input_file_quality_status()
            ),
            "post_rebuild_validator": {
                "enabled": True,
                "phase": (
                    "after_dashboard_charts"
                ),
                "runs_after": [
                    "company_policy_enriched",
                    "linkage",
                    "flood_excel_base",
                    "spatial_prediction_entity",
                    "map",
                    "dashboard_charts",
                ],
                "does_not_require_existing_data_quality_cache": (
                    True
                ),
            },
            "meta": {
                "generated_at": now_iso(),
                "source_record_count": (
                    source_record_count
                ),
                "issue_count": len(
                    issues
                ),
                "degraded": degraded,
                "active_data_source": (
                    "excel"
                    if bool(
                        get_runtime_config_value(
                            "USE_EXCEL_DATA_SOURCE",
                            True,
                        )
                    )
                    else "mysql"
                ),
                "post_rebuild_validator": (
                    True
                ),
                "cache_keys_checked": (
                    POST_REBUILD_CRITICAL_CACHE_KEYS
                ),
            },
        }
    )

def filter_quality_issues(issues: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    ctx = normalize_context(context)
    filters = dict(ctx.get("filters", {}) or {})
    for key in ["severity", "category", "source", "issue_type", "tax_id_norm", "field"]:
        if key in ctx and ctx.get(key):
            filters[key] = ctx[key]
    search = clean_text_lower(ctx.get("search", ""))
    filtered = []
    for issue in issues or []:
        keep = True
        for key, expected in filters.items():
            if is_empty_value(expected):
                continue
            actual = clean_text_lower(issue.get(key))
            values = expected if isinstance(expected, list) else [expected]
            if actual not in {clean_text_lower(value) for value in values}:
                keep = False
                break
        if keep and search:
            haystack = " ".join(clean_text(issue.get(field)) for field in ["issue_id", "issue_type", "message", "source", "category", "field", "record_key", "company_name"])
            keep = search in haystack.lower()
        if keep:
            filtered.append(issue)
    return filtered


def paginate_quality_issues(issues: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = normalize_context(context)
    page = max(1, int(ctx.get("page", 1) or 1))
    page_size = max(1, min(500, int(ctx.get("page_size", ctx.get("limit", 50)) or 50)))
    filtered = filter_quality_issues(issues, ctx)
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size
    return {
        "issues": filtered[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": bool(total_pages and page < total_pages),
        "has_prev": bool(total_pages and page > 1),
    }


def response_for_issues(label: str, issues: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = dedupe_issues(issues)
    paginated = paginate_quality_issues(normalized, context)
    summary = summarize_issues_v2(normalized)
    data = {
        "summary": summary,
        "issues": paginated["issues"],
        "total": paginated["total"],
        "page": paginated["page"],
        "page_size": paginated["page_size"],
        "total_pages": paginated["total_pages"],
    }
    data.update(extra or {})
    return make_quality_response(
        data=data,
        message=f"{label} data quality loaded.",
        meta={"source_count": summary.get("source_count", 0), "issue_count": len(normalized), "degraded": summary.get("degraded", False)},
    )

def get_data_quality_summary(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)

    try:
        cache_result = get_or_build_cache(
            cache_key=(
                DATA_QUALITY_CACHE_KEY
            ),
            builder=lambda: (
                build_data_quality_summary(
                    {
                        **ctx,
                        "force_refresh": False,
                    }
                )
            ),
            ttl_seconds=(
                CACHE_TTL_SECONDS.get(
                    "data_quality",
                    900,
                )
                if isinstance(
                    CACHE_TTL_SECONDS,
                    dict,
                )
                else 900
            ),
            force_refresh=ctx.get(
                "force_refresh",
                False,
            ),
            source=(
                "data_quality."
                "get_data_quality_summary"
            ),
        )

        payload = dict(
            cache_result.get(
                "data"
            )
            or {}
        )

        all_issues = (
            payload.get(
                "issues",
                [],
            )
            if isinstance(
                payload.get(
                    "issues"
                ),
                list,
            )
            else []
        )

        paginated = (
            paginate_quality_issues(
                all_issues,
                ctx,
            )
        )

        payload["issues"] = (
            paginated["issues"]
        )
        payload["pagination"] = {
            "total": (
                paginated["total"]
            ),
            "page": (
                paginated["page"]
            ),
            "page_size": (
                paginated["page_size"]
            ),
            "total_pages": (
                paginated["total_pages"]
            ),
            "has_next": (
                paginated["has_next"]
            ),
            "has_prev": (
                paginated["has_prev"]
            ),
        }
        payload["cache_used"] = bool(
            cache_result.get(
                "cache_used",
                False,
            )
        )

        return make_quality_response(
            data=payload,
            message=(
                "Data quality summary "
                "loaded."
            ),
            meta={
                "source_count": (
                    payload.get(
                        "summary",
                        {},
                    ).get(
                        "source_count",
                        0,
                    )
                ),
                "issue_count": len(
                    all_issues
                ),
                "degraded": (
                    payload.get(
                        "summary",
                        {},
                    ).get(
                        "degraded",
                        False,
                    )
                ),
                "cache_used": (
                    payload[
                        "cache_used"
                    ]
                ),
            },
        )

    except Exception as exc:
        return make_quality_error(
            safe_exception_message(
                exc,
                (
                    "Data quality summary "
                    "could not be loaded."
                ),
            ),
            error_type=(
                exc.__class__.__name__
            ),
        )

def get_tax_id_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    issues = check_tax_id_quality(context)
    return response_for_issues(
        "Tax ID",
        issues,
        context,
        {
            "invalid_tax_id_count": sum(1 for issue in issues if issue.get("issue_type") == "invalid_tax_id_format"),
            "missing_tax_id_count": sum(1 for issue in issues if issue.get("issue_type") == "missing_tax_id"),
            "duplicate_tax_id_count": sum(1 for issue in issues if issue.get("issue_type") == "duplicate_key"),
            "join_loss_count": sum(1 for issue in issues if issue.get("issue_type") == "tax_id_join_loss"),
        },
    )


def get_coordinate_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    issues = check_coordinate_quality(context)
    return response_for_issues(
        "Coordinate",
        issues,
        context,
        {
            "missing_coordinate_count": sum(1 for issue in issues if issue.get("issue_type") == "missing_coordinate"),
            "invalid_coordinate_count": sum(1 for issue in issues if issue.get("issue_type") == "invalid_coordinate"),
            "zero_coordinate_count": sum(1 for issue in issues if issue.get("issue_type") == "zero_coordinate"),
            "outside_thailand_count": sum(1 for issue in issues if issue.get("issue_type") == "outside_thailand_coordinate"),
        },
    )


def get_policy_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    issues = check_policy_quality(context)
    conflicts = [issue for issue in check_policy_status_conflicts(context) if issue.get("issue_type") == "policy_status_conflict"]
    return response_for_issues("Policy", issues + conflicts, context, {"status_conflicts": conflicts, "financial_anomalies": [issue for issue in issues if issue.get("issue_type") == "invalid_policy_numeric"], "join_loss_count": 0})


def get_linkage_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    issues = check_linkage_quality(context)
    return response_for_issues("Linkage", issues, context, {"director_issue_count": sum(1 for issue in issues if "director" in issue.get("issue_type", "")), "edge_issue_count": sum(1 for issue in issues if "edge" in issue.get("issue_type", "")), "join_loss_count": sum(1 for issue in issues if "join_loss" in issue.get("issue_type", ""))})

def get_flood_quality(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    issues = check_flood_quality(
        context
    )

    prediction_records = (
        get_prediction_records_for_quality(
            context
        )
    )

    return response_for_issues(
        "Flood",
        issues,
        context,
        {
            "missing_source_count": sum(
                1
                for issue in issues
                if "missing"
                in issue.get(
                    "issue_type",
                    "",
                )
            ),
            "unknown_risk_count": sum(
                1
                for issue in issues
                if issue.get(
                    "issue_type"
                )
                == "unknown_risk_level"
            ),
            "invalid_coordinate_count": sum(
                1
                for issue in issues
                if "coordinate"
                in issue.get(
                    "issue_type",
                    "",
                )
            ),
            "prediction_record_count": (
                len(
                    prediction_records
                )
            ),
            "prediction_map_ready_count": sum(
                1
                for record
                in prediction_records
                if (
                    to_bool(
                        record.get(
                            "map_ready"
                        ),
                        default=False,
                    )
                    and validate_coordinate(
                        (
                            record.get(
                                "latitude"
                            )
                            if record.get(
                                "latitude"
                            )
                            is not None
                            else record.get(
                                "lat"
                            )
                        ),
                        (
                            record.get(
                                "longitude"
                            )
                            if record.get(
                                "longitude"
                            )
                            is not None
                            else record.get(
                                "lon"
                            )
                        ),
                    ).get("valid")
                )
            ),
        },
    )

def get_spatial_join_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    issues = check_spatial_join_quality_internal(context)
    return response_for_issues("Spatial join", issues, context, {"join_loss_count": sum(1 for issue in issues if "join_loss" in issue.get("issue_type", "")), "missing_context_count": sum(1 for issue in issues if "missing" in issue.get("issue_type", "")), "unknown_risk_count": sum(1 for issue in issues if "unknown" in issue.get("issue_type", ""))})


def get_policy_status_conflicts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    issues = check_policy_status_conflicts(context)
    conflicts = [
        {
            "tax_id_norm": issue.get("tax_id_norm"),
            "company_name": issue.get("company_name"),
            "issue_type": issue.get("issue_type"),
            "message": issue.get("message"),
            "severity": issue.get("severity"),
            **(issue.get("actual") if isinstance(issue.get("actual"), dict) else {}),
        }
        for issue in issues
    ]
    return response_for_issues("Policy status conflict", issues, context, {"conflicts": conflicts})

def get_data_quality_issues(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)

    cache_result = get_or_build_cache(
        cache_key=(
            DATA_QUALITY_CACHE_KEY
        ),
        builder=lambda: (
            build_data_quality_summary(
                {
                    **ctx,
                    "force_refresh": False,
                }
            )
        ),
        ttl_seconds=(
            CACHE_TTL_SECONDS.get(
                "data_quality",
                900,
            )
            if isinstance(
                CACHE_TTL_SECONDS,
                dict,
            )
            else 900
        ),
        force_refresh=ctx.get(
            "force_refresh",
            False,
        ),
        source=(
            "data_quality."
            "get_data_quality_issues"
        ),
    )

    payload = (
        cache_result.get(
            "data",
            {}
        )
        if isinstance(
            cache_result.get(
                "data"
            ),
            dict,
        )
        else {}
    )

    issues = (
        payload.get(
            "issues",
            [],
        )
        if isinstance(
            payload.get(
                "issues"
            ),
            list,
        )
        else []
    )

    paginated = paginate_quality_issues(
        issues,
        ctx,
    )

    return make_quality_response(
        data={
            "issues": (
                paginated["issues"]
            ),
            "total": (
                paginated["total"]
            ),
            "page": (
                paginated["page"]
            ),
            "page_size": (
                paginated["page_size"]
            ),
            "total_pages": (
                paginated[
                    "total_pages"
                ]
            ),
            "has_next": (
                paginated["has_next"]
            ),
            "has_prev": (
                paginated["has_prev"]
            ),
            "severity": (
                ctx.get("severity", "")
            ),
            "category": (
                ctx.get("category", "")
            ),
            "source": (
                ctx.get("source", "")
            ),
        },
        message=(
            "Data quality issues loaded."
        ),
        meta={
            "issue_count": len(
                issues
            ),
            "source_count": len(
                group_issues(
                    issues,
                    "source",
                )
            ),
            "cache_used": bool(
                cache_result.get(
                    "cache_used",
                    False,
                )
            ),
        },
    )

def get_company_quality_flags(context: Optional[Any] = None) -> Dict[str, Any]:
    if not isinstance(context, dict) and not is_empty_value(context):
        tax_id = normalize_tax_id(context)
        flags = build_quality_flags_by_tax_id().get(tax_id, [])
        return make_quality_response(data={"tax_id_norm": tax_id, "flags": flags}, message="Company quality flags loaded.", meta={"issue_count": len(flags)})
    issues = build_all_data_quality_issues(context if isinstance(context, dict) else None)
    flags = build_quality_flags_by_company(issues)
    return make_quality_response(data=flags, message="Company quality flags loaded.", meta={"issue_count": len(issues), "source_count": len(flags.get("flags_by_tax_id", {}))})

def get_admin_data_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_data_quality_summary(context)


def get_admin_errors(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    error_log_path = get_runtime_path("ERROR_LOG_PATH", None)
    records: List[Dict[str, Any]] = []

    if error_log_path and error_log_path.exists():
        try:
            lines = error_log_path.read_text(encoding="utf-8", errors="ignore").splitlines()

            for index, line in enumerate(lines[-500:]):
                records.append(
                    {
                        "row_number": index + 1,
                        "message": line,
                        "source": "error_log",
                        "severity": "high" if "ERROR" in line.upper() else "medium" if "WARNING" in line.upper() else "info",
                    }
                )

        except Exception as exc:
            return make_quality_error(
                message=f"อ่าน error log ไม่สำเร็จ: {exc}",
                error_type=exc.__class__.__name__,
                status_code=200,
                data={
                    "records": [],
                    "total": 0,
                },
            )

    return make_quality_response(
        data={
            "records": records,
            "total": len(records),
        },
        message="Admin errors loaded.",
        meta={
            "issue_count": len(records),
            "degraded": False,
            "source": "error_log",
        },
    )

def get_admin_scrape_runs(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    records = load_cache_records("scrape_runs")

    if not records:
        records = load_cache_records("flood_scrape_runs")

    if not records:
        records = load_cache_records("admin_scrape_runs")

    return make_quality_response(
        data={
            "records": records,
            "total": len(records),
            "source_candidates": [
                "scrape_runs",
                "flood_scrape_runs",
                "admin_scrape_runs",
            ],
        },
        message="Admin scrape runs loaded.",
        meta={
            "source_count": len(records),
            "degraded": False,
        },
    )

def get_error_log(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_admin_errors(context)


def get_scrape_runs(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_admin_scrape_runs(context)

def rebuild_data_quality_cache(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = normalize_context(context)

    payload = build_data_quality_summary(
        {
            **ctx,
            "force_refresh": True,
        }
    )

    issues = (
        payload.get(
            "issues",
            [],
        )
        if isinstance(
            payload.get(
                "issues"
            ),
            list,
        )
        else []
    )

    summary = (
        payload.get(
            "summary",
            {},
        )
        if isinstance(
            payload.get(
                "summary"
            ),
            dict,
        )
        else {}
    )

    ttl_seconds = (
        CACHE_TTL_SECONDS.get(
            "data_quality",
            900,
        )
        if isinstance(
            CACHE_TTL_SECONDS,
            dict,
        )
        else 900
    )

    write_result = write_cache(
        DATA_QUALITY_CACHE_KEY,
        payload,
        ttl_seconds=ttl_seconds,
        source=(
            "data_quality."
            "rebuild_data_quality_cache"
        ),
    )

    issues_write_result = write_cache(
        DATA_QUALITY_ISSUES_CACHE_KEY,
        issues,
        ttl_seconds=ttl_seconds,
        source=(
            "data_quality."
            "rebuild_data_quality_cache."
            "issues"
        ),
    )

    return make_quality_response(
        data={
            "rebuilt": True,
            "summary": summary,
            "issues": issues,
            "cache": write_result,
            "issues_cache": (
                issues_write_result
            ),
            "cache_keys": [
                DATA_QUALITY_CACHE_KEY,
                DATA_QUALITY_ISSUES_CACHE_KEY,
            ],
        },
        message=(
            "Data quality cache rebuilt."
        ),
        meta={
            "degraded": (
                summary.get(
                    "degraded",
                    False,
                )
            ),
            "issue_count": (
                summary.get(
                    "issue_count",
                    len(issues),
                )
            ),
            "cache_key": (
                DATA_QUALITY_CACHE_KEY
            ),
            "issues_cache_key": (
                DATA_QUALITY_ISSUES_CACHE_KEY
            ),
            "cache_used": False,
        },
    )

def get_data_quality_module_status() -> Dict[str, Any]:
    return {
        "module": "data_quality",
        "ready": True,
        "role": "post_rebuild_validator",
        "config_loaded": CONFIG_LOADED,
        "utils_loaded": UTILS_LOADED,
        "schemas_loaded": SCHEMAS_LOADED,
        "pandas_loaded": PANDAS_LOADED,
        "supported_checks": [
            *SOURCE_READINESS_CHECKS,
            "policy_quality",
            "linkage_quality",
            *FLOOD_PREDICTION_CHECKS,
            *ENTITY_UPLOAD_CHECKS,
            "company_unified_quality",
            "spatial_join_quality",
            "map_readiness",
            "package_readiness",
            "frontend_readiness",
            *CACHE_REGISTRY_CHECKS,
        ],
        "admin_contracts": [
            "get_admin_data_quality",
            "get_admin_errors",
            "get_admin_scrape_runs",
            "get_error_log",
            "get_scrape_runs",
        ],
        "cache_key": DATA_QUALITY_CACHE_KEY,
        "issues_cache_key": DATA_QUALITY_ISSUES_CACHE_KEY,
        "critical_cache_keys": POST_REBUILD_CRITICAL_CACHE_KEYS,
        "dependency_order": POST_REBUILD_DEPENDENCY_ORDER,
        "does_not_require_existing_data_quality_cache": True,
        "active_data_source": "excel" if bool(get_runtime_config_value("USE_EXCEL_DATA_SOURCE", True)) else "mysql",
        "mysql_placeholder_only": not bool(get_runtime_config_value("USE_MYSQL_DATA_SOURCE", False)),
        "checked_at": now_iso(),
    }

def run_data_quality_self_test() -> Dict[str, Any]:
    source_issues: List[Dict[str, Any]] = []
    source_issues.extend(check_data_source_config({}))
    source_issues.extend(check_excel_source_paths({}))
    source_issues.extend(check_mysql_source_placeholder({}))

    cache_issues: List[Dict[str, Any]] = []
    cache_issues.extend(check_missing_critical_cache({}))
    cache_issues.extend(check_degraded_cache({}))

    flood_issues = check_flood_quality({})
    entity_issues = []
    entity_issues.extend(check_latest_entity_upload_exists({}))
    entity_issues.extend(check_entity_displayable_count({}))
    entity_issues.extend(check_entity_invalid_coordinate_count({}))

    summary = summarize_issues_v2(source_issues + cache_issues + flood_issues + entity_issues)

    return {
        "module": "data_quality",
        "self_test": True,
        "status": get_data_quality_module_status(),
        "source_issues": source_issues,
        "cache_issues": cache_issues,
        "flood_issues": flood_issues,
        "entity_issues": entity_issues,
        "summary": summary,
        "contract_checks": {
            "admin_alias_get_error_log": callable(globals().get("get_error_log")),
            "admin_alias_get_scrape_runs": callable(globals().get("get_scrape_runs")),
            "dashboard_payload": callable(globals().get("get_data_quality_dashboard_payload")),
            "build_dashboard_payload_alias": callable(globals().get("build_data_quality_dashboard_payload")),
        },
        "checked_at": now_iso(),
    }

def get_data_quality_dashboard_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = get_data_quality_summary(context)
    data = response.get("data", {}) if isinstance(response, dict) else {}

    if not isinstance(data, dict):
        data = {}

    summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
    issues = data.get("issues", []) if isinstance(data.get("issues"), list) else []

    return json_safe(
        {
            **data,
            "summary_cards": data.get("cards", []),
            "charts": {
                "by_severity": {
                    "chart_id": "data_quality_by_severity",
                    "chart_type": "bar",
                    "title": "Data Quality by Severity",
                    "labels": list((summary.get("by_severity") or data.get("by_severity") or {}).keys()),
                    "datasets": [
                        {
                            "label": "Issues",
                            "data": list((summary.get("by_severity") or data.get("by_severity") or {}).values()),
                        }
                    ],
                },
                "by_category": {
                    "chart_id": "data_quality_by_category",
                    "chart_type": "bar",
                    "title": "Data Quality by Category",
                    "labels": list((summary.get("by_category") or data.get("by_category") or {}).keys()),
                    "datasets": [
                        {
                            "label": "Issues",
                            "data": list((summary.get("by_category") or data.get("by_category") or {}).values()),
                        }
                    ],
                },
            },
            "issues": issues,
            "module_status": get_data_quality_module_status(),
            "admin": {
                "data_quality_endpoint": "get_admin_data_quality",
                "errors_endpoint": "get_admin_errors",
                "scrape_runs_endpoint": "get_admin_scrape_runs",
                "errors_alias": "get_error_log",
                "scrape_runs_alias": "get_scrape_runs",
            },
            "meta": {
                **(data.get("meta") if isinstance(data.get("meta"), dict) else {}),
                "post_rebuild_validator": True,
                "generated_at": now_iso(),
                "degraded": summary.get("degraded", False),
            },
        }
    )

def build_data_quality_dashboard_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_data_quality_dashboard_payload(context)
