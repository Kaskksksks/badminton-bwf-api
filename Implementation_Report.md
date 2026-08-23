# Badminton Data Platform: Implementation Report

**Implementation status:** Completed in the local development workspace  
**Date:** 23 August 2026  
**Scope delivered:** Historical seed import through 22 August 2026, BWF ingestion architecture from 23 August 2026, immutable live game-state storage, derived-statistics foundation, versioned FastAPI reads, tests, migrations, and container packaging.

## Delivered system

The delivered service is a Python FastAPI application backed by SQLAlchemy and designed for PostgreSQL deployment. It implements the approved boundary between the user-supplied historical seed and live BWF data. The historical package is treated as immutable source evidence, while the BWF Match Centre adapter is isolated behind a source-specific client using only observed JSON routes.

| Layer | Delivered behavior |
|---|---|
| Source registry | Separate `HISTORICAL_SEED` and `BWF_LIVE` source records; no source identity is inferred from display names alone. |
| Provenance | Dataset versions, import batches, source artifacts, staged rows, raw ingestion records, record lineage, reconciliation cases, and exclusion records. |
| Historical import | Manifest/hash verification, full source-row staging, validation, exact-duplicate reconciliation, raw-score preservation, source aliasing, tournament-tier preservation, and canonical match/game writes. |
| Canonical model | Tournaments, events, singles/pair participants, player aliases, matches, side context, structured games, source identifiers, and source completeness/status fields. |
| Live BWF adapter | Current tournament and live-match requests via the previously observed BWF Match Centre JSON routes; response capture before normalization. |
| Game-state model | Immutable changed score-state observations, collection/source time distinction, timing basis, 11-point interval assessment, and versioned derivation fields. |
| Statistics foundation | Coverage-aware interval lead conversion, comeback, deficit, and post-interval differential calculations. |
| API | `/api/v1` endpoints for health, data status, matches, games, snapshots/states, intervals, live matches, tournaments, events, H2H, statistics coverage, and protected import-batch status. |
| Operations | Environment-driven settings, structured logging, Alembic baseline migration, Docker Compose API/worker/PostgreSQL topology, and an adaptive polling decision engine. |

## Historical import verification

A full local validation import was executed against the supplied audited historical package. The import did not execute the package’s own scripts. The application’s importer independently registered the source artifacts, staged all CSV rows, and preserved lineage for every decision.

| Verification item | Result |
|---|---:|
| Latest import-batch status | `SUCCEEDED` |
| Staged historical source rows | 94,772 |
| Canonical matches after exact reconciliation | 94,564 |
| Exact duplicate lineage decisions | 208 |
| Rejected historical rows | 0 |
| Retained excluded source records | 4 |

These results match the audited package’s expected totals. Exact duplicate source rows remain in `staged_import_records` and `record_lineage`; they were not deleted. The four walkover records are retained in `excluded_source_records` with their source identities and reasons.

## Live score and interval correctness

The system makes an explicit distinction between an observation and an event. `game_state_observations.observed_at` denotes when the platform collected a changed BWF score state. `source_observed_at` remains null unless a source explicitly supplies such a time. An observed 11–8 score can establish the score and interval side, but cannot establish the rally time; consequently `interval_exact` remains false. Sparse values such as 12–11 produce an inferred crossing, while 11–11 remains undetermined without source event/rally evidence.

> **No game start time, game end time, per-game duration, interval timestamp, rally order, or precision is fabricated.** The raw response and immutable score-state observations are retained so an improved official source contract can be used later without re-fetching old matches.

## Verification results

The automated suite completed successfully with **6 passing tests**. The tests cover service configuration, staged historical imports, exact duplicate lineage, nonstandard score retention, BWF client path contracts through mock transport, game-state deduplication, interval exactness safeguards, API match reads, admin protection, and interval-statistics eligibility. The Alembic baseline migration also applied successfully to a fresh validation database.

## Deployment and handoff

The service can be run locally against a PostgreSQL database or packaged with `docker compose`. The public API and worker are separate services. The worker is the only process that performs BWF synchronization; public API requests are database reads only. Deployment settings—including the database URL, CORS allow-list, BWF source base, cutover dates, polling cadence, raw retention, and administrator API key—are provided through environment variables in `.env`.

The `README.md` in the service directory contains the exact local import, migration, testing, and Docker commands. The source archive includes the architecture and data-audit documentation prepared earlier in the task.

## Operational limits to acknowledge

The BWF Match Centre routes were verified as currently used by the official client but are not treated as a formal stable API contract. Their schema, availability, rate policy, and freshness behavior must be monitored. The repository contains an adapter, raw capture, validation, and contract-test seams so upstream changes fail visibly rather than silently altering canonical records.

The local full-seed validation database is a development artifact and is intentionally excluded from the handoff archive. Before production use, deploy PostgreSQL, apply Alembic migrations, place the approved seed dataset in controlled storage, set a secure `ADMIN_API_KEY`, and configure the worker according to the chosen hosting model.
