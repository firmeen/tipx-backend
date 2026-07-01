# TIPX Backend API Contract

Enterprise Intelligence Dashboard Backend API Contract for React Frontend Integration

## Metadata

| Item | Value |
|---|---|
| Project | TIPX Enterprise Intelligence Dashboard |
| Backend | Flask |
| API Prefix | `/api` |
| Contract Version | `v1` |
| Generated / Updated | 2026-06-12 08:34:30 |
| Source files | `app.py`, `api_routes.py`, `test_api_contract.py` |
| Contract status | `PARTIAL` based on PHASE 15 environment-blocked run; contract script exists and syntax passes, but real Flask runtime must be run locally |
| Intended frontend | React, OpenLayers, D3 / React Flow, Filter Builder, Package/Public Viewer |

---

## 1. Overview

This document defines the API contract between the TIPX Flask backend and the future React frontend. It is based on the current `api_routes.py`, `app.py`, `test_api_contract.py`, and service payload conventions validated through PHASE 06–15.

The backend is designed around a stable response envelope. Frontend code should never assume that `HTTP 200` means the underlying data source is complete. A service can return `success: true` and still be a controlled fallback or partial response. The frontend must check `meta.fallback`, `meta.partial`, `data.fallback`, and `errors`.

---

## 2. Base URL

Local development default:

```text
http://127.0.0.1:5000
```

API base:

```text
http://127.0.0.1:5000/api
```

Frontend should keep the API base URL configurable, for example through an environment variable such as `VITE_API_BASE_URL`.

---

## 3. Standard Response Envelope

All `/api/*` JSON endpoints should return this top-level shape:

```json
{
  "success": true,
  "message": "OK",
  "data": {},
  "meta": {
    "fallback": false,
    "partial": false,
    "record_count": 0,
    "generated_at": "2026-06-12T00:00:00",
    "service_module": "company_policy_service",
    "service_function": "get_policy_summary"
  },
  "errors": []
}
```

| Field | Type | Meaning | Frontend rule |
|---|---|---|---|
| `success` | boolean | Indicates whether the API call is successful at the envelope level | Check first |
| `message` | string | Human/debug status such as `OK`, `OK_WITH_FALLBACK`, `BAD_REQUEST`, `ERROR` | Use for logs/toasts |
| `data` | object/list | Module-specific payload | Normalize per module |
| `meta` | object | Response metadata, fallback flags, counts, warnings | Always read |
| `errors` | array | Structured error list | Always treat as array |

Important: `meta.record_count` is a helper value, not always the source of truth. For paginated tables, prefer `data.total`, `data.records.length`, and pagination fields when present.

---

## 4. Success Response

```json
{
  "success": true,
  "message": "OK",
  "data": {
    "records": [],
    "total": 0
  },
  "meta": {
    "fallback": false,
    "partial": false,
    "record_count": 0
  },
  "errors": []
}
```

A success response means the endpoint returned a valid backend payload. It does not guarantee that every source module has complete data unless `meta.fallback === false` and `meta.partial === false`.

---

## 5. Fallback / Partial Response

```json
{
  "success": true,
  "message": "OK_WITH_FALLBACK",
  "data": {
    "fallback": true,
    "records": [],
    "summary": {},
    "service_module": "flood_spatial_service",
    "service_function": "get_flood_summary",
    "error": {
      "type": "FileNotFoundError",
      "message": "Flood source file is not available",
      "category": "data_source_missing"
    }
  },
  "meta": {
    "fallback": true,
    "partial": true,
    "record_count": 0,
    "warnings": [
      {
        "type": "FileNotFoundError",
        "message": "Flood source file is not available",
        "service_module": "flood_spatial_service",
        "service_function": "get_flood_summary"
      }
    ]
  },
  "errors": []
}
```

Fallback means the endpoint remains usable, but the backend returned empty/default/partial data because one source or service was unavailable. Frontend behavior should be:

- Show a warning badge or banner.
- Keep the page usable where possible.
- Avoid treating empty arrays as “true zero” when `meta.fallback` is true.
- Prefer `meta.fallback` as the primary signal, and `data.fallback` as a secondary signal.

---

## 6. Error Response

```json
{
  "success": false,
  "message": "BAD_REQUEST",
  "data": {},
  "meta": {
    "fallback": false,
    "partial": false
  },
  "errors": [
    {
      "type": "ValidationError",
      "message": "Invalid request payload",
      "field": "conditions",
      "category": "bad_request"
    }
  ]
}
```

Frontend rules:

- `success === false` means show an error state.
- `errors` must be handled as an array.
- Do not parse raw tracebacks.
- Do not assume `data` contains useful module data in fatal errors.

---

## 7. Status Code Policy

| Status | Meaning | Frontend behavior |
|---:|---|---|
| 200 | Success, controlled fallback, or partial response | Inspect `success`, `meta.fallback`, `meta.partial` |
| 400 | Invalid request body/query/filter/package payload | Show validation error |
| 401 | Authentication/token missing when required | Ask for token/login if implemented |
| 403 | Access denied, expired, invalid package token | Show access denied |
| 404 | Resource or route not found | Show not found state |
| 500 | Unexpected backend bug | Show fatal backend error |
| 503 | Required service unavailable | Show service unavailable |

Optional service missing may return `200 OK_WITH_FALLBACK` instead of `503`.

---

## 8. Common Query Parameters

