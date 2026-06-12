# ============================================================
# FILE: backend/map_graph_service.py
# TIPX Enterprise Intelligence Dashboard
# ลำดับไฟล์ที่ 12 / 20
# ============================================================

"""
backend/map_graph_service.py

ไฟล์นี้เป็นศูนย์กลาง Map / OpenLayers Layer / Graph-map Integration ของระบบ TIPX

หน้าที่หลัก:
1. สร้าง OpenLayers Map Layers
2. สร้าง company point layer
3. สร้าง flood point layer
4. สร้าง policy exposure layer
5. สร้าง linkage line layer
6. สร้าง branch / province fallback point layer
7. สร้าง heatmap layer
8. สร้าง selected-context payload
9. รวม map + graph + dashboard context ให้ frontend ใช้งาน
10. รองรับ API กลุ่ม /api/map/*
11. รองรับ OpenLayers GeoJSON FeatureCollection
12. รองรับ D3 linkage graph integration
13. รองรับ filter builder context
14. รองรับ Package Export และ External Viewer Package

Data Source:
- cache/company_unified_master.json
- cache/spatial_join_result.json
- cache/flood_computed_risk.json
- cache/province_risk_exposure.json
- cache/linkage_graph_payload.json
- cache/shared_director_links.json
- cache/province_branch_coordinate_master.json

Layer Types:
- company_points
- flood_points
- policy_exposure_points
- linkage_lines
- branch_points
- heatmap_points
- province_boundaries
- basin_boundaries
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
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from config import (
    CACHE_TTL_SECONDS,
    MAP_DEFAULT_CENTER,
    MAP_DEFAULT_ZOOM,
    MAP_MIN_ZOOM,
    MAP_MAX_ZOOM,
    MAP_BASE_TILE_URL,
    MAP_BASE_ATTRIBUTION,
    MAP_LAYER_DEFAULTS,
    RISK_COLORS,
    RISK_SCORE,
    GRAPH_DEFAULT_MAX_NODES,
)

from utils import (
    apply_search_sort_pagination,
    clean_text,
    clean_text_lower,
    combine_risk_levels,
    get_or_build_cache,
    haversine_km,
    is_empty_value,
    make_feature_collection,
    make_line_feature,
    make_point_feature,
    normalize_risk_level,
    normalize_tax_id,
    read_cache,
    to_bool,
    to_jsonable,
    to_number,
    validate_coordinate,
)

try:
    from filter_engine import filter_company_records_for_map, filter_company_records_for_graph
except Exception:
    filter_company_records_for_map = None
    filter_company_records_for_graph = None

try:
    from flood_spatial_service import (
        get_flood_map_feature_collection,
        get_company_flood_map_feature_collection,
        get_province_boundaries,
        get_basin_boundaries,
    )
except Exception:
    get_flood_map_feature_collection = None
    get_company_flood_map_feature_collection = None
    get_province_boundaries = None
    get_basin_boundaries = None


# ============================================================
# 1) CONSTANTS
# ============================================================

DEFAULT_CONTEXT: Dict[str, Any] = {
    "force_refresh": False,
    "page": 1,
    "page_size": 500,
    "search": "",
    "sort_by": "",
    "sort_dir": "asc",
    "filters": {},
    "include_companies": True,
    "include_flood": True,
    "include_policy": True,
    "include_linkage": True,
    "include_branches": True,
    "include_heatmap": True,
    "include_boundaries": True,
    "selected_tax_id": "",
    "selected_director_id": "",
    "selected_province": "",
}

CACHE_KEYS: Dict[str, str] = {
    "map_layers": "map_layers",
    "map_companies": "map_companies",
    "map_flood": "map_flood",
    "map_policy_exposure": "map_policy_exposure",
    "map_linkage_lines": "map_linkage_lines",
    "map_branches": "map_branches",
    "map_heatmap": "map_heatmap",
    "map_selected_context": "map_selected_context",
}

COMPANY_SEARCHABLE_FIELDS: List[str] = [
    "tax_id_norm",
    "company_name",
    "province",
    "district",
    "subdistrict",
    "business_type_tsic",
    "wtip",
    "flood_risk_level",
    "loss_ratio_band",
]

FLOOD_SEARCHABLE_FIELDS: List[str] = [
    "source_type",
    "source_id",
    "source_name",
    "station_id",
    "station_name",
    "dam_id",
    "dam_name",
    "province",
    "risk_level",
]

DEFAULT_LAYER_ORDER: List[str] = [
    "province_boundaries",
    "basin_boundaries",
    "heatmap",
    "flood_points",
    "policy_exposure",
    "company_points",
    "branch_points",
    "linkage_lines",
]


# ============================================================
# 2) CONTEXT HELPERS
# ============================================================

def now_iso() -> str:
    """
    คืนเวลาปัจจุบันแบบ ISO string
    """

    return datetime.now().isoformat(timespec="seconds")


def normalize_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    normalize context จาก api_routes.py
    """

    result = dict(DEFAULT_CONTEXT)
    result.update(context or {})

    result["force_refresh"] = bool(result.get("force_refresh", False))
    result["page"] = int(result.get("page", 1) or 1)
    result["page_size"] = int(result.get("page_size", 500) or 500)
    result["search"] = clean_text(result.get("search", ""))
    result["sort_by"] = clean_text(result.get("sort_by", ""))
    result["sort_dir"] = clean_text_lower(result.get("sort_dir", "asc")) or "asc"

    if not isinstance(result.get("filters"), dict):
        result["filters"] = {}

    for key in [
        "include_companies",
        "include_flood",
        "include_policy",
        "include_linkage",
        "include_branches",
        "include_heatmap",
        "include_boundaries",
    ]:
        result[key] = bool(to_bool(result.get(key, True), default=True))

    result["selected_tax_id"] = normalize_tax_id(result.get("selected_tax_id") or result.get("tax_id") or "")
    result["selected_director_id"] = clean_text(result.get("selected_director_id") or result.get("director_id") or "")
    result["selected_province"] = clean_text(result.get("selected_province") or result.get("province") or "")

    return result


