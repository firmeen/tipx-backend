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
try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

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

from config import (
    POLICY_FACT_COLUMNS,
    POLICY_LOCATION_COLUMNS,
    PROVINCE_BRANCH_COLUMNS,
    LINKAGE_COLUMNS,
)


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

def normalize_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    normalize context จาก api_routes.py

    context ใช้ควบคุม:
    - force_refresh
    - pagination
    - search
    - sort
    - filter
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

def check_input_file_exists() -> List[Dict[str, Any]]:
    """
    ตรวจว่าไฟล์ input หลักมีอยู่หรือไม่
    """

    issues: List[Dict[str, Any]] = []

    if not POLICY_INPUT_PATH.exists():
        issues.append(
            make_issue(
                code="policy_input_missing",
                message="ไม่พบไฟล์ Policy Input",
                category="input",
                severity="error",
                dataset="policy_input",
                field="file_path",
                value=str(POLICY_INPUT_PATH),
                suggestion="ตรวจสอบว่าไฟล์ policy_input.xlsx อยู่ใน input/policy/",
                source="file_system",
            )
        )

    if not LINKAGE_INPUT_PATH.exists():
        issues.append(
            make_issue(
                code="linkage_input_missing",
                message="ไม่พบไฟล์ Linkage Input",
                category="input",
                severity="error",
                dataset="linkage_input",
                field="file_path",
                value=str(LINKAGE_INPUT_PATH),
                suggestion="ตรวจสอบว่าไฟล์ linkage_input.xlsx อยู่ใน input/linkage/",
                source="file_system",
            )
        )

    if not FLOOD_OUTPUT_DIR.exists():
        issues.append(
            make_issue_from_rule(
                rule_code="flood_file_missing",
                dataset="flood_output",
                field="folder_path",
                value=str(FLOOD_OUTPUT_DIR),
                suggestion="ตรวจสอบ path C:/Users/afimeenu/project/flood/output_fl หรือกำหนด TIPX_FLOOD_OUTPUT_DIR",
                source="file_system",
            )
        )

    if not FLOOD_LATEST_DATABASE_PATH.exists():
        issues.append(
            make_issue_from_rule(
                rule_code="flood_file_missing",
                dataset="flood_latest",
                field="file_path",
                value=str(FLOOD_LATEST_DATABASE_PATH),
                suggestion="ตรวจสอบไฟล์ latest/latest_database.xlsx จาก flood pipeline",
                source="file_system",
            )
        )

    if not FLOOD_MASTER_DATABASE_PATH.exists():
        issues.append(
            make_issue_from_rule(
                rule_code="flood_file_missing",
                dataset="flood_master",
                field="file_path",
                value=str(FLOOD_MASTER_DATABASE_PATH),
                suggestion="ตรวจสอบไฟล์ master/master_database.xlsx จาก flood pipeline",
                source="file_system",
            )
        )

    return issues


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


def check_flood_quality() -> List[Dict[str, Any]]:
    """
    ตรวจคุณภาพ Flood Source ทั้งหมด
    """

    flood_latest = load_flood_latest_for_quality()

    issues: List[Dict[str, Any]] = []

    issues.extend(check_flood_sheet_structure(flood_latest))
    issues.extend(check_flood_freshness(flood_latest))
    issues.extend(check_flood_coordinate_quality(flood_latest))
    issues.extend(check_flood_history_quality())

    return issues


# ============================================================
# 9) COMPANY UNIFIED / CACHE QUALITY
# ============================================================

def load_cached_records(cache_key: str) -> List[Dict[str, Any]]:
    """
    โหลด records จาก cache ถ้ามี
    """

    path = get_cache_file_path(cache_key)

    if not path.exists():
        return []

    data = read_json(path, default={})

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


