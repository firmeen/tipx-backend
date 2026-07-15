# ============================================================
# FILE: backend/schemas.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 4 / 20
# ============================================================

"""
backend/schemas.py

ไฟล์นี้เป็นศูนย์กลางของ Schema / Field Dictionary / Data Contract ทั้งหมดของระบบ TIPX

หน้าที่หลัก:
1. กำหนดโครงสร้างข้อมูลมาตรฐานของทุก pipeline
2. กำหนด field dictionary สำหรับ frontend และ filter builder
3. กำหนด schema ของ input file ทั้ง Flood / Policy / Linkage
4. กำหนด schema ของ output data model
5. กำหนด schema ของ API response
6. กำหนด schema ของ filter payload
7. กำหนด schema ของ package export
8. กำหนด schema ของ map layer / graph payload / dashboard payload
9. กำหนด helper สำหรับ validate schema แบบไม่ผูกกับ library หนัก
10. ทำหน้าที่แทน schemas/ หลายไฟล์จากโครงสร้าง Enterprise เดิม

โครงสร้างเดิมที่ถูกรวมมาในไฟล์นี้:
- schemas/field_dictionary.py
- schemas/input_schema.py
- schemas/output_schema.py
- schemas/filter_schema.py
- schemas/package_schema.py
- schemas/api_schema.py
- schemas/security_schema.py บางส่วน

Schema ที่รองรับ:
- Flood Input Schema
- Policy Input Schema
- Linkage Input Schema
- Company Unified Master Schema
- Policy Fact Schema
- Policy Summary Schema
- Linkage Graph Schema
- Director Master Schema
- Flood Computed Risk Schema
- Spatial Join Schema
- Map Layer Schema
- Dashboard Summary Schema
- Filter Builder Schema
- Package Export Schema
- External Viewer Schema
- Data Quality Schema
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field
from datetime import datetime
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple, Union


from config import (
    APP_SHORT_NAME,
    APP_VERSION,
    API_PREFIX,
    PUBLIC_API_PREFIX,
    RISK_LEVELS,
    LOSS_RATIO_BANDS,
    LOCATION_QUALITY_LEVELS,
    SPATIAL_JOIN_LEVELS,
    FILTER_OPERATORS,
    FILTER_LOGICAL_OPERATORS,
    PACKAGE_COMPONENTS,
    PACKAGE_SECURITY_OPTIONS,
    PACKAGE_DEFAULT_EXPIRE_DAYS,
    PACKAGE_MAX_EXPIRE_DAYS,
    DATA_QUALITY_SEVERITIES,
    DATA_QUALITY_CATEGORIES,
    PREDICTION_REQUIRED_COLUMNS,
    PREDICTION_SUPPORTED_COLUMNS,
    ENTITY_REQUIRED_COLUMNS,
    ENTITY_SUPPORTED_COLUMNS,
)


# ============================================================
# 1) BASIC TYPE ALIASES
# ============================================================

JSONDict = Dict[str, Any]
JSONList = List[JSONDict]
MaybeNumber = Optional[Union[int, float]]
MaybeString = Optional[str]


# ============================================================
# 2) COMMON FIELD DEFINITIONS
# ============================================================

@dataclass(frozen=True)
class FieldDefinition:
    """
    คำอธิบาย field กลางของระบบ

    ใช้โดย:
    - filter builder
    - frontend table
    - package export
    - data dictionary
    - validation
    """

    name: str
    label: str
    description: str = ""
    dtype: str = "string"
    group: str = "general"
    source: str = "computed"
    required: bool = False
    nullable: bool = True
    filterable: bool = False
    sortable: bool = False
    searchable: bool = False
    exportable: bool = True
    visible_default: bool = True
    sensitive: bool = False
    unit: str = ""
    example: Any = None
    allowed_values: Optional[List[Any]] = None


@dataclass(frozen=True)
class SheetSchema:
    """
    Schema ของ Excel Sheet

    ใช้กำหนด:
    - ชื่อ logical sheet
    - description
    - required fields
    - optional fields
    - fallback index
    """

    key: str
    display_name: str
    description: str
    required_columns: List[str] = dc_field(default_factory=list)
    optional_columns: List[str] = dc_field(default_factory=list)
    fallback_index: Optional[int] = None
    source_type: str = "excel"


@dataclass(frozen=True)
class DatasetSchema:
    """
    Schema ของ processed dataset

    เช่น:
    - company_unified_master
    - policy_fact
    - linkage_nodes
    - flood_computed_risk
    """

    key: str
    display_name: str
    description: str
    primary_key: Optional[str] = None
    fields: List[str] = dc_field(default_factory=list)
    required_fields: List[str] = dc_field(default_factory=list)
    default_sort: Optional[str] = None
    default_sort_dir: str = "asc"
    supports_filter: bool = True
    supports_search: bool = True
    supports_export: bool = True

@dataclass(frozen=True)
class DataSourceConfigSchema:
    active_source: str = "excel"
    excel_enabled: bool = True
    mysql_enabled: bool = False
    excel_paths: Dict[str, str] = dc_field(default_factory=dict)
    mysql_status: str = "placeholder_not_implemented"
    validation: Dict[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class FloodLatestRecord:
    source_type: str
    source_id: str
    source_name: str = ""
    province: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    latest_value: Optional[float] = None
    latest_unit: str = ""
    risk_level: str = "Unknown"
    risk_reason: str = ""
    data_datetime: str = ""


@dataclass(frozen=True)
class FloodPredictionRecord:
    record_key: str
    station_name: str = ""
    station_id: str = ""
    station_code: str = ""
    matched_station_id: str = ""
    matched_station_code: str = ""
    matched_station_name: str = ""
    province: str = ""
    province_model: str = ""
    base_date: str = ""
    target_date: str = ""
    forecast_horizon_day: Optional[int] = None
    risk_level: str = "Unknown"
    risk_status: str = ""
    warning_level: str = ""
    warning_level_predict: str = ""
    predicted_level_m: Optional[float] = None
    latest_value: Optional[float] = None
    latest_unit: str = ""
    percent_to_bank: Optional[float] = None
    from_bank_m: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    map_ready: bool = False
    focus_level: str = ""
    focus_fallback: str = ""
    focus_fallback_reason: str = ""


@dataclass(frozen=True)
class UploadedEntityRecord:
    upload_id: str = ""
    entity_id: str = ""
    entity_type: str = ""
    entity_name_th: str = ""
    entity_name_en: str = ""
    province_name_th: str = ""
    province: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    risk_group: str = "Unknown"
    risk_level: str = "Unknown"
    source_type: str = "uploaded_entity"
    map_ready: bool = False
    has_location: bool = False
    is_displayable: bool = False
    validation_reasons: List[str] = dc_field(default_factory=list)


@dataclass(frozen=True)
class MapLayerPayloadSchema:
    layer_id: str
    layer_name: str = ""
    layer_type: str = "point"
    visible: bool = True
    opacity: float = 1.0
    z_index: int = 0
    records: List[Dict[str, Any]] = dc_field(default_factory=list)
    features: Dict[str, Any] = dc_field(default_factory=lambda: {"type": "FeatureCollection", "features": []})
    feature_collection: Dict[str, Any] = dc_field(default_factory=lambda: {"type": "FeatureCollection", "features": []})
    total: int = 0
    record_count: int = 0
    style: Dict[str, Any] = dc_field(default_factory=dict)
    meta: Dict[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class DashboardProvinceInsightsSchema:
    prediction_risk_top3: List[Dict[str, Any]] = dc_field(default_factory=list)
    rainfall_top5: List[Dict[str, Any]] = dc_field(default_factory=list)
    waterlevel_top5: List[Dict[str, Any]] = dc_field(default_factory=list)
    reservoir_top5: List[Dict[str, Any]] = dc_field(default_factory=list)
    filters: Dict[str, Any] = dc_field(default_factory=dict)
    generated_at: str = ""


@dataclass(frozen=True)
class CacheRegistryItemSchema:
    cache_key: str
    owner_service: str = ""
    payload_type: str = "json"
    depends_on: List[str] = dc_field(default_factory=list)
    consumed_by: List[str] = dc_field(default_factory=list)
    critical: bool = False
    allow_stale: bool = False
    aliases: List[str] = dc_field(default_factory=list)


@dataclass(frozen=True)
class RebuildPhaseResultSchema:
    phase: str
    status: str = "pending"
    outputs: Dict[str, Any] = dc_field(default_factory=dict)
    errors: List[Dict[str, Any]] = dc_field(default_factory=list)
    warnings: List[Dict[str, Any]] = dc_field(default_factory=list)
    duration_ms: Optional[int] = None


# ============================================================
# 3) STANDARD API RESPONSE SCHEMA
# ============================================================

@dataclass
class ApiMeta:
    """
    meta ของ API response ทุก endpoint
    """

    timestamp: str = dc_field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    app: str = APP_SHORT_NAME
    version: str = APP_VERSION
    module: str = ""
    service: str = ""
    record_count: Optional[int] = None
    page: Optional[int] = None
    page_size: Optional[int] = None
    total: Optional[int] = None
    cache_used: Optional[bool] = None
    fallback: Optional[bool] = None
    source: Optional[str] = None


@dataclass
class ApiResponseSchema:
    """
    รูปแบบ response กลางของระบบ TIPX

    ทุก API ควรตอบกลับในรูปแบบนี้
    """

    success: bool
    message: str
    data: Any = dc_field(default_factory=dict)
    meta: Dict[str, Any] = dc_field(default_factory=dict)
    errors: List[Any] = dc_field(default_factory=list)


def make_api_schema_example() -> Dict[str, Any]:
    """
    ตัวอย่าง API response
    """

    return {
        "success": True,
        "message": "OK",
        "data": {},
        "meta": {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "app": APP_SHORT_NAME,
            "version": APP_VERSION,
            "module": "example",
            "record_count": 0,
            "cache_used": False,
        },
        "errors": [],
    }


# ============================================================
# 4) FIELD DICTIONARY
# ============================================================

RUNTIME_FILTER_TARGETS: List[str] = [
    "company",
    "policy",
    "linkage",
    "director",
    "flood",
    "spatial",
    "map",
    "dashboard",
    "data_quality",
    "package",
    "flood_rainfall_latest",
    "flood_waterlevel_latest",
    "flood_dam_latest",
    "flood_prediction_latest",
    "flood_prediction_map",
    "uploaded_entity_latest",
    "map_layers",
    "dashboard_province_insights",
    "prediction_map_view",
    "entity_overlay_view",
    "flood_dashboard_view",
    "province_insight_view",
]

INTERNAL_NON_EXPORTABLE_FIELDS: set[str] = {
    "source_file",
    "source_file_path",
    "internal_path",
    "cache_file",
    "cache_path",
    "raw_file_path",
    "upload_dir",
    "saved_file",
    "error_report_file",
    "debug_traceback",
    "raw_record",
    "raw_records",
    "raw_row",
    "raw_rows",
    "raw_payload",
    "raw_sheet",
    "raw_sheet_name",
    "source_row",
    "source_sheet",
}

FIELD_DEFINITIONS: Dict[str, FieldDefinition] = {
    # --------------------------------------------------------
    # Identity
    # --------------------------------------------------------
    "tax_id_raw": FieldDefinition(
        name="tax_id_raw",
        label="Tax ID Raw",
        description="เลขประจำตัวผู้เสียภาษีตามไฟล์ต้นฉบับก่อน normalize",
        dtype="string",
        group="identity",
        source="policy/linkage/location",
        searchable=True,
        exportable=True,
        sensitive=True,
        example="0105560000000",
    ),
    "tax_id_norm": FieldDefinition(
        name="tax_id_norm",
        label="Tax ID",
        description="เลขประจำตัวผู้เสียภาษีที่ normalize แล้ว ใช้เป็น key หลักในการ join",
        dtype="string",
        group="identity",
        source="computed",
        required=True,
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
        sensitive=True,
        example="0105560000000",
    ),
    "tax_id_valid": FieldDefinition(
        name="tax_id_valid",
        label="Tax ID Valid",
        description="สถานะว่า Tax ID ถูกต้องหรือไม่",
        dtype="boolean",
        group="identity",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        example=True,
    ),
    "tax_id_issue": FieldDefinition(
        name="tax_id_issue",
        label="Tax ID Issue",
        description="รายละเอียดปัญหาของ Tax ID",
        dtype="string",
        group="identity",
        source="computed",
        filterable=True,
        searchable=True,
        exportable=True,
        example="not_13_digits",
    ),

    # --------------------------------------------------------
    # Company
    # --------------------------------------------------------
    "company_name": FieldDefinition(
        name="company_name",
        label="Company Name",
        description="ชื่อบริษัทหลักที่ resolve แล้วจาก policy/linkage/location",
        dtype="string",
        group="company",
        source="computed",
        required=True,
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
        example="บริษัท ตัวอย่าง จำกัด",
    ),
    "company_name_policy": FieldDefinition(
        name="company_name_policy",
        label="Company Name from Policy",
        description="ชื่อบริษัทจาก Policy Sheet 1",
        dtype="string",
        group="company",
        source="policy",
        searchable=True,
        exportable=True,
    ),
    "company_name_linkage": FieldDefinition(
        name="company_name_linkage",
        label="Company Name from Linkage",
        description="ชื่อบริษัทจาก Linkage Input",
        dtype="string",
        group="company",
        source="linkage",
        searchable=True,
        exportable=True,
    ),
    "company_name_location": FieldDefinition(
        name="company_name_location",
        label="Company Name from Location",
        description="ชื่อบริษัทจาก Policy Sheet 2",
        dtype="string",
        group="company",
        source="policy_location",
        searchable=True,
        exportable=True,
    ),
    "business_type_objective": FieldDefinition(
        name="business_type_objective",
        label="Business Objective",
        description="วัตถุประสงค์ทางธุรกิจ",
        dtype="string",
        group="company_profile",
        source="linkage",
        filterable=True,
        searchable=True,
        exportable=True,
    ),
    "business_type_tsic": FieldDefinition(
        name="business_type_tsic",
        label="TSIC",
        description="ประเภทธุรกิจตาม TSIC",
        dtype="string",
        group="company_profile",
        source="linkage",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
    ),
    "company_size": FieldDefinition(
        name="company_size",
        label="Company Size",
        description="ขนาดบริษัท",
        dtype="string",
        group="company_profile",
        source="linkage",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "wtip": FieldDefinition(
        name="wtip",
        label="WTIP",
        description="ตัวบ่งชี้ WTIP จากข้อมูล linkage",
        dtype="string",
        group="company_profile",
        source="linkage",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
    ),

    # --------------------------------------------------------
    # Financial
    # --------------------------------------------------------
    "most_recent_asset_val": FieldDefinition(
        name="most_recent_asset_val",
        label="Most Recent Asset",
        description="มูลค่าสินทรัพย์ล่าสุด",
        dtype="number",
        group="financial",
        source="policy",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),
    "most_recent_income_val": FieldDefinition(
        name="most_recent_income_val",
        label="Most Recent Income",
        description="รายได้ล่าสุด",
        dtype="number",
        group="financial",
        source="policy/linkage",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),
    "registered_capital": FieldDefinition(
        name="registered_capital",
        label="Registered Capital",
        description="ทุนจดทะเบียน",
        dtype="number",
        group="financial",
        source="policy/linkage",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),

    # --------------------------------------------------------
    # Location
    # --------------------------------------------------------
    "address": FieldDefinition(
        name="address",
        label="Address",
        description="ที่อยู่บริษัท",
        dtype="string",
        group="location",
        source="policy_location",
        searchable=True,
        exportable=True,
        sensitive=True,
    ),
    "province": FieldDefinition(
        name="province",
        label="Province",
        description="จังหวัด",
        dtype="string",
        group="location",
        source="policy/location/flood",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
        example="น่าน",
    ),
    "district": FieldDefinition(
        name="district",
        label="District",
        description="อำเภอ/เขต",
        dtype="string",
        group="location",
        source="policy_location",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
    ),
    "subdistrict": FieldDefinition(
        name="subdistrict",
        label="Subdistrict",
        description="ตำบล/แขวง",
        dtype="string",
        group="location",
        source="policy_location",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
    ),
    "lat": FieldDefinition(
        name="lat",
        label="Latitude",
        description="ละติจูด",
        dtype="number",
        group="location",
        source="policy_location/branch/flood",
        sortable=True,
        exportable=True,
    ),
    "lon": FieldDefinition(
        name="lon",
        label="Longitude",
        description="ลองจิจูด",
        dtype="number",
        group="location",
        source="policy_location/branch/flood",
        sortable=True,
        exportable=True,
    ),
    "location_source": FieldDefinition(
        name="location_source",
        label="Location Source",
        description="แหล่งที่มาของพิกัด",
        dtype="string",
        group="location",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "location_quality": FieldDefinition(
        name="location_quality",
        label="Location Quality",
        description="คุณภาพพิกัด",
        dtype="string",
        group="location",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        allowed_values=LOCATION_QUALITY_LEVELS,
    ),

    # --------------------------------------------------------
    # Source flags
    # --------------------------------------------------------
    "has_policy": FieldDefinition(
        name="has_policy",
        label="Has Policy",
        description="มีข้อมูล policy หรือไม่",
        dtype="boolean",
        group="source_flag",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "has_linkage": FieldDefinition(
        name="has_linkage",
        label="Has Linkage",
        description="มีข้อมูล linkage หรือไม่",
        dtype="boolean",
        group="source_flag",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "has_location": FieldDefinition(
        name="has_location",
        label="Has Location",
        description="มีข้อมูลพิกัดหรือไม่",
        dtype="boolean",
        group="source_flag",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "has_flood_context": FieldDefinition(
        name="has_flood_context",
        label="Has Flood Context",
        description="มีข้อมูล flood spatial context หรือไม่",
        dtype="boolean",
        group="source_flag",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),

    # --------------------------------------------------------
    # Policy
    # --------------------------------------------------------
    "product": FieldDefinition(
        name="product",
        label="Product",
        description="ผลิตภัณฑ์ประกันภัย",
        dtype="string",
        group="policy",
        source="policy",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
    ),
    "subclass": FieldDefinition(
        name="subclass",
        label="Subclass",
        description="ประเภทภัย / subclass",
        dtype="string",
        group="policy",
        source="policy",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
    ),
    "policy_status": FieldDefinition(
        name="policy_status",
        label="Policy Status",
        description="สถานะกรมธรรม์ที่ normalize แล้ว",
        dtype="string",
        group="policy",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "is_active_policy": FieldDefinition(
        name="is_active_policy",
        label="Active Policy",
        description="เป็นกรมธรรม์ active หรือไม่",
        dtype="boolean",
        group="policy",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "is_expired_policy": FieldDefinition(
        name="is_expired_policy",
        label="Expired Policy",
        description="เป็นกรมธรรม์หมดอายุหรือไม่",
        dtype="boolean",
        group="policy",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "policy_year": FieldDefinition(
        name="policy_year",
        label="Policy Year",
        description="ปีกรมธรรม์",
        dtype="integer",
        group="policy",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "premium": FieldDefinition(
        name="premium",
        label="Premium",
        description="เบี้ยประกัน",
        dtype="number",
        group="policy_financial",
        source="policy",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),
    "loss": FieldDefinition(
        name="loss",
        label="Loss",
        description="ค่าสินไหม",
        dtype="number",
        group="policy_financial",
        source="policy",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),
    "suminsure": FieldDefinition(
        name="suminsure",
        label="Sum Insured",
        description="ทุนประกัน",
        dtype="number",
        group="policy_financial",
        source="policy",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),
    "noofpol": FieldDefinition(
        name="noofpol",
        label="No. of Policies",
        description="จำนวนกรมธรรม์",
        dtype="number",
        group="policy",
        source="policy",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "total_premium": FieldDefinition(
        name="total_premium",
        label="Total Premium",
        description="เบี้ยประกันรวม",
        dtype="number",
        group="policy_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),
    "total_loss": FieldDefinition(
        name="total_loss",
        label="Total Loss",
        description="ค่าสินไหมรวม",
        dtype="number",
        group="policy_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),
    "total_suminsure": FieldDefinition(
        name="total_suminsure",
        label="Total Sum Insured",
        description="ทุนประกันรวม",
        dtype="number",
        group="policy_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="THB",
    ),
    "loss_ratio": FieldDefinition(
        name="loss_ratio",
        label="Loss Ratio",
        description="Loss / Premium * 100",
        dtype="number",
        group="policy_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        unit="%",
    ),
    "loss_ratio_band": FieldDefinition(
        name="loss_ratio_band",
        label="Loss Ratio Band",
        description="กลุ่มระดับ Loss Ratio",
        dtype="string",
        group="policy_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        allowed_values=list(LOSS_RATIO_BANDS.keys()),
    ),

    # --------------------------------------------------------
    # Linkage
    # --------------------------------------------------------
    "boardlist": FieldDefinition(
        name="boardlist",
        label="Board List",
        description="รายชื่อกรรมการจากไฟล์ linkage",
        dtype="string",
        group="linkage",
        source="linkage",
        searchable=True,
        exportable=True,
        sensitive=True,
    ),
    "director_id": FieldDefinition(
        name="director_id",
        label="Director ID",
        description="รหัสกรรมการที่สร้างจากชื่อ normalized",
        dtype="string",
        group="linkage",
        source="computed",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
        sensitive=True,
    ),
    "director_name": FieldDefinition(
        name="director_name",
        label="Director Name",
        description="ชื่อกรรมการ",
        dtype="string",
        group="linkage",
        source="linkage",
        filterable=True,
        sortable=True,
        searchable=True,
        exportable=True,
        sensitive=True,
    ),
    "director_count": FieldDefinition(
        name="director_count",
        label="Director Count",
        description="จำนวนกรรมการของบริษัท",
        dtype="integer",
        group="linkage_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "company_count": FieldDefinition(
        name="company_count",
        label="Company Count",
        description="จำนวนบริษัทที่กรรมการเชื่อมโยง",
        dtype="integer",
        group="linkage_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "is_key_connector": FieldDefinition(
        name="is_key_connector",
        label="Key Connector",
        description="กรรมการที่เชื่อมมากกว่า 1 บริษัท",
        dtype="boolean",
        group="linkage_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "shared_company_count": FieldDefinition(
        name="shared_company_count",
        label="Shared Company Count",
        description="จำนวนบริษัทที่เชื่อมผ่านกรรมการร่วม",
        dtype="integer",
        group="linkage_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),
    "key_connector_count": FieldDefinition(
        name="key_connector_count",
        label="Key Connector Count",
        description="จำนวน key connector ที่เกี่ยวข้องกับบริษัท",
        dtype="integer",
        group="linkage_summary",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
    ),

    # --------------------------------------------------------
    # Flood / Spatial
    # --------------------------------------------------------
    "flood_risk_level": FieldDefinition(
        name="flood_risk_level",
        label="Flood Risk Level",
        description="ระดับความเสี่ยงน้ำท่วม",
        dtype="string",
        group="flood",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        allowed_values=RISK_LEVELS,
    ),
    "flood_join_level": FieldDefinition(
        name="flood_join_level",
        label="Flood Join Level",
        description="ระดับการ join กับข้อมูลน้ำท่วม",
        dtype="string",
        group="flood",
        source="computed",
        filterable=True,
        sortable=True,
        exportable=True,
        allowed_values=SPATIAL_JOIN_LEVELS,
    ),
    "flood_risk_reason": FieldDefinition(
        name="flood_risk_reason",
        label="Flood Risk Reason",
        description="เหตุผลการจัดระดับ flood risk",
        dtype="string",
        group="flood",
        source="computed",
        searchable=True,
        exportable=True,
    ),
    "nearest_rainfall_station_id": FieldDefinition(
        name="nearest_rainfall_station_id",
        label="Nearest Rainfall Station ID",
        description="รหัสสถานีฝนที่ใกล้บริษัทที่สุด",
        dtype="string",
        group="spatial",
        source="computed",
        exportable=True,
    ),
    "nearest_waterlevel_station_id": FieldDefinition(
        name="nearest_waterlevel_station_id",
        label="Nearest Waterlevel Station ID",
        description="รหัสสถานีระดับน้ำที่ใกล้บริษัทที่สุด",
        dtype="string",
        group="spatial",
        source="computed",
        exportable=True,
    ),
    "nearest_dam_id": FieldDefinition(
        name="nearest_dam_id",
        label="Nearest Dam ID",
        description="รหัสเขื่อนที่ใกล้บริษัทที่สุด",
        dtype="string",
        group="spatial",
        source="computed",
        exportable=True,
    ),

    # --------------------------------------------------------
    # Data Quality
    # --------------------------------------------------------
    "data_quality_flags": FieldDefinition(
        name="data_quality_flags",
        label="Data Quality Flags",
        description="รายการ flag คุณภาพข้อมูลของ record",
        dtype="array",
        group="data_quality",
        source="computed",
        filterable=True,
        searchable=True,
        exportable=True,
    ),
}

FIELD_DEFINITIONS.update(
    {
        "data_source": FieldDefinition(
            name="data_source",
            label="Data Source",
            description="active data source ของ runtime",
            dtype="string",
            group="data_source",
            source="config",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
            example="excel",
        ),
        "source_file_modified_at": FieldDefinition(
            name="source_file_modified_at",
            label="Source File Modified At",
            description="เวลาที่ source file ถูกแก้ไขล่าสุด",
            dtype="datetime",
            group="data_source",
            source="source_layer",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "source_type": FieldDefinition(
            name="source_type",
            label="Source Type",
            description="ชนิด source ของ record เช่น rainfall/waterlevel/dam/prediction/entity",
            dtype="string",
            group="source_flag",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "source_id": FieldDefinition(
            name="source_id",
            label="Source ID",
            description="รหัส source record",
            dtype="string",
            group="source_flag",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "source_name": FieldDefinition(
            name="source_name",
            label="Source Name",
            description="ชื่อ source record",
            dtype="string",
            group="source_flag",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "latitude": FieldDefinition(
            name="latitude",
            label="Latitude",
            description="ละติจูดมาตรฐานสำหรับ map/table",
            dtype="number",
            group="location",
            source="computed",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "longitude": FieldDefinition(
            name="longitude",
            label="Longitude",
            description="ลองจิจูดมาตรฐานสำหรับ map/table",
            dtype="number",
            group="location",
            source="computed",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "latest_value": FieldDefinition(
            name="latest_value",
            label="Latest Value",
            description="ค่าล่าสุดที่ normalize แล้วสำหรับ rainfall/waterlevel/dam/prediction",
            dtype="number",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "latest_unit": FieldDefinition(
            name="latest_unit",
            label="Latest Unit",
            description="หน่วยของ latest_value",
            dtype="string",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "risk_level": FieldDefinition(
            name="risk_level",
            label="Risk Level",
            description="ระดับความเสี่ยงมาตรฐาน",
            dtype="string",
            group="flood",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
            allowed_values=RISK_LEVELS,
        ),
        "risk_status": FieldDefinition(
            name="risk_status",
            label="Risk Status",
            description="สถานะความเสี่ยงจาก source",
            dtype="string",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
            allowed_values=RISK_LEVELS,
        ),
        "risk_reason": FieldDefinition(
            name="risk_reason",
            label="Risk Reason",
            description="เหตุผลการจัดระดับความเสี่ยง",
            dtype="string",
            group="flood",
            source="computed",
            searchable=True,
            exportable=True,
        ),
        "data_datetime": FieldDefinition(
            name="data_datetime",
            label="Data Datetime",
            description="วันเวลาของข้อมูล source",
            dtype="datetime",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "data_date": FieldDefinition(
            name="data_date",
            label="Data Date",
            description="วันที่ของข้อมูล source",
            dtype="date",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "prediction_record_key": FieldDefinition(
            name="prediction_record_key",
            label="Prediction Record Key",
            description="record key ของ prediction",
            dtype="string",
            group="prediction",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "record_key": FieldDefinition(
            name="record_key",
            label="Record Key",
            description="record key กลางของ runtime record",
            dtype="string",
            group="general",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "station_id": FieldDefinition(
            name="station_id",
            label="Station ID",
            description="รหัสสถานีจาก source",
            dtype="string",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "station_code": FieldDefinition(
            name="station_code",
            label="Station Code",
            description="รหัสสถานีแบบ code",
            dtype="string",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "station_name": FieldDefinition(
            name="station_name",
            label="Station Name",
            description="ชื่อสถานี",
            dtype="string",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "matched_station_id": FieldDefinition(
            name="matched_station_id",
            label="Matched Station ID",
            description="รหัสสถานีที่ match จาก station master",
            dtype="string",
            group="prediction",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "matched_station_code": FieldDefinition(
            name="matched_station_code",
            label="Matched Station Code",
            description="station code ที่ match จาก station master",
            dtype="string",
            group="prediction",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "matched_station_name": FieldDefinition(
            name="matched_station_name",
            label="Matched Station Name",
            description="ชื่อสถานีที่ match จาก station master",
            dtype="string",
            group="prediction",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "province_model": FieldDefinition(
            name="province_model",
            label="Province Model",
            description="จังหวัดที่ model/prediction ระบุ",
            dtype="string",
            group="prediction",
            source="prediction",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "base_date": FieldDefinition(
            name="base_date",
            label="Base Date",
            description="วันที่ฐานของ prediction",
            dtype="date",
            group="prediction",
            source="prediction",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "target_date": FieldDefinition(
            name="target_date",
            label="Target Date",
            description="วันที่ forecast target",
            dtype="date",
            group="prediction",
            source="prediction",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "forecast_horizon_day": FieldDefinition(
            name="forecast_horizon_day",
            label="Forecast Horizon Day",
            description="จำนวนวันล่วงหน้าของ forecast",
            dtype="integer",
            group="prediction",
            source="prediction",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "warning_level": FieldDefinition(
            name="warning_level",
            label="Warning Level",
            description="ระดับเตือนภัยจาก source",
            dtype="string",
            group="flood",
            source="flood",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "warning_level_predict": FieldDefinition(
            name="warning_level_predict",
            label="Warning Level Predict",
            description="ระดับเตือนภัยที่ prediction คาดการณ์",
            dtype="string",
            group="prediction",
            source="prediction",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "predicted_level_m": FieldDefinition(
            name="predicted_level_m",
            label="Predicted Level",
            description="ระดับน้ำที่คาดการณ์ หน่วยเมตร",
            dtype="number",
            group="prediction",
            source="prediction",
            filterable=True,
            sortable=True,
            exportable=True,
            unit="m",
        ),
        "percent_to_bank": FieldDefinition(
            name="percent_to_bank",
            label="Percent To Bank",
            description="เปอร์เซ็นต์เทียบระดับตลิ่ง",
            dtype="number",
            group="prediction",
            source="prediction",
            filterable=True,
            sortable=True,
            exportable=True,
            unit="%",
        ),
        "from_bank_m": FieldDefinition(
            name="from_bank_m",
            label="From Bank",
            description="ระยะจากระดับตลิ่ง หน่วยเมตร",
            dtype="number",
            group="prediction",
            source="prediction",
            filterable=True,
            sortable=True,
            exportable=True,
            unit="m",
        ),
        "map_ready": FieldDefinition(
            name="map_ready",
            label="Map Ready",
            description="พร้อมแสดงบน map หรือไม่",
            dtype="boolean",
            group="map",
            source="computed",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "focus_level": FieldDefinition(
            name="focus_level",
            label="Focus Level",
            description="ระดับ focus map เช่น station/province_boundary",
            dtype="string",
            group="map",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "focus_fallback": FieldDefinition(
            name="focus_fallback",
            label="Focus Fallback",
            description="fallback สำหรับ frontend map focus",
            dtype="string",
            group="map",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "focus_fallback_reason": FieldDefinition(
            name="focus_fallback_reason",
            label="Focus Fallback Reason",
            description="เหตุผลที่ใช้ focus fallback",
            dtype="string",
            group="map",
            source="computed",
            searchable=True,
            exportable=True,
        ),
        "upload_id": FieldDefinition(
            name="upload_id",
            label="Upload ID",
            description="รหัส upload ของ uploaded entity",
            dtype="string",
            group="entity",
            source="uploaded_entity",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "entity_id": FieldDefinition(
            name="entity_id",
            label="Entity ID",
            description="รหัส entity จากไฟล์ upload",
            dtype="string",
            group="entity",
            source="uploaded_entity",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "entity_type": FieldDefinition(
            name="entity_type",
            label="Entity Type",
            description="ประเภท entity จากไฟล์ upload",
            dtype="string",
            group="entity",
            source="uploaded_entity",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "entity_name_th": FieldDefinition(
            name="entity_name_th",
            label="Entity Name TH",
            description="ชื่อ entity ภาษาไทย",
            dtype="string",
            group="entity",
            source="uploaded_entity",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "entity_name_en": FieldDefinition(
            name="entity_name_en",
            label="Entity Name EN",
            description="ชื่อ entity ภาษาอังกฤษ",
            dtype="string",
            group="entity",
            source="uploaded_entity",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "province_name_th": FieldDefinition(
            name="province_name_th",
            label="Province Name TH",
            description="ชื่อจังหวัดภาษาไทยจาก uploaded entity",
            dtype="string",
            group="entity",
            source="uploaded_entity",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "risk_group": FieldDefinition(
            name="risk_group",
            label="Risk Group",
            description="กลุ่มความเสี่ยงของ uploaded entity",
            dtype="string",
            group="entity",
            source="uploaded_entity",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "is_displayable": FieldDefinition(
            name="is_displayable",
            label="Is Displayable",
            description="uploaded entity แสดงผลบน map ได้หรือไม่",
            dtype="boolean",
            group="entity",
            source="computed",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "validation_reasons": FieldDefinition(
            name="validation_reasons",
            label="Validation Reasons",
            description="เหตุผล validation ของ uploaded entity",
            dtype="array",
            group="entity",
            source="computed",
            searchable=True,
            exportable=True,
        ),
        "layer_id": FieldDefinition(
            name="layer_id",
            label="Layer ID",
            description="รหัส layer",
            dtype="string",
            group="map",
            source="map",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "layer_type": FieldDefinition(
            name="layer_type",
            label="Layer Type",
            description="ประเภท layer",
            dtype="string",
            group="map",
            source="map",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "visible": FieldDefinition(
            name="visible",
            label="Visible",
            description="สถานะการแสดงผล layer",
            dtype="boolean",
            group="map",
            source="map",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "opacity": FieldDefinition(
            name="opacity",
            label="Opacity",
            description="ค่าความโปร่งใสของ layer",
            dtype="number",
            group="map",
            source="map",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "cache_key": FieldDefinition(
            name="cache_key",
            label="Cache Key",
            description="ชื่อ cache key",
            dtype="string",
            group="cache",
            source="cache_registry",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "owner_service": FieldDefinition(
            name="owner_service",
            label="Owner Service",
            description="service เจ้าของ cache",
            dtype="string",
            group="cache",
            source="cache_registry",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "payload_type": FieldDefinition(
            name="payload_type",
            label="Payload Type",
            description="ชนิด payload ของ cache",
            dtype="string",
            group="cache",
            source="cache_registry",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "critical": FieldDefinition(
            name="critical",
            label="Critical Cache",
            description="เป็น cache สำคัญหรือไม่",
            dtype="boolean",
            group="cache",
            source="cache_registry",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "allow_stale": FieldDefinition(
            name="allow_stale",
            label="Allow Stale",
            description="อนุญาตให้ใช้ cache stale หรือไม่",
            dtype="boolean",
            group="cache",
            source="cache_registry",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "phase": FieldDefinition(
            name="phase",
            label="Rebuild Phase",
            description="ชื่อ rebuild phase",
            dtype="string",
            group="cache",
            source="rebuild",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "status": FieldDefinition(
            name="status",
            label="Status",
            description="สถานะทั่วไปของ payload/phase",
            dtype="string",
            group="general",
            source="computed",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "duration_ms": FieldDefinition(
            name="duration_ms",
            label="Duration MS",
            description="เวลา execute phase หน่วย ms",
            dtype="integer",
            group="cache",
            source="rebuild",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
    }
)

FIELD_DEFINITIONS.update(
    {
        "active_source": FieldDefinition(
            name="active_source",
            label="Active Source",
            description="data source ที่ใช้งานจริงใน runtime",
            dtype="string",
            group="data_source",
            source="config",
            required=True,
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
            example="excel",
        ),
        "excel_enabled": FieldDefinition(
            name="excel_enabled",
            label="Excel Enabled",
            description="สถานะเปิดใช้งาน Excel data source",
            dtype="boolean",
            group="data_source",
            source="config",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "mysql_enabled": FieldDefinition(
            name="mysql_enabled",
            label="MySQL Enabled",
            description="สถานะเปิดใช้งาน MySQL data source",
            dtype="boolean",
            group="data_source",
            source="config",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "excel_paths": FieldDefinition(
            name="excel_paths",
            label="Excel Paths",
            description="summary path ของ Excel source แบบ public-safe",
            dtype="object",
            group="data_source",
            source="config",
            exportable=True,
        ),
        "mysql_status": FieldDefinition(
            name="mysql_status",
            label="MySQL Status",
            description="สถานะ MySQL placeholder",
            dtype="string",
            group="data_source",
            source="config",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "validation": FieldDefinition(
            name="validation",
            label="Validation",
            description="validation result ของ config/source/cache",
            dtype="object",
            group="data_quality",
            source="computed",
            exportable=True,
        ),
        "layer_name": FieldDefinition(
            name="layer_name",
            label="Layer Name",
            description="ชื่อ layer สำหรับ frontend map",
            dtype="string",
            group="map",
            source="map",
            filterable=True,
            sortable=True,
            searchable=True,
            exportable=True,
        ),
        "z_index": FieldDefinition(
            name="z_index",
            label="Z Index",
            description="ลำดับการซ้อน layer บน map",
            dtype="integer",
            group="map",
            source="map",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "record_count": FieldDefinition(
            name="record_count",
            label="Record Count",
            description="จำนวน record ใน payload",
            dtype="integer",
            group="general",
            source="computed",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "feature_collection": FieldDefinition(
            name="feature_collection",
            label="Feature Collection",
            description="GeoJSON FeatureCollection ของ map layer",
            dtype="object",
            group="map",
            source="map",
            exportable=True,
        ),
        "features": FieldDefinition(
            name="features",
            label="Features",
            description="GeoJSON features หรือ feature collection",
            dtype="array",
            group="map",
            source="map",
            exportable=True,
        ),
        "records": FieldDefinition(
            name="records",
            label="Records",
            description="records ใน payload",
            dtype="array",
            group="general",
            source="computed",
            exportable=True,
        ),
        "total": FieldDefinition(
            name="total",
            label="Total",
            description="จำนวนรวมของ records",
            dtype="integer",
            group="general",
            source="computed",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "style": FieldDefinition(
            name="style",
            label="Style",
            description="style object ของ map layer",
            dtype="object",
            group="map",
            source="map",
            exportable=True,
        ),
        "meta": FieldDefinition(
            name="meta",
            label="Meta",
            description="metadata ของ payload",
            dtype="object",
            group="general",
            source="computed",
            exportable=True,
        ),
        "summary": FieldDefinition(
            name="summary",
            label="Summary",
            description="summary object ของ payload",
            dtype="object",
            group="dashboard",
            source="computed",
            exportable=True,
        ),
        "filters": FieldDefinition(
            name="filters",
            label="Filters",
            description="filter context ที่ใช้สร้าง payload",
            dtype="object",
            group="dashboard",
            source="computed",
            exportable=True,
        ),
        "generated_at": FieldDefinition(
            name="generated_at",
            label="Generated At",
            description="เวลาที่สร้าง payload",
            dtype="datetime",
            group="general",
            source="computed",
            filterable=True,
            sortable=True,
            exportable=True,
        ),
        "prediction_risk_top3": FieldDefinition(
            name="prediction_risk_top3",
            label="Prediction Risk Top 3",
            description="จังหวัดเสี่ยงสูงสุดจาก prediction",
            dtype="array",
            group="dashboard",
            source="dashboard",
            exportable=True,
        ),
        "rainfall_top5": FieldDefinition(
            name="rainfall_top5",
            label="Rainfall Top 5",
            description="จังหวัดหรือสถานีฝนสูงสุด 5 อันดับ",
            dtype="array",
            group="dashboard",
            source="dashboard",
            exportable=True,
        ),
        "waterlevel_top5": FieldDefinition(
            name="waterlevel_top5",
            label="Waterlevel Top 5",
            description="จังหวัดหรือสถานีระดับน้ำสูงสุด 5 อันดับ",
            dtype="array",
            group="dashboard",
            source="dashboard",
            exportable=True,
        ),
        "reservoir_top5": FieldDefinition(
            name="reservoir_top5",
            label="Reservoir Top 5",
            description="เขื่อนหรืออ่างเก็บน้ำสำคัญ 5 อันดับ",
            dtype="array",
            group="dashboard",
            source="dashboard",
            exportable=True,
        ),
        "depends_on": FieldDefinition(
            name="depends_on",
            label="Depends On",
            description="cache dependency upstream",
            dtype="array",
            group="cache",
            source="cache_registry",
            exportable=True,
        ),
        "consumed_by": FieldDefinition(
            name="consumed_by",
            label="Consumed By",
            description="service downstream ที่ใช้ cache นี้",
            dtype="array",
            group="cache",
            source="cache_registry",
            exportable=True,
        ),
        "aliases": FieldDefinition(
            name="aliases",
            label="Aliases",
            description="cache key alias",
            dtype="array",
            group="cache",
            source="cache_registry",
            exportable=True,
        ),
        "outputs": FieldDefinition(
            name="outputs",
            label="Outputs",
            description="outputs ของ rebuild phase",
            dtype="object",
            group="cache",
            source="rebuild",
            exportable=True,
        ),
        "errors": FieldDefinition(
            name="errors",
            label="Errors",
            description="errors ของ payload หรือ rebuild phase",
            dtype="array",
            group="data_quality",
            source="computed",
            exportable=True,
        ),
        "warnings": FieldDefinition(
            name="warnings",
            label="Warnings",
            description="warnings ของ payload หรือ rebuild phase",
            dtype="array",
            group="data_quality",
            source="computed",
            exportable=True,
        ),
        **{
            field_name: FieldDefinition(
                name=field_name,
                label=field_name.replace("_", " ").title(),
                description="internal path/debug/raw field ห้าม export public default",
                dtype="string",
                group="internal",
                source="internal",
                filterable=False,
                sortable=False,
                searchable=False,
                exportable=False,
                visible_default=False,
                sensitive=True,
            )
            for field_name in INTERNAL_NON_EXPORTABLE_FIELDS
        },
    }
)

DATA_SOURCE_CONFIG_SCHEMA: Dict[str, Any] = asdict(
    DataSourceConfigSchema(
        active_source="excel",
        excel_enabled=True,
        mysql_enabled=False,
        excel_paths={
            "latest": "latest_database.xlsx",
            "master": "master_database.xlsx",
            "history": "history/",
            "prediction": "predict/",
            "upload": "upload/",
        },
        mysql_status="placeholder_not_implemented",
        validation={
            "allow_multiple_active_sources": False,
            "mysql_implemented": False,
            "mysql_allowed_in_current_phase": False,
        },
    )
)

FLOOD_LATEST_RECORD_SCHEMA: Dict[str, Any] = asdict(
    FloodLatestRecord(
        source_type="rainfall",
        source_id="station_id",
        source_name="Station Name",
        province="น่าน",
        latitude=18.7,
        longitude=100.7,
        latest_value=120.0,
        latest_unit="mm",
        risk_level="Warning",
        risk_reason="rainfall threshold",
        data_datetime="2026-07-01T08:00:00",
    )
)

FLOOD_PREDICTION_RECORD_SCHEMA: Dict[str, Any] = asdict(
    FloodPredictionRecord(
        record_key="prediction|1373690|2026-07-01|2026-07-03|2",
        station_name="Station Name",
        station_id="1373690",
        station_code="ST001",
        matched_station_id="1373690",
        matched_station_code="ST001",
        matched_station_name="Station Name",
        province="น่าน",
        province_model="น่าน",
        base_date="2026-07-01",
        target_date="2026-07-03",
        forecast_horizon_day=2,
        risk_level="Warning",
        risk_status="Warning",
        warning_level="Watch",
        warning_level_predict="Warning",
        predicted_level_m=4.2,
        latest_value=4.2,
        latest_unit="m",
        percent_to_bank=85.0,
        from_bank_m=0.35,
        latitude=18.7,
        longitude=100.7,
        map_ready=True,
        focus_level="station",
        focus_fallback="station",
        focus_fallback_reason="matched_station_master",
    )
)

UPLOADED_ENTITY_RECORD_SCHEMA: Dict[str, Any] = asdict(
    UploadedEntityRecord(
        upload_id="UP_20260701_000001",
        entity_id="E001",
        entity_type="shop",
        entity_name_th="ร้านตัวอย่าง",
        entity_name_en="Example Shop",
        province_name_th="น่าน",
        province="น่าน",
        latitude=18.7,
        longitude=100.7,
        risk_group="Watch",
        risk_level="Watch",
        source_type="uploaded_entity",
        map_ready=True,
        has_location=True,
        is_displayable=True,
        validation_reasons=[],
    )
)

MAP_LAYER_PAYLOAD_SCHEMA: Dict[str, Any] = asdict(
    MapLayerPayloadSchema(
        layer_id="prediction",
        layer_name="Flood Prediction",
        layer_type="point",
        visible=True,
        opacity=1.0,
        z_index=5,
        records=[],
        features={
            "type": "FeatureCollection",
            "features": [],
        },
        feature_collection={
            "type": "FeatureCollection",
            "features": [],
        },
        total=0,
        record_count=0,
        style={
            "renderer": "point",
            "risk_field": "risk_level",
            "color_field": "risk_level",
            "size_field": "latest_value",
            "label_field": "station_name",
            "focus_fallback": True,
        },
        meta={
            "source": "excel",
            "degraded": False,
            "errors": [],
        },
    )
)

MERGED_MAP_LAYERS_SCHEMA: Dict[str, Any] = {
    "rainfall": MAP_LAYER_PAYLOAD_SCHEMA,
    "waterlevel": MAP_LAYER_PAYLOAD_SCHEMA,
    "dam": MAP_LAYER_PAYLOAD_SCHEMA,
    "prediction": MAP_LAYER_PAYLOAD_SCHEMA,
    "entity": MAP_LAYER_PAYLOAD_SCHEMA,
    "province_boundary": MAP_LAYER_PAYLOAD_SCHEMA,
    "basin_boundary": MAP_LAYER_PAYLOAD_SCHEMA,
    "province_boundaries": MAP_LAYER_PAYLOAD_SCHEMA,
    "basin_boundaries": MAP_LAYER_PAYLOAD_SCHEMA,
    "company_points": MAP_LAYER_PAYLOAD_SCHEMA,
    "flood_points": MAP_LAYER_PAYLOAD_SCHEMA,
    "policy_exposure": MAP_LAYER_PAYLOAD_SCHEMA,
    "linkage_lines": MAP_LAYER_PAYLOAD_SCHEMA,
    "branch_points": MAP_LAYER_PAYLOAD_SCHEMA,
    "heatmap": MAP_LAYER_PAYLOAD_SCHEMA,
}

DASHBOARD_PROVINCE_INSIGHTS_SCHEMA: Dict[str, Any] = asdict(
    DashboardProvinceInsightsSchema(
        prediction_risk_top3=[],
        rainfall_top5=[],
        waterlevel_top5=[],
        reservoir_top5=[],
        filters={},
        generated_at="2026-07-01T08:00:00",
    )
)

CACHE_REGISTRY_ITEM_SCHEMA: Dict[str, Any] = asdict(
    CacheRegistryItemSchema(
        cache_key="flood_prediction_latest",
        owner_service="flood_spatial_service",
        payload_type="records",
        depends_on=["flood_master_station_index"],
        consumed_by=["map_graph_service", "dashboard_package_service", "data_quality", "filter_engine"],
        critical=True,
        allow_stale=False,
        aliases=["prediction_latest", "forecast_latest"],
    )
)

REBUILD_PHASE_RESULT_SCHEMA: Dict[str, Any] = asdict(
    RebuildPhaseResultSchema(
        phase="spatial_prediction_entity",
        status="success",
        outputs={
            "flood_prediction_latest": {"total": 0},
            "flood_prediction_map": {"total": 0},
            "uploaded_entity_latest": {"total": 0},
        },
        errors=[],
        warnings=[],
        duration_ms=0,
    )
)

# ============================================================
# 5) INPUT SCHEMA
# ============================================================

POLICY_INPUT_SCHEMA: Dict[str, SheetSchema] = {
    "policy_fact": SheetSchema(
        key="policy_fact",
        display_name="Policy Fact / Company Policy Data",
        description=(
            "Sheet หลักของกรมธรรม์ ใช้สร้าง policy_fact, "
            "policy_company_summary และ policy dashboard"
        ),
        required_columns=[
            "Tax Id",
            "Company Name",
            "Product",
            "Subclass",
            "Premium",
            "Loss",
            "Suminsure",
        ],
        optional_columns=[
            "Inforced Flag",
            "Status Now",
            "status now (new)",
            "Yearmonth Year First",
            "Noofpol",
            "Active Subs",
            "Expired Subs",
            "Product Holding",
            "subclass Holding",
            "Most Recent Asset Val",
            "Most Recent Income Val",
            "Registered Capital",
        ],
        fallback_index=0,
        source_type="excel",
    ),
    "company_location": SheetSchema(
        key="company_location",
        display_name="Company Location",
        description=(
            "Sheet พิกัดบริษัท ใช้สร้าง company_location_master "
            "และใช้ spatial join กับ flood"
        ),
        required_columns=[
            "Tax Id",
            "Name Th",
            "Province",
        ],
        optional_columns=[
            "Address",
            "District",
            "Subdistrict",
            "Lat",
            "Longitude",
            "Point Company",
        ],
        fallback_index=1,
        source_type="excel",
    ),
    "province_branch_coordinate": SheetSchema(
        key="province_branch_coordinate",
        display_name="Province / Branch Coordinate",
        description=(
            "Sheet พิกัดสาขาหรือศูนย์ ใช้เป็น fallback "
            "เมื่อบริษัทไม่มี coordinate"
        ),
        required_columns=[
            "จังหวัด",
            "Lat",
            "Long",
        ],
        optional_columns=[
            "ชื่อสาขา/ศูนย์1",
            "ตำบล",
            "ภาค",
            "อำเภอ",
        ],
        fallback_index=2,
        source_type="excel",
    ),
}


LINKAGE_INPUT_SCHEMA: SheetSchema = SheetSchema(
    key="linkage_input",
    display_name="Linkage Input",
    description=(
        "ไฟล์ข้อมูลบริษัทและกรรมการ ใช้สร้าง director_master, "
        "linkage_nodes, linkage_edges และ shared_director_links"
    ),
    required_columns=[
        "tax_id",
        "name_th",
        "boardlist",
    ],
    optional_columns=[
        "business_type_objective",
        "most_recent_income_val",
        "registered_capital",
        "business_type_tsic",
        "company_size",
        "Wtip",
    ],
    fallback_index=0,
    source_type="excel",
)


FLOOD_INPUT_SCHEMA: Dict[str, SheetSchema] = {
    "rainfall_latest": SheetSchema(
        key="rainfall_latest",
        display_name="02_rainfall_latest",
        description="ข้อมูลฝนล่าสุดรายสถานี ใช้คำนวณ rainfall risk และ map layer",
        required_columns=[],
        optional_columns=[
            "station_id",
            "station_name",
            "province",
            "basin",
            "lat",
            "lon",
            "rainfall_value",
            "rainfall_24h",
            "data_datetime",
        ],
        source_type="excel",
    ),
    "waterlevel_latest": SheetSchema(
        key="waterlevel_latest",
        display_name="05_waterlevel_latest",
        description="ข้อมูลระดับน้ำล่าสุดรายสถานี ใช้คำนวณ waterlevel risk",
        required_columns=[],
        optional_columns=[
            "station_id",
            "station_name",
            "province",
            "basin",
            "lat",
            "lon",
            "waterlevel_value",
            "warning_level",
            "critical_level",
            "data_datetime",
        ],
        source_type="excel",
    ),
    "large_dam_latest": SheetSchema(
        key="large_dam_latest",
        display_name="07_large_dam_latest",
        description="ข้อมูลเขื่อนขนาดใหญ่ล่าสุด",
        required_columns=[],
        optional_columns=[
            "dam_id",
            "dam_name",
            "province",
            "basin",
            "lat",
            "lon",
            "storage",
            "capacity",
            "storage_percent",
            "inflow",
            "release",
            "data_datetime",
        ],
        source_type="excel",
    ),
    "medium_dam_latest": SheetSchema(
        key="medium_dam_latest",
        display_name="09_medium_dam_latest",
        description="ข้อมูลเขื่อนขนาดกลางล่าสุด",
        required_columns=[],
        optional_columns=[
            "medium_id",
            "medium_name",
            "province",
            "basin",
            "lat",
            "lon",
            "storage",
            "capacity",
            "storage_percent",
            "data_datetime",
        ],
        source_type="excel",
    ),
    "all_long_latest": SheetSchema(
        key="all_long_latest",
        display_name="17_all_long_latest",
        description="ข้อมูล flood latest แบบ long format",
        required_columns=[],
        optional_columns=[
            "source_type",
            "source_id",
            "province",
            "lat",
            "lon",
            "value",
            "data_datetime",
        ],
        source_type="excel",
    ),
}

FLOOD_INPUT_SCHEMA.update(
    {
        "prediction_latest": SheetSchema(
            key="prediction_latest",
            display_name="predict_YYYY_MM_DD.xlsx",
            description=(
                "ไฟล์ prediction ล่าสุด ใช้สร้าง "
                "prediction latest/map/location-debug/risk-distribution"
            ),
            required_columns=list(PREDICTION_REQUIRED_COLUMNS),
            optional_columns=[
                column
                for column in PREDICTION_SUPPORTED_COLUMNS
                if column not in set(PREDICTION_REQUIRED_COLUMNS)
            ],
            source_type="excel",
        ),
        "uploaded_entity": SheetSchema(
            key="uploaded_entity",
            display_name="uploaded_entity.csv/.xlsx/.xls",
            description=(
                "ไฟล์ uploaded entity overlay จากผู้ใช้ "
                "ใช้เฉพาะ displayable records สำหรับ public map"
            ),
            required_columns=list(ENTITY_REQUIRED_COLUMNS),
            optional_columns=[
                column
                for column in ENTITY_SUPPORTED_COLUMNS
                if column not in set(ENTITY_REQUIRED_COLUMNS)
            ],
            source_type="tabular_upload",
        ),
    }
)

# ============================================================
# 6) OUTPUT DATASET SCHEMA
# ============================================================

DATASET_SCHEMAS: Dict[str, DatasetSchema] = {
    "policy_fact": DatasetSchema(
        key="policy_fact",
        display_name="Policy Fact",
        description="ข้อมูลกรมธรรม์ระดับรายการหลัง clean และ normalize",
        primary_key=None,
        fields=[
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
            "policy_status",
            "is_active_policy",
            "is_expired_policy",
            "policy_year",
            "premium",
            "loss",
            "suminsure",
            "noofpol",
            "loss_ratio",
            "loss_ratio_band",
        ],
        required_fields=[
            "tax_id_norm",
            "company_name",
        ],
        default_sort="company_name",
    ),
    "policy_company_summary": DatasetSchema(
        key="policy_company_summary",
        display_name="Policy Company Summary",
        description="ข้อมูล policy สรุประดับบริษัท",
        primary_key="tax_id_norm",
        fields=[
            "tax_id_norm",
            "company_name",
            "total_premium",
            "total_loss",
            "total_suminsure",
            "total_noofpol",
            "active_policy_count",
            "expired_policy_count",
            "product_count",
            "subclass_count",
            "first_policy_year",
            "latest_policy_year",
            "loss_ratio",
            "loss_ratio_band",
        ],
        required_fields=[
            "tax_id_norm",
            "company_name",
        ],
        default_sort="total_suminsure",
        default_sort_dir="desc",
    ),
    "company_location_master": DatasetSchema(
        key="company_location_master",
        display_name="Company Location Master",
        description="ข้อมูลตำแหน่งบริษัทจาก Policy Sheet 2 และ fallback จาก Sheet 3",
        primary_key="tax_id_norm",
        fields=[
            "tax_id_norm",
            "company_name",
            "address",
            "province",
            "district",
            "subdistrict",
            "lat",
            "lon",
            "location_source",
            "location_quality",
        ],
        required_fields=[
            "tax_id_norm",
        ],
        default_sort="province",
    ),
    "company_unified_master": DatasetSchema(
        key="company_unified_master",
        display_name="Company Unified Master",
        description="ข้อมูลบริษัทกลางที่รวม policy, linkage, location และ flood context",
        primary_key="tax_id_norm",
        fields=[
            "tax_id_raw",
            "tax_id_norm",
            "tax_id_valid",
            "tax_id_issue",
            "company_name",
            "business_type_objective",
            "business_type_tsic",
            "company_size",
            "wtip",
            "most_recent_asset_val",
            "most_recent_income_val",
            "registered_capital",
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
            "loss_ratio",
            "loss_ratio_band",
            "director_count",
            "shared_company_count",
            "key_connector_count",
            "flood_risk_level",
            "flood_join_level",
            "data_quality_flags",
        ],
        required_fields=[
            "tax_id_norm",
            "company_name",
        ],
        default_sort="company_name",
    ),
    "director_master": DatasetSchema(
        key="director_master",
        display_name="Director Master",
        description="ข้อมูลกรรมการหลัง normalize และ aggregate",
        primary_key="director_id",
        fields=[
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
        ],
        required_fields=[
            "director_id",
            "director_name",
        ],
        default_sort="company_count",
        default_sort_dir="desc",
    ),
    "linkage_nodes": DatasetSchema(
        key="linkage_nodes",
        display_name="Linkage Nodes",
        description="Nodes สำหรับ D3 graph ประกอบด้วย company และ director",
        primary_key="id",
        fields=[
            "id",
            "type",
            "label",
            "tax_id_norm",
            "director_id",
            "size",
            "color",
            "metadata",
        ],
        required_fields=[
            "id",
            "type",
            "label",
        ],
        default_sort="label",
    ),
    "linkage_edges": DatasetSchema(
        key="linkage_edges",
        display_name="Linkage Edges",
        description="Edges สำหรับ D3 graph",
        primary_key="id",
        fields=[
            "id",
            "source",
            "target",
            "type",
            "weight",
            "shared_directors",
            "metadata",
        ],
        required_fields=[
            "id",
            "source",
            "target",
            "type",
        ],
        default_sort="type",
    ),
    "flood_computed_risk": DatasetSchema(
        key="flood_computed_risk",
        display_name="Flood Computed Risk",
        description="ข้อมูล flood หลังคำนวณ risk จาก rainfall/waterlevel/dam",
        primary_key="source_key",
        fields=[
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
        ],
        required_fields=[
            "source_type",
            "risk_level",
        ],
        default_sort="risk_score",
        default_sort_dir="desc",
    ),
    "spatial_join_result": DatasetSchema(
        key="spatial_join_result",
        display_name="Spatial Join Result",
        description="ผลการเชื่อมบริษัทกับ flood risk",
        primary_key="tax_id_norm",
        fields=[
            "tax_id_norm",
            "company_name",
            "company_lat",
            "company_lon",
            "company_province",
            "join_level",
            "location_quality",
            "nearest_rainfall_station_id",
            "nearest_rainfall_station_name",
            "nearest_rainfall_distance_km",
            "nearest_waterlevel_station_id",
            "nearest_waterlevel_station_name",
            "nearest_waterlevel_distance_km",
            "nearest_dam_id",
            "nearest_dam_name",
            "nearest_dam_distance_km",
            "province_risk_level",
            "station_risk_level",
            "final_flood_risk_level",
            "flood_risk_reason",
            "has_flood_context",
        ],
        required_fields=[
            "tax_id_norm",
        ],
        default_sort="final_flood_risk_level",
    ),
    "map_layers": DatasetSchema(
        key="map_layers",
        display_name="Map Layers",
        description="Payload สำหรับ OpenLayers",
        primary_key=None,
        fields=[
            "layer_id",
            "layer_name",
            "layer_type",
            "feature_collection",
            "style",
            "visible",
            "record_count",
        ],
        supports_search=False,
        supports_export=True,
    ),
    "dashboard_summary": DatasetSchema(
        key="dashboard_summary",
        display_name="Dashboard Summary",
        description="Summary cards และภาพรวม dashboard",
        primary_key=None,
        fields=[
            "summary_cards",
            "charts",
            "top_companies",
            "top_directors",
            "risk_insights",
            "data_quality",
        ],
        supports_search=False,
        supports_filter=True,
        supports_export=True,
    ),
}

DATASET_SCHEMAS.update(
    {
        "data_source_config": DatasetSchema(
            key="data_source_config",
            display_name="Data Source Config",
            description="runtime data source config สำหรับ Excel/MySQL placeholder",
            primary_key="active_source",
            fields=[
                "data_source",
                "active_source",
                "excel_enabled",
                "mysql_enabled",
                "excel_paths",
                "mysql_status",
                "validation",
            ],
            required_fields=[
                "active_source",
            ],
            supports_filter=False,
            supports_search=False,
            supports_export=True,
        ),
        "flood_rainfall_latest": DatasetSchema(
            key="flood_rainfall_latest",
            display_name="Flood Rainfall Latest",
            description="rainfall latest normalized records",
            primary_key="source_id",
            fields=[
                "source_type",
                "source_id",
                "source_name",
                "province",
                "latitude",
                "longitude",
                "latest_value",
                "latest_unit",
                "risk_level",
                "risk_reason",
                "data_datetime",
                "source_file_modified_at",
            ],
            required_fields=[
                "source_type",
                "source_id",
                "risk_level",
            ],
            default_sort="latest_value",
            default_sort_dir="desc",
        ),
        "flood_waterlevel_latest": DatasetSchema(
            key="flood_waterlevel_latest",
            display_name="Flood Waterlevel Latest",
            description="waterlevel latest normalized records",
            primary_key="source_id",
            fields=[
                "source_type",
                "source_id",
                "source_name",
                "province",
                "latitude",
                "longitude",
                "latest_value",
                "latest_unit",
                "risk_level",
                "risk_reason",
                "data_datetime",
                "source_file_modified_at",
            ],
            required_fields=[
                "source_type",
                "source_id",
                "risk_level",
            ],
            default_sort="risk_level",
            default_sort_dir="desc",
        ),
        "flood_dam_latest": DatasetSchema(
            key="flood_dam_latest",
            display_name="Flood Dam Latest",
            description="large/medium dam latest normalized records",
            primary_key="source_id",
            fields=[
                "source_type",
                "source_id",
                "source_name",
                "province",
                "latitude",
                "longitude",
                "latest_value",
                "latest_unit",
                "risk_level",
                "risk_reason",
                "data_datetime",
                "source_file_modified_at",
            ],
            required_fields=[
                "source_type",
                "source_id",
                "risk_level",
            ],
            default_sort="latest_value",
            default_sort_dir="desc",
        ),
        "flood_prediction_latest": DatasetSchema(
            key="flood_prediction_latest",
            display_name="Flood Prediction Latest",
            description="prediction latest enriched from station master",
            primary_key="record_key",
            fields=[
                "record_key",
                "prediction_record_key",
                "station_name",
                "station_id",
                "station_code",
                "matched_station_id",
                "matched_station_code",
                "matched_station_name",
                "province",
                "province_model",
                "base_date",
                "target_date",
                "forecast_horizon_day",
                "risk_level",
                "warning_level_predict",
                "predicted_level_m",
                "percent_to_bank",
                "from_bank_m",
                "latitude",
                "longitude",
                "map_ready",
                "focus_level",
                "focus_fallback",
                "focus_fallback_reason",
            ],
            required_fields=[
                "record_key",
                "target_date",
                "forecast_horizon_day",
                "risk_level",
            ],
            default_sort="risk_level",
            default_sort_dir="desc",
        ),
        "flood_prediction_map": DatasetSchema(
            key="flood_prediction_map",
            display_name="Flood Prediction Map",
            description="prediction records ready for map layer",
            primary_key="record_key",
            fields=[
                "record_key",
                "source_type",
                "station_name",
                "matched_station_id",
                "province",
                "risk_level",
                "base_date",
                "target_date",
                "forecast_horizon_day",
                "map_ready",
                "focus_level",
                "focus_fallback",
                "latitude",
                "longitude",
            ],
            required_fields=[
                "record_key",
                "risk_level",
                "map_ready",
            ],
            default_sort="risk_level",
            default_sort_dir="desc",
        ),
        "uploaded_entity_latest": DatasetSchema(
            key="uploaded_entity_latest",
            display_name="Uploaded Entity Latest",
            description="uploaded entity overlay latest records",
            primary_key="entity_id",
            fields=[
                "upload_id",
                "entity_id",
                "entity_type",
                "entity_name_th",
                "entity_name_en",
                "province_name_th",
                "province",
                "latitude",
                "longitude",
                "risk_group",
                "risk_level",
                "is_displayable",
                "map_ready",
                "source_type",
                "validation_reasons",
            ],
            required_fields=[
                "entity_id",
                "entity_type",
                "entity_name_th",
                "province_name_th",
            ],
            default_sort="entity_name_th",
        ),
        "dashboard_province_insights": DatasetSchema(
            key="dashboard_province_insights",
            display_name="Dashboard Province Insights",
            description="top prediction/rainfall/waterlevel/reservoir insights for dashboard",
            primary_key=None,
            fields=[
                "prediction_risk_top3",
                "rainfall_top5",
                "waterlevel_top5",
                "reservoir_top5",
                "filters",
                "generated_at",
            ],
            supports_search=False,
            supports_filter=True,
            supports_export=True,
        ),
        "cache_registry": DatasetSchema(
            key="cache_registry",
            display_name="Cache Registry",
            description="cache dependency registry",
            primary_key="cache_key",
            fields=[
                "cache_key",
                "owner_service",
                "payload_type",
                "depends_on",
                "consumed_by",
                "critical",
                "allow_stale",
                "aliases",
            ],
            required_fields=[
                "cache_key",
                "owner_service",
            ],
            default_sort="cache_key",
        ),
        "rebuild_phase_result": DatasetSchema(
            key="rebuild_phase_result",
            display_name="Rebuild Phase Result",
            description="result payload ของ staged rebuild phase",
            primary_key="phase",
            fields=[
                "phase",
                "status",
                "outputs",
                "errors",
                "warnings",
                "duration_ms",
            ],
            required_fields=[
                "phase",
                "status",
            ],
            default_sort="phase",
        ),
    }
)

DATASET_SCHEMAS.update(
    {
        "company_unified_base": DatasetSchema(
            key="company_unified_base",
            display_name="Company Unified Base",
            description="ข้อมูลบริษัทกลางก่อน enrich linkage/flood/data_quality ใช้เป็น upstream ของ linkage/spatial",
            primary_key="tax_id_norm",
            fields=[
                "tax_id_raw",
                "tax_id_norm",
                "tax_id_valid",
                "tax_id_issue",
                "company_name",
                "business_type_objective",
                "business_type_tsic",
                "company_size",
                "wtip",
                "most_recent_asset_val",
                "most_recent_income_val",
                "registered_capital",
                "province",
                "district",
                "subdistrict",
                "lat",
                "lon",
                "latitude",
                "longitude",
                "location_source",
                "location_quality",
                "has_policy",
                "has_linkage",
                "has_location",
                "total_premium",
                "total_loss",
                "total_suminsure",
                "loss_ratio",
                "loss_ratio_band",
                "boardlist",
            ],
            required_fields=[
                "tax_id_norm",
                "company_name",
            ],
            default_sort="company_name",
        ),
        "map_layers": DatasetSchema(
            key="map_layers",
            display_name="Merged Map Layers",
            description="Merged OpenLayers payload รวม enterprise + flood dashboard layers",
            primary_key=None,
            fields=[
                "layers",
                "layers_by_id",
                "layer_list",
                "layers_list",
                "legacy_layers",
                "layer_order",
                "summary",
                "meta",
                "map",
                "center",
                "zoom",
                "min_zoom",
                "max_zoom",
                "base_tile_url",
                "base_attribution",
            ],
            required_fields=[
                "layers",
                "layer_order",
                "summary",
                "meta",
            ],
            supports_search=False,
            supports_filter=True,
            supports_export=True,
        ),
        "map_layer_payload": DatasetSchema(
            key="map_layer_payload",
            display_name="Map Layer Payload",
            description="Payload ของ layer เดี่ยวใน merged map",
            primary_key="layer_id",
            fields=[
                "layer_id",
                "layer_name",
                "layer_type",
                "visible",
                "opacity",
                "z_index",
                "records",
                "features",
                "feature_collection",
                "total",
                "record_count",
                "style",
                "meta",
            ],
            required_fields=[
                "layer_id",
                "layer_type",
                "features",
                "meta",
            ],
            supports_search=False,
            supports_filter=True,
            supports_export=True,
        ),
        "data_source_config": DatasetSchema(
            key="data_source_config",
            display_name="Data Source Config",
            description="runtime data source config สำหรับ Excel/MySQL placeholder",
            primary_key="active_source",
            fields=[
                "active_source",
                "data_source",
                "excel_enabled",
                "mysql_enabled",
                "excel_paths",
                "mysql_status",
                "validation",
            ],
            required_fields=[
                "active_source",
            ],
            supports_filter=False,
            supports_search=False,
            supports_export=True,
        ),
        "cache_registry": DatasetSchema(
            key="cache_registry",
            display_name="Cache Registry",
            description="cache dependency registry",
            primary_key="cache_key",
            fields=[
                "cache_key",
                "owner_service",
                "payload_type",
                "depends_on",
                "consumed_by",
                "critical",
                "allow_stale",
                "aliases",
            ],
            required_fields=[
                "cache_key",
                "owner_service",
            ],
            default_sort="cache_key",
        ),
        "rebuild_phase_result": DatasetSchema(
            key="rebuild_phase_result",
            display_name="Rebuild Phase Result",
            description="result payload ของ staged rebuild phase",
            primary_key="phase",
            fields=[
                "phase",
                "status",
                "outputs",
                "errors",
                "warnings",
                "duration_ms",
            ],
            required_fields=[
                "phase",
                "status",
            ],
            default_sort="phase",
        ),
    }
)


# ============================================================
# 7) FILTER SCHEMA
# ============================================================

@dataclass
class FilterConditionSchema:
    """
    เงื่อนไข filter 1 เงื่อนไข
    """

    field: str
    operator: str
    value: Any = None
    value_to: Any = None
    dtype: str = "string"


@dataclass
class FilterGroupSchema:
    """
    กลุ่ม filter แบบ AND / OR
    """

    logic: str = "AND"
    conditions: List[Dict[str, Any]] = dc_field(default_factory=list)
    groups: List[Dict[str, Any]] = dc_field(default_factory=list)


@dataclass
class FilterPayloadSchema:
    """
    Payload สำหรับ filter builder
    """

    target: str = "company"
    filters: Dict[str, Any] = dc_field(default_factory=dict)
    advanced: Dict[str, Any] = dc_field(default_factory=dict)
    search: str = ""
    page: int = 1
    page_size: int = 50
    sort_by: str = ""
    sort_dir: str = "asc"
    include_summary: bool = True
    include_map: bool = True
    include_graph: bool = False


FILTER_PAYLOAD_EXAMPLE: Dict[str, Any] = {
    "target": "company",
    "filters": {
        "province": ["น่าน", "แพร่"],
        "flood_risk_level": ["Watch", "Warning", "Critical"],
        "has_policy": True,
    },
    "advanced": {
        "logic": "AND",
        "conditions": [
            {
                "field": "total_suminsure",
                "operator": "gte",
                "value": 1000000,
            },
            {
                "field": "loss_ratio",
                "operator": "between",
                "value": 60,
                "value_to": 100,
            },
        ],
        "groups": [],
    },
    "search": "",
    "page": 1,
    "page_size": 50,
    "sort_by": "total_suminsure",
    "sort_dir": "desc",
}


# ============================================================
# 8) MAP SCHEMA
# ============================================================

@dataclass
class GeoJSONGeometrySchema:
    """
    Geometry แบบ GeoJSON
    """

    type: str
    coordinates: Any


@dataclass
class GeoJSONFeatureSchema:
    """
    Feature แบบ GeoJSON
    """

    type: str = "Feature"
    geometry: Dict[str, Any] = dc_field(default_factory=dict)
    properties: Dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class GeoJSONFeatureCollectionSchema:
    """
    FeatureCollection แบบ GeoJSON
    """

    type: str = "FeatureCollection"
    features: List[Dict[str, Any]] = dc_field(default_factory=list)

MAP_LAYER_SCHEMA: Dict[str, Any] = {
    "layer_id": "string",
    "layer_name": "string",
    "layer_type": "point|line|polygon|heatmap|cluster|boundary",
    "visible": "boolean",
    "opacity": "number",
    "z_index": "integer",
    "records": [],
    "features": {
        "type": "FeatureCollection",
        "features": [],
    },
    "feature_collection": {
        "type": "FeatureCollection",
        "features": [],
    },
    "total": "integer",
    "record_count": "integer",
    "style": {
        "renderer": "point|line|polygon|heatmap",
        "color_field": "string",
        "size_field": "string",
        "risk_field": "string",
        "label_field": "string",
    },
    "meta": {
        "source": "excel",
        "filters": {},
        "counts": {},
        "record_count": 0,
        "skipped_invalid_coordinates": 0,
        "degraded": False,
        "errors": [],
        "generated_at": "",
        "cache_used": False,
    },
}


MERGED_MAP_LAYERS_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "map": {
        "center": [],
        "zoom": "integer",
        "min_zoom": "integer",
        "max_zoom": "integer",
        "base_tile_url": "string",
        "base_attribution": "string",
    },
    "center": [],
    "zoom": "integer",
    "min_zoom": "integer",
    "max_zoom": "integer",
    "base_tile_url": "string",
    "base_attribution": "string",
    "layers": MERGED_MAP_LAYERS_SCHEMA,
    "layers_by_id": MERGED_MAP_LAYERS_SCHEMA,
    "layer_order": [
        "province_boundary",
        "basin_boundary",
        "rainfall",
        "waterlevel",
        "dam",
        "prediction",
        "entity",
        "flood_points",
        "policy_exposure",
        "company_points",
        "branch_points",
        "heatmap",
        "linkage_lines",
    ],
    "layer_list": [],
    "layers_list": [],
    "legacy_layers": [],
    "summary": {
        "layer_count": 0,
        "canonical_layer_count": 0,
        "feature_count": 0,
        "record_count": 0,
        "record_count_by_layer": {},
        "enabled_layers": [],
        "compatibility_layers": [],
        "degraded_layer_ids": [],
        "generated_at": "",
        "degraded": False,
    },
    "meta": {
        "source": "excel",
        "filters": {},
        "counts": {},
        "record_count_by_layer": {},
        "upstream_cache_keys": [],
        "degraded": False,
        "degraded_layer_ids": [],
        "errors": [],
        "generated_at": "",
        "cache_used": False,
    },
}


MAP_FEATURE_PROPERTY_SCHEMA: Dict[str, str] = {
    "feature_id": "string",
    "feature_type": "company|flood_source|rainfall|waterlevel|dam|prediction|entity|branch|province|basin|linkage_line|heatmap|policy_exposure",
    "object_type": "company|flood|prediction|entity|boundary|linkage",
    "source_type": "string",
    "tax_id_norm": "string",
    "company_name": "string",
    "province": "string",
    "station_id": "string",
    "station_code": "string",
    "station_name": "string",
    "matched_station_id": "string",
    "matched_station_code": "string",
    "matched_station_name": "string",
    "entity_id": "string",
    "entity_type": "string",
    "entity_name_th": "string",
    "risk_level": "string",
    "risk_status": "string",
    "warning_level": "string",
    "warning_level_predict": "string",
    "risk_group": "string",
    "latest_value": "number",
    "latest_unit": "string",
    "map_ready": "boolean",
    "focus_level": "string",
    "focus_fallback": "string",
    "focus_fallback_reason": "string",
    "latitude": "number",
    "longitude": "number",
    "lat": "number",
    "lon": "number",
    "premium": "number",
    "suminsure": "number",
    "loss_ratio": "number",
    "loss_ratio_band": "string",
    "flood_risk_level": "string",
    "location_quality": "string",
    "marker_size": "number",
    "marker_color": "string",
    "marker_outline": "string",
    "marker_shape": "string",
}

# ============================================================
# 9) GRAPH SCHEMA
# ============================================================

GRAPH_NODE_SCHEMA: Dict[str, Any] = {
    "id": "string",
    "type": "company|director",
    "label": "string",
    "tax_id_norm": "string|null",
    "director_id": "string|null",
    "size": "number",
    "color": "string",
    "border_color": "string",
    "badges": [],
    "metadata": {},
}


GRAPH_EDGE_SCHEMA: Dict[str, Any] = {
    "id": "string",
    "source": "string",
    "target": "string",
    "type": "DIRECTOR_OF|SHARED_DIRECTOR",
    "weight": "number",
    "shared_directors": [],
    "metadata": {},
}


GRAPH_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "nodes": [],
    "edges": [],
    "summary": {
        "node_count": 0,
        "edge_count": 0,
        "company_node_count": 0,
        "director_node_count": 0,
        "key_connector_count": 0,
    },
    "layout": {
        "mode": "force",
        "depth": 1,
        "limited": False,
        "max_nodes": 300,
    },
    "warnings": [],
}


# ============================================================
# 10) DASHBOARD SCHEMA
# ============================================================

SUMMARY_CARD_SCHEMA: Dict[str, Any] = {
    "key": "string",
    "label": "string",
    "value": "number|string",
    "display_value": "string",
    "delta": "number|null",
    "delta_label": "string",
    "unit": "string",
    "status": "normal|watch|warning|critical|unknown",
    "description": "string",
}


DASHBOARD_SUMMARY_SCHEMA: Dict[str, Any] = {
    "summary_cards": [],
    "charts": {},
    "top_companies": [],
    "top_directors": [],
    "risk_insights": [],
    "province_insights": DASHBOARD_PROVINCE_INSIGHTS_SCHEMA,
    "prediction_risk_top3": [],
    "rainfall_top5": [],
    "waterlevel_top5": [],
    "reservoir_top5": [],
    "data_quality": {},
    "freshness": {},
}


CHART_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "chart_id": "string",
    "chart_type": "bar|line|pie|doughnut|scatter|table",
    "title": "string",
    "labels": [],
    "datasets": [],
    "options": {},
    "meta": {},
}


# ============================================================
# 11) PACKAGE SCHEMA
# ============================================================

@dataclass
class PackageSecuritySchema:
    """
    Security option สำหรับ package export
    """

    mask_tax_id: bool = True
    mask_director_name: bool = False
    mask_address: bool = True
    hide_financial_fields: bool = False
    allow_external_filter: bool = True
    include_data_quality: bool = True


@dataclass
class PackageRequestSchema:
    """
    Payload สำหรับ generate package
    """

    package_name: str
    description: str = ""
    filters: Dict[str, Any] = dc_field(default_factory=dict)
    components: List[str] = dc_field(default_factory=lambda: list(PACKAGE_COMPONENTS))
    security: Dict[str, Any] = dc_field(default_factory=lambda: dict(PACKAGE_SECURITY_OPTIONS))
    expire_days: int = 30
    created_by: str = "system"
    allow_public_access: bool = True


PACKAGE_META_SCHEMA: Dict[str, Any] = {
    "package_id": "string",
    "package_name": "string",
    "description": "string",
    "created_at": "datetime",
    "created_by": "string",
    "expire_at": "datetime|null",
    "status": "active|disabled|expired|deleted",
    "components": [],
    "filters": {},
    "security": {},
    "record_counts": {},
    "files": [],
    "public_url": "string",
    "download_url": "string",
}


PACKAGE_SNAPSHOT_SCHEMA: Dict[str, Any] = {
    "package_meta": PACKAGE_META_SCHEMA,
    "data": {
        "summary": {},
        "companies": [],
        "policy_summary": {},
        "policy_table": [],
        "linkage_graph": GRAPH_PAYLOAD_SCHEMA,
        "map": MERGED_MAP_LAYERS_PAYLOAD_SCHEMA,
        "map_layers": MERGED_MAP_LAYERS_PAYLOAD_SCHEMA,
        "charts": {},
        "tables": {},
        "filter_options": {},
        "data_quality": {},
        "prediction": [],
        "flood_prediction": [],
        "flood_prediction_latest": [],
        "flood_prediction_map": {
            "type": "FeatureCollection",
            "features": [],
            "total": 0,
            "meta": {},
        },
        "entity": [],
        "uploaded_entity": [],
        "uploaded_entity_latest": [],
    },
    "checksum_components": [
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
    ],
}


PUBLIC_PACKAGE_SCHEMA: Dict[str, Any] = {
    "meta": PACKAGE_META_SCHEMA,
    "summary": {},
    "map": MERGED_MAP_LAYERS_PAYLOAD_SCHEMA,
    "charts": {},
    "tables": {},
    "filter_options": {},
    "data_quality": {},
    "prediction": [],
    "entity": [],
}


# ============================================================
# 12) DATA QUALITY SCHEMA
# ============================================================

@dataclass
class DataQualityIssueSchema:
    """
    Issue คุณภาพข้อมูล 1 รายการ
    """

    issue_id: str
    category: str
    severity: str
    code: str
    message: str
    dataset: str = ""
    field: str = ""
    record_key: str = ""
    row_number: Optional[int] = None
    value: Any = None
    suggestion: str = ""
    created_at: str = dc_field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


DATA_QUALITY_SUMMARY_SCHEMA: Dict[str, Any] = {
    "total_issues": 0,
    "by_severity": {
        "info": 0,
        "warning": 0,
        "error": 0,
        "critical": 0,
    },
    "by_category": {
        category: 0 for category in DATA_QUALITY_CATEGORIES
    },
    "top_issues": [],
    "issues": [],
}


# ============================================================
# 13) SECURITY / MASKING SCHEMA
# ============================================================

MASKING_SCHEMA: Dict[str, Any] = {
    "tax_id": {
        "enabled": True,
        "visible_last_digits": 4,
        "example_input": "0105560000000",
        "example_output": "*********0000",
    },
    "director_name": {
        "enabled": False,
        "visible_first_chars": 2,
        "example_input": "นายตัวอย่าง ทดสอบ",
        "example_output": "นา***************",
    },
    "address": {
        "enabled": True,
        "example_input": "99/9 ถนนตัวอย่าง แขวงตัวอย่าง เขตตัวอย่าง กรุงเทพฯ",
        "example_output": "[masked address]",
    },
    "financial_fields": {
        "enabled": False,
        "fields": [
            "premium",
            "loss",
            "suminsure",
            "total_premium",
            "total_loss",
            "total_suminsure",
            "most_recent_income_val",
            "registered_capital",
        ],
    },
}


# ============================================================
# 14) FIELD GROUPS FOR FRONTEND
# ============================================================

FIELD_GROUPS: Dict[str, Dict[str, Any]] = {
    "identity": {
        "label": "Identity",
        "description": "ข้อมูลตัวตนและ key หลัก",
        "order": 1,
    },
    "company": {
        "label": "Company",
        "description": "ข้อมูลบริษัท",
        "order": 2,
    },
    "company_profile": {
        "label": "Company Profile",
        "description": "ข้อมูลประเภทธุรกิจและ profile",
        "order": 3,
    },
    "financial": {
        "label": "Financial",
        "description": "ข้อมูลทางการเงินของบริษัท",
        "order": 4,
    },
    "location": {
        "label": "Location",
        "description": "ข้อมูลที่อยู่และพิกัด",
        "order": 5,
    },
    "source_flag": {
        "label": "Source Flags",
        "description": "สถานะว่าบริษัทมีข้อมูลจาก source ใดบ้าง",
        "order": 6,
    },
    "policy": {
        "label": "Policy",
        "description": "ข้อมูลกรมธรรม์",
        "order": 7,
    },
    "policy_financial": {
        "label": "Policy Financial",
        "description": "ข้อมูลเบี้ย ทุนประกัน และค่าสินไหม",
        "order": 8,
    },
    "policy_summary": {
        "label": "Policy Summary",
        "description": "ข้อมูลสรุปกรมธรรม์",
        "order": 9,
    },
    "linkage": {
        "label": "Linkage",
        "description": "ข้อมูลกรรมการและความเชื่อมโยง",
        "order": 10,
    },
    "linkage_summary": {
        "label": "Linkage Summary",
        "description": "ข้อมูลสรุป network",
        "order": 11,
    },
    "flood": {
        "label": "Flood",
        "description": "ข้อมูลความเสี่ยงน้ำท่วม",
        "order": 12,
    },
    "spatial": {
        "label": "Spatial",
        "description": "ข้อมูล spatial join และ nearest station",
        "order": 13,
    },
    "data_quality": {
        "label": "Data Quality",
        "description": "ข้อมูลคุณภาพข้อมูล",
        "order": 14,
    },
}

FIELD_GROUPS.update(
    {
        "data_source": {
            "label": "Data Source",
            "description": "ข้อมูล runtime data source และ source freshness",
            "order": 15,
        },
        "prediction": {
            "label": "Prediction",
            "description": "ข้อมูล flood prediction และ map focus fallback",
            "order": 16,
        },
        "entity": {
            "label": "Uploaded Entity",
            "description": "ข้อมูล uploaded entity overlay",
            "order": 17,
        },
        "map": {
            "label": "Map",
            "description": "ข้อมูล map layer และ map readiness",
            "order": 18,
        },
        "dashboard": {
            "label": "Dashboard",
            "description": "ข้อมูล dashboard summary และ province insights",
            "order": 19,
        },
        "cache": {
            "label": "Cache / Rebuild",
            "description": "ข้อมูล cache registry และ staged rebuild",
            "order": 20,
        },
    }
)


# ============================================================
# 15) TABLE VIEW SCHEMA
# ============================================================

TABLE_VIEW_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "company": {
        "dataset": "company_unified_master",
        "title": "Company Intelligence Table",
        "primary_key": "tax_id_norm",
        "columns": [
            "tax_id_norm",
            "company_name",
            "province",
            "district",
            "company_size",
            "business_type_tsic",
            "wtip",
            "total_premium",
            "total_loss",
            "total_suminsure",
            "loss_ratio",
            "loss_ratio_band",
            "director_count",
            "key_connector_count",
            "flood_risk_level",
            "location_quality",
            "has_policy",
            "has_linkage",
            "has_location",
            "has_flood_context",
        ],
        "default_visible_columns": [
            "company_name",
            "province",
            "company_size",
            "wtip",
            "total_premium",
            "total_suminsure",
            "loss_ratio_band",
            "flood_risk_level",
        ],
        "row_actions": [
            "view_detail",
            "view_policy",
            "view_linkage",
            "zoom_map",
            "add_to_package",
        ],
    },
    "policy": {
        "dataset": "policy_fact",
        "title": "Policy Table",
        "primary_key": None,
        "columns": [
            "tax_id_norm",
            "company_name",
            "product",
            "subclass",
            "policy_status",
            "is_active_policy",
            "policy_year",
            "premium",
            "loss",
            "suminsure",
            "noofpol",
            "loss_ratio",
            "loss_ratio_band",
        ],
        "default_visible_columns": [
            "company_name",
            "product",
            "subclass",
            "policy_status",
            "premium",
            "loss",
            "suminsure",
            "loss_ratio_band",
        ],
        "row_actions": [
            "view_company",
            "add_to_package",
        ],
    },
    "director": {
        "dataset": "director_master",
        "title": "Director / Key Connector Table",
        "primary_key": "director_id",
        "columns": [
            "director_id",
            "director_name",
            "company_count",
            "is_key_connector",
            "total_connected_income",
            "total_connected_capital",
            "total_connected_premium",
            "total_connected_suminsure",
            "connected_flood_risk_levels",
        ],
        "default_visible_columns": [
            "director_name",
            "company_count",
            "is_key_connector",
            "total_connected_suminsure",
            "connected_flood_risk_levels",
        ],
        "row_actions": [
            "view_director_network",
            "filter_by_director",
            "add_to_package",
        ],
    },
    "data_quality": {
        "dataset": "data_quality_issues",
        "title": "Data Quality Issues",
        "primary_key": "issue_id",
        "columns": [
            "issue_id",
            "category",
            "severity",
            "code",
            "message",
            "dataset",
            "field",
            "record_key",
            "row_number",
            "value",
            "suggestion",
            "created_at",
        ],
        "default_visible_columns": [
            "severity",
            "category",
            "code",
            "message",
            "dataset",
            "field",
            "suggestion",
        ],
        "row_actions": [
            "view_record",
            "copy_issue",
        ],
    },
}


TABLE_VIEW_SCHEMAS.update(
    {
        "flood_prediction_latest": {
            "dataset": "flood_prediction_latest",
            "title": "Flood Prediction Latest",
            "primary_key": "record_key",
            "columns": [
                "record_key",
                "province",
                "province_model",
                "station_name",
                "matched_station_id",
                "risk_level",
                "warning_level_predict",
                "base_date",
                "target_date",
                "forecast_horizon_day",
                "predicted_level_m",
                "percent_to_bank",
                "from_bank_m",
                "map_ready",
                "focus_level",
            ],
            "default_visible_columns": [
                "province",
                "station_name",
                "risk_level",
                "target_date",
                "forecast_horizon_day",
                "map_ready",
            ],
            "row_actions": [
                "focus_map",
                "view_station_detail",
                "add_to_package",
            ],
        },
        "uploaded_entity_latest": {
            "dataset": "uploaded_entity_latest",
            "title": "Uploaded Entity Latest",
            "primary_key": "entity_id",
            "columns": [
                "upload_id",
                "entity_id",
                "entity_type",
                "entity_name_th",
                "entity_name_en",
                "province_name_th",
                "latitude",
                "longitude",
                "risk_group",
                "is_displayable",
                "validation_reasons",
            ],
            "default_visible_columns": [
                "entity_name_th",
                "entity_type",
                "province_name_th",
                "risk_group",
                "is_displayable",
            ],
            "row_actions": [
                "focus_map",
                "view_entity_detail",
            ],
        },
        "dashboard_province_insights": {
            "dataset": "dashboard_province_insights",
            "title": "Dashboard Province Insights",
            "primary_key": None,
            "columns": [
                "prediction_risk_top3",
                "rainfall_top5",
                "waterlevel_top5",
                "reservoir_top5",
                "filters",
                "generated_at",
            ],
            "default_visible_columns": [
                "prediction_risk_top3",
                "rainfall_top5",
                "waterlevel_top5",
                "reservoir_top5",
            ],
            "row_actions": [
                "focus_province",
                "switch_mode",
            ],
        },
        "cache_registry": {
            "dataset": "cache_registry",
            "title": "Cache Registry",
            "primary_key": "cache_key",
            "columns": [
                "cache_key",
                "owner_service",
                "payload_type",
                "depends_on",
                "consumed_by",
                "critical",
                "allow_stale",
                "aliases",
            ],
            "default_visible_columns": [
                "cache_key",
                "owner_service",
                "critical",
                "allow_stale",
            ],
            "row_actions": [
                "view_cache_status",
            ],
        },
    }
)


# ============================================================
# 16) API ROUTE CATALOG
# ============================================================

API_ROUTE_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "core": [
        {"method": "GET", "path": f"{API_PREFIX}/health", "description": "ตรวจสุขภาพระบบ"},
        {"method": "GET", "path": f"{API_PREFIX}/status", "description": "สถานะระบบ"},
        {"method": "GET", "path": f"{API_PREFIX}/config", "description": "config summary"},
        {"method": "GET", "path": f"{API_PREFIX}/routes", "description": "registered routes + schema catalog"},
        {"method": "GET", "path": f"{API_PREFIX}/paths", "description": "สถานะ path"},
        {"method": "GET", "path": f"{API_PREFIX}/inputs", "description": "สถานะ input file"},
        {"method": "GET", "path": f"{API_PREFIX}/schema", "description": "frontend schema bundle"},
    ],
    "company": [
        {"method": "GET", "path": f"{API_PREFIX}/companies", "description": "รายการบริษัท"},
        {"method": "GET", "path": f"{API_PREFIX}/companies/<tax_id>", "description": "รายละเอียดบริษัท"},
        {"method": "GET", "path": f"{API_PREFIX}/companies/summary", "description": "summary บริษัท"},
        {"method": "GET", "path": f"{API_PREFIX}/companies/ranking/income", "description": "ranking บริษัทตามรายได้"},
    ],
    "policy": [
        {"method": "GET", "path": f"{API_PREFIX}/policy/summary", "description": "policy summary"},
        {"method": "GET", "path": f"{API_PREFIX}/policy/companies", "description": "policy company list"},
        {"method": "GET", "path": f"{API_PREFIX}/policy/company/<tax_id>", "description": "policy detail by company"},
        {"method": "GET", "path": f"{API_PREFIX}/policy/product-summary", "description": "product summary"},
        {"method": "GET", "path": f"{API_PREFIX}/policy/subclass-summary", "description": "subclass summary"},
    ],
    "linkage": [
        {"method": "GET", "path": f"{API_PREFIX}/linkage/summary", "description": "linkage summary"},
        {"method": "GET", "path": f"{API_PREFIX}/linkage/graph", "description": "D3 graph payload"},
        {"method": "GET", "path": f"{API_PREFIX}/linkage/company/<tax_id>", "description": "company network"},
        {"method": "GET", "path": f"{API_PREFIX}/linkage/director/<director_id>", "description": "director network"},
    ],
    "flood": [
        {"method": "GET", "path": f"{API_PREFIX}/flood/summary", "description": "flood summary"},
        {"method": "GET", "path": f"{API_PREFIX}/flood/rainfall/latest", "description": "rainfall latest"},
        {"method": "GET", "path": f"{API_PREFIX}/flood/waterlevel/latest", "description": "waterlevel latest"},
        {"method": "GET", "path": f"{API_PREFIX}/flood/dam/latest", "description": "dam latest"},
        {"method": "GET", "path": f"{API_PREFIX}/flood/computed-risk", "description": "computed flood risk"},
        {"method": "GET", "path": f"{API_PREFIX}/latest/rainfall", "description": "rainfall latest alias"},
        {"method": "GET", "path": f"{API_PREFIX}/latest/waterlevel", "description": "waterlevel latest alias"},
        {"method": "GET", "path": f"{API_PREFIX}/latest/dam", "description": "dam latest alias"},
        {"method": "GET", "path": f"{API_PREFIX}/history/rainfall", "description": "rainfall history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/rain15d", "description": "rain15d history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/rain-yearly", "description": "rain yearly history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/waterlevel", "description": "waterlevel history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/dam", "description": "dam history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/all-long", "description": "all long history"},
    ],
    "prediction": [
        {"method": "GET", "path": f"{API_PREFIX}/prediction/contract", "description": "prediction contract"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/latest", "description": "latest flood predictions"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/summary", "description": "prediction summary"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/map", "description": "prediction map layer data"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/location-debug", "description": "prediction location match debug"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/station/<station_id>", "description": "prediction station detail"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/risk-distribution", "description": "prediction risk distribution"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/search", "description": "prediction search"},
        {"method": "GET", "path": f"{API_PREFIX}/forecast/latest", "description": "forecast latest alias"},
        {"method": "GET", "path": f"{API_PREFIX}/forecast/map", "description": "forecast map alias"},
    ],
    "upload": [
        {"method": "POST", "path": f"{API_PREFIX}/upload/entities", "description": "upload entity CSV"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/entities/latest", "description": "latest entity records"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/entities/map", "description": "latest entity map features"},
        {"method": "DELETE", "path": f"{API_PREFIX}/upload/entities/latest", "description": "clear latest entity"},
        {"method": "POST", "path": f"{API_PREFIX}/upload/entities/clear", "description": "clear latest entity alias"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/logs", "description": "upload logs"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/result/<upload_id>", "description": "upload result"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/result/<upload_id>/displayable", "description": "displayable upload rows"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/result/<upload_id>/not-displayable", "description": "not-displayable upload rows"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/result/<upload_id>/error-report", "description": "upload error report"},
    ],
    "map": [
        {"method": "GET", "path": f"{API_PREFIX}/map/layers", "description": "OpenLayers merged layers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/companies", "description": "company markers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/flood", "description": "flood markers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/rainfall", "description": "rainfall map layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/waterlevel", "description": "waterlevel map layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/dam", "description": "dam map layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/prediction", "description": "prediction map layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/entities", "description": "uploaded entity map layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/boundaries", "description": "province/basin boundary layers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/linkage-lines", "description": "linkage line layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/boundary/province", "description": "province boundary layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/boundary/basin", "description": "basin boundary layer"},
    ],
    "dashboard": [
        {"method": "GET", "path": f"{API_PREFIX}/summary", "description": "dashboard summary"},
        {"method": "GET", "path": f"{API_PREFIX}/dashboard/overview", "description": "dashboard overview"},
        {"method": "GET", "path": f"{API_PREFIX}/dashboard/province-insights", "description": "province insight cards/ranking"},
        {"method": "GET", "path": f"{API_PREFIX}/dashboard/freshness", "description": "data freshness"},
        {"method": "GET", "path": f"{API_PREFIX}/charts/risk-distribution", "description": "risk distribution chart"},
        {"method": "GET", "path": f"{API_PREFIX}/charts/province-comparison", "description": "province comparison chart"},
        {"method": "GET", "path": f"{API_PREFIX}/charts/station-ranking", "description": "station ranking chart"},
    ],
    "filter": [
        {"method": "GET", "path": f"{API_PREFIX}/filter/fields", "description": "filter fields"},
        {"method": "GET", "path": f"{API_PREFIX}/filter/quick-presets", "description": "quick presets"},
        {"method": "POST", "path": f"{API_PREFIX}/filter/preview", "description": "preview filter"},
        {"method": "POST", "path": f"{API_PREFIX}/filter/apply", "description": "apply filter"},
    ],
    "data_quality": [
        {"method": "GET", "path": f"{API_PREFIX}/data-quality/summary", "description": "data quality summary"},
        {"method": "GET", "path": f"{API_PREFIX}/data-quality/flood", "description": "flood data quality"},
        {"method": "GET", "path": f"{API_PREFIX}/data-quality/spatial", "description": "spatial data quality"},
        {"method": "GET", "path": f"{API_PREFIX}/admin/data-quality", "description": "admin data quality"},
        {"method": "GET", "path": f"{API_PREFIX}/admin/errors", "description": "admin errors"},
        {"method": "GET", "path": f"{API_PREFIX}/admin/scrape-runs", "description": "admin scrape runs"},
    ],
    "cache": [
        {"method": "GET", "path": f"{API_PREFIX}/cache/status", "description": "cache status"},
        {"method": "POST", "path": f"{API_PREFIX}/cache/clear", "description": "clear cache"},
        {"method": "POST", "path": f"{API_PREFIX}/cache/rebuild", "description": "staged rebuild all cache"},
        {"method": "POST", "path": f"{API_PREFIX}/cache/rebuild-phase", "description": "rebuild selected phase"},
    ],
    "detail": [
        {"method": "GET", "path": f"{API_PREFIX}/detail/object", "description": "generic object detail"},
        {"method": "GET", "path": f"{API_PREFIX}/search", "description": "global search"},
    ],
    "package": [
        {"method": "POST", "path": f"{API_PREFIX}/packages/preview", "description": "preview package"},
        {"method": "POST", "path": f"{API_PREFIX}/packages/generate", "description": "generate package"},
        {"method": "GET", "path": f"{API_PREFIX}/packages", "description": "list packages"},
        {"method": "GET", "path": f"{API_PREFIX}/packages/<package_id>/download", "description": "download package file"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/meta", "description": "public package meta"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/data", "description": "public package data"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/summary", "description": "public package summary"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/map", "description": "public package map"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/charts", "description": "public package charts"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/tables", "description": "public package tables"},
    ],
}

API_ROUTE_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "core": [
        {"method": "GET", "path": f"{API_PREFIX}/health", "description": "ตรวจสุขภาพระบบ"},
        {"method": "GET", "path": f"{API_PREFIX}/status", "description": "สถานะระบบ"},
        {"method": "GET", "path": f"{API_PREFIX}/config", "description": "config summary"},
        {"method": "GET", "path": f"{API_PREFIX}/routes", "description": "รายการ API routes"},
        {"method": "GET", "path": f"{API_PREFIX}/paths", "description": "สถานะ path"},
        {"method": "GET", "path": f"{API_PREFIX}/inputs", "description": "สถานะ input file"},
        {"method": "GET", "path": f"{API_PREFIX}/schema", "description": "frontend schema bundle"},
    ],
    "company": [
        {"method": "GET", "path": f"{API_PREFIX}/companies", "description": "รายการบริษัท"},
        {"method": "GET", "path": f"{API_PREFIX}/companies/<tax_id>", "description": "รายละเอียดบริษัท"},
        {"method": "GET", "path": f"{API_PREFIX}/companies/summary", "description": "summary บริษัท"},
        {"method": "GET", "path": f"{API_PREFIX}/companies/ranking/income", "description": "ranking บริษัทตามรายได้"},
    ],
    "policy": [
        {"method": "GET", "path": f"{API_PREFIX}/policy/summary", "description": "policy summary"},
        {"method": "GET", "path": f"{API_PREFIX}/policy/companies", "description": "policy company list"},
        {"method": "GET", "path": f"{API_PREFIX}/policy/company/<tax_id>", "description": "policy detail by company"},
        {"method": "GET", "path": f"{API_PREFIX}/policy/product-summary", "description": "product summary"},
        {"method": "GET", "path": f"{API_PREFIX}/policy/subclass-summary", "description": "subclass summary"},
    ],
    "linkage": [
        {"method": "GET", "path": f"{API_PREFIX}/linkage/summary", "description": "linkage summary"},
        {"method": "GET", "path": f"{API_PREFIX}/linkage/graph", "description": "D3 graph payload"},
        {"method": "GET", "path": f"{API_PREFIX}/linkage/company/<tax_id>", "description": "company network"},
        {"method": "GET", "path": f"{API_PREFIX}/linkage/director/<director_id>", "description": "director network"},
    ],
    "flood": [
        {"method": "GET", "path": f"{API_PREFIX}/flood/summary", "description": "flood summary"},
        {"method": "GET", "path": f"{API_PREFIX}/flood/rainfall/latest", "description": "rainfall latest"},
        {"method": "GET", "path": f"{API_PREFIX}/flood/waterlevel/latest", "description": "waterlevel latest"},
        {"method": "GET", "path": f"{API_PREFIX}/flood/dam/latest", "description": "dam latest"},
        {"method": "GET", "path": f"{API_PREFIX}/flood/computed-risk", "description": "computed flood risk"},
        {"method": "GET", "path": f"{API_PREFIX}/latest/rainfall", "description": "rainfall latest alias"},
        {"method": "GET", "path": f"{API_PREFIX}/latest/waterlevel", "description": "waterlevel latest alias"},
        {"method": "GET", "path": f"{API_PREFIX}/latest/dam", "description": "dam latest alias"},
        {"method": "GET", "path": f"{API_PREFIX}/history/rainfall", "description": "rainfall history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/rain15d", "description": "rain15d history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/rain-yearly", "description": "rain yearly history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/waterlevel", "description": "waterlevel history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/dam", "description": "dam history"},
        {"method": "GET", "path": f"{API_PREFIX}/history/all-long", "description": "all long history"},
    ],
    "prediction": [
        {"method": "GET", "path": f"{API_PREFIX}/prediction/contract", "description": "prediction contract"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/latest", "description": "latest flood predictions"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/summary", "description": "prediction summary"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/map", "description": "prediction map layer data"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/location-debug", "description": "prediction location match debug"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/station/<station_id>", "description": "prediction station detail"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/risk-distribution", "description": "prediction risk distribution"},
        {"method": "GET", "path": f"{API_PREFIX}/prediction/search", "description": "prediction search"},
        {"method": "GET", "path": f"{API_PREFIX}/forecast/latest", "description": "forecast latest alias"},
        {"method": "GET", "path": f"{API_PREFIX}/forecast/map", "description": "forecast map alias"},
    ],
    "upload": [
        {"method": "POST", "path": f"{API_PREFIX}/upload/entities", "description": "upload entity CSV"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/entities/latest", "description": "latest entity records"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/entities/map", "description": "latest entity map features"},
        {"method": "DELETE", "path": f"{API_PREFIX}/upload/entities/latest", "description": "clear latest entity"},
        {"method": "POST", "path": f"{API_PREFIX}/upload/entities/clear", "description": "clear latest entity alias"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/logs", "description": "upload logs"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/result/<upload_id>", "description": "upload result"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/result/<upload_id>/displayable", "description": "displayable upload rows"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/result/<upload_id>/not-displayable", "description": "not-displayable upload rows"},
        {"method": "GET", "path": f"{API_PREFIX}/upload/result/<upload_id>/error-report", "description": "upload error report"},
    ],
    "map": [
        {"method": "GET", "path": f"{API_PREFIX}/map/layers", "description": "OpenLayers merged layers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/companies", "description": "company markers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/flood", "description": "flood markers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/entities", "description": "uploaded entity map layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/linkage-lines", "description": "linkage line layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/boundary/province", "description": "province boundary layer"},
        {"method": "GET", "path": f"{API_PREFIX}/map/boundary/basin", "description": "basin boundary layer"},
    ],
    "dashboard": [
        {"method": "GET", "path": f"{API_PREFIX}/summary", "description": "dashboard summary"},
        {"method": "GET", "path": f"{API_PREFIX}/dashboard/overview", "description": "dashboard overview"},
        {"method": "GET", "path": f"{API_PREFIX}/dashboard/province-insights", "description": "province insight cards/ranking"},
        {"method": "GET", "path": f"{API_PREFIX}/dashboard/freshness", "description": "data freshness"},
        {"method": "GET", "path": f"{API_PREFIX}/charts/risk-distribution", "description": "risk distribution chart"},
        {"method": "GET", "path": f"{API_PREFIX}/charts/province-comparison", "description": "province comparison chart"},
        {"method": "GET", "path": f"{API_PREFIX}/charts/station-ranking", "description": "station ranking chart"},
    ],
    "filter": [
        {"method": "GET", "path": f"{API_PREFIX}/filter/fields", "description": "filter fields"},
        {"method": "GET", "path": f"{API_PREFIX}/filter/quick-presets", "description": "quick presets"},
        {"method": "POST", "path": f"{API_PREFIX}/filter/preview", "description": "preview filter"},
        {"method": "POST", "path": f"{API_PREFIX}/filter/apply", "description": "apply filter"},
    ],
    "data_quality": [
        {"method": "GET", "path": f"{API_PREFIX}/data-quality/summary", "description": "data quality summary"},
        {"method": "GET", "path": f"{API_PREFIX}/data-quality/flood", "description": "flood data quality"},
        {"method": "GET", "path": f"{API_PREFIX}/data-quality/spatial", "description": "spatial data quality"},
        {"method": "GET", "path": f"{API_PREFIX}/admin/data-quality", "description": "admin data quality"},
        {"method": "GET", "path": f"{API_PREFIX}/admin/errors", "description": "admin errors"},
        {"method": "GET", "path": f"{API_PREFIX}/admin/scrape-runs", "description": "admin scrape runs"},
    ],
    "cache": [
        {"method": "POST", "path": f"{API_PREFIX}/cache/rebuild", "description": "staged rebuild all cache"},
        {"method": "POST", "path": f"{API_PREFIX}/cache/rebuild-phase", "description": "rebuild selected phase"},
        {"method": "GET", "path": f"{API_PREFIX}/cache/status", "description": "cache status"},
    ],
    "detail": [
        {"method": "GET", "path": f"{API_PREFIX}/detail/object", "description": "generic object detail"},
        {"method": "GET", "path": f"{API_PREFIX}/search", "description": "global search"},
    ],
    "package": [
        {"method": "POST", "path": f"{API_PREFIX}/packages/preview", "description": "preview package"},
        {"method": "POST", "path": f"{API_PREFIX}/packages/generate", "description": "generate package"},
        {"method": "GET", "path": f"{API_PREFIX}/packages", "description": "list packages"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/meta", "description": "public package meta"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/data", "description": "public package data"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/summary", "description": "public package summary"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/map", "description": "public package map"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/charts", "description": "public package charts"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/tables", "description": "public package tables"},
    ],
}

# ============================================================
# 17) VALIDATION HELPERS
# ============================================================

def field_definition_to_dict(field_def: FieldDefinition) -> Dict[str, Any]:
    """
    แปลง FieldDefinition เป็น dict
    """

    return asdict(field_def)


def sheet_schema_to_dict(sheet_schema: SheetSchema) -> Dict[str, Any]:
    """
    แปลง SheetSchema เป็น dict
    """

    return asdict(sheet_schema)


def dataset_schema_to_dict(dataset_schema: DatasetSchema) -> Dict[str, Any]:
    """
    แปลง DatasetSchema เป็น dict
    """

    return asdict(dataset_schema)


def get_field_definition(field_name: str) -> Optional[Dict[str, Any]]:
    """
    คืน field definition ตามชื่อ field
    """

    field_def = FIELD_DEFINITIONS.get(field_name)

    if not field_def:
        return None

    return field_definition_to_dict(field_def)


def get_fields_by_group(group: str) -> List[Dict[str, Any]]:
    """
    คืน field ทั้งหมดตาม group
    """

    return [
        field_definition_to_dict(field_def)
        for field_def in FIELD_DEFINITIONS.values()
        if field_def.group == group
    ]


def get_filterable_fields(
    target: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    คืน field ที่ filter ได้ตาม target

    Args:
        target:
            target ของ dataset หรือ runtime view
    """

    fields = [
        field_def
        for field_def in FIELD_DEFINITIONS.values()
        if field_def.filterable
    ]

    target_key = str(target or "").strip().lower()

    if not target_key:
        return [
            field_definition_to_dict(field_def)
            for field_def in fields
        ]

    target_groups: Dict[str, set[str]] = {
        "company": {
            "identity",
            "company",
            "company_profile",
            "financial",
            "location",
            "source_flag",
            "policy_summary",
            "linkage_summary",
            "flood",
            "data_quality",
        },
        "policy": {
            "identity",
            "company",
            "policy",
            "policy_financial",
            "policy_summary",
        },
        "linkage": {
            "identity",
            "company",
            "linkage",
            "linkage_summary",
            "policy_summary",
            "flood",
        },
        "director": {
            "linkage",
            "linkage_summary",
        },
        "flood": {
            "location",
            "flood",
            "spatial",
            "data_source",
            "source_flag",
        },
        "spatial": {
            "identity",
            "company",
            "location",
            "flood",
            "spatial",
            "source_flag",
        },
        "flood_rainfall_latest": {
            "location",
            "flood",
            "data_source",
            "source_flag",
        },
        "flood_waterlevel_latest": {
            "location",
            "flood",
            "data_source",
            "source_flag",
        },
        "flood_dam_latest": {
            "location",
            "flood",
            "data_source",
            "source_flag",
        },
        "flood_prediction_latest": {
            "prediction",
            "flood",
            "location",
            "map",
            "data_source",
            "source_flag",
        },
        "flood_prediction_map": {
            "prediction",
            "flood",
            "location",
            "map",
            "data_source",
            "source_flag",
        },
        "prediction_map_view": {
            "prediction",
            "flood",
            "location",
            "map",
            "data_source",
            "source_flag",
        },
        "uploaded_entity_latest": {
            "entity",
            "location",
            "map",
            "source_flag",
        },
        "entity_overlay_view": {
            "entity",
            "location",
            "map",
            "source_flag",
        },
        "map_layers": {
            "map",
            "flood",
            "prediction",
            "entity",
            "location",
            "source_flag",
        },
        "map": {
            "map",
            "location",
            "flood",
            "prediction",
            "entity",
            "source_flag",
        },
        "dashboard_province_insights": {
            "dashboard",
            "flood",
            "prediction",
            "location",
        },
        "province_insight_view": {
            "dashboard",
            "flood",
            "prediction",
            "location",
        },
        "dashboard": {
            "dashboard",
            "flood",
            "prediction",
            "location",
            "data_quality",
            "policy_summary",
            "linkage_summary",
        },
        "flood_dashboard_view": {
            "dashboard",
            "flood",
            "prediction",
            "location",
            "data_quality",
        },
        "data_quality": {
            "data_quality",
            "cache",
            "data_source",
            "general",
        },
        "package": {
            "identity",
            "company",
            "company_profile",
            "financial",
            "location",
            "source_flag",
            "policy",
            "policy_financial",
            "policy_summary",
            "linkage",
            "linkage_summary",
            "flood",
            "spatial",
            "prediction",
            "entity",
            "map",
            "dashboard",
            "data_quality",
        },
        "cache_registry": {
            "cache",
        },
    }

    allowed_groups = target_groups.get(target_key)

    if allowed_groups is None:
        return []

    return [
        field_definition_to_dict(field_def)
        for field_def in fields
        if field_def.group in allowed_groups
    ]