def get_map_ttl() -> int:
    """
    TTL สำหรับ map cache
    """

    return int(CACHE_TTL_SECONDS.get("map", 1800))


def get_layer_default(layer_id: str) -> Dict[str, Any]:
    """
    คืนค่า default ของ layer จาก config ถ้ามี
    """

    defaults = MAP_LAYER_DEFAULTS.get(layer_id, {}) if isinstance(MAP_LAYER_DEFAULTS, dict) else {}

    return {
        "layer_id": layer_id,
        "layer_name": defaults.get("layer_name", layer_id),
        "visible": defaults.get("visible", True),
        "opacity": defaults.get("opacity", 1.0),
        "z_index": defaults.get("z_index", DEFAULT_LAYER_ORDER.index(layer_id) if layer_id in DEFAULT_LAYER_ORDER else 99),
        "style": defaults.get("style", {}),
    }


# ============================================================
# 3) CACHE LOADERS
# ============================================================

def load_records_from_cache(cache_key: str) -> List[Dict[str, Any]]:
    """
    โหลด records จาก cache json

    รองรับ:
    - list
    - {"records": []}
    - {"data": []}
    - {"data": {"records": []}}
    """

    data = read_cache(cache_key, default={})

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


def load_company_records() -> List[Dict[str, Any]]:
    """
    โหลด company_unified_master จาก cache
    """

    return load_records_from_cache("company_unified_master")


def load_spatial_records() -> List[Dict[str, Any]]:
    """
    โหลด spatial_join_result จาก cache
    """

    return load_records_from_cache("spatial_join_result")


def load_flood_records() -> List[Dict[str, Any]]:
    """
    โหลด flood_computed_risk จาก cache
    """

    return load_records_from_cache("flood_computed_risk")


def load_branch_records() -> List[Dict[str, Any]]:
    """
    โหลด province_branch_coordinate_master จาก cache
    """

    return load_records_from_cache("province_branch_coordinate_master")


def load_shared_director_links() -> List[Dict[str, Any]]:
    """
    โหลด shared director links จาก cache
    """

    return load_records_from_cache("shared_director_links")


def load_linkage_graph_payload() -> Dict[str, Any]:
    """
    โหลด linkage graph payload จาก cache
    """

    data = read_cache("linkage_graph_payload", default={})

    if isinstance(data, dict):
        return data

    return {
        "nodes": [],
        "edges": [],
        "summary": {},
    }


# ============================================================
# 4) STYLE HELPERS
# ============================================================

def get_risk_color(risk_level: Any) -> str:
    """
    คืนสีตาม risk level
    """

    level = normalize_risk_level(risk_level)
    return RISK_COLORS.get(level, RISK_COLORS.get("Unknown", "#64748b"))


def get_risk_score(risk_level: Any) -> int:
    """
    คืน risk score
    """

    level = normalize_risk_level(risk_level)
    return RISK_SCORE.get(level, -1)


def scale_marker_size(
    value: Any,
    min_size: float = 8,
    max_size: float = 34,
    divisor: float = 1_000_000,
) -> float:
    """
    คำนวณขนาด marker จาก numeric value
    """

    number = to_number(value, 0) or 0

    if number <= 0:
        return min_size

    scaled = min_size + min(max_size - min_size, number / divisor)

    return round(scaled, 2)


def company_marker_style(company: Dict[str, Any]) -> Dict[str, Any]:
    """
    style สำหรับ company marker
    """

    risk_level = normalize_risk_level(company.get("flood_risk_level"))
    has_policy = bool(to_bool(company.get("has_policy"), default=False))
    has_linkage = bool(to_bool(company.get("has_linkage"), default=False))

    return {
        "marker_color": get_risk_color(risk_level),
        "marker_outline": "#ffffff" if has_policy else "#94a3b8",
        "marker_shape": "circle" if has_linkage else "square",
        "marker_size": scale_marker_size(company.get("total_suminsure"), min_size=10, max_size=36),
        "risk_level": risk_level,
        "risk_score": get_risk_score(risk_level),
    }


