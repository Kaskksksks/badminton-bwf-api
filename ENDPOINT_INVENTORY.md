# BWF Provider Endpoint Inventory

**Audit date:** 2026-08-28  
**Repository source:** `https://github.com/Kaskksksks/badminton-bwf-api`, `main`, commit `2ad9e3e440618294692c50fd96453d3198fd74a4`  
**Deployed base:** `https://badminton-bwf-api.onrender.com`  
**Rule:** “Available” below means a live response was observed, not merely that a route exists in source.

## Website-facing routes

| Route | Provider source | Expected response schema | Deployed observation | Auth | Freshness/side effects | Website surface |
|---|---|---|---|---|---|---|
| `GET /api/v1/website/calendar` | `app/api/v1/website_routes.py`; `website_contract_service.py` | `WebsiteCalendarListResponse`: `data[]`, `pagination`, `meta`; each entry includes `CalendarProvenance` | **Available.** HTTP 200; 19 entries; latest persisted corporate-calendar snapshot was returned. Later probes also saw HTTP 429, so callers need retry/error handling. | None in OpenAPI | Read-only persisted snapshot; no source request. Ordered by start date; latest row per source tournament ID. | Calendar/tournament discovery |
| `GET /api/v1/website/calendar/{calendar_entry_id}/draw-documents` | `website_routes.py`; `website_contract_service.py` | `WebsiteDrawDocumentListResponse`: metadata-only `data[]`, `meta` | **Available.** HTTP 200 for China Masters; one direct BWF PDF metadata record, `CAPTURED_REVIEW_REQUIRED`. | None | Read-only metadata; never returns PDF bytes or triggers collection. | Draw provenance/status |
| `GET /api/v1/website/active-participants` | `website_routes.py`; `website_contract_service.py` | `SeniorParticipantListResponse`: confirmed player/pair records plus pagination/meta | **Available.** HTTP 200 response observed with confirmed active participants. Later probe was rate limited. | None | Read-only. Requires complete confirmed membership and a dated completed/retired eligible match within 52 weeks. | Participant selector, active roster |
| `GET /api/v1/website/matches` | `website_routes.py` | `WebsiteMatchListResponse`: `data[]`, `PageInfo`, `ApiMeta`; `scope=all|live|scheduled|completed` | **Available.** HTTP 200 for `scope=live`; empty at the probe time, total 0. | None | Read-only persisted data; filters in SQL; public results are restricted to approved tournaments. | Match list/live/completed/scheduled views |
| `GET /api/v1/website/matches/{match_id}` | `website_routes.py` | `WebsiteMatchResponse`: one `WebsiteMatch` plus meta | **Not endpoint-probed with a valid match ID.** Source contract is typed; invalid/unknown or ineligible IDs return 404. | None | Read-only. Completed official result fields supersede forecast display. | Match detail |
| `GET /api/v1/website/matches/{match_id}/forecast` | `website_routes.py`; `match_forecast_snapshot` | `WebsiteMatchForecastResponse`: overall `ContractAvailability`, four field-level availability objects, optional snapshot | **Not endpoint-probed with a valid match ID.** Local contract test returns HTTP 200 with explicit withholding for an unknown match. Live model contract reports zero published forecasts. | None | Read-only published snapshot only; never computes on request. | Forecast panel, currently withheld |
| `GET /api/v1/website/tournaments` | `website_routes.py` | `WebsiteTournamentListResponse`: `TournamentSummary[]`, pagination, meta | **Available.** HTTP 200; total 267. | None | Read-only; reruns approved-scope classification before delivery. | Tournament index |
| `GET /api/v1/website/tournaments/{tournament_id}/events` | `website_routes.py` | `WebsiteEventListResponse`: normalized `EventSummary[]`, meta | **Not endpoint-probed.** Unknown or ineligible tournament returns 404. | None | Read-only; event discipline is normalized to `MS|WS|MD|WD|XD|UNKNOWN`. | Tournament event tabs/filter |
| `GET /api/v1/website/players` | `website_routes.py` | `WebsitePlayerListResponse`: `WebsitePlayer[]`, pagination, meta | **Available.** HTTP 200; total 2759; sample identity `CONFIRMED`. | None | Read-only stored official profile identities. | Player search |
| `GET /api/v1/website/players/{player_id}/matches` | `website_routes.py` | `WebsiteMatchListResponse` | **Not endpoint-probed.** Requires a confirmed player; otherwise 404. | None | Read-only, bounded history, approved scope only. | Player history |
| `GET /api/v1/website/rankings` | `website_routes.py` | `WebsiteRankingListResponse`: entries, pagination, optional snapshot, issues, meta | **Available route, unavailable data.** HTTP 200 with empty data, null snapshot, `ranking_snapshot_unavailable`. | None | Read-only stored complete senior snapshot; no BWF request. | Rankings, currently unavailable |
| `GET /api/v1/website/head-to-head/{participant_a}/{participant_b}` | `website_routes.py`; `validated_head_to_head_snapshot` | `WebsiteHeadToHeadResponse`: IDs, `ContractAvailability`, optional validated snapshot, meta | **Capability verified, pair response not sampled.** Live model contract reports 9851 validated records. | None | Read-only immutable validated snapshot; distinct participant IDs required. | H2H comparison |
| `GET /api/v1/website/calendar/{calendar_entry_id}/brackets/{discipline}` | `website_routes.py`; `official_bracket` | `OfficialBracketResponse`: availability, discipline, IDs, node list, meta | **Available as an explicit withheld response.** HTTP 200, `official_document_captured_parser_not_validated`, empty data for MS. | None | Read-only. Requires parser-validated topology and full canonical reconciliation; never infers a bracket from match rows. | Official bracket, currently withheld |
| `GET /api/v1/website/calendar/{calendar_entry_id}/simulation` | `website_routes.py`; `tournament_simulation_snapshot` | `WebsiteTournamentSimulationResponse`: availability, optional snapshot, meta | **Available as an explicit withheld response.** HTTP 200, `canonical_tournament_link_not_available`, null snapshot. | None | Read-only published snapshot only; never simulates on request. | Tournament probabilities, currently withheld |
| `GET /api/v1/website/model-contract` | `website_routes.py`; `model_contract` | `ModelContractResponse`: availability records for model, predictions, H2H, simulations | **Available.** HTTP 200; model true/1, predictions false/0, H2H true/9851, simulations false/0. | None | Read-only persisted counts and prerequisites. | Capability/readiness summary |
| `GET /api/v1/website/model-details` | `website_routes.py`; `active_model_details` | `ActiveModelDetailsResponse`: availability plus optional evaluated model details | **Not endpoint-probed.** Source requires active/evaluated model with cutoff, methodology, input contract, and evaluation summary. | None | Read-only; no model run. | Methodology/evaluation disclosure |
| `GET /api/v1/website/model-readiness` | `website_routes.py`; `app/modeling/service.py` | `ModelReadinessResponse`: corpus readiness object plus meta | **Available.** HTTP 200; 3441 confirmed participants, 16514 approved validated completed matches, publication-ready true. | None | Read-only; explicitly no training or writes. | Model corpus readiness |
| `GET /api/v1/website/capabilities` | `website_routes.py` | `CapabilityResponse`: provider capability map plus meta | **Available.** HTTP 200; rankings/draws/predictions/simulations false, H2H/live states true. | None | Read-only database counts and contract checks. | Global capability matrix |

