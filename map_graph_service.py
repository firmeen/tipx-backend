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
import json
import math
import config
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
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

try:
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
    UTILS_LOADED = True
except Exception as e:
    UTILS_LOADED = False
    UTILS_ERROR = str(e)

    def clean_text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default

    def clean_text_lower(value: Any, default: str = "") -> str:
        return clean_text(value, default=default).lower()

    def is_empty_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if isinstance(value, float) and math.isnan(value):
            return True
        return False

    def to_number(value: Any, default: Any = None) -> Any:
        if is_empty_value(value):
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(number) or math.isinf(number):
            return default
        return number

    def to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        text = clean_text_lower(value)
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return default

    def normalize_tax_id(value: Any) -> str:
        return "".join(ch for ch in clean_text(value) if ch.isdigit())

    def normalize_risk_level(value: Any) -> str:
        text = clean_text_lower(value)
        if text in {"critical", "very_high", "very high", "severe"}:
            return "Critical"
        if text in {"high", "สูง"}:
            return "High"
        if text in {"medium", "moderate", "กลาง"}:
            return "Medium"
        if text in {"low", "ต่ำ"}:
            return "Low"
        if text in {"normal", "none"}:
            return "Normal"
        return "Unknown"

    def combine_risk_levels(values: List[Any]) -> str:
        order = ["Unknown", "Normal", "Low", "Medium", "High", "Critical"]
        best = "Unknown"
        for value in values:
            level = normalize_risk_level(value)
            if order.index(level) > order.index(best):
                best = level
        return best

    def validate_coordinate(lat: Any, lon: Any) -> Dict[str, Any]:
        lat_number = to_number(lat, None)
        lon_number = to_number(lon, None)
        if lat_number is None or lon_number is None:
            return {"valid": False, "lat": None, "lon": None, "issue": "missing coordinate"}
        if lat_number == 0 and lon_number == 0:
            return {"valid": False, "lat": lat_number, "lon": lon_number, "issue": "zero coordinate"}
        if not (5.0 <= lat_number <= 21.5 and 97.0 <= lon_number <= 106.5):
            return {"valid": False, "lat": lat_number, "lon": lon_number, "issue": "outside Thailand bounds"}
        return {"valid": True, "lat": lat_number, "lon": lon_number, "issue": ""}

    def make_feature_collection(features: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        return {"type": "FeatureCollection", "features": list(features or [])}

    def make_point_feature(lon: Any, lat: Any, properties: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        coord = validate_coordinate(lat, lon)
        if not coord["valid"]:
            return None
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [coord["lon"], coord["lat"]]},
            "properties": dict(properties or {}),
        }

    def make_line_feature(coordinates: List[Tuple[Any, Any]], properties: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        clean_coordinates = []
        for lon, lat in coordinates:
            coord = validate_coordinate(lat, lon)
            if not coord["valid"]:
                return None
            clean_coordinates.append([coord["lon"], coord["lat"]])
        if len(clean_coordinates) < 2:
            return None
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": clean_coordinates},
            "properties": dict(properties or {}),
        }

    def haversine_km(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> Optional[float]:
        coord1 = validate_coordinate(lat1, lon1)
        coord2 = validate_coordinate(lat2, lon2)
        if not coord1["valid"] or not coord2["valid"]:
            return None
        radius_km = 6371.0088
        phi1 = math.radians(coord1["lat"])
        phi2 = math.radians(coord2["lat"])
        d_phi = math.radians(coord2["lat"] - coord1["lat"])
        d_lambda = math.radians(coord2["lon"] - coord1["lon"])
        a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        return round(radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 4)

    def to_jsonable(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return None if math.isnan(value) or math.isinf(value) else value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {clean_text(key): to_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [to_jsonable(item) for item in value]
        if hasattr(value, "to_dict"):
            try:
                return to_jsonable(value.to_dict(orient="records"))
            except TypeError:
                return to_jsonable(value.to_dict())
        if hasattr(value, "item"):
            try:
                return to_jsonable(value.item())
            except Exception:
                pass
        return clean_text(value)

    def read_cache(cache_key: str, default: Any = None) -> Any:
        if default is None:
            default = {}
        cache_path = Path(__file__).resolve().parent.parent / "cache" / f"{cache_key}.json"
        if not cache_path.exists():
            return default
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def get_or_build_cache(
        cache_key: str,
        builder: Any,
        ttl_seconds: int = 0,
        force_refresh: bool = False,
        source: str = "",
    ) -> Dict[str, Any]:
        return {
            "data": builder(),
            "cache_used": False,
            "source": source,
            "ttl_seconds": ttl_seconds,
            "force_refresh": bool(force_refresh),
        }

    def apply_search_sort_pagination(records: List[Dict[str, Any]], *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"records": records, "meta": {"total": len(records)}}

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
        get_latest_rainfall,
        get_latest_waterlevel,
        get_latest_dam,
        get_flood_prediction_map,
    )
except Exception:
    get_flood_map_feature_collection = None
    get_company_flood_map_feature_collection = None
    get_province_boundaries = None
    get_basin_boundaries = None
    get_latest_rainfall = None
    get_latest_waterlevel = None
    get_latest_dam = None
    get_flood_prediction_map = None


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
    "include_rainfall": True,
    "include_waterlevel": True,
    "include_dam": True,
    "include_prediction": True,
    "include_entity": True,
    "include_policy": True,
    "include_policy_exposure": True,
    "include_linkage": True,
    "include_linkage_lines": True,
    "include_branches": True,
    "include_heatmap": True,
    "heatmap": True,
    "include_boundary": True,
    "include_boundaries": True,
    "include_province_boundary": True,
    "include_province_boundaries": True,
    "include_basin_boundary": True,
    "include_basin_boundaries": True,
    "entity_limit": 500,
    "entity_offset": 0,
    "entity_query": "",
    "prediction_limit": 500,
    "prediction_offset": 0,
    "selected_tax_id": "",
    "selected_director_id": "",
    "selected_province": "",
    "public_mode": False,
    "package_id": "",
}

CACHE_KEYS: Dict[str, str] = {
    "map_layers": "map_layers",
    "map_companies": "map_companies",
    "map_flood": "map_flood",
    "map_rainfall": "map_rainfall",
    "map_waterlevel": "map_waterlevel",
    "map_dam": "map_dam",
    "map_prediction": "map_prediction",
    "map_entity": "map_entity",
    "map_boundaries": "map_boundaries",
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
    if isinstance(context, dict):
        result.update(context)

    result["force_refresh"] = bool(to_bool(result.get("force_refresh"), default=False))
    result["public_mode"] = bool(to_bool(result.get("public_mode"), default=False))

    try:
        result["page"] = max(1, int(result.get("page", 1) or 1))
    except (TypeError, ValueError):
        result["page"] = 1

    try:
        result["page_size"] = max(1, min(5000, int(result.get("page_size", 500) or 500)))
    except (TypeError, ValueError):
        result["page_size"] = 500

    for numeric_key, default_value in [
        ("entity_limit", 500),
        ("entity_offset", 0),
        ("prediction_limit", 500),
        ("prediction_offset", 0),
    ]:
        try:
            result[numeric_key] = max(0, int(result.get(numeric_key, default_value) or default_value))
        except (TypeError, ValueError):
            result[numeric_key] = default_value

    result["search"] = clean_text(result.get("search", ""))
    result["entity_query"] = clean_text(result.get("entity_query", ""))
    result["sort_by"] = clean_text(result.get("sort_by", ""))
    result["sort_dir"] = clean_text_lower(result.get("sort_dir", "asc")) or "asc"
    if result["sort_dir"] not in {"asc", "desc"}:
        result["sort_dir"] = "asc"

    if not isinstance(result.get("filters"), dict):
        result["filters"] = {}

    result["include_boundary"] = bool(
        to_bool(
            result.get("include_boundary", result.get("include_boundaries", True)),
            default=True,
        )
    )
    result["include_boundaries"] = result["include_boundary"]

    result["include_province_boundary"] = bool(
        to_bool(
            result.get("include_province_boundary", result.get("include_province_boundaries", result["include_boundary"])),
            default=True,
        )
    )
    result["include_province_boundaries"] = result["include_province_boundary"]

    result["include_basin_boundary"] = bool(
        to_bool(
            result.get("include_basin_boundary", result.get("include_basin_boundaries", result["include_boundary"])),
            default=True,
        )
    )
    result["include_basin_boundaries"] = result["include_basin_boundary"]

    result["include_policy"] = bool(
        to_bool(
            result.get("include_policy", result.get("include_policy_exposure", True)),
            default=True,
        )
    )
    result["include_policy_exposure"] = result["include_policy"]

    result["include_linkage"] = bool(
        to_bool(
            result.get("include_linkage", result.get("include_linkage_lines", True)),
            default=True,
        )
    )
    result["include_linkage_lines"] = result["include_linkage"]

    result["include_heatmap"] = bool(
        to_bool(
            result.get("include_heatmap", result.get("heatmap", True)),
            default=True,
        )
    )
    result["heatmap"] = result["include_heatmap"]

    for key in [
        "include_companies",
        "include_flood",
        "include_rainfall",
        "include_waterlevel",
        "include_dam",
        "include_prediction",
        "include_entity",
        "include_branches",
    ]:
        result[key] = bool(to_bool(result.get(key, True), default=True))

    result["selected_tax_id"] = normalize_tax_id(result.get("selected_tax_id") or result.get("tax_id") or "")
    result["selected_director_id"] = clean_text(result.get("selected_director_id") or result.get("director_id") or "")
    result["selected_province"] = clean_text(result.get("selected_province") or result.get("province") or "")
    result["package_id"] = clean_text(result.get("package_id", ""))

    return result


def normalize_map_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Public normalizer for map payload callers.
    """

    return normalize_context(context)


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

        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("nodes"), list):
            return data["data"]["nodes"]

        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("edges"), list):
            return data["data"]["edges"]

        if isinstance(data.get("nodes"), list):
            return data["nodes"]

        if isinstance(data.get("edges"), list):
            return data["edges"]

        if isinstance(data.get("layers"), list):
            return data["layers"]

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


def load_policy_exposure_records() -> List[Dict[str, Any]]:
    """
    Load policy exposure records from the available cache variants.
    """

    records = load_records_from_cache("policy_flood_exposure")
    if records:
        return records
    return load_records_from_cache("province_risk_exposure")


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


def load_linkage_records() -> List[Dict[str, Any]]:
    """
    Load linkage line candidate records without rebuilding upstream linkage data.
    """

    links = load_shared_director_links()
    if links:
        return links

    payload = load_linkage_graph_payload()
    for key in ["edges", "links", "records"]:
        if isinstance(payload.get(key), list):
            return payload[key]
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ["edges", "links", "records"]:
            if isinstance(data.get(key), list):
                return data[key]
    return []


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


def load_boundary_records(boundary_type: str) -> List[Dict[str, Any]]:
    """
    Load cached boundary records when flood_spatial_service boundaries are unavailable.
    """

    if boundary_type == "province":
        return load_records_from_cache("province_boundaries")
    if boundary_type == "basin":
        return load_records_from_cache("basin_boundaries")
    return []


# ============================================================
# 4) GEOJSON HELPERS
# ============================================================

COORDINATE_FIELD_PAIRS: List[Tuple[str, str]] = [
    ("lat", "lon"),
    ("latitude", "longitude"),
    ("company_lat", "company_lon"),
    ("company_latitude", "company_longitude"),
    ("dam_latitude", "dam_longitude"),
    ("medium_latitude", "medium_longitude"),
    ("station_latitude", "station_longitude"),
]


def first_present(record: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    """
    Return the first non-empty value from common cache column aliases.
    """

    for key in keys:
        value = record.get(key)
        if not is_empty_value(value):
            return value
    return default


def empty_feature_collection() -> Dict[str, Any]:
    """
    Return a valid empty GeoJSON FeatureCollection.
    """

    return {"type": "FeatureCollection", "features": []}


def safe_feature_collection(value: Any) -> Dict[str, Any]:
    """
    Normalize a raw GeoJSON-like object into a FeatureCollection.
    """

    if isinstance(value, dict) and value.get("type") == "FeatureCollection" and isinstance(value.get("features"), list):
        return {"type": "FeatureCollection", "features": value["features"]}
    if isinstance(value, dict) and isinstance(value.get("features"), list):
        return {"type": "FeatureCollection", "features": value["features"]}
    if isinstance(value, list):
        return {"type": "FeatureCollection", "features": value}
    return empty_feature_collection()


def safe_get_lat_lon(
    record: Dict[str, Any],
    preferred_pairs: Optional[List[Tuple[str, str]]] = None,
) -> Tuple[Optional[float], Optional[float], bool, str]:
    """
    Resolve and validate latitude/longitude from common field pairs.
    """

    pairs = list(preferred_pairs or []) + COORDINATE_FIELD_PAIRS
    seen = set()

    for lat_key, lon_key in pairs:
        if (lat_key, lon_key) in seen:
            continue
        seen.add((lat_key, lon_key))
        lat_value = record.get(lat_key)
        lon_value = record.get(lon_key)
        if is_empty_value(lat_value) or is_empty_value(lon_value):
            continue
        coord = validate_coordinate(lat_value, lon_value)
        if coord.get("valid"):
            return coord.get("lat"), coord.get("lon"), True, ""
        return coord.get("lat"), coord.get("lon"), False, clean_text(coord.get("issue") or coord.get("reason") or "invalid coordinate")

    return None, None, False, "missing coordinate"


def safe_point_feature(
    record: Dict[str, Any],
    properties: Dict[str, Any],
    preferred_pairs: Optional[List[Tuple[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Create a GeoJSON point with [lon, lat] coordinates or return None.
    """

    lat, lon, valid, _issue = safe_get_lat_lon(record, preferred_pairs=preferred_pairs)
    if not valid:
        return None
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": to_jsonable(properties),
    }


def safe_line_feature(
    source_record: Dict[str, Any],
    target_record: Dict[str, Any],
    properties: Dict[str, Any],
    source_pairs: Optional[List[Tuple[str, str]]] = None,
    target_pairs: Optional[List[Tuple[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Create a GeoJSON LineString with [lon, lat] coordinates or return None.
    """

    source_lat, source_lon, source_valid, _source_issue = safe_get_lat_lon(source_record, preferred_pairs=source_pairs)
    target_lat, target_lon, target_valid, _target_issue = safe_get_lat_lon(target_record, preferred_pairs=target_pairs)
    if not source_valid or not target_valid:
        return None
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [source_lon, source_lat],
                [target_lon, target_lat],
            ],
        },
        "properties": to_jsonable(properties),
    }


def make_empty_layer(
    layer_id: str,
    layer_name: str,
    layer_type: str,
    reason: str = "",
    degraded: bool = False,
) -> Dict[str, Any]:
    """
    Return a valid empty layer payload for degraded or missing-source states.
    """

    return build_layer_payload(
        layer_id=layer_id,
        layer_name=layer_name,
        layer_type=layer_type,
        feature_collection=empty_feature_collection(),
        extra={
            "degraded": degraded,
            "reason": reason,
        },
    )


def make_layer(
    layer_id: str,
    layer_name: str,
    layer_type: str,
    features: List[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
    visible: Optional[bool] = None,
    opacity: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Build a standard layer from a list of GeoJSON features.
    """

    return build_layer_payload(
        layer_id=layer_id,
        layer_name=layer_name,
        layer_type=layer_type,
        feature_collection=make_feature_collection(features),
        visible=visible,
        opacity=opacity,
        extra=extra,
    )


def boundary_records_to_feature_collection(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Preserve cached GeoJSON geometries without inventing polygons.
    """

    features = []
    for index, record in enumerate(records):
        geometry = record.get("geometry") or record.get("geojson")
        if isinstance(geometry, dict) and geometry.get("type") in {"Polygon", "MultiPolygon"}:
            properties = {
                key: value
                for key, value in record.items()
                if key not in {"geometry", "geojson"}
            }
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "feature_id": record.get("feature_id") or record.get("id") or f"boundary:{index}",
                        **properties,
                    },
                }
            )
        elif record.get("type") == "Feature" and isinstance(record.get("geometry"), dict):
            features.append(record)
    return make_feature_collection(features)


# ============================================================
# 5) STYLE HELPERS
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
        "rainfall": {
            "renderer": "point",
            "color_field": "risk_level",
            "size_field": "risk_score",
            "label_field": "source_name",
            "marker_shape": "triangle",
            "cluster": True,
            "cluster_distance": 35,
        },
        "waterlevel": {
            "renderer": "point",
            "color_field": "risk_level",
            "size_field": "risk_score",
            "label_field": "source_name",
            "marker_shape": "diamond",
            "cluster": True,
            "cluster_distance": 35,
        },
        "dam": {
            "renderer": "point",
            "color_field": "risk_level",
            "size_field": "risk_score",
            "label_field": "source_name",
            "marker_shape": "hexagon",
            "cluster": True,
            "cluster_distance": 35,
        },
        "prediction": {
            "renderer": "point",
            "color_field": "risk_level",
            "size_field": "risk_score",
            "label_field": "station_name",
            "marker_shape": "circle",
            "cluster": True,
            "cluster_distance": 35,
            "focus_fallback": True,
        },
        "entity": {
            "renderer": "point",
            "color_field": "risk_group",
            "size_field": "marker_size",
            "label_field": "entity_name_th",
            "marker_shape": "square",
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
        "province_boundary": {
            "renderer": "polygon",
            "stroke_color": "#64748b",
            "stroke_width": 1,
            "fill_color": "rgba(100,116,139,0.08)",
        },
        "province_boundaries": {
            "renderer": "polygon",
            "stroke_color": "#64748b",
            "stroke_width": 1,
            "fill_color": "rgba(100,116,139,0.08)",
        },
        "basin_boundary": {
            "renderer": "polygon",
            "stroke_color": "#0ea5e9",
            "stroke_width": 1,
            "fill_color": "rgba(14,165,233,0.06)",
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

    feature = safe_point_feature(
        company,
        properties={
            "feature_id": normalize_tax_id(company.get("tax_id_norm") or company.get("tax_id")),
            "feature_type": "company",
            "tax_id_norm": normalize_tax_id(company.get("tax_id_norm") or company.get("tax_id")),
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

    feature = safe_point_feature(
        record,
        properties={
            "feature_id": record.get("source_key") or f"{record.get('source_type')}:{record.get('source_id')}",
            "feature_type": "flood_source",
            "source_type": record.get("source_type") or "unknown",
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
            "value": first_present(record, ["value", "rainfall_value", "waterlevel_value", "storage_percent"]),
            "unit": record.get("unit"),
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

    feature = safe_point_feature(
        branch,
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

    source_record = {
        "lat": first_present(link, ["source_lat", "from_lat", "company_a_lat"]),
        "lon": first_present(link, ["source_lon", "from_lon", "company_a_lon"]),
    }
    target_record = {
        "lat": first_present(link, ["target_lat", "to_lat", "company_b_lat"]),
        "lon": first_present(link, ["target_lon", "to_lon", "company_b_lon"]),
    }
    source_lat, source_lon, source_valid, _source_issue = safe_get_lat_lon(source_record)
    target_lat, target_lon, target_valid, _target_issue = safe_get_lat_lon(target_record)

    if not source_valid or not target_valid:
        return None

    distance = haversine_km(source_lat, source_lon, target_lat, target_lon)

    risk_level = combine_risk_levels(
        [
            link.get("source_flood_risk_level"),
            link.get("target_flood_risk_level"),
            link.get("combined_flood_risk_level"),
        ]
    )

    source_tax_id = normalize_tax_id(first_present(link, ["source_tax_id", "source_tax_id_norm", "company_a_tax_id", "from_tax_id"]))
    target_tax_id = normalize_tax_id(first_present(link, ["target_tax_id", "target_tax_id_norm", "company_b_tax_id", "to_tax_id"]))

    feature = safe_line_feature(
        source_record,
        target_record,
        properties={
            "feature_id": link.get("link_id") or f"{source_tax_id}:{target_tax_id}",
            "feature_type": "linkage_line",
            "link_id": link.get("link_id"),
            "source_tax_id": source_tax_id,
            "target_tax_id": target_tax_id,
            "source_company": first_present(link, ["source_company", "source_company_name", "company_a_name"]),
            "target_company": first_present(link, ["target_company", "target_company_name", "company_b_name"]),
            "source_company_name": first_present(link, ["source_company_name", "source_company", "company_a_name"]),
            "target_company_name": first_present(link, ["target_company_name", "target_company", "company_b_name"]),
            "shared_directors": link.get("shared_directors", []),
            "shared_director_count": to_number(link.get("shared_director_count"), None) or len(link.get("shared_directors", []) or []),
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
    weight_value = first_present(
        record,
        ["total_suminsure", "total_premium", "most_recent_income_val", "registered_capital"],
        default=1,
    )
    weight = max(1.0, to_number(weight_value, 1) or 1)
    heat_weight = min(1.0, max(0.05, weight / 10_000_000))
    if risk_score > 0:
        heat_weight = max(heat_weight, min(1.0, (risk_score + 1) / 5))

    final_weight = round(heat_weight, 4)

    feature = safe_point_feature(
        record,
        properties={
            "feature_id": record.get("tax_id_norm"),
            "feature_type": "heatmap",
            "tax_id_norm": record.get("tax_id_norm"),
            "company_name": record.get("company_name"),
            "province": record.get("province"),
            "flood_risk_level": normalize_risk_level(record.get("flood_risk_level")),
            "loss_ratio_band": record.get("loss_ratio_band"),
            "total_suminsure": to_number(record.get("total_suminsure"), 0) or 0,
            "weight": weight,
            "metric": "total_suminsure" if not is_empty_value(record.get("total_suminsure")) else "fallback",
            "heat_weight": final_weight,
        },
    )

    return feature


# ============================================================
# 7) LAYER PAYLOAD BUILDERS
# ============================================================

def extract_service_data(payload: Any) -> Any:
    """
    ดึง data จาก service payload แบบ success/message/data/meta/errors
    """

    if isinstance(payload, dict) and "data" in payload and "success" in payload:
        return payload.get("data")

    return payload


def extract_records_from_service_payload(payload: Any) -> List[Dict[str, Any]]:
    """
    ดึง records จาก payload ที่อาจเป็น standard response หรือ raw dict
    """

    data = extract_service_data(payload)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("records"), list):
            return data["records"]

        if isinstance(data.get("features"), list):
            return data["features"]

        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("records"), list):
            return data["data"]["records"]

        if isinstance(data.get("data"), list):
            return data["data"]

    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            return payload["records"]

        if isinstance(payload.get("features"), list):
            return payload["features"]

    return []


def extract_feature_collection_from_service_payload(payload: Any) -> Dict[str, Any]:
    """
    ดึง FeatureCollection จาก service payload
    """

    data = extract_service_data(payload)

    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return safe_feature_collection(data)

    if isinstance(data, dict) and isinstance(data.get("features"), dict):
        return safe_feature_collection(data["features"])

    if isinstance(data, dict) and isinstance(data.get("feature_collection"), dict):
        return safe_feature_collection(data["feature_collection"])

    if isinstance(data, dict) and isinstance(data.get("features"), list):
        return safe_feature_collection(data)

    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        return safe_feature_collection(payload)

    if isinstance(payload, dict) and isinstance(payload.get("features"), dict):
        return safe_feature_collection(payload["features"])

    if isinstance(payload, dict) and isinstance(payload.get("feature_collection"), dict):
        return safe_feature_collection(payload["feature_collection"])

    if isinstance(payload, dict) and isinstance(payload.get("features"), list):
        return safe_feature_collection(payload)

    return empty_feature_collection()


def clone_layer_with_alias(layer: Dict[str, Any], alias_id: str, alias_name: str) -> Dict[str, Any]:
    """
    clone layer payload เป็น alias โดยไม่ rebuild source ซ้ำ
    """

    cloned = dict(layer)
    cloned["layer_id"] = alias_id
    cloned["layer_name"] = alias_name

    if isinstance(cloned.get("meta"), dict):
        cloned["meta"] = {
            **cloned["meta"],
            "alias_of": layer.get("layer_id"),
        }

    return cloned


def get_layer_record_count(layer: Dict[str, Any]) -> int:
    """
    นับ feature ใน layer payload
    """

    if isinstance(layer.get("record_count"), int):
        return layer["record_count"]

    feature_collection = layer.get("feature_collection") or layer.get("features")

    if isinstance(feature_collection, dict) and isinstance(feature_collection.get("features"), list):
        return len(feature_collection["features"])

    return 0


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

    collection = safe_feature_collection(feature_collection)
    features = collection.get("features", [])
    extra_meta = dict(extra or {})
    generated_at = now_iso()
    source = clean_text(extra_meta.pop("source", ""))
    degraded = bool(to_bool(extra_meta.pop("degraded", False), default=False))
    skipped_invalid_coordinates = int(to_number(extra_meta.pop("skipped_invalid_coordinates", 0), 0) or 0)

    payload = {
        "layer_id": layer_id,
        "layer_name": layer_name,
        "layer_type": layer_type,
        "visible": defaults["visible"] if visible is None else bool(visible),
        "opacity": defaults["opacity"] if opacity is None else float(opacity),
        "z_index": defaults["z_index"] if z_index is None else int(z_index),
        "record_count": len(features),
        "features": collection,
        "feature_collection": collection,
        "style": get_layer_style(layer_id),
        "meta": {
            "record_count": len(features),
            "skipped_invalid_coordinates": skipped_invalid_coordinates,
            "degraded": degraded,
            "source": source,
            "generated_at": generated_at,
            "created_at": generated_at,
            **extra_meta,
        },
    }

    return to_jsonable(payload)


def finalize_cached_payload(cache_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Attach cache metadata and ensure public facade payloads are JSON-safe.
    """

    payload = dict(cache_result.get("data") or {})
    if "features" not in payload and "feature_collection" in payload:
        payload["features"] = safe_feature_collection(payload.get("feature_collection"))
    if "feature_collection" not in payload and "features" in payload:
        payload["feature_collection"] = safe_feature_collection(payload.get("features"))
    if "record_count" not in payload and isinstance(payload.get("features"), dict):
        payload["record_count"] = len(payload["features"].get("features", []))
    if isinstance(payload.get("features"), dict) and not isinstance(payload.get("meta"), dict):
        payload["meta"] = {
            "record_count": payload.get("record_count", 0),
            "skipped_invalid_coordinates": 0,
            "degraded": False,
            "source": "",
            "generated_at": now_iso(),
        }
    payload["cache_used"] = bool(cache_result.get("cache_used", False))
    if isinstance(payload.get("meta"), dict):
        payload["meta"]["cache_used"] = payload["cache_used"]
    return to_jsonable(payload)


def build_company_points_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง company_points layer
    """

    ctx = normalize_context(context)

    companies = load_company_records()
    companies = filter_company_records(companies, ctx)

    features = []
    skipped_invalid_coordinates = 0

    for company in companies:
        feature = build_company_feature(company)
        if feature:
            features.append(feature)
        else:
            skipped_invalid_coordinates += 1

    return build_layer_payload(
        layer_id="company_points",
        layer_name="Company Points",
        layer_type="point",
        feature_collection=make_feature_collection(features),
        extra={
            "source": "company_unified_master",
            "company_count": len(companies),
            "skipped_invalid_coordinates": skipped_invalid_coordinates,
            "degraded": not bool(companies),
            "reason": "company source missing or empty" if not companies else "",
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
    skipped_invalid_coordinates = 0

    for record in flood_records:
        feature = build_flood_feature(record)
        if feature:
            features.append(feature)
        else:
            skipped_invalid_coordinates += 1

    return build_layer_payload(
        layer_id="flood_points",
        layer_name="Flood Sources",
        layer_type="point",
        feature_collection=make_feature_collection(features),
        extra={
            "source": "flood_computed_risk",
            "flood_count": len(flood_records),
            "skipped_invalid_coordinates": skipped_invalid_coordinates,
            "degraded": not bool(flood_records),
            "reason": "flood source missing or empty" if not flood_records else "",
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
    ]

    if not companies:
        companies = [
            record
            for record in load_spatial_records()
            if to_bool(record.get("has_policy"), default=False)
            or not is_empty_value(record.get("total_suminsure"))
            or not is_empty_value(record.get("total_premium"))
        ]

    companies = filter_company_records(companies, ctx)

    features = []
    skipped_invalid_coordinates = 0

    for company in companies:
        feature = build_company_feature(company)
        if feature:
            feature["properties"]["feature_type"] = "policy_exposure"
            feature["properties"]["exposure_size"] = feature["properties"].get("marker_size")
            feature["properties"]["exposure_color"] = feature["properties"].get("marker_color")
            features.append(feature)
        else:
            skipped_invalid_coordinates += 1

    return build_layer_payload(
        layer_id="policy_exposure",
        layer_name="Policy Exposure",
        layer_type="point",
        feature_collection=make_feature_collection(features),
        extra={
            "source": "company_unified_master",
            "company_count": len(companies),
            "skipped_invalid_coordinates": skipped_invalid_coordinates,
            "degraded": not bool(features),
            "reason": "point-level policy exposure source missing or empty" if not features else "",
        },
    )


def build_linkage_lines_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง linkage_lines layer จาก shared_director_links
    """

    ctx = normalize_context(context)

    links = load_linkage_records()

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

    company_lookup = {}
    for company in load_company_records():
        tax_id = normalize_tax_id(company.get("tax_id_norm") or company.get("tax_id"))
        if tax_id:
            company_lookup[tax_id] = company

    features = []
    skipped_invalid_coordinates = 0
    seen_pairs = set()

    for link in links:
        source_tax_id = normalize_tax_id(first_present(link, ["source_tax_id", "source_tax_id_norm", "company_a_tax_id", "from_tax_id"]))
        target_tax_id = normalize_tax_id(first_present(link, ["target_tax_id", "target_tax_id_norm", "company_b_tax_id", "to_tax_id"]))

        if not source_tax_id or not target_tax_id or source_tax_id == target_tax_id:
            skipped_invalid_coordinates += 1
            continue

        pair_key = tuple(sorted([source_tax_id, target_tax_id]))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        source_company = company_lookup.get(source_tax_id, {})
        target_company = company_lookup.get(target_tax_id, {})
        if source_company:
            link = {
                **link,
                "source_lat": first_present(link, ["source_lat", "from_lat", "company_a_lat"], source_company.get("lat")),
                "source_lon": first_present(link, ["source_lon", "from_lon", "company_a_lon"], source_company.get("lon")),
                "source_company_name": first_present(link, ["source_company_name", "source_company", "company_a_name"], source_company.get("company_name")),
                "source_province": first_present(link, ["source_province", "company_a_province"], source_company.get("province")),
            }
        if target_company:
            link = {
                **link,
                "target_lat": first_present(link, ["target_lat", "to_lat", "company_b_lat"], target_company.get("lat")),
                "target_lon": first_present(link, ["target_lon", "to_lon", "company_b_lon"], target_company.get("lon")),
                "target_company_name": first_present(link, ["target_company_name", "target_company", "company_b_name"], target_company.get("company_name")),
                "target_province": first_present(link, ["target_province", "company_b_province"], target_company.get("province")),
            }

        feature = build_linkage_line_feature(link)
        if feature:
            features.append(feature)
        else:
            skipped_invalid_coordinates += 1

    return build_layer_payload(
        layer_id="linkage_lines",
        layer_name="Shared Director Lines",
        layer_type="line",
        feature_collection=make_feature_collection(features),
        extra={
            "source": "shared_director_links",
            "link_count": len(links),
            "skipped_invalid_coordinates": skipped_invalid_coordinates,
            "degraded": not bool(features),
            "reason": "linkage source missing or no valid company-company coordinates" if not features else "",
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
    skipped_invalid_coordinates = 0

    for branch in branches:
        feature = build_branch_feature(branch)
        if feature:
            features.append(feature)
        else:
            skipped_invalid_coordinates += 1

    return build_layer_payload(
        layer_id="branch_points",
        layer_name="Branch / Province Fallback Points",
        layer_type="point",
        feature_collection=make_feature_collection(features),
        visible=False,
        extra={
            "source": "province_branch_coordinate_master",
            "branch_count": len(branches),
            "skipped_invalid_coordinates": skipped_invalid_coordinates,
            "degraded": not bool(branches),
            "reason": "branch source missing or empty" if not branches else "",
        },
    )


def build_heatmap_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง heatmap layer จาก company exposure
    """

    ctx = normalize_context(context)

    companies = load_company_records()

    companies = filter_company_records(companies, ctx)

    features = []
    skipped_invalid_coordinates = 0

    for company in companies:
        feature = build_heatmap_feature(company)
        if feature:
            features.append(feature)
        else:
            skipped_invalid_coordinates += 1

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
            "skipped_invalid_coordinates": skipped_invalid_coordinates,
            "degraded": not bool(companies),
            "reason": "company source missing or empty" if not companies else "",
        },
    )


def build_province_boundaries_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง province boundary layer
    """

    if get_province_boundaries is not None:
        try:
            boundary = get_province_boundaries()
            feature_collection = safe_feature_collection(boundary)
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
        except Exception as exc:
            return build_layer_payload(
                layer_id="province_boundaries",
                layer_name="Province Boundaries",
                layer_type="polygon",
                feature_collection=empty_feature_collection(),
                visible=False,
                opacity=0.7,
                extra={
                    "source": "flood_spatial_service",
                    "degraded": True,
                    "reason": "province boundary service failed",
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                },
            )

    cached_records = load_boundary_records("province")
    if cached_records:
        return build_layer_payload(
            layer_id="province_boundaries",
            layer_name="Province Boundaries",
            layer_type="polygon",
            feature_collection=boundary_records_to_feature_collection(cached_records),
            visible=False,
            opacity=0.7,
            extra={
                "source": "province_boundaries",
                "record_count_raw": len(cached_records),
                "degraded": False,
            },
        )

    return build_layer_payload(
        layer_id="province_boundaries",
        layer_name="Province Boundaries",
        layer_type="polygon",
        feature_collection=make_feature_collection([]),
        visible=False,
        opacity=0.7,
        extra={
            "source": "",
            "degraded": True,
            "reason": "province boundary source missing or empty",
        },
    )


def build_basin_boundaries_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง basin boundary layer
    """

    if get_basin_boundaries is not None:
        try:
            boundary = get_basin_boundaries()
            feature_collection = safe_feature_collection(boundary)
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
        except Exception as exc:
            return build_layer_payload(
                layer_id="basin_boundaries",
                layer_name="Basin Boundaries",
                layer_type="polygon",
                feature_collection=empty_feature_collection(),
                visible=False,
                opacity=0.7,
                extra={
                    "source": "flood_spatial_service",
                    "degraded": True,
                    "reason": "basin boundary service failed",
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                },
            )

    cached_records = load_boundary_records("basin")
    if cached_records:
        return build_layer_payload(
            layer_id="basin_boundaries",
            layer_name="Basin Boundaries",
            layer_type="polygon",
            feature_collection=boundary_records_to_feature_collection(cached_records),
            visible=False,
            opacity=0.7,
            extra={
                "source": "basin_boundaries",
                "record_count_raw": len(cached_records),
                "degraded": False,
            },
        )

    return build_layer_payload(
        layer_id="basin_boundaries",
        layer_name="Basin Boundaries",
        layer_type="polygon",
        feature_collection=make_feature_collection([]),
        visible=False,
        opacity=0.7,
        extra={
            "source": "",
            "degraded": True,
            "reason": "basin boundary source missing or empty",
        },
    )


# ============================================================
# 8) API LAYER FUNCTIONS
# ============================================================

def build_flood_runtime_records_layer(
    context: Optional[Dict[str, Any]],
    layer_id: str,
    layer_name: str,
    source_type: str,
    service_func: Any,
) -> Dict[str, Any]:
    """
    สร้าง rainfall/waterlevel/dam layer จาก flood_spatial_service
    """

    ctx = normalize_context(context)

    if service_func is None:
        return make_empty_layer(
            layer_id=layer_id,
            layer_name=layer_name,
            layer_type="point",
            reason="flood runtime service unavailable",
            degraded=True,
        )

    try:
        payload = service_func(context=ctx)
        records = extract_records_from_service_payload(payload)

        features: List[Dict[str, Any]] = []
        skipped_invalid_coordinates = 0

        for record in records:
            normalized_record = {
                **record,
                "source_type": record.get("source_type") or source_type,
            }
            feature = build_flood_feature(normalized_record)

            if feature:
                feature["properties"]["feature_type"] = layer_id
                feature["properties"]["object_type"] = source_type
                features.append(feature)
            else:
                skipped_invalid_coordinates += 1

        return build_layer_payload(
            layer_id=layer_id,
            layer_name=layer_name,
            layer_type="point",
            feature_collection=make_feature_collection(features),
            extra={
                "source": "excel",
                "upstream_service": f"flood_spatial_service.{getattr(service_func, '__name__', '')}",
                "upstream_cache_keys": [f"flood_{source_type}_latest"],
                "raw_record_count": len(records),
                "skipped_invalid_coordinates": skipped_invalid_coordinates,
                "degraded": not bool(features),
                "reason": f"{layer_id} source missing or empty" if not features else "",
            },
        )

    except Exception as exc:
        return make_empty_layer(
            layer_id=layer_id,
            layer_name=layer_name,
            layer_type="point",
            reason=str(exc),
            degraded=True,
        )


def build_rainfall_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return build_flood_runtime_records_layer(
        context=context,
        layer_id="rainfall",
        layer_name="Rainfall",
        source_type="rainfall",
        service_func=get_latest_rainfall,
    )


def build_waterlevel_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return build_flood_runtime_records_layer(
        context=context,
        layer_id="waterlevel",
        layer_name="Water Level",
        source_type="waterlevel",
        service_func=get_latest_waterlevel,
    )


def build_dam_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return build_flood_runtime_records_layer(
        context=context,
        layer_id="dam",
        layer_name="Dam Storage",
        source_type="dam",
        service_func=get_latest_dam,
    )


def build_prediction_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง prediction layer จาก flood_spatial_service.get_flood_prediction_map()
    """

    ctx = normalize_context(context)

    if get_flood_prediction_map is None:
        return make_empty_layer(
            layer_id="prediction",
            layer_name="Flood Prediction",
            layer_type="point",
            reason="prediction service unavailable",
            degraded=True,
        )

    try:
        prediction_context = {
            **ctx,
            "limit": ctx.get("prediction_limit"),
            "offset": ctx.get("prediction_offset"),
            "page_size": ctx.get("prediction_limit"),
        }

        payload = get_flood_prediction_map(context=prediction_context)
        feature_collection = extract_feature_collection_from_service_payload(payload)
        data = extract_service_data(payload)

        fallback_focus = []
        if isinstance(data, dict):
            fallback_focus = data.get("fallback_focus", []) or []

        return build_layer_payload(
            layer_id="prediction",
            layer_name="Flood Prediction",
            layer_type="point",
            feature_collection=feature_collection,
            extra={
                "source": "excel",
                "upstream_service": "flood_spatial_service.get_flood_prediction_map",
                "upstream_cache_keys": ["flood_prediction_map", "flood_prediction_latest"],
                "fallback_focus": fallback_focus,
                "fallback_focus_count": len(fallback_focus),
                "record_count_raw": len(feature_collection.get("features", [])),
                "degraded": False,
            },
        )

    except Exception as exc:
        return make_empty_layer(
            layer_id="prediction",
            layer_name="Flood Prediction",
            layer_type="point",
            reason=str(exc),
            degraded=True,
        )


def build_entity_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง entity layer จาก entity_upload_service.get_latest_entity_map_features()
    """

    ctx = normalize_context(context)

    try:
        import entity_upload_service

        payload = entity_upload_service.get_latest_entity_map_features(
            province=ctx.get("selected_province") or None,
            risk_level=ctx.get("filters", {}).get("risk_level") if isinstance(ctx.get("filters"), dict) else None,
            query=ctx.get("entity_query") or ctx.get("search") or None,
            limit=ctx.get("entity_limit"),
            offset=ctx.get("entity_offset"),
            context=ctx,
        )

        feature_collection = extract_feature_collection_from_service_payload(payload)
        data = extract_service_data(payload)
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}

        return build_layer_payload(
            layer_id="entity",
            layer_name="Uploaded Entity Overlay",
            layer_type="point",
            feature_collection=feature_collection,
            extra={
                "source": "uploaded_entity",
                "upstream_service": "entity_upload_service.get_latest_entity_map_features",
                "upstream_cache_keys": ["uploaded_entity_latest"],
                "upload_id": meta.get("upload_id") if isinstance(meta, dict) else None,
                "updated_at": meta.get("updated_at") if isinstance(meta, dict) else None,
                "record_count_raw": data.get("total") if isinstance(data, dict) else len(feature_collection.get("features", [])),
                "degraded": False,
            },
        )

    except Exception as exc:
        return make_empty_layer(
            layer_id="entity",
            layer_name="Uploaded Entity Overlay",
            layer_type="point",
            reason=str(exc),
            degraded=True,
        )


def build_province_boundary_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    layer = build_province_boundaries_layer(context)
    return clone_layer_with_alias(layer, "province_boundary", "Province Boundary")


def build_basin_boundary_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    layer = build_basin_boundaries_layer(context)
    return clone_layer_with_alias(layer, "basin_boundary", "Basin Boundary")


def get_map_prediction(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/prediction
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_prediction_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_prediction"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_prediction",
    )

    return finalize_cached_payload(cache_result)


def get_map_entity(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/entity
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_entity_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_entity"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_entity",
    )

    return finalize_cached_payload(cache_result)


def get_map_boundaries(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/boundaries
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        province_layer = build_province_boundary_layer(ctx)
        basin_layer = build_basin_boundary_layer(ctx)

        return {
            "layers": {
                "province_boundary": province_layer,
                "basin_boundary": basin_layer,
                "province_boundaries": clone_layer_with_alias(province_layer, "province_boundaries", "Province Boundaries"),
                "basin_boundaries": clone_layer_with_alias(basin_layer, "basin_boundaries", "Basin Boundaries"),
            },
            "layer_order": [
                "province_boundary",
                "basin_boundary",
                "province_boundaries",
                "basin_boundaries",
            ],
            "summary": {
                "layer_count": 4,
                "feature_count": get_layer_record_count(province_layer) + get_layer_record_count(basin_layer),
                "generated_at": now_iso(),
            },
        }

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_boundaries"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_boundaries",
    )

    return to_jsonable(
        {
            **dict(cache_result.get("data") or {}),
            "cache_used": cache_result.get("cache_used", False),
        }
    )

def get_map_layers(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/layers

    คืน layer ทั้งหมดที่ OpenLayers ต้องใช้
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        layer_builders = [
            (
                "province_boundary",
                bool(ctx.get("include_boundary") and ctx.get("include_province_boundary")),
                build_province_boundary_layer,
                "Province Boundary",
                "polygon",
            ),
            (
                "basin_boundary",
                bool(ctx.get("include_boundary") and ctx.get("include_basin_boundary")),
                build_basin_boundary_layer,
                "Basin Boundary",
                "polygon",
            ),
            ("rainfall", bool(ctx.get("include_rainfall") and ctx.get("include_flood")), build_rainfall_layer, "Rainfall", "point"),
            ("waterlevel", bool(ctx.get("include_waterlevel") and ctx.get("include_flood")), build_waterlevel_layer, "Water Level", "point"),
            ("dam", bool(ctx.get("include_dam") and ctx.get("include_flood")), build_dam_layer, "Dam Storage", "point"),
            ("prediction", bool(ctx.get("include_prediction")), build_prediction_layer, "Flood Prediction", "point"),
            ("entity", bool(ctx.get("include_entity")), build_entity_layer, "Uploaded Entity Overlay", "point"),
            ("flood_points", bool(ctx.get("include_flood")), build_flood_points_layer, "Flood Sources", "point"),
            ("policy_exposure", bool(ctx.get("include_policy_exposure")), build_policy_exposure_layer, "Policy Exposure", "point"),
            ("company_points", bool(ctx.get("include_companies")), build_company_points_layer, "Company Points", "point"),
            ("branch_points", bool(ctx.get("include_branches")), build_branch_points_layer, "Branch / Province Fallback Points", "point"),
            ("heatmap", bool(ctx.get("include_heatmap")), build_heatmap_layer, "Exposure Heatmap", "heatmap"),
            ("linkage_lines", bool(ctx.get("include_linkage_lines")), build_linkage_lines_layer, "Shared Director Lines", "line"),
        ]

        layers_by_id: Dict[str, Dict[str, Any]] = {}
        errors: List[Dict[str, Any]] = []

        for layer_id, enabled, layer_builder, layer_name, layer_type in layer_builders:
            if not enabled:
                continue

            try:
                layers_by_id[layer_id] = layer_builder(ctx)
            except Exception as exc:
                layers_by_id[layer_id] = make_empty_layer(
                    layer_id=layer_id,
                    layer_name=layer_name,
                    layer_type=layer_type,
                    reason=str(exc),
                    degraded=True,
                )
                errors.append(
                    {
                        "layer_id": layer_id,
                        "error_type": exc.__class__.__name__,
                        "message": str(exc),
                    }
                )

        if "province_boundary" in layers_by_id:
            layers_by_id["province_boundaries"] = clone_layer_with_alias(
                layers_by_id["province_boundary"],
                "province_boundaries",
                "Province Boundaries",
            )

        if "basin_boundary" in layers_by_id:
            layers_by_id["basin_boundaries"] = clone_layer_with_alias(
                layers_by_id["basin_boundary"],
                "basin_boundaries",
                "Basin Boundaries",
            )

        canonical_layer_order = [
            layer_id
            for layer_id in DEFAULT_LAYER_ORDER
            if layer_id in layers_by_id
        ]

        compatibility_layer_order = [
            "province_boundaries",
            "basin_boundaries",
        ]

        layer_order = canonical_layer_order + [
            layer_id
            for layer_id in compatibility_layer_order
            if layer_id in layers_by_id and layer_id not in canonical_layer_order
        ]

        layer_list = [
            layers_by_id[layer_id]
            for layer_id in layer_order
        ]

        counts = {
            layer_id: get_layer_record_count(layer)
            for layer_id, layer in layers_by_id.items()
        }

        record_count = sum(counts.get(layer_id, 0) for layer_id in canonical_layer_order)
        degraded = bool(errors) or any(layer.get("meta", {}).get("degraded") for layer in layer_list)
        generated_at = now_iso()

        return {
            "map": {
                "center": MAP_DEFAULT_CENTER,
                "zoom": MAP_DEFAULT_ZOOM,
                "min_zoom": MAP_MIN_ZOOM,
                "max_zoom": MAP_MAX_ZOOM,
                "base_tile_url": MAP_BASE_TILE_URL,
                "base_attribution": MAP_BASE_ATTRIBUTION,
            },
            "center": MAP_DEFAULT_CENTER,
            "zoom": MAP_DEFAULT_ZOOM,
            "min_zoom": MAP_MIN_ZOOM,
            "max_zoom": MAP_MAX_ZOOM,
            "base_tile_url": MAP_BASE_TILE_URL,
            "base_attribution": MAP_BASE_ATTRIBUTION,
            "layers": layers_by_id,
            "layers_by_id": layers_by_id,
            "layer_order": layer_order,
            "layer_list": layer_list,
            "summary": {
                "layer_count": len(layer_order),
                "feature_count": record_count,
                "record_count": record_count,
                "record_count_by_layer": counts,
                "generated_at": generated_at,
                "degraded": degraded,
            },
            "meta": {
                "source": "excel" if getattr(config, "USE_EXCEL_DATA_SOURCE", True) else "mysql",
                "generated_at": generated_at,
                "layer_count": len(layer_order),
                "record_count": record_count,
                "counts": counts,
                "record_count_by_layer": counts,
                "filters": ctx.get("filters", {}),
                "upstream_cache_keys": [
                    "flood_rainfall_latest",
                    "flood_waterlevel_latest",
                    "flood_large_dam_latest",
                    "flood_medium_dam_latest",
                    "flood_prediction_map",
                    "uploaded_entity_latest",
                    "company_unified_master",
                    "policy_flood_exposure",
                    "linkage_graph_payload",
                    "shared_director_links",
                ],
                "degraded": degraded,
                "errors": errors,
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

    data = dict(cache_result.get("data") or {})
    if not isinstance(data.get("layers"), dict):
        data = builder()

    payload = {
        **data,
        "cache_used": cache_result["cache_used"],
    }

    if isinstance(payload.get("meta"), dict):
        payload["meta"]["cache_used"] = cache_result["cache_used"]

    return to_jsonable(payload)

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

    return finalize_cached_payload(cache_result)


def get_map_rainfall(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/rainfall
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_rainfall_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_rainfall"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_rainfall",
    )

    return finalize_cached_payload(cache_result)


def get_map_waterlevel(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/waterlevel
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_waterlevel_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_waterlevel"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_waterlevel",
    )

    return finalize_cached_payload(cache_result)


def get_map_dam(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/dam
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        return build_dam_layer(ctx)

    cache_result = get_or_build_cache(
        cache_key=CACHE_KEYS["map_dam"],
        builder=builder,
        ttl_seconds=get_map_ttl(),
        force_refresh=ctx.get("force_refresh", False),
        source="map_graph_service.get_map_dam",
    )

    return finalize_cached_payload(cache_result)


def get_map_entities(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API alias:
    GET /api/map/entities
    """

    return get_map_entity(context)


def get_map_prediction_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_prediction(context)


def get_map_entity_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_entity(context)

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

    return finalize_cached_payload(cache_result)


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

    return finalize_cached_payload(cache_result)


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

    return finalize_cached_payload(cache_result)


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

    return finalize_cached_payload(cache_result)


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

    return finalize_cached_payload(cache_result)


# ============================================================
# 9) FULL MAP LAYERS
# ============================================================

def get_map_layers(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    API:
    GET /api/map/layers

    คืน merged layer contract สำหรับ OpenLayers:
    rainfall / waterlevel / dam / prediction / entity / boundary / company / policy / linkage
    """

    ctx = normalize_context(context)

    def builder() -> Dict[str, Any]:
        layer_builders = [
            (
                "province_boundary",
                bool(ctx.get("include_boundary") and ctx.get("include_province_boundary")),
                build_province_boundary_layer,
                "Province Boundary",
                "polygon",
            ),
            (
                "basin_boundary",
                bool(ctx.get("include_boundary") and ctx.get("include_basin_boundary")),
                build_basin_boundary_layer,
                "Basin Boundary",
                "polygon",
            ),
            (
                "rainfall",
                bool(ctx.get("include_flood") and ctx.get("include_rainfall")),
                build_rainfall_layer,
                "Rainfall",
                "point",
            ),
            (
                "waterlevel",
                bool(ctx.get("include_flood") and ctx.get("include_waterlevel")),
                build_waterlevel_layer,
                "Water Level",
                "point",
            ),
            (
                "dam",
                bool(ctx.get("include_flood") and ctx.get("include_dam")),
                build_dam_layer,
                "Dam Storage",
                "point",
            ),
            (
                "prediction",
                bool(ctx.get("include_prediction")),
                build_prediction_layer,
                "Flood Prediction",
                "point",
            ),
            (
                "entity",
                bool(ctx.get("include_entity")),
                build_entity_layer,
                "Uploaded Entity Overlay",
                "point",
            ),
            (
                "flood_points",
                bool(ctx.get("include_flood")),
                build_flood_points_layer,
                "Flood Sources",
                "point",
            ),
            (
                "policy_exposure",
                bool(ctx.get("include_policy_exposure")),
                build_policy_exposure_layer,
                "Policy Exposure",
                "point",
            ),
            (
                "company_points",
                bool(ctx.get("include_companies")),
                build_company_points_layer,
                "Company Points",
                "point",
            ),
            (
                "branch_points",
                bool(ctx.get("include_branches")),
                build_branch_points_layer,
                "Branch / Province Fallback Points",
                "point",
            ),
            (
                "heatmap",
                bool(ctx.get("include_heatmap")),
                build_heatmap_layer,
                "Exposure Heatmap",
                "heatmap",
            ),
            (
                "linkage_lines",
                bool(ctx.get("include_linkage_lines")),
                build_linkage_lines_layer,
                "Shared Director Lines",
                "line",
            ),
        ]

        layers_by_id: Dict[str, Dict[str, Any]] = {}
        errors: List[Dict[str, Any]] = []

        for layer_id, enabled, layer_builder, layer_name, layer_type in layer_builders:
            if not enabled:
                continue

            try:
                layer = layer_builder(ctx)
                if not isinstance(layer, dict):
                    layer = make_empty_layer(
                        layer_id=layer_id,
                        layer_name=layer_name,
                        layer_type=layer_type,
                        reason="layer builder returned invalid payload",
                        degraded=True,
                    )
                layers_by_id[layer_id] = layer
            except Exception as exc:
                layers_by_id[layer_id] = make_empty_layer(
                    layer_id=layer_id,
                    layer_name=layer_name,
                    layer_type=layer_type,
                    reason=str(exc),
                    degraded=True,
                )
                errors.append(
                    {
                        "layer_id": layer_id,
                        "error_type": exc.__class__.__name__,
                        "message": str(exc),
                    }
                )

        if "province_boundary" in layers_by_id:
            layers_by_id["province_boundaries"] = clone_layer_with_alias(
                layers_by_id["province_boundary"],
                "province_boundaries",
                "Province Boundaries",
            )

        if "basin_boundary" in layers_by_id:
            layers_by_id["basin_boundaries"] = clone_layer_with_alias(
                layers_by_id["basin_boundary"],
                "basin_boundaries",
                "Basin Boundaries",
            )

        canonical_layer_order = [
            layer_id
            for layer_id in DEFAULT_LAYER_ORDER
            if layer_id in layers_by_id
        ]

        compatibility_layer_order = [
            layer_id
            for layer_id in [
                "province_boundaries",
                "basin_boundaries",
            ]
            if layer_id in layers_by_id and layer_id not in canonical_layer_order
        ]

        layer_order = canonical_layer_order + compatibility_layer_order

        layer_list = [
            layers_by_id[layer_id]
            for layer_id in layer_order
            if layer_id in layers_by_id
        ]

        counts = {
            layer_id: get_layer_record_count(layer)
            for layer_id, layer in layers_by_id.items()
        }

        canonical_record_count = sum(
            counts.get(layer_id, 0)
            for layer_id in canonical_layer_order
        )

        total_feature_count = sum(
            counts.get(layer_id, 0)
            for layer_id in layer_order
        )

        degraded_layer_ids = [
            layer_id
            for layer_id, layer in layers_by_id.items()
            if isinstance(layer.get("meta"), dict) and layer["meta"].get("degraded")
        ]

        generated_at = now_iso()
        degraded = bool(errors or degraded_layer_ids)

        return {
            "map": {
                "center": MAP_DEFAULT_CENTER,
                "zoom": MAP_DEFAULT_ZOOM,
                "min_zoom": MAP_MIN_ZOOM,
                "max_zoom": MAP_MAX_ZOOM,
                "base_tile_url": MAP_BASE_TILE_URL,
                "base_attribution": MAP_BASE_ATTRIBUTION,
            },
            "center": MAP_DEFAULT_CENTER,
            "zoom": MAP_DEFAULT_ZOOM,
            "min_zoom": MAP_MIN_ZOOM,
            "max_zoom": MAP_MAX_ZOOM,
            "base_tile_url": MAP_BASE_TILE_URL,
            "base_attribution": MAP_BASE_ATTRIBUTION,
            "layers": layers_by_id,
            "layers_by_id": layers_by_id,
            "layer_order": layer_order,
            "layer_list": layer_list,
            "layers_list": layer_list,
            "legacy_layers": layer_list,
            "summary": {
                "layer_count": len(layer_order),
                "canonical_layer_count": len(canonical_layer_order),
                "feature_count": total_feature_count,
                "record_count": canonical_record_count,
                "record_count_by_layer": counts,
                "enabled_layers": canonical_layer_order,
                "compatibility_layers": compatibility_layer_order,
                "degraded_layer_ids": degraded_layer_ids,
                "generated_at": generated_at,
                "degraded": degraded,
            },
            "meta": {
                "source": "excel" if getattr(config, "USE_EXCEL_DATA_SOURCE", True) else "mysql",
                "generated_at": generated_at,
                "created_at": generated_at,
                "layer_count": len(layer_order),
                "canonical_layer_count": len(canonical_layer_order),
                "feature_count": total_feature_count,
                "record_count": canonical_record_count,
                "counts": counts,
                "record_count_by_layer": counts,
                "filters": ctx.get("filters", {}),
                "upstream_cache_keys": [
                    "flood_rainfall_latest",
                    "flood_waterlevel_latest",
                    "flood_large_dam_latest",
                    "flood_medium_dam_latest",
                    "flood_prediction_map",
                    "flood_prediction_latest",
                    "uploaded_entity_latest",
                    "company_unified_master",
                    "policy_flood_exposure",
                    "linkage_graph_payload",
                    "shared_director_links",
                    "province_boundaries",
                    "basin_boundaries",
                ],
                "degraded": degraded,
                "degraded_layer_ids": degraded_layer_ids,
                "errors": errors,
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

    data = dict(cache_result.get("data") or {})

    if not isinstance(data.get("layers"), dict):
        data = builder()

    payload = {
        **data,
        "cache_used": cache_result["cache_used"],
    }

    if isinstance(payload.get("meta"), dict):
        payload["meta"]["cache_used"] = cache_result["cache_used"]

    return to_jsonable(payload)

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
    feature_type = clean_text(ctx.get("feature_type") or ctx.get("object_type") or "")
    feature_id = clean_text(ctx.get("feature_id") or ctx.get("record_key") or "")

    result: Dict[str, Any] = {
        "selected": {
            "tax_id_norm": selected_tax_id,
            "director_id": selected_director_id,
            "province": selected_province,
            "feature_type": feature_type,
            "feature_id": feature_id,
        },
        "company": {},
        "director": {},
        "province": {},
        "spatial": {},
        "prediction": {},
        "entity": {},
        "nearby": {
            "companies": [],
            "flood_sources": [],
        },
        "nearby_companies": [],
        "nearby_flood_sources": [],
        "linkage_lines": [],
        "province_context": {},
        "map_focus": {
            "center": MAP_DEFAULT_CENTER,
            "zoom": 8,
            "focus_level": "default",
            "focus_fallback": None,
        },
        "meta": {
            "found": False,
            "generated_at": now_iso(),
            "degraded": False,
        },
    }

    if selected_tax_id:
        company = find_company_by_tax_id(selected_tax_id)
        spatial = find_spatial_by_tax_id(selected_tax_id)

        result["company"] = company or {}
        result["spatial"] = spatial or {}
        result["meta"]["found"] = bool(company or spatial)

        if company:
            lat, lon, valid, issue = safe_get_lat_lon(company)

            if valid:
                result["map_focus"] = {
                    "center": [lon, lat],
                    "zoom": 12,
                    "focus_level": "point",
                    "focus_fallback": None,
                }

                result["nearby_companies"] = find_nearby_companies(
                    origin_company=company,
                    limit=20,
                    max_distance_km=50,
                )

                result["nearby_flood_sources"] = find_nearby_flood_sources(
                    lat=lat,
                    lon=lon,
                    limit=20,
                    max_distance_km=80,
                )
            else:
                province = clean_text(company.get("province") or selected_province)
                result["map_focus"] = {
                    "center": MAP_DEFAULT_CENTER,
                    "zoom": 8,
                    "focus_level": "province_boundary" if province else "default",
                    "focus_fallback": {
                        "type": "province_boundary",
                        "province": province,
                        "reason": issue,
                    } if province else None,
                }

        result["linkage_lines"] = [
            link
            for link in load_shared_director_links()
            if normalize_tax_id(link.get("source_tax_id")) == selected_tax_id
            or normalize_tax_id(link.get("target_tax_id")) == selected_tax_id
        ]

        result["nearby"] = {
            "companies": result["nearby_companies"],
            "flood_sources": result["nearby_flood_sources"],
        }

    if selected_director_id:
        director_links = [
            link
            for link in load_linkage_records()
            if clean_text(link.get("director_id") or link.get("person_id")) == selected_director_id
            or selected_director_id in clean_text(link.get("shared_directors_text"))
        ]
        result["director"] = {
            "director_id": selected_director_id,
            "connected_link_count": len(director_links),
            "connected_links": director_links[:50],
        }
        result["meta"]["found"] = result["meta"]["found"] or bool(director_links)

    if selected_province:
        province_context = build_province_context(selected_province)
        result["province_context"] = province_context
        result["province"] = province_context
        result["map_focus"] = {
            **result["map_focus"],
            "focus_level": "province_boundary",
            "focus_fallback": {
                "type": "province_boundary",
                "province": selected_province,
            },
        }
        result["meta"]["found"] = result["meta"]["found"] or bool(province_context)

    if feature_type in {"prediction", "forecast", "flood_prediction"} and feature_id:
        try:
            prediction_layer = build_prediction_layer(ctx)
            features = prediction_layer.get("feature_collection", {}).get("features", [])
            matched = [
                feature
                for feature in features
                if clean_text(feature.get("properties", {}).get("record_key")) == feature_id
                or clean_text(feature.get("properties", {}).get("feature_id")) == feature_id
            ]
            result["prediction"] = matched[0].get("properties", {}) if matched else {}
            result["meta"]["found"] = result["meta"]["found"] or bool(matched)

            if matched:
                properties = matched[0].get("properties", {})
                geometry = matched[0].get("geometry")

                if isinstance(geometry, dict) and geometry.get("type") == "Point":
                    coordinates = geometry.get("coordinates", [])
                    if len(coordinates) >= 2:
                        result["map_focus"] = {
                            "center": [coordinates[0], coordinates[1]],
                            "zoom": 12,
                            "focus_level": "point",
                            "focus_fallback": None,
                        }
                elif properties.get("focus_fallback"):
                    result["map_focus"] = {
                        "center": MAP_DEFAULT_CENTER,
                        "zoom": 8,
                        "focus_level": properties.get("focus_level") or "province_boundary",
                        "focus_fallback": properties.get("focus_fallback"),
                    }
        except Exception as exc:
            result["meta"]["degraded"] = True
            result["meta"]["prediction_error"] = str(exc)

    if feature_type in {"entity", "uploaded_entity"} and feature_id:
        try:
            entity_layer = build_entity_layer(ctx)
            features = entity_layer.get("feature_collection", {}).get("features", [])
            matched = [
                feature
                for feature in features
                if clean_text(feature.get("properties", {}).get("entity_id")) == feature_id
                or clean_text(feature.get("properties", {}).get("record_key")) == feature_id
            ]
            result["entity"] = matched[0].get("properties", {}) if matched else {}
            result["meta"]["found"] = result["meta"]["found"] or bool(matched)

            if matched and isinstance(matched[0].get("geometry"), dict):
                coordinates = matched[0]["geometry"].get("coordinates", [])
                if len(coordinates) >= 2:
                    result["map_focus"] = {
                        "center": [coordinates[0], coordinates[1]],
                        "zoom": 12,
                        "focus_level": "point",
                        "focus_fallback": None,
                    }
        except Exception as exc:
            result["meta"]["degraded"] = True
            result["meta"]["entity_error"] = str(exc)

    return to_jsonable(result)


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

    return to_jsonable({
        "map": layers.get("map", {}),
        "layers": layers.get("layers", {}),
        "layers_by_id": layers.get("layers_by_id", {}),
        "layer_order": layers.get("layer_order", []),
        "summary": layer_summary,
        "selected_context": selected_context,
        "meta": {
            "generated_at": now_iso(),
            "degraded": bool(layers.get("meta", {}).get("degraded") or selected_context.get("meta", {}).get("degraded")),
            "layer_count": layer_summary.get("layer_count", 0),
            "record_count": layer_summary.get("record_count", layer_summary.get("feature_count", 0)),
        },
        "generated_at": now_iso(),
    })

def get_external_viewer_map_payload(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    สร้าง map payload สำหรับ External Viewer Package

    external viewer อ่าน snapshot/package payload เท่านั้น และรับ layer แบบ public-safe
    """

    ctx = normalize_context(context)
    ctx["public_mode"] = True

    if not ctx.get("package_id"):
        return to_jsonable({
            "map": {
                "center": MAP_DEFAULT_CENTER,
                "zoom": MAP_DEFAULT_ZOOM,
                "min_zoom": MAP_MIN_ZOOM,
                "max_zoom": MAP_MAX_ZOOM,
                "base_tile_url": MAP_BASE_TILE_URL,
                "base_attribution": MAP_BASE_ATTRIBUTION,
            },
            "layer_order": [],
            "layers": [],
            "layers_by_id": {},
            "summary": {
                "layer_count": 0,
                "record_count": 0,
                "feature_count": 0,
                "generated_at": now_iso(),
                "degraded": True,
            },
            "meta": {
                "generated_at": now_iso(),
                "degraded": True,
                "reason": "public package context missing",
                "package_id": "",
                "public_mode": True,
            },
            "generated_at": now_iso(),
        })

    layers_payload = get_map_layers(ctx)
    raw_layers = layers_payload.get("layers", {})

    if isinstance(raw_layers, dict):
        layer_items = [
            raw_layers[layer_id]
            for layer_id in layers_payload.get("layer_order", [])
            if layer_id in raw_layers
        ]
        if not layer_items:
            layer_items = list(raw_layers.values())
    elif isinstance(raw_layers, list):
        layer_items = raw_layers
    else:
        layer_items = []

    public_layers: List[Dict[str, Any]] = []
    public_layers_by_id: Dict[str, Dict[str, Any]] = {}

    for layer in layer_items:
        if not isinstance(layer, dict):
            continue

        safe_meta = {
            key: value
            for key, value in layer.get("meta", {}).items()
            if key not in {
                "source_path",
                "cache_path",
                "file_path",
                "source_file",
                "raw_file_path",
                "internal_path",
                "upload_dir",
                "saved_file",
                "error_report_file",
                "debug_traceback",
                "raw_record",
            }
        }

        public_layer = {
            "layer_id": layer.get("layer_id"),
            "layer_name": layer.get("layer_name"),
            "layer_type": layer.get("layer_type"),
            "visible": layer.get("visible"),
            "opacity": layer.get("opacity"),
            "z_index": layer.get("z_index"),
            "record_count": layer.get("record_count"),
            "features": layer.get("features"),
            "feature_collection": layer.get("feature_collection"),
            "style": layer.get("style"),
            "meta": safe_meta,
        }

        public_layers.append(public_layer)

        if public_layer.get("layer_id"):
            public_layers_by_id[clean_text(public_layer.get("layer_id"))] = public_layer

    return to_jsonable({
        "map": layers_payload.get("map", {}),
        "layer_order": layers_payload.get("layer_order", []),
        "layers": public_layers,
        "layers_by_id": public_layers_by_id,
        "summary": layers_payload.get("summary", {}),
        "meta": {
            "generated_at": now_iso(),
            "degraded": bool(layers_payload.get("meta", {}).get("degraded") or not ctx.get("package_id")),
            "package_id": ctx.get("package_id"),
            "public_mode": True,
            "snapshot_only": True,
        },
        "generated_at": now_iso(),
    })

# ============================================================
# 12) CACHE REBUILD
# ============================================================

def rebuild_map_cache(context: Optional[Dict[str, Any]] = None, force_refresh: Optional[bool] = None) -> Dict[str, Any]:
    """
    rebuild cache ทั้งหมดของ map_graph_service.py
    """

    if isinstance(context, bool):
        context = {"force_refresh": context}

    ctx = normalize_context(context)

    if force_refresh is not None:
        ctx["force_refresh"] = bool(force_refresh)

    results: Dict[str, Dict[str, Any]] = {}

    rebuild_plan = [
        ("map_companies", get_map_companies),
        ("map_flood", get_map_flood),
        ("map_rainfall", get_map_rainfall),
        ("map_waterlevel", get_map_waterlevel),
        ("map_dam", get_map_dam),
        ("map_prediction", get_map_prediction),
        ("map_entity", get_map_entity),
        ("map_boundaries", get_map_boundaries),
        ("map_policy_exposure", get_map_policy_exposure),
        ("map_linkage_lines", get_map_linkage_lines),
        ("map_branches", get_map_branches),
        ("map_heatmap", get_map_heatmap),
        ("map_layers", get_map_layers),
        ("map_selected_context", get_selected_context),
    ]

    errors: List[Dict[str, Any]] = []

    for cache_key, function_ref in rebuild_plan:
        try:
            results[cache_key] = function_ref(ctx)
        except Exception as exc:
            results[cache_key] = {
                "record_count": 0,
                "summary": {
                    "feature_count": 0,
                    "degraded": True,
                },
                "meta": {
                    "degraded": True,
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                    "generated_at": now_iso(),
                },
                "cache_used": False,
            }
            errors.append(
                {
                    "cache_key": cache_key,
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                }
            )

    return to_jsonable({
        "rebuilt": True,
        "degraded": bool(errors),
        "results": {
            key: {
                "record_count": value.get("record_count") or value.get("summary", {}).get("record_count") or value.get("summary", {}).get("feature_count") or 0,
                "feature_count": value.get("summary", {}).get("feature_count") or value.get("record_count") or 0,
                "cache_used": value.get("cache_used"),
                "degraded": bool(value.get("meta", {}).get("degraded") or value.get("summary", {}).get("degraded")),
                "created_at": value.get("meta", {}).get("created_at") or value.get("meta", {}).get("generated_at") or value.get("summary", {}).get("generated_at"),
            }
            for key, value in results.items()
        },
        "errors": errors,
        "generated_at": now_iso(),
    })


# ============================================================
# 13) BACKWARD COMPATIBILITY ALIASES
# ============================================================

def get_rainfall_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_rainfall(context)


def get_waterlevel_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_waterlevel(context)


def get_dam_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_dam(context)


def get_prediction_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_prediction(context)


def get_entity_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_entity(context)


def get_uploaded_entity_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_entity(context)


def get_boundary_map_layers(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_boundaries(context)


def get_flood_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_flood(context)


def get_company_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_companies(context)


def get_policy_exposure_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_policy_exposure(context)


def get_linkage_line_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_linkage_lines(context)


def get_branch_map_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_branches(context)


def get_heatmap_layer(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_map_heatmap(context)


def get_selected_map_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_selected_context(context)


# ============================================================
# 14) CLASS ADAPTER FOR API ROUTES
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

    def get_map_rainfall(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_rainfall(context)

    def get_map_waterlevel(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_waterlevel(context)

    def get_map_dam(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_dam(context)

    def get_map_prediction(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_prediction(context)

    def get_map_entity(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_entity(context)

    def get_map_entities(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_entities(context)

    def get_map_boundaries(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_map_boundaries(context)

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
        "merged_layer_contract": {
            "canonical_layers": DEFAULT_LAYER_ORDER,
            "compatibility_aliases": {
                "province_boundaries": "province_boundary",
                "basin_boundaries": "basin_boundary",
                "get_company_map_layer": "get_map_companies",
                "get_prediction_map_layer": "get_map_prediction",
                "get_entity_map_layer": "get_map_entity",
            },
            "layers_payload_shape": {
                "layers": "dict[layer_id, layer_payload]",
                "layers_by_id": "dict[layer_id, layer_payload]",
                "layer_list": "list[layer_payload]",
                "layer_order": "list[layer_id]",
            },
        },
        "supported_layers": [
            "rainfall",
            "waterlevel",
            "dam",
            "prediction",
            "entity",
            "province_boundary",
            "basin_boundary",
            "company_points",
            "flood_points",
            "policy_exposure",
            "linkage_lines",
            "branch_points",
            "heatmap",
            "province_boundaries",
            "basin_boundaries",
        ],
        "supported_api_functions": [
            "get_map_layers",
            "get_map_companies",
            "get_map_flood",
            "get_map_rainfall",
            "get_map_waterlevel",
            "get_map_dam",
            "get_map_prediction",
            "get_map_entity",
            "get_map_entities",
            "get_map_boundaries",
            "get_map_policy_exposure",
            "get_map_linkage_lines",
            "get_map_branches",
            "get_map_heatmap",
            "get_selected_context",
            "get_map_dashboard_payload",
            "get_external_viewer_map_payload",
            "rebuild_map_cache",
        ],
        "layer_order": DEFAULT_LAYER_ORDER,
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
            "rainfall_service_ready": get_latest_rainfall is not None,
            "waterlevel_service_ready": get_latest_waterlevel is not None,
            "dam_service_ready": get_latest_dam is not None,
            "prediction_service_ready": get_flood_prediction_map is not None,
            "entity_service_ready": True,
            "source": "excel" if getattr(config, "USE_EXCEL_DATA_SOURCE", True) else "mysql",
        },
        "checked_at": now_iso(),
    }

def run_map_graph_self_test() -> Dict[str, Any]:
    """
    self test เบื้องต้น
    """

    ctx = {"force_refresh": False}

    companies = get_map_companies(ctx)
    flood = get_map_flood(ctx)
    rainfall = get_map_rainfall(ctx)
    waterlevel = get_map_waterlevel(ctx)
    dam = get_map_dam(ctx)
    prediction = get_map_prediction(ctx)
    entity = get_map_entity(ctx)
    boundaries = get_map_boundaries(ctx)
    layers = get_map_layers(ctx)

    return {
        "module": "map_graph_service",
        "self_test": True,
        "status": get_map_graph_module_status(),
        "company_layer_count": companies.get("record_count", 0),
        "flood_layer_count": flood.get("record_count", 0),
        "rainfall_layer_count": rainfall.get("record_count", 0),
        "waterlevel_layer_count": waterlevel.get("record_count", 0),
        "dam_layer_count": dam.get("record_count", 0),
        "prediction_layer_count": prediction.get("record_count", 0),
        "entity_layer_count": entity.get("record_count", 0),
        "boundary_summary": boundaries.get("summary", {}),
        "layer_summary": layers.get("summary", {}),
        "layer_order": layers.get("layer_order", []),
        "layers_shape": {
            "layers_is_dict": isinstance(layers.get("layers"), dict),
            "layer_list_is_list": isinstance(layers.get("layer_list"), list),
            "layers_by_id_is_dict": isinstance(layers.get("layers_by_id"), dict),
        },
        "checked_at": now_iso(),
    }