def check_company_unified_quality() -> List[Dict[str, Any]]:
    """
    ตรวจ company_unified_master จาก cache ถ้ามี

    ถ้ายังไม่มี cache จะไม่ถือว่า error
    เพราะไฟล์ service อาจยังไม่ได้ run
    """

    issues: List[Dict[str, Any]] = []

    records = load_cached_records("company_unified_master")

    if not records:
        issues.append(
            make_issue(
                code="company_unified_cache_missing",
                message="ยังไม่พบ company_unified_master cache",
                category="system",
                severity="info",
                dataset="company_unified_master",
                field="cache",
                suggestion="run company_policy_service เพื่อสร้าง company_unified_master",
                source="cache",
            )
        )
        return issues

    seen_tax_ids: Dict[str, int] = {}

    for record in records:
        tax_id_norm = normalize_tax_id(record.get("tax_id_norm") or record.get("tax_id"))
        company_name = clean_text(record.get("company_name"))

        if not tax_id_norm:
            issues.append(
                make_issue_from_rule(
                    rule_code="missing_tax_id",
                    dataset="company_unified_master",
                    field="tax_id_norm",
                    record_key="",
                    value=record.get("tax_id_norm"),
                    suggestion="ตรวจสอบขั้นตอน normalize tax id ใน company_policy_service",
                    source="cache",
                )
            )
        else:
            seen_tax_ids[tax_id_norm] = seen_tax_ids.get(tax_id_norm, 0) + 1

        if not company_name:
            issues.append(
                make_issue(
                    code="company_name_missing",
                    message="company_unified_master มีบริษัทที่ไม่มีชื่อ",
                    category="input",
                    severity="warning",
                    dataset="company_unified_master",
                    field="company_name",
                    record_key=tax_id_norm,
                    suggestion="ตรวจสอบ source priority ของ company_name",
                    source="cache",
                )
            )

        lat = record.get("lat")
        lon = record.get("lon")

        if not is_empty_value(lat) or not is_empty_value(lon):
            validation = validate_coordinate(lat, lon)

            if not validation["valid"]:
                issues.append(
                    make_issue_from_rule(
                        rule_code="invalid_coordinate",
                        dataset="company_unified_master",
                        field="lat/lon",
                        record_key=tax_id_norm,
                        value={
                            "lat": lat,
                            "lon": lon,
                        },
                        suggestion="ตรวจสอบ location_service หรือ fallback coordinate",
                        source="cache",
                        extra={
                            "issues": validation["issues"],
                        },
                    )
                )

    for tax_id, count in seen_tax_ids.items():
        if count > 1:
            issues.append(
                make_issue_from_rule(
                    rule_code="duplicate_tax_id",
                    dataset="company_unified_master",
                    field="tax_id_norm",
                    record_key=tax_id,
                    value=tax_id,
                    suggestion="company_unified_master ควรมี 1 แถวต่อ Tax ID",
                    source="cache",
                    extra={
                        "duplicate_count": count,
                    },
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
# 11) FULL DATA QUALITY PIPELINE
# ============================================================

def build_all_data_quality_issues() -> List[Dict[str, Any]]:
    """
    สร้าง issues ทั้งหมดของระบบ TIPX

    ลำดับการตรวจ:
    1. input file exists
    2. policy input
    3. linkage input
    4. flood source
    5. company unified cache
    6. spatial join cache
    """

    issues: List[Dict[str, Any]] = []

    issues.extend(check_input_file_exists())

    try:
        issues.extend(check_policy_input_quality())
    except Exception as exc:
        issues.append(
            make_issue(
                code="policy_quality_check_exception",
                message=f"เกิด error ระหว่างตรวจ Policy Input: {exc}",
                category="policy",
                severity="error",
                dataset="policy_input",
                suggestion="ตรวจ traceback ใน log และตรวจ format Excel",
                source="data_quality",
                extra={
                    "exception_type": exc.__class__.__name__,
                },
            )
        )

    try:
        issues.extend(check_linkage_input_quality())
    except Exception as exc:
        issues.append(
            make_issue(
                code="linkage_quality_check_exception",
                message=f"เกิด error ระหว่างตรวจ Linkage Input: {exc}",
                category="linkage",
                severity="error",
                dataset="linkage_input",
                suggestion="ตรวจ traceback ใน log และตรวจ format Excel",
                source="data_quality",
                extra={
                    "exception_type": exc.__class__.__name__,
                },
            )
        )

    try:
        issues.extend(check_flood_quality())
    except Exception as exc:
        issues.append(
            make_issue(
                code="flood_quality_check_exception",
                message=f"เกิด error ระหว่างตรวจ Flood Source: {exc}",
                category="flood",
                severity="error",
                dataset="flood",
                suggestion="ตรวจ path และ format ของ flood output",
                source="data_quality",
                extra={
                    "exception_type": exc.__class__.__name__,
                },
            )
        )

    try:
        issues.extend(check_company_unified_quality())
    except Exception as exc:
        issues.append(
            make_issue(
                code="company_unified_quality_check_exception",
                message=f"เกิด error ระหว่างตรวจ Company Unified Master: {exc}",
                category="system",
                severity="error",
                dataset="company_unified_master",
                suggestion="ตรวจ cache หรือ service ที่สร้าง company_unified_master",
                source="data_quality",
                extra={
                    "exception_type": exc.__class__.__name__,
                },
            )
        )

    try:
        issues.extend(check_spatial_join_quality_internal())
    except Exception as exc:
        issues.append(
            make_issue(
                code="spatial_join_quality_check_exception",
                message=f"เกิด error ระหว่างตรวจ Spatial Join: {exc}",
                category="spatial",
                severity="error",
                dataset="spatial_join_result",
                suggestion="ตรวจ flood_spatial_service และ cache spatial_join_result",
                source="data_quality",
                extra={
                    "exception_type": exc.__class__.__name__,
                },
            )
        )

    return deduplicate_issues(issues)


def build_data_quality_summary() -> Dict[str, Any]:
    """
    สร้าง data quality summary ทั้งระบบ
    """

    issues = build_all_data_quality_issues()
    summary = summarize_issues(issues)

    summary["input_file_status"] = get_input_file_quality_status()
    summary["module_status"] = {
        "policy_input_checked": POLICY_INPUT_PATH.exists(),
        "linkage_input_checked": LINKAGE_INPUT_PATH.exists(),
        "flood_output_checked": FLOOD_OUTPUT_DIR.exists(),
        "company_unified_cache_checked": True,
        "spatial_join_cache_checked": True,
    }

    return summary


def get_data_quality_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/data-quality/summary
    """

    ctx = normalize_context(context)

    cache_result = get_or_build_cache(
        cache_key=DATA_QUALITY_CACHE_KEY,
        builder=build_data_quality_summary,
        ttl_seconds=CACHE_TTL_SECONDS.get("data_quality", 900),
        force_refresh=ctx.get("force_refresh", False),
        source="data_quality.py",
    )

    summary = cache_result["data"]

    issues = summary.get("issues", [])
    paginated = apply_issue_context(issues, ctx)

    response_summary = dict(summary)
    response_summary["issues"] = paginated["records"]
    response_summary["pagination"] = {
        "total": paginated["total"],
        "page": paginated["page"],
        "page_size": paginated["page_size"],
        "total_pages": paginated["total_pages"],
        "has_next": paginated["has_next"],
        "has_prev": paginated["has_prev"],
    }
    response_summary["cache_used"] = cache_result["cache_used"]

    return response_summary


# ============================================================
# 12) API-SPECIFIC QUALITY FUNCTIONS
# ============================================================

def get_tax_id_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/data-quality/tax-id
    """

    summary = get_data_quality_summary(
        {
            **normalize_context(context),
            "force_refresh": normalize_context(context).get("force_refresh", False),
        }
    )

    all_issues = build_all_data_quality_issues()

    issues = [
        issue
        for issue in all_issues
        if issue.get("category") == "tax_id"
    ]

    paginated = apply_issue_context(issues, context)

    return {
        "summary": summarize_issues(issues),
        "issues": paginated["records"],
        "pagination": {
            "total": paginated["total"],
            "page": paginated["page"],
            "page_size": paginated["page_size"],
            "total_pages": paginated["total_pages"],
        },
    }


def get_coordinate_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/data-quality/coordinates
    """

    all_issues = build_all_data_quality_issues()

    issues = [
        issue
        for issue in all_issues
        if issue.get("category") in {"location", "spatial", "flood"}
        and (
            "coordinate" in clean_text_lower(issue.get("code"))
            or "lat" in clean_text_lower(issue.get("field"))
            or "lon" in clean_text_lower(issue.get("field"))
            or issue.get("code") in {"missing_coordinate", "invalid_coordinate"}
        )
    ]

    paginated = apply_issue_context(issues, context)

    return {
        "summary": summarize_issues(issues),
        "issues": paginated["records"],
        "pagination": {
            "total": paginated["total"],
            "page": paginated["page"],
            "page_size": paginated["page_size"],
            "total_pages": paginated["total_pages"],
        },
    }


def get_policy_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/data-quality/policy
    """

    all_issues = build_all_data_quality_issues()

    issues = [
        issue
        for issue in all_issues
        if issue.get("category") == "policy"
        or issue.get("dataset") in {"policy_fact", "policy_input"}
    ]

    paginated = apply_issue_context(issues, context)

    return {
        "summary": summarize_issues(issues),
        "issues": paginated["records"],
        "pagination": {
            "total": paginated["total"],
            "page": paginated["page"],
            "page_size": paginated["page_size"],
            "total_pages": paginated["total_pages"],
        },
    }


def get_linkage_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/data-quality/linkage
    """

    all_issues = build_all_data_quality_issues()

    issues = [
        issue
        for issue in all_issues
        if issue.get("category") == "linkage"
        or issue.get("dataset") in {"linkage_input", "director_master", "linkage_nodes", "linkage_edges"}
    ]

    paginated = apply_issue_context(issues, context)

    return {
        "summary": summarize_issues(issues),
        "issues": paginated["records"],
        "pagination": {
            "total": paginated["total"],
            "page": paginated["page"],
            "page_size": paginated["page_size"],
            "total_pages": paginated["total_pages"],
        },
    }


def get_spatial_join_quality(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/data-quality/spatial-join
    """

    all_issues = build_all_data_quality_issues()

    issues = [
        issue
        for issue in all_issues
        if issue.get("category") == "spatial"
        or issue.get("dataset") == "spatial_join_result"
    ]

    paginated = apply_issue_context(issues, context)

    return {
        "summary": summarize_issues(issues),
        "issues": paginated["records"],
        "pagination": {
            "total": paginated["total"],
            "page": paginated["page"],
            "page_size": paginated["page_size"],
            "total_pages": paginated["total_pages"],
        },
    }


def get_policy_status_conflicts(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API function:
    GET /api/data-quality/status-conflicts
    """

    all_issues = build_all_data_quality_issues()

    issues = [
        issue
        for issue in all_issues
        if issue.get("code") == "policy_status_conflict"
    ]

    paginated = apply_issue_context(issues, context)

    return {
        "records": paginated["records"],
        "total": paginated["total"],
        "page": paginated["page"],
        "page_size": paginated["page_size"],
        "summary": summarize_issues(issues),
    }


# ============================================================
# 13) DATA QUALITY FLAGS FOR COMPANY MASTER
# ============================================================

def build_quality_flags_by_tax_id(issues: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[str]]:
    """
    สร้าง mapping:
    tax_id_norm -> list quality flags

    ใช้ใน company_policy_service.py
    เพื่อเอาไปใส่ company_unified_master.data_quality_flags
    """

    if issues is None:
        issues = build_all_data_quality_issues()

    result: Dict[str, List[str]] = defaultdict(list)

    for issue in issues:
        record_key = normalize_tax_id(issue.get("record_key"))

        if not record_key:
            continue

        code = clean_text(issue.get("code"))

        if code and code not in result[record_key]:
            result[record_key].append(code)

    return dict(result)


def get_company_quality_flags(tax_id: Any) -> List[str]:
    """
    คืน quality flags ของบริษัทตาม tax_id
    """

    tax_id_norm = normalize_tax_id(tax_id)

    if not tax_id_norm:
        return ["missing_tax_id"]

    flags_by_tax = build_quality_flags_by_tax_id()

    return flags_by_tax.get(tax_id_norm, [])


# ============================================================
# 14) DASHBOARD PAYLOAD
# ============================================================

def build_data_quality_dashboard_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง payload สำหรับหน้า Data Quality Dashboard
    """

    summary = get_data_quality_summary(context)
    issues = summary.get("issues", [])

    by_severity = summary.get("by_severity", {})
    by_category = summary.get("by_category", {})
    by_dataset = summary.get("by_dataset", {})

    severity_chart = {
        "chart_id": "data_quality_by_severity",
        "chart_type": "bar",
        "title": "Data Quality Issues by Severity",
        "labels": list(by_severity.keys()),
        "datasets": [
            {
                "label": "Issues",
                "data": list(by_severity.values()),
            }
        ],
    }

    category_chart = {
        "chart_id": "data_quality_by_category",
        "chart_type": "bar",
        "title": "Data Quality Issues by Category",
        "labels": list(by_category.keys()),
        "datasets": [
            {
                "label": "Issues",
                "data": list(by_category.values()),
            }
        ],
    }

    dataset_chart = {
        "chart_id": "data_quality_by_dataset",
        "chart_type": "bar",
        "title": "Data Quality Issues by Dataset",
        "labels": list(by_dataset.keys()),
        "datasets": [
            {
                "label": "Issues",
                "data": list(by_dataset.values()),
            }
        ],
    }

    return {
        "summary_cards": [
            {
                "key": "quality_score",
                "label": "Quality Score",
                "value": summary.get("quality_score"),
                "display_value": f"{summary.get('quality_score')}%",
                "status": summary.get("quality_level"),
            },
            {
                "key": "total_issues",
                "label": "Total Issues",
                "value": summary.get("total_issues"),
                "display_value": str(summary.get("total_issues")),
                "status": "Warning" if summary.get("total_issues", 0) else "Normal",
            },
            {
                "key": "critical_issues",
                "label": "Critical",
                "value": by_severity.get("critical", 0),
                "display_value": str(by_severity.get("critical", 0)),
                "status": "Critical" if by_severity.get("critical", 0) else "Normal",
            },
            {
                "key": "error_issues",
                "label": "Errors",
                "value": by_severity.get("error", 0),
                "display_value": str(by_severity.get("error", 0)),
                "status": "Warning" if by_severity.get("error", 0) else "Normal",
            },
        ],
        "charts": {
            "severity": severity_chart,
            "category": category_chart,
            "dataset": dataset_chart,
        },
        "issues": issues,
        "pagination": summary.get("pagination", {}),
        "top_issues": summary.get("top_issues", []),
        "top_datasets": summary.get("top_datasets", []),
        "input_file_status": summary.get("input_file_status", {}),
        "generated_at": summary.get("generated_at"),
    }


# ============================================================
# 15) MODULE HEALTH
# ============================================================

def get_data_quality_module_status() -> Dict[str, Any]:
    """
    คืนสถานะ module data_quality.py
    """

    return {
        "module": "data_quality",
        "ready": True,
        "supported_checks": [
            "input_file_exists",
            "policy_sheet_structure",
            "policy_tax_id",
            "policy_numeric",
            "policy_status_conflict",
            "company_location_coordinate",
            "linkage_structure",
            "linkage_tax_id",
            "linkage_boardlist",
            "linkage_financial",
            "flood_sheet_structure",
            "flood_freshness",
            "flood_coordinate",
            "flood_history",
            "company_unified_cache",
            "spatial_join_cache",
        ],
        "cache_key": DATA_QUALITY_CACHE_KEY,
        "issues_cache_key": DATA_QUALITY_ISSUES_CACHE_KEY,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def run_data_quality_self_test() -> Dict[str, Any]:
    """
    self test เบื้องต้นสำหรับ data_quality.py
    """

    issues = check_input_file_exists()
    summary = summarize_issues(issues)

    return {
        "module": "data_quality",
        "self_test": True,
        "input_file_issues": issues,
        "summary": summary,
        "module_status": get_data_quality_module_status(),
    }