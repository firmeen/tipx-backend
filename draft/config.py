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
try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)
import os
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
DEBUG: bool = os.getenv("TIPX_DEBUG", "true").strip().lower() in {"1", "true", "yes", "y"}
TESTING: bool = os.getenv("TIPX_TESTING", "false").strip().lower() in {"1", "true", "yes", "y"}

API_PREFIX: str = "/api"
PUBLIC_API_PREFIX: str = "/api/public"

DEFAULT_ENCODING: str = "utf-8"
DEFAULT_TIMEZONE: str = "Asia/Bangkok"


# ============================================================
# 2) PROJECT ROOT AND MAIN PATHS
# ============================================================

BACKEND_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = BACKEND_DIR.parent

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

POLICY_INPUT_FILENAME: str = os.getenv("policy", "policy_input.xlsx")
LINKAGE_INPUT_FILENAME: str = os.getenv("linkage", "linkage_input.xlsx")

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

DEFAULT_FLOOD_OUTPUT_DIR: str = r"C:/Users/afimeenu/project/flood/output_fl"

FLOOD_OUTPUT_DIR: Path = Path(
    os.getenv("TIPX_FLOOD_OUTPUT_DIR", DEFAULT_FLOOD_OUTPUT_DIR)
).expanduser()

FLOOD_LATEST_DIR: Path = FLOOD_OUTPUT_DIR / "latest"
FLOOD_MASTER_DIR: Path = FLOOD_OUTPUT_DIR / "master"
FLOOD_HISTORY_DIR: Path = FLOOD_OUTPUT_DIR / "history"

FLOOD_LATEST_DATABASE_PATH: Path = FLOOD_LATEST_DIR / "latest_database.xlsx"
FLOOD_MASTER_DATABASE_PATH: Path = FLOOD_MASTER_DIR / "master_database.xlsx"

FLOOD_HISTORY_RAINFALL_DIR: Path = FLOOD_HISTORY_DIR / "rainfall"
FLOOD_HISTORY_RAIN15D_DIR: Path = FLOOD_HISTORY_DIR / "rain15d"
FLOOD_HISTORY_RAIN_YEARLY_DIR: Path = FLOOD_HISTORY_DIR / "rain_yearly"
FLOOD_HISTORY_WATERLEVEL_DIR: Path = FLOOD_HISTORY_DIR / "waterlevel"
FLOOD_HISTORY_DAM_DIR: Path = FLOOD_HISTORY_DIR / "dam"
FLOOD_HISTORY_LARGE_DAM_DIR: Path = FLOOD_HISTORY_DAM_DIR / "large"
FLOOD_HISTORY_MEDIUM_DAM_DIR: Path = FLOOD_HISTORY_DAM_DIR / "medium"
FLOOD_HISTORY_ALL_LONG_DIR: Path = FLOOD_HISTORY_DIR / "all_long"


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
    "company_unified_master": "company_unified_master.json",

    "director_master": "director_master.json",
    "director_company_pairs": "director_company_pairs.json",
    "linkage_nodes": "linkage_nodes.json",
    "linkage_edges": "linkage_edges.json",
    "shared_director_links": "shared_director_links.json",
    "key_connector_summary": "key_connector_summary.json",
    "linkage_graph": "linkage_graph.json",

    "flood_latest": "flood_latest.json",
    "flood_master": "flood_master.json",
    "flood_computed_risk": "flood_computed_risk.json",
    "flood_summary": "flood_summary.json",

    "spatial_join_result": "spatial_join_result.json",
    "company_flood_context": "company_flood_context.json",
    "policy_flood_exposure": "policy_flood_exposure.json",
    "province_risk_summary": "province_risk_summary.json",

    "map_layers": "map_layers.json",
    "graph_payload": "graph_payload.json",
    "chart_payload": "chart_payload.json",
    "dashboard_summary": "dashboard_summary.json",

    "filter_fields": "filter_fields.json",
    "filter_presets": "filter_presets.json",

    "data_quality_summary": "data_quality_summary.json",
    "data_quality_issues": "data_quality_issues.json",

    "package_index": "package_index.json",
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


