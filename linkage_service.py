# ============================================================
# FILE: backend/linkage_service.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 10 / 20
# ============================================================

"""
backend/linkage_service.py

ไฟล์นี้เป็นศูนย์กลาง Linkage / Director Network / Graph Processing ของระบบ TIPX

หน้าที่หลัก:
1. อ่าน Linkage Input File
2. normalize tax_id
3. normalize company name
4. parse boardlist
5. สร้าง director_master
6. สร้าง director_company_pairs
7. สร้าง linkage_nodes สำหรับ D3 graph
8. สร้าง linkage_edges สำหรับ D3 graph
9. สร้าง DIRECTOR_OF edges
10. สร้าง SHARED_DIRECTOR edges
11. คำนวณ key connector
12. คำนวณ shared director links
13. คำนวณ exposure by director
14. เชื่อม policy exposure จาก company_unified_master
15. เชื่อม flood context จาก company_unified_master
16. รองรับ API /api/linkage/*
17. ส่ง graph payload ให้ frontend dashboard_modules.js ใช้กับ D3
18. เขียน cache ให้ module อื่นใช้ต่อ

Data Source:
- input/linkage/linkage_input.xlsx
- cache/company_unified_master.json จาก company_policy_service.py ถ้ามี

Core Concepts:
- Company Node:
    id = company:<tax_id_norm>
- Director Node:
    id = director:<director_id>
- DIRECTOR_OF edge:
    company <-> director
- SHARED_DIRECTOR edge:
    company <-> company ผ่านกรรมการร่วม
- Key Connector:
    director ที่เชื่อมมากกว่า 1 บริษัท
"""

from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from config import (
    LINKAGE_INPUT_PATH,
    LINKAGE_SHEET_INDEX_FALLBACK,
    LINKAGE_COLUMNS,
    CACHE_TTL_SECONDS,
    GRAPH_DEFAULT_MODE,
    GRAPH_DEFAULT_DEPTH,
    GRAPH_DEFAULT_MAX_NODES,
    GRAPH_NODE_SIZE,
    GRAPH_COLORS,
    EDGE_TYPE_DIRECTOR_OF,
    EDGE_TYPE_SHARED_DIRECTOR,
)

from utils import (
    apply_search_sort_pagination,
    clean_dataframe_common,
    clean_text,
    clean_text_lower,
    first_non_empty,
    get_or_build_cache,
    group_records_by,
    is_empty_value,
    make_company_node_id,
    make_director_id,
    make_director_node_id,
    make_edge_id,
    make_hash_id,
    normalize_director_name,
    normalize_director_name_for_id,
    normalize_tax_id,
    parse_boardlist,
    read_cache,
    read_excel_by_logical_sheet,
    rename_columns_by_candidates,
    to_bool,
    to_int,
    to_jsonable,
    to_number,
    validate_tax_id,
    write_cache,
)

try:
    from filter_engine import filter_records_for_service
except Exception:
    filter_records_for_service = None


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
    "mode": GRAPH_DEFAULT_MODE,
    "depth": GRAPH_DEFAULT_DEPTH,
    "max_nodes": GRAPH_DEFAULT_MAX_NODES,
    "tax_id": "",
    "director_id": "",
    "include_shared_edges": True,
    "include_policy": True,
    "include_flood": True,
}

CACHE_KEYS: Dict[str, str] = {
    "linkage_input_clean": "linkage_input_clean",
    "director_company_pairs": "director_company_pairs",
    "director_master": "director_master",
    "linkage_nodes": "linkage_nodes",
    "linkage_edges": "linkage_edges",
    "shared_director_links": "shared_director_links",
    "key_connector_summary": "key_connector_summary",
    "linkage_company_summary": "linkage_company_summary",
    "linkage_graph_payload": "linkage_graph_payload",
    "linkage_graph": "linkage_graph_payload",
    "graph_payload": "linkage_graph_payload",
    "exposure_by_director": "exposure_by_director",
}

LINKAGE_SEARCHABLE_FIELDS: List[str] = [
    "tax_id_norm",
    "company_name",
    "director_id",
    "director_name",
    "business_type_objective",
    "business_type_tsic",
    "company_size",
    "wtip",
]

DIRECTOR_SEARCHABLE_FIELDS: List[str] = [
    "director_id",
    "director_name",
    "company_list_text",
    "risk_level_text",
]


LINKAGE_GRAPH_MAIN_CACHE_KEY = "linkage_graph_payload"

LINKAGE_GRAPH_ALIAS_CACHE_KEYS: Dict[str, str] = {
    "linkage_graph": LINKAGE_GRAPH_MAIN_CACHE_KEY,
    "graph_payload": LINKAGE_GRAPH_MAIN_CACHE_KEY,
}

