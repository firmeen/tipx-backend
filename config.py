# ============================================================
# FILE: backend/config.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 1 / 20
# ============================================================

"""
backend/config.py

ไฟล์นี้เป็นศูนย์กลางการตั้งค่าทั้งหมดของระบบ TIPX

หน้าที่หลัก:
1. กำหนดชื่อระบบ เวอร์ชัน และ environment
2. กำหนด path ของ project, input, cache, output, export, flood source
3. กำหนดชื่อไฟล์ input ของ Policy / Linkage
4. กำหนด path ของ Flood Output Folder เดิม
5. กำหนดชื่อ Sheet ของ Excel ทุกกลุ่ม
6. กำหนด schema column สำคัญที่ระบบต้องใช้
7. กำหนดค่า threshold สำหรับ Policy / Flood / Data Quality
8. กำหนดค่า cache TTL
9. กำหนดค่า API response, pagination, map, graph, package
10. เป็นไฟล์ config กลางที่ทุก service ใช้ร่วมกัน

โครงสร้างระบบที่ไฟล์นี้รองรับ:
- Flood Pipeline
- Policy Pipeline
- Linkage Pipeline
- Company Unified Master
- Flood Spatial Join
- OpenLayers Map Layer
- D3 Linkage Graph
- Filter Builder
- Data Quality
- Dashboard Summary
- Package Export
- External Viewer Package
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 1) PROJECT IDENTITY
# ============================================================

APP_NAME: str = "TIPX Enterprise Intelligence Dashboard"
APP_SHORT_NAME: str = "TIPX"
APP_VERSION: str = "1.0.0"
APP_DESCRIPTION: str = (
    "Enterprise Intelligence Dashboard for Company, Policy, Linkage, "
    "Flood Spatial Risk, Map, Graph, Filter Builder, and Package Export."
)

DEFAULT_ENV: str = os.getenv("TIPX_ENV", "development").strip().lower()
DEBUG: bool = os.getenv("TIPX_DEBUG", "false").strip().lower() in {"1", "true", "yes", "y"}
TESTING: bool = os.getenv("TIPX_TESTING", "false").strip().lower() in {"1", "true", "yes", "y"}

API_PREFIX: str = "/api"
PUBLIC_API_PREFIX: str = "/api/public"

DEFAULT_ENCODING: str = "utf-8"
DEFAULT_TIMEZONE: str = "Asia/Bangkok"

FLOOD_APP_NAME: str = "Flood Intelligence Dashboard API"
FLOOD_APP_DESCRIPTION: str = "Backend API contract for OpenLayers Flood Intelligence Dashboard."
FLOOD_MODULE_ENABLED: bool = os.getenv("TIPX_FLOOD_MODULE_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

USE_EXCEL_DATA_SOURCE: bool = os.getenv("TIPX_USE_EXCEL_DATA_SOURCE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

USE_MYSQL_DATA_SOURCE: bool = os.getenv("TIPX_USE_MYSQL_DATA_SOURCE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

DATA_SOURCE_EXCEL: str = "excel"
DATA_SOURCE_MYSQL: str = "mysql"
DATA_SOURCE_NOT_IMPLEMENTED_MESSAGE: str = (
    "MySQL data source is configured but not implemented yet. "
    "Set TIPX_USE_EXCEL_DATA_SOURCE=true and TIPX_USE_MYSQL_DATA_SOURCE=false."
)

# ============================================================
# 2) PROJECT ROOT AND MAIN PATHS
# ============================================================

BACKEND_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = BACKEND_DIR.parent

WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def is_windows_absolute_path(value: Any) -> bool:
    return bool(WINDOWS_ABSOLUTE_PATH_PATTERN.match(str(value or "").strip()))


def is_path_compatible_with_runtime(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if os.name != "nt" and is_windows_absolute_path(text):
        return False
    return True


def resolve_config_path(value: Any, base: Optional[Path] = None) -> Path:
    text = os.path.expandvars(str(value or "").strip())
    if not text:
        return Path(base or BACKEND_DIR)
    if os.name != "nt" and is_windows_absolute_path(text):
        return Path(text.replace("\\", "/"))
    path = Path(text).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    return path.resolve(strict=False)


def config_path_exists(value: Any) -> bool:
    if not is_path_compatible_with_runtime(value):
        return False
    try:
        return Path(value).exists()
    except OSError:
        return False

INPUT_DIR: Path = PROJECT_ROOT / "input"
CACHE_DIR: Path = PROJECT_ROOT / "cache"
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
LOG_DIR: Path = OUTPUT_DIR / "logs"
EXPORT_DIR: Path = OUTPUT_DIR / "exports"
PACKAGE_DIR: Path = EXPORT_DIR / "packages"
PACKAGE_ZIP_DIR: Path = EXPORT_DIR / "zip"
EXPORT_HISTORY_DIR: Path = EXPORT_DIR / "history"
DATA_QUALITY_OUTPUT_DIR: Path = OUTPUT_DIR / "data_quality"

POLICY_INPUT_DIR: Path = INPUT_DIR / "policy"
LINKAGE_INPUT_DIR: Path = INPUT_DIR / "linkage"

FRONTEND_DIR: Path = PROJECT_ROOT / "frontend"




# ============================================================
# 3) INPUT FILE PATHS
# ============================================================

POLICY_INPUT_FILENAME: str = os.getenv(
    "TIPX_POLICY_INPUT_FILENAME",
    "policy_input.xlsx",
).strip()

LINKAGE_INPUT_FILENAME: str = os.getenv(
    "TIPX_LINKAGE_INPUT_FILENAME",
    "linkage_input.xlsx",
).strip()

POLICY_INPUT_PATH: Path = POLICY_INPUT_DIR / POLICY_INPUT_FILENAME
LINKAGE_INPUT_PATH: Path = LINKAGE_INPUT_DIR / LINKAGE_INPUT_FILENAME


# ============================================================
# 4) FLOOD SOURCE PATH
# ============================================================

"""
Flood source เป็น output จาก flood pipeline เดิมของผู้ใช้

ตัวอย่าง path ที่ผู้ใช้ระบุ:
C:/Users/afimeenu/project/flood/output_fl

ระบบ TIPX จะไม่ scrape flood เองในไฟล์นี้
แต่จะอ่าน output ที่ flood project สร้างไว้แล้ว

โครงสร้างที่คาดหวัง:

output_fl/
├── latest/
│   └── latest_database.xlsx
├── master/
│   └── master_database.xlsx
└── history/
    ├── rainfall/
    ├── rain15d/
    ├── rain_yearly/
    ├── waterlevel/
    ├── dam/
    │   ├── large/
    │   └── medium/
    └── all_long/
"""

DEFAULT_FLOOD_PIPELINE_BASE_DIR: str = r"C:/Users/afimeenu/project/main"
DEFAULT_FLOOD_OUTPUT_DIR: str = r"C:/Users/afimeenu/project/main/output_flood"

FLOOD_PIPELINE_BASE_DIR: Path = resolve_config_path(
    os.getenv("TIPX_FLOOD_PIPELINE_BASE_DIR", DEFAULT_FLOOD_PIPELINE_BASE_DIR)
)

PIPELINE_BASE_DIR: Path = FLOOD_PIPELINE_BASE_DIR

FLOOD_OUTPUT_DIR: Path = resolve_config_path(
    os.getenv("TIPX_FLOOD_OUTPUT_DIR", DEFAULT_FLOOD_OUTPUT_DIR)
)

PIPELINE_OUTPUT_DIR: Path = resolve_config_path(
    os.getenv("TIPX_FLOOD_PIPELINE_OUTPUT_DIR", str(FLOOD_OUTPUT_DIR))
)

FLOOD_EXCEL_DATABASE_DIR: Path = resolve_config_path(
    os.getenv(
        "TIPX_FLOOD_EXCEL_DATABASE_DIR",
        str(PIPELINE_OUTPUT_DIR / "excel_database"),
    )
)

EXCEL_DATABASE_DIR: Path = FLOOD_EXCEL_DATABASE_DIR

FLOOD_MASTER_DIR: Path = resolve_config_path(
    os.getenv("TIPX_FLOOD_MASTER_DIR", str(FLOOD_EXCEL_DATABASE_DIR / "master"))
)
FLOOD_LATEST_DIR: Path = resolve_config_path(
    os.getenv("TIPX_FLOOD_LATEST_DIR", str(FLOOD_EXCEL_DATABASE_DIR / "latest"))
)
FLOOD_HISTORY_DIR: Path = resolve_config_path(
    os.getenv("TIPX_FLOOD_HISTORY_DIR", str(FLOOD_EXCEL_DATABASE_DIR / "history"))
)

MASTER_EXCEL_DIR: Path = FLOOD_MASTER_DIR
LATEST_EXCEL_DIR: Path = FLOOD_LATEST_DIR
HISTORY_EXCEL_DIR: Path = FLOOD_HISTORY_DIR

FLOOD_LATEST_DATABASE_PATH: Path = resolve_config_path(
    os.getenv(
        "TIPX_FLOOD_LATEST_DATABASE_PATH",
        str(FLOOD_LATEST_DIR / "latest_database.xlsx"),
    )
)
FLOOD_MASTER_DATABASE_PATH: Path = resolve_config_path(
    os.getenv(
        "TIPX_FLOOD_MASTER_DATABASE_PATH",
        str(FLOOD_MASTER_DIR / "master_database.xlsx"),
    )
)

LATEST_EXCEL_FILE: Path = FLOOD_LATEST_DATABASE_PATH
MASTER_EXCEL_FILE: Path = FLOOD_MASTER_DATABASE_PATH

FLOOD_HISTORY_RAINFALL_DIR: Path = FLOOD_HISTORY_DIR / "rainfall"
FLOOD_HISTORY_RAIN15D_DIR: Path = FLOOD_HISTORY_DIR / "rain15d"
FLOOD_HISTORY_RAIN_YEARLY_DIR: Path = FLOOD_HISTORY_DIR / "rain_yearly"
FLOOD_HISTORY_WATERLEVEL_DIR: Path = FLOOD_HISTORY_DIR / "waterlevel"
FLOOD_HISTORY_DAM_DIR: Path = FLOOD_HISTORY_DIR / "dam"
FLOOD_HISTORY_LARGE_DAM_DIR: Path = FLOOD_HISTORY_DIR / "large_dam"
FLOOD_HISTORY_MEDIUM_DAM_DIR: Path = FLOOD_HISTORY_DIR / "medium_dam"
FLOOD_HISTORY_ALL_LONG_DIR: Path = FLOOD_HISTORY_DIR / "all_long"

RAINFALL_HISTORY_DIR: Path = FLOOD_HISTORY_RAINFALL_DIR
RAIN15D_HISTORY_DIR: Path = FLOOD_HISTORY_RAIN15D_DIR
RAIN_YEARLY_HISTORY_DIR: Path = FLOOD_HISTORY_RAIN_YEARLY_DIR
WATERLEVEL_HISTORY_DIR: Path = FLOOD_HISTORY_WATERLEVEL_DIR
LARGE_DAM_HISTORY_DIR: Path = FLOOD_HISTORY_LARGE_DAM_DIR
MEDIUM_DAM_HISTORY_DIR: Path = FLOOD_HISTORY_MEDIUM_DAM_DIR
ALL_LONG_HISTORY_DIR: Path = FLOOD_HISTORY_ALL_LONG_DIR

FLOOD_PREDICTION_DIR: Path = resolve_config_path(
    os.getenv("TIPX_FLOOD_PREDICTION_DIR", str(FLOOD_PIPELINE_BASE_DIR / "predict"))
)

PREDICTION_DATA_DIR: Path = FLOOD_PREDICTION_DIR
PREDICTION_FILE_PREFIX: str = "predict"
PREDICTION_FILE_GLOB: str = "predict_[0-9][0-9][0-9][0-9]_[0-9][0-9]_[0-9][0-9].xlsx"
PREDICTION_FILE_PATTERN: str = "predict_YYYY_MM_DD.xlsx"
PREDICTION_FILE_EXAMPLE: str = "predict_2026_06_16.xlsx"

WEB_DATA_DIR: Path = PROJECT_ROOT / "web_data"
UPLOAD_DIR: Path = WEB_DATA_DIR / "uploads"
UPLOAD_ENTITY_DIR: Path = UPLOAD_DIR / "entities"
UPLOAD_LOG_DIR: Path = WEB_DATA_DIR / "upload_logs"
UPLOAD_ERROR_REPORT_DIR: Path = WEB_DATA_DIR / "upload_error_reports"
WEB_CACHE_DIR: Path = WEB_DATA_DIR / "cache"
WEB_LOG_DIR: Path = WEB_DATA_DIR / "logs"
ERROR_LOG_PATH: Path = LOG_DIR / "tipx_backend_error.log"


# ============================================================
# 5) OUTPUT / CACHE FILES
# ============================================================
CACHE_FILES: Dict[str, str] = {
    "system_status": "system_status.json",
    "input_status": "input_status.json",

    "policy_fact": "policy_fact.json",
    "policy_company_summary": "policy_company_summary.json",
    "policy_product_summary": "policy_product_summary.json",
    "policy_subclass_summary": "policy_subclass_summary.json",
    "policy_yearly_summary": "policy_yearly_summary.json",
    "policy_loss_ratio_summary": "policy_loss_ratio_summary.json",

    "company_location_master": "company_location_master.json",
    "province_branch_coordinate_master": "province_branch_coordinate_master.json",
    "company_unified_base": "company_unified_base.json",
    "company_unified_master": "company_unified_master.json",

    "director_master": "director_master.json",
    "director_company_pairs": "director_company_pairs.json",
    "linkage_nodes": "linkage_nodes.json",
    "linkage_edges": "linkage_edges.json",
    "shared_director_links": "shared_director_links.json",
    "key_connector_summary": "key_connector_summary.json",
    "linkage_company_summary": "linkage_company_summary.json",
    "linkage_graph_payload": "linkage_graph_payload.json",
    "linkage_graph": "linkage_graph_payload.json",
    "graph_payload": "linkage_graph_payload.json",

    "flood_latest": "flood_latest.json",
    "flood_master": "flood_master.json",
    "flood_rainfall_latest": "flood_rainfall_latest.json",
    "flood_waterlevel_latest": "flood_waterlevel_latest.json",
    "flood_large_dam_latest": "flood_large_dam_latest.json",
    "flood_medium_dam_latest": "flood_medium_dam_latest.json",
    "flood_all_long_latest": "flood_all_long_latest.json",
    "flood_prediction_files": "flood_prediction_files.json",
    "flood_prediction_latest": "flood_prediction_latest.json",
    "flood_prediction_summary": "flood_prediction_summary.json",
    "flood_prediction_map": "flood_prediction_map.json",
    "flood_prediction_location_debug": "flood_prediction_location_debug.json",
    "flood_computed_risk": "flood_computed_risk.json",
    "flood_summary": "flood_summary.json",

    "spatial_join_result": "spatial_join_result.json",
    "company_flood_context": "company_flood_context.json",
    "policy_flood_exposure": "policy_flood_exposure.json",
    "province_risk_summary": "province_risk_summary.json",
    "province_risk_exposure": "province_risk_exposure.json",

    "uploaded_entity_latest": "uploaded_entity_latest.json",
    "uploaded_entity_map": "uploaded_entity_map.json",

    "map_layers": "map_layers.json",
    "map_flood": "map_flood.json",
    "map_prediction": "map_prediction.json",
    "map_entity": "map_entity.json",
    "map_boundaries": "map_boundaries.json",
    "map_selected_context": "map_selected_context.json",

    "chart_payload": "chart_payload.json",
    "chart_summary": "chart_summary.json",
    "dashboard_summary": "dashboard_summary.json",
    "dashboard_overview": "dashboard_overview.json",
    "dashboard_province_insights": "dashboard_province_insights.json",

    "filter_fields": "filter_fields.json",
    "filter_presets": "filter_presets.json",

    "data_quality_summary": "data_quality_summary.json",
    "data_quality_issues": "data_quality_issues.json",

    "package_index": "package_index.json",
    "package_snapshot": "package_snapshot.json",
    "export_history": "export_history.json",
}


# ============================================================
# 6) EXCEL SHEET NAMES
# ============================================================

POLICY_SHEETS: Dict[str, str] = {
    "policy_fact": "policy_fact",
    "company_location": "company_location",
    "province_branch_coordinate": "province_branch_coordinate",
}

"""
หมายเหตุ:
ชื่อ sheet จริงของ policy input อาจไม่ตรงกับ key ด้านบน
service จะต้องมี fallback logic เช่น:
- ใช้ชื่อ sheet ลำดับที่ 1 เป็น policy_fact ถ้าหา exact name ไม่เจอ
- ใช้ชื่อ sheet ลำดับที่ 2 เป็น company_location
- ใช้ชื่อ sheet ลำดับที่ 3 เป็น province_branch_coordinate

เหตุผล:
ไฟล์ policy จริงอาจมีชื่อ sheet ภาษาไทยหรือชื่อที่ export จากระบบอื่น
"""

POLICY_SHEET_INDEX_FALLBACK: Dict[str, int] = {
    "policy_fact": 0,
    "company_location": 1,
    "province_branch_coordinate": 2,
}


LINKAGE_SHEET_INDEX_FALLBACK: int = 0


SHEET_META_INFO: str = "00_meta_info"
SHEET_SCRAPE_RUNS: str = "01_scrape_runs"
SHEET_RAINFALL_LATEST: str = "02_rainfall_latest"
SHEET_RAINFALL_DAILY_HISTORY: str = "03_rainfall_daily_history"
SHEET_RAINFALL_YEARLY_SUMMARY: str = "04_rainfall_yearly_summary"
SHEET_WATERLEVEL_LATEST: str = "05_waterlevel_latest"
SHEET_WATERLEVEL_HISTORY: str = "06_waterlevel_history_yearly"
SHEET_LARGE_DAM_LATEST: str = "07_large_dam_latest"
SHEET_LARGE_DAM_HISTORY: str = "08_large_dam_history_yearly"
SHEET_MEDIUM_DAM_LATEST: str = "09_medium_dam_latest"
SHEET_MEDIUM_DAM_HISTORY: str = "10_medium_dam_history_yearly"
SHEET_PROVINCE_BOUNDARY: str = "11_province_boundary"
SHEET_BASIN_BOUNDARY: str = "12_basin_boundary"
SHEET_RAINFALL_STATION_MASTER: str = "13_rainfall_station_master"
SHEET_WATERLEVEL_STATION_MASTER: str = "14_waterlevel_station_master"
SHEET_DAM_RESERVOIR_MASTER: str = "15_dam_reservoir_master"
SHEET_LOCATION_MASTER: str = "16_location_master"
SHEET_ALL_LONG: str = "17_all_long"
SHEET_ALL_LONG_LATEST: str = "17_all_long_latest"
SHEET_ENDPOINT_MASTER: str = "18_endpoint_master"
SHEET_DATA_QUALITY_LOG: str = "19_data_quality_log"
SHEET_ERROR_LOG: str = "20_error_log"
SHEET_RAW_FILE_INDEX: str = "21_raw_file_index"
SHEET_MOVE_LOG: str = "22_move_log"
SHEET_TELESTATION_LIST_MASTER: str = "23_telestation_list_master"
SHEET_DAILY_LOOP_RUNS: str = "24_daily_loop_runs"
SHEET_DAILY_LOOP_ROUNDS: str = "25_daily_loop_rounds"
SHEET_RAINFALL_15D_HISTORY: str = "26_rainfall_15d_history"
SHEET_GAP_DETECTION_LOG: str = "27_gap_detection_log"
SHEET_GAP_RECOVERY_RUNS: str = "28_gap_recovery_runs"
SHEET_FLOOD_PREDICTION_LATEST: str = "29_flood_prediction_latest"
SHEET_FLOOD_PREDICTION_HISTORY: str = "30_flood_prediction_history"

FLOOD_LATEST_SHEETS: Dict[str, str] = {
    "rainfall_latest": SHEET_RAINFALL_LATEST,
    "rainfall": SHEET_RAINFALL_LATEST,
    "rain_24h": SHEET_RAINFALL_LATEST,
    "waterlevel_latest": SHEET_WATERLEVEL_LATEST,
    "waterlevel": SHEET_WATERLEVEL_LATEST,
    "waterlevel_load": SHEET_WATERLEVEL_LATEST,
    "large_dam_latest": SHEET_LARGE_DAM_LATEST,
    "large_dam": SHEET_LARGE_DAM_LATEST,
    "medium_dam_latest": SHEET_MEDIUM_DAM_LATEST,
    "medium_dam": SHEET_MEDIUM_DAM_LATEST,
    "dam": SHEET_LARGE_DAM_LATEST,
    "all_long_latest": SHEET_ALL_LONG_LATEST,
    "all_long": SHEET_ALL_LONG_LATEST,
}

LATEST_SHEETS: Dict[str, str] = FLOOD_LATEST_SHEETS

FLOOD_MASTER_SHEETS: Dict[str, str] = {
    "meta": SHEET_META_INFO,
    "meta_info": SHEET_META_INFO,
    "scrape_runs": SHEET_SCRAPE_RUNS,
    "province_boundary": SHEET_PROVINCE_BOUNDARY,
    "basin_boundary": SHEET_BASIN_BOUNDARY,
    "rainfall_station_master": SHEET_RAINFALL_STATION_MASTER,
    "waterlevel_station_master": SHEET_WATERLEVEL_STATION_MASTER,
    "dam_reservoir_master": SHEET_DAM_RESERVOIR_MASTER,
    "location_master": SHEET_LOCATION_MASTER,
    "endpoint_master": SHEET_ENDPOINT_MASTER,
    "data_quality_log": SHEET_DATA_QUALITY_LOG,
    "error_log": SHEET_ERROR_LOG,
    "raw_file_index": SHEET_RAW_FILE_INDEX,
    "move_log": SHEET_MOVE_LOG,
    "telestation_list_master": SHEET_TELESTATION_LIST_MASTER,
    "daily_loop_runs": SHEET_DAILY_LOOP_RUNS,
    "daily_loop_rounds": SHEET_DAILY_LOOP_ROUNDS,
    "gap_detection_log": SHEET_GAP_DETECTION_LOG,
    "gap_recovery_runs": SHEET_GAP_RECOVERY_RUNS,
}

MASTER_SHEETS: Dict[str, str] = FLOOD_MASTER_SHEETS

FLOOD_HISTORY_SHEETS: Dict[str, str] = {
    "rainfall_daily_history": SHEET_RAINFALL_DAILY_HISTORY,
    "rainfall": SHEET_RAINFALL_DAILY_HISTORY,
    "rain": SHEET_RAINFALL_DAILY_HISTORY,
    "rainfall_daily": SHEET_RAINFALL_DAILY_HISTORY,
    "rain_monthly_graph": SHEET_RAINFALL_DAILY_HISTORY,

    "rain15d_history": SHEET_RAINFALL_15D_HISTORY,
    "rain15d": SHEET_RAINFALL_15D_HISTORY,
    "rain_15d": SHEET_RAINFALL_15D_HISTORY,
    "rainfall_15d": SHEET_RAINFALL_15D_HISTORY,

    "rain_yearly_summary": SHEET_RAINFALL_YEARLY_SUMMARY,
    "rain_yearly": SHEET_RAINFALL_YEARLY_SUMMARY,
    "rainfall_yearly": SHEET_RAINFALL_YEARLY_SUMMARY,
    "rain_yearly_graph": SHEET_RAINFALL_YEARLY_SUMMARY,

    "waterlevel_history_yearly": SHEET_WATERLEVEL_HISTORY,
    "waterlevel": SHEET_WATERLEVEL_HISTORY,
    "water": SHEET_WATERLEVEL_HISTORY,
    "waterlevel_history": SHEET_WATERLEVEL_HISTORY,
    "waterlevel_graph_year": SHEET_WATERLEVEL_HISTORY,

    "large_dam_history_yearly": SHEET_LARGE_DAM_HISTORY,
    "large_dam": SHEET_LARGE_DAM_HISTORY,
    "large-dam": SHEET_LARGE_DAM_HISTORY,
    "dam_large": SHEET_LARGE_DAM_HISTORY,
    "dam_yearly_graph": SHEET_LARGE_DAM_HISTORY,

    "medium_dam_history_yearly": SHEET_MEDIUM_DAM_HISTORY,
    "medium_dam": SHEET_MEDIUM_DAM_HISTORY,
    "medium-dam": SHEET_MEDIUM_DAM_HISTORY,
    "dam_medium": SHEET_MEDIUM_DAM_HISTORY,
    "dam_medium_graph": SHEET_MEDIUM_DAM_HISTORY,

    "all_long_history": SHEET_ALL_LONG,
    "all_long": SHEET_ALL_LONG,
    "all": SHEET_ALL_LONG,
    "all_long_latest": SHEET_ALL_LONG,
}

HISTORY_SHEETS: Dict[str, str] = FLOOD_HISTORY_SHEETS

HISTORY_DIRS: Dict[str, Path] = {
    "rainfall": RAINFALL_HISTORY_DIR,
    "rain": RAINFALL_HISTORY_DIR,
    "rainfall_daily": RAINFALL_HISTORY_DIR,
    "rain_monthly_graph": RAINFALL_HISTORY_DIR,

    "rain15d": RAIN15D_HISTORY_DIR,
    "rain_15d": RAIN15D_HISTORY_DIR,
    "rainfall_15d": RAIN15D_HISTORY_DIR,

    "rain_yearly": RAIN_YEARLY_HISTORY_DIR,
    "rainfall_yearly": RAIN_YEARLY_HISTORY_DIR,
    "rain_yearly_graph": RAIN_YEARLY_HISTORY_DIR,

    "waterlevel": WATERLEVEL_HISTORY_DIR,
    "water": WATERLEVEL_HISTORY_DIR,
    "waterlevel_history": WATERLEVEL_HISTORY_DIR,
    "waterlevel_graph_year": WATERLEVEL_HISTORY_DIR,

    "large_dam": LARGE_DAM_HISTORY_DIR,
    "large-dam": LARGE_DAM_HISTORY_DIR,
    "dam_large": LARGE_DAM_HISTORY_DIR,
    "dam_yearly_graph": LARGE_DAM_HISTORY_DIR,

    "medium_dam": MEDIUM_DAM_HISTORY_DIR,
    "medium-dam": MEDIUM_DAM_HISTORY_DIR,
    "dam_medium": MEDIUM_DAM_HISTORY_DIR,
    "dam_medium_graph": MEDIUM_DAM_HISTORY_DIR,

    "all_long": ALL_LONG_HISTORY_DIR,
    "all": ALL_LONG_HISTORY_DIR,
    "all_long_history": ALL_LONG_HISTORY_DIR,
}

HISTORY_FILE_PREFIXES: Dict[str, str] = {
    "rainfall": "rainfall",
    "rain": "rainfall",
    "rainfall_daily": "rainfall",
    "rain_monthly_graph": "rainfall",

    "rain15d": "rain15d",
    "rain_15d": "rain15d",
    "rainfall_15d": "rain15d",

    "rain_yearly": "rain_yearly",
    "rainfall_yearly": "rain_yearly",
    "rain_yearly_graph": "rain_yearly",

    "waterlevel": "waterlevel",
    "water": "waterlevel",
    "waterlevel_history": "waterlevel",
    "waterlevel_graph_year": "waterlevel",

    "large_dam": "large_dam",
    "large-dam": "large_dam",
    "dam_large": "large_dam",
    "dam_yearly_graph": "large_dam",

    "medium_dam": "medium_dam",
    "medium-dam": "medium_dam",
    "dam_medium": "medium_dam",
    "dam_medium_graph": "medium_dam",

    "all_long": "all_long",
    "all": "all_long",
    "all_long_history": "all_long",
}

# ============================================================
# 7) RAW INPUT COLUMN NAMES
# ============================================================

POLICY_FACT_COLUMNS: Dict[str, List[str]] = {
    "business_type": [
        "Business Type",
        "Business T",
        "business_type",
        "ประเภทธุรกิจ",
    ],

    "company_name": [
        "Company Name",
        "Company",
        "Company I",
        "Company I ",
        "company_name",
        "name",
        "Name",
        "ชื่อบริษัท",
        "ชื่อนิติบุคคล",
        "บริษัท",
    ],

    "income_range": [
        "Income Range",
        "Income Ra",
        "Income",
        "income_range",
        "รายได้",
        "ช่วงรายได้",
    ],

    "tax_id": [
        "Tax Id",
        "Tax ID",
        "TaxId",
        "tax_id",
        "taxid",
        "เลขประจำตัวผู้เสียภาษี",
        "เลขทะเบียนนิติบุคคล",
    ],

    "inforced_flag": [
        "Inforced Flag",
        "Inforced F",
        "Inforce Flag",
        "Inforce",
        "Inforced",
        "inforced_flag",
        "inforce_flag",
    ],

    "status_now": [
        "Status Now",
        "Status Nov",
        "Status",
        "status_now",
        "status",
        "สถานะ",
    ],

    "status_now_new": [
        "Status Now (New)",
        "status now (new)",
        "status_now_new",
        "Status New",
    ],

    "product": [
        "Product",
        "product",
        "ผลิตภัณฑ์",
    ],

    "product_holding_text": [
        "Product Holding",
        "Product Holding Province",
        "Product Holding ",
        "product_holding_text",
    ],

    "province": [
        "Province",
        "province",
        "จังหวัด",
    ],

    "subclass": [
        "Subclass",
        "Sub Class",
        "Sub-class",
        "subclass",
        "sub_class",
        "ประเภทภัย",
    ],

    "loss": [
        "Loss",
        "loss",
        "Claim",
        "Claim Amount",
        "ค่าสินไหม",
    ],

    "premium": [
        "Premium",
        "premium",
        "เบี้ย",
        "เบี้ยประกัน",
    ],

    "suminsure": [
        "Suminsure",
        "Sum Insure",
        "Sum Insured",
        "suminsure",
        "sum_insure",
        "ทุนประกัน",
    ],

    "noofpol": [
        "Noofpol",
        "No Of Pol",
        "No. of Pol",
        "noofpol",
        "no_of_pol",
        "จำนวนกรมธรรม์",
    ],

    "yearmonth_year_first": [
        "Yearmonth Year First",
        "yearmonth_year_first",
        "Year First",
        "policy_year",
        "Year",
        "ปี",
    ],

    "active_subs": [
        "Active Subs",
        "active_subs",
    ],

    "expired_subs": [
        "Expired Subs",
        "expired_subs",
    ],

    "product_holding": [
        "Product Holding Count",
        "product_holding",
    ],

    "subclass_holding": [
        "Subclass Holding",
        "subclass_holding",
    ],

    "most_recent_asset_val": [
        "most_recent_asset_val",
        "Most Recent Asset Val",
        "asset",
    ],

    "most_recent_income_val": [
        "most_recent_income_val",
        "Most Recent Income Val",
        "income",
    ],

    "registered_capital": [
        "registered_capital",
        "Registered Capital",
        "capital",
        "ทุนจดทะเบียน",
    ],
}


POLICY_LOCATION_COLUMNS: Dict[str, List[str]] = {
    "tax_id": [
        "Tax Id",
        "Tax ID",
        "TaxId",
        "tax_id",
        "เลขประจำตัวผู้เสียภาษี",
        "เลขทะเบียนนิติบุคคล",
    ],

    "name_th": [
        "Name Th",
        "Name TH",
        "name_th",
        "Company Name",
        "Company",
        "ชื่อบริษัท",
        "ชื่อนิติบุคคล",
    ],

    "address": [
        "Address",
        "address",
        "ที่อยู่",
    ],

    "province": [
        "Province",
        "province",
        "จังหวัด",
    ],

    "district": [
        "District",
        "district",
        "อำเภอ",
        "เขต",
    ],

    "subdistrict": [
        "Subdistrict",
        "Sub District",
        "subdistrict",
        "ตำบล",
        "แขวง",
    ],

    "lat": [
        "Latitude",
        "Lat",
        "lat",
        "latitude",
    ],

    "lon": [
        "Longitude",
        "Long",
        "Lon",
        "Lng",
        "lon",
        "lng",
        "longitude",
    ],

    "latlong_pair": [
        "latlong_pal",
        "latlong",
        "latlong_pair",
        "Lat Long",
        "Lat,Long",
        "Location Pair",
    ],

    "location_text": [
        "Location",
        "location",
    ],

    "toggle_url_section": [
        "Toggle URL Section",
        "toggle_url_section",
    ],

    "point_company": [
        "Point Company",
        "Point",
        "point_company",
    ],
}


PROVINCE_BRANCH_COLUMNS: Dict[str, List[str]] = {
    "province": [
        "จังหวัด",
        "Province",
        "province",
    ],

    "branch_name": [
        "ชื่อสาขา/ศูนย์1",
        "ชื่อสาขา/ศูนย์",
        "ชื่อสาขา",
        "สาขา",
        "Branch",
        "Branch Name",
        "branch_name",
    ],

    "subdistrict": [
        "ตำบล",
        "Subdistrict",
        "Sub District",
        "subdistrict",
    ],

    "region": [
        "ภาค",
        "Region",
        "region",
    ],

    "district": [
        "อำเภอ",
        "District",
        "district",
    ],

    "lat": [
        "Lat",
        "Latitude",
        "lat",
        "latitude",
    ],

    "lon": [
        "Long",
        "Longitude",
        "Lon",
        "Lng",
        "lon",
        "lng",
    ],
}


LINKAGE_COLUMNS: Dict[str, List[str]] = {
    "tax_id": [
        "tax_id",
        "Tax Id",
        "Tax ID",
        "TaxId",
        "taxid",
        "เลขประจำตัวผู้เสียภาษี",
    ],

    "name_th": [
        "name_th",
        "Name Th",
        "Name TH",
        "company_name",
        "Company Name",
        "ชื่อบริษัท",
        "ชื่อนิติบุคคล",
    ],

    "boardlist": [
        "boardlist",
        "Boardlist",
        "Board List",
        "กรรมการ",
        "รายชื่อกรรมการ",
    ],

    "business_type_objective": [
        "business_type_objective",
        "Business Type Objective",
        "objective",
        "วัตถุประสงค์",
    ],

    "most_recent_income_val": [
        "most_recent_income_val",
        "Most Recent Income Val",
        "income",
        "รายได้ล่าสุด",
    ],

    "registered_capital": [
        "registered_capital",
        "Registered Capital",
        "capital",
        "ทุนจดทะเบียน",
    ],

    "business_type_tsic": [
        "business_type_tsic",
        "Business Type TSIC",
        "TSIC",
        "tsic",
    ],

    "company_size": [
        "company_size",
        "Company Size",
        "size",
        "ขนาดธุรกิจ",
    ],

    "wtip": [
        "Wtip",
        "WTIP",
        "wtip",
    ],
}


# ============================================================
# 8) INTERNAL STANDARD FIELD NAMES
# ============================================================

STANDARD_COMPANY_FIELDS: List[str] = [
    "tax_id_raw",
    "tax_id_norm",
    "tax_id_valid",
    "tax_id_issue",

    "company_name",
    "company_name_policy",
    "company_name_linkage",
    "company_name_location",

    "business_type_objective",
    "business_type_tsic",
    "company_size",
    "wtip",

    "most_recent_asset_val",
    "most_recent_income_val",
    "registered_capital",

    "address",
    "province",
    "district",
    "subdistrict",
    "lat",
    "lon",
    "location_source",
    "location_quality",

    "has_policy",
    "has_linkage",
    "has_location",
    "has_flood_context",

    "total_premium",
    "total_loss",
    "total_suminsure",
    "total_noofpol",
    "active_policy_count",
    "expired_policy_count",
    "product_count",
    "subclass_count",
    "loss_ratio",
    "loss_ratio_band",

    "director_count",
    "shared_company_count",
    "key_connector_count",

    "flood_risk_level",
    "flood_join_level",
    "flood_risk_reason",

    "data_quality_flags",
]


STANDARD_POLICY_FACT_FIELDS: List[str] = [
    "source_file",
    "source_sheet",
    "source_row",

    "tax_id_raw",
    "tax_id_norm",
    "tax_id_valid",
    "tax_id_issue",

    "company_name",
    "product",
    "subclass",

    "inforced_flag",
    "status_now",
    "status_now_new",
    "policy_status",
    "is_active_policy",
    "is_expired_policy",
    "status_conflict_flag",

    "yearmonth_year_first",
    "policy_year",

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

    "loss_ratio_row",
    "loss_ratio_band",
]


STANDARD_LINKAGE_FIELDS: List[str] = [
    "tax_id_raw",
    "tax_id_norm",
    "tax_id_valid",
    "tax_id_issue",

    "company_name",
    "name_th",
    "boardlist",

    "business_type_objective",
    "business_type_tsic",
    "company_size",
    "wtip",

    "most_recent_income_val",
    "registered_capital",
]


STANDARD_DIRECTOR_FIELDS: List[str] = [
    "director_id",
    "director_name",
    "director_name_norm",
    "company_count",
    "company_list",
    "tax_id_list",
    "is_key_connector",
    "total_connected_income",
    "total_connected_capital",
    "total_connected_premium",
    "total_connected_suminsure",
    "connected_flood_risk_levels",
]

STANDARD_FLOOD_PREDICTION_FIELDS: List[str] = [
    "record_key",
    "source_file",
    "source_sheet",
    "source_row",
    "data_date",
    "base_date",
    "target_date",
    "forecast_horizon_day",
    "province",
    "province_model",
    "station_id",
    "station_code",
    "station_name",
    "station_name_th",
    "matched_station_id",
    "matched_station_code",
    "matched_station_name",
    "matched_source",
    "risk_level",
    "risk_status",
    "warning_level",
    "warning_level_predict",
    "predicted_level_m",
    "percent_to_bank",
    "from_bank_m",
    "latest_value",
    "latest_unit",
    "lat",
    "lon",
    "latitude",
    "longitude",
    "has_location",
    "map_ready",
    "focus_level",
    "focus_fallback_reason",
]

PREDICTION_REQUIRED_COLUMNS: List[str] = [
    "station_name",
    "province_model",
]

PREDICTION_SUPPORTED_COLUMNS: List[str] = [
    "data_date",
    "predict_date",
    "file_date",
    "base_date",
    "target_date",
    "forecast_horizon_day",
    "horizon",
    "province",
    "province_model",
    "station_id",
    "station_code",
    "station_name",
    "station_name_th",
    "warning_level",
    "warning_level_predict",
    "risk_level",
    "risk_status",
    "predicted_level_m",
    "actual_level_m",
    "percent_to_bank",
    "from_bank_m",
    "diff_from_bank_m",
    "depth_above_ground_m",
    "water_depth_above_bed_m",
]

PREDICTION_NUMERIC_COLUMNS: List[str] = [
    "forecast_horizon_day",
    "horizon",
    "predicted_level_m",
    "actual_level_m",
    "percent_to_bank",
    "from_bank_m",
    "diff_from_bank_m",
    "depth_above_ground_m",
    "water_depth_above_bed_m",
]

PREDICTION_DATE_COLUMNS: List[str] = [
    "data_date",
    "predict_date",
    "file_date",
    "base_date",
    "target_date",
]

PREDICTION_RISK_NORMALIZE_MAP: Dict[str, str] = {
    "normal": "Normal",
    "ปกติ": "Normal",
    "1.ปกติ": "Normal",
    "watch": "Watch",
    "เฝ้าระวัง": "Watch",
    "2.เฝ้าระวัง": "Watch",
    "warning": "Warning",
    "เตือนภัย": "Warning",
    "เตือน": "Warning",
    "3.เตือนภัย": "Warning",
    "critical": "Critical",
    "วิกฤต": "Critical",
    "4.วิกฤต": "Critical",
    "unknown": "Unknown",
    "ไม่ทราบ": "Unknown",
    "ไม่มีข้อมูล": "Unknown",
}

PREDICTION_QUERY_PARAM_ALIASES: Dict[str, List[str]] = {
    "data_date": [
        "data_date",
        "predict_date",
        "file_date",
        "prediction_data_date",
        "prediction_predict_date",
        "prediction_file_date",
    ],
    "province": [
        "province",
        "province_model",
        "prediction_province",
        "prediction_province_model",
    ],
    "risk_level": [
        "risk",
        "risk_level",
        "risk_status",
        "warning_level",
        "warning_level_predict",
        "prediction_risk_level",
        "prediction_risk_status",
        "prediction_warning_level",
        "prediction_warning_level_predict",
    ],
    "station": [
        "station",
        "station_name",
        "station_name_th",
        "station_id",
        "station_code",
        "matched_station_id",
        "matched_station_code",
        "matched_station_name",
        "prediction_station",
        "prediction_station_name",
        "prediction_station_name_th",
        "prediction_station_id",
        "prediction_station_code",
    ],
    "base_date": [
        "base_date",
        "prediction_base_date",
    ],
    "target_date": [
        "target_date",
        "prediction_target_date",
    ],
    "forecast_horizon_day": [
        "forecast_horizon_day",
        "horizon",
        "prediction_forecast_horizon_day",
        "prediction_horizon",
    ],
}

PREDICTION_RECORD_KEY_PARTS: List[str] = [
    "station_name",
    "station_id",
    "base_date",
    "target_date",
    "forecast_horizon_day",
]

PREDICTION_STATION_MATCH_COLUMNS: List[str] = [
    "station_id",
    "station_code",
    "station_name",
    "station_name_th",
    "matched_station_id",
    "matched_station_code",
    "matched_station_name",
]

PREDICTION_LOCATION_MASTER_SOURCES: List[str] = [
    "waterlevel_station_master",
    "rainfall_station_master",
]

UPLOAD_ALLOWED_EXTENSIONS: List[str] = [
    ".csv",
    ".xlsx",
    ".xls",
]

UPLOAD_MAX_CONTENT_LENGTH_MB: int = int(os.getenv("TIPX_UPLOAD_MAX_CONTENT_LENGTH_MB", "100"))

UPLOAD_CSV_ENCODING_CANDIDATES: List[str] = [
    "utf-8-sig",
    "utf-8",
    "cp874",
    "tis-620",
]

HIDDEN_EMPTY_VALUES: List[str] = [
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
]

ENTITY_REQUIRED_COLUMNS: List[str] = [
    "entity_id",
    "entity_type",
    "entity_name_th",
    "province_name_th",
    "latitude",
    "longitude",
]

ENTITY_SUPPORTED_COLUMNS: List[str] = [
    "entity_id",
    "entity_type",
    "entity_name_th",
    "entity_name_en",
    "province_name_th",
    "province_name_en",
    "district_name_th",
    "subdistrict_name_th",
    "latitude",
    "longitude",
    "risk_group",
    "description",
    "contact",
    "source",
    "note",
]


# ============================================================
# 9) RISK LEVELS AND COLORS
# ============================================================

RISK_LEVELS: List[str] = [
    "Normal",
    "Watch",
    "Warning",
    "Critical",
    "Unknown",
]

RISK_SCORE: Dict[str, int] = {
    "Normal": 0,
    "Watch": 1,
    "Warning": 2,
    "Critical": 3,
    "Unknown": -1,
}

RISK_COLORS: Dict[str, str] = {
    "Normal": "#22c55e",
    "Watch": "#eab308",
    "Warning": "#f97316",
    "Critical": "#ef4444",
    "Unknown": "#94a3b8",
}


LOSS_RATIO_BANDS: Dict[str, Dict[str, Any]] = {
    "Excellent": {
        "min": 0,
        "max": 30,
        "color": "#22c55e",
        "description": "Loss Ratio ต่ำมาก",
    },
    "Good": {
        "min": 30,
        "max": 60,
        "color": "#84cc16",
        "description": "Loss Ratio อยู่ในระดับดี",
    },
    "Watch": {
        "min": 60,
        "max": 80,
        "color": "#eab308",
        "description": "เริ่มควรติดตาม",
    },
    "Warning": {
        "min": 80,
        "max": 100,
        "color": "#f97316",
        "description": "ความเสียหายสูง",
    },
    "Critical": {
        "min": 100,
        "max": None,
        "color": "#ef4444",
        "description": "Loss มากกว่า Premium",
    },
    "Undefined": {
        "min": None,
        "max": None,
        "color": "#94a3b8",
        "description": "ไม่สามารถคำนวณได้",
    },
}


FLOOD_RAINFALL_THRESHOLDS_MM: Dict[str, float] = {
    "normal_max": 35.0,
    "watch_max": 70.0,
    "warning_max": 90.0,
    "critical_min": 90.0,
}


FLOOD_WATERLEVEL_THRESHOLDS: Dict[str, float] = {
    "watch_ratio": 0.80,
    "warning_ratio": 1.00,
    "critical_ratio": 1.10,
}


FLOOD_DAM_STORAGE_THRESHOLDS_PERCENT: Dict[str, float] = {
    "normal_max": 70.0,
    "watch_max": 80.0,
    "warning_max": 90.0,
    "critical_min": 90.0,
}


# ============================================================
# 10) POLICY STATUS RULES
# ============================================================

ACTIVE_POLICY_VALUES: List[str] = [
    "active",
    "inforce",
    "inforced",
    "inforced flag",
    "มีผลบังคับ",
    "ยังมีผล",
]

EXPIRED_POLICY_VALUES: List[str] = [
    "expired",
    "cancelled",
    "canceled",
    "inactive",
    "หมดอายุ",
    "ยกเลิก",
]

POLICY_ACTIVE_RULE: Dict[str, Any] = {
    "inforced_flag_should_equal": "Inforced",
    "status_now_new_should_equal": "Active",
    "logic": "AND",
    "description": (
        "ถือว่าเป็น active policy เมื่อ Inforced Flag = Inforced "
        "และ status now (new) = Active"
    ),
}


# ============================================================
# 11) LOCATION AND SPATIAL SETTINGS
# ============================================================

THAILAND_LAT_RANGE: Tuple[float, float] = (5.0, 21.5)
THAILAND_LON_RANGE: Tuple[float, float] = (97.0, 106.5)

DEFAULT_MAP_CENTER: Tuple[float, float] = (100.5018, 13.7563)
DEFAULT_MAP_ZOOM: int = 6
DEFAULT_MAP_MIN_ZOOM: int = 4
DEFAULT_MAP_MAX_ZOOM: int = 18

MAP_DEFAULT_CENTER: Tuple[float, float] = DEFAULT_MAP_CENTER
MAP_DEFAULT_ZOOM: int = DEFAULT_MAP_ZOOM
MAP_MIN_ZOOM: int = DEFAULT_MAP_MIN_ZOOM
MAP_MAX_ZOOM: int = DEFAULT_MAP_MAX_ZOOM
MAP_BASE_TILE_URL: str = "https://{a-c}.tile.openstreetmap.org/{z}/{x}/{y}.png"
MAP_BASE_ATTRIBUTION: str = "OpenStreetMap contributors"

DEFAULT_ACTIVE_LAYERS: List[str] = [
    "rainfall",
    "waterlevel",
    "dam",
    "prediction",
    "entity",
    "province_boundary",
    "basin_boundary",
]

SUPPORTED_LAYERS: List[str] = [
    "rainfall",
    "waterlevel",
    "large_dam",
    "medium_dam",
    "dam",
    "prediction",
    "forecast",
    "flood_prediction",
    "entity",
    "province_boundary",
    "basin_boundary",
    "province_boundaries",
    "basin_boundaries",
    "company_points",
    "flood_points",
    "policy_exposure",
    "linkage_lines",
    "branch_points",
    "heatmap",
    "cluster",
    "label",
]

LAYER_DISPLAY_NAMES: Dict[str, str] = {
    "rainfall": "Rain",
    "waterlevel": "Water Level",
    "large_dam": "Large Dam",
    "medium_dam": "Medium Dam",
    "dam": "Dam",
    "prediction": "Flood Prediction",
    "forecast": "Flood Prediction",
    "flood_prediction": "Flood Prediction",
    "entity": "Uploaded Entities",
    "province_boundary": "Province Boundary",
    "basin_boundary": "Basin Boundary",
    "province_boundaries": "Province Boundaries",
    "basin_boundaries": "Basin Boundaries",
    "company_points": "Company Points",
    "flood_points": "Flood Points",
    "policy_exposure": "Policy Exposure",
    "linkage_lines": "Linkage Lines",
    "branch_points": "Branch Points",
    "heatmap": "Flood Risk Heatmap",
}

MAP_LAYER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "province_boundary": {
        "layer_name": "Province Boundary",
        "visible": True,
        "opacity": 0.45,
        "z_index": 0,
    },
    "basin_boundary": {
        "layer_name": "Basin Boundary",
        "visible": False,
        "opacity": 0.45,
        "z_index": 1,
    },
    "province_boundaries": {
        "layer_name": "Province Boundaries",
        "visible": True,
        "opacity": 0.45,
        "z_index": 0,
    },
    "basin_boundaries": {
        "layer_name": "Basin Boundaries",
        "visible": False,
        "opacity": 0.45,
        "z_index": 1,
    },
    "heatmap": {
        "layer_name": "Flood Risk Heatmap",
        "visible": False,
        "opacity": 0.65,
        "z_index": 2,
    },
    "rainfall": {
        "layer_name": "Rain",
        "visible": True,
        "opacity": 0.9,
        "z_index": 3,
    },
    "waterlevel": {
        "layer_name": "Water Level",
        "visible": True,
        "opacity": 0.9,
        "z_index": 4,
    },
    "dam": {
        "layer_name": "Dam",
        "visible": True,
        "opacity": 0.9,
        "z_index": 5,
    },
    "prediction": {
        "layer_name": "Flood Prediction",
        "visible": True,
        "opacity": 0.95,
        "z_index": 6,
    },
    "entity": {
        "layer_name": "Uploaded Entities",
        "visible": True,
        "opacity": 0.95,
        "z_index": 7,
    },
    "flood_points": {
        "layer_name": "Flood Points",
        "visible": True,
        "opacity": 0.85,
        "z_index": 8,
    },
    "policy_exposure": {
        "layer_name": "Policy Exposure",
        "visible": True,
        "opacity": 0.9,
        "z_index": 9,
    },
    "company_points": {
        "layer_name": "Company Points",
        "visible": True,
        "opacity": 1.0,
        "z_index": 10,
    },
    "branch_points": {
        "layer_name": "Branch Points",
        "visible": True,
        "opacity": 0.9,
        "z_index": 11,
    },
    "linkage_lines": {
        "layer_name": "Linkage Lines",
        "visible": False,
        "opacity": 0.65,
        "z_index": 12,
    },
}

LOCATION_QUALITY_LEVELS: List[str] = [
    "exact_company_location",
    "approximate_branch_or_province",
    "invalid_coordinate",
    "missing_coordinate",
]

LOCATION_SOURCE_PRIORITY: List[str] = [
    "policy_sheet_2_exact",
    "policy_sheet_3_branch",
    "policy_sheet_3_province",
    "missing",
]

SPATIAL_JOIN_LEVELS: List[str] = [
    "coordinate",
    "province",
    "branch_approx",
    "none",
]

NEAREST_STATION_MAX_DISTANCE_KM: float = 100.0
NEAREST_DAM_MAX_DISTANCE_KM: float = 150.0
SPATIAL_NEAREST_STATION_LIMIT_KM: float = NEAREST_STATION_MAX_DISTANCE_KM
SPATIAL_COMPANY_FLOOD_RADIUS_KM: float = 50.0


# ============================================================
# 12) LINKAGE GRAPH SETTINGS
# ============================================================

BOARDLIST_SPLIT_PATTERN: str = r"[,;\n\r|]+"

DIRECTOR_ID_PREFIX: str = "director"
COMPANY_NODE_PREFIX: str = "company"
DIRECTOR_NODE_PREFIX: str = "director"

EDGE_TYPE_DIRECTOR_OF: str = "DIRECTOR_OF"
EDGE_TYPE_SHARED_DIRECTOR: str = "SHARED_DIRECTOR"

KEY_CONNECTOR_MIN_COMPANY_COUNT: int = 2

GRAPH_DEFAULT_MODE: str = "ego"
GRAPH_DEFAULT_DEPTH: int = 1
GRAPH_DEFAULT_MAX_NODES: int = 300
GRAPH_HARD_MAX_NODES: int = 1500
GRAPH_DEFAULT_MAX_EDGES: int = 3000

GRAPH_NODE_TYPES: Dict[str, str] = {
    "company": "company",
    "director": "director",
}

GRAPH_EDGE_TYPES: Dict[str, str] = {
    "director_of": EDGE_TYPE_DIRECTOR_OF,
    "shared_director": EDGE_TYPE_SHARED_DIRECTOR,
}

GRAPH_COLORS: Dict[str, str] = {
    "company": "#60A5FA",
    "director": "#FBBF24",
    "person": "#FBBF24",
    "key_connector": "#F97316",
    "policy": "#A78BFA",
    "linkage": "#38BDF8",
    "edge": "#64748B",
    "shared_director": "#94A3B8",
    "normal": "#22C55E",
    "watch": "#EAB308",
    "warning": "#F97316",
    "critical": "#EF4444",
    "unknown": "#94A3B8",
    "low": "#22C55E",
    "medium": "#EAB308",
    "high": "#F97316",
}


# ============================================================
# 13) DASHBOARD SETTINGS
# ============================================================

DASHBOARD_DEFAULT_PAGE: str = "executive"

DASHBOARD_PAGES: List[str] = [
    "executive",
    "company",
    "policy",
    "linkage",
    "flood",
    "map",
    "filter_builder",
    "package_builder",
    "export_history",
    "data_quality",
    "external_viewer",
]

SUMMARY_CARD_KEYS: List[str] = [
    "total_companies",
    "companies_with_policy",
    "companies_with_linkage",
    "companies_with_location",
    "companies_with_flood_context",
    "total_premium",
    "total_loss",
    "total_suminsure",
    "average_loss_ratio",
    "high_loss_company_count",
    "flood_risk_company_count",
    "key_connector_count",
    "data_quality_warning_count",
]

DEFAULT_TABLE_PAGE_SIZE: int = 50
MAX_TABLE_PAGE_SIZE: int = 500
DEFAULT_SEARCH_DEBOUNCE_MS: int = 350


# ============================================================
# 14) FILTER BUILDER SETTINGS
# ============================================================

FILTER_OPERATORS: List[str] = [
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "is_empty",
    "is_not_empty",
]

FILTER_LOGICAL_OPERATORS: List[str] = [
    "AND",
    "OR",
]

FILTERABLE_FIELDS: Dict[str, List[str]] = {
    "company": [
        "tax_id_norm",
        "company_name",
        "province",
        "district",
        "subdistrict",
        "business_type_tsic",
        "company_size",
        "wtip",
        "most_recent_income_val",
        "registered_capital",
        "has_policy",
        "has_linkage",
        "has_location",
        "has_flood_context",
        "loss_ratio_band",
        "flood_risk_level",
    ],
    "policy": [
        "product",
        "subclass",
        "policy_status",
        "is_active_policy",
        "policy_year",
        "premium",
        "loss",
        "suminsure",
        "noofpol",
        "loss_ratio_band",
    ],
    "linkage": [
        "director_id",
        "director_name",
        "company_count",
        "is_key_connector",
    ],
    "flood": [
        "province",
        "basin",
        "risk_level",
        "source_type",
    ],
}


QUICK_FILTER_PRESETS: Dict[str, Dict[str, Any]] = {
    "high_policy_exposure": {
        "label": "High Policy Exposure",
        "description": "บริษัทที่มีทุนประกันหรือเบี้ยประกันสูง",
        "target": "company",
        "conditions": [
            {"field": "total_suminsure", "operator": "gte", "value": 1_000_000}
        ],
    },
    "high_loss_ratio": {
        "label": "High Loss Ratio",
        "description": "บริษัทที่มี Loss Ratio สูง",
        "target": "company",
        "conditions": [
            {"field": "loss_ratio", "operator": "gte", "value": 80}
        ],
    },
    "wtip_companies": {
        "label": "WTIP Companies",
        "description": "บริษัทที่มี WTIP",
        "target": "company",
        "conditions": [
            {"field": "wtip", "operator": "is_not_empty", "value": None}
        ],
    },
    "companies_in_flood_risk_area": {
        "label": "Companies in Flood Risk Area",
        "description": "บริษัทที่อยู่ในพื้นที่ Watch / Warning / Critical",
        "target": "company",
        "conditions": [
            {
                "field": "flood_risk_level",
                "operator": "in",
                "value": ["Watch", "Warning", "Critical"],
            }
        ],
    },
    "key_connectors": {
        "label": "Key Connectors",
        "description": "กรรมการที่เชื่อมหลายบริษัท",
        "target": "linkage",
        "conditions": [
            {"field": "is_key_connector", "operator": "equals", "value": True}
        ],
    },
    "missing_location": {
        "label": "Missing Location",
        "description": "บริษัทที่ไม่มีพิกัด",
        "target": "company",
        "conditions": [
            {"field": "has_location", "operator": "equals", "value": False}
        ],
    },
}


# ============================================================
# 15) PACKAGE EXPORT SETTINGS
# ============================================================

PACKAGE_ID_PREFIX: str = "PKG"
PACKAGE_DATETIME_FORMAT: str = "%Y%m%d_%H%M%S"

PACKAGE_DEFAULT_EXPIRE_DAYS: int = 30
PACKAGE_MAX_EXPIRE_DAYS: int = 365

PACKAGE_COMPONENTS: List[str] = [
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

PACKAGE_SECURITY_OPTIONS: Dict[str, bool] = {
    "mask_tax_id": True,
    "mask_director_name": False,
    "mask_address": True,
    "hide_financial_fields": False,
    "allow_external_filter": True,
    "include_data_quality": True,
}

# ============================================================
# PACKAGE FILE SETTINGS
# ============================================================

PACKAGE_INDEX_FILENAME: str = "package_index.json"
PACKAGE_META_FILENAME: str = "package_meta.json"
PACKAGE_SNAPSHOT_FILENAME: str = "package_snapshot.json"
PACKAGE_PUBLIC_DATA_FILENAME: str = "public_data.json"
PACKAGE_EXPORT_DIRNAME: str = "exports"
PACKAGE_EXTERNAL_VIEWER_DIRNAME: str = "external_viewer"
PACKAGE_ACCESS_LOG_FILENAME: str = "access_log.jsonl"

PACKAGE_REQUIRED_FILES: List[str] = [
    "package_meta.json",
    "data/summary.json",
    "data/companies.json",
    "data/map_layers.json",
    "data/charts.json",
    "data/tables.json",
    "data/filter_options.json",
]


# ============================================================
# 16) DATA QUALITY SETTINGS
# ============================================================

DATA_QUALITY_SEVERITIES: List[str] = [
    "info",
    "warning",
    "error",
    "critical",
]

DATA_QUALITY_CATEGORIES: List[str] = [
    "input",
    "tax_id",
    "policy",
    "linkage",
    "location",
    "flood",
    "spatial",
    "map",
    "graph",
    "package",
    "system",
]

DATA_QUALITY_RULES: Dict[str, Dict[str, Any]] = {
    "missing_tax_id": {
        "category": "tax_id",
        "severity": "error",
        "description": "ไม่พบ Tax ID",
    },
    "invalid_tax_id": {
        "category": "tax_id",
        "severity": "warning",
        "description": "Tax ID ไม่ถูกต้องหรือไม่ได้ 13 หลัก",
    },
    "duplicate_tax_id": {
        "category": "tax_id",
        "severity": "warning",
        "description": "พบ Tax ID ซ้ำ",
    },
    "premium_zero_with_loss": {
        "category": "policy",
        "severity": "warning",
        "description": "Premium เป็น 0 แต่มี Loss",
    },
    "policy_status_conflict": {
        "category": "policy",
        "severity": "warning",
        "description": "สถานะกรมธรรม์ขัดแย้งกัน",
    },
    "empty_boardlist": {
        "category": "linkage",
        "severity": "info",
        "description": "ไม่มีข้อมูลกรรมการ",
    },
    "missing_coordinate": {
        "category": "location",
        "severity": "warning",
        "description": "ไม่มีพิกัดบริษัท",
    },
    "invalid_coordinate": {
        "category": "location",
        "severity": "error",
        "description": "พิกัดไม่ถูกต้อง",
    },
    "flood_file_missing": {
        "category": "flood",
        "severity": "error",
        "description": "ไม่พบไฟล์ Flood Source",
    },
    "flood_data_stale": {
        "category": "flood",
        "severity": "warning",
        "description": "ข้อมูล Flood ไม่ใช่ข้อมูลล่าสุด",
    },
    "spatial_join_failed": {
        "category": "spatial",
        "severity": "warning",
        "description": "ไม่สามารถเชื่อมบริษัทกับ Flood Context ได้",
    },
    "package_missing_file": {
        "category": "package",
        "severity": "error",
        "description": "Package มีไฟล์ไม่ครบ",
    },
}


# ============================================================
# 17) CACHE SETTINGS
# ============================================================

CACHE_ENABLED: bool = os.getenv("TIPX_CACHE_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

CACHE_TTL_SECONDS: Dict[str, int] = {
    "system_status": 60,

    "flood": 60 * 60,
    "policy": 60 * 60,
    "linkage": 60 * 60,
    "company": 60 * 60,
    "spatial": 60 * 60,
    "map": 30 * 60,
    "graph": 30 * 60,
    "dashboard": 15 * 60,
    "filter": 15 * 60,
    "data_quality": 15 * 60,

    "package": 0,
}

CACHE_METADATA_FILENAME: str = "_cache_meta.json"

CACHE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "company_unified_base": {
        "filename": CACHE_FILES["company_unified_base"],
        "owner_service": "company_policy_service",
        "builder_function": "build_company_unified_base",
        "payload_type": "records",
        "depends_on": ["policy_fact", "company_location_master", "province_branch_coordinate_master"],
        "consumed_by": ["linkage_service", "flood_spatial_service"],
        "ttl_group": "company",
        "critical": True,
        "allow_stale": True,
        "aliases": [],
    },
    "company_unified_master": {
        "filename": CACHE_FILES["company_unified_master"],
        "owner_service": "company_policy_service",
        "builder_function": "build_company_unified_master",
        "payload_type": "records",
        "depends_on": ["company_unified_base", "linkage_graph_payload", "spatial_join_result"],
        "consumed_by": ["map_graph_service", "dashboard_package_service", "data_quality", "security"],
        "ttl_group": "company",
        "critical": True,
        "allow_stale": True,
        "aliases": [],
    },
    "linkage_graph_payload": {
        "filename": CACHE_FILES["linkage_graph_payload"],
        "owner_service": "linkage_service",
        "builder_function": "build_linkage_graph_payload",
        "payload_type": "graph",
        "depends_on": ["company_unified_base", "director_company_pairs", "shared_director_links"],
        "consumed_by": ["map_graph_service", "dashboard_package_service", "security"],
        "ttl_group": "graph",
        "critical": False,
        "allow_stale": True,
        "aliases": ["linkage_graph", "graph_payload"],
    },
    "flood_rainfall_latest": {
        "filename": CACHE_FILES["flood_rainfall_latest"],
        "owner_service": "flood_spatial_service",
        "builder_function": "get_latest_rainfall",
        "payload_type": "records",
        "depends_on": [],
        "consumed_by": ["map_graph_service", "dashboard_package_service", "data_quality"],
        "ttl_group": "flood",
        "critical": False,
        "allow_stale": True,
        "aliases": ["rainfall_latest"],
    },
    "flood_waterlevel_latest": {
        "filename": CACHE_FILES["flood_waterlevel_latest"],
        "owner_service": "flood_spatial_service",
        "builder_function": "get_latest_waterlevel",
        "payload_type": "records",
        "depends_on": [],
        "consumed_by": ["map_graph_service", "dashboard_package_service", "data_quality"],
        "ttl_group": "flood",
        "critical": False,
        "allow_stale": True,
        "aliases": ["waterlevel_latest"],
    },
    "flood_large_dam_latest": {
        "filename": CACHE_FILES["flood_large_dam_latest"],
        "owner_service": "flood_spatial_service",
        "builder_function": "get_latest_large_dam",
        "payload_type": "records",
        "depends_on": [],
        "consumed_by": ["map_graph_service", "dashboard_package_service", "data_quality"],
        "ttl_group": "flood",
        "critical": False,
        "allow_stale": True,
        "aliases": ["large_dam_latest"],
    },
    "flood_medium_dam_latest": {
        "filename": CACHE_FILES["flood_medium_dam_latest"],
        "owner_service": "flood_spatial_service",
        "builder_function": "get_latest_medium_dam",
        "payload_type": "records",
        "depends_on": [],
        "consumed_by": ["map_graph_service", "dashboard_package_service", "data_quality"],
        "ttl_group": "flood",
        "critical": False,
        "allow_stale": True,
        "aliases": ["medium_dam_latest"],
    },
    "flood_prediction_latest": {
        "filename": CACHE_FILES["flood_prediction_latest"],
        "owner_service": "flood_spatial_service",
        "builder_function": "get_latest_flood_predictions",
        "payload_type": "records",
        "depends_on": ["flood_master"],
        "consumed_by": ["map_graph_service", "dashboard_package_service", "data_quality"],
        "ttl_group": "flood",
        "critical": False,
        "allow_stale": True,
        "aliases": ["prediction_latest", "forecast_latest"],
    },
    "uploaded_entity_latest": {
        "filename": CACHE_FILES["uploaded_entity_latest"],
        "owner_service": "entity_upload_service",
        "builder_function": "get_latest_entity_records",
        "payload_type": "records",
        "depends_on": [],
        "consumed_by": ["map_graph_service", "dashboard_package_service", "data_quality"],
        "ttl_group": "map",
        "critical": False,
        "allow_stale": True,
        "aliases": ["entity_latest"],
    },
    "map_layers": {
        "filename": CACHE_FILES["map_layers"],
        "owner_service": "map_graph_service",
        "builder_function": "get_map_layers",
        "payload_type": "map",
        "depends_on": [
            "company_unified_master",
            "flood_rainfall_latest",
            "flood_waterlevel_latest",
            "flood_large_dam_latest",
            "flood_medium_dam_latest",
            "flood_prediction_latest",
            "uploaded_entity_latest",
            "linkage_graph_payload",
        ],
        "consumed_by": ["dashboard_package_service", "security"],
        "ttl_group": "map",
        "critical": False,
        "allow_stale": True,
        "aliases": [],
    },
    "dashboard_province_insights": {
        "filename": CACHE_FILES["dashboard_province_insights"],
        "owner_service": "dashboard_package_service",
        "builder_function": "get_dashboard_province_insights",
        "payload_type": "dashboard",
        "depends_on": [
            "flood_prediction_latest",
            "flood_rainfall_latest",
            "flood_waterlevel_latest",
            "flood_large_dam_latest",
            "flood_medium_dam_latest",
        ],
        "consumed_by": ["api_routes", "security"],
        "ttl_group": "dashboard",
        "critical": False,
        "allow_stale": True,
        "aliases": [],
    },
}


# ============================================================
# 18) API SETTINGS
# ============================================================

API_DEFAULT_SUCCESS_MESSAGE: str = "OK"
API_DEFAULT_ERROR_MESSAGE: str = "ERROR"

API_RESPONSE_KEYS: Dict[str, str] = {
    "success": "success",
    "message": "message",
    "data": "data",
    "meta": "meta",
    "errors": "errors",
}

CORS_ENABLED: bool = os.getenv("TIPX_CORS_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

CORS_ALLOW_ORIGINS: List[str] = [
    origin.strip()
    for origin in os.getenv(
        "TIPX_CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS: bool = os.getenv(
    "TIPX_CORS_ALLOW_CREDENTIALS", "false"
).strip().lower() in {"1", "true", "yes", "y"}
CORS_ALLOW_METHODS: List[str] = [
    item.strip().upper()
    for item in os.getenv(
        "TIPX_CORS_ALLOW_METHODS",
        "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    ).split(",")
    if item.strip()
]
CORS_ALLOW_HEADERS: List[str] = [
    item.strip()
    for item in os.getenv(
        "TIPX_CORS_ALLOW_HEADERS",
        "Content-Type,Authorization,X-Requested-With,X-Request-ID,X-Correlation-ID,X-TIPX-Package-Token,X-Package-Token",
    ).split(",")
    if item.strip()
]
TRUSTED_HOSTS: List[str] = [
    item.strip()
    for item in os.getenv("TIPX_TRUSTED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if item.strip()
]
PACKAGE_TOKEN_HEADER_NAME: str = os.getenv(
    "TIPX_PACKAGE_TOKEN_HEADER_NAME", "X-TIPX-Package-Token"
).strip()

JSON_SORT_KEYS: bool = False
JSON_AS_ASCII: bool = False
MAX_CONTENT_LENGTH_MB: int = UPLOAD_MAX_CONTENT_LENGTH_MB


# ============================================================
# 19) AUTH / SECURITY SETTINGS
# ============================================================

"""
security.py และ backend/auth/* จะใช้ค่ากลุ่มนี้

ระบบ auth รอบนี้เป็น Fixed Auth System:
- admin  = 1 account
- user   = 1 account
- viewer = 1 account

รองรับ:
- password login
- password hash
- JWT Bearer token
- backend role guard
- frontend route guard
- protect internal /api
- simple audit log
- MySQL auth storage

ยังไม่รองรับ:
- OAuth
- API key
- session table
- refresh token
- forgot password
- user registration
- admin create user
- field-level permission
- CSRF เต็มระบบ
"""

# ------------------------------------------------------------
# legacy / package security
# ------------------------------------------------------------

SECRET_KEY: str = os.getenv("TIPX_SECRET_KEY", "").strip()

PACKAGE_TOKEN_SALT: str = os.getenv("TIPX_PACKAGE_TOKEN_SALT", "").strip()

ENABLE_PACKAGE_ACCESS_TOKEN: bool = os.getenv(
    "TIPX_ENABLE_PACKAGE_ACCESS_TOKEN", "false"
).strip().lower() in {"1", "true", "yes", "y"}

PUBLIC_PACKAGE_READ_ONLY: bool = True

MASK_TAX_ID_VISIBLE_LAST_DIGITS: int = 4
MASK_DIRECTOR_VISIBLE_FIRST_CHARS: int = 2


# ------------------------------------------------------------
# MySQL auth database
# ------------------------------------------------------------

MYSQL_HOST: str = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_USER: str = os.getenv("MYSQL_USER", "tipx")
MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "").strip()
MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "tipx_login")
MYSQL_CHARSET: str = os.getenv("MYSQL_CHARSET", "utf8mb4")
MYSQL_CONNECT_TIMEOUT_SECONDS: int = int(os.getenv("MYSQL_CONNECT_TIMEOUT_SECONDS", "10"))

AUTH_MYSQL_TABLE_USERS: str = os.getenv("AUTH_MYSQL_TABLE_USERS", "auth_users")
AUTH_MYSQL_TABLE_AUDIT_LOGS: str = os.getenv("AUTH_MYSQL_TABLE_AUDIT_LOGS", "auth_audit_logs")

AUTH_DB_AUTO_CREATE: bool = os.getenv("AUTH_DB_AUTO_CREATE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

AUTH_DB_AUTO_SEED: bool = os.getenv("AUTH_DB_AUTO_SEED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}


# ------------------------------------------------------------
# Auth enable / fixed users
# ------------------------------------------------------------

AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

AUTH_FIXED_USERS_ENABLED: bool = True
AUTH_ALLOW_REGISTRATION: bool = False
AUTH_ALLOW_ADMIN_CREATE_USER: bool = False
AUTH_ALLOW_FORGOT_PASSWORD: bool = False
AUTH_ALLOW_REFRESH_TOKEN: bool = False
AUTH_ALLOW_OAUTH: bool = False
AUTH_ALLOW_API_KEY: bool = False
AUTH_ALLOW_SESSION_TABLE: bool = False

AUTH_ADMIN_USERNAME: str = os.getenv("AUTH_ADMIN_USERNAME", "admin").strip()
AUTH_ADMIN_PASSWORD: str = os.getenv("AUTH_ADMIN_PASSWORD", "").strip()

AUTH_USER_USERNAME: str = os.getenv("AUTH_USER_USERNAME", "user").strip()
AUTH_USER_PASSWORD: str = os.getenv("AUTH_USER_PASSWORD", "").strip()

AUTH_VIEWER_USERNAME: str = os.getenv("AUTH_VIEWER_USERNAME", "viewer").strip()
AUTH_VIEWER_PASSWORD: str = os.getenv("AUTH_VIEWER_PASSWORD", "").strip()

AUTH_ROLES: List[str] = [
    "admin",
    "user",
    "viewer",
]

AUTH_ROLE_LEVEL: Dict[str, int] = {
    "viewer": 10,
    "user": 50,
    "admin": 100,
}

AUTH_FIXED_USERS: List[Dict[str, Any]] = [
    {
        "username": AUTH_ADMIN_USERNAME,
        "password": AUTH_ADMIN_PASSWORD,
        "role": "admin",
        "display_name": "TIPX Admin",
        "is_active": True,
        "fixed": True,
    },
    {
        "username": AUTH_USER_USERNAME,
        "password": AUTH_USER_PASSWORD,
        "role": "user",
        "display_name": "TIPX User",
        "is_active": True,
        "fixed": True,
    },
    {
        "username": AUTH_VIEWER_USERNAME,
        "password": AUTH_VIEWER_PASSWORD,
        "role": "viewer",
        "display_name": "TIPX Viewer",
        "is_active": True,
        "fixed": True,
    },
]

AUTH_FIXED_USERNAMES: List[str] = [
    AUTH_ADMIN_USERNAME,
    AUTH_USER_USERNAME,
    AUTH_VIEWER_USERNAME,
]


# ------------------------------------------------------------
# Password hash
# ------------------------------------------------------------

PASSWORD_HASH_SCHEME: str = os.getenv("PASSWORD_HASH_SCHEME", "pbkdf2_sha256")
PASSWORD_HASH_ITERATIONS: int = int(os.getenv("PASSWORD_HASH_ITERATIONS", "260000"))
PASSWORD_HASH_SALT_BYTES: int = int(os.getenv("PASSWORD_HASH_SALT_BYTES", "16"))
PASSWORD_HASH_PEPPER: str = os.getenv("PASSWORD_HASH_PEPPER", "")


# ------------------------------------------------------------
# JWT
# ------------------------------------------------------------

JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", os.getenv("TIPX_JWT_SECRET_KEY", SECRET_KEY))
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
JWT_ISSUER: str = os.getenv("JWT_ISSUER", APP_SHORT_NAME)
JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "tipx-web")
JWT_CLOCK_SKEW_SECONDS: int = int(os.getenv("JWT_CLOCK_SKEW_SECONDS", "30"))

AUTH_TOKEN_TYPE: str = "Bearer"
AUTH_HEADER_NAME: str = "Authorization"
AUTH_TOKEN_PREFIX: str = "Bearer "
AUTH_USER_STATE_KEY: str = "user"


# ------------------------------------------------------------
# Backend API guard
# ------------------------------------------------------------

AUTH_PROTECT_INTERNAL_API: bool = True
AUTH_PROTECTED_API_PREFIX: str = API_PREFIX
AUTH_SKIP_OPTIONS_REQUEST: bool = True

AUTH_PUBLIC_EXACT_PATHS: List[str] = [
    "/",
    "/favicon.ico",
    f"{API_PREFIX}/health",
    f"{API_PREFIX}/status",
    f"{API_PREFIX}/docs",
    f"{API_PREFIX}/redoc",
    f"{API_PREFIX}/openapi.json",
    f"{API_PREFIX}/auth/login",
    f"{API_PREFIX}/auth/status",
    f"{API_PREFIX}/auth/contract",
]


AUTH_PUBLIC_PREFIXES: List[str] = [
    "/static",
    "/assets",
    "/frontend",
    "/external_viewer",
    PUBLIC_API_PREFIX,
]

AUTH_AUTHENTICATED_EXACT_PATHS: List[str] = [
    f"{API_PREFIX}/auth/me",
    f"{API_PREFIX}/auth/logout",
]

AUTH_DEFAULT_READ_ROLES: List[str] = [
    "admin",
    "user",
    "viewer",
]

AUTH_DEFAULT_WRITE_ROLES: List[str] = [
    "admin",
    "user",
]

AUTH_DEFAULT_ADMIN_ROLES: List[str] = [
    "admin",
]

AUTH_ROLE_ROUTE_RULES: List[Dict[str, Any]] = [
    {
        "name": "auth_me",
        "methods": ["GET"],
        "path_prefix": f"{API_PREFIX}/auth/me",
        "roles": ["admin", "user", "viewer"],
        "audit_action": "auth_me",
    },
    {
        "name": "auth_logout",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/auth/logout",
        "roles": ["admin", "user", "viewer"],
        "audit_action": "logout",
    },
    {
        "name": "admin_api",
        "methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        "path_prefix": f"{API_PREFIX}/admin",
        "roles": ["admin"],
        "audit_action": "admin_api",
    },
    {
        "name": "cache_api",
        "methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        "path_prefix": f"{API_PREFIX}/cache",
        "roles": ["admin"],
        "audit_action": "cache_admin",
    },
    {
        "name": "upload_clear",
        "methods": ["POST", "DELETE"],
        "path_prefix": f"{API_PREFIX}/upload/entities/clear",
        "roles": ["admin"],
        "audit_action": "clear_upload",
    },
    {
        "name": "upload_delete",
        "methods": ["DELETE"],
        "path_prefix": f"{API_PREFIX}/upload",
        "roles": ["admin"],
        "audit_action": "delete_upload",
    },
    {
        "name": "upload_entities",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/upload/entities",
        "roles": ["admin", "user"],
        "audit_action": "upload_entities",
    },
    {
        "name": "package_generate",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/packages/generate",
        "roles": ["admin", "user"],
        "audit_action": "package_generate",
    },
    {
        "name": "package_preview",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/packages/preview",
        "roles": ["admin", "user"],
        "audit_action": "package_preview",
    },
    {
        "name": "package_manage",
        "methods": ["POST", "PUT", "PATCH", "DELETE"],
        "path_prefix": f"{API_PREFIX}/packages",
        "roles": ["admin", "user"],
        "audit_action": "package_manage",
    },
    {
        "name": "filter_apply",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/filter",
        "roles": ["admin", "user", "viewer"],
        "audit_action": "filter_apply",
    },
    {
        "name": "internal_read_api",
        "methods": ["GET"],
        "path_prefix": f"{API_PREFIX}",
        "roles": ["admin", "user", "viewer"],
        "audit_action": "read_api",
    },
    {
        "name": "internal_write_api",
        "methods": ["POST", "PUT", "PATCH"],
        "path_prefix": f"{API_PREFIX}",
        "roles": ["admin", "user"],
        "audit_action": "write_api",
    },
    {
        "name": "internal_delete_api",
        "methods": ["DELETE"],
        "path_prefix": f"{API_PREFIX}",
        "roles": ["admin"],
        "audit_action": "delete_api",
    },
]


# ------------------------------------------------------------
# Frontend route guard contract
# ------------------------------------------------------------

FRONTEND_AUTH_ENABLED: bool = AUTH_ENABLED
FRONTEND_LOGIN_PATH: str = "/login"
FRONTEND_DEFAULT_AFTER_LOGIN_PATH: str = "/dashboard"

FRONTEND_ROLE_HOME_PATHS: Dict[str, str] = {
    "admin": "/admin",
    "user": "/dashboard",
    "viewer": "/dashboard",
}

FRONTEND_PUBLIC_ROUTES: List[str] = [
    "/login",
    "/public",
    "/external-viewer",
]

FRONTEND_ROLE_ROUTE_RULES: List[Dict[str, Any]] = [
    {
        "path_prefix": "/admin",
        "roles": ["admin"],
    },
    {
        "path_prefix": "/settings",
        "roles": ["admin"],
    },
    {
        "path_prefix": "/cache",
        "roles": ["admin"],
    },
    {
        "path_prefix": "/upload",
        "roles": ["admin", "user"],
    },
    {
        "path_prefix": "/packages/generate",
        "roles": ["admin", "user"],
    },
    {
        "path_prefix": "/dashboard",
        "roles": ["admin", "user", "viewer"],
    },
    {
        "path_prefix": "/map",
        "roles": ["admin", "user", "viewer"],
    },
    {
        "path_prefix": "/companies",
        "roles": ["admin", "user", "viewer"],
    },
    {
        "path_prefix": "/policy",
        "roles": ["admin", "user", "viewer"],
    },
    {
        "path_prefix": "/linkage",
        "roles": ["admin", "user", "viewer"],
    },
    {
        "path_prefix": "/flood",
        "roles": ["admin", "user", "viewer"],
    },
]


# ------------------------------------------------------------
# Audit log
# ------------------------------------------------------------

AUDIT_ENABLED: bool = os.getenv("AUDIT_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

AUDIT_LOG_SUCCESS_READS: bool = os.getenv("AUDIT_LOG_SUCCESS_READS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}

AUDIT_LOG_REQUEST_BODY: bool = False
AUDIT_LOG_RESPONSE_BODY: bool = False
AUDIT_LOG_IP_ADDRESS: bool = True
AUDIT_LOG_USER_AGENT: bool = True

AUDIT_ACTION_PATH_RULES: List[Dict[str, Any]] = [
    {
        "action": "login_success",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/auth/login",
    },
    {
        "action": "logout",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/auth/logout",
    },
    {
        "action": "cache_rebuild",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/cache/rebuild",
    },
    {
        "action": "cache_clear",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/cache/clear",
    },
    {
        "action": "upload_entities",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/upload/entities",
    },
    {
        "action": "clear_upload",
        "methods": ["POST", "DELETE"],
        "path_prefix": f"{API_PREFIX}/upload/entities/clear",
    },
    {
        "action": "package_preview",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/packages/preview",
    },
    {
        "action": "package_generate",
        "methods": ["POST"],
        "path_prefix": f"{API_PREFIX}/packages/generate",
    },
    {
        "action": "package_download",
        "methods": ["GET"],
        "path_prefix": f"{API_PREFIX}/packages",
        "path_contains": "/download",
    },
    {
        "action": "admin_errors_view",
        "methods": ["GET"],
        "path_prefix": f"{API_PREFIX}/admin/errors",
    },
    {
        "action": "admin_data_quality_view",
        "methods": ["GET"],
        "path_prefix": f"{API_PREFIX}/admin/data-quality",
    },
]


# ============================================================
# 20) LOGGING SETTINGS
# ============================================================

LOG_LEVEL: str = os.getenv("TIPX_LOG_LEVEL", "INFO").strip().upper()
LOG_FILENAME: str = "tipx_backend.log"
LOG_PATH: Path = LOG_DIR / LOG_FILENAME

ENABLE_REQUEST_LOG: bool = True
ENABLE_PIPELINE_LOG: bool = True
ENABLE_DATA_QUALITY_LOG: bool = True


# ============================================================
# 21) DATACLASS CONFIG OBJECTS
# ============================================================

@dataclass(frozen=True)
class AuthMySQLConfig:
    host: str = MYSQL_HOST
    port: int = MYSQL_PORT
    user: str = MYSQL_USER
    password: str = MYSQL_PASSWORD
    database: str = MYSQL_DATABASE
    charset: str = MYSQL_CHARSET
    connect_timeout_seconds: int = MYSQL_CONNECT_TIMEOUT_SECONDS
    users_table: str = AUTH_MYSQL_TABLE_USERS
    audit_logs_table: str = AUTH_MYSQL_TABLE_AUDIT_LOGS
    auto_create: bool = AUTH_DB_AUTO_CREATE
    auto_seed: bool = AUTH_DB_AUTO_SEED


@dataclass(frozen=True)
class AuthJWTConfig:
    secret_key: str = JWT_SECRET_KEY
    algorithm: str = JWT_ALGORITHM
    expire_minutes: int = JWT_EXPIRE_MINUTES
    issuer: str = JWT_ISSUER
    audience: str = JWT_AUDIENCE
    clock_skew_seconds: int = JWT_CLOCK_SKEW_SECONDS
    token_type: str = AUTH_TOKEN_TYPE
    header_name: str = AUTH_HEADER_NAME


@dataclass(frozen=True)
class AuthPasswordConfig:
    hash_scheme: str = PASSWORD_HASH_SCHEME
    iterations: int = PASSWORD_HASH_ITERATIONS
    salt_bytes: int = PASSWORD_HASH_SALT_BYTES
    pepper: str = PASSWORD_HASH_PEPPER


@dataclass(frozen=True)
class AuthRouteGuardConfig:
    protect_internal_api: bool = AUTH_PROTECT_INTERNAL_API
    protected_api_prefix: str = AUTH_PROTECTED_API_PREFIX
    skip_options_request: bool = AUTH_SKIP_OPTIONS_REQUEST
    public_exact_paths: List[str] = field(default_factory=lambda: list(AUTH_PUBLIC_EXACT_PATHS))
    public_prefixes: List[str] = field(default_factory=lambda: list(AUTH_PUBLIC_PREFIXES))
    authenticated_exact_paths: List[str] = field(default_factory=lambda: list(AUTH_AUTHENTICATED_EXACT_PATHS))
    default_read_roles: List[str] = field(default_factory=lambda: list(AUTH_DEFAULT_READ_ROLES))
    default_write_roles: List[str] = field(default_factory=lambda: list(AUTH_DEFAULT_WRITE_ROLES))
    default_admin_roles: List[str] = field(default_factory=lambda: list(AUTH_DEFAULT_ADMIN_ROLES))
    role_route_rules: List[Dict[str, Any]] = field(default_factory=lambda: list(AUTH_ROLE_ROUTE_RULES))


@dataclass(frozen=True)
class AuthFrontendConfig:
    enabled: bool = FRONTEND_AUTH_ENABLED
    login_path: str = FRONTEND_LOGIN_PATH
    default_after_login_path: str = FRONTEND_DEFAULT_AFTER_LOGIN_PATH
    role_home_paths: Dict[str, str] = field(default_factory=lambda: dict(FRONTEND_ROLE_HOME_PATHS))
    public_routes: List[str] = field(default_factory=lambda: list(FRONTEND_PUBLIC_ROUTES))
    role_route_rules: List[Dict[str, Any]] = field(default_factory=lambda: list(FRONTEND_ROLE_ROUTE_RULES))


@dataclass(frozen=True)
class AuditConfig:
    enabled: bool = AUDIT_ENABLED
    log_success_reads: bool = AUDIT_LOG_SUCCESS_READS
    log_request_body: bool = AUDIT_LOG_REQUEST_BODY
    log_response_body: bool = AUDIT_LOG_RESPONSE_BODY
    log_ip_address: bool = AUDIT_LOG_IP_ADDRESS
    log_user_agent: bool = AUDIT_LOG_USER_AGENT
    action_path_rules: List[Dict[str, Any]] = field(default_factory=lambda: list(AUDIT_ACTION_PATH_RULES))


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool = AUTH_ENABLED
    fixed_users_enabled: bool = AUTH_FIXED_USERS_ENABLED
    allow_registration: bool = AUTH_ALLOW_REGISTRATION
    allow_admin_create_user: bool = AUTH_ALLOW_ADMIN_CREATE_USER
    allow_forgot_password: bool = AUTH_ALLOW_FORGOT_PASSWORD
    allow_refresh_token: bool = AUTH_ALLOW_REFRESH_TOKEN
    allow_oauth: bool = AUTH_ALLOW_OAUTH
    allow_api_key: bool = AUTH_ALLOW_API_KEY
    allow_session_table: bool = AUTH_ALLOW_SESSION_TABLE
    roles: List[str] = field(default_factory=lambda: list(AUTH_ROLES))
    role_level: Dict[str, int] = field(default_factory=lambda: dict(AUTH_ROLE_LEVEL))
    fixed_users: List[Dict[str, Any]] = field(default_factory=lambda: list(AUTH_FIXED_USERS))
    fixed_usernames: List[str] = field(default_factory=lambda: list(AUTH_FIXED_USERNAMES))
    mysql: AuthMySQLConfig = field(default_factory=AuthMySQLConfig)
    jwt: AuthJWTConfig = field(default_factory=AuthJWTConfig)
    password: AuthPasswordConfig = field(default_factory=AuthPasswordConfig)
    route_guard: AuthRouteGuardConfig = field(default_factory=AuthRouteGuardConfig)
    frontend: AuthFrontendConfig = field(default_factory=AuthFrontendConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
@dataclass(frozen=True)
class PathConfig:
    project_root: Path = PROJECT_ROOT
    backend_dir: Path = BACKEND_DIR
    frontend_dir: Path = FRONTEND_DIR

    input_dir: Path = INPUT_DIR
    policy_input_dir: Path = POLICY_INPUT_DIR
    linkage_input_dir: Path = LINKAGE_INPUT_DIR

    policy_input_path: Path = POLICY_INPUT_PATH
    linkage_input_path: Path = LINKAGE_INPUT_PATH

    cache_dir: Path = CACHE_DIR
    output_dir: Path = OUTPUT_DIR
    log_dir: Path = LOG_DIR
    export_dir: Path = EXPORT_DIR
    package_dir: Path = PACKAGE_DIR
    package_zip_dir: Path = PACKAGE_ZIP_DIR
    export_history_dir: Path = EXPORT_HISTORY_DIR
    data_quality_output_dir: Path = DATA_QUALITY_OUTPUT_DIR

    flood_pipeline_base_dir: Path = FLOOD_PIPELINE_BASE_DIR
    pipeline_base_dir: Path = PIPELINE_BASE_DIR
    pipeline_output_dir: Path = PIPELINE_OUTPUT_DIR

    flood_output_dir: Path = FLOOD_OUTPUT_DIR
    flood_excel_database_dir: Path = FLOOD_EXCEL_DATABASE_DIR
    excel_database_dir: Path = EXCEL_DATABASE_DIR
    flood_latest_dir: Path = FLOOD_LATEST_DIR
    flood_master_dir: Path = FLOOD_MASTER_DIR
    flood_history_dir: Path = FLOOD_HISTORY_DIR
    flood_latest_database_path: Path = FLOOD_LATEST_DATABASE_PATH
    flood_master_database_path: Path = FLOOD_MASTER_DATABASE_PATH

    flood_prediction_dir: Path = FLOOD_PREDICTION_DIR
    prediction_data_dir: Path = PREDICTION_DATA_DIR

    web_data_dir: Path = WEB_DATA_DIR
    upload_dir: Path = UPLOAD_DIR
    upload_entity_dir: Path = UPLOAD_ENTITY_DIR
    upload_log_dir: Path = UPLOAD_LOG_DIR
    upload_error_report_dir: Path = UPLOAD_ERROR_REPORT_DIR
    web_cache_dir: Path = WEB_CACHE_DIR
    web_log_dir: Path = WEB_LOG_DIR


@dataclass(frozen=True)
class SheetConfig:
    policy_sheets: Dict[str, str] = field(default_factory=lambda: dict(POLICY_SHEETS))
    policy_sheet_index_fallback: Dict[str, int] = field(
        default_factory=lambda: dict(POLICY_SHEET_INDEX_FALLBACK)
    )
    linkage_sheet_index_fallback: int = LINKAGE_SHEET_INDEX_FALLBACK
    flood_latest_sheets: Dict[str, str] = field(default_factory=lambda: dict(FLOOD_LATEST_SHEETS))
    flood_master_sheets: Dict[str, str] = field(default_factory=lambda: dict(FLOOD_MASTER_SHEETS))
    flood_history_sheets: Dict[str, str] = field(default_factory=lambda: dict(FLOOD_HISTORY_SHEETS))
    latest_sheets: Dict[str, str] = field(default_factory=lambda: dict(LATEST_SHEETS))
    master_sheets: Dict[str, str] = field(default_factory=lambda: dict(MASTER_SHEETS))
    history_sheets: Dict[str, str] = field(default_factory=lambda: dict(HISTORY_SHEETS))
    history_dirs: Dict[str, Path] = field(default_factory=lambda: dict(HISTORY_DIRS))
    history_file_prefixes: Dict[str, str] = field(default_factory=lambda: dict(HISTORY_FILE_PREFIXES))


@dataclass(frozen=True)
class RiskConfig:
    risk_levels: List[str] = field(default_factory=lambda: list(RISK_LEVELS))
    risk_score: Dict[str, int] = field(default_factory=lambda: dict(RISK_SCORE))
    risk_colors: Dict[str, str] = field(default_factory=lambda: dict(RISK_COLORS))
    loss_ratio_bands: Dict[str, Dict[str, Any]] = field(
        default_factory=lambda: dict(LOSS_RATIO_BANDS)
    )
    rainfall_thresholds_mm: Dict[str, float] = field(
        default_factory=lambda: dict(FLOOD_RAINFALL_THRESHOLDS_MM)
    )
    waterlevel_thresholds: Dict[str, float] = field(
        default_factory=lambda: dict(FLOOD_WATERLEVEL_THRESHOLDS)
    )
    dam_storage_thresholds_percent: Dict[str, float] = field(
        default_factory=lambda: dict(FLOOD_DAM_STORAGE_THRESHOLDS_PERCENT)
    )


@dataclass(frozen=True)
class CacheConfig:
    enabled: bool = CACHE_ENABLED
    ttl_seconds: Dict[str, int] = field(default_factory=lambda: dict(CACHE_TTL_SECONDS))
    cache_files: Dict[str, str] = field(default_factory=lambda: dict(CACHE_FILES))
    cache_registry: Dict[str, Dict[str, Any]] = field(default_factory=lambda: dict(CACHE_REGISTRY))
    metadata_filename: str = CACHE_METADATA_FILENAME

# ============================================================
# GRAPH VISUAL SETTINGS
# ============================================================

GRAPH_NODE_SIZE: Dict[str, int] = {
    "company": 12,
    "director": 9,
    "key_connector": 18,
    "selected": 22,
    "default": 10,
}

GRAPH_EDGE_WIDTH: Dict[str, float] = {
    "DIRECTOR_OF": 1.2,
    "SHARED_DIRECTOR": 2.0,
    "default": 1.0,
}

GRAPH_MAX_NODES = 800
GRAPH_MAX_EDGES = 2000
GRAPH_DEFAULT_LAYOUT = "force"

@dataclass(frozen=True)
class MapConfig:
    default_center: Tuple[float, float] = DEFAULT_MAP_CENTER
    default_zoom: int = DEFAULT_MAP_ZOOM
    min_zoom: int = DEFAULT_MAP_MIN_ZOOM
    max_zoom: int = DEFAULT_MAP_MAX_ZOOM
    thailand_lat_range: Tuple[float, float] = THAILAND_LAT_RANGE
    thailand_lon_range: Tuple[float, float] = THAILAND_LON_RANGE
    nearest_station_max_distance_km: float = NEAREST_STATION_MAX_DISTANCE_KM
    nearest_dam_max_distance_km: float = NEAREST_DAM_MAX_DISTANCE_KM



@dataclass(frozen=True)
class GraphConfig:
    default_mode: str = GRAPH_DEFAULT_MODE
    default_depth: int = GRAPH_DEFAULT_DEPTH
    default_max_nodes: int = GRAPH_DEFAULT_MAX_NODES
    hard_max_nodes: int = GRAPH_HARD_MAX_NODES
    default_max_edges: int = GRAPH_DEFAULT_MAX_EDGES
    key_connector_min_company_count: int = KEY_CONNECTOR_MIN_COMPANY_COUNT
    director_id_prefix: str = DIRECTOR_ID_PREFIX
    company_node_prefix: str = COMPANY_NODE_PREFIX
    director_node_prefix: str = DIRECTOR_NODE_PREFIX
    edge_type_director_of: str = EDGE_TYPE_DIRECTOR_OF
    edge_type_shared_director: str = EDGE_TYPE_SHARED_DIRECTOR


@dataclass(frozen=True)
class PackageConfig:
    package_id_prefix: str = PACKAGE_ID_PREFIX
    datetime_format: str = PACKAGE_DATETIME_FORMAT
    default_expire_days: int = PACKAGE_DEFAULT_EXPIRE_DAYS
    max_expire_days: int = PACKAGE_MAX_EXPIRE_DAYS
    components: List[str] = field(default_factory=lambda: list(PACKAGE_COMPONENTS))
    security_options: Dict[str, bool] = field(default_factory=lambda: dict(PACKAGE_SECURITY_OPTIONS))
    required_files: List[str] = field(default_factory=lambda: list(PACKAGE_REQUIRED_FILES))


@dataclass(frozen=True)
class AppConfig:
    app_name: str = APP_NAME
    app_short_name: str = APP_SHORT_NAME
    app_version: str = APP_VERSION
    app_description: str = APP_DESCRIPTION
    env: str = DEFAULT_ENV
    debug: bool = DEBUG
    testing: bool = TESTING
    timezone: str = DEFAULT_TIMEZONE
    api_prefix: str = API_PREFIX
    public_api_prefix: str = PUBLIC_API_PREFIX

    paths: PathConfig = field(default_factory=PathConfig)
    sheets: SheetConfig = field(default_factory=SheetConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    map: MapConfig = field(default_factory=MapConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    package: PackageConfig = field(default_factory=PackageConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)


CONFIG = AppConfig()


# ============================================================
# 22) DIRECTORY BOOTSTRAP
# ============================================================

REQUIRED_DIRECTORIES: List[Path] = [
    INPUT_DIR,
    POLICY_INPUT_DIR,
    LINKAGE_INPUT_DIR,
    CACHE_DIR,
    OUTPUT_DIR,
    LOG_DIR,
    EXPORT_DIR,
    PACKAGE_DIR,
    PACKAGE_ZIP_DIR,
    EXPORT_HISTORY_DIR,
    DATA_QUALITY_OUTPUT_DIR,

    WEB_DATA_DIR,
    UPLOAD_DIR,
    UPLOAD_ENTITY_DIR,
    UPLOAD_LOG_DIR,
    UPLOAD_ERROR_REPORT_DIR,
    WEB_CACHE_DIR,
    WEB_LOG_DIR,

    FLOOD_OUTPUT_DIR,
    FLOOD_EXCEL_DATABASE_DIR,
    FLOOD_LATEST_DIR,
    FLOOD_MASTER_DIR,
    FLOOD_HISTORY_DIR,
    FLOOD_HISTORY_RAINFALL_DIR,
    FLOOD_HISTORY_RAIN15D_DIR,
    FLOOD_HISTORY_RAIN_YEARLY_DIR,
    FLOOD_HISTORY_WATERLEVEL_DIR,
    FLOOD_HISTORY_LARGE_DAM_DIR,
    FLOOD_HISTORY_MEDIUM_DAM_DIR,
    FLOOD_HISTORY_ALL_LONG_DIR,
    FLOOD_PREDICTION_DIR,
]


def ensure_directories() -> None:
    """Create writable runtime directories without creating foreign external paths."""
    internal_directories = [
        INPUT_DIR,
        CACHE_DIR,
        OUTPUT_DIR,
        LOG_DIR,
        EXPORT_DIR,
        PACKAGE_DIR,
        PACKAGE_ZIP_DIR,
        EXPORT_HISTORY_DIR,
        DATA_QUALITY_OUTPUT_DIR,
        POLICY_INPUT_DIR,
        LINKAGE_INPUT_DIR,
        WEB_DATA_DIR,
        UPLOAD_DIR,
        UPLOAD_ENTITY_DIR,
        UPLOAD_LOG_DIR,
        UPLOAD_ERROR_REPORT_DIR,
        WEB_CACHE_DIR,
        WEB_LOG_DIR,
    ]
    external_directories = [
        FLOOD_OUTPUT_DIR,
        FLOOD_EXCEL_DATABASE_DIR,
        FLOOD_LATEST_DIR,
        FLOOD_MASTER_DIR,
        FLOOD_HISTORY_DIR,
        FLOOD_HISTORY_RAINFALL_DIR,
        FLOOD_HISTORY_RAIN15D_DIR,
        FLOOD_HISTORY_RAIN_YEARLY_DIR,
        FLOOD_HISTORY_WATERLEVEL_DIR,
        FLOOD_HISTORY_DAM_DIR,
        FLOOD_HISTORY_LARGE_DAM_DIR,
        FLOOD_HISTORY_MEDIUM_DAM_DIR,
        FLOOD_HISTORY_ALL_LONG_DIR,
        FLOOD_PREDICTION_DIR,
    ]

    for directory in internal_directories:
        directory.mkdir(parents=True, exist_ok=True)

    if os.getenv("TIPX_CREATE_EXTERNAL_DIRS", "false").strip().lower() in {"1", "true", "yes", "y"}:
        for directory in external_directories:
            if is_path_compatible_with_runtime(directory):
                directory.mkdir(parents=True, exist_ok=True)



# ============================================================
# 23) PATH HELPERS
# ============================================================

def validate_data_source_config() -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if USE_EXCEL_DATA_SOURCE and USE_MYSQL_DATA_SOURCE:
        errors.append(
            {
                "code": "data_source_conflict",
                "message": "เปิด USE_EXCEL_DATA_SOURCE และ USE_MYSQL_DATA_SOURCE พร้อมกันไม่ได้",
                "excel_enabled": USE_EXCEL_DATA_SOURCE,
                "mysql_enabled": USE_MYSQL_DATA_SOURCE,
            }
        )

    if not USE_EXCEL_DATA_SOURCE and not USE_MYSQL_DATA_SOURCE:
        errors.append(
            {
                "code": "data_source_missing",
                "message": "ต้องเปิด data source อย่างน้อย 1 ตัว",
                "excel_enabled": USE_EXCEL_DATA_SOURCE,
                "mysql_enabled": USE_MYSQL_DATA_SOURCE,
            }
        )

    if USE_MYSQL_DATA_SOURCE:
        warnings.append(
            {
                "code": "mysql_not_implemented",
                "message": DATA_SOURCE_NOT_IMPLEMENTED_MESSAGE,
                "mysql_enabled": USE_MYSQL_DATA_SOURCE,
            }
        )

    active_source = None

    if USE_EXCEL_DATA_SOURCE and not USE_MYSQL_DATA_SOURCE:
        active_source = DATA_SOURCE_EXCEL

    if USE_MYSQL_DATA_SOURCE and not USE_EXCEL_DATA_SOURCE:
        active_source = DATA_SOURCE_MYSQL

    status = "ok"

    if warnings:
        status = "warning"

    if errors:
        status = "error"

    return {
        "status": status,
        "active_source": active_source,
        "excel_enabled": USE_EXCEL_DATA_SOURCE,
        "mysql_enabled": USE_MYSQL_DATA_SOURCE,
        "mysql_implemented": False,
        "errors": errors,
        "warnings": warnings,
    }


def get_active_data_source() -> str:
    validation = validate_data_source_config()

    if validation["status"] == "error":
        return "invalid"

    return str(validation.get("active_source") or "invalid")


def normalize_history_data_type(data_type: Any) -> str:
    text = str(data_type or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "rain": "rainfall",
        "rainfall_daily": "rainfall",
        "rain_monthly_graph": "rainfall",
        "rain_15d": "rain15d",
        "rainfall_15d": "rain15d",
        "rainfall_yearly": "rain_yearly",
        "rain_yearly_graph": "rain_yearly",
        "water": "waterlevel",
        "waterlevel_history": "waterlevel",
        "waterlevel_graph_year": "waterlevel",
        "large-dam": "large_dam",
        "dam_large": "large_dam",
        "dam_yearly_graph": "large_dam",
        "medium-dam": "medium_dam",
        "dam_medium": "medium_dam",
        "dam_medium_graph": "medium_dam",
        "all": "all_long",
        "all_long_history": "all_long",
    }

    return aliases.get(text, text)


def get_history_sheet(data_type: Any) -> str:
    data_type_key = normalize_history_data_type(data_type)
    sheet_name = HISTORY_SHEETS.get(data_type_key)

    if sheet_name:
        return sheet_name

    return HISTORY_SHEETS.get(str(data_type or "").strip(), SHEET_ALL_LONG)


def get_history_dir(data_type: Any) -> Path:
    data_type_key = normalize_history_data_type(data_type)
    history_dir = HISTORY_DIRS.get(data_type_key)

    if history_dir:
        return history_dir

    return FLOOD_HISTORY_DIR


def get_history_file_prefix(data_type: Any) -> str:
    data_type_key = normalize_history_data_type(data_type)
    return HISTORY_FILE_PREFIXES.get(data_type_key, data_type_key or "history")


def get_history_file(data_type: Any, year: int | str, month: int | str) -> Path:
    data_type_key = normalize_history_data_type(data_type)
    history_dir = get_history_dir(data_type_key)
    prefix = get_history_file_prefix(data_type_key)

    try:
        safe_year = int(year)
    except Exception:
        safe_year = 0

    try:
        safe_month = int(month)
    except Exception:
        safe_month = 0

    if safe_year <= 0:
        safe_year_text = str(year).strip()
    else:
        safe_year_text = f"{safe_year:04d}"

    if safe_month <= 0:
        safe_month_text = str(month).strip()
    else:
        safe_month_text = f"{safe_month:02d}"

    return history_dir / f"{prefix}_{safe_year_text}_{safe_month_text}.xlsx"


def find_latest_prediction_file() -> Optional[Path]:
    if not config_path_exists(FLOOD_PREDICTION_DIR):
        return None

    files = [
        path
        for path in FLOOD_PREDICTION_DIR.glob(PREDICTION_FILE_GLOB)
        if path.is_file()
    ]

    if not files:
        return None

    prefix = f"{PREDICTION_FILE_PREFIX}_"
    dated_files: List[Tuple[Tuple[int, int, int], Path]] = []

    for path in files:
        date_text = path.stem[len(prefix):] if path.stem.startswith(prefix) else ""
        date_parts = date_text.split("_")

        if len(date_parts) != 3 or not all(part.isdigit() for part in date_parts):
            continue

        year, month, day = (int(part) for part in date_parts)

        if year < 1 or not 1 <= month <= 12 or not 1 <= day <= 31:
            continue

        dated_files.append(((year, month, day), path))

    if dated_files:
        return max(dated_files, key=lambda item: item[0])[1]

    return max(files, key=lambda path: path.stat().st_mtime)


def allowed_upload_file(filename: str) -> bool:
    suffix = Path(str(filename or "")).suffix.lower()
    return suffix in set(UPLOAD_ALLOWED_EXTENSIONS)

def get_auth_config_summary() -> Dict[str, Any]:
    """
    คืน auth config แบบ safe ไม่เปิด password / secret / token
    """

    return {
        "enabled": AUTH_ENABLED,
        "fixed_users_enabled": AUTH_FIXED_USERS_ENABLED,
        "roles": list(AUTH_ROLES),
        "fixed_usernames": list(AUTH_FIXED_USERNAMES),
        "mysql": {
            "host": MYSQL_HOST,
            "port": MYSQL_PORT,
            "user": MYSQL_USER,
            "database": MYSQL_DATABASE,
            "charset": MYSQL_CHARSET,
            "users_table": AUTH_MYSQL_TABLE_USERS,
            "audit_logs_table": AUTH_MYSQL_TABLE_AUDIT_LOGS,
            "password_configured": bool(MYSQL_PASSWORD),
            "auto_create": AUTH_DB_AUTO_CREATE,
            "auto_seed": AUTH_DB_AUTO_SEED,
        },
        "jwt": {
            "algorithm": JWT_ALGORITHM,
            "expire_minutes": JWT_EXPIRE_MINUTES,
            "issuer": JWT_ISSUER,
            "audience": JWT_AUDIENCE,
            "secret_configured": bool(JWT_SECRET_KEY),
        },
        "route_guard": {
            "protect_internal_api": AUTH_PROTECT_INTERNAL_API,
            "protected_api_prefix": AUTH_PROTECTED_API_PREFIX,
            "public_exact_paths": list(AUTH_PUBLIC_EXACT_PATHS),
            "public_prefixes": list(AUTH_PUBLIC_PREFIXES),
            "role_route_rules": list(AUTH_ROLE_ROUTE_RULES),
        },
        "frontend": {
            "enabled": FRONTEND_AUTH_ENABLED,
            "login_path": FRONTEND_LOGIN_PATH,
            "default_after_login_path": FRONTEND_DEFAULT_AFTER_LOGIN_PATH,
            "role_home_paths": dict(FRONTEND_ROLE_HOME_PATHS),
            "public_routes": list(FRONTEND_PUBLIC_ROUTES),
            "role_route_rules": list(FRONTEND_ROLE_ROUTE_RULES),
        },
        "audit": {
            "enabled": AUDIT_ENABLED,
            "log_success_reads": AUDIT_LOG_SUCCESS_READS,
            "action_path_rules": list(AUDIT_ACTION_PATH_RULES),
        },
    }

def get_supported_config() -> Dict[str, Any]:
    return get_config_summary()


def get_runtime_paths() -> Dict[str, Any]:
    paths = get_system_path_status()
    latest_prediction_file = find_latest_prediction_file()

    paths.update(
        {
            "master_excel_file": str(MASTER_EXCEL_FILE),
            "latest_excel_file": str(LATEST_EXCEL_FILE),
            "history_excel_dir": str(HISTORY_EXCEL_DIR),
            "prediction_data_dir": str(PREDICTION_DATA_DIR),
            "latest_prediction_file": str(latest_prediction_file) if latest_prediction_file else None,
            "latest_prediction_file_exists": latest_prediction_file.exists() if latest_prediction_file else False,
            "latest_prediction_file_modified_time": (
                latest_prediction_file.stat().st_mtime if latest_prediction_file else None
            ),
            "upload_entity_dir": str(UPLOAD_ENTITY_DIR),
        }
    )

    return paths


def get_path_status() -> Dict[str, bool]:
    return {
        "project_root_exists": PROJECT_ROOT.exists(),
        "backend_dir_exists": BACKEND_DIR.exists(),
        "frontend_dir_exists": FRONTEND_DIR.exists(),
        "input_dir_exists": INPUT_DIR.exists(),
        "cache_dir_exists": CACHE_DIR.exists(),
        "output_dir_exists": OUTPUT_DIR.exists(),
        "package_dir_exists": PACKAGE_DIR.exists(),
        "flood_output_dir_exists": FLOOD_OUTPUT_DIR.exists(),
        "flood_excel_database_dir_exists": FLOOD_EXCEL_DATABASE_DIR.exists(),
        "master_excel_file_exists": MASTER_EXCEL_FILE.exists(),
        "latest_excel_file_exists": LATEST_EXCEL_FILE.exists(),
        "history_excel_dir_exists": HISTORY_EXCEL_DIR.exists(),
        "prediction_data_dir_exists": PREDICTION_DATA_DIR.exists(),
        "upload_entity_dir_exists": UPLOAD_ENTITY_DIR.exists(),
        "web_log_dir_exists": WEB_LOG_DIR.exists(),
        "auth_enabled": AUTH_ENABLED,
        "auth_mysql_host_configured": bool(MYSQL_HOST),
        "auth_mysql_port_configured": bool(MYSQL_PORT),
        "auth_mysql_user_configured": bool(MYSQL_USER),
        "auth_mysql_password_configured": bool(MYSQL_PASSWORD),
        "auth_mysql_database_configured": bool(MYSQL_DATABASE),
    }

def validate_startup_paths() -> List[str]:
    warnings: List[str] = []
    validation = validate_basic_config()

    for item in validation.get("warnings", []):
        code = item.get("code", "warning")
        message = item.get("message", "")
        path = item.get("path")
        warnings.append(f"{code}: {message}" + (f" ({path})" if path else ""))

    for item in validation.get("errors", []):
        code = item.get("code", "error")
        message = item.get("message", "")
        path = item.get("path")
        warnings.append(f"{code}: {message}" + (f" ({path})" if path else ""))

    return warnings

def get_cache_path(cache_key: str) -> Path:
    """
    คืน path ของ cache file ตาม cache key

    Args:
        cache_key:
            key เช่น company_unified_master, policy_fact, flood_summary

    Returns:
        Path:
            path เต็มของ cache file
    """

    normalized_key = str(cache_key or "").strip()

    for registry_key, registry_item in CACHE_REGISTRY.items():
        aliases = registry_item.get("aliases", [])
        if normalized_key == registry_key or normalized_key in aliases:
            filename = registry_item.get("filename") or CACHE_FILES.get(registry_key)
            return CACHE_DIR / str(filename)

    filename = CACHE_FILES.get(normalized_key)

    if not filename:
        safe_key = normalized_key.replace("/", "_").replace("\\", "_")
        filename = f"{safe_key}.json"

    return CACHE_DIR / filename


def get_package_folder(package_id: str) -> Path:
    """
    คืน path folder ของ package ตาม package_id
    """

    safe_package_id = str(package_id).strip().replace("/", "_").replace("\\", "_")
    return PACKAGE_DIR / safe_package_id


def get_package_data_folder(package_id: str) -> Path:
    """
    คืน path data folder ภายใน package
    """

    return get_package_folder(package_id) / "data"


def get_package_zip_path(package_id: str) -> Path:
    """
    คืน path zip file ของ package
    """

    safe_package_id = str(package_id).strip().replace("/", "_").replace("\\", "_")
    return PACKAGE_ZIP_DIR / f"{safe_package_id}.zip"


def get_export_history_path() -> Path:
    """
    คืน path export history file
    """

    return EXPORT_HISTORY_DIR / CACHE_FILES["export_history"]


def get_log_path(filename: Optional[str] = None) -> Path:
    """
    คืน path log file
    """

    if filename:
        safe_filename = str(filename).strip().replace("/", "_").replace("\\", "_")
        return LOG_DIR / safe_filename

    return LOG_PATH


# ============================================================
# 24) STATUS HELPERS
# ============================================================

def get_input_file_status() -> Dict[str, Any]:
    """
    ตรวจสถานะไฟล์ input หลักของระบบ

    ใช้โดย:
    - /api/status
    - /api/health
    - data_quality.py
    """

    latest_prediction_file = find_latest_prediction_file()

    return {
        "policy": {
            "expected_path": str(POLICY_INPUT_PATH),
            "exists": POLICY_INPUT_PATH.exists(),
            "filename": POLICY_INPUT_FILENAME,
        },
        "linkage": {
            "expected_path": str(LINKAGE_INPUT_PATH),
            "exists": LINKAGE_INPUT_PATH.exists(),
            "filename": LINKAGE_INPUT_FILENAME,
        },
        "data_source": validate_data_source_config(),
        "flood": {
            "output_dir": str(FLOOD_OUTPUT_DIR),
            "output_dir_exists": FLOOD_OUTPUT_DIR.exists(),
            "pipeline_base_dir": str(FLOOD_PIPELINE_BASE_DIR),
            "pipeline_base_dir_exists": FLOOD_PIPELINE_BASE_DIR.exists(),
            "pipeline_output_dir": str(PIPELINE_OUTPUT_DIR),
            "pipeline_output_dir_exists": PIPELINE_OUTPUT_DIR.exists(),
            "excel_database_dir": str(FLOOD_EXCEL_DATABASE_DIR),
            "excel_database_dir_exists": FLOOD_EXCEL_DATABASE_DIR.exists(),
            "latest_database_path": str(FLOOD_LATEST_DATABASE_PATH),
            "latest_database_exists": FLOOD_LATEST_DATABASE_PATH.exists(),
            "master_database_path": str(FLOOD_MASTER_DATABASE_PATH),
            "master_database_exists": FLOOD_MASTER_DATABASE_PATH.exists(),
            "history_dir": str(FLOOD_HISTORY_DIR),
            "history_dir_exists": FLOOD_HISTORY_DIR.exists(),
            "prediction_dir": str(FLOOD_PREDICTION_DIR),
            "prediction_dir_exists": FLOOD_PREDICTION_DIR.exists(),
            "latest_prediction_file": str(latest_prediction_file) if latest_prediction_file else None,
            "latest_prediction_file_exists": latest_prediction_file.exists() if latest_prediction_file else False,
        },
        "upload": {
            "upload_dir": str(UPLOAD_DIR),
            "upload_dir_exists": UPLOAD_DIR.exists(),
            "upload_entity_dir": str(UPLOAD_ENTITY_DIR),
            "upload_entity_dir_exists": UPLOAD_ENTITY_DIR.exists(),
            "upload_log_dir": str(UPLOAD_LOG_DIR),
            "upload_log_dir_exists": UPLOAD_LOG_DIR.exists(),
            "upload_error_report_dir": str(UPLOAD_ERROR_REPORT_DIR),
            "upload_error_report_dir_exists": UPLOAD_ERROR_REPORT_DIR.exists(),
        },
    }


def get_system_path_status() -> Dict[str, Any]:
    """
    ตรวจสถานะ path สำคัญของระบบ
    """

    return {
        "project_root": str(PROJECT_ROOT),
        "backend_dir": str(BACKEND_DIR),
        "frontend_dir": str(FRONTEND_DIR),
        "input_dir": str(INPUT_DIR),
        "cache_dir": str(CACHE_DIR),
        "output_dir": str(OUTPUT_DIR),
        "export_dir": str(EXPORT_DIR),
        "package_dir": str(PACKAGE_DIR),
        "log_dir": str(LOG_DIR),
        "data_quality_output_dir": str(DATA_QUALITY_OUTPUT_DIR),

        "flood_pipeline_base_dir": str(FLOOD_PIPELINE_BASE_DIR),
        "pipeline_base_dir": str(PIPELINE_BASE_DIR),
        "pipeline_output_dir": str(PIPELINE_OUTPUT_DIR),
        "flood_output_dir": str(FLOOD_OUTPUT_DIR),
        "flood_excel_database_dir": str(FLOOD_EXCEL_DATABASE_DIR),
        "excel_database_dir": str(EXCEL_DATABASE_DIR),
        "flood_latest_dir": str(FLOOD_LATEST_DIR),
        "flood_master_dir": str(FLOOD_MASTER_DIR),
        "flood_history_dir": str(FLOOD_HISTORY_DIR),
        "flood_latest_database_path": str(FLOOD_LATEST_DATABASE_PATH),
        "flood_master_database_path": str(FLOOD_MASTER_DATABASE_PATH),
        "flood_prediction_dir": str(FLOOD_PREDICTION_DIR),
        "prediction_data_dir": str(PREDICTION_DATA_DIR),

        "web_data_dir": str(WEB_DATA_DIR),
        "upload_dir": str(UPLOAD_DIR),
        "upload_entity_dir": str(UPLOAD_ENTITY_DIR),
        "upload_log_dir": str(UPLOAD_LOG_DIR),
        "upload_error_report_dir": str(UPLOAD_ERROR_REPORT_DIR),
        "web_cache_dir": str(WEB_CACHE_DIR),
        "web_log_dir": str(WEB_LOG_DIR),
    }

def get_config_summary() -> Dict[str, Any]:
    """
    คืน summary config สำหรับ API /api/config

    ไม่คืนค่า secret/password/token โดยตรง
    """

    return {
        "app": {
            "name": APP_NAME,
            "short_name": APP_SHORT_NAME,
            "version": APP_VERSION,
            "description": APP_DESCRIPTION,
            "env": DEFAULT_ENV,
            "debug": DEBUG,
            "testing": TESTING,
            "timezone": DEFAULT_TIMEZONE,
            "flood_app_name": FLOOD_APP_NAME,
            "flood_module_enabled": FLOOD_MODULE_ENABLED,
        },
        "data_source": validate_data_source_config(),
        "api": {
            "api_prefix": API_PREFIX,
            "public_api_prefix": PUBLIC_API_PREFIX,
            "cors_enabled": CORS_ENABLED,
            "cors_allow_origins": CORS_ALLOW_ORIGINS,
            "json_as_ascii": JSON_AS_ASCII,
            "json_sort_keys": JSON_SORT_KEYS,
        },
        "auth": {
            "enabled": AUTH_ENABLED,
            "fixed_users_enabled": AUTH_FIXED_USERS_ENABLED,
            "fixed_usernames": list(AUTH_FIXED_USERNAMES),
            "roles": list(AUTH_ROLES),
            "role_level": dict(AUTH_ROLE_LEVEL),
            "mysql": {
                "host": MYSQL_HOST,
                "port": MYSQL_PORT,
                "user": MYSQL_USER,
                "database": MYSQL_DATABASE,
                "charset": MYSQL_CHARSET,
                "users_table": AUTH_MYSQL_TABLE_USERS,
                "audit_logs_table": AUTH_MYSQL_TABLE_AUDIT_LOGS,
                "auto_create": AUTH_DB_AUTO_CREATE,
                "auto_seed": AUTH_DB_AUTO_SEED,
                "password_configured": bool(MYSQL_PASSWORD),
            },
            "jwt": {
                "algorithm": JWT_ALGORITHM,
                "expire_minutes": JWT_EXPIRE_MINUTES,
                "issuer": JWT_ISSUER,
                "audience": JWT_AUDIENCE,
                "clock_skew_seconds": JWT_CLOCK_SKEW_SECONDS,
                "secret_configured": bool(JWT_SECRET_KEY),
                "secret_uses_default": JWT_SECRET_KEY == "tipx-development-secret-key-change-in-production",
            },
            "password_hash": {
                "scheme": PASSWORD_HASH_SCHEME,
                "iterations": PASSWORD_HASH_ITERATIONS,
                "salt_bytes": PASSWORD_HASH_SALT_BYTES,
                "pepper_configured": bool(PASSWORD_HASH_PEPPER),
            },
            "route_guard": {
                "protect_internal_api": AUTH_PROTECT_INTERNAL_API,
                "protected_api_prefix": AUTH_PROTECTED_API_PREFIX,
                "public_exact_path_count": len(AUTH_PUBLIC_EXACT_PATHS),
                "public_prefix_count": len(AUTH_PUBLIC_PREFIXES),
                "role_rule_count": len(AUTH_ROLE_ROUTE_RULES),
                "skip_options_request": AUTH_SKIP_OPTIONS_REQUEST,
            },
            "frontend": {
                "enabled": FRONTEND_AUTH_ENABLED,
                "login_path": FRONTEND_LOGIN_PATH,
                "default_after_login_path": FRONTEND_DEFAULT_AFTER_LOGIN_PATH,
                "role_home_paths": FRONTEND_ROLE_HOME_PATHS,
                "public_routes": FRONTEND_PUBLIC_ROUTES,
                "role_route_rule_count": len(FRONTEND_ROLE_ROUTE_RULES),
            },
            "audit": {
                "enabled": AUDIT_ENABLED,
                "log_success_reads": AUDIT_LOG_SUCCESS_READS,
                "log_request_body": AUDIT_LOG_REQUEST_BODY,
                "log_response_body": AUDIT_LOG_RESPONSE_BODY,
                "log_ip_address": AUDIT_LOG_IP_ADDRESS,
                "log_user_agent": AUDIT_LOG_USER_AGENT,
                "action_rule_count": len(AUDIT_ACTION_PATH_RULES),
            },
        },
        "paths": get_system_path_status(),
        "inputs": get_input_file_status(),
        "cache": {
            "enabled": CACHE_ENABLED,
            "ttl_seconds": CACHE_TTL_SECONDS,
            "cache_dir": str(CACHE_DIR),
            "cache_registry_keys": sorted(CACHE_REGISTRY.keys()),
        },
        "flood": {
            "latest_sheets": FLOOD_LATEST_SHEETS,
            "master_sheets": FLOOD_MASTER_SHEETS,
            "history_sheets": FLOOD_HISTORY_SHEETS,
            "history_dirs": {key: str(value) for key, value in HISTORY_DIRS.items()},
            "prediction_file_glob": PREDICTION_FILE_GLOB,
            "prediction_file_pattern": PREDICTION_FILE_PATTERN,
        },
        "upload": {
            "allowed_extensions": UPLOAD_ALLOWED_EXTENSIONS,
            "max_content_length_mb": UPLOAD_MAX_CONTENT_LENGTH_MB,
            "entity_required_columns": ENTITY_REQUIRED_COLUMNS,
            "entity_supported_columns": ENTITY_SUPPORTED_COLUMNS,
        },
        "dashboard": {
            "default_page": DASHBOARD_DEFAULT_PAGE,
            "pages": DASHBOARD_PAGES,
            "default_table_page_size": DEFAULT_TABLE_PAGE_SIZE,
            "max_table_page_size": MAX_TABLE_PAGE_SIZE,
        },
        "map": {
            "default_center": DEFAULT_MAP_CENTER,
            "default_zoom": DEFAULT_MAP_ZOOM,
            "min_zoom": DEFAULT_MAP_MIN_ZOOM,
            "max_zoom": DEFAULT_MAP_MAX_ZOOM,
            "default_active_layers": DEFAULT_ACTIVE_LAYERS,
            "supported_layers": SUPPORTED_LAYERS,
            "layer_display_names": LAYER_DISPLAY_NAMES,
        },
        "graph": {
            "default_mode": GRAPH_DEFAULT_MODE,
            "default_depth": GRAPH_DEFAULT_DEPTH,
            "default_max_nodes": GRAPH_DEFAULT_MAX_NODES,
            "hard_max_nodes": GRAPH_HARD_MAX_NODES,
            "default_max_edges": GRAPH_DEFAULT_MAX_EDGES,
        },
        "package": {
            "default_expire_days": PACKAGE_DEFAULT_EXPIRE_DAYS,
            "max_expire_days": PACKAGE_MAX_EXPIRE_DAYS,
            "components": PACKAGE_COMPONENTS,
            "public_read_only": PUBLIC_PACKAGE_READ_ONLY,
        },
    }

# ============================================================
# 25) VALIDATION HELPERS
# ============================================================
def validate_basic_config() -> Dict[str, Any]:
    """
    ตรวจ config พื้นฐาน

    ไม่ถือว่าไฟล์ input หายแล้วระบบต้องล่มเสมอ
    เพราะบาง module อาจยังทำงานได้

    Return:
        dict:
            status, errors, warnings
    """

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    data_source_status = validate_data_source_config()

    if data_source_status["status"] == "error":
        errors.extend(data_source_status.get("errors", []))

    if data_source_status["status"] == "warning":
        warnings.extend(data_source_status.get("warnings", []))

    if not PROJECT_ROOT.exists():
        errors.append(
            {
                "code": "project_root_missing",
                "message": "ไม่พบ PROJECT_ROOT",
                "path": str(PROJECT_ROOT),
            }
        )

    if not BACKEND_DIR.exists():
        errors.append(
            {
                "code": "backend_dir_missing",
                "message": "ไม่พบ backend directory",
                "path": str(BACKEND_DIR),
            }
        )

    if not POLICY_INPUT_PATH.exists():
        warnings.append(
            {
                "code": "policy_input_missing",
                "message": "ไม่พบไฟล์ Policy Input",
                "path": str(POLICY_INPUT_PATH),
            }
        )

    if not LINKAGE_INPUT_PATH.exists():
        warnings.append(
            {
                "code": "linkage_input_missing",
                "message": "ไม่พบไฟล์ Linkage Input",
                "path": str(LINKAGE_INPUT_PATH),
            }
        )

    if USE_EXCEL_DATA_SOURCE:
        if not config_path_exists(FLOOD_OUTPUT_DIR):
            warnings.append(
                {
                    "code": "flood_output_dir_missing",
                    "message": "ไม่พบ Flood Output Directory",
                    "path": str(FLOOD_OUTPUT_DIR),
                }
            )

        if not config_path_exists(FLOOD_EXCEL_DATABASE_DIR):
            warnings.append(
                {
                    "code": "flood_excel_database_dir_missing",
                    "message": "ไม่พบ Flood Excel Database Directory",
                    "path": str(FLOOD_EXCEL_DATABASE_DIR),
                }
            )

        if not config_path_exists(FLOOD_LATEST_DATABASE_PATH):
            warnings.append(
                {
                    "code": "flood_latest_database_missing",
                    "message": "ไม่พบ latest_database.xlsx",
                    "path": str(FLOOD_LATEST_DATABASE_PATH),
                }
            )

        if not config_path_exists(FLOOD_MASTER_DATABASE_PATH):
            warnings.append(
                {
                    "code": "flood_master_database_missing",
                    "message": "ไม่พบ master_database.xlsx",
                    "path": str(FLOOD_MASTER_DATABASE_PATH),
                }
            )

        if not config_path_exists(FLOOD_HISTORY_DIR):
            warnings.append(
                {
                    "code": "flood_history_dir_missing",
                    "message": "ไม่พบ Flood History Directory",
                    "path": str(FLOOD_HISTORY_DIR),
                }
            )

        if not config_path_exists(FLOOD_PREDICTION_DIR):
            warnings.append(
                {
                    "code": "flood_prediction_dir_missing",
                    "message": "ไม่พบ Flood Prediction Directory",
                    "path": str(FLOOD_PREDICTION_DIR),
                }
            )

    if CORS_ALLOW_CREDENTIALS and "*" in CORS_ALLOW_ORIGINS:
        errors.append({
            "code": "cors_wildcard_credentials",
            "message": "Wildcard CORS origin cannot be used with credentials.",
        })

    if DEFAULT_ENV in {"production", "prod"} and not CORS_ALLOW_ORIGINS:
        warnings.append({
            "code": "cors_origins_empty",
            "message": "No production CORS origins are configured.",
        })

    if ENABLE_PACKAGE_ACCESS_TOKEN:
        if not SECRET_KEY:
            errors.append({
                "code": "package_secret_missing",
                "message": "TIPX_SECRET_KEY is required when package access tokens are enabled.",
            })
        if not PACKAGE_TOKEN_SALT:
            errors.append({
                "code": "package_token_salt_missing",
                "message": "TIPX_PACKAGE_TOKEN_SALT is required when package access tokens are enabled.",
            })

    if AUTH_ENABLED:
        if not MYSQL_HOST:
            errors.append(
                {
                    "code": "auth_mysql_host_missing",
                    "message": "MYSQL_HOST is required when AUTH_ENABLED=true",
                }
            )

        if not MYSQL_PORT:
            errors.append(
                {
                    "code": "auth_mysql_port_missing",
                    "message": "MYSQL_PORT is required when AUTH_ENABLED=true",
                }
            )

        if not MYSQL_USER:
            errors.append(
                {
                    "code": "auth_mysql_user_missing",
                    "message": "MYSQL_USER is required when AUTH_ENABLED=true",
                }
            )

        if not MYSQL_PASSWORD:
            errors.append(
                {
                    "code": "auth_mysql_password_missing",
                    "message": "MYSQL_PASSWORD is required when AUTH_ENABLED=true",
                }
            )

        if not MYSQL_DATABASE:
            errors.append(
                {
                    "code": "auth_mysql_database_missing",
                    "message": "MYSQL_DATABASE is required when AUTH_ENABLED=true",
                }
            )

        if JWT_SECRET_KEY in {
            "",
            "tipx-development-secret-key-change-in-production",
        }:
            warnings.append(
                {
                    "code": "jwt_secret_key_default",
                    "message": "JWT_SECRET_KEY ยังเป็นค่า default ควรเปลี่ยนใน production",
                }
            )

        if SECRET_KEY == "tipx-development-secret-key-change-in-production":
            warnings.append(
                {
                    "code": "secret_key_default",
                    "message": "TIPX_SECRET_KEY ยังเป็นค่า default ควรเปลี่ยนใน production",
                }
            )

        if PASSWORD_HASH_SCHEME != "pbkdf2_sha256":
            warnings.append(
                {
                    "code": "password_hash_scheme_not_default",
                    "message": f"PASSWORD_HASH_SCHEME={PASSWORD_HASH_SCHEME}",
                }
            )

        if PASSWORD_HASH_ITERATIONS < 100000:
            warnings.append(
                {
                    "code": "password_hash_iterations_low",
                    "message": "PASSWORD_HASH_ITERATIONS ควรมากกว่า 100000",
                    "actual": PASSWORD_HASH_ITERATIONS,
                }
            )

        fixed_user_roles = [
            item.get("role")
            for item in AUTH_FIXED_USERS
            if isinstance(item, dict)
        ]

        for required_role in AUTH_ROLES:
            if required_role not in fixed_user_roles:
                errors.append(
                    {
                        "code": "auth_fixed_user_role_missing",
                        "message": f"ไม่พบ fixed user สำหรับ role={required_role}",
                    }
                )

        for fixed_user in AUTH_FIXED_USERS:
            username = fixed_user.get("username") if isinstance(fixed_user, dict) else ""
            password = fixed_user.get("password") if isinstance(fixed_user, dict) else ""
            role = fixed_user.get("role") if isinstance(fixed_user, dict) else ""

            if not username:
                errors.append(
                    {
                        "code": "auth_fixed_username_missing",
                        "message": f"fixed user role={role} ไม่มี username",
                    }
                )

            if not password:
                errors.append(
                    {
                        "code": "auth_fixed_password_missing",
                        "message": f"fixed user username={username} ไม่มี password",
                    }
                )

            if str(password).startswith("change-me-"):
                warnings.append(
                    {
                        "code": "auth_fixed_password_default",
                        "message": f"password ของ fixed user username={username} ยังเป็นค่า default",
                    }
                )

            if role not in AUTH_ROLES:
                errors.append(
                    {
                        "code": "auth_fixed_role_invalid",
                        "message": f"fixed user username={username} มี role ไม่ถูกต้อง",
                        "actual": role,
                        "allowed_roles": AUTH_ROLES,
                    }
                )

        if not AUTH_ROLE_ROUTE_RULES:
            warnings.append(
                {
                    "code": "auth_role_route_rules_empty",
                    "message": "AUTH_ROLE_ROUTE_RULES ว่าง ทำให้ role guard คุม route ไม่ละเอียด",
                }
            )

        if AUDIT_ENABLED and not AUTH_MYSQL_TABLE_AUDIT_LOGS:
            errors.append(
                {
                    "code": "audit_table_missing",
                    "message": "AUTH_MYSQL_TABLE_AUDIT_LOGS is required when AUDIT_ENABLED=true",
                }
            )

    status = "ok"

    if warnings:
        status = "degraded"

    if errors:
        status = "error"

    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "features": {
            "auth_enabled": AUTH_ENABLED,
            "auth_ready": bool(AUTH_ENABLED and not any(item.get("code", "").startswith("auth_") for item in errors)),
            "package_token_enabled": ENABLE_PACKAGE_ACCESS_TOKEN,
            "package_security_ready": bool(not ENABLE_PACKAGE_ACCESS_TOKEN or (SECRET_KEY and PACKAGE_TOKEN_SALT)),
            "excel_source_enabled": USE_EXCEL_DATA_SOURCE,
            "mysql_business_source_enabled": USE_MYSQL_DATA_SOURCE,
        },
    }

# ============================================================
# 26) FLASK CONFIG CLASS
# ============================================================

class FlaskConfig:
    """
    Legacy config class สำหรับ Flask transition

    คงไว้ชั่วคราวระหว่าง migration ไป FastAPI
    """

    SECRET_KEY = SECRET_KEY

    DEBUG = DEBUG
    TESTING = TESTING

    JSON_SORT_KEYS = JSON_SORT_KEYS
    JSON_AS_ASCII = JSON_AS_ASCII

    MAX_CONTENT_LENGTH = MAX_CONTENT_LENGTH_MB * 1024 * 1024

    TIPX_APP_NAME = APP_NAME
    TIPX_APP_SHORT_NAME = APP_SHORT_NAME
    TIPX_APP_VERSION = APP_VERSION
    TIPX_ENV = DEFAULT_ENV

    TIPX_API_PREFIX = API_PREFIX
    TIPX_PUBLIC_API_PREFIX = PUBLIC_API_PREFIX

    TIPX_PROJECT_ROOT = str(PROJECT_ROOT)
    TIPX_INPUT_DIR = str(INPUT_DIR)
    TIPX_CACHE_DIR = str(CACHE_DIR)
    TIPX_OUTPUT_DIR = str(OUTPUT_DIR)
    TIPX_EXPORT_DIR = str(EXPORT_DIR)
    TIPX_PACKAGE_DIR = str(PACKAGE_DIR)

    TIPX_POLICY_INPUT_PATH = str(POLICY_INPUT_PATH)
    TIPX_LINKAGE_INPUT_PATH = str(LINKAGE_INPUT_PATH)

    TIPX_USE_EXCEL_DATA_SOURCE = USE_EXCEL_DATA_SOURCE
    TIPX_USE_MYSQL_DATA_SOURCE = USE_MYSQL_DATA_SOURCE
    TIPX_ACTIVE_DATA_SOURCE = get_active_data_source()

    TIPX_FLOOD_OUTPUT_DIR = str(FLOOD_OUTPUT_DIR)
    TIPX_FLOOD_EXCEL_DATABASE_DIR = str(FLOOD_EXCEL_DATABASE_DIR)
    TIPX_FLOOD_LATEST_DATABASE_PATH = str(FLOOD_LATEST_DATABASE_PATH)
    TIPX_FLOOD_MASTER_DATABASE_PATH = str(FLOOD_MASTER_DATABASE_PATH)
    TIPX_FLOOD_HISTORY_DIR = str(FLOOD_HISTORY_DIR)
    TIPX_FLOOD_PREDICTION_DIR = str(FLOOD_PREDICTION_DIR)

    TIPX_UPLOAD_ENTITY_DIR = str(UPLOAD_ENTITY_DIR)

    TIPX_CACHE_ENABLED = CACHE_ENABLED

    TIPX_AUTH_ENABLED = AUTH_ENABLED
    TIPX_AUTH_FIXED_USERS_ENABLED = AUTH_FIXED_USERS_ENABLED
    TIPX_AUTH_ROLES = AUTH_ROLES
    TIPX_AUTH_PUBLIC_EXACT_PATHS = AUTH_PUBLIC_EXACT_PATHS
    TIPX_AUTH_PUBLIC_PREFIXES = AUTH_PUBLIC_PREFIXES
    TIPX_AUTH_ROLE_ROUTE_RULES = AUTH_ROLE_ROUTE_RULES

    TIPX_MYSQL_HOST = MYSQL_HOST
    TIPX_MYSQL_PORT = MYSQL_PORT
    TIPX_MYSQL_USER = MYSQL_USER
    TIPX_MYSQL_DATABASE = MYSQL_DATABASE
    TIPX_MYSQL_CHARSET = MYSQL_CHARSET

    TIPX_JWT_ALGORITHM = JWT_ALGORITHM
    TIPX_JWT_EXPIRE_MINUTES = JWT_EXPIRE_MINUTES
    TIPX_JWT_ISSUER = JWT_ISSUER
    TIPX_JWT_AUDIENCE = JWT_AUDIENCE

    TIPX_AUDIT_ENABLED = AUDIT_ENABLED
    TIPX_AUDIT_ACTION_PATH_RULES = AUDIT_ACTION_PATH_RULES


# ============================================================
# 27) INITIAL DIRECTORY CREATION
# ============================================================

if os.getenv("TIPX_AUTO_CREATE_DIRS", "false").strip().lower() in {"1", "true", "yes", "y"}:
    ensure_directories()