FLOOD_LATEST_SHEETS: Dict[str, str] = {
    "rainfall_latest": "02_rainfall_latest",
    "waterlevel_latest": "05_waterlevel_latest",
    "large_dam_latest": "07_large_dam_latest",
    "medium_dam_latest": "09_medium_dam_latest",
    "all_long_latest": "17_all_long_latest",
}


FLOOD_MASTER_SHEETS: Dict[str, str] = {
    "meta_info": "00_meta_info",
    "scrape_runs": "01_scrape_runs",
    "province_boundary": "11_province_boundary",
    "basin_boundary": "12_basin_boundary",
    "rainfall_station_master": "13_rainfall_station_master",
    "waterlevel_station_master": "14_waterlevel_station_master",
    "dam_reservoir_master": "15_dam_reservoir_master",
    "location_master": "16_location_master",
    "endpoint_master": "18_endpoint_master",
    "data_quality_log": "19_data_quality_log",
    "error_log": "20_error_log",
    "raw_file_index": "21_raw_file_index",
    "move_log": "22_move_log",
    "telestation_list_master": "23_telestation_list_master",
    "daily_loop_runs": "24_daily_loop_runs",
    "daily_loop_rounds": "25_daily_loop_rounds",
}


FLOOD_HISTORY_SHEETS: Dict[str, str] = {
    "rainfall_daily_history": "03_rainfall_daily_history",
    "rain15d_history": "26_rainfall_15d_history",
    "rain_yearly_summary": "04_rainfall_yearly_summary",
    "waterlevel_history_yearly": "06_waterlevel_history_yearly",
    "large_dam_history_yearly": "08_large_dam_history_yearly",
    "medium_dam_history_yearly": "10_medium_dam_history_yearly",
    "all_long_history": "17_all_long_history",
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


STANDARD_FLOOD_RISK_FIELDS: List[str] = [
    "source_type",
    "source_id",
    "source_name",
    "province",
    "basin",
    "lat",
    "lon",
    "data_datetime",
    "risk_level",
    "risk_score",
    "risk_reason",
    "risk_color",
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

# Service-facing OpenLayers map aliases.
# Keep DEFAULT_MAP_* for existing config consumers, and expose MAP_* for
# map_graph_service.py import stability. Coordinates are (lon, lat).
MAP_DEFAULT_CENTER: Tuple[float, float] = (
    float(os.getenv("TIPX_MAP_DEFAULT_LON", str(DEFAULT_MAP_CENTER[0]))),
    float(os.getenv("TIPX_MAP_DEFAULT_LAT", str(DEFAULT_MAP_CENTER[1]))),
)
MAP_DEFAULT_ZOOM: int = int(os.getenv("TIPX_MAP_DEFAULT_ZOOM", str(DEFAULT_MAP_ZOOM)))
MAP_MIN_ZOOM: int = int(os.getenv("TIPX_MAP_MIN_ZOOM", str(DEFAULT_MAP_MIN_ZOOM)))
MAP_MAX_ZOOM: int = int(os.getenv("TIPX_MAP_MAX_ZOOM", str(DEFAULT_MAP_MAX_ZOOM)))
MAP_BASE_TILE_URL: str = os.getenv(
    "TIPX_MAP_BASE_TILE_URL",
    "https://{a-c}.tile.openstreetmap.org/{z}/{x}/{y}.png",
)
MAP_BASE_ATTRIBUTION: str = os.getenv(
    "TIPX_MAP_BASE_ATTRIBUTION",
    "© OpenStreetMap contributors",
)

# Layer keys follow the actual layer IDs used by map_graph_service.py.
MAP_LAYER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "province_boundaries": {
        "layer_name": "Province Boundaries",
        "label": "Province Boundaries",
        "visible": True,
        "z_index": 10,
        "opacity": 0.35,
        "layer_type": "polygon",
    },
    "basin_boundaries": {
        "layer_name": "Basin Boundaries",
        "label": "Basin Boundaries",
        "visible": False,
        "z_index": 11,
        "opacity": 0.3,
        "layer_type": "polygon",
    },
    "heatmap": {
        "layer_name": "Risk Heatmap",
        "label": "Risk Heatmap",
        "visible": False,
        "z_index": 20,
        "opacity": 0.65,
        "layer_type": "heatmap",
    },
    "flood_points": {
        "layer_name": "Flood Stations",
        "label": "Flood Stations",
        "visible": True,
        "z_index": 30,
        "opacity": 0.9,
        "layer_type": "point",
    },
    "policy_exposure": {
        "layer_name": "Policy Exposure",
        "label": "Policy Exposure",
        "visible": True,
        "z_index": 35,
        "opacity": 0.9,
        "layer_type": "point",
    },
    "company_points": {
        "layer_name": "Companies",
        "label": "Companies",
        "visible": True,
        "z_index": 40,
        "opacity": 1.0,
        "layer_type": "point",
    },
    "branch_points": {
        "layer_name": "Branches",
        "label": "Branches",
        "visible": True,
        "z_index": 45,
        "opacity": 1.0,
        "layer_type": "point",
    },
    "linkage_lines": {
        "layer_name": "Linkage Lines",
        "label": "Linkage Lines",
        "visible": False,
        "z_index": 50,
        "opacity": 0.7,
        "layer_type": "line",
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

SPATIAL_NEAREST_STATION_LIMIT_KM: float = float(
    os.getenv("TIPX_SPATIAL_NEAREST_STATION_LIMIT_KM", "50")
)
SPATIAL_COMPANY_FLOOD_RADIUS_KM: float = float(
    os.getenv("TIPX_SPATIAL_COMPANY_FLOOD_RADIUS_KM", "30")
)


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
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

JSON_SORT_KEYS: bool = False
JSON_AS_ASCII: bool = False
MAX_CONTENT_LENGTH_MB: int = 100


# ============================================================
# 19) SECURITY SETTINGS
# ============================================================

"""
security.py จะใช้ค่ากลุ่มนี้

หมายเหตุ:
ระบบนี้เป็น local/internal dashboard ก่อน
แต่เตรียมโครงสร้างสำหรับ package external viewer ไว้ด้วย
"""

SECRET_KEY: str = os.getenv("TIPX_SECRET_KEY", "tipx-development-secret-key-change-in-production")

PACKAGE_TOKEN_SALT: str = os.getenv("TIPX_PACKAGE_TOKEN_SALT", "tipx-package-salt-change-in-production")

ENABLE_PACKAGE_ACCESS_TOKEN: bool = os.getenv(
    "TIPX_ENABLE_PACKAGE_ACCESS_TOKEN", "false"
).strip().lower() in {"1", "true", "yes", "y"}

PUBLIC_PACKAGE_READ_ONLY: bool = True

MASK_TAX_ID_VISIBLE_LAST_DIGITS: int = 4
MASK_DIRECTOR_VISIBLE_FIRST_CHARS: int = 2


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

    flood_output_dir: Path = FLOOD_OUTPUT_DIR
    flood_latest_dir: Path = FLOOD_LATEST_DIR
    flood_master_dir: Path = FLOOD_MASTER_DIR
    flood_history_dir: Path = FLOOD_HISTORY_DIR
    flood_latest_database_path: Path = FLOOD_LATEST_DATABASE_PATH
    flood_master_database_path: Path = FLOOD_MASTER_DATABASE_PATH


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

GRAPH_COLORS: Dict[str, str] = {
    "company": "#38bdf8",
    "company_wtip": "#22c55e",
    "director": "#a855f7",
    "key_connector": "#facc15",
    "selected": "#f97316",
    "connected": "#fb7185",
    "director_of": "rgba(148, 163, 184, 0.42)",
    "shared_director": "rgba(56, 189, 248, 0.78)",
    "default": "#94a3b8",
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
]


def ensure_directories() -> List[str]:
    """
    สร้าง folder พื้นฐานที่ระบบ TIPX ต้องใช้

    Return:
        List[str]: รายชื่อ folder ที่ถูกสร้างหรือมีอยู่แล้ว
    """

    created_or_existing: List[str] = []

    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
        created_or_existing.append(str(directory))

    return created_or_existing


# ============================================================
# 23) PATH HELPERS
# ============================================================

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

    filename = CACHE_FILES.get(cache_key)

    if not filename:
        safe_key = str(cache_key).strip().replace("/", "_").replace("\\", "_")
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
        "flood": {
            "output_dir": str(FLOOD_OUTPUT_DIR),
            "output_dir_exists": FLOOD_OUTPUT_DIR.exists(),
            "latest_database_path": str(FLOOD_LATEST_DATABASE_PATH),
            "latest_database_exists": FLOOD_LATEST_DATABASE_PATH.exists(),
            "master_database_path": str(FLOOD_MASTER_DATABASE_PATH),
            "master_database_exists": FLOOD_MASTER_DATABASE_PATH.exists(),
            "history_dir": str(FLOOD_HISTORY_DIR),
            "history_dir_exists": FLOOD_HISTORY_DIR.exists(),
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
    }


def get_config_summary() -> Dict[str, Any]:
    """
    คืน summary config สำหรับ API /api/config

    ไม่คืนค่า secret โดยตรง
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
        },
        "api": {
            "api_prefix": API_PREFIX,
            "public_api_prefix": PUBLIC_API_PREFIX,
            "cors_enabled": CORS_ENABLED,
            "json_as_ascii": JSON_AS_ASCII,
            "json_sort_keys": JSON_SORT_KEYS,
        },
        "paths": get_system_path_status(),
        "inputs": get_input_file_status(),
        "cache": {
            "enabled": CACHE_ENABLED,
            "ttl_seconds": CACHE_TTL_SECONDS,
            "cache_dir": str(CACHE_DIR),
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

    if not FLOOD_OUTPUT_DIR.exists():
        warnings.append(
            {
                "code": "flood_output_dir_missing",
                "message": "ไม่พบ Flood Output Directory",
                "path": str(FLOOD_OUTPUT_DIR),
            }
        )

    if not FLOOD_LATEST_DATABASE_PATH.exists():
        warnings.append(
            {
                "code": "flood_latest_database_missing",
                "message": "ไม่พบ latest_database.xlsx",
                "path": str(FLOOD_LATEST_DATABASE_PATH),
            }
        )

    if not FLOOD_MASTER_DATABASE_PATH.exists():
        warnings.append(
            {
                "code": "flood_master_database_missing",
                "message": "ไม่พบ master_database.xlsx",
                "path": str(FLOOD_MASTER_DATABASE_PATH),
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
    }


# ============================================================
# 26) FLASK CONFIG CLASS
# ============================================================

class FlaskConfig:
    """
    Config class สำหรับ Flask app

    ใช้ใน app.py:
        app.config.from_object(FlaskConfig)
    """

    SECRET_KEY = SECRET_KEY

    DEBUG = DEBUG
    TESTING = TESTING

    JSON_SORT_KEYS = JSON_SORT_KEYS
    JSON_AS_ASCII = JSON_AS_ASCII

    MAX_CONTENT_LENGTH = MAX_CONTENT_LENGTH_MB * 1024 * 1024

    TIPX_APP_NAME = APP_NAME
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
    TIPX_FLOOD_OUTPUT_DIR = str(FLOOD_OUTPUT_DIR)

    TIPX_CACHE_ENABLED = CACHE_ENABLED


# ============================================================
# 27) INITIAL DIRECTORY CREATION
# ============================================================

if os.getenv("TIPX_AUTO_CREATE_DIRS", "true").strip().lower() in {"1", "true", "yes", "y"}:
    ensure_directories()