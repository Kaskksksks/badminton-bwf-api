# Badminton Data Platform API

A provenance-aware FastAPI and PostgreSQL service for historical badminton results and BWF live ingestion. The implementation preserves the supplied historical seed as traceable source evidence through **22 August 2026**, then begins BWF Match Centre ingestion on **23 August 2026**. It is deliberately an API and ingestion platform rather than a standalone analytics application.

## What is implemented

The service has a normalized relational core for tournaments, events, players, participants, matches, games, source identifiers, raw evidence, import batches, staged rows, record lineage, reconciliation cases, and exclusions. It supports singles and doubles without collapsing pair members into a single player field. The initial historical import stages every CSV row before canonicalization and retains duplicate/excluded evidence.

| Capability | Implementation status |
|---|---|
| Historical seed integrity and staged import | Implemented |
| Source artifacts, hashes, import batches, staged rows, and lineage | Implemented |
| Exact duplicate reconciliation | Implemented; source copies are retained |
| Raw score preservation and conservative game parsing | Implemented |
| BWF Match Centre client for observed JSON routes | Implemented |
| Cutover enforcement from 23 August 2026 | Implemented |
| Adaptive polling decision engine and worker entry point | Implemented |
| Immutable changed live game-state observations | Implemented |
| Live participant-context linkage for active eligibility | Implemented |
| Conservative 11-point interval assessment | Implemented |
| Coverage-aware interval statistics foundation | Implemented |
| Versioned FastAPI public and protected-admin endpoints | Implemented |
| Evidence-gated Elo model, forecast, H2H, and simulation producers | Implemented; requires eligible data and validated draw topology |
| Alembic baseline migration and Docker Compose topology | Implemented |

## Data-source rules

The BWF adapter uses only the Match Centre JSON routes observed during source discovery. It does not scrape rendered HTML or accept arbitrary remote targets.

| Operation | Route |
|---|---|
| Current tournaments | `/api/match-center/vue-current-live` |
| Tournament detail | `/api/match-center/vue-tournament-detail?tmtId=…` |
| Live matches by tournament | `/api/match-center/vue-live-matches?tmtId=…&tmtType=0` |
| Per-match live enrichment | `/api/match-center/vue-live-single?tmtId=…&matchId=…` |

The source is an undocumented interface. Responses are retained as raw ingestion records, contract failures are not silently normalized, and source data is never called from a public API request.

## Historical seed behavior

The supplied seed package is imported only through `scripts/import_historical_seed.py`. The importer verifies the manifest checksums, registers source artifacts, stages every `matches.csv` source row with its original row number and row hash, validates it, normalizes defensible facts, and links all source rows to a canonical match or a reconciliation decision.

The audited package has 94,772 staged match rows. The importer produced 94,564 canonical matches and 208 exact-duplicate source-row decisions. Four documented extension walkovers are retained in the exclusion ledger rather than being deleted. The baseline’s player names are stored as unresolved aliases unless official BWF identity evidence is available; player IDs are never fabricated.

## Live game-state and interval behavior

Each changed BWF score state creates an immutable `game_state_observations` row with a platform collection timestamp, raw-response link, status, court, score, and optional source time. Repeated identical polls do not create duplicate state rows.

The platform models the 11-point interval with explicit precision. An observed state such as 11–8 identifies the interval score and side, but its collection timestamp does not claim to be the rally timestamp. Therefore `interval_exact` stays `false` unless a future BWF source explicitly supplies an exact interval event/time. Sparse states such as 12–11 are recorded as an inferred threshold crossing; 11–11 remains ambiguous without a rally sequence.

Derived comeback, lead-conversion, closing, post-interval, and score-state metrics are computed only from sufficient stored observations in `app/statistics`. Historical seed rows do not get fabricated live snapshots or interval statistics.

## Configuration

Copy `.env.example` to `.env` and set real values. PostgreSQL is the deployment database. SQLite is used only for the included local/test validation workflow.

```bash
cp .env.example .env
# Edit DATABASE_URL, POSTGRES_PASSWORD, ADMIN_API_KEY, CORS_ORIGINS, and SEED_DATASET_ROOT.
```