def flood_marker_style(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    style สำหรับ flood marker
    """

    risk_level = normalize_risk_level(record.get("risk_level"))

    return {
        "marker_color": get_risk_color(risk_level),
        "marker_outline": "#0f172a",
        "marker_shape": {
            "rainfall": "triangle",
            "waterlevel": "diamond",
            "large_dam": "hexagon",
            "medium_dam": "hexagon",
            "dam": "hexagon",
        }.get(clean_text(record.get("source_type")), "circle"),
        "marker_size": 8 + max(0, get_risk_score(risk_level)) * 4,
        "risk_level": risk_level,
        "risk_score": get_risk_score(risk_level),
    }


def get_layer_style(layer_id: str) -> Dict[str, Any]:
    """
    คืน style object ที่ frontend ใช้กับ OpenLayers
    """

    base = get_layer_default(layer_id)

    styles: Dict[str, Dict[str, Any]] = {
        "company_points": {
            "renderer": "point",
            "color_field": "flood_risk_level",
            "size_field": "total_suminsure",
            "label_field": "company_name",
            "cluster": True,
            "cluster_distance": 40,
        },
        "flood_points": {
            "renderer": "point",
            "color_field": "risk_level",
            "size_field": "risk_score",
            "label_field": "source_name",
            "cluster": True,
            "cluster_distance": 35,
        },
        "policy_exposure": {
            "renderer": "point",
            "color_field": "flood_risk_level",
            "size_field": "total_suminsure",
            "label_field": "company_name",
            "cluster": False,
        },
        "linkage_lines": {
            "renderer": "line",
            "color": "#38bdf8",
            "width_field": "weight",
            "opacity": 0.45,
        },
        "branch_points": {
            "renderer": "point",
            "color": "#a855f7",
            "size": 8,
            "label_field": "branch_name",
            "cluster": True,
        },
        "heatmap": {
            "renderer": "heatmap",
            "weight_field": "heat_weight",
            "radius": 25,
            "blur": 18,
        },
        "province_boundaries": {
            "renderer": "polygon",
            "stroke_color": "#64748b",
            "stroke_width": 1,
            "fill_color": "rgba(100,116,139,0.08)",
        },
        "basin_boundaries": {
            "renderer": "polygon",
            "stroke_color": "#0ea5e9",
            "stroke_width": 1,
            "fill_color": "rgba(14,165,233,0.06)",
        },
    }

    return {
        **styles.get(layer_id, {}),
        **base.get("style", {}),
    }


# ============================================================
# 5) FILTER HELPERS
# ============================================================

def filter_company_records(records: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    filter company records สำหรับ map
    """

    ctx = normalize_context(context)

    filtered = list(records)

    if filter_company_records_for_map is not None:
        try:
            return filter_company_records_for_map(filtered, ctx)
        except Exception:
            pass

    if ctx.get("selected_province"):
        province = ctx["selected_province"]
        filtered = [
            record
            for record in filtered
            if clean_text(record.get("province")) == province
        ]

    if ctx.get("search"):
        search = clean_text_lower(ctx.get("search"))
        filtered = [
            record
            for record in filtered
            if search in " ".join(
                [
                    clean_text(record.get("tax_id_norm")),
                    clean_text(record.get("company_name")),
                    clean_text(record.get("province")),
                    clean_text(record.get("business_type_tsic")),
                ]
            ).lower()
        ]

    filters = ctx.get("filters", {})

    for key, value in filters.items():
        if is_empty_value(value):
            continue

        if isinstance(value, list):
            value_set = {clean_text(v) for v in value}
            filtered = [
                record
                for record in filtered
                if clean_text(record.get(key)) in value_set
            ]
        else:
            filtered = [
                record
                for record in filtered
                if clean_text(record.get(key)) == clean_text(value)
            ]

    return filtered


def filter_flood_records(records: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    filter flood records สำหรับ map
    """

    ctx = normalize_context(context)

    filtered = list(records)

    if ctx.get("selected_province"):
        province = ctx["selected_province"]
        filtered = [
            record
            for record in filtered
            if clean_text(record.get("province")) == province
        ]

    if ctx.get("search"):
        search = clean_text_lower(ctx.get("search"))
        filtered = [
            record
            for record in filtered
            if search in " ".join(
                [
                    clean_text(record.get("source_type")),
                    clean_text(record.get("source_id")),
                    clean_text(record.get("source_name")),
                    clean_text(record.get("province")),
                    clean_text(record.get("risk_level")),
                ]
            ).lower()
        ]

    filters = ctx.get("filters", {})

    for key, value in filters.items():
        if is_empty_value(value):
            continue

        if key in {"flood_risk_level", "risk_level"}:
            if isinstance(value, list):
                allowed = {normalize_risk_level(v) for v in value}
                filtered = [
                    record
                    for record in filtered
                    if normalize_risk_level(record.get("risk_level")) in allowed
                ]
            else:
                expected = normalize_risk_level(value)
                filtered = [
                    record
                    for record in filtered
                    if normalize_risk_level(record.get("risk_level")) == expected
                ]

    return filtered


# ============================================================
# 6) FEATURE BUILDERS
# ============================================================

def build_company_feature(company: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    สร้าง GeoJSON Feature ของบริษัท
    """

    style = company_marker_style(company)

    feature = make_point_feature(
        lon=company.get("lon"),
        lat=company.get("lat"),
        properties={
            "feature_id": company.get("tax_id_norm"),
            "feature_type": "company",
            "tax_id_norm": company.get("tax_id_norm"),
            "company_name": company.get("company_name"),
            "province": company.get("province"),
            "district": company.get("district"),
            "subdistrict": company.get("subdistrict"),
            "business_type_tsic": company.get("business_type_tsic"),
            "company_size": company.get("company_size"),
            "wtip": company.get("wtip"),

            "has_policy": company.get("has_policy"),
            "has_linkage": company.get("has_linkage"),
            "has_location": company.get("has_location"),
            "has_flood_context": company.get("has_flood_context"),

            "total_premium": company.get("total_premium"),
            "total_loss": company.get("total_loss"),
            "total_suminsure": company.get("total_suminsure"),
            "loss_ratio": company.get("loss_ratio"),
            "loss_ratio_band": company.get("loss_ratio_band"),

            "flood_risk_level": style["risk_level"],
            "risk_level": style["risk_level"],
            "risk_score": style["risk_score"],
            "flood_risk_reason": company.get("flood_risk_reason"),
            "location_quality": company.get("location_quality"),

            **style,
        },
    )

    return feature


def build_flood_feature(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    สร้าง GeoJSON Feature ของ flood source
    """

    style = flood_marker_style(record)

    feature = make_point_feature(
        lon=record.get("lon"),
        lat=record.get("lat"),
        properties={
            "feature_id": record.get("source_key") or f"{record.get('source_type')}:{record.get('source_id')}",
            "feature_type": record.get("source_type"),
            "source_type": record.get("source_type"),
            "source_id": record.get("source_id"),
            "source_name": record.get("source_name"),
            "station_id": record.get("station_id"),
            "station_name": record.get("station_name"),
            "dam_id": record.get("dam_id"),
            "dam_name": record.get("dam_name"),
            "province": record.get("province"),
            "basin": record.get("basin"),
            "data_datetime": record.get("data_datetime"),
            "rainfall_value": record.get("rainfall_value"),
            "waterlevel_value": record.get("waterlevel_value"),
            "storage_percent": record.get("storage_percent"),
            "risk_level": style["risk_level"],
            "risk_score": style["risk_score"],
            "risk_reason": record.get("risk_reason"),
            "risk_color": style["marker_color"],
            **style,
        },
    )

    return feature


def build_branch_feature(branch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    สร้าง GeoJSON Feature ของสาขา / province fallback coordinate
    """

    feature = make_point_feature(
        lon=branch.get("lon"),
        lat=branch.get("lat"),
        properties={
            "feature_id": branch.get("branch_id"),
            "feature_type": "branch",
            "branch_id": branch.get("branch_id"),
            "branch_name": branch.get("branch_name"),
            "province": branch.get("province"),
            "district": branch.get("district"),
            "subdistrict": branch.get("subdistrict"),
            "region": branch.get("region"),
            "location_quality": branch.get("location_quality"),
            "marker_color": "#a855f7",
            "marker_size": 8,
            "marker_shape": "cross",
        },
    )

    return feature


def build_linkage_line_feature(link: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    สร้าง GeoJSON LineString ของ shared director link
    """

    source_lat = to_number(link.get("source_lat"), None)
    source_lon = to_number(link.get("source_lon"), None)
    target_lat = to_number(link.get("target_lat"), None)
    target_lon = to_number(link.get("target_lon"), None)

    if source_lat is None or source_lon is None or target_lat is None or target_lon is None:
        return None

    distance = haversine_km(source_lat, source_lon, target_lat, target_lon)

    risk_level = combine_risk_levels(
        [
            link.get("source_flood_risk_level"),
            link.get("target_flood_risk_level"),
            link.get("combined_flood_risk_level"),
        ]
    )

    feature = make_line_feature(
        coordinates=[
            (source_lon, source_lat),
            (target_lon, target_lat),
        ],
        properties={
            "feature_id": link.get("link_id"),
            "feature_type": "linkage_line",
            "link_id": link.get("link_id"),
            "source_tax_id": link.get("source_tax_id"),
            "target_tax_id": link.get("target_tax_id"),
            "source_company_name": link.get("source_company_name"),
            "target_company_name": link.get("target_company_name"),
            "shared_directors": link.get("shared_directors", []),
            "shared_directors_text": link.get("shared_directors_text", ""),
            "weight": link.get("weight", 1),
            "distance_km": distance,
            "combined_flood_risk_level": risk_level,
            "risk_level": risk_level,
            "line_color": get_risk_color(risk_level),
            "line_width": max(1, min(8, to_number(link.get("weight"), 1) or 1)),
            "line_opacity": 0.45,
            "combined_suminsure": link.get("combined_suminsure", 0),
        },
    )

    return feature


def build_heatmap_feature(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    สร้าง heatmap point จาก company exposure
    """

    risk_score = get_risk_score(record.get("flood_risk_level"))
    suminsure = to_number(record.get("total_suminsure"), 0) or 0

    heat_weight = max(0.05, min(1.0, (risk_score + 1) / 5))
    exposure_weight = min(1.0, suminsure / 10_000_000) if suminsure > 0 else 0

    final_weight = round(max(heat_weight, exposure_weight), 4)

    feature = make_point_feature(
        lon=record.get("lon"),
        lat=record.get("lat"),
        properties={
            "feature_id": record.get("tax_id_norm"),
            "feature_type": "heatmap",
            "tax_id_norm": record.get("tax_id_norm"),
            "company_name": record.get("company_name"),
            "province": record.get("province"),
            "flood_risk_level": normalize_risk_level(record.get("flood_risk_level")),
            "total_suminsure": suminsure,
            "heat_weight": final_weight,
        },
    )

    return feature


# ============================================================
# 7) LAYER PAYLOAD BUILDERS
# ============================================================

def build_layer_payload(
    layer_id: str,
    layer_name: str,
    layer_type: str,
    feature_collection: Dict[str, Any],
    visible: Optional[bool] = None,
    opacity: Optional[float] = None,
    z_index: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    สร้าง layer payload มาตรฐานสำหรับ OpenLayers
    """

    defaults = get_layer_default(layer_id)

    features = feature_collection.get("features", []) if isinstance(feature_collection, dict) else []

    return {
        "layer_id": layer_id,
        "layer_name": layer_name,
        "layer_type": layer_type,
        "visible": defaults["visible"] if visible is None else bool(visible),
        "opacity": defaults["opacity"] if opacity is None else float(opacity),
        "z_index": defaults["z_index"] if z_index is None else int(z_index),
        "record_count": len(features),
        "feature_collection": feature_collection,
        "style": get_layer_style(layer_id),
        "meta": {
            "created_at": now_iso(),
            **(extra or {}),
        },
    }


def build_company_points_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง company_points layer
    """

    ctx = normalize_context(context)

    companies = load_company_records()
    companies = [
        company
        for company in companies
        if to_bool(company.get("has_location"), default=False)
        or validate_coordinate(company.get("lat"), company.get("lon"))["valid"]
    ]

    companies = filter_company_records(companies, ctx)

    features = []

    for company in companies:
        feature = build_company_feature(company)
        if feature:
            features.append(feature)

    return build_layer_payload(
        layer_id="company_points",
        layer_name="Company Points",
        layer_type="point",
        feature_collection=make_feature_collection(features),
        extra={
            "source": "company_unified_master",
            "company_count": len(companies),
        },
    )


def build_flood_points_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง flood_points layer
    """

    ctx = normalize_context(context)

    if get_flood_map_feature_collection is not None:
        try:
            feature_collection = get_flood_map_feature_collection(ctx)
            return build_layer_payload(
                layer_id="flood_points",
                layer_name="Flood Sources",
                layer_type="point",
                feature_collection=feature_collection,
                extra={
                    "source": "flood_spatial_service",
                },
            )
        except Exception:
            pass

    flood_records = filter_flood_records(load_flood_records(), ctx)

    features = []

    for record in flood_records:
        feature = build_flood_feature(record)
        if feature:
            features.append(feature)

    return build_layer_payload(
        layer_id="flood_points",
        layer_name="Flood Sources",
        layer_type="point",
        feature_collection=make_feature_collection(features),
        extra={
            "source": "flood_computed_risk",
            "flood_count": len(flood_records),
        },
    )


def build_policy_exposure_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง policy_exposure layer

    ใช้ company_unified_master เฉพาะบริษัทที่มี policy และมีพิกัด
    """

    ctx = normalize_context(context)

    if get_company_flood_map_feature_collection is not None:
        try:
            feature_collection = get_company_flood_map_feature_collection(ctx)
            return build_layer_payload(
                layer_id="policy_exposure",
                layer_name="Policy Flood Exposure",
                layer_type="point",
                feature_collection=feature_collection,
                extra={
                    "source": "company_flood_context",
                },
            )
        except Exception:
            pass

    companies = load_company_records()
    companies = [
        company
        for company in companies
        if to_bool(company.get("has_policy"), default=False)
        and validate_coordinate(company.get("lat"), company.get("lon"))["valid"]
    ]

    companies = filter_company_records(companies, ctx)

    features = []

    for company in companies:
        feature = build_company_feature(company)
        if feature:
            feature["properties"]["feature_type"] = "policy_exposure"
            features.append(feature)

    return build_layer_payload(
        layer_id="policy_exposure",
        layer_name="Policy Exposure",
        layer_type="point",
        feature_collection=make_feature_collection(features),
        extra={
            "source": "company_unified_master",
            "company_count": len(companies),
        },
    )


def build_linkage_lines_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง linkage_lines layer จาก shared_director_links
    """

    ctx = normalize_context(context)

    links = load_shared_director_links()

    if ctx.get("selected_tax_id"):
        tax_id = ctx["selected_tax_id"]
        links = [
            link
            for link in links
            if normalize_tax_id(link.get("source_tax_id")) == tax_id
            or normalize_tax_id(link.get("target_tax_id")) == tax_id
        ]

    if ctx.get("selected_province"):
        province = ctx["selected_province"]
        links = [
            link
            for link in links
            if clean_text(link.get("source_province")) == province
            or clean_text(link.get("target_province")) == province
        ]

    features = []

    for link in links:
        feature = build_linkage_line_feature(link)
        if feature:
            features.append(feature)

    return build_layer_payload(
        layer_id="linkage_lines",
        layer_name="Shared Director Lines",
        layer_type="line",
        feature_collection=make_feature_collection(features),
        extra={
            "source": "shared_director_links",
            "link_count": len(links),
        },
    )


def build_branch_points_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง branch_points layer
    """

    ctx = normalize_context(context)

    branches = load_branch_records()

    if ctx.get("selected_province"):
        province = ctx["selected_province"]
        branches = [
            branch
            for branch in branches
            if clean_text(branch.get("province")) == province
        ]

    features = []

    for branch in branches:
        feature = build_branch_feature(branch)
        if feature:
            features.append(feature)

    return build_layer_payload(
        layer_id="branch_points",
        layer_name="Branch / Province Fallback Points",
        layer_type="point",
        feature_collection=make_feature_collection(features),
        visible=False,
        extra={
            "source": "province_branch_coordinate_master",
            "branch_count": len(branches),
        },
    )


def build_heatmap_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง heatmap layer จาก company exposure
    """

    ctx = normalize_context(context)

    companies = load_company_records()

    companies = [
        company
        for company in companies
        if validate_coordinate(company.get("lat"), company.get("lon"))["valid"]
    ]

    companies = filter_company_records(companies, ctx)

    features = []

    for company in companies:
        feature = build_heatmap_feature(company)
        if feature:
            features.append(feature)

    return build_layer_payload(
        layer_id="heatmap",
        layer_name="Exposure Heatmap",
        layer_type="heatmap",
        feature_collection=make_feature_collection(features),
        visible=False,
        opacity=0.65,
        extra={
            "source": "company_unified_master",
            "company_count": len(companies),
        },
    )


def build_province_boundaries_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง province boundary layer
    """

    if get_province_boundaries is not None:
        try:
            boundary = get_province_boundaries()
            feature_collection = {
                "type": "FeatureCollection",
                "features": boundary.get("features", []),
            }
            records = boundary.get("records", [])

            return build_layer_payload(
                layer_id="province_boundaries",
                layer_name="Province Boundaries",
                layer_type="polygon",
                feature_collection=feature_collection,
                visible=False,
                opacity=0.7,
                extra={
                    "source": "flood_master_database",
                    "record_count_raw": len(records),
                },
            )
        except Exception:
            pass

    return build_layer_payload(
        layer_id="province_boundaries",
        layer_name="Province Boundaries",
        layer_type="polygon",
        feature_collection=make_feature_collection([]),
        visible=False,
        opacity=0.7,
    )


def build_basin_boundaries_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง basin boundary layer
    """

    if get_basin_boundaries is not None:
        try:
            boundary = get_basin_boundaries()
            feature_collection = {
                "type": "FeatureCollection",
                "features": boundary.get("features", []),
            }
            records = boundary.get("records", [])

            return build_layer_payload(
                layer_id="basin_boundaries",
                layer_name="Basin Boundaries",
                layer_type="polygon",
                feature_collection=feature_collection,
                visible=False,
                opacity=0.7,
                extra={
                    "source": "flood_master_database",
                    "record_count_raw": len(records),
                },
            )
        except Exception:
            pass

    return build_layer_payload(
        layer_id="basin_boundaries",
        layer_name="Basin Boundaries",
        layer_type="polygon",
        feature_collection=make_feature_collection([]),
        visible=False,
        opacity=0.7,
    )


# ============================================================
# 8) API LAYER FUNCTIONS
# ============================================================

def get_map_companies(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/companies
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_company_points_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_companies"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_companies",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def get_map_flood(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/flood
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_flood_points_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_flood"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_flood",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def get_map_policy_exposure(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/policy-exposure
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_policy_exposure_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_policy_exposure"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_policy_exposure",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def get_map_linkage_lines(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/linkage-lines
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_linkage_lines_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_linkage_lines"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_linkage_lines",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def get_map_branches(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/branches
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_branch_points_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_branches"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_branches",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


def get_map_heatmap(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/heatmap
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_heatmap_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_heatmap"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_heatmap",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


# ============================================================
# 9) FULL MAP LAYERS
# ============================================================

def get_map_layers(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/layers

    คืน layer ทั้งหมดที่ OpenLayers ต้องใช้
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        layers: Dict[str, Dict[str, Any]] = {}

        if ctx.get("include_boundaries"):
            layers["province_boundaries"] = build_province_boundaries_layer(ctx)
            layers["basin_boundaries"] = build_basin_boundaries_layer(ctx)

        if ctx.get("include_heatmap"):
            layers["heatmap"] = build_heatmap_layer(ctx)

        if ctx.get("include_flood"):
            layers["flood_points"] = build_flood_points_layer(ctx)

        if ctx.get("include_policy"):
            layers["policy_exposure"] = build_policy_exposure_layer(ctx)

        if ctx.get("include_companies"):
            layers["company_points"] = build_company_points_layer(ctx)

        if ctx.get("include_branches"):
            layers["branch_points"] = build_branch_points_layer(ctx)

        if ctx.get("include_linkage"):
            layers["linkage_lines"] = build_linkage_lines_layer(ctx)

        layer_list = [
            layers[layer_id]
            for layer_id in DEFAULT_LAYER_ORDER
            if layer_id in layers
        ]

        feature_count = sum(layer.get("record_count", 0) for layer in layer_list)

        return {
            "map": {
                "center": MAP_DEFAULT_CENTER,
                "zoom": MAP_DEFAULT_ZOOM,
                "min_zoom": MAP_MIN_ZOOM,
                "max_zoom": MAP_MAX_ZOOM,
                "base_tile_url": MAP_BASE_TILE_URL,
                "base_attribution": MAP_BASE_ATTRIBUTION,
            },
            "layers": layers,
            "layer_order": [layer["layer_id"] for layer in layer_list],
            "layer_list": layer_list,
            "summary": {
                "layer_count": len(layer_list),
                "feature_count": feature_count,
                "generated_at": now_iso(),
            },
            "context": ctx,
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_layers"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_layers",
    )

    return {
        **cache_result["data"],
        "cache_used": cache_result["cache_used"],
    }


# ============================================================
# 10) SELECTED CONTEXT
# ============================================================

def find_company_by_tax_id(tax_id: str) -> Optional[Dict[str, Any]]:
    """
    หา company จาก company_unified_master
    """

    tax_id_norm = normalize_tax_id(tax_id)

    for company in load_company_records():
        if normalize_tax_id(company.get("tax_id_norm")) == tax_id_norm:
            return company

    return None


def find_spatial_by_tax_id(tax_id: str) -> Optional[Dict[str, Any]]:
    """
    หา spatial context จาก spatial_join_result
    """

    tax_id_norm = normalize_tax_id(tax_id)

    for record in load_spatial_records():
        if normalize_tax_id(record.get("tax_id_norm")) == tax_id_norm:
            return record

    return None


def get_selected_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/selected-context

    ใช้ตอน user คลิก marker / node แล้ว frontend ต้องการ context รอบตัว
    """

    ctx = normalize_context(context)

    selected_tax_id = ctx.get("selected_tax_id")
    selected_director_id = ctx.get("selected_director_id")
    selected_province = ctx.get("selected_province")

    result: Dict[str, Any] = {
        "selected_tax_id": selected_tax_id,
        "selected_director_id": selected_director_id,
        "selected_province": selected_province,
        "company": None,
        "spatial": None,
        "nearby_companies": [],
        "nearby_flood_sources": [],
        "linkage_lines": [],
        "province_context": {},
        "map_focus": None,
        "generated_at": now_iso(),
    }

    if selected_tax_id:
        company = find_company_by_tax_id(selected_tax_id)
        spatial = find_spatial_by_tax_id(selected_tax_id)

        result["company"] = company
        result["spatial"] = spatial

        if company:
            lat = company.get("lat")
            lon = company.get("lon")
            coord = validate_coordinate(lat, lon)

            if coord["valid"]:
                result["map_focus"] = {
                    "lat": coord["lat"],
                    "lon": coord["lon"],
                    "zoom": 12,
                }

                result["nearby_companies"] = find_nearby_companies(
                    origin_company=company,
                    limit=20,
                    max_distance_km=50,
                )

                result["nearby_flood_sources"] = find_nearby_flood_sources(
                    lat=coord["lat"],
                    lon=coord["lon"],
                    limit=20,
                    max_distance_km=80,
                )

        result["linkage_lines"] = [
            link
            for link in load_shared_director_links()
            if normalize_tax_id(link.get("source_tax_id")) == selected_tax_id
            or normalize_tax_id(link.get("target_tax_id")) == selected_tax_id
        ]

    if selected_province:
        result["province_context"] = build_province_context(selected_province)

    return result


def find_nearby_companies(
    origin_company: Dict[str, Any],
    limit: int = 20,
    max_distance_km: float = 50,
) -> List[Dict[str, Any]]:
    """
    หา nearby companies จาก origin company
    """

    origin_tax_id = normalize_tax_id(origin_company.get("tax_id_norm"))
    origin_lat = origin_company.get("lat")
    origin_lon = origin_company.get("lon")

    nearby: List[Dict[str, Any]] = []

    for company in load_company_records():
        tax_id = normalize_tax_id(company.get("tax_id_norm"))

        if tax_id == origin_tax_id:
            continue

        distance = haversine_km(origin_lat, origin_lon, company.get("lat"), company.get("lon"))

        if distance is None:
            continue

        if distance > max_distance_km:
            continue

        item = {
            "tax_id_norm": tax_id,
            "company_name": company.get("company_name"),
            "province": company.get("province"),
            "lat": company.get("lat"),
            "lon": company.get("lon"),
            "distance_km": distance,
            "flood_risk_level": company.get("flood_risk_level"),
            "total_suminsure": company.get("total_suminsure"),
        }

        nearby.append(item)

    nearby = sorted(nearby, key=lambda item: item["distance_km"])

    return nearby[:limit]


def find_nearby_flood_sources(
    lat: Any,
    lon: Any,
    limit: int = 20,
    max_distance_km: float = 80,
) -> List[Dict[str, Any]]:
    """
    หา nearby flood sources
    """

    sources = []

    for source in load_flood_records():
        distance = haversine_km(lat, lon, source.get("lat"), source.get("lon"))

        if distance is None:
            continue

        if distance > max_distance_km:
            continue

        item = dict(source)
        item["distance_km"] = distance

        sources.append(item)

    sources = sorted(
        sources,
        key=lambda item: (
            item.get("distance_km", 999999),
            -(to_number(item.get("risk_score"), -1) or -1),
        ),
    )

    return sources[:limit]


def build_province_context(province: str) -> Dict[str, Any]:
    """
    สร้าง province context สำหรับ selected province
    """

    province = clean_text(province)

    companies = [
        company
        for company in load_company_records()
        if clean_text(company.get("province")) == province
    ]

    flood_sources = [
        source
        for source in load_flood_records()
        if clean_text(source.get("province")) == province
    ]

    risk_level = combine_risk_levels(
        [source.get("risk_level") for source in flood_sources]
        + [company.get("flood_risk_level") for company in companies]
    )

    return {
        "province": province,
        "company_count": len(companies),
        "flood_source_count": len(flood_sources),
        "risk_level": risk_level,
        "risk_color": get_risk_color(risk_level),
        "risk_counts": dict(Counter(normalize_risk_level(item.get("risk_level")) for item in flood_sources)),
        "company_risk_counts": dict(Counter(normalize_risk_level(item.get("flood_risk_level")) for item in companies)),
        "total_premium": sum(to_number(item.get("total_premium"), 0) or 0 for item in companies),
        "total_loss": sum(to_number(item.get("total_loss"), 0) or 0 for item in companies),
        "total_suminsure": sum(to_number(item.get("total_suminsure"), 0) or 0 for item in companies),
        "top_companies": sorted(
            companies,
            key=lambda item: to_number(item.get("total_suminsure"), 0) or 0,
            reverse=True,
        )[:20],
        "top_flood_sources": sorted(
            flood_sources,
            key=lambda item: to_number(item.get("risk_score"), -1) or -1,
            reverse=True,
        )[:20],
    }


# ============================================================
# 11) DASHBOARD / PACKAGE SUPPORT
# ============================================================

def get_map_dashboard_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง map payload สำหรับ dashboard_package_service.py
    """

    ctx = normalize_context(context)

    layers = get_map_layers(ctx)
    selected_context = get_selected_context(ctx)

    layer_summary = layers.get("summary", {})

    return {
        "map": layers.get("map", {}),
        "layers": layers.get("layers", {}),
        "layer_order": layers.get("layer_order", []),
        "summary": layer_summary,
        "selected_context": selected_context,
        "generated_at": now_iso(),
    }


def get_external_viewer_map_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง map payload สำหรับ External Viewer Package

    เน้นข้อมูลที่ frontend ใช้งานได้ทันที
    """

    ctx = normalize_context(context)

    layers = get_map_layers(ctx)

    return {
        "map": layers.get("map", {}),
        "layer_order": layers.get("layer_order", []),
        "layers": {
            layer_id: {
                "layer_id": layer.get("layer_id"),
                "layer_name": layer.get("layer_name"),
                "layer_type": layer.get("layer_type"),
                "visible": layer.get("visible"),
                "opacity": layer.get("opacity"),
                "z_index": layer.get("z_index"),
                "record_count": layer.get("record_count"),
                "feature_collection": layer.get("feature_collection"),
                "style": layer.get("style"),
            }
            for layer_id, layer in layers.get("layers", {}).items()
        },
        "summary": layers.get("summary", {}),
        "generated_at": now_iso(),
    }


# ============================================================
# 12) CACHE REBUILD
# ============================================================

def rebuild_map_cache(force_refresh: bool = True) -> Dict[str, Any]:
    """
    rebuild cache ทั้งหมดของ map_graph_service.py
    """

    context = {
        "force_refresh": force_refresh,
    }

    results = {
        "map_companies": get_map_companies(context),
        "map_flood": get_map_flood(context),
        "map_policy_exposure": get_map_policy_exposure(context),
        "map_linkage_lines": get_map_linkage_lines(context),
        "map_branches": get_map_branches(context),
        "map_heatmap": get_map_heatmap(context),
        "map_layers": get_map_layers(context),
        "map_selected_context": get_selected_context(context),
    }

    return {
        "rebuilt": True,
        "results": {
            key: {
                "record_count": value.get("record_count") or value.get("summary", {}).get("feature_count"),
                "cache_used": value.get("cache_used"),
                "created_at": value.get("meta", {}).get("created_at") or value.get("summary", {}).get("generated_at"),
            }
            for key, value in results.items()
        },
        "generated_at": now_iso(),
    }


# ============================================================
# 13) CLASS ADAPTER FOR API ROUTES
# ============================================================

class MapGraphService:
    """
    Class adapter สำหรับ api_routes.py

    api_routes.py สามารถเรียกแบบ:
        service = MapGraphService()
        service.get_map_layers(context)

    หรือเรียก module-level function โดยตรงก็ได้
    """

    def get_map_layers(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_layers(context)

    def get_map_flood(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_flood(context)

    def get_map_companies(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_companies(context)

    def get_map_policy_exposure(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_policy_exposure(context)

    def get_map_linkage_lines(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_linkage_lines(context)

    def get_map_branches(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_branches(context)

    def get_map_heatmap(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_heatmap(context)

    def get_selected_context(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_selected_context(context)

    def get_map_dashboard_payload(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_dashboard_payload(context)

    def get_external_viewer_map_payload(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_external_viewer_map_payload(context)

    def rebuild_cache(self, force_refresh: bool = True) -> Dict[str, Any]:
        return rebuild_map_cache(force_refresh=force_refresh)


# ============================================================
# 14) MODULE STATUS / SELF TEST
# ============================================================

def get_map_graph_module_status() -> Dict[str, Any]:
    """
    คืนสถานะ module map_graph_service.py
    """

    return {
        "module": "map_graph_service",
        "ready": True,
        "cache_keys": CACHE_KEYS,
        "supported_layers": [
            "company_points",
            "flood_points",
            "policy_exposure",
            "linkage_lines",
            "branch_points",
            "heatmap",
            "province_boundaries",
            "basin_boundaries",
        ],
        "map_config": {
            "center": MAP_DEFAULT_CENTER,
            "zoom": MAP_DEFAULT_ZOOM,
            "min_zoom": MAP_MIN_ZOOM,
            "max_zoom": MAP_MAX_ZOOM,
            "base_tile_url": MAP_BASE_TILE_URL,
            "base_attribution": MAP_BASE_ATTRIBUTION,
        },
        "data_sources": {
            "company_records": len(load_company_records()),
            "spatial_records": len(load_spatial_records()),
            "flood_records": len(load_flood_records()),
            "branch_records": len(load_branch_records()),
            "shared_director_links": len(load_shared_director_links()),
        },
        "checked_at": now_iso(),
    }


def run_map_graph_self_test() -> Dict[str, Any]:
    """
    self test เบื้องต้น
    """

    companies = get_map_companies({"force_refresh": False})
    flood = get_map_flood({"force_refresh": False})
    layers = get_map_layers({"force_refresh": False})

    return {
        "module": "map_graph_service",
        "self_test": True,
        "status": get_map_graph_module_status(),
        "company_layer_count": companies.get("record_count", 0),
        "flood_layer_count": flood.get("record_count", 0),
        "layer_summary": layers.get("summary", {}),
        "checked_at": now_iso(),
    }