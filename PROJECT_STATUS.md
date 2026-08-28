# BWF // Supercomputer — Project Status

**Audit date:** 2026-08-28 (Asia/Singapore)  
**Scope:** Prompt 0 technical reconnaissance and provider-contract audit  
**Website project state:** No website application is present in this project yet. The current project contains the API Server artifact and the Canvas/mockup artifact only.

## Current provider baseline

- Repository: `https://github.com/Kaskksksks/badminton-bwf-api`
- Branch inspected: `main`
- Commit inspected: `2ad9e3e440618294692c50fd96453d3198fd74a4`
- Commit time: `2026-08-28T02:06:17Z`
- Deployed provider: `https://badminton-bwf-api.onrender.com`
- API prefix: `/api/v1`
- OpenAPI title/version: `Badminton Data Platform`, `0.1.0`
- Website contract version emitted by live responses: `website-2026-08`

The repository became publicly readable during this audit. Before that change, GitHub returned 404 to unauthenticated repository requests; no source conclusions were made from the missing repository.

## Verified deployed observations

The provider was queried only with `GET` requests. The observations below are time-stamped by the provider response metadata where available.

| Surface | Observed result |
|---|---|
| `/openapi.json` | HTTP 200; FastAPI OpenAPI 3.1 document. |
| `/docs` | HTTP 200; Swagger UI points to `/openapi.json`. |
| `/api/v1/health` | HTTP 200 observed once with `api_status=ok`, `database_status=ok`, `collector_status=configured`, `live_match_count=193`, last successful collection `2026-08-27T08:11:07.744605+00:00`, latest data timestamp `2026-08-26T05:48:20.343099+00:00`, and zero errors in the prior 24 hours. A separate bounded probe also observed a transient HTTP 502/approximately 20-second response. |
| `/api/v1/website/calendar?page=1&page_size=1` | HTTP 200 at `2026-08-28T03:22:38.365551Z`; total `19`. The first entry was LI-NING China Masters 2026, with BWF Corporate Calendar provenance and `snapshot_status=PARSED`. |
| `/api/v1/website/calendar/{id}/draw-documents` | HTTP 200 for the China Masters entry. One direct PDF metadata record was returned with `parser_status=CAPTURED_REVIEW_REQUIRED`; no PDF bytes were returned. |
| `/api/v1/website/calendar/{id}/brackets/MS` | HTTP 200 with `availability.available=false` and reason `official_document_captured_parser_not_validated`. `data=[]`. |
| `/api/v1/website/calendar/{id}/simulation` | HTTP 200 with `availability.available=false` and reason `canonical_tournament_link_not_available`. `snapshot=null`. |
| `/api/v1/website/model-contract` | HTTP 200. Model availability was `true` with one eligible record; predictions were `false` with zero published records; head-to-head was `true` with `9851` validated records; simulations were `false` with zero published records. |
| `/api/v1/website/model-readiness` | HTTP 200 at `2026-08-28T03:24:31.367390Z`; `publication_ready=true`, `confirmed_participants=3441`, `approved_dated_validated_completed_matches=16514`, corpus through `2026-08-22`. |
| `/api/v1/website/capabilities` | HTTP 200. Rankings were `available=false` (`not_yet_ingested`); draws were `available=false`; predictions were `available=false`; head-to-head was `available=true`; tournament simulations were `available=false`; live states were `available=true` with a partial-score/collection-time caveat. |
| `/api/v1/website/matches?scope=live&page=1&page_size=1` | HTTP 200 at `2026-08-28T03:24:37.387040Z`; `data=[]`, total `0` for that read. This does not contradict the earlier health count because live state is time-dependent and the endpoints use different stored views. |
| `/api/v1/website/tournaments?page=1&page_size=1` | HTTP 200; total `267`. |
| `/api/v1/website/players?page=1&page_size=1` | HTTP 200; total `2759`; returned player identity was `CONFIRMED`. |
| `/api/v1/website/rankings?page=1&page_size=1` | HTTP 200 with `data=[]`, `snapshot=null`, and `issues=["ranking_snapshot_unavailable"]`. |

Additional transient behavior was observed during bounded probing: Cloudflare returned HTTP 429 HTML challenge pages for several requests, and the provider/deployment path returned HTTP 503 for `/api/v1/data-status` and for some early capability probes. Those responses are treated as explicit unavailable/error states, not as empty data.

## What can be built against real data now

1. Server-side provider adapter and browser-safe website routes.
2. Calendar browsing with source provenance, eligibility rationale, and pagination.
3. Draw-document metadata display with parser status and issue text.
4. Tournament, player, participant, and match browsing using the typed website routes.
5. Completed result display using canonical scores and games where returned.
6. Live match display with an explicit timestamp and partial-score caveat.
7. Model readiness/capability panels.
8. Validated head-to-head surface, subject to the requested participant IDs and endpoint response.
9. Honest empty, withheld, unavailable, timeout, 429, 502, and 503 states.

## What must remain withheld

- Rankings until a complete senior ranking snapshot is actually ingested and returned.
- Bracket topology until the captured direct BWF PDF is parser-validated and every node is reconciled to canonical matches.
- Per-match forecasts until a published pre-match snapshot is returned and its probabilities sum to 10,000 basis points.
- Tournament simulations until a canonical tournament link, published reconciled topology, active evaluated model, and published simulation snapshot all exist.
- Any analyst conclusion, confidence, probability, Elo value, or accuracy claim not returned by the provider contract.

## Provider-side activation not verified

The repository contains implementation and migrations, but the following deployment facts were not exposed by the safe read endpoints and must not be claimed as active:

- Whether the deployed database is at Alembic revision `0006_model_contracts`.
- Whether Render environment flags enabled the live worker, calendar scheduler, rankings scheduler, player-profile scheduler, draw parser, or modeling scheduler.
- Whether a controlled calendar/draw parser review has completed.
- Whether canonical draw reconciliation has been performed.
- Whether the published model, forecast snapshots, or simulation snapshots were produced by the current deployment or are complete for all eligible records.
- Any Render or Neon setting change.

## Recommended next action

Build the website as a separate server-backed web application. Keep `BADMINTON_API_BASE_URL` server-side, proxy browser requests through the website server, use the provider’s website contract routes, and preserve the state rules in `CONTRACT_PACK.md`. Do not create a browser-side sports database or invent fallback records.
