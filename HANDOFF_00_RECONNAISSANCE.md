# Handoff 00 — Technical Reconnaissance

**Role:** Technical lead and provider-contract auditor  
**Stage:** 00 — reconnaissance before styling or website implementation  
**Date:** 2026-08-28 (Asia/Singapore)

## Summary

The provider repository and deployed API are now both readable. The provider is a FastAPI/PostgreSQL service with a typed `website-2026-08` contract group. A website can be built against real calendar, tournament, player, participant, completed-result, live-state, readiness, capability, and validated H2H contracts. Rankings, official brackets, forecasts, and tournament simulations must remain unavailable or withheld until their returned prerequisites are satisfied.

The current website project itself has no web application yet; it contains the API Server and Canvas artifacts. This handoff is an implementation map, not a claim that the website is complete.

## Files changed

- `PROJECT_STATUS.md`
- `ENDPOINT_INVENTORY.md`
- `CONTRACT_PACK.md`
- `PROVIDER_CAPABILITY_MATRIX.md`
- `TODO.md`
- `HANDOFF_00_RECONNAISSANCE.md`

No provider repository files, Render settings, Neon settings, or production data were changed.

## Provider source inspected

- Repository: `https://github.com/Kaskksksks/badminton-bwf-api`
- Branch: `main`
- Commit: `2ad9e3e440618294692c50fd96453d3198fd74a4`
- Latest commit subject: `feat: expose bounded import batch diagnostics`
- Route registration: `app/api/v1/website_routes.py`, `app/api/v1/routes.py`, `app/main.py`
- Website schemas: `app/api/v1/website_contract.py`
- Website read services: `app/api/v1/website_contract_service.py`
- Senior classifier: `app/ingestion/approved_scope.py`
- Calendar/draw source: `app/ingestion/calendar_draws/service.py`
- Model contracts/publication: `app/modeling/service.py`
- Scheduler: `app/polling/scheduler.py`
- Configuration defaults: `app/core/config.py`
- Migrations: `alembic/versions/0001_initial_schema.py` through `0006_evidence_gated_model_contracts.py`
- Tests include senior scope, Para/junior exclusion, calendar ingestion, draw topology, website contract behavior, modeling, rankings, worker safety, and integration routes.

## Provider endpoints inspected

Safe read-only requests were made to:

- `GET https://badminton-bwf-api.onrender.com/openapi.json`
- `GET https://badminton-bwf-api.onrender.com/docs`
- `GET https://badminton-bwf-api.onrender.com/api/v1/health`
- `GET https://badminton-bwf-api.onrender.com/api/v1/data-status`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/calendar?page=1&page_size=1`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/calendar/73bfb1ea-41f5-4669-8cd1-3fcf9e31e811/draw-documents`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/calendar/73bfb1ea-41f5-4669-8cd1-3fcf9e31e811/brackets/MS`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/calendar/73bfb1ea-41f5-4669-8cd1-3fcf9e31e811/simulation`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/active-participants`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/model-contract`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/model-readiness`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/capabilities`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/matches?scope=live&page=1&page_size=1`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/tournaments?page=1&page_size=1`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/players?page=1&page_size=1`
- `GET https://badminton-bwf-api.onrender.com/api/v1/website/rankings?page=1&page_size=1`

Observed response classes:

- HTTP 200 populated: OpenAPI, docs, health at one timestamp, calendar, draw metadata, readiness, capabilities, tournaments, players.
- HTTP 200 empty/explicit unavailable: live match scope at the sampled time, rankings, bracket data, simulation snapshot.
- HTTP 429: Cloudflare challenge/rate-limit HTML on several bounded probes.
- HTTP 502: transient health/deployment-path failure.
- HTTP 503: data-status and some early capability probes.
- HTTP 404: unsupported `/healthz` path; this was not treated as provider health.

## Test and validation results

Command run:

```text
cd /tmp/bwf-provider && python -m compileall -q app tests
```

Result: **PASS**.

Command attempted:

```text
cd /tmp/bwf-provider && python -m pytest -q
```

Result: **BLOCKED** because the environment has no `pytest` module installed. No test result was invented. The provider checkout contains 106 test functions by a source scan, but that count is not a test execution result.

The provider’s committed `Implementation_Report.md` says an earlier automated suite had 6 passing tests, but that statement is historical repository documentation and was not treated as a current run.

## Assumptions deliberately avoided

- No endpoint was labeled available solely because it exists in OpenAPI or source.
- No missing bracket was inferred from match rows.
- No forecast, ranking, confidence, Elo value, analyst conclusion, or simulation was generated locally.
- No live score timestamp was treated as rally/event time.
- No provider capability was inferred from migration presence alone.
- No Render/Neon setting or secret was inspected or changed.
- No admin route, collector, model run, parser job, or mutating request was called.
- No browser-side provider credential or direct provider URL was proposed.

## Unresolved blockers

1. There is no website application in the current project yet.
2. The deployed provider does not expose its Alembic revision or full scheduler configuration through the audited read endpoints.
3. The direct draw PDF is captured but remains `CAPTURED_REVIEW_REQUIRED`; official topology is not validated/reconciled.
4. The model contract reports an active model and validated H2H snapshots, but there are zero published forecast and simulation snapshots.
5. Rankings have no complete stored snapshot.
6. The provider has intermittent 429/502/503 behavior that the website must render explicitly and retry conservatively.

## Exact next steps for the website agent

1. Create a server-backed web application; do not add a browser-side sports database.
2. Add a server-only provider client using `BADMINTON_API_BASE_URL`.
3. Implement website routes for calendar, draw metadata, participants, matches, players, tournaments, capabilities, readiness, model contract, and H2H.
4. Preserve the response envelopes, provenance, nulls, pagination, and exact capability reasons.
5. Implement `loading`, populated/partial, empty, withheld, unavailable, and error states independently per endpoint.
6. Keep rankings, brackets, forecast fields, and simulations visibly withheld until live provider contracts return validated populated snapshots.
7. Before claiming any provider-side activation, obtain an authorized verification response rather than reading source flags or migration files.