def get_searchable_fields(target: Optional[str] = None) -> List[str]:
    """
    คืนชื่อ field ที่ search ได้
    """

    filterable = get_filterable_fields(target)
    return [
        field["name"]
        for field in filterable
        if field.get("searchable")
    ]


def get_sortable_fields(target: Optional[str] = None) -> List[str]:
    """
    คืนชื่อ field ที่ sort ได้
    """

    filterable = get_filterable_fields(target)
    return [
        field["name"]
        for field in filterable
        if field.get("sortable")
    ]

def get_exportable_fields(dataset_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    คืน field ที่ export ได้ โดยตัด internal path/debug/raw field ออกเสมอ
    """

    if dataset_key and dataset_key in DATASET_SCHEMAS:
        allowed_fields = set(DATASET_SCHEMAS[dataset_key].fields)

        return [
            field_definition_to_dict(field_def)
            for name, field_def in FIELD_DEFINITIONS.items()
            if name in allowed_fields
            and field_def.exportable
            and name not in INTERNAL_NON_EXPORTABLE_FIELDS
        ]

    return [
        field_definition_to_dict(field_def)
        for name, field_def in FIELD_DEFINITIONS.items()
        if field_def.exportable
        and name not in INTERNAL_NON_EXPORTABLE_FIELDS
    ]

def get_dataset_schema(dataset_key: str) -> Optional[Dict[str, Any]]:
    """
    คืน dataset schema
    """

    schema = DATASET_SCHEMAS.get(dataset_key)

    if not schema:
        return None

    return dataset_schema_to_dict(schema)


def get_all_dataset_schemas() -> Dict[str, Dict[str, Any]]:
    """
    คืน dataset schema ทั้งหมด
    """

    return {
        key: dataset_schema_to_dict(schema)
        for key, schema in DATASET_SCHEMAS.items()
    }


def get_all_input_schemas() -> Dict[str, Any]:
    """
    คืน input schema ทั้งหมด
    """

    return {
        "policy": {
            key: sheet_schema_to_dict(schema)
            for key, schema in POLICY_INPUT_SCHEMA.items()
        },
        "linkage": sheet_schema_to_dict(LINKAGE_INPUT_SCHEMA),
        "flood": {
            key: sheet_schema_to_dict(schema)
            for key, schema in FLOOD_INPUT_SCHEMA.items()
        },
    }


def validate_required_columns(
    columns: List[str],
    required_columns: List[str],
    case_sensitive: bool = False,
) -> Dict[str, Any]:
    """
    ตรวจ required columns

    Args:
        columns:
            column ที่มีจริง

        required_columns:
            column ที่ต้องมี

        case_sensitive:
            ถ้า False จะเทียบแบบ lowercase

    Returns:
        dict:
            valid, missing_columns, available_columns
    """

    if case_sensitive:
        available = set(str(col).strip() for col in columns)
        required = set(str(col).strip() for col in required_columns)
    else:
        available = set(str(col).strip().lower() for col in columns)
        required = set(str(col).strip().lower() for col in required_columns)

    missing = sorted(list(required - available))

    return {
        "valid": len(missing) == 0,
        "missing_columns": missing,
        "available_columns": list(columns),
        "required_columns": list(required_columns),
    }

def validate_filter_payload(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    ตรวจ Filter Payload ตาม Field Dictionary และ Runtime Target
    """

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if not isinstance(payload, dict):
        return {
            "valid": False,
            "errors": [
                {
                    "code": "invalid_filter_payload",
                    "message": "payload ต้องเป็น object",
                }
            ],
            "warnings": [],
        }

    target = str(
        payload.get("target", "company")
        or "company"
    ).strip().lower()

    if target not in RUNTIME_FILTER_TARGETS:
        errors.append(
            {
                "code": "invalid_filter_target",
                "message": f"target ไม่ถูกต้อง: {target}",
                "allowed_targets": list(RUNTIME_FILTER_TARGETS),
            }
        )

    allowed_fields = {
        field_item["name"]
        for field_item in get_filterable_fields(target)
    }

    filters = payload.get("filters", {})

    if not isinstance(filters, dict):
        errors.append(
            {
                "code": "invalid_filters",
                "message": "filters ต้องเป็น object",
            }
        )
    else:
        for raw_field_name in filters.keys():
            field_name = str(raw_field_name or "").strip()
            base_field = field_name

            if (
                base_field.endswith("_min")
                or base_field.endswith("_max")
            ):
                base_field = base_field[:-4]

            field_definition = FIELD_DEFINITIONS.get(base_field)

            if field_definition is None:
                errors.append(
                    {
                        "code": "unknown_filter_field",
                        "message": (
                            "ไม่พบ field ใน dictionary: "
                            f"{base_field}"
                        ),
                        "field": field_name,
                    }
                )
                continue

            if not field_definition.filterable:
                errors.append(
                    {
                        "code": "field_not_filterable",
                        "message": (
                            f"field ไม่รองรับ filter: {base_field}"
                        ),
                        "field": field_name,
                    }
                )
                continue

            if allowed_fields and base_field not in allowed_fields:
                errors.append(
                    {
                        "code": "field_not_allowed_for_target",
                        "message": (
                            f"field {base_field} "
                            f"ไม่รองรับ target {target}"
                        ),
                        "field": field_name,
                        "target": target,
                    }
                )

    advanced = payload.get("advanced", {})

    if advanced:
        if not isinstance(advanced, dict):
            errors.append(
                {
                    "code": "invalid_advanced_filter",
                    "message": "advanced ต้องเป็น object",
                }
            )
        else:
            logic = str(
                advanced.get("logic", "AND")
                or "AND"
            ).strip().upper()

            if logic not in FILTER_LOGICAL_OPERATORS:
                errors.append(
                    {
                        "code": "invalid_filter_logic",
                        "message": (
                            "logical operator ไม่ถูกต้อง: "
                            f"{logic}"
                        ),
                        "allowed_operators": list(
                            FILTER_LOGICAL_OPERATORS
                        ),
                    }
                )

            conditions = advanced.get(
                "conditions",
                [],
            )

            if not isinstance(conditions, list):
                errors.append(
                    {
                        "code": "invalid_filter_conditions",
                        "message": "conditions ต้องเป็น list",
                    }
                )
                conditions = []

            for index, condition in enumerate(conditions):
                if not isinstance(condition, dict):
                    errors.append(
                        {
                            "code": "invalid_filter_condition",
                            "message": "condition ต้องเป็น object",
                            "index": index,
                        }
                    )
                    continue

                field_name = str(
                    condition.get("field")
                    or ""
                ).strip()

                operator = str(
                    condition.get("operator")
                    or condition.get("op")
                    or ""
                ).strip()

                if not field_name:
                    errors.append(
                        {
                            "code": "filter_field_missing",
                            "message": (
                                "filter condition ไม่มี field"
                            ),
                            "index": index,
                        }
                    )
                    continue

                field_definition = FIELD_DEFINITIONS.get(
                    field_name
                )

                if field_definition is None:
                    errors.append(
                        {
                            "code": "unknown_filter_field",
                            "message": (
                                "ไม่พบ field ใน dictionary: "
                                f"{field_name}"
                            ),
                            "field": field_name,
                            "index": index,
                        }
                    )
                elif not field_definition.filterable:
                    errors.append(
                        {
                            "code": "field_not_filterable",
                            "message": (
                                "field ไม่รองรับ filter: "
                                f"{field_name}"
                            ),
                            "field": field_name,
                            "index": index,
                        }
                    )
                elif (
                    allowed_fields
                    and field_name not in allowed_fields
                ):
                    errors.append(
                        {
                            "code": "field_not_allowed_for_target",
                            "message": (
                                f"field {field_name} "
                                f"ไม่รองรับ target {target}"
                            ),
                            "field": field_name,
                            "target": target,
                            "index": index,
                        }
                    )

                if not operator:
                    errors.append(
                        {
                            "code": "filter_operator_missing",
                            "message": (
                                "filter condition ไม่มี operator"
                            ),
                            "field": field_name,
                            "index": index,
                        }
                    )
                elif operator not in FILTER_OPERATORS:
                    errors.append(
                        {
                            "code": "invalid_filter_operator",
                            "message": (
                                "operator ไม่ถูกต้อง: "
                                f"{operator}"
                            ),
                            "field": field_name,
                            "index": index,
                            "allowed_operators": list(
                                FILTER_OPERATORS
                            ),
                        }
                    )

                if (
                    operator
                    not in {
                        "is_empty",
                        "is_not_empty",
                    }
                    and "value" not in condition
                ):
                    errors.append(
                        {
                            "code": "filter_value_missing",
                            "message": (
                                "filter condition ไม่มี value"
                            ),
                            "field": field_name,
                            "index": index,
                        }
                    )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }

def validate_package_request(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate Package Request ตาม Package Contract กลาง
    """

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if not isinstance(payload, dict):
        return {
            "valid": False,
            "errors": [
                {
                    "code": "invalid_package_payload",
                    "message": "payload ต้องเป็น object",
                }
            ],
            "warnings": [],
        }

    package_name = str(
        payload.get("package_name", "")
        or ""
    ).strip()

    if not package_name:
        errors.append(
            {
                "code": "package_name_required",
                "message": "ต้องระบุ package_name",
            }
        )

    components = payload.get(
        "components",
        list(PACKAGE_COMPONENTS),
    )

    if not isinstance(components, list):
        errors.append(
            {
                "code": "package_components_invalid",
                "message": "components ต้องเป็น list",
            }
        )
    else:
        normalized_components = [
            str(component or "").strip()
            for component in components
            if str(component or "").strip()
        ]

        if not normalized_components:
            errors.append(
                {
                    "code": "package_components_required",
                    "message": (
                        "ต้องเลือก package component "
                        "อย่างน้อย 1 รายการ"
                    ),
                }
            )

        unknown_components = sorted(
            {
                component
                for component in normalized_components
                if component not in PACKAGE_COMPONENTS
            }
        )

        if unknown_components:
            errors.append(
                {
                    "code": "unknown_package_components",
                    "message": (
                        "พบ package component ที่ไม่รองรับ"
                    ),
                    "components": unknown_components,
                    "allowed_components": list(
                        PACKAGE_COMPONENTS
                    ),
                }
            )

        duplicate_components = sorted(
            {
                component
                for component in normalized_components
                if normalized_components.count(component) > 1
            }
        )

        if duplicate_components:
            warnings.append(
                {
                    "code": "duplicate_package_components",
                    "message": (
                        "พบ package component ซ้ำ"
                    ),
                    "components": duplicate_components,
                }
            )

    security = payload.get(
        "security",
        dict(PACKAGE_SECURITY_OPTIONS),
    )

    if not isinstance(security, dict):
        errors.append(
            {
                "code": "package_security_invalid",
                "message": "security ต้องเป็น object",
            }
        )
    else:
        unknown_security_keys = sorted(
            {
                str(key)
                for key in security.keys()
                if key not in PACKAGE_SECURITY_OPTIONS
            }
        )

        if unknown_security_keys:
            errors.append(
                {
                    "code": "unknown_package_security_options",
                    "message": (
                        "พบ security option ที่ไม่รองรับ"
                    ),
                    "fields": unknown_security_keys,
                    "allowed_fields": list(
                        PACKAGE_SECURITY_OPTIONS.keys()
                    ),
                }
            )

        for field_name, value in security.items():
            if (
                field_name in PACKAGE_SECURITY_OPTIONS
                and not isinstance(value, bool)
            ):
                errors.append(
                    {
                        "code": "package_security_value_invalid",
                        "message": (
                            f"security.{field_name} "
                            "ต้องเป็น boolean"
                        ),
                        "field": field_name,
                    }
                )

    expire_days = payload.get(
        "expire_days",
        PACKAGE_DEFAULT_EXPIRE_DAYS,
    )

    try:
        expire_days_int = int(expire_days)

        if expire_days_int <= 0:
            errors.append(
                {
                    "code": "package_expire_days_invalid",
                    "message": (
                        "expire_days ต้องมากกว่า 0"
                    ),
                }
            )
        elif expire_days_int > PACKAGE_MAX_EXPIRE_DAYS:
            errors.append(
                {
                    "code": "package_expire_days_exceeded",
                    "message": (
                        "expire_days ต้องไม่เกิน "
                        f"{PACKAGE_MAX_EXPIRE_DAYS}"
                    ),
                    "max_expire_days": (
                        PACKAGE_MAX_EXPIRE_DAYS
                    ),
                }
            )

    except Exception:
        errors.append(
            {
                "code": "package_expire_days_invalid",
                "message": "expire_days ต้องเป็นตัวเลข",
            }
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }

# ============================================================
# 18) FRONTEND CONTRACT HELPERS
# ============================================================

def get_api_route_catalog() -> Dict[str, List[Dict[str, Any]]]:
    """
    สร้าง Route Catalog จาก FastAPI Router ที่ใช้งานจริง
    """

    catalog: Dict[str, List[Dict[str, Any]]] = {}
    seen: set[Tuple[str, str]] = set()
    router_sources: List[Tuple[Any, str]] = []

    try:
        from api_routes import router as api_router

        router_sources.append(
            (
                api_router,
                "",
            )
        )
    except Exception:
        pass

    try:
        from auth.auth_routes import router as auth_router

        router_sources.append(
            (
                auth_router,
                API_PREFIX,
            )
        )
    except Exception:
        pass

    group_mapping: Dict[str, str] = {
        "health": "core",
        "status": "core",
        "config": "core",
        "paths": "core",
        "inputs": "core",
        "routes": "core",
        "schema": "core",
        "auth": "auth",
        "companies": "company",
        "policy": "policy",
        "linkage": "linkage",
        "flood": "flood",
        "latest": "flood",
        "history": "flood",
        "master": "flood",
        "prediction": "prediction",
        "forecast": "prediction",
        "spatial": "spatial",
        "upload": "upload",
        "map": "map",
        "charts": "dashboard",
        "dashboard": "dashboard",
        "summary": "dashboard",
        "filter": "filter",
        "data-quality": "data_quality",
        "admin": "data_quality",
        "cache": "cache",
        "detail": "detail",
        "search": "detail",
        "packages": "package",
        "public": "package",
    }

    for router_source, path_prefix in router_sources:
        for route in getattr(
            router_source,
            "routes",
            [],
        ):
            route_path = str(
                getattr(route, "path", "")
                or ""
            ).strip()

            if not route_path:
                continue

            full_path = route_path

            if (
                path_prefix
                and not full_path.startswith(path_prefix)
            ):
                full_path = (
                    f"{path_prefix.rstrip('/')}/"
                    f"{full_path.lstrip('/')}"
                )

            methods = sorted(
                method
                for method in (
                    getattr(route, "methods", set())
                    or set()
                )
                if method not in {
                    "HEAD",
                    "OPTIONS",
                }
            )

            if not methods:
                continue

            relative_path = full_path

            if relative_path.startswith(API_PREFIX):
                relative_path = relative_path[
                    len(API_PREFIX):
                ]

            first_segment = (
                relative_path
                .strip("/")
                .split("/", 1)[0]
            )

            group = group_mapping.get(
                first_segment,
                first_segment or "core",
            )

            description = str(
                getattr(route, "summary", "")
                or ""
            ).strip()

            if not description:
                route_description = str(
                    getattr(route, "description", "")
                    or ""
                ).strip()

                if route_description:
                    description = (
                        route_description.splitlines()[0]
                    )

            if not description:
                description = str(
                    getattr(route, "name", "")
                    or ""
                )

            for method in methods:
                route_key = (
                    method,
                    full_path,
                )

                if route_key in seen:
                    continue

                seen.add(route_key)

                catalog.setdefault(
                    group,
                    [],
                ).append(
                    {
                        "method": method,
                        "path": full_path,
                        "name": str(
                            getattr(route, "name", "")
                            or ""
                        ),
                        "description": description,
                    }
                )

    if not catalog:
        fallback_catalog = deepcopy(
            API_ROUTE_CATALOG
        )

        for routes in fallback_catalog.values():
            for route in routes:
                route["path"] = (
                    str(route.get("path") or "")
                    .replace("<", "{")
                    .replace(">", "}")
                )

        return fallback_catalog

    return {
        group: sorted(
            routes,
            key=lambda item: (
                item.get("path", ""),
                item.get("method", ""),
            ),
        )
        for group, routes in sorted(
            catalog.items(),
            key=lambda item: item[0],
        )
    }


def flatten_api_route_catalog() -> List[Dict[str, Any]]:
    """
    คืน Route Catalog แบบ Flat List
    """

    records: List[Dict[str, Any]] = []

    for group, routes in get_api_route_catalog().items():
        for route in routes:
            item = dict(route)
            item["group"] = group
            records.append(item)

    return sorted(
        records,
        key=lambda item: (
            item.get("path", ""),
            item.get("method", ""),
        ),
    )

def get_prediction_contract_schema() -> Dict[str, Any]:
    """
    คืน prediction contract สำหรับ /api/prediction/contract
    """

    return {
        "record_schema": FLOOD_PREDICTION_RECORD_SCHEMA,
        "dataset_schema": dataset_schema_to_dict(DATASET_SCHEMAS["flood_prediction_latest"]),
        "map_dataset_schema": dataset_schema_to_dict(DATASET_SCHEMAS["flood_prediction_map"]),
        "required_fields": DATASET_SCHEMAS["flood_prediction_latest"].required_fields,
        "fields": DATASET_SCHEMAS["flood_prediction_latest"].fields,
        "field_aliases": {
            "risk": [
                "risk_level",
                "risk_status",
                "warning_level",
                "warning_level_predict",
            ],
            "province": [
                "province",
                "province_model",
                "prediction_province",
                "prediction_province_model",
            ],
            "station": [
                "station_name",
                "station_id",
                "station_code",
                "matched_station_id",
                "matched_station_code",
                "matched_station_name",
            ],
            "horizon": [
                "forecast_horizon_day",
                "prediction_horizon",
                "horizon",
            ],
        },
        "map_contract": {
            "map_ready": "true ถ้ามีพิกัดจาก station master",
            "focus_level": "station|province_boundary|none",
            "focus_fallback": "station|province_boundary|none",
            "focus_fallback_reason": "matched_station_master|province_boundary_fallback|missing_location",
            "latitude_longitude_source": "station_master_first_then_province_boundary_fallback",
            "public_map_can_expose_lat_lon": True,
        },
        "record_key": "prediction|station|base_date|target_date|forecast_horizon_day",
        "public_allowed_fields": [
            "province",
            "station_name",
            "risk_level",
            "target_date",
            "forecast_horizon_day",
            "latest_value",
            "latest_unit",
            "map_ready",
            "latitude",
            "longitude",
        ],
    }

def get_cache_rebuild_contract_schema() -> Dict[str, Any]:
    """
    คืน contract ของ cache registry และ rebuild phase
    """

    return {
        "cache_registry_item": CACHE_REGISTRY_ITEM_SCHEMA,
        "rebuild_phase_result": REBUILD_PHASE_RESULT_SCHEMA,
        "phase_order": [
            "validate_runtime_inputs",
            "company_policy_base",
            "linkage",
            "flood_excel_base",
            "spatial_prediction_entity",
            "company_policy_enriched",
            "map",
            "dashboard_charts",
            "data_quality",
            "package_snapshot",
        ],
    }

def get_frontend_field_dictionary() -> Dict[str, Any]:
    """
    คืน field dictionary สำหรับ frontend

    ใช้โดย:
    - filter builder
    - table column selector
    - package builder
    - data dictionary panel
    """

    return {
        "field_groups": FIELD_GROUPS,
        "fields": {
            name: field_definition_to_dict(field_def)
            for name, field_def in FIELD_DEFINITIONS.items()
        },
        "filterable_fields": get_filterable_fields(),
        "operators": FILTER_OPERATORS,
        "logical_operators": FILTER_LOGICAL_OPERATORS,
        "table_views": TABLE_VIEW_SCHEMAS,
        "runtime_contracts": {
            "data_source": DATA_SOURCE_CONFIG_SCHEMA,
            "flood_latest": FLOOD_LATEST_RECORD_SCHEMA,
            "flood_prediction": FLOOD_PREDICTION_RECORD_SCHEMA,
            "uploaded_entity": UPLOADED_ENTITY_RECORD_SCHEMA,
            "map_layer": MAP_LAYER_PAYLOAD_SCHEMA,
            "merged_map_layers": MERGED_MAP_LAYERS_PAYLOAD_SCHEMA,
            "dashboard_province_insights": DASHBOARD_PROVINCE_INSIGHTS_SCHEMA,
            "cache_registry": CACHE_REGISTRY_ITEM_SCHEMA,
            "rebuild_phase_result": REBUILD_PHASE_RESULT_SCHEMA,
        },
    }

def get_frontend_schema_bundle() -> Dict[str, Any]:
    """
    คืน Schema Bundle ทั้งหมดที่ Frontend ต้องใช้
    """

    uploaded_entity_schema = FLOOD_INPUT_SCHEMA.get(
        "uploaded_entity",
        SheetSchema(
            key="uploaded_entity",
            display_name="uploaded_entity.csv/.xlsx/.xls",
            description="uploaded entity fallback schema",
            required_columns=list(
                ENTITY_REQUIRED_COLUMNS
            ),
            optional_columns=[
                column
                for column in ENTITY_SUPPORTED_COLUMNS
                if column not in set(
                    ENTITY_REQUIRED_COLUMNS
                )
            ],
            source_type="tabular_upload",
        ),
    )

    prediction_schema = FLOOD_INPUT_SCHEMA.get(
        "prediction_latest",
        SheetSchema(
            key="prediction_latest",
            display_name="predict_YYYY_MM_DD.xlsx",
            description="prediction fallback schema",
            required_columns=list(
                PREDICTION_REQUIRED_COLUMNS
            ),
            optional_columns=[
                column
                for column in PREDICTION_SUPPORTED_COLUMNS
                if column not in set(
                    PREDICTION_REQUIRED_COLUMNS
                )
            ],
            source_type="excel",
        ),
    )

    route_catalog = get_api_route_catalog()
    route_list = flatten_api_route_catalog()

    bundle: Dict[str, Any] = {
        "api": {
            "prefix": API_PREFIX,
            "public_prefix": PUBLIC_API_PREFIX,
            "response_example": make_api_schema_example(),
            "routes": route_catalog,
            "route_list": route_list,
        },
        "fields": get_frontend_field_dictionary(),
        "datasets": get_all_dataset_schemas(),
        "inputs": get_all_input_schemas(),
        "data_source": DATA_SOURCE_CONFIG_SCHEMA,
        "filter": {
            "payload_example": FILTER_PAYLOAD_EXAMPLE,
            "operators": FILTER_OPERATORS,
            "logical_operators": (
                FILTER_LOGICAL_OPERATORS
            ),
            "targets": RUNTIME_FILTER_TARGETS,
        },
        "map": {
            "layer_schema": MAP_LAYER_SCHEMA,
            "merged_layers_schema": (
                MERGED_MAP_LAYERS_PAYLOAD_SCHEMA
            ),
            "feature_property_schema": (
                MAP_FEATURE_PROPERTY_SCHEMA
            ),
            "canonical_layer_order": (
                MERGED_MAP_LAYERS_PAYLOAD_SCHEMA[
                    "layer_order"
                ]
            ),
        },
        "graph": {
            "node_schema": GRAPH_NODE_SCHEMA,
            "edge_schema": GRAPH_EDGE_SCHEMA,
            "payload_schema": GRAPH_PAYLOAD_SCHEMA,
        },
        "dashboard": {
            "summary_card_schema": (
                SUMMARY_CARD_SCHEMA
            ),
            "dashboard_summary_schema": (
                DASHBOARD_SUMMARY_SCHEMA
            ),
            "province_insights_schema": (
                DASHBOARD_PROVINCE_INSIGHTS_SCHEMA
            ),
            "chart_payload_schema": (
                CHART_PAYLOAD_SCHEMA
            ),
        },
        "prediction": {
            **get_prediction_contract_schema(),
            "input_schema": sheet_schema_to_dict(
                prediction_schema
            ),
        },
        "entity": {
            "record_schema": (
                UPLOADED_ENTITY_RECORD_SCHEMA
            ),
            "input_schema": sheet_schema_to_dict(
                uploaded_entity_schema
            ),
            "required_fields": list(
                uploaded_entity_schema.required_columns
            ),
            "public_policy": {
                "displayable_only": True,
                "remove_internal_paths": True,
                "remove_raw_invalid_rows": True,
            },
        },
        "cache_rebuild": (
            get_cache_rebuild_contract_schema()
        ),
        "package": {
            "request_schema": asdict(
                PackageRequestSchema(
                    package_name="Example Package",
                    description=(
                        "Example dashboard snapshot"
                    ),
                )
            ),
            "meta_schema": PACKAGE_META_SCHEMA,
            "snapshot_schema": (
                PACKAGE_SNAPSHOT_SCHEMA
            ),
            "public_schema": PUBLIC_PACKAGE_SCHEMA,
            "security_schema": MASKING_SCHEMA,
            "checksum_components": (
                PACKAGE_SNAPSHOT_SCHEMA[
                    "checksum_components"
                ]
            ),
        },
        "data_quality": {
            "issue_schema": asdict(
                DataQualityIssueSchema(
                    issue_id="ISSUE_EXAMPLE",
                    category="input",
                    severity="warning",
                    code="example_issue",
                    message="Example issue",
                )
            ),
            "summary_schema": (
                DATA_QUALITY_SUMMARY_SCHEMA
            ),
            "severities": (
                DATA_QUALITY_SEVERITIES
            ),
            "categories": (
                DATA_QUALITY_CATEGORIES
            ),
        },
    }

    return deepcopy(bundle)

# ============================================================
# 19) DEFAULT EMPTY PAYLOADS
# ============================================================

EMPTY_PAYLOADS: Dict[str, Any] = {
    "company_list": {
        "records": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
    },
    "policy_summary": {
        "total_premium": 0,
        "total_loss": 0,
        "total_suminsure": 0,
        "total_policy_count": 0,
        "average_loss_ratio": 0,
    },
    "linkage_graph": {
        "nodes": [],
        "edges": [],
        "summary": {
            "node_count": 0,
            "edge_count": 0,
            "company_node_count": 0,
            "director_node_count": 0,
            "key_connector_count": 0,
        },
        "layout": {
            "mode": "force",
            "depth": 1,
            "limited": False,
            "max_nodes": 300,
        },
        "warnings": [],
    },
    "map_layers": {
        "map": {},
        "center": [],
        "zoom": 0,
        "layers": {},
        "layers_by_id": {},
        "layer_order": [],
        "layer_list": [],
        "layers_list": [],
        "legacy_layers": [],
        "summary": {
            "layer_count": 0,
            "canonical_layer_count": 0,
            "feature_count": 0,
            "record_count": 0,
            "record_count_by_layer": {},
            "enabled_layers": [],
            "compatibility_layers": [],
            "degraded_layer_ids": [],
            "generated_at": "",
            "degraded": False,
        },
        "meta": {
            "source": "excel",
            "filters": {},
            "counts": {},
            "record_count_by_layer": {},
            "upstream_cache_keys": [],
            "degraded": False,
            "errors": [],
            "generated_at": "",
            "cache_used": False,
        },
    },
    "flood_rainfall_latest": {
        "records": [],
        "total": 0,
        "meta": {
            "source": "excel",
        },
    },
    "flood_waterlevel_latest": {
        "records": [],
        "total": 0,
        "meta": {
            "source": "excel",
        },
    },
    "flood_dam_latest": {
        "records": [],
        "total": 0,
        "meta": {
            "source": "excel",
        },
    },
    "flood_prediction_latest": {
        "records": [],
        "total": 0,
        "meta": {
            "source": "excel",
            "map_ready_count": 0,
        },
    },
    "flood_prediction_map": {
        "type": "FeatureCollection",
        "features": [],
        "total": 0,
        "meta": {
            "source": "excel",
            "map_ready_count": 0,
            "province_fallback_count": 0,
        },
    },
    "uploaded_entity_latest": {
        "records": [],
        "displayable_records": [],
        "not_displayable_records": [],
        "total": 0,
        "meta": {
            "source": "uploaded_entity",
        },
    },
    "dashboard_province_insights": {
        "prediction_risk_top3": [],
        "rainfall_top5": [],
        "waterlevel_top5": [],
        "reservoir_top5": [],
        "filters": {},
        "generated_at": "",
    },
    "dashboard_summary": {
        "summary_cards": [],
        "charts": {},
        "top_companies": [],
        "top_directors": [],
        "risk_insights": [],
        "province_insights": DASHBOARD_PROVINCE_INSIGHTS_SCHEMA,
        "prediction_risk_top3": [],
        "rainfall_top5": [],
        "waterlevel_top5": [],
        "reservoir_top5": [],
        "data_quality": DATA_QUALITY_SUMMARY_SCHEMA,
        "freshness": {},
    },
    "data_quality": DATA_QUALITY_SUMMARY_SCHEMA,
    "cache_registry": {
        "records": [],
        "total": 0,
    },
    "rebuild_phase_result": {
        "phase": "",
        "status": "pending",
        "outputs": {},
        "errors": [],
        "warnings": [],
        "duration_ms": None,
    },
    "package_preview": {
        "components": PACKAGE_COMPONENTS,
        "security_options": PACKAGE_SECURITY_OPTIONS,
        "estimated_records": {},
        "warnings": [],
    },
    "package_snapshot": PACKAGE_SNAPSHOT_SCHEMA,
    "public_package": PUBLIC_PACKAGE_SCHEMA,
}

def get_empty_payload(
    key: str,
) -> Any:
    """
    คืน Empty Payload ตาม Key โดยไม่คืน Reference ของ Global Object
    """

    payload = EMPTY_PAYLOADS.get(
        str(key or "").strip(),
        {},
    )

    return deepcopy(payload)

# ============================================================
# 20) MODULE SUMMARY
# ============================================================

def get_schema_summary() -> Dict[str, Any]:
    """
    คืน Summary ของ schemas.py
    """

    required_runtime_inputs = [
        "rainfall_latest",
        "waterlevel_latest",
        "large_dam_latest",
        "medium_dam_latest",
        "all_long_latest",
        "prediction_latest",
        "uploaded_entity",
    ]

    required_runtime_datasets = [
        "company_unified_base",
        "company_unified_master",
        "flood_rainfall_latest",
        "flood_waterlevel_latest",
        "flood_dam_latest",
        "flood_prediction_latest",
        "flood_prediction_map",
        "uploaded_entity_latest",
        "map_layers",
        "dashboard_province_insights",
        "cache_registry",
        "rebuild_phase_result",
    ]

    missing_inputs = [
        key
        for key in required_runtime_inputs
        if key not in FLOOD_INPUT_SCHEMA
    ]

    missing_datasets = [
        key
        for key in required_runtime_datasets
        if key not in DATASET_SCHEMAS
    ]

    route_catalog = get_api_route_catalog()
    route_list = flatten_api_route_catalog()

    return {
        "field_count": len(FIELD_DEFINITIONS),
        "field_group_count": len(FIELD_GROUPS),
        "dataset_count": len(DATASET_SCHEMAS),
        "policy_input_sheet_count": len(
            POLICY_INPUT_SCHEMA
        ),
        "flood_input_sheet_count": len(
            FLOOD_INPUT_SCHEMA
        ),
        "api_group_count": len(route_catalog),
        "api_route_count": len(route_list),
        "table_view_count": len(
            TABLE_VIEW_SCHEMAS
        ),
        "package_component_count": len(
            PACKAGE_COMPONENTS
        ),
        "data_quality_category_count": len(
            DATA_QUALITY_CATEGORIES
        ),
        "runtime_contracts": [
            "DataSourceConfigSchema",
            "FloodLatestRecord",
            "FloodPredictionRecord",
            "UploadedEntityRecord",
            "MapLayerPayloadSchema",
            "DashboardProvinceInsightsSchema",
            "CacheRegistryItemSchema",
            "RebuildPhaseResultSchema",
        ],
        "runtime_filter_targets": list(
            RUNTIME_FILTER_TARGETS
        ),
        "new_runtime_datasets": (
            required_runtime_datasets
        ),
        "required_runtime_inputs": (
            required_runtime_inputs
        ),
        "missing_runtime_inputs": (
            missing_inputs
        ),
        "missing_runtime_datasets": (
            missing_datasets
        ),
        "contract_ready": (
            not missing_inputs
            and not missing_datasets
        ),
        "schema_bundle_version": (
            SCHEMA_BUNDLE_VERSION
        ),
    }

SCHEMA_BUNDLE_VERSION: str = "1.0.0"
