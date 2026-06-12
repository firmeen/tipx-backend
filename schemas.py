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
try:
    import bootstrap
    BOOTSTRAP_LOADED = True
except Exception as e:
    bootstrap = None
    BOOTSTRAP_LOADED = False
    BOOTSTRAP_ERROR = str(e)
from dataclasses import asdict, dataclass, field 
from datetime import datetime
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
    DATA_QUALITY_SEVERITIES,
    DATA_QUALITY_CATEGORIES,
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
    required_columns: List[str] = field(default_factory=list)
    optional_columns: List[str] = field(default_factory=list)
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
    fields: List[str] = field(default_factory=list)
    required_fields: List[str] = field(default_factory=list)
    default_sort: Optional[str] = None
    default_sort_dir: str = "asc"
    supports_filter: bool = True
    supports_search: bool = True
    supports_export: bool = True


# ============================================================
# 3) STANDARD API RESPONSE SCHEMA
# ============================================================

@dataclass
class ApiMeta:
    """
    meta ของ API response ทุก endpoint
    """

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
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
    data: Any = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    errors: List[Any] = field(default_factory=list)


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
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    groups: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class FilterPayloadSchema:
    """
    Payload สำหรับ filter builder
    """

    target: str = "company"
    filters: Dict[str, Any] = field(default_factory=dict)
    advanced: Dict[str, Any] = field(default_factory=dict)
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
    geometry: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GeoJSONFeatureCollectionSchema:
    """
    FeatureCollection แบบ GeoJSON
    """

    type: str = "FeatureCollection"
    features: List[Dict[str, Any]] = field(default_factory=list)


MAP_LAYER_SCHEMA: Dict[str, Any] = {
    "layer_id": "string",
    "layer_name": "string",
    "layer_type": "point|line|polygon|heatmap|cluster",
    "visible": "boolean",
    "record_count": "integer",
    "feature_collection": {
        "type": "FeatureCollection",
        "features": [],
    },
    "style": {
        "color_field": "string",
        "size_field": "string",
        "risk_field": "string",
    },
}


MAP_FEATURE_PROPERTY_SCHEMA: Dict[str, str] = {
    "feature_id": "string",
    "feature_type": "company|rainfall|waterlevel|dam|branch|province|basin|linkage_line",
    "tax_id_norm": "string",
    "company_name": "string",
    "province": "string",
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
    filters: Dict[str, Any] = field(default_factory=dict)
    components: List[str] = field(default_factory=lambda: list(PACKAGE_COMPONENTS))
    security: Dict[str, Any] = field(default_factory=lambda: dict(PACKAGE_SECURITY_OPTIONS))
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
        "map_layers": {},
        "charts": {},
        "tables": {},
        "filter_options": {},
        "data_quality": {},
    },
}