| Setting | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL SQLAlchemy connection string |
| `HISTORICAL_SEED_CUTOFF_DATE` | Last date eligible for the frozen seed; defaults to `2026-08-22` |
| `BWF_INGESTION_START_DATE` | First date accepted from BWF live ingestion; defaults to `2026-08-23` |
| `POLL_IDLE_MINUTES` | No-active-tournament cadence |
| `POLL_TOURNAMENT_MINUTES` | Active-tournament cadence |
| `POLL_LIVE_MATCH_SECONDS` | Live-match target cadence |
| `SCHEDULER_ENABLED` | Enables in-process scheduler only when explicitly set; default `false` |
| `BWF_RANKINGS_ENABLED` / `BWF_RANKINGS_PERMISSION_REFERENCE` | Enables authorised ranking collection only after permission/licensing is confirmed |
| `BWF_PLAYER_PROFILES_ENABLED` / `BWF_PLAYER_PROFILES_PERMISSION_REFERENCE` | Enables authorised player-profile collection only after permission/licensing is confirmed |
| `BWF_CALENDAR_ENABLED` / `BWF_CALENDAR_PERMISSION_REFERENCE` | Enables authorised corporate-calendar and direct-draw collection only after permission is confirmed |
| `BWF_DRAW_PARSER_ENABLED` | Extracts explicit discipline sections from captured PDFs into review-required topology candidates |
| `MODELING_SCHEDULER_ENABLED` | Enables evidence-gated model/forecast/H2H/simulation publication jobs |
| `ADMIN_API_KEY` | Required for protected administrative endpoints |

## Local development

Install the package and tests:

```bash
pip install -e '.[test]'
```

Create the local validation database and import the audited package:

```bash
export DATABASE_URL='sqlite+pysqlite:///./data/historical_seed_validation.db'
python scripts/import_historical_seed.py \
  --dataset-root /absolute/path/to/bwf_match_data_2010_2026_08_22 \
  --create-tables
```

For PostgreSQL, use Alembic before importing data:

```bash
alembic upgrade head
python scripts/import_historical_seed.py --dataset-root "$SEED_DATASET_ROOT"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The OpenAPI and Swagger interface is available at `http://localhost:8000/docs`.

## Containers

Create `.env` with a strong `POSTGRES_PASSWORD` and a non-default `ADMIN_API_KEY`, then run:

```bash
docker compose up --build
```

Compose creates PostgreSQL, a public API service, and a separate worker. The API applies Alembic migrations and serves port 8000. The worker applies the same migration, then runs the controlled scheduler. It is deliberately separate from API requests so frontend traffic never performs source collection.

## API contract

Public endpoints use `/api/v1` and return consistent `data` plus `meta` envelopes. Implemented resources include players, rankings, tournaments, events, matches, games, live states, snapshots, 11-point interval assessments, live matches, head-to-head, insight scaffolding, model readiness, forecasts, official draw metadata/topology, tournament simulations, health, data status, and statistics coverage. Publication endpoints return explicit evidence-based withholding reasons until their prerequisites are met.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | API and dependency status |
| `GET /api/v1/data-status` | Historical cutover and source status |
| `GET /api/v1/matches` | Paginated/filterable canonical match read model |
| `GET /api/v1/matches/{id}/games` | Structured final/parsed games |
| `GET /api/v1/matches/{id}/snapshots` | Immutable BWF-originated changed score states |
| `GET /api/v1/matches/{id}/games/{n}/states` | Game-specific observations with precision metadata |
| `GET /api/v1/matches/{id}/games/{n}/intervals` | Derived interval assessment and exactness flag |
| `GET /api/v1/live/matches` | Database-only current live read model |
| `GET /api/v1/participants/{id}/interval-statistics` | Coverage-aware derived interval metrics |
| `GET /api/v1/admin/import-batches` | Protected import status and counts |
| `POST /api/v1/admin/rankings/run` | Protected one-shot authorised ranking ingestion |
| `POST /api/v1/admin/draws/documents/{id}/collect-and-parse` | Re-fetch the exact captured PDF, verify its hash, and stage real BWF table candidates |
| `POST /api/v1/admin/draws/documents/{id}/parse` | Stage topology candidates from an exact captured-PDF hash and supplied extracted text |
| `GET /api/v1/admin/draws/topologies/{id}` | Inspect staged node IDs and reconciliation status |
| `POST /api/v1/admin/draws/nodes/{id}/reconcile` | Record explicit reviewer-confirmed canonical-match linkage |
| `POST /api/v1/admin/draws/topologies/{id}/publish` | Publish only a fully reconciled topology |
| `POST /api/v1/admin/modeling/run` | Train/evaluate and publish eligible model outputs |

## Testing

Tests do not call BWF by default. They use isolated SQLite fixtures and mock HTTP transport to verify source-route contracts, historical staging, duplicate lineage, conservative score handling, game-state deduplication, non-fabricated interval precision, statistics eligibility, and API protection.

```bash
DATABASE_URL='sqlite+pysqlite:///:memory:' pytest -q
```

## Operational safeguards

The service does not treat collection time as a BWF rally timestamp, does not fabricate player IDs for name-only history, does not discard exact duplicate source rows, and does not allow public or administrative APIs to scrape arbitrary URLs. Configuration, deployment topology, BWF request behavior, and administrative credentials are environment-driven.