| Param | Type | Default | Used by | Description |
|---|---:|---:|---|---|
| `force_refresh` | boolean | `false` | most modules | Rebuild/read fresh cache. Avoid in normal frontend refresh loops. |
| `page` | integer | `1` | table endpoints | Page number. Values below 1 should be normalized. |
| `page_size` | integer | backend default | table endpoints | Records per page. Backend may clamp. |
| `search` | string | `""` | list/table endpoints | Full text search. |
| `sort_by` | string | module-specific | list/table endpoints | Field to sort by. |
| `sort_dir` | `asc`/`desc` | `asc` | list/table endpoints | Sort direction. |
| `province` | string | none | company/flood/map | Province filter. |
| `risk_level` | string | none | flood/map/data quality | Risk filter. |
| `source_type` | string | none | flood/data quality | Source filter. |
| `severity` | string | none | data quality | Issue severity filter. |
| `category` | string | none | data quality/filter | Issue or record category. |
| `max_nodes` | integer | config default | linkage graph | Graph size limit. |
| `depth` | integer | module default | linkage graph | Graph depth. |
| `mode` | string | module default | linkage graph | Graph mode. |
| `tax_id` | string | none | company/linkage/map | Company selection. |
| `director_id` | string | none | linkage/map | Director selection. |
| `token` | string | none | public package | Public package access token if enforced. |

Map-specific query flags:

```text
include_companies
include_flood
include_policy
include_linkage
include_branches
include_heatmap
include_boundaries
selected_tax_id
selected_director_id
selected_province
```

---

## 9. Pagination Contract

Paginated endpoints usually return either:

```json
{
  "records": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "total_pages": 0,
  "has_next": false,
  "has_prev": false
}
```

or the same fields inside `data`. Frontend should normalize both direct and nested pagination paths:

- `response.data.records`
- `response.data.total`
- `response.data.page`
- `response.data.page_size`
- `response.data.total_pages`
- `response.meta.record_count`

---

## 10. Frontend Error / Fallback Detection Rules

```js
export function isApiFallback(res) {
  return Boolean(
    res?.meta?.fallback ||
    res?.data?.fallback ||
    res?.message === "OK_WITH_FALLBACK"
  );
}

export function isApiPartial(res) {
  return Boolean(res?.meta?.partial || res?.message === "PARTIAL_SUCCESS");
}

export function getApiErrors(res) {
  return Array.isArray(res?.errors) ? res.errors : [];
}

export function getApiWarnings(res) {
  return Array.isArray(res?.meta?.warnings) ? res.meta.warnings : [];
}
```

Frontend should avoid direct use of raw `fetch().json().data` without envelope handling.

---

## 11. Endpoint Summary Table

| Module | Method | Path | Required | Service function | Data path | Fallback behavior | Frontend use |
|---|---|---|---|---|---|---|---|
| Core | GET | `/api/health` | Yes | `internal/app/config` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Core | GET | `/api/status` | Yes | `internal/app/config` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Core | GET | `/api/config` | No/Module | `internal/app/config` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Core | GET | `/api/paths` | No/Module | `internal/app/config` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Core | GET | `/api/inputs` | No/Module | `internal/app/config` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Core | GET | `/api/routes` | Yes | `internal/app/config` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies` | Yes | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies/summary` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies/<tax_id>` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies/ranking/income` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies/ranking/capital` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies/source-flags` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies/missing-policy` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies/missing-linkage` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Company | GET | `/api/companies/missing-location` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/summary` | Yes | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/companies` | No/Module | `company_policy_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/company/<tax_id>` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/company/<tax_id>/summary` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/company/<tax_id>/table` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/company/<tax_id>/trend` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/product-summary` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/subclass-summary` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/yearly-summary` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/loss-ratio-ranking` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/high-loss` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Policy | GET | `/api/policy/exposure` | No/Module | `company_policy_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Linkage | GET | `/api/linkage/summary` | Yes | `linkage_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Linkage | GET | `/api/linkage/graph` | Yes | `linkage_service` | `data.nodes / data.edges` | `meta.fallback`, `data.fallback` | React/API adapter |
| Linkage | GET | `/api/linkage/company/<tax_id>` | No/Module | `linkage_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Linkage | GET | `/api/linkage/director/<director_id>` | No/Module | `linkage_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Linkage | GET | `/api/linkage/key-connectors` | No/Module | `linkage_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Linkage | GET | `/api/linkage/shared-directors` | No/Module | `linkage_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Linkage | GET | `/api/linkage/exposure-by-director` | No/Module | `linkage_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/flood/summary` | Yes | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/flood/rainfall/latest` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/flood/waterlevel/latest` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/flood/dam/large/latest` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/flood/dam/medium/latest` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/flood/computed-risk` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/flood/boundaries/province` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/flood/boundaries/basin` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | POST | `/api/flood/refresh` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/spatial/company-flood-context` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/spatial/company/<tax_id>/flood-context` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/spatial/policy-flood-exposure` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/spatial/province-risk-exposure` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Flood / Spatial | GET | `/api/spatial/nearest-stations/<tax_id>` | No/Module | `flood_spatial_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Map | GET | `/api/map/layers` | Yes | `map_graph_service` | `data.layers / data.map` | `meta.fallback`, `data.fallback` | React/API adapter |
| Map | GET | `/api/map/flood` | No/Module | `map_graph_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Map | GET | `/api/map/companies` | No/Module | `map_graph_service` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Map | GET | `/api/map/policy-exposure` | No/Module | `map_graph_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Map | GET | `/api/map/linkage-lines` | No/Module | `map_graph_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Map | GET | `/api/map/branches` | No/Module | `map_graph_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Map | GET | `/api/map/heatmap` | No/Module | `map_graph_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Map | GET | `/api/map/selected-context` | No/Module | `map_graph_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Dashboard | GET | `/api/charts/summary` | No/Module | `dashboard_package_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Dashboard | GET | `/api/dashboard/executive` | No/Module | `dashboard_package_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Dashboard | GET | `/api/dashboard/summary` | No/Module | `dashboard_package_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Dashboard | GET | `/api/dashboard/overview` | No/Module | `dashboard_package_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Dashboard | GET | `/api/dashboard/freshness` | No/Module | `dashboard_package_service` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | GET | `/api/filter/fields` | Yes | `filter_engine` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | GET | `/api/filter/quick-presets` | No/Module | `filter_engine` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | POST | `/api/filter/preview` | No/Module | `filter_engine` | `data.preview / data.components` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | POST | `/api/filter/apply` | No/Module | `filter_engine` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | POST | `/api/filter/save-view` | No/Module | `filter_engine` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | GET | `/api/filter/saved-views` | No/Module | `filter_engine` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | GET | `/api/filter/saved-views/<view_id>` | No/Module | `filter_engine` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | PUT | `/api/filter/saved-views/<view_id>` | No/Module | `filter_engine` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Filter | DELETE | `/api/filter/saved-views/<view_id>` | No/Module | `filter_engine` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Data Quality | GET | `/api/data-quality/summary` | Yes | `data_quality` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Data Quality | GET | `/api/data-quality/tax-id` | No/Module | `data_quality` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Data Quality | GET | `/api/data-quality/coordinates` | No/Module | `data_quality` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Data Quality | GET | `/api/data-quality/policy` | No/Module | `data_quality` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Data Quality | GET | `/api/data-quality/linkage` | No/Module | `data_quality` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Data Quality | GET | `/api/data-quality/spatial-join` | No/Module | `data_quality` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Data Quality | GET | `/api/data-quality/status-conflicts` | No/Module | `data_quality` | `data` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | POST | `/api/packages/preview` | No/Module | `dashboard_package_service / security` | `data.preview / data.components` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | POST | `/api/packages/generate` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages` | Yes | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages/<package_id>` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages/<package_id>/download` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | POST | `/api/packages/<package_id>/disable` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | DELETE | `/api/packages/<package_id>` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages/<package_id>/meta` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages/<package_id>/data` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages/<package_id>/summary` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages/<package_id>/map` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages/<package_id>/charts` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | GET | `/api/packages/<package_id>/tables` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |
| Package / Public | POST | `/api/packages/<package_id>/access-log` | No/Module | `dashboard_package_service / security` | `data.records` | `meta.fallback`, `data.fallback` | React/API adapter |

---

## 12. Core / Health / Status APIs

### GET `/api/health`

Purpose: Fast health check for backend status.

Response data includes:

- app metadata
- version
- environment
- config validation summary

Frontend use: health indicator, backend connection check.

### GET `/api/status`

Purpose: Broader backend status including paths, inputs, validation, and module list.

Response data includes:

- `app`
- `paths`
- `inputs`
- `validation`
- `modules`

### GET `/api/inputs`

Purpose: Show expected input file status.

Response data includes input file existence/size/status. Frontend should avoid displaying raw local paths in public UI.

### GET `/api/routes`

Purpose: Developer/debug route inventory. It returns route rules and methods. This should be treated as dev/admin data, not public UI data.

---

## 13. Dashboard APIs

Actual dashboard routes include:

- `GET /api/dashboard/executive`
- `GET /api/dashboard/summary`
- `GET /api/dashboard/overview`
- `GET /api/dashboard/freshness`
- `GET /api/charts/summary`

Primary source module: `dashboard_package_service`.

Frontend components:

- `DashboardSummaryCards`
- `ExecutiveOverview`
- `ChartPanel`
- `FreshnessWarningPanel`

Fallback behavior: If a source module is partial, dashboard endpoints may return summary with warnings or fallback payloads. Frontend should display warning badges per module.

---

## 14. Company APIs

### GET `/api/companies`

Common query:

```text
page, page_size, search, sort_by, sort_dir, province, risk_level
```

Expected data path:

```text
response.data.records
response.data.total
response.data.page
response.data.page_size
```

Company record fields may include:

```text
tax_id_norm
tax_id_raw
company_name
province
district
subdistrict
lat / lon
location_quality
total_premium
total_loss
total_suminsure
loss_ratio
loss_ratio_band
active_policy_count
expired_policy_count
product_count
subclass_count
wtip
business_type_objective
business_type_tsic
company_size
has_policy
has_linkage
has_location
has_flood_context
```

### GET `/api/companies/summary`

Expected data includes total company counts and source flags.

### GET `/api/companies/<tax_id>`

Expected data includes company detail. If not found, backend should return controlled empty/detail response or 404 depending on handler behavior.

Additional company endpoints:

```text
/api/companies/ranking/income
/api/companies/ranking/capital
/api/companies/source-flags
/api/companies/missing-policy
/api/companies/missing-linkage
/api/companies/missing-location
```

---

## 15. Policy APIs

Actual policy routes include:

```text
GET /api/policy/summary
GET /api/policy/companies
GET /api/policy/company/<tax_id>
GET /api/policy/company/<tax_id>/summary
GET /api/policy/company/<tax_id>/table
GET /api/policy/company/<tax_id>/trend
GET /api/policy/product-summary
GET /api/policy/subclass-summary
GET /api/policy/yearly-summary
GET /api/policy/loss-ratio-ranking
GET /api/policy/high-loss
GET /api/policy/exposure
```

Compatibility note: PHASE 15 test specs also reference shorter aliases such as `/api/policy/products`, `/api/policy/subclasses`, `/api/policy/yearly`, and `/api/policy/loss-ratio`. If these aliases are not registered in the current `api_routes.py`, they should be treated as test/documentation warnings or added in a route-alias stabilization phase.

### GET `/api/policy/summary`

Expected fields:

```text
total_policy_records
total_companies
total_products
total_subclasses
total_premium
total_loss
total_suminsure
total_noofpol
average_loss_ratio
loss_ratio_band
active_policy_record_count
expired_policy_record_count
generated_at
```

Policy fallback: If input/cache is missing, frontend should expect empty summaries or `OK_WITH_FALLBACK`.

---

## 16. Linkage APIs

Actual linkage routes include:

```text
GET /api/linkage/summary
GET /api/linkage/graph
GET /api/linkage/company/<tax_id>
GET /api/linkage/director/<director_id>
GET /api/linkage/key-connectors
GET /api/linkage/shared-directors
GET /api/linkage/exposure-by-director
```

### GET `/api/linkage/graph`

Query:

```text
max_nodes
depth
mode
tax_id
director_id
include_shared_edges
```

Expected data path:

```text
response.data.nodes
response.data.edges
```

or, for nested graph payloads:

```text
response.data.graph.nodes
response.data.graph.edges
```

Node fields:

```text
id
type / node_type
label / name
tax_id_norm
director_id
degree
metrics
color / style
metadata
```

Edge fields:

```text
id
source
target
type / edge_type
weight
shared_directors
metadata
```

Fallback: if boardlist/linkage cache is missing, graph should return controlled `nodes=[]`, `edges=[]`, or fallback metadata.

---

## 17. Flood / Spatial APIs

Actual flood/spatial routes include:

```text
GET /api/flood/summary
GET /api/flood/rainfall/latest
GET /api/flood/waterlevel/latest
GET /api/flood/dam/large/latest
GET /api/flood/dam/medium/latest
GET /api/flood/computed-risk
GET /api/flood/boundaries/province
GET /api/flood/boundaries/basin
POST /api/flood/refresh
GET /api/spatial/company-flood-context
GET /api/spatial/company/<tax_id>/flood-context
GET /api/spatial/policy-flood-exposure
GET /api/spatial/province-risk-exposure
GET /api/spatial/nearest-stations/<tax_id>
```

Compatibility note: PHASE 15 specs reference `/api/flood/risk`, `/api/spatial/company-context`, `/api/spatial/policy-exposure`, and `/api/spatial/province-exposure`. Current actual routes use `/computed-risk`, `/company-flood-context`, `/policy-flood-exposure`, and `/province-risk-exposure`. Frontend should use actual routes or backend should add aliases.

### GET `/api/flood/summary`

Expected fields:

```text
rainfall_station_count
waterlevel_station_count
large_dam_count
medium_dam_count
computed_risk_count
province_risk_count
risk_counts
source_counts
files
policy_flood_exposure
generated_at
```

### GET `/api/flood/computed-risk`

Expected record fields:

```text
source_type
source_id / station_id / dam_id
source_name / station_name / dam_name
province
basin
lat / lon or latitude / longitude
risk_level
risk_score
risk_reason
risk_color
data_datetime / data_date / source_updated_at
```

Fallback: Flood source missing or stale should not crash. Frontend should show a warning and continue rendering non-flood modules.

---

## 18. Map APIs

Actual map routes include:

```text
GET /api/map/layers
GET /api/map/flood
GET /api/map/companies
GET /api/map/policy-exposure
GET /api/map/linkage-lines
GET /api/map/branches
GET /api/map/heatmap
GET /api/map/selected-context
```

Compatibility note: Some prompt/test aliases use `/api/map/company-layer` and `/api/map/flood-layer`. Current actual route names are `/api/map/companies` and `/api/map/flood`.

### GET `/api/map/layers`

Query:

```text
include_companies
include_flood
include_policy
include_linkage
include_branches
include_heatmap
include_boundaries
selected_tax_id
selected_director_id
selected_province
```

Expected data:

```text
response.data.map
response.data.layers
response.data.layer_order
response.data.layer_list
response.data.summary
response.data.context
```

Layer object fields:

```text
layer_id
layer_name
layer_type
visible
opacity
z_index
record_count
feature_collection
style
meta
cache_used
```

GeoJSON contract:

```json
{
  "type": "FeatureCollection",
  "features": []
}
```

Coordinate order must be:

```text
[longitude, latitude]
```

Expected layer keys include:

```text
company_points
branch_points
flood_points
policy_exposure
linkage_lines
heatmap
province_boundaries
basin_boundaries
```

Frontend components:

```text
OpenLayersMap
LayerControlPanel
MapPopup
MapLegend
```

---

## 19. Filter Builder APIs

Actual filter routes include:

```text
GET /api/filter/fields
GET /api/filter/quick-presets
POST /api/filter/preview
POST /api/filter/apply
POST /api/filter/save-view
GET /api/filter/saved-views
GET /api/filter/saved-views/<view_id>
PUT /api/filter/saved-views/<view_id>
DELETE /api/filter/saved-views/<view_id>
```

Compatibility note: PHASE 15 uses `/api/filter/presets`. Current actual route is `/api/filter/quick-presets` unless an alias is added later.

### GET `/api/filter/fields`

Expected data:

```text
fields
field_groups
operators
logical_operators
filterable_by_target
table_views
payload_example
```

### POST `/api/filter/preview`

Request:

```json
{
  "target": "company",
  "logic": "AND",
  "conditions": [
    {
      "field": "province",
      "operator": "equals",
      "value": "Bangkok"
    }
  ],
  "page": 1,
  "page_size": 20
}
```

Response data:

```text
valid
validation
target
preview.total_before_filter
preview.total_after_filter
preview.sample_records
summary
filter
```

### POST `/api/filter/apply`

Expected data:

```text
records
total
page
page_size
total_pages
has_next
has_prev
summary
filter
```

Operators currently documented from PHASE 10:

```text
equals
not_equals
contains
not_contains
starts_with
ends_with
in
not_in
gt
gte
lt
lte
between
is_empty
is_not_empty
```

Frontend may map UI aliases such as `eq` to backend `equals`.

---

## 20. Data Quality APIs

Actual data quality routes include:

```text
GET /api/data-quality/summary
GET /api/data-quality/tax-id
GET /api/data-quality/coordinates
GET /api/data-quality/policy
GET /api/data-quality/linkage
GET /api/data-quality/spatial-join
GET /api/data-quality/status-conflicts
```

Compatibility note: PHASE 15 references `/api/data-quality/issues`, `/api/data-quality/cache-status`, and `/api/data-quality/source-status`. If these routes are not present in current `api_routes.py`, they are documentation/test warnings or should be added as aliases.

### GET `/api/data-quality/summary`

Expected data:

```text
total_issues
quality_score
quality_level
by_severity
by_category
by_dataset
top_issues
top_datasets
issues
generated_at
input_file_status
module_status
pagination
cache_used
```

Issue fields:

```text
issue_id
severity
category
code
message
dataset
field
record_key
value
suggestion
created_at
source
row_number
extra
```

Fallback: Missing source/cache should be represented as issues or warnings, not crash the endpoint.

---

## 21. Package Export APIs

Actual package routes include:

```text
POST /api/packages/preview
POST /api/packages/generate
GET /api/packages
GET /api/packages/<package_id>
GET /api/packages/<package_id>/download
POST /api/packages/<package_id>/disable
DELETE /api/packages/<package_id>
```

### GET `/api/packages`

Expected data:

```text
records
total
page
page_size
total_pages
has_next
has_prev
```

Package item fields:

```text
package_id
package_name / title
created_at
expire_at
components
status
security
checksum
```

### POST `/api/packages/preview`

Request:

```json
{
  "package_name": "TIPX_EXPORT",
  "components": ["summary", "companies", "policy_table", "linkage_graph", "map_layers", "data_quality"],
  "security": {
    "public": true,
    "mask_tax_id": true,
    "mask_directors": true,
    "hide_addresses": true,
    "remove_internal_fields": true
  },
  "expire_days": 7
}
```

Response data:

```text
request
filter_context
estimated_record_counts
estimated_files
components
security
warnings
previewed_at
```

### POST `/api/packages/generate`

Expected data:

```text
generated
package_id
package_meta
index_item
files
public_data_preview
generated_at
```

Frontend must treat generated package metadata as admin/internal unless the endpoint explicitly serves public data.

---

## 22. Public Viewer APIs

Actual public package routes are currently under:

```text
GET /api/packages/<package_id>/meta
GET /api/packages/<package_id>/data
GET /api/packages/<package_id>/summary
GET /api/packages/<package_id>/map
GET /api/packages/<package_id>/charts
GET /api/packages/<package_id>/tables
POST /api/packages/<package_id>/access-log
```

Compatibility note: PHASE 15 references `/api/public/packages/not-exist/data`, but current actual `api_routes.py` uses `/api/packages/<package_id>/data`. If public URL separation is required, add aliases in a future route stabilization step.

Public data response should include sanitized package data only:

```text
status
allowed
package_id
component
timestamp
data
```

Public viewer error behavior:

- Package not found: `404`
- Token invalid/expired: `401` or `403`
- Response must still use the standard JSON envelope
- No internal paths, raw records, debug payloads, or secrets

---

## 23. Security & Sanitization Notes

Public package payloads must be sanitized by `security.py` and package service logic.

Sensitive fields and patterns:

```text
tax_id
director/person names
full address
financial fields when hide_financials is enabled
internal paths
cache_key
debug_raw
raw_record
token
secret
password
private_key
traceback
server logs
```

Public viewer must not expose:

```text
local developer paths
internal cache paths
raw debug payloads
tracebacks
tokens/secrets
```

Frontend rules:

- Do not log public tokens to console.
- Do not store package tokens in long-lived local storage unless necessary.
- Treat public package data as a read-only sanitized snapshot.
- Re-run public leak scan before public deployment.

---

## 24. Response Shape Details by Module

### Company

- List: `GET /api/companies` → `data.records`
- Summary: `GET /api/companies/summary` → `data`
- Detail: `GET /api/companies/<tax_id>` → `data.company` or detail object

### Policy

- Summary: `GET /api/policy/summary` → `data`
- Product/subclass/yearly summaries: actual paths use `*-summary`
- Loss ranking: `GET /api/policy/loss-ratio-ranking` → `data.records`

### Linkage

- Summary: `GET /api/linkage/summary` → `data`
- Graph: `GET /api/linkage/graph` → `data.nodes`, `data.edges`

### Flood

- Summary: `GET /api/flood/summary` → `data`
- Risk records: `GET /api/flood/computed-risk` → `data.records`
- Stale/missing source warning: `meta.warnings`, `data.files`, or module-specific source status

### Map

- Layers: `GET /api/map/layers` → `data.layers`
- Feature collection: `data.layers.<layer_key>.feature_collection`
- Coordinates: `[longitude, latitude]`

### Filter

- Fields: `GET /api/filter/fields` → `data.fields`, `data.field_groups`
- Preview: `POST /api/filter/preview` → `data.preview.sample_records`
- Apply: `POST /api/filter/apply` → `data.records`
- Saved views: `GET /api/filter/saved-views` → `data.records` or `data.views`

### Data Quality

- Summary: `GET /api/data-quality/summary` → `data.quality_score`, `data.total_issues`
- Issues: if route exists, `GET /api/data-quality/issues` → `data.records`

### Package

- Preview: `POST /api/packages/preview` → `data.components`, `data.estimated_record_counts`
- Generate: `POST /api/packages/generate` → `data.package_id`, `data.package_meta`
- Public data: `GET /api/packages/<package_id>/data` → `data.data`

---

## 25. Frontend Adapter Guide

Recommended central adapter functions:

```text
unwrapApiResponse(response)
isApiSuccess(response)
isApiFallback(response)
getApiErrors(response)
getApiWarnings(response)
getRecordCount(response)
normalizePagination(response)
normalizeCompanyList(response)
normalizePolicySummary(response)
normalizeLinkageGraph(response)
normalizeMapLayers(response)
normalizeFloodSummary(response)
normalizeFilterFields(response)
normalizeDataQualitySummary(response)
normalizePackagePreview(response)
normalizePublicPackageData(response)
```

Example:

```js
export function isApiFallback(res) {
  return Boolean(
    res?.meta?.fallback ||
    res?.data?.fallback ||
    res?.message === "OK_WITH_FALLBACK"
  );
}

export function getApiErrors(res) {
  return Array.isArray(res?.errors) ? res.errors : [];
}

export function getDataOrFallback(res, fallbackValue) {
  if (!res || res.success === false) return fallbackValue;
  return res.data ?? fallbackValue;
}
```

Frontend should have module-level adapters instead of directly binding UI components to raw backend payloads.

---

## 26. Automated Contract Test Coverage

Based on `test_api_contract.py`:

| Test group | Covered | Required | Status | Notes |
|---|---:|---:|---|---|
| App load | Yes | Yes | PARTIAL | PHASE 15 sandbox run was environment-blocked because Flask was missing |
| Route inventory | Yes | Yes | Ready | Checks required route prefixes |
| Core GET | Yes | Yes | Ready | health/status/inputs/routes |
| Company/Policy GET | Yes | Yes | Ready with alias warnings | Test includes shorter policy aliases that may not be registered |
| Linkage GET | Yes | Yes | Ready | Includes graph validator |
| Flood/Spatial GET | Yes | Partial | Ready with alias warnings | Test includes shorter flood/spatial aliases |
| Map GET | Yes | Yes | Ready | Includes map layer validator |
| Filter GET/POST | Yes | Yes | Ready with alias warning | Test uses `/api/filter/presets`; actual route may be `/quick-presets` |
| Data Quality GET | Yes | Yes | Ready with alias warning | Test includes issues/cache/source status routes that may need aliases |
| Package GET/POST | Yes | Yes | Ready | Preview validator included |
| Public package not found | Yes | Optional | Ready with route warning | Test uses `/api/public/packages/not-exist/data`; actual route may differ |
| Invalid payloads | Yes | Yes | Ready | Expects controlled JSON error |
| Leak scan | Yes | Yes | Ready | Scans for traceback, HTML, internal path, secret markers |

PHASE 15 status: `PARTIAL PASS / ENVIRONMENT BLOCKED`. Run `python test_api_contract.py` on the local backend environment after installing requirements.

---

## 27. Known Fallbacks / Warnings

| Case | Endpoint | Signal | Frontend recommendation |
|---|---|---|---|
| Flood source missing | `/api/flood/summary`, `/api/flood/computed-risk` | `meta.fallback`, `meta.partial`, empty counts, module warning | Show yellow warning, keep non-flood UI usable |
| Flood source stale | flood/spatial endpoints | stale warning in data/meta if available | Show freshness warning |
| Map layer source missing | `/api/map/layers` | empty layer + warning/fallback | Keep layer toggle but show empty state |
| Linkage graph empty | `/api/linkage/graph` | `nodes=[]`, `edges=[]`, fallback/partial warning | Show empty graph message |
| Data quality critical | `/api/data-quality/summary` | `quality_level`, issue counts | Show quality warning panel |
| Saved views empty | `/api/filter/saved-views` | `records=[]` or `views=[]` | Show no saved views state |
| Package component partial | package preview/generate | `warnings` | Show preview warning before generate |
| Public package not found | public package data endpoint | `404`, `success=false` | Show not found/access state |
| Route alias mismatch | test aliases vs actual `api_routes.py` | `404` in contract test | Add route aliases or update frontend/test paths |

---

## 28. Known Risks / Open Items

| Risk | Severity | Notes | Next action |
|---|---|---|---|
| PHASE 15 not fully run in real Flask environment | High | Sandbox lacked Flask | Run locally after `pip install -r requirements.txt` |
| Route aliases in tests may not match actual routes | Medium | policy/filter/flood/spatial/public aliases need stabilization | Decide aliases before frontend integration |
| Flood source path may be missing | High | Flood/spatial endpoints can be controlled fallback | Run PHASE 08A if real flood map is required |
| Public package sanitization must be rechecked before public deployment | High | PHASE 12 passed after patch, but public deployment needs final scan | Re-run package/public scan |
| React adapters should not assume direct data path | Medium | All data comes through envelope | Implement central API adapter |
| Contract tests use Flask test_client, not real CORS/network | Medium | CORS/network still need runtime validation | Run app startup/curl/CORS checks |
| API contract should be frozen before frontend starts | Medium | Avoid changing paths after React integration begins | Finalize aliases in PHASE 17 |

This backend is not declared production-ready by this document. It is ready for PHASE 17 readiness gate review after the local contract test is run.

---

## 29. Backend Readiness Notes for PHASE 17

Checklist for PHASE 17:

```text
API_CONTRACT.md created
api_routes fallback fixed
app startup validated or environment blocker documented
test_api_contract.py created
service modules validated through PHASE 06-12
package/security public payload validated
known warnings documented
frontend adapter guide documented
remaining blockers identified
```

PHASE 17 should decide:

- backend ready for React frontend integration
- backend ready for local demo
- backend ready for public demo mode
- blockers before React implementation
- whether route aliases must be added before frontend starts

---

## 30. Appendix: Example Payloads

### Example 1: GET `/api/policy/summary` success

```json
{
  "success": true,
  "message": "Policy summary",
  "data": {
    "total_policy_records": 55,
    "total_companies": 10,
    "total_premium": 5769400.71,
    "total_loss": 6946466.28,
    "loss_ratio_band": "Critical"
  },
  "meta": {
    "fallback": false,
    "partial": false,
    "record_count": 0
  },
  "errors": []
}
```

### Example 2: GET `/api/linkage/graph` success

```json
{
  "success": true,
  "message": "Linkage graph",
  "data": {
    "nodes": [
      {"id": "company:masked", "type": "company", "label": "Company A"}
    ],
    "edges": [
      {"id": "edge:1", "source": "company:masked", "target": "director:masked", "type": "DIRECTOR_OF"}
    ]
  },
  "meta": {
    "fallback": false,
    "partial": false,
    "node_count": 1,
    "edge_count": 1
  },
  "errors": []
}
```

### Example 3: GET `/api/flood/summary` fallback

```json
{
  "success": true,
  "message": "OK_WITH_FALLBACK",
  "data": {
    "fallback": true,
    "rainfall_station_count": 0,
    "waterlevel_station_count": 0,
    "computed_risk_count": 0,
    "source_status": {"warning": "Flood source missing"}
  },
  "meta": {
    "fallback": true,
    "partial": true,
    "warnings": [{"message": "Flood source missing"}]
  },
  "errors": []
}
```

### Example 4: GET `/api/map/layers` success

```json
{
  "success": true,
  "message": "Map layers",
  "data": {
    "map": {"center": [100.5018, 13.7563], "zoom": 6},
    "layers": {
      "company_points": {
        "layer_id": "company_points",
        "layer_type": "point",
        "visible": true,
        "feature_collection": {"type": "FeatureCollection", "features": []}
      }
    }
  },
  "meta": {"fallback": false, "partial": false},
  "errors": []
}
```

### Example 5: POST `/api/filter/preview`

Request:

```json
{
  "target": "company",
  "logic": "AND",
  "conditions": [
    {"field": "province", "operator": "equals", "value": "Bangkok"}
  ],
  "page": 1,
  "page_size": 5
}
```

Response:

```json
{
  "success": true,
  "message": "Filter preview",
  "data": {
    "valid": true,
    "target": "company",
    "preview": {
      "total_before_filter": 110,
      "total_after_filter": 10,
      "sample_records": []
    }
  },
  "meta": {"fallback": false, "partial": false},
  "errors": []
}
```

### Example 6: POST `/api/packages/preview`

Request:

```json
{
  "package_name": "TIPX_EXPORT",
  "components": ["summary", "companies", "map_layers"],
  "security": {
    "public": true,
    "mask_tax_id": true,
    "remove_internal_fields": true
  },
  "expire_days": 7
}
```

Response:

```json
{
  "success": true,
  "message": "Package preview",
  "data": {
    "components": ["summary", "companies", "map_layers"],
    "estimated_record_counts": {"companies": 110},
    "security": {"public": true, "mask_tax_id": true},
    "warnings": []
  },
  "meta": {"fallback": false, "partial": false},
  "errors": []
}
```

### Example 7: Invalid filter payload

```json
{
  "success": false,
  "message": "BAD_REQUEST",
  "data": {},
  "meta": {"fallback": false, "partial": false},
  "errors": [
    {
      "type": "ValidationError",
      "message": "conditions must be a list",
      "field": "conditions",
      "category": "bad_request"
    }
  ]
}
```

### Example 8: Public package not found

```json
{
  "success": false,
  "message": "NOT_FOUND",
  "data": {},
  "meta": {"fallback": false, "partial": false},
  "errors": [
    {"type": "NotFound", "message": "Package not found", "category": "not_found"}
  ]
}
```

---

## Appendix A: Actual Routes in Current `api_routes.py`

### Core

| Method | Path | Handler |
|---|---|---|
| GET | `/api/health` | `api_health` |
| GET | `/api/status` | `api_status` |
| GET | `/api/config` | `api_config` |
| GET | `/api/paths` | `api_paths` |
| GET | `/api/inputs` | `api_inputs` |
| GET | `/api/routes` | `api_routes` |

### Dashboard

| Method | Path | Handler |
|---|---|---|
| GET | `/api/charts/summary` | `api_charts_summary` |
| GET | `/api/dashboard/executive` | `api_dashboard_executive` |
| GET | `/api/dashboard/summary` | `api_dashboard_summary` |
| GET | `/api/dashboard/overview` | `api_dashboard_overview` |
| GET | `/api/dashboard/freshness` | `api_dashboard_freshness` |

### Company

| Method | Path | Handler |
|---|---|---|
| GET | `/api/companies` | `api_companies` |
| GET | `/api/companies/summary` | `api_companies_summary` |
| GET | `/api/companies/<tax_id>` | `api_company_detail` |
| GET | `/api/companies/ranking/income` | `api_companies_ranking_income` |
| GET | `/api/companies/ranking/capital` | `api_companies_ranking_capital` |
| GET | `/api/companies/source-flags` | `api_companies_source_flags` |
| GET | `/api/companies/missing-policy` | `api_companies_missing_policy` |
| GET | `/api/companies/missing-linkage` | `api_companies_missing_linkage` |
| GET | `/api/companies/missing-location` | `api_companies_missing_location` |

### Policy