## Supporting service and generic read routes

| Route | Provider source | Expected schema | Deployed observation | Auth and side effects | Website use |
|---|---|---|---|---|---|
| `GET /` | `app/main.py` | `{service, api_prefix, docs}` | Swagger/root discovery was available during the audit; a later root probe hit a Cloudflare 429 page. | None; read-only | Diagnostics only |
| `GET /openapi.json` | FastAPI-generated from `app/main.py` and routers | OpenAPI 3.1 document | HTTP 200; 47 API paths were enumerated, including the website routes above. | None; read-only | Contract discovery, not browser data |
| `GET /docs` | FastAPI | Swagger UI HTML | HTTP 200 | None; read-only | Operator diagnostics only |
| `GET /api/v1/health` | `app/main.py`; `app/health/service.py` | `{data, meta}`; health includes API/database/collector/source state and timestamps | HTTP 200 observed with healthy API/database and collector configured; a separate probe saw HTTP 502. | None; read-only | Server status badge; do not convert transient failure to empty data |
| `GET /api/v1/data-status` | `app/main.py`; `app/health/service.py` | `{data, meta}` | HTTP 503 observed in a bounded probe. | None; read-only | Optional data freshness diagnostics |
| `GET /api/v1/matches` | `app/api/v1/routes.py` | OpenAPI currently describes a generic object response | Not needed for the first website integration; prefer the typed website route. | None; read-only | Internal fallback only |
| `GET /api/v1/live/matches` | `app/api/v1/routes.py` | Generic object response in OpenAPI | Not independently sampled after the website live route. | None; read-only | Prefer `/website/matches?scope=live` |
| `GET /api/v1/players` | `app/api/v1/routes.py` | Generic object response | Not independently sampled. | None; read-only | Prefer typed website players |
| `GET /api/v1/tournaments` | `app/api/v1/routes.py` | Generic object response | Not independently sampled. | None; read-only | Prefer typed website tournaments |
| `GET /api/v1/rankings` | `app/api/v1/routes.py` | Generic object response; query accepts ranking system, discipline, date, pagination | Not independently sampled. | None; read-only | Prefer typed website rankings |
| `GET /api/v1/head-to-head/{participant_a}/{participant_b}` | `app/api/v1/routes.py` | Generic object response | Not independently sampled. | None; read-only | Prefer typed website H2H |

## Admin and collector routes — not website routes

The OpenAPI document also exposes admin/diagnostic paths under `/api/v1/admin/*`, including identity coverage/review/run, ranking run/diagnostic, modeling run, draw collect/parse/reconcile/publish, and import-batch diagnostics. These must not be called by the browser or website public server as part of a read. Admin routes accept an `X-API-Key` parameter in OpenAPI and include mutating `POST` operations. They are intentionally excluded from the website integration surface.

## Source and contract location

- Route registration: `app/api/v1/website_routes.py`
- Typed website schemas: `app/api/v1/website_contract.py`
- Read-only database contract services: `app/api/v1/website_contract_service.py`
- Approved senior classifier: `app/ingestion/approved_scope.py`
- Calendar/draw ingestion: `app/ingestion/calendar_draws/service.py`
- Model readiness/publication: `app/modeling/service.py`
- Scheduler and cadence gates: `app/polling/scheduler.py`
- Runtime settings: `app/core/config.py`
- Schema revisions: `alembic/versions/0001_initial_schema.py` through `0006_evidence_gated_model_contracts.py`