PUBLIC_PACKAGE_SCHEMA: Dict[str, Any] = {
    "meta": PACKAGE_META_SCHEMA,
    "summary": {},
    "map": {},
    "charts": {},
    "tables": {},
    "filter_options": {},
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
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


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


# ============================================================
# 16) API ROUTE CATALOG
# ============================================================

API_ROUTE_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "core": [
        {"method": "GET", "path": f"{API_PREFIX}/health", "description": "ตรวจสุขภาพระบบ"},
        {"method": "GET", "path": f"{API_PREFIX}/status", "description": "สถานะระบบ"},
        {"method": "GET", "path": f"{API_PREFIX}/config", "description": "config summary"},
        {"method": "GET", "path": f"{API_PREFIX}/routes", "description": "รายการ API routes"},
        {"method": "GET", "path": f"{API_PREFIX}/paths", "description": "สถานะ path"},
        {"method": "GET", "path": f"{API_PREFIX}/inputs", "description": "สถานะ input file"},
    ],
    "company": [
        {"method": "GET", "path": f"{API_PREFIX}/companies", "description": "รายการบริษัท"},
        {"method": "GET", "path": f"{API_PREFIX}/companies/<tax_id>", "description": "รายละเอียดบริษัท"},
        {"method": "GET", "path": f"{API_PREFIX}/companies/summary", "description": "summary บริษัท"},
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
        {"method": "GET", "path": f"{API_PREFIX}/flood/computed-risk", "description": "computed flood risk"},
    ],
    "map": [
        {"method": "GET", "path": f"{API_PREFIX}/map/layers", "description": "OpenLayers layers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/companies", "description": "company markers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/flood", "description": "flood markers"},
        {"method": "GET", "path": f"{API_PREFIX}/map/linkage-lines", "description": "linkage line layer"},
    ],
    "filter": [
        {"method": "GET", "path": f"{API_PREFIX}/filter/fields", "description": "filter fields"},
        {"method": "GET", "path": f"{API_PREFIX}/filter/quick-presets", "description": "quick presets"},
        {"method": "POST", "path": f"{API_PREFIX}/filter/preview", "description": "preview filter"},
        {"method": "POST", "path": f"{API_PREFIX}/filter/apply", "description": "apply filter"},
    ],
    "package": [
        {"method": "POST", "path": f"{API_PREFIX}/packages/preview", "description": "preview package"},
        {"method": "POST", "path": f"{API_PREFIX}/packages/generate", "description": "generate package"},
        {"method": "GET", "path": f"{API_PREFIX}/packages", "description": "list packages"},
        {"method": "GET", "path": f"{PUBLIC_API_PREFIX}/packages/<package_id>/data", "description": "public package data"},
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


def get_filterable_fields(target: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    คืน field ที่ filter ได้

    Args:
        target:
            company / policy / linkage / flood
    """

    fields = [
        field_def
        for field_def in FIELD_DEFINITIONS.values()
        if field_def.filterable
    ]

    if target:
        target_groups = {
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
            "flood": {
                "location",
                "flood",
                "spatial",
            },
        }.get(target, set())

        if target_groups:
            fields = [
                field_def
                for field_def in fields
                if field_def.group in target_groups
            ]

    return [field_definition_to_dict(field_def) for field_def in fields]


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
    คืน field ที่ export ได้
    """

    if dataset_key and dataset_key in DATASET_SCHEMAS:
        allowed_fields = set(DATASET_SCHEMAS[dataset_key].fields)

        return [
            field_definition_to_dict(field_def)
            for name, field_def in FIELD_DEFINITIONS.items()
            if name in allowed_fields and field_def.exportable
        ]

    return [
        field_definition_to_dict(field_def)
        for field_def in FIELD_DEFINITIONS.values()
        if field_def.exportable
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


def validate_filter_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    validate filter payload แบบเบื้องต้น

    ไม่ apply filter จริง
    แค่ตรวจว่าโครงสร้างถูกหรือไม่
    """

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    target = payload.get("target", "company")

    if target not in {"company", "policy", "linkage", "flood", "map", "dashboard"}:
        errors.append(
            {
                "code": "invalid_filter_target",
                "message": f"target ไม่ถูกต้อง: {target}",
            }
        )

    advanced = payload.get("advanced", {})

    if advanced:
        logic = advanced.get("logic", "AND")

        if logic not in FILTER_LOGICAL_OPERATORS:
            errors.append(
                {
                    "code": "invalid_filter_logic",
                    "message": f"logical operator ไม่ถูกต้อง: {logic}",
                }
            )

        for condition in advanced.get("conditions", []):
            field_name = condition.get("field")
            operator = condition.get("operator")

            if not field_name:
                errors.append(
                    {
                        "code": "filter_field_missing",
                        "message": "filter condition ไม่มี field",
                    }
                )
                continue

            if field_name not in FIELD_DEFINITIONS:
                warnings.append(
                    {
                        "code": "unknown_filter_field",
                        "message": f"ไม่พบ field ใน dictionary: {field_name}",
                    }
                )

            if operator not in FILTER_OPERATORS:
                errors.append(
                    {
                        "code": "invalid_filter_operator",
                        "message": f"operator ไม่ถูกต้อง: {operator}",
                    }
                )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def validate_package_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    validate package request
    """

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    package_name = str(payload.get("package_name", "")).strip()

    if not package_name:
        errors.append(
            {
                "code": "package_name_required",
                "message": "ต้องระบุ package_name",
            }
        )

    components = payload.get("components", PACKAGE_COMPONENTS)

    if not isinstance(components, list):
        errors.append(
            {
                "code": "package_components_invalid",
                "message": "components ต้องเป็น list",
            }
        )
    else:
        unknown_components = [
            component
            for component in components
            if component not in PACKAGE_COMPONENTS
        ]

        if unknown_components:
            warnings.append(
                {
                    "code": "unknown_package_components",
                    "message": "พบ component ที่ไม่รู้จัก",
                    "components": unknown_components,
                }
            )

    security = payload.get("security", {})

    if security and not isinstance(security, dict):
        errors.append(
            {
                "code": "package_security_invalid",
                "message": "security ต้องเป็น object",
            }
        )

    expire_days = payload.get("expire_days", 30)

    try:
        expire_days_int = int(expire_days)
        if expire_days_int <= 0:
            warnings.append(
                {
                    "code": "package_no_expire_or_invalid",
                    "message": "expire_days น้อยกว่าหรือเท่ากับ 0",
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
    }


def get_frontend_schema_bundle() -> Dict[str, Any]:
    """
    คืน schema bundle ทั้งหมดที่ frontend ต้องใช้
    """

    return {
        "api": {
            "prefix": API_PREFIX,
            "public_prefix": PUBLIC_API_PREFIX,
            "response_example": make_api_schema_example(),
            "routes": API_ROUTE_CATALOG,
        },
        "fields": get_frontend_field_dictionary(),
        "datasets": get_all_dataset_schemas(),
        "inputs": get_all_input_schemas(),
        "filter": {
            "payload_example": FILTER_PAYLOAD_EXAMPLE,
            "operators": FILTER_OPERATORS,
            "logical_operators": FILTER_LOGICAL_OPERATORS,
        },
        "map": {
            "layer_schema": MAP_LAYER_SCHEMA,
            "feature_property_schema": MAP_FEATURE_PROPERTY_SCHEMA,
        },
        "graph": {
            "node_schema": GRAPH_NODE_SCHEMA,
            "edge_schema": GRAPH_EDGE_SCHEMA,
            "payload_schema": GRAPH_PAYLOAD_SCHEMA,
        },
        "dashboard": {
            "summary_card_schema": SUMMARY_CARD_SCHEMA,
            "dashboard_summary_schema": DASHBOARD_SUMMARY_SCHEMA,
            "chart_payload_schema": CHART_PAYLOAD_SCHEMA,
        },
        "package": {
            "request_schema": asdict(
                PackageRequestSchema(
                    package_name="Example Package",
                    description="Example dashboard snapshot",
                )
            ),
            "meta_schema": PACKAGE_META_SCHEMA,
            "snapshot_schema": PACKAGE_SNAPSHOT_SCHEMA,
            "public_schema": PUBLIC_PACKAGE_SCHEMA,
            "security_schema": MASKING_SCHEMA,
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
            "summary_schema": DATA_QUALITY_SUMMARY_SCHEMA,
            "severities": DATA_QUALITY_SEVERITIES,
            "categories": DATA_QUALITY_CATEGORIES,
        },
    }


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
        "layers": {},
        "summary": {
            "layer_count": 0,
            "feature_count": 0,
        },
    },
    "dashboard_summary": {
        "summary_cards": [],
        "charts": {},
        "top_companies": [],
        "top_directors": [],
        "risk_insights": [],
        "data_quality": DATA_QUALITY_SUMMARY_SCHEMA,
        "freshness": {},
    },
    "data_quality": DATA_QUALITY_SUMMARY_SCHEMA,
    "package_preview": {
        "components": PACKAGE_COMPONENTS,
        "security_options": PACKAGE_SECURITY_OPTIONS,
        "estimated_records": {},
        "warnings": [],
    },
}


def get_empty_payload(key: str) -> Any:
    """
    คืน empty payload ตาม key
    """

    return EMPTY_PAYLOADS.get(key, {})


# ============================================================
# 20) MODULE SUMMARY
# ============================================================

def get_schema_summary() -> Dict[str, Any]:
    """
    คืน summary ของ schemas.py
    """

    return {
        "field_count": len(FIELD_DEFINITIONS),
        "field_group_count": len(FIELD_GROUPS),
        "dataset_count": len(DATASET_SCHEMAS),
        "policy_input_sheet_count": len(POLICY_INPUT_SCHEMA),
        "flood_input_sheet_count": len(FLOOD_INPUT_SCHEMA),
        "api_group_count": len(API_ROUTE_CATALOG),
        "table_view_count": len(TABLE_VIEW_SCHEMAS),
        "package_component_count": len(PACKAGE_COMPONENTS),
        "data_quality_category_count": len(DATA_QUALITY_CATEGORIES),
    }


SCHEMA_BUNDLE_VERSION: str = "1.0.0"