| Method | Path | Handler |
|---|---|---|
| GET | `/api/policy/summary` | `api_policy_summary` |
| GET | `/api/policy/companies` | `api_policy_companies` |
| GET | `/api/policy/company/<tax_id>` | `api_policy_company` |
| GET | `/api/policy/company/<tax_id>/summary` | `api_policy_company_summary` |
| GET | `/api/policy/company/<tax_id>/table` | `api_policy_company_table` |
| GET | `/api/policy/company/<tax_id>/trend` | `api_policy_company_trend` |
| GET | `/api/policy/product-summary` | `api_policy_product_summary` |
| GET | `/api/policy/subclass-summary` | `api_policy_subclass_summary` |
| GET | `/api/policy/yearly-summary` | `api_policy_yearly_summary` |
| GET | `/api/policy/loss-ratio-ranking` | `api_policy_loss_ratio_ranking` |
| GET | `/api/policy/high-loss` | `api_policy_high_loss` |
| GET | `/api/policy/exposure` | `api_policy_exposure` |

### Linkage

| Method | Path | Handler |
|---|---|---|
| GET | `/api/linkage/summary` | `api_linkage_summary` |
| GET | `/api/linkage/graph` | `api_linkage_graph` |
| GET | `/api/linkage/company/<tax_id>` | `api_linkage_company` |
| GET | `/api/linkage/director/<director_id>` | `api_linkage_director` |
| GET | `/api/linkage/key-connectors` | `api_linkage_key_connectors` |
| GET | `/api/linkage/shared-directors` | `api_linkage_shared_directors` |
| GET | `/api/linkage/exposure-by-director` | `api_linkage_exposure_by_director` |

### Flood / Spatial

| Method | Path | Handler |
|---|---|---|
| GET | `/api/flood/summary` | `api_flood_summary` |
| GET | `/api/flood/rainfall/latest` | `api_flood_rainfall_latest` |
| GET | `/api/flood/waterlevel/latest` | `api_flood_waterlevel_latest` |
| GET | `/api/flood/dam/large/latest` | `api_flood_large_dam_latest` |
| GET | `/api/flood/dam/medium/latest` | `api_flood_medium_dam_latest` |
| GET | `/api/flood/computed-risk` | `api_flood_computed_risk` |
| GET | `/api/flood/boundaries/province` | `api_flood_province_boundaries` |
| GET | `/api/flood/boundaries/basin` | `api_flood_basin_boundaries` |
| POST | `/api/flood/refresh` | `api_flood_refresh` |
| GET | `/api/spatial/company-flood-context` | `api_spatial_company_flood_context` |
| GET | `/api/spatial/company/<tax_id>/flood-context` | `api_spatial_company_single_flood_context` |
| GET | `/api/spatial/policy-flood-exposure` | `api_spatial_policy_flood_exposure` |
| GET | `/api/spatial/province-risk-exposure` | `api_spatial_province_risk_exposure` |
| GET | `/api/spatial/nearest-stations/<tax_id>` | `api_spatial_nearest_stations` |

### Map

| Method | Path | Handler |
|---|---|---|
| GET | `/api/map/layers` | `api_map_layers` |
| GET | `/api/map/flood` | `api_map_flood` |
| GET | `/api/map/companies` | `api_map_companies` |
| GET | `/api/map/policy-exposure` | `api_map_policy_exposure` |
| GET | `/api/map/linkage-lines` | `api_map_linkage_lines` |
| GET | `/api/map/branches` | `api_map_branches` |
| GET | `/api/map/heatmap` | `api_map_heatmap` |
| GET | `/api/map/selected-context` | `api_map_selected_context` |

### Filter

| Method | Path | Handler |
|---|---|---|
| GET | `/api/filter/fields` | `api_filter_fields` |
| GET | `/api/filter/quick-presets` | `api_filter_quick_presets` |
| POST | `/api/filter/preview` | `api_filter_preview` |
| POST | `/api/filter/apply` | `api_filter_apply` |
| POST | `/api/filter/save-view` | `api_filter_save_view` |
| GET | `/api/filter/saved-views` | `api_filter_saved_views` |
| GET | `/api/filter/saved-views/<view_id>` | `api_filter_saved_view_detail` |
| PUT | `/api/filter/saved-views/<view_id>` | `api_filter_saved_view_update` |
| DELETE | `/api/filter/saved-views/<view_id>` | `api_filter_saved_view_delete` |

### Data Quality

| Method | Path | Handler |
|---|---|---|
| GET | `/api/data-quality/summary` | `api_data_quality_summary` |
| GET | `/api/data-quality/tax-id` | `api_data_quality_tax_id` |
| GET | `/api/data-quality/coordinates` | `api_data_quality_coordinates` |
| GET | `/api/data-quality/policy` | `api_data_quality_policy` |
| GET | `/api/data-quality/linkage` | `api_data_quality_linkage` |
| GET | `/api/data-quality/spatial-join` | `api_data_quality_spatial_join` |
| GET | `/api/data-quality/status-conflicts` | `api_data_quality_status_conflicts` |

### Package / Public

| Method | Path | Handler |
|---|---|---|
| POST | `/api/packages/preview` | `api_package_preview` |
| POST | `/api/packages/generate` | `api_package_generate` |
| GET | `/api/packages` | `api_package_list` |
| GET | `/api/packages/<package_id>` | `api_package_detail` |
| GET | `/api/packages/<package_id>/download` | `api_package_download` |
| POST | `/api/packages/<package_id>/disable` | `api_package_disable` |
| DELETE | `/api/packages/<package_id>` | `api_package_delete` |
| GET | `/api/packages/<package_id>/meta` | `public_package_meta` |
| GET | `/api/packages/<package_id>/data` | `public_package_data` |
| GET | `/api/packages/<package_id>/summary` | `public_package_summary` |
| GET | `/api/packages/<package_id>/map` | `public_package_map` |
| GET | `/api/packages/<package_id>/charts` | `public_package_charts` |
| GET | `/api/packages/<package_id>/tables` | `public_package_tables` |
| POST | `/api/packages/<package_id>/access-log` | `public_package_access_log` |