SHARED_LINK_SEARCHABLE_FIELDS: List[str] = [
    "source_tax_id",
    "target_tax_id",
    "source_company_name",
    "target_company_name",
    "shared_directors_text",
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

    result["mode"] = clean_text(
        result.get(
            "mode",
            GRAPH_DEFAULT_MODE,
        ),
        default=GRAPH_DEFAULT_MODE,
    )

    try:
        result["depth"] = max(
            1,
            min(
                5,
                int(
                    result.get(
                        "depth",
                        GRAPH_DEFAULT_DEPTH,
                    )
                    or GRAPH_DEFAULT_DEPTH
                ),
            ),
        )
    except (TypeError, ValueError):
        result["depth"] = GRAPH_DEFAULT_DEPTH

    try:
        result["max_nodes"] = max(
            10,
            min(
                1500,
                int(
                    result.get(
                        "max_nodes",
                        GRAPH_DEFAULT_MAX_NODES,
                    )
                    or GRAPH_DEFAULT_MAX_NODES
                ),
            ),
        )
    except (TypeError, ValueError):
        result["max_nodes"] = (
            GRAPH_DEFAULT_MAX_NODES
        )

    result["tax_id"] = get_valid_tax_id(
        result.get("tax_id", "")
    )
    result["director_id"] = clean_text(
        result.get("director_id", "")
    )

    result["include_shared_edges"] = bool(
        to_bool(
            result.get(
                "include_shared_edges",
                True,
            ),
            default=True,
        )
    )
    result["include_policy"] = bool(
        to_bool(
            result.get("include_policy", True),
            default=True,
        )
    )
    result["include_flood"] = bool(
        to_bool(
            result.get("include_flood", True),
            default=True,
        )
    )

    return result

def get_linkage_ttl() -> int:
    """
    TTL สำหรับ linkage cache
    """

    return int(CACHE_TTL_SECONDS.get("linkage", 3600))

def get_valid_tax_id(
    value: Any,
) -> str:
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


def get_linkage_risk_level(
    director_count: Any,
    shared_company_count: Any,
    key_connector_count: Any,
) -> str:
    director_total = (
        to_int(
            director_count,
            0,
        )
        or 0
    )

    shared_total = (
        to_int(
            shared_company_count,
            0,
        )
        or 0
    )

    connector_total = (
        to_int(
            key_connector_count,
            0,
        )
        or 0
    )

    if (
        connector_total > 0
        or shared_total >= 5
    ):
        return "Warning"

    if (
        shared_total > 0
        or director_total > 0
    ):
        return "Watch"

    return "Normal"

def filter_records_api(
    records: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
    searchable_fields: Optional[List[str]] = None,
    target: str = "linkage",
) -> Dict[str, Any]:
    """
    apply filter/search/sort/pagination
    """

    ctx = normalize_context(context)

    if filter_records_for_service is not None:
        try:
            filtered_result = (
                filter_records_for_service(
                    records=records,
                    context=ctx,
                    target=target,
                    paginate=True,
                )
            )

            if (
                isinstance(filtered_result, dict)
                and isinstance(
                    filtered_result.get("records"),
                    list,
                )
            ):
                return filtered_result

        except Exception:
            pass

    filtered_records = list(
        records
        or []
    )

    try:
        from filter_engine import apply_simple_filters

        filtered_records = apply_simple_filters(
            filtered_records,
            ctx.get("filters", {}),
        )
    except Exception:
        pass

    return apply_search_sort_pagination(
        records=filtered_records,
        context=ctx,
        searchable_fields=searchable_fields,
    )

# ============================================================
# 3) INPUT LOADER
# ============================================================

def load_linkage_input_clean(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    อ่าน linkage_input.xlsx และ clean เบื้องต้น

    Output records จะมี field:
    - tax_id_raw
    - tax_id_norm
    - tax_id_valid
    - tax_id_issue
    - company_name
    - boardlist
    - business_type_objective
    - most_recent_income_val
    - registered_capital
    - business_type_tsic
    - company_size
    - wtip
    """

    def builder() -> Dict[str, Any]:
        if (
            not LINKAGE_INPUT_PATH.exists()
            or not LINKAGE_INPUT_PATH.is_file()
        ):
            return {
                "records": [],
                "total": 0,
                "source_path": str(
                    LINKAGE_INPUT_PATH
                ),
                "created_at": now_iso(),
                "warnings": [
                    "linkage_input_file_missing"
                ],
            }

        try:
            df = read_excel_by_logical_sheet(
                LINKAGE_INPUT_PATH,
                expected_sheet_name=None,
                fallback_index=(
                    LINKAGE_SHEET_INDEX_FALLBACK
                ),
                dtype=str,
            )
        except Exception:
            return {
                "records": [],
                "total": 0,
                "source_path": str(
                    LINKAGE_INPUT_PATH
                ),
                "created_at": now_iso(),
                "warnings": [
                    "linkage_input_read_failed"
                ],
            }

        df = clean_dataframe_common(df)

        df = rename_columns_by_candidates(
            df,
            LINKAGE_COLUMNS,
            keep_original=True,
        )

        if df.empty:
            return {
                "records": [],
                "total": 0,
                "source_path": str(
                    LINKAGE_INPUT_PATH
                ),
                "created_at": now_iso(),
                "warnings": [
                    "linkage_input_empty"
                ],
            }

        if "tax_id" not in df.columns:
            df["tax_id"] = ""

        records: List[
            Dict[str, Any]
        ] = []

        for idx, row in df.iterrows():
            validation = validate_tax_id(
                row.get("tax_id")
            )

            company_name = clean_text(
                row.get("name_th")
                or row.get("company_name")
            )

            director_names: List[str] = []
            seen_director_ids: Set[str] = set()

            for raw_director_name in parse_boardlist(
                row.get("boardlist")
            ):
                director_name = normalize_director_name(
                    raw_director_name
                )

                director_id = make_director_id(
                    director_name
                )

                if (
                    not director_name
                    or not director_id
                    or director_id
                    in seen_director_ids
                ):
                    continue

                seen_director_ids.add(
                    director_id
                )
                director_names.append(
                    director_name
                )

            records.append(
                {
                    "source_file": (
                        LINKAGE_INPUT_PATH.name
                    ),
                    "source_sheet": (
                        "linkage_input"
                    ),
                    "source_row": int(idx) + 2,
                    "tax_id_raw": validation.get(
                        "tax_id_raw",
                        "",
                    ),
                    "tax_id_norm": validation.get(
                        "tax_id_norm",
                        "",
                    ),
                    "tax_id_valid": bool(
                        validation.get(
                            "tax_id_valid",
                            False,
                        )
                    ),
                    "tax_id_issue": validation.get(
                        "tax_id_issue",
                        "",
                    ),
                    "company_name": company_name,
                    "name_th": company_name,
                    "boardlist": clean_text(
                        row.get("boardlist")
                    ),
                    "director_names": (
                        director_names
                    ),
                    "director_count_raw": len(
                        director_names
                    ),
                    "business_type_objective": clean_text(
                        row.get(
                            "business_type_objective"
                        )
                    ),
                    "business_type_tsic": clean_text(
                        row.get(
                            "business_type_tsic"
                        )
                    ),
                    "company_size": clean_text(
                        row.get("company_size")
                    ),
                    "wtip": clean_text(
                        row.get("wtip")
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
                }
            )

        return {
            "records": records,
            "total": len(records),
            "source_path": str(
                LINKAGE_INPUT_PATH
            ),
            "created_at": now_iso(),
            "invalid_tax_id_count": sum(
                1
                for record in records
                if not record.get(
                    "tax_id_valid"
                )
            ),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "linkage_input_clean"
        ],
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source=(
            "linkage_service."
            "load_linkage_input_clean"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }

def get_linkage_input_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน linkage input clean records
    """

    return load_linkage_input_clean(force_refresh=force_refresh).get("records", [])


# ============================================================
# 4) COMPANY UNIFIED ENRICHMENT
# ============================================================

def extract_records_from_cache_payload(
    payload: Any,
) -> List[Dict[str, Any]]:
    """
    ดึง records จาก cache payload หลายรูปแบบ
    """

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
        return extract_records_from_cache_payload(
            data
        )

    return []


def index_company_records_by_tax_id(
    records: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    index company records ด้วย valid tax_id_norm
    """

    result: Dict[
        str,
        Dict[str, Any],
    ] = {}

    def record_score(
        record: Dict[str, Any],
    ) -> int:
        return sum(
            1
            for value in record.values()
            if not is_empty_value(value)
        )

    for record in records or []:
        if not isinstance(record, dict):
            continue

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

def load_company_source_payload() -> Dict[str, Any]:
    """
    PHASE linkage อ่าน company_unified_base เท่านั้น

    ถ้าไม่มี company_unified_base:
    - ใช้ linkage input record เป็น fallback
    - ไม่อ่าน company_unified_master
      เพื่อไม่สร้าง circular dependency
    """

    payload = read_cache(
        "company_unified_base",
        default={},
    )

    records = extract_records_from_cache_payload(
        payload
    )

    if records:
        return {
            "company_source": (
                "company_unified_base"
            ),
            "records": records,
            "index": (
                index_company_records_by_tax_id(
                    records
                )
            ),
            "record_count": len(records),
            "degraded": False,
        }

    return {
        "company_source": (
            "linkage_input_fallback"
        ),
        "records": [],
        "index": {},
        "record_count": 0,
        "degraded": True,
    }

def build_linkage_cache_meta(
    cache_key: str,
    source_input: str,
    company_source: str,
    record_count: int = 0,
    node_count: int = 0,
    edge_count: int = 0,
    cache_used: bool = False,
    degraded: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    metadata กลางของ linkage cache
    """

    return {
        "cache_key": cache_key,
        "source_input": source_input,
        "company_source": company_source,
        "record_count": int(record_count or 0),
        "node_count": int(node_count or 0),
        "edge_count": int(edge_count or 0),
        "generated_at": now_iso(),
        "cache_used": bool(cache_used),
        "degraded": bool(degraded),
        **(extra or {}),
    }


def write_linkage_graph_aliases(payload: Dict[str, Any], cache_used: bool = False) -> Dict[str, Any]:
    """
    เขียน alias cache ให้ข้อมูลเดียวกับ linkage_graph_payload
    """

    alias_results: Dict[str, Any] = {}

    if not isinstance(payload, dict):
        return alias_results

    for alias_key in LINKAGE_GRAPH_ALIAS_CACHE_KEYS.keys():
        alias_payload = dict(payload)
        alias_payload["meta"] = {
            **(payload.get("meta") if isinstance(payload.get("meta"), dict) else {}),
            "cache_key": LINKAGE_GRAPH_MAIN_CACHE_KEY,
            "alias_cache_key": alias_key,
            "alias_of": LINKAGE_GRAPH_MAIN_CACHE_KEY,
            "cache_used": bool(cache_used),
            "generated_at": now_iso(),
        }

        alias_results[alias_key] = write_cache(
            alias_key,
            alias_payload,
            ttl_seconds=get_linkage_ttl(),
            source=f"linkage_service.write_linkage_graph_aliases.{alias_key}",
        )

    return alias_results

def load_company_unified_index() -> Dict[str, Dict[str, Any]]:
    """
    โหลด company index สำหรับ linkage phase

    ลำดับ:
    1. company_unified_base
    2. company_unified_master
    3. linkage_input_fallback ผ่าน enrich_company_fields(base)
    """

    return load_company_source_payload().get("index", {})


def enrich_company_fields(
    base: Dict[str, Any],
    company_index: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    เติมข้อมูลจาก company_unified_base/company_unified_master เข้า linkage record

    ถ้าไม่มี company cache ให้ fallback เป็น linkage input record เดิม
    """

    if company_index is None:
        company_index = load_company_unified_index()

    tax_id_norm = normalize_tax_id(base.get("tax_id_norm") or base.get("tax_id"))
    company = company_index.get(tax_id_norm, {}) if isinstance(company_index, dict) else {}

    result = dict(base)

    result.update(
        {
            "company_name": first_non_empty(
                company.get("company_name"),
                base.get("company_name"),
                base.get("name_th"),
                default="",
            ),
            "province": first_non_empty(company.get("province"), base.get("province"), default=""),
            "district": first_non_empty(company.get("district"), base.get("district"), default=""),
            "subdistrict": first_non_empty(company.get("subdistrict"), base.get("subdistrict"), default=""),
            "lat": company.get("lat", base.get("lat")),
            "lon": company.get("lon", base.get("lon")),
            "latitude": company.get("latitude", company.get("lat", base.get("latitude", base.get("lat")))),
            "longitude": company.get("longitude", company.get("lon", base.get("longitude", base.get("lon")))),

            "has_policy": bool(to_bool(company.get("has_policy", base.get("has_policy")), default=False)),
            "has_location": bool(to_bool(company.get("has_location", base.get("has_location")), default=False)),
            "has_flood_context": bool(to_bool(company.get("has_flood_context", base.get("has_flood_context")), default=False)),

            "total_premium": to_number(company.get("total_premium", base.get("total_premium")), 0) or 0,
            "total_loss": to_number(company.get("total_loss", base.get("total_loss")), 0) or 0,
            "total_suminsure": to_number(company.get("total_suminsure", base.get("total_suminsure")), 0) or 0,
            "loss_ratio": first_non_empty(company.get("loss_ratio"), base.get("loss_ratio"), default=None),
            "loss_ratio_band": first_non_empty(company.get("loss_ratio_band"), base.get("loss_ratio_band"), default="Undefined"),

            "most_recent_income_val": first_non_empty(
                company.get("most_recent_income_val"),
                base.get("most_recent_income_val"),
                default=None,
            ),
            "registered_capital": first_non_empty(
                company.get("registered_capital"),
                base.get("registered_capital"),
                default=None,
            ),

            "flood_risk_level": first_non_empty(
                company.get("flood_risk_level"),
                base.get("flood_risk_level"),
                default="Unknown",
            ),
            "flood_join_level": first_non_empty(
                company.get("flood_join_level"),
                base.get("flood_join_level"),
                default="none",
            ),
            "flood_risk_reason": first_non_empty(
                company.get("flood_risk_reason"),
                base.get("flood_risk_reason"),
                default="",
            ),
            "location_quality": first_non_empty(
                company.get("location_quality"),
                base.get("location_quality"),
                default="",
            ),
            "company_source": company.get("record_stage", "company_cache") if company else "linkage_input_fallback",
        }
    )

    return result

# ============================================================
# 5) DIRECTOR-COMPANY PAIRS
# ============================================================

def build_director_company_pairs(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง director_company_pairs

    PHASE linkage อ่าน company_unified_base ก่อน
    ถ้าไม่มี company cache ให้ใช้ linkage input fallback
    """

    def builder() -> Dict[str, Any]:
        linkage_records = get_linkage_input_records(
            force_refresh=force_refresh
        )

        company_source_payload = (
            load_company_source_payload()
        )

        company_index = (
            company_source_payload.get(
                "index",
                {},
            )
        )

        company_source = (
            company_source_payload.get(
                "company_source",
                "linkage_input_fallback",
            )
        )

        pairs: List[
            Dict[str, Any]
        ] = []

        invalid_company_count = 0
        invalid_director_count = 0

        for record in linkage_records:
            tax_id_norm = get_valid_tax_id(
                record.get("tax_id_norm")
                or record.get("tax_id")
                or record.get("tax_id_raw")
            )

            if not tax_id_norm:
                invalid_company_count += 1
                continue

            company_enriched = enrich_company_fields(
                record,
                company_index=company_index,
            )

            director_names = record.get(
                "director_names"
            )

            if not isinstance(
                director_names,
                list,
            ):
                director_names = parse_boardlist(
                    record.get("boardlist")
                )

            directors: Dict[str, str] = {}

            for raw_director_name in director_names:
                director_name = normalize_director_name(
                    raw_director_name
                )

                director_id = make_director_id(
                    director_name
                )

                if (
                    not director_name
                    or not director_id
                ):
                    invalid_director_count += 1
                    continue

                directors.setdefault(
                    director_id,
                    director_name,
                )

            for director_id, director_name in sorted(
                directors.items(),
                key=lambda item: item[1],
            ):
                company_node_id = make_company_node_id(
                    tax_id_norm
                )

                director_node_id = make_director_node_id(
                    director_id
                )

                pair = {
                    "pair_id": make_hash_id(
                        (
                            f"{tax_id_norm}|"
                            f"{director_id}"
                        ),
                        prefix="pair",
                        length=20,
                    ),
                    "tax_id_norm": tax_id_norm,
                    "tax_id_valid": True,
                    "company_node_id": (
                        company_node_id
                    ),
                    "company_name": (
                        company_enriched.get(
                            "company_name",
                            "",
                        )
                    ),
                    "director_id": director_id,
                    "director_node_id": (
                        director_node_id
                    ),
                    "director_name": director_name,
                    "director_name_norm": (
                        normalize_director_name_for_id(
                            director_name
                        )
                    ),
                    "business_type_objective": (
                        company_enriched.get(
                            "business_type_objective",
                            "",
                        )
                    ),
                    "business_type_tsic": (
                        company_enriched.get(
                            "business_type_tsic",
                            "",
                        )
                    ),
                    "company_size": (
                        company_enriched.get(
                            "company_size",
                            "",
                        )
                    ),
                    "wtip": company_enriched.get(
                        "wtip",
                        "",
                    ),
                    "province": (
                        company_enriched.get(
                            "province",
                            "",
                        )
                    ),
                    "district": (
                        company_enriched.get(
                            "district",
                            "",
                        )
                    ),
                    "lat": company_enriched.get(
                        "lat"
                    ),
                    "lon": company_enriched.get(
                        "lon"
                    ),
                    "latitude": (
                        company_enriched.get(
                            "latitude",
                            company_enriched.get(
                                "lat"
                            ),
                        )
                    ),
                    "longitude": (
                        company_enriched.get(
                            "longitude",
                            company_enriched.get(
                                "lon"
                            ),
                        )
                    ),
                    "location_quality": (
                        company_enriched.get(
                            "location_quality",
                            "",
                        )
                    ),
                    "has_policy": bool(
                        to_bool(
                            company_enriched.get(
                                "has_policy"
                            ),
                            default=False,
                        )
                    ),
                    "has_location": bool(
                        to_bool(
                            company_enriched.get(
                                "has_location"
                            ),
                            default=False,
                        )
                    ),
                    "has_flood_context": bool(
                        to_bool(
                            company_enriched.get(
                                "has_flood_context"
                            ),
                            default=False,
                        )
                    ),
                    "total_premium": (
                        to_number(
                            company_enriched.get(
                                "total_premium"
                            ),
                            0,
                        )
                        or 0
                    ),
                    "total_loss": (
                        to_number(
                            company_enriched.get(
                                "total_loss"
                            ),
                            0,
                        )
                        or 0
                    ),
                    "total_suminsure": (
                        to_number(
                            company_enriched.get(
                                "total_suminsure"
                            ),
                            0,
                        )
                        or 0
                    ),
                    "loss_ratio": (
                        company_enriched.get(
                            "loss_ratio"
                        )
                    ),
                    "loss_ratio_band": (
                        company_enriched.get(
                            "loss_ratio_band",
                            "Undefined",
                        )
                    ),
                    "most_recent_income_val": (
                        company_enriched.get(
                            "most_recent_income_val"
                        )
                    ),
                    "registered_capital": (
                        company_enriched.get(
                            "registered_capital"
                        )
                    ),
                    "flood_risk_level": (
                        company_enriched.get(
                            "flood_risk_level",
                            "Unknown",
                        )
                    ),
                    "flood_join_level": (
                        company_enriched.get(
                            "flood_join_level",
                            "none",
                        )
                    ),
                    "flood_risk_reason": (
                        company_enriched.get(
                            "flood_risk_reason",
                            "",
                        )
                    ),
                    "edge_contract": {
                        "company_node_id": (
                            company_node_id
                        ),
                        "director_node_id": (
                            director_node_id
                        ),
                        "edge_type": (
                            EDGE_TYPE_DIRECTOR_OF
                        ),
                    },
                    "company_source": (
                        company_source
                    ),
                    "source_file": record.get(
                        "source_file",
                        "",
                    ),
                    "source_row": record.get(
                        "source_row"
                    ),
                }

                pairs.append(pair)

        unique = {
            pair["pair_id"]: pair
            for pair in pairs
        }

        records = sorted(
            unique.values(),
            key=lambda item: (
                clean_text(
                    item.get("director_name")
                ),
                clean_text(
                    item.get("company_name")
                ),
            ),
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
            "meta": build_linkage_cache_meta(
                cache_key=CACHE_KEYS[
                    "director_company_pairs"
                ],
                source_input=str(
                    LINKAGE_INPUT_PATH
                ),
                company_source=company_source,
                record_count=len(records),
                degraded=(
                    company_source
                    != "company_unified_base"
                ),
                extra={
                    "invalid_company_count": (
                        invalid_company_count
                    ),
                    "invalid_director_count": (
                        invalid_director_count
                    ),
                },
            ),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "director_company_pairs"
        ],
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source=(
            "linkage_service."
            "build_director_company_pairs"
        ),
    )

    data = dict(
        cache_result["data"]
    )

    data["cache_used"] = cache_result[
        "cache_used"
    ]

    if isinstance(
        data.get("meta"),
        dict,
    ):
        data["meta"]["cache_used"] = (
            cache_result["cache_used"]
        )

    return data

def get_director_company_pair_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน director-company pairs
    """

    return build_director_company_pairs(force_refresh=force_refresh).get("records", [])


# ============================================================
# 6) DIRECTOR MASTER
# ============================================================

def build_director_master(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง director_master

    1 แถว = director 1 คน
    """

    def builder() -> Dict[str, Any]:
        pairs = get_director_company_pair_records(force_refresh=force_refresh)
        groups = group_records_by(pairs, "director_id")

        records: List[Dict[str, Any]] = []

        for director_id, group in groups.items():
            if director_id == "__EMPTY__":
                continue

            company_tax_ids = sorted(
                {
                    normalize_tax_id(item.get("tax_id_norm"))
                    for item in group
                    if normalize_tax_id(item.get("tax_id_norm"))
                }
            )

            company_names = sorted(
                {
                    clean_text(item.get("company_name"))
                    for item in group
                    if clean_text(item.get("company_name"))
                }
            )

            provinces = sorted(
                {
                    clean_text(item.get("province"))
                    for item in group
                    if clean_text(item.get("province"))
                }
            )

            risk_levels = sorted(
                {
                    clean_text(item.get("flood_risk_level"), default="Unknown")
                    for item in group
                }
            )

            director_name = first_non_empty(
                *[item.get("director_name") for item in group],
                default="",
            )

            company_count = len(company_tax_ids)
            is_key_connector = company_count > 1

            record = {
                "director_id": director_id,
                "director_name": director_name,
                "director_name_norm": normalize_director_name_for_id(director_name),
                "company_count": company_count,
                "company_list": company_names,
                "company_list_text": ", ".join(company_names),
                "tax_id_list": company_tax_ids,
                "province_list": provinces,
                "province_count": len(provinces),
                "is_key_connector": is_key_connector,

                "total_connected_income": sum(to_number(item.get("most_recent_income_val"), 0) or 0 for item in group),
                "total_connected_capital": sum(to_number(item.get("registered_capital"), 0) or 0 for item in group),
                "total_connected_premium": sum(to_number(item.get("total_premium"), 0) or 0 for item in group),
                "total_connected_loss": sum(to_number(item.get("total_loss"), 0) or 0 for item in group),
                "total_connected_suminsure": sum(to_number(item.get("total_suminsure"), 0) or 0 for item in group),

                "connected_flood_risk_levels": risk_levels,
                "risk_level_text": ", ".join(risk_levels),
                "highest_flood_risk_level": _combine_risk_levels_safe(risk_levels),

                "connected_loss_ratio_bands": sorted(
                    {
                        clean_text(item.get("loss_ratio_band"), default="Undefined")
                        for item in group
                    }
                ),

                "has_any_policy": any(to_bool(item.get("has_policy"), default=False) for item in group),
                "has_any_flood_context": any(to_bool(item.get("has_flood_context"), default=False) for item in group),

                "created_at": now_iso(),
            }

            records.append(record)

        records = sorted(
            records,
            key=lambda item: (
                not bool(item.get("is_key_connector")),
                -(to_number(item.get("company_count"), 0) or 0),
                clean_text(item.get("director_name")),
            ),
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["director_master"],
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source="linkage_service.build_director_master",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def _combine_risk_levels_safe(levels: List[Any]) -> str:
    """
    combine risk levels แบบไม่ให้ module พัง
    """

    try:
        from utils import combine_risk_levels
        return combine_risk_levels(levels)
    except Exception:
        priority = {
            "Critical": 4,
            "Warning": 3,
            "Watch": 2,
            "Normal": 1,
            "Unknown": 0,
        }
        best = "Unknown"
        best_score = -1

        for level in levels:
            text = clean_text(level, default="Unknown")
            score = priority.get(text, 0)
            if score > best_score:
                best = text
                best_score = score

        return best


def get_director_master_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน director_master records
    """

    return build_director_master(force_refresh=force_refresh).get("records", [])


# ============================================================
# 7) LINKAGE COMPANY SUMMARY
# ============================================================

def build_linkage_company_summary(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง linkage_company_summary

    1 แถว = company 1 บริษัท
    พร้อมจำนวน director, shared company และ key connector
    """

    def builder() -> Dict[str, Any]:
        pairs = get_director_company_pair_records(
            force_refresh=force_refresh
        )

        director_master = get_director_master_records(
            force_refresh=force_refresh
        )

        director_index = {
            clean_text(
                item.get("director_id")
            ): item
            for item in director_master
            if clean_text(
                item.get("director_id")
            )
        }

        shared_links = build_shared_director_links(
            force_refresh=force_refresh
        ).get(
            "records",
            [],
        )

        shared_company_by_tax_id: Dict[
            str,
            Set[str],
        ] = defaultdict(set)

        for link in shared_links:
            source_tax_id = get_valid_tax_id(
                link.get("source_tax_id")
            )
            target_tax_id = get_valid_tax_id(
                link.get("target_tax_id")
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

        groups = group_records_by(
            pairs,
            "tax_id_norm",
        )

        records: List[
            Dict[str, Any]
        ] = []

        for raw_tax_id, group in groups.items():
            tax_id_norm = get_valid_tax_id(
                raw_tax_id
            )

            if not tax_id_norm:
                continue

            representative = max(
                group,
                key=lambda item: sum(
                    1
                    for value in item.values()
                    if not is_empty_value(value)
                ),
            )

            director_ids = sorted(
                {
                    clean_text(
                        item.get("director_id")
                    )
                    for item in group
                    if clean_text(
                        item.get("director_id")
                    )
                }
            )

            key_connector_ids = [
                director_id
                for director_id in director_ids
                if bool(
                    to_bool(
                        director_index.get(
                            director_id,
                            {},
                        ).get(
                            "is_key_connector"
                        ),
                        default=False,
                    )
                )
            ]

            shared_company_ids = sorted(
                shared_company_by_tax_id.get(
                    tax_id_norm,
                    set(),
                )
            )

            director_count = len(
                director_ids
            )
            shared_company_count = len(
                shared_company_ids
            )
            key_connector_count = len(
                key_connector_ids
            )

            records.append(
                {
                    "tax_id_norm": tax_id_norm,
                    "tax_id_valid": True,
                    "company_name": first_non_empty(
                        *[
                            item.get("company_name")
                            for item in group
                        ],
                        default="",
                    ),
                    "director_count": director_count,
                    "director_ids": director_ids,
                    "director_names": [
                        director_index.get(
                            director_id,
                            {},
                        ).get(
                            "director_name",
                            "",
                        )
                        for director_id
                        in director_ids
                    ],
                    "key_connector_count": (
                        key_connector_count
                    ),
                    "key_connector_ids": (
                        key_connector_ids
                    ),
                    "shared_company_count": (
                        shared_company_count
                    ),
                    "shared_company_ids": (
                        shared_company_ids
                    ),
                    "has_linkage": (
                        director_count > 0
                    ),
                    "linkage_risk_level": (
                        get_linkage_risk_level(
                            director_count=(
                                director_count
                            ),
                            shared_company_count=(
                                shared_company_count
                            ),
                            key_connector_count=(
                                key_connector_count
                            ),
                        )
                    ),
                    "province": representative.get(
                        "province",
                        "",
                    ),
                    "district": representative.get(
                        "district",
                        "",
                    ),
                    "lat": representative.get(
                        "lat"
                    ),
                    "lon": representative.get(
                        "lon"
                    ),
                    "latitude": representative.get(
                        "latitude",
                        representative.get("lat"),
                    ),
                    "longitude": representative.get(
                        "longitude",
                        representative.get("lon"),
                    ),
                    "location_quality": (
                        representative.get(
                            "location_quality",
                            "",
                        )
                    ),
                    "has_policy": bool(
                        to_bool(
                            representative.get(
                                "has_policy"
                            ),
                            default=False,
                        )
                    ),
                    "has_location": bool(
                        to_bool(
                            representative.get(
                                "has_location"
                            ),
                            default=False,
                        )
                    ),
                    "has_flood_context": bool(
                        to_bool(
                            representative.get(
                                "has_flood_context"
                            ),
                            default=False,
                        )
                    ),
                    "business_type_objective": (
                        representative.get(
                            "business_type_objective",
                            "",
                        )
                    ),
                    "business_type_tsic": (
                        representative.get(
                            "business_type_tsic",
                            "",
                        )
                    ),
                    "company_size": (
                        representative.get(
                            "company_size",
                            "",
                        )
                    ),
                    "wtip": representative.get(
                        "wtip",
                        "",
                    ),
                    "flood_risk_level": (
                        representative.get(
                            "flood_risk_level",
                            "Unknown",
                        )
                    ),
                    "flood_join_level": (
                        representative.get(
                            "flood_join_level",
                            "none",
                        )
                    ),
                    "total_premium": (
                        to_number(
                            representative.get(
                                "total_premium"
                            ),
                            0,
                        )
                        or 0
                    ),
                    "total_loss": (
                        to_number(
                            representative.get(
                                "total_loss"
                            ),
                            0,
                        )
                        or 0
                    ),
                    "total_suminsure": (
                        to_number(
                            representative.get(
                                "total_suminsure"
                            ),
                            0,
                        )
                        or 0
                    ),
                    "loss_ratio": representative.get(
                        "loss_ratio"
                    ),
                    "loss_ratio_band": (
                        representative.get(
                            "loss_ratio_band",
                            "Undefined",
                        )
                    ),
                    "most_recent_income_val": (
                        representative.get(
                            "most_recent_income_val"
                        )
                    ),
                    "registered_capital": (
                        representative.get(
                            "registered_capital"
                        )
                    ),
                }
            )

        records = sorted(
            records,
            key=lambda item: (
                -(
                    to_int(
                        item.get(
                            "key_connector_count"
                        ),
                        0,
                    )
                    or 0
                ),
                -(
                    to_int(
                        item.get(
                            "shared_company_count"
                        ),
                        0,
                    )
                    or 0
                ),
                -(
                    to_int(
                        item.get(
                            "director_count"
                        ),
                        0,
                    )
                    or 0
                ),
                clean_text(
                    item.get("company_name")
                ),
            ),
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "linkage_company_summary"
        ],
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source=(
            "linkage_service."
            "build_linkage_company_summary"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }

# ============================================================
# 8) SHARED DIRECTOR LINKS
# ============================================================

def build_shared_director_links(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง shared_director_links

    1 แถว = company A เชื่อม company B
    ผ่านกรรมการร่วม
    """

    def builder() -> Dict[str, Any]:
        pairs = get_director_company_pair_records(
            force_refresh=force_refresh
        )

        director_groups = group_records_by(
            pairs,
            "director_id",
        )

        company_pair_map: Dict[
            Tuple[str, str],
            Dict[str, Any],
        ] = {}

        for director_id, group in director_groups.items():
            director_id = clean_text(
                director_id
            )

            if (
                not director_id
                or director_id == "__EMPTY__"
            ):
                continue

            companies: Dict[
                str,
                Dict[str, Any],
            ] = {}

            for item in group:
                tax_id_norm = get_valid_tax_id(
                    item.get("tax_id_norm")
                )

                if not tax_id_norm:
                    continue

                existing = companies.get(
                    tax_id_norm
                )

                if existing is None:
                    companies[tax_id_norm] = item
                    continue

                existing_score = sum(
                    1
                    for value in existing.values()
                    if not is_empty_value(value)
                )

                item_score = sum(
                    1
                    for value in item.values()
                    if not is_empty_value(value)
                )

                if item_score > existing_score:
                    companies[tax_id_norm] = item

            company_ids = sorted(
                companies
            )

            if len(company_ids) < 2:
                continue

            director_name = first_non_empty(
                *[
                    item.get("director_name")
                    for item in group
                ],
                default="",
            )

            for source_index in range(
                len(company_ids) - 1
            ):
                source_tax_id = company_ids[
                    source_index
                ]

                for target_index in range(
                    source_index + 1,
                    len(company_ids),
                ):
                    target_tax_id = company_ids[
                        target_index
                    ]

                    pair_key = (
                        source_tax_id,
                        target_tax_id,
                    )

                    if pair_key not in company_pair_map:
                        source_company = companies[
                            source_tax_id
                        ]
                        target_company = companies[
                            target_tax_id
                        ]

                        company_pair_map[pair_key] = {
                            "link_id": make_hash_id(
                                (
                                    f"{source_tax_id}|"
                                    f"{target_tax_id}"
                                ),
                                prefix="shared",
                                length=20,
                            ),
                            "source_tax_id": (
                                source_tax_id
                            ),
                            "target_tax_id": (
                                target_tax_id
                            ),
                            "source_company_name": (
                                source_company.get(
                                    "company_name",
                                    "",
                                )
                            ),
                            "target_company_name": (
                                target_company.get(
                                    "company_name",
                                    "",
                                )
                            ),
                            "shared_director_ids": [],
                            "shared_directors": [],
                            "shared_directors_text": "",
                            "weight": 0,
                            "source_province": (
                                source_company.get(
                                    "province",
                                    "",
                                )
                            ),
                            "target_province": (
                                target_company.get(
                                    "province",
                                    "",
                                )
                            ),
                            "source_lat": (
                                source_company.get("lat")
                            ),
                            "source_lon": (
                                source_company.get("lon")
                            ),
                            "target_lat": (
                                target_company.get("lat")
                            ),
                            "target_lon": (
                                target_company.get("lon")
                            ),
                            "source_flood_risk_level": (
                                source_company.get(
                                    "flood_risk_level",
                                    "Unknown",
                                )
                            ),
                            "target_flood_risk_level": (
                                target_company.get(
                                    "flood_risk_level",
                                    "Unknown",
                                )
                            ),
                            "source_total_suminsure": (
                                source_company.get(
                                    "total_suminsure",
                                    0,
                                )
                            ),
                            "target_total_suminsure": (
                                target_company.get(
                                    "total_suminsure",
                                    0,
                                )
                            ),
                        }

                    link = company_pair_map[
                        pair_key
                    ]

                    if (
                        director_id
                        not in link[
                            "shared_director_ids"
                        ]
                    ):
                        link[
                            "shared_director_ids"
                        ].append(director_id)

                    if (
                        director_name
                        and director_name
                        not in link[
                            "shared_directors"
                        ]
                    ):
                        link[
                            "shared_directors"
                        ].append(director_name)

        records = list(
            company_pair_map.values()
        )

        for record in records:
            record["weight"] = len(
                record[
                    "shared_director_ids"
                ]
            )

            record[
                "shared_director_count"
            ] = record["weight"]

            record[
                "shared_directors_text"
            ] = ", ".join(
                record[
                    "shared_directors"
                ]
            )

            record[
                "combined_flood_risk_level"
            ] = _combine_risk_levels_safe(
                [
                    record.get(
                        "source_flood_risk_level"
                    ),
                    record.get(
                        "target_flood_risk_level"
                    ),
                ]
            )

            record["combined_suminsure"] = (
                (
                    to_number(
                        record.get(
                            "source_total_suminsure"
                        ),
                        0,
                    )
                    or 0
                )
                + (
                    to_number(
                        record.get(
                            "target_total_suminsure"
                        ),
                        0,
                    )
                    or 0
                )
            )

        records = sorted(
            records,
            key=lambda item: (
                -(
                    to_number(
                        item.get("weight"),
                        0,
                    )
                    or 0
                ),
                clean_text(
                    item.get(
                        "source_company_name"
                    )
                ),
                clean_text(
                    item.get(
                        "target_company_name"
                    )
                ),
            ),
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "shared_director_links"
        ],
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source=(
            "linkage_service."
            "build_shared_director_links"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }


def get_shared_director_link_records(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    คืน shared director links
    """

    return build_shared_director_links(force_refresh=force_refresh).get("records", [])


# ============================================================
# 9) GRAPH NODES / EDGES
# ============================================================

def make_company_node(
    company_record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    สร้าง company node สำหรับ D3 graph
    """

    tax_id_norm = get_valid_tax_id(
        company_record.get("tax_id_norm")
        or company_record.get("tax_id")
    )

    if not tax_id_norm:
        return {}

    node_id = make_company_node_id(
        tax_id_norm
    )

    total_suminsure = (
        to_number(
            company_record.get(
                "total_suminsure"
            ),
            0,
        )
        or 0
    )

    director_count = (
        to_number(
            company_record.get(
                "director_count"
            ),
            0,
        )
        or 0
    )

    size = (
        GRAPH_NODE_SIZE.get(
            "company",
            18,
        )
        + min(
            20,
            director_count * 2,
        )
    )

    if total_suminsure > 0:
        size += min(
            24,
            total_suminsure / 1_000_000,
        )

    risk_level = clean_text(
        company_record.get(
            "flood_risk_level"
        ),
        default="Unknown",
    )

    color = GRAPH_COLORS.get(
        "company",
        "#2563eb",
    )

    if risk_level == "Critical":
        color = "#dc2626"
    elif risk_level == "Warning":
        color = "#f97316"
    elif risk_level == "Watch":
        color = "#facc15"
    elif risk_level == "Normal":
        color = "#22c55e"

    has_policy = bool(
        to_bool(
            company_record.get(
                "has_policy"
            ),
            default=False,
        )
    )

    has_flood_context = bool(
        to_bool(
            company_record.get(
                "has_flood_context"
            ),
            default=False,
        )
    )

    has_linkage = bool(
        to_bool(
            company_record.get(
                "has_linkage"
            ),
            default=True,
        )
    )

    return {
        "id": node_id,
        "type": "company",
        "label": clean_text(
            company_record.get(
                "company_name"
            ),
            default=tax_id_norm,
        ),
        "tax_id_norm": tax_id_norm,
        "director_id": None,
        "size": round(size, 2),
        "color": color,
        "border_color": "#ffffff",
        "badges": [
            badge
            for badge, enabled in {
                "policy": has_policy,
                "flood": has_flood_context,
                "linkage": has_linkage,
            }.items()
            if enabled
        ],
        "metadata": {
            "company_name": (
                company_record.get(
                    "company_name",
                    "",
                )
            ),
            "province": company_record.get(
                "province",
                "",
            ),
            "district": company_record.get(
                "district",
                "",
            ),
            "business_type_tsic": (
                company_record.get(
                    "business_type_tsic",
                    "",
                )
            ),
            "company_size": (
                company_record.get(
                    "company_size",
                    "",
                )
            ),
            "wtip": company_record.get(
                "wtip",
                "",
            ),
            "director_count": director_count,
            "shared_company_count": (
                company_record.get(
                    "shared_company_count",
                    0,
                )
            ),
            "key_connector_count": (
                company_record.get(
                    "key_connector_count",
                    0,
                )
            ),
            "linkage_risk_level": (
                company_record.get(
                    "linkage_risk_level",
                    "Normal",
                )
            ),
            "has_policy": has_policy,
            "has_flood_context": (
                has_flood_context
            ),
            "total_premium": (
                company_record.get(
                    "total_premium",
                    0,
                )
            ),
            "total_loss": company_record.get(
                "total_loss",
                0,
            ),
            "total_suminsure": (
                total_suminsure
            ),
            "loss_ratio": company_record.get(
                "loss_ratio"
            ),
            "loss_ratio_band": (
                company_record.get(
                    "loss_ratio_band",
                    "Undefined",
                )
            ),
            "flood_risk_level": risk_level,
            "lat": company_record.get("lat"),
            "lon": company_record.get("lon"),
        },
    }


def make_director_node(
    director_record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    สร้าง director node สำหรับ D3 graph
    """

    director_id = clean_text(
        director_record.get("director_id")
    )

    if not director_id:
        return {}

    node_id = make_director_node_id(
        director_id
    )

    company_count = (
        to_number(
            director_record.get(
                "company_count"
            ),
            0,
        )
        or 0
    )

    is_key_connector = bool(
        to_bool(
            director_record.get(
                "is_key_connector"
            ),
            default=False,
        )
    )

    size = (
        GRAPH_NODE_SIZE.get(
            "director",
            12,
        )
        + min(
            30,
            company_count * 4,
        )
    )

    color = GRAPH_COLORS.get(
        (
            "key_connector"
            if is_key_connector
            else "director"
        ),
        "#9333ea",
    )

    return {
        "id": node_id,
        "type": "director",
        "label": clean_text(
            director_record.get(
                "director_name"
            ),
            default=director_id,
        ),
        "tax_id_norm": None,
        "director_id": director_id,
        "size": round(size, 2),
        "color": color,
        "border_color": "#ffffff",
        "badges": (
            ["key_connector"]
            if is_key_connector
            else []
        ),
        "metadata": {
            "director_name": (
                director_record.get(
                    "director_name",
                    "",
                )
            ),
            "company_count": company_count,
            "is_key_connector": (
                is_key_connector
            ),
            "company_list": (
                director_record.get(
                    "company_list",
                    [],
                )
            ),
            "province_list": (
                director_record.get(
                    "province_list",
                    [],
                )
            ),
            "total_connected_premium": (
                director_record.get(
                    "total_connected_premium",
                    0,
                )
            ),
            "total_connected_loss": (
                director_record.get(
                    "total_connected_loss",
                    0,
                )
            ),
            "total_connected_suminsure": (
                director_record.get(
                    "total_connected_suminsure",
                    0,
                )
            ),
            "highest_flood_risk_level": (
                director_record.get(
                    "highest_flood_risk_level",
                    "Unknown",
                )
            ),
        },
    }

def build_linkage_nodes(
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    สร้าง linkage_nodes สำหรับ graph
    """

    def builder() -> Dict[str, Any]:
        company_summary = (
            build_linkage_company_summary(
                force_refresh=force_refresh
            ).get("records", [])
        )

        director_master = (
            build_director_master(
                force_refresh=force_refresh
            ).get("records", [])
        )

        nodes: Dict[
            str,
            Dict[str, Any],
        ] = {}

        for company in company_summary:
            node = make_company_node(
                company
            )

            if node.get("id"):
                nodes[node["id"]] = node

        for director in director_master:
            node = make_director_node(
                director
            )

            if node.get("id"):
                nodes[node["id"]] = node

        records = list(
            nodes.values()
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS[
            "linkage_nodes"
        ],
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source=(
            "linkage_service."
            "build_linkage_nodes"
        ),
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result[
            "cache_used"
        ],
    }

def build_director_of_edges(
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    สร้าง DIRECTOR_OF edges
    """

    pairs = get_director_company_pair_records(
        force_refresh=force_refresh
    )

    edges: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for pair in pairs:
        tax_id_norm = get_valid_tax_id(
            pair.get("tax_id_norm")
        )

        director_id = clean_text(
            pair.get("director_id")
        )

        if (
            not tax_id_norm
            or not director_id
        ):
            continue

        source = make_company_node_id(
            tax_id_norm
        )
        target = make_director_node_id(
            director_id
        )

        if not source or not target:
            continue

        edge_id = make_edge_id(
            source,
            target,
            EDGE_TYPE_DIRECTOR_OF,
        )

        edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "type": EDGE_TYPE_DIRECTOR_OF,
            "weight": 1,
            "shared_directors": [],
            "metadata": {
                "tax_id_norm": tax_id_norm,
                "company_name": pair.get(
                    "company_name",
                    "",
                ),
                "director_id": director_id,
                "director_name": pair.get(
                    "director_name",
                    "",
                ),
                "province": pair.get(
                    "province",
                    "",
                ),
                "flood_risk_level": (
                    pair.get(
                        "flood_risk_level",
                        "Unknown",
                    )
                ),
                "total_suminsure": pair.get(
                    "total_suminsure",
                    0,
                ),
            },
        }

    return list(
        edges.values()
    )


def build_shared_director_edges(
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    สร้าง SHARED_DIRECTOR edges
    ระหว่าง company-company
    """

    shared_links = (
        get_shared_director_link_records(
            force_refresh=force_refresh
        )
    )

    edges: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for link in shared_links:
        source_tax_id = get_valid_tax_id(
            link.get("source_tax_id")
        )
        target_tax_id = get_valid_tax_id(
            link.get("target_tax_id")
        )

        if (
            not source_tax_id
            or not target_tax_id
            or source_tax_id
            == target_tax_id
        ):
            continue

        source = make_company_node_id(
            source_tax_id
        )
        target = make_company_node_id(
            target_tax_id
        )

        if not source or not target:
            continue

        edge_id = make_edge_id(
            source,
            target,
            EDGE_TYPE_SHARED_DIRECTOR,
        )

        edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "type": EDGE_TYPE_SHARED_DIRECTOR,
            "weight": (
                to_number(
                    link.get("weight"),
                    1,
                )
                or 1
            ),
            "shared_directors": list(
                link.get(
                    "shared_directors",
                    [],
                )
                or []
            ),
            "metadata": {
                "link_id": link.get(
                    "link_id"
                ),
                "source_tax_id": (
                    source_tax_id
                ),
                "target_tax_id": (
                    target_tax_id
                ),
                "source_company_name": (
                    link.get(
                        "source_company_name"
                    )
                ),
                "target_company_name": (
                    link.get(
                        "target_company_name"
                    )
                ),
                "shared_director_ids": list(
                    link.get(
                        "shared_director_ids",
                        [],
                    )
                    or []
                ),
                "shared_directors": list(
                    link.get(
                        "shared_directors",
                        [],
                    )
                    or []
                ),
                "combined_flood_risk_level": (
                    link.get(
                        "combined_flood_risk_level",
                        "Unknown",
                    )
                ),
                "combined_suminsure": (
                    link.get(
                        "combined_suminsure",
                        0,
                    )
                ),
            },
        }

    return list(
        edges.values()
    )

def build_linkage_edges(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง linkage_edges ทั้งหมด
    """

    def builder() -> Dict[str, Any]:
        director_edges = build_director_of_edges(force_refresh=force_refresh)
        shared_edges = build_shared_director_edges(force_refresh=force_refresh)

        records = director_edges + shared_edges

        return {
            "records": records,
            "total": len(records),
            "director_of_count": len(director_edges),
            "shared_director_count": len(shared_edges),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["linkage_edges"],
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source="linkage_service.build_linkage_edges",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


# ============================================================
# 10) GRAPH FILTERING
# ============================================================

def build_graph_adjacency(edges: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """
    สร้าง adjacency map จาก edges
    """

    adjacency: Dict[str, Set[str]] = defaultdict(set)

    for edge in edges:
        source = clean_text(edge.get("source"))
        target = clean_text(edge.get("target"))

        if not source or not target:
            continue

        adjacency[source].add(target)
        adjacency[target].add(source)

    return adjacency


def collect_nodes_by_depth(
    seed_node_ids: List[str],
    edges: List[Dict[str, Any]],
    depth: int = 1,
) -> Set[str]:
    """
    เก็บ node ids จาก seed ตาม depth
    """

    adjacency = build_graph_adjacency(edges)

    visited: Set[str] = set()
    frontier: Set[str] = set(seed_node_ids)

    for _level in range(depth + 1):
        next_frontier: Set[str] = set()

        for node_id in frontier:
            if node_id in visited:
                continue

            visited.add(node_id)
            next_frontier.update(adjacency.get(node_id, set()))

        frontier = next_frontier - visited

    return visited

def filter_graph_payload(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    filter graph ตาม context:
    - tax_id
    - director_id
    - depth
    - max_nodes
    - include_shared_edges
    - include_policy
    - include_flood
    """

    ctx = normalize_context(context)

    working_nodes: List[
        Dict[str, Any]
    ] = []

    for node in nodes or []:
        if not isinstance(node, dict):
            continue

        node_copy = dict(node)
        node_copy["badges"] = list(
            node.get("badges", [])
            or []
        )
        node_copy["metadata"] = dict(
            node.get("metadata", {})
            or {}
        )

        if not ctx.get("include_policy"):
            node_copy["badges"] = [
                badge
                for badge in node_copy[
                    "badges"
                ]
                if badge != "policy"
            ]

            for key in [
                "has_policy",
                "total_premium",
                "total_loss",
                "total_suminsure",
                "loss_ratio",
                "loss_ratio_band",
                "total_connected_premium",
                "total_connected_loss",
                "total_connected_suminsure",
            ]:
                node_copy["metadata"].pop(
                    key,
                    None,
                )

        if not ctx.get("include_flood"):
            node_copy["badges"] = [
                badge
                for badge in node_copy[
                    "badges"
                ]
                if badge != "flood"
            ]

            for key in [
                "has_flood_context",
                "flood_risk_level",
                "highest_flood_risk_level",
            ]:
                node_copy["metadata"].pop(
                    key,
                    None,
                )

        working_nodes.append(
            node_copy
        )

    working_edges: List[
        Dict[str, Any]
    ] = []

    for edge in edges or []:
        if not isinstance(edge, dict):
            continue

        edge_copy = dict(edge)
        edge_copy["metadata"] = dict(
            edge.get("metadata", {})
            or {}
        )
        edge_copy["shared_directors"] = list(
            edge.get("shared_directors", [])
            or []
        )

        if not ctx.get("include_policy"):
            for key in [
                "total_suminsure",
                "combined_suminsure",
            ]:
                edge_copy["metadata"].pop(
                    key,
                    None,
                )

        if not ctx.get("include_flood"):
            for key in [
                "flood_risk_level",
                "combined_flood_risk_level",
            ]:
                edge_copy["metadata"].pop(
                    key,
                    None,
                )

        working_edges.append(
            edge_copy
        )

    node_index = {
        clean_text(node.get("id")): node
        for node in working_nodes
        if clean_text(node.get("id"))
    }

    filtered_edges = list(
        working_edges
    )

    if not ctx.get(
        "include_shared_edges",
        True,
    ):
        filtered_edges = [
            edge
            for edge in filtered_edges
            if edge.get("type")
            != EDGE_TYPE_SHARED_DIRECTOR
        ]

    seed_node_ids: List[str] = []

    if ctx.get("tax_id"):
        seed = make_company_node_id(
            ctx["tax_id"]
        )

        if seed:
            seed_node_ids.append(seed)

    if ctx.get("director_id"):
        seed = make_director_node_id(
            ctx["director_id"]
        )

        if seed:
            seed_node_ids.append(seed)

    seed_node_ids = list(
        dict.fromkeys(seed_node_ids)
    )

    if seed_node_ids:
        allowed_nodes = collect_nodes_by_depth(
            seed_node_ids=seed_node_ids,
            edges=filtered_edges,
            depth=ctx.get(
                "depth",
                GRAPH_DEFAULT_DEPTH,
            ),
        )
    else:
        allowed_nodes = set(
            node_index
        )

    graph_nodes = [
        node
        for node_id, node
        in node_index.items()
        if node_id in allowed_nodes
    ]

    allowed_node_ids = {
        node.get("id")
        for node in graph_nodes
    }

    graph_edges = [
        edge
        for edge in filtered_edges
        if edge.get("source")
        in allowed_node_ids
        and edge.get("target")
        in allowed_node_ids
    ]

    limited = False

    max_nodes = ctx.get(
        "max_nodes",
        GRAPH_DEFAULT_MAX_NODES,
    )

    if len(graph_nodes) > max_nodes:
        limited = True

        degree_by_node: Dict[
            str,
            int,
        ] = defaultdict(int)

        for edge in graph_edges:
            source = clean_text(
                edge.get("source")
            )
            target = clean_text(
                edge.get("target")
            )

            if source:
                degree_by_node[source] += 1

            if target:
                degree_by_node[target] += 1

        seed_nodes = [
            node_index[seed_node_id]
            for seed_node_id in seed_node_ids
            if seed_node_id in node_index
            and seed_node_id
            in allowed_node_ids
        ]

        seed_id_set = {
            node.get("id")
            for node in seed_nodes
        }

        remaining_nodes = [
            node
            for node in graph_nodes
            if node.get("id")
            not in seed_id_set
        ]

        remaining_nodes = sorted(
            remaining_nodes,
            key=lambda node: (
                degree_by_node.get(
                    clean_text(
                        node.get("id")
                    ),
                    0,
                ),
                (
                    to_number(
                        node.get("size"),
                        0,
                    )
                    or 0
                ),
                clean_text(
                    node.get("label")
                ),
            ),
            reverse=True,
        )

        remaining_limit = max(
            0,
            max_nodes - len(seed_nodes),
        )

        graph_nodes = (
            seed_nodes
            + remaining_nodes[
                :remaining_limit
            ]
        )

        allowed_node_ids = {
            node.get("id")
            for node in graph_nodes
        }

        graph_edges = [
            edge
            for edge in graph_edges
            if edge.get("source")
            in allowed_node_ids
            and edge.get("target")
            in allowed_node_ids
        ]

    warnings: List[str] = []

    if limited:
        warnings.append(
            "graph_limited_by_max_nodes"
        )

    missing_seed_node_ids = [
        seed_node_id
        for seed_node_id in seed_node_ids
        if seed_node_id not in node_index
    ]

    if missing_seed_node_ids:
        warnings.append(
            "graph_seed_not_found"
        )

    return {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "limited": limited,
        "summary": build_graph_summary(
            graph_nodes,
            graph_edges,
        ),
        "layout": {
            "mode": ctx.get(
                "mode",
                GRAPH_DEFAULT_MODE,
            ),
            "depth": ctx.get(
                "depth",
                GRAPH_DEFAULT_DEPTH,
            ),
            "max_nodes": max_nodes,
        },
        "warnings": warnings,
        "missing_seed_node_ids": (
            missing_seed_node_ids
        ),
    }

def build_graph_summary(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    สรุป graph payload
    """

    company_nodes = [node for node in nodes if node.get("type") == "company"]
    director_nodes = [node for node in nodes if node.get("type") == "director"]

    director_of_edges = [
        edge for edge in edges if edge.get("type") == EDGE_TYPE_DIRECTOR_OF
    ]

    shared_edges = [
        edge for edge in edges if edge.get("type") == EDGE_TYPE_SHARED_DIRECTOR
    ]

    key_connector_nodes = [
        node for node in director_nodes
        if "key_connector" in node.get("badges", [])
    ]

    risk_counts = Counter(
        node.get("metadata", {}).get("flood_risk_level", "Unknown")
        for node in company_nodes
    )

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "company_node_count": len(company_nodes),
        "director_node_count": len(director_nodes),
        "director_of_edge_count": len(director_of_edges),
        "shared_director_edge_count": len(shared_edges),
        "key_connector_count": len(key_connector_nodes),
        "risk_counts": dict(risk_counts),
    }


def build_linkage_graph_payload(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง graph payload เต็ม

    cache key หลัก = linkage_graph_payload
    alias = linkage_graph, graph_payload
    """

    def builder() -> Dict[str, Any]:
        company_source_payload = load_company_source_payload()
        company_source = company_source_payload.get("company_source", "linkage_input_fallback")

        nodes = build_linkage_nodes(force_refresh=force_refresh).get("records", [])
        edges = build_linkage_edges(force_refresh=force_refresh).get("records", [])
        summary = build_graph_summary(nodes, edges)

        payload = {
            "nodes": nodes,
            "edges": edges,
            "summary": summary,
            "layout": {
                "mode": GRAPH_DEFAULT_MODE,
                "depth": GRAPH_DEFAULT_DEPTH,
                "max_nodes": GRAPH_DEFAULT_MAX_NODES,
            },
            "warnings": [],
            "meta": build_linkage_cache_meta(
                cache_key=LINKAGE_GRAPH_MAIN_CACHE_KEY,
                source_input=str(LINKAGE_INPUT_PATH),
                company_source=company_source,
                record_count=len(nodes) + len(edges),
                node_count=len(nodes),
                edge_count=len(edges),
                degraded=company_source != "company_unified_base",
                extra={
                    "alias_cache_keys": list(LINKAGE_GRAPH_ALIAS_CACHE_KEYS.keys()),
                    "graph_contract": {
                        "company_node_id": "company:<tax_id_norm>",
                        "director_node_id": "director:<director_id>",
                        "edge_types": [
                            EDGE_TYPE_DIRECTOR_OF,
                            EDGE_TYPE_SHARED_DIRECTOR,
                        ],
                    },
                },
            ),
            "created_at": now_iso(),
        }

        return payload

    cache_result = get_or_build_cache(
        cache_key=LINKAGE_GRAPH_MAIN_CACHE_KEY,
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source="linkage_service.build_linkage_graph_payload",
    )

    data = dict(cache_result["data"])
    data["cache_used"] = cache_result["cache_used"]

    if isinstance(data.get("meta"), dict):
        data["meta"]["cache_used"] = cache_result["cache_used"]
        data["meta"]["cache_key"] = LINKAGE_GRAPH_MAIN_CACHE_KEY

    data["alias_cache_results"] = write_linkage_graph_aliases(data, cache_used=cache_result["cache_used"])

    return data

# ============================================================
# 11) EXPOSURE BY DIRECTOR
# ============================================================

def build_exposure_by_director(force_refresh: bool = False) -> Dict[str, Any]:
    """
    สร้าง exposure by director

    ใช้ดูว่ากรรมการแต่ละคนเชื่อม exposure เท่าไร
    """

    def builder() -> Dict[str, Any]:
        directors = get_director_master_records(force_refresh=force_refresh)

        records = []

        for director in directors:
            record = {
                "director_id": director.get("director_id"),
                "director_name": director.get("director_name"),
                "company_count": director.get("company_count"),
                "is_key_connector": director.get("is_key_connector"),
                "province_count": director.get("province_count"),
                "province_list": director.get("province_list", []),

                "total_connected_income": director.get("total_connected_income", 0),
                "total_connected_capital": director.get("total_connected_capital", 0),
                "total_connected_premium": director.get("total_connected_premium", 0),
                "total_connected_loss": director.get("total_connected_loss", 0),
                "total_connected_suminsure": director.get("total_connected_suminsure", 0),

                "highest_flood_risk_level": director.get("highest_flood_risk_level", "Unknown"),
                "connected_flood_risk_levels": director.get("connected_flood_risk_levels", []),
                "connected_loss_ratio_bands": director.get("connected_loss_ratio_bands", []),
                "company_list": director.get("company_list", []),
                "company_list_text": director.get("company_list_text", ""),
            }

            records.append(record)

        records = sorted(
            records,
            key=lambda item: (
                bool(item.get("is_key_connector")),
                to_number(item.get("total_connected_suminsure"), 0) or 0,
                to_number(item.get("company_count"), 0) or 0,
            ),
            reverse=True,
        )

        return {
            "records": records,
            "total": len(records),
            "created_at": now_iso(),
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["exposure_by_director"],
        builder=builder,
        ttl_seconds=get_linkage_ttl(),
        force_refresh=force_refresh,
        source="linkage_service.build_exposure_by_director",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


# ============================================================
# 12) API FUNCTIONS
# ============================================================

def get_linkage_summary(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/linkage/summary
    """

    ctx = normalize_context(context)

    input_records = get_linkage_input_records(force_refresh=ctx.get("force_refresh", False))
    pairs = get_director_company_pair_records(force_refresh=ctx.get("force_refresh", False))
    directors = get_director_master_records(force_refresh=ctx.get("force_refresh", False))
    shared_links = get_shared_director_link_records(force_refresh=ctx.get("force_refresh", False))
    graph = build_linkage_graph_payload(force_refresh=ctx.get("force_refresh", False))

    key_connectors = [
        director for director in directors
        if to_bool(director.get("is_key_connector"), default=False)
    ]

    return {
        "total_input_companies": len(input_records),
        "total_director_company_pairs": len(pairs),
        "total_directors": len(directors),
        "total_key_connectors": len(key_connectors),
        "total_shared_director_links": len(shared_links),
        "total_graph_nodes": len(graph.get("nodes", [])),
        "total_graph_edges": len(graph.get("edges", [])),
        "company_with_boardlist_count": sum(1 for r in input_records if r.get("director_count_raw", 0) > 0),
        "company_without_boardlist_count": sum(1 for r in input_records if r.get("director_count_raw", 0) == 0),
        "top_key_connectors": key_connectors[:10],
        "created_at": now_iso(),
    }


def get_linkage_graph(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/linkage/graph
    """

    ctx = normalize_context(context)

    graph = build_linkage_graph_payload(force_refresh=ctx.get("force_refresh", False))

    filtered = filter_graph_payload(
        nodes=graph.get("nodes", []),
        edges=graph.get("edges", []),
        context=ctx,
    )

    filtered["meta"] = {
        **(graph.get("meta") if isinstance(graph.get("meta"), dict) else {}),
        "cache_used": graph.get("cache_used", False),
        "filtered_node_count": len(filtered.get("nodes", [])),
        "filtered_edge_count": len(filtered.get("edges", [])),
        "filters": ctx.get("filters", {}),
        "mode": ctx.get("mode"),
        "tax_id": ctx.get("tax_id"),
        "director_id": ctx.get("director_id"),
    }

    return to_jsonable(filtered)

def get_linkage_company_detail(
    tax_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/linkage/company/<tax_id>
    """

    tax_id_norm = get_valid_tax_id(
        tax_id
    )

    ctx = normalize_context(context)

    if not tax_id_norm:
        return {
            "tax_id": tax_id,
            "tax_id_norm": "",
            "found": False,
            "company_name": "",
            "directors": [],
            "director_count": 0,
            "shared_links": [],
            "connected_companies": [],
            "shared_company_count": 0,
            "edges": [],
            "graph": {
                "nodes": [],
                "edges": [],
                "limited": False,
                "summary": {},
            },
        }

    force_refresh = ctx.get(
        "force_refresh",
        False,
    )

    pairs = [
        pair
        for pair in get_director_company_pair_records(
            force_refresh=force_refresh
        )
        if get_valid_tax_id(
            pair.get("tax_id_norm")
        )
        == tax_id_norm
    ]

    director_ids = sorted(
        {
            clean_text(
                pair.get("director_id")
            )
            for pair in pairs
            if clean_text(
                pair.get("director_id")
            )
        }
    )

    directors_index = {
        clean_text(
            director.get("director_id")
        ): director
        for director in get_director_master_records(
            force_refresh=force_refresh
        )
        if clean_text(
            director.get("director_id")
        )
    }

    directors = [
        directors_index[director_id]
        for director_id in director_ids
        if director_id in directors_index
    ]

    shared_links = [
        link
        for link in get_shared_director_link_records(
            force_refresh=force_refresh
        )
        if (
            get_valid_tax_id(
                link.get("source_tax_id")
            )
            == tax_id_norm
            or get_valid_tax_id(
                link.get("target_tax_id")
            )
            == tax_id_norm
        )
    ]

    connected_companies_by_tax_id: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for link in shared_links:
        source_tax_id = get_valid_tax_id(
            link.get("source_tax_id")
        )
        target_tax_id = get_valid_tax_id(
            link.get("target_tax_id")
        )

        if source_tax_id == tax_id_norm:
            connected_tax_id = target_tax_id
            connected_name = link.get(
                "target_company_name",
                "",
            )
            connected_province = link.get(
                "target_province",
                "",
            )
        else:
            connected_tax_id = source_tax_id
            connected_name = link.get(
                "source_company_name",
                "",
            )
            connected_province = link.get(
                "source_province",
                "",
            )

        if not connected_tax_id:
            continue

        connected_companies_by_tax_id[
            connected_tax_id
        ] = {
            "tax_id_norm": connected_tax_id,
            "company_name": connected_name,
            "province": connected_province,
            "shared_director_count": (
                to_int(
                    link.get("weight"),
                    0,
                )
                or 0
            ),
            "shared_director_ids": list(
                link.get(
                    "shared_director_ids",
                    [],
                )
                or []
            ),
            "shared_directors": list(
                link.get(
                    "shared_directors",
                    [],
                )
                or []
            ),
        }

    connected_companies = sorted(
        connected_companies_by_tax_id.values(),
        key=lambda item: (
            -(
                to_int(
                    item.get(
                        "shared_director_count"
                    ),
                    0,
                )
                or 0
            ),
            clean_text(
                item.get("company_name")
            ),
        ),
    )

    graph = get_linkage_graph(
        {
            **ctx,
            "tax_id": tax_id_norm,
            "depth": ctx.get("depth", 2),
        }
    )

    company_name = first_non_empty(
        *[
            pair.get("company_name")
            for pair in pairs
        ],
        default="",
    )

    return {
        "tax_id": tax_id,
        "tax_id_norm": tax_id_norm,
        "found": bool(pairs),
        "company_name": company_name,
        "directors": directors,
        "director_count": len(directors),
        "shared_links": shared_links,
        "connected_companies": (
            connected_companies
        ),
        "shared_company_count": len(
            connected_companies
        ),
        "edges": shared_links,
        "graph": graph,
    }

def get_linkage_director_detail(
    director_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    API:
    GET /api/linkage/director/<director_id>
    """

    director_id = clean_text(
        director_id
    )

    ctx = normalize_context(context)

    if not director_id:
        return {
            "director_id": "",
            "found": False,
            "director": {},
            "companies": [],
            "company_count": 0,
            "shared_links": [],
            "edges": [],
            "graph": {
                "nodes": [],
                "edges": [],
                "limited": False,
                "summary": {},
            },
        }

    force_refresh = ctx.get(
        "force_refresh",
        False,
    )

    directors = get_director_master_records(
        force_refresh=force_refresh
    )

    director = next(
        (
            item
            for item in directors
            if clean_text(
                item.get("director_id")
            )
            == director_id
        ),
        None,
    )

    pairs = [
        pair
        for pair in get_director_company_pair_records(
            force_refresh=force_refresh
        )
        if clean_text(
            pair.get("director_id")
        )
        == director_id
    ]

    shared_links = [
        link
        for link in get_shared_director_link_records(
            force_refresh=force_refresh
        )
        if director_id
        in {
            clean_text(
                shared_director_id
            )
            for shared_director_id
            in (
                link.get(
                    "shared_director_ids",
                    [],
                )
                or []
            )
            if clean_text(
                shared_director_id
            )
        }
    ]

    graph = get_linkage_graph(
        {
            **ctx,
            "director_id": director_id,
            "depth": ctx.get("depth", 2),
        }
    )

    return {
        "director_id": director_id,
        "found": bool(
            director
            or pairs
        ),
        "director": director or {},
        "companies": pairs,
        "company_count": len(pairs),
        "shared_links": shared_links,
        "edges": shared_links,
        "graph": graph,
    }

def get_key_connectors(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/linkage/key-connectors
    """

    ctx = normalize_context(context)

    records = [
        director
        for director in get_director_master_records(force_refresh=ctx.get("force_refresh", False))
        if to_bool(director.get("is_key_connector"), default=False)
    ]

    if not ctx.get("sort_by"):
        ctx["sort_by"] = "company_count"
        ctx["sort_dir"] = "desc"

    return filter_records_api(
        records=records,
        context=ctx,
        searchable_fields=DIRECTOR_SEARCHABLE_FIELDS,
        target="director",
    )


def get_shared_director_links(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/linkage/shared-directors
    """

    ctx = normalize_context(context)

    records = get_shared_director_link_records(force_refresh=ctx.get("force_refresh", False))

    if not ctx.get("sort_by"):
        ctx["sort_by"] = "weight"
        ctx["sort_dir"] = "desc"

    return filter_records_api(
        records=records,
        context=ctx,
        searchable_fields=SHARED_LINK_SEARCHABLE_FIELDS,
        target="linkage",
    )


def get_exposure_by_director(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/linkage/exposure-by-director
    """

    ctx = normalize_context(context)

    records = build_exposure_by_director(force_refresh=ctx.get("force_refresh", False)).get("records", [])

    if not ctx.get("sort_by"):
        ctx["sort_by"] = "total_connected_suminsure"
        ctx["sort_dir"] = "desc"

    return filter_records_api(
        records=records,
        context=ctx,
        searchable_fields=DIRECTOR_SEARCHABLE_FIELDS,
        target="director",
    )


# ============================================================
# 13) DASHBOARD SUPPORT FUNCTIONS
# ============================================================

def get_linkage_dashboard_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง payload สำหรับ dashboard summary
    """

    ctx = normalize_context(context)

    summary = get_linkage_summary(ctx)

    key_connectors = get_key_connectors(
        {
            **ctx,
            "page": 1,
            "page_size": 10,
        }
    ).get("records", [])

    shared_links = get_shared_director_links(
        {
            **ctx,
            "page": 1,
            "page_size": 10,
        }
    ).get("records", [])

    exposure = get_exposure_by_director(
        {
            **ctx,
            "page": 1,
            "page_size": 10,
        }
    ).get("records", [])

    graph = get_linkage_graph(
        {
            **ctx,
            "max_nodes": 300,
        }
    )

    return {
        "summary": summary,
        "key_connectors": key_connectors,
        "shared_director_links": shared_links,
        "exposure_by_director": exposure,
        "graph": graph,
        "generated_at": now_iso(),
    }

def rebuild_linkage_cache(
    force_refresh: bool = True,
) -> Dict[str, Any]:
    """
    rebuild cache ทั้งหมดของ linkage

    PHASE linkage:
    - อ่าน company_unified_base ถ้ามี
    - fallback เป็น linkage input
    - เขียน graph หลักที่ linkage_graph_payload
    - ใช้ alias result ที่ graph builder เขียนแล้ว
    """

    company_source_payload = (
        load_company_source_payload()
    )

    company_source = (
        company_source_payload.get(
            "company_source",
            "linkage_input_fallback",
        )
    )

    results = {
        "linkage_input_clean": (
            load_linkage_input_clean(
                force_refresh=force_refresh
            )
        ),
        "director_company_pairs": (
            build_director_company_pairs(
                force_refresh=force_refresh
            )
        ),
        "director_master": (
            build_director_master(
                force_refresh=force_refresh
            )
        ),
        "shared_director_links": (
            build_shared_director_links(
                force_refresh=force_refresh
            )
        ),
        "linkage_company_summary": (
            build_linkage_company_summary(
                force_refresh=force_refresh
            )
        ),
        "linkage_nodes": (
            build_linkage_nodes(
                force_refresh=force_refresh
            )
        ),
        "linkage_edges": (
            build_linkage_edges(
                force_refresh=force_refresh
            )
        ),
        "linkage_graph_payload": (
            build_linkage_graph_payload(
                force_refresh=force_refresh
            )
        ),
        "exposure_by_director": (
            build_exposure_by_director(
                force_refresh=force_refresh
            )
        ),
    }

    graph_payload = results[
        "linkage_graph_payload"
    ]

    alias_results = (
        graph_payload.get(
            "alias_cache_results",
            {},
        )
        if isinstance(
            graph_payload,
            dict,
        )
        else {}
    )

    result_summary: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for key, value in results.items():
        if not isinstance(value, dict):
            value = {}

        summary = (
            value.get("summary", {})
            if isinstance(
                value.get("summary"),
                dict,
            )
            else {}
        )

        meta = (
            value.get("meta", {})
            if isinstance(
                value.get("meta"),
                dict,
            )
            else {}
        )

        result_summary[key] = {
            "cache_key": CACHE_KEYS.get(
                key,
                key,
            ),
            "total": value.get("total"),
            "record_count": (
                value.get("total")
                if value.get("total")
                is not None
                else meta.get(
                    "record_count",
                    0,
                )
            ),
            "node_count": summary.get(
                "node_count",
                meta.get("node_count", 0),
            ),
            "edge_count": summary.get(
                "edge_count",
                meta.get("edge_count", 0),
            ),
            "cache_used": value.get(
                "cache_used"
            ),
            "created_at": value.get(
                "created_at"
            ),
            "meta": meta,
        }

    return {
        "rebuilt": True,
        "phase": "linkage",
        "company_source": company_source,
        "degraded": (
            company_source
            != "company_unified_base"
        ),
        "results": result_summary,
        "aliases": {
            "linkage_graph": (
                LINKAGE_GRAPH_MAIN_CACHE_KEY
            ),
            "graph_payload": (
                LINKAGE_GRAPH_MAIN_CACHE_KEY
            ),
        },
        "alias_cache_results": alias_results,
        "meta": build_linkage_cache_meta(
            cache_key=(
                LINKAGE_GRAPH_MAIN_CACHE_KEY
            ),
            source_input=str(
                LINKAGE_INPUT_PATH
            ),
            company_source=company_source,
            record_count=sum(
                (
                    to_int(
                        value.get("total"),
                        0,
                    )
                    or 0
                )
                for value in results.values()
                if isinstance(value, dict)
            ),
            node_count=(
                graph_payload.get(
                    "summary",
                    {},
                ).get("node_count", 0)
                if isinstance(
                    graph_payload,
                    dict,
                )
                else 0
            ),
            edge_count=(
                graph_payload.get(
                    "summary",
                    {},
                ).get("edge_count", 0)
                if isinstance(
                    graph_payload,
                    dict,
                )
                else 0
            ),
            degraded=(
                company_source
                != "company_unified_base"
            ),
        ),
        "generated_at": now_iso(),
    }

# ============================================================
# 14) MODULE STATUS / SELF TEST
# ============================================================

def get_linkage_module_status() -> Dict[str, Any]:
    """
    คืนสถานะ module linkage_service.py
    """

    company_source_payload = load_company_source_payload()

    return {
        "module": "linkage_service",
        "ready": True,
        "linkage_input_path": str(LINKAGE_INPUT_PATH),
        "linkage_input_exists": LINKAGE_INPUT_PATH.exists(),
        "cache_keys": CACHE_KEYS,
        "main_graph_cache_key": LINKAGE_GRAPH_MAIN_CACHE_KEY,
        "graph_cache_aliases": LINKAGE_GRAPH_ALIAS_CACHE_KEYS,
        "company_source_contract": {
            "phase": "linkage",
            "preferred_company_source": "company_unified_base",
            "fallback_company_source": "linkage_input_fallback",
            "current_company_source": company_source_payload.get("company_source"),
            "current_company_source_record_count": company_source_payload.get("record_count", 0),
            "reads_company_unified_master_in_linkage_phase": False,
            "reads_flood_prediction": False,
        },
        "graph_contract": {
            "company_node_id": "company:<tax_id_norm>",
            "director_node_id": "director:<director_id>",
            "director_of_edge_type": EDGE_TYPE_DIRECTOR_OF,
            "shared_director_edge_type": EDGE_TYPE_SHARED_DIRECTOR,
            "key_connector": "director.company_count > 1",
        },
        "supported_outputs": [
            "linkage_input_clean",
            "director_company_pairs",
            "director_master",
            "shared_director_links",
            "linkage_company_summary",
            "linkage_nodes",
            "linkage_edges",
            "linkage_graph_payload",
            "linkage_graph",
            "graph_payload",
            "exposure_by_director",
        ],
        "edge_types": [
            EDGE_TYPE_DIRECTOR_OF,
            EDGE_TYPE_SHARED_DIRECTOR,
        ],
        "graph": {
            "default_mode": GRAPH_DEFAULT_MODE,
            "default_depth": GRAPH_DEFAULT_DEPTH,
            "default_max_nodes": GRAPH_DEFAULT_MAX_NODES,
        },
        "checked_at": now_iso(),
    }

def run_linkage_self_test() -> Dict[str, Any]:
    """
    self test เบื้องต้น
    """

    input_data = load_linkage_input_clean(force_refresh=False)
    pairs = build_director_company_pairs(force_refresh=False)
    directors = build_director_master(force_refresh=False)
    graph_payload = build_linkage_graph_payload(force_refresh=False)
    graph = get_linkage_graph({"max_nodes": 100})

    alias_status = {
        alias_key: bool(read_cache(alias_key, default={}))
        for alias_key in LINKAGE_GRAPH_ALIAS_CACHE_KEYS.keys()
    }

    return {
        "module": "linkage_service",
        "self_test": True,
        "status": get_linkage_module_status(),
        "input_total": input_data.get("total", 0),
        "pair_total": pairs.get("total", 0),
        "director_total": directors.get("total", 0),
        "graph_summary": graph.get("summary", {}),
        "main_graph_cache_key": LINKAGE_GRAPH_MAIN_CACHE_KEY,
        "main_graph_cache_ready": bool(graph_payload.get("nodes") or graph_payload.get("edges")),
        "alias_status": alias_status,
        "company_source": graph_payload.get("meta", {}).get("company_source"),
        "checked_at": now_iso(),
    }