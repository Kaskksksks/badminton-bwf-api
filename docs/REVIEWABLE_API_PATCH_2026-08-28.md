# Reviewable API Patch — 28 August 2026

## Scope and non-negotiable controls

This is a **local-only review patch** against `main` at `50ecd7a`. It does not push, deploy, invoke a collector, alter Render or Neon variables, change the approved twelve-hour corporate-calendar cadence, expand BWF source scope, or modify the global collection lock, byte budget, or OOM protections.

The audit confirmed that the current branch already contains read-only calendar/document routes, an active-senior participant selector, review-only direct-BWF-PDF topology staging, and stored model-contract tables. Those source files are **not evidence that the deployed public API currently exposes or has populated those features**. The current provider deployment must still be treated as unavailable for any capability until a separately approved deployment and post-deploy contract check prove otherwise.

## Local patch summary

| Area | Local change | Public-safety effect |
| --- | --- | --- |
| Website Head-to-Head | Adds `GET /api/v1/website/head-to-head?participant_a_id=…&participant_b_id=…`. | Returns a stored validated summary only when both distinct subjects are confirmed, current, approved-senior participants. It returns no forecast, probability, scoreline, or browser-generated output. |
| Official result precedence | Withholds the public forecast payload after a result or terminal result status exists. | A settled official result cannot be displayed as a live prediction; an immutable historic snapshot remains an audit record rather than a forecast surface. |
| Capability metadata | Adds typed availability/count metadata for persisted calendar entries, direct draw document metadata, current senior participants, and complete senior ranking snapshots. | The website can distinguish "not deployed/populated" from a safe empty eligible dataset without initiating any source collection. |
| Model publication | Adds an explicit `modeling_publication_approved` setting, defaulting to `false`. | An enabled scheduler cannot publish sporting forecasts merely because qualifying-looking data exists. No environment value was edited. |
| Simulation truthfulness | Removes the active use of independent draw-node probabilities as a tournament simulation and returns a clear unavailable state. | The API does not mislabel independent matchup calculations as Monte Carlo advancement probabilities. |

## Public contract changes proposed for review

The newly local Head-to-Head route uses only internal participant IDs supplied by the already read-only `active-participants` catalogue. Its contract has a standard availability envelope and optional persisted snapshot:

```text
GET /api/v1/website/head-to-head?participant_a_id=<uuid>&participant_b_id=<uuid>

data:
  participant_a_id: string
  participant_b_id: string
  availability: { available, reason, prerequisites, eligible_record_count }
  snapshot: null | {
    participant_a_id, participant_b_id, input_cutoff,
    eligible_meetings, participant_a_wins, participant_b_wins, evidence
  }
meta: { api_version, contract_version, timestamp, source }
```

The snapshot is reordered only for the caller’s requested A/B display order. Its counts originate from the immutable stored summary; it is not recomputed on the request path. Both participants must have complete confirmed membership, a completed or retired match within 52 weeks, and an approved senior competition context. A doubles subject therefore remains a verified pair rather than two independent singles players.

The local capability payload adds `calendar`, `draw_documents`, and `active_participants` keys with `available`, `eligible_record_count`, a source/reason, and `read_only` where relevant. `rankings.available` now requires a complete **senior** snapshot rather than any stored snapshot.

## Existing architecture verified on main

| Workstream | Current main-branch evidence | Status for public activation |
| --- | --- | --- |
| Calendar and draw metadata | `official_tournament_calendar_*` tables; read-only `/website/calendar` and calendar-entry document metadata route; only direct calendar-derived BWF PDFs. | Implementation exists locally. It needs the user-approved deployment and a post-deploy populated-response check. |
| Active participant catalogue | Confirmed complete member identity plus completed/retired approved-senior context within 52 weeks. | Implementation exists locally. It remains empty until authorised identity/profile processing produces qualifying confirmed records. |
| Official rankings | Immutable senior `RankingSnapshot` / `RankingEntry` tables and an opt-in, permission-gated ingestion job. | No current complete senior snapshot may be asserted without source permission, completed ingestion, and response validation. |
| Draw parser and reconciliation | Direct-PDF extraction yields `PENDING_REVIEW` nodes only; explicit reviewer reconciliation is required before topology publication. | Not a complete directed bracket graph yet. It cannot drive a tournament simulation. |
| Forecasts and Head-to-Head | Immutable model/forecast/H2H tables and a deterministic Elo baseline pipeline exist. | This patch makes public publication opt-in. A model is not approved or active in the deployed API. |
| Simulations, analyst, evaluation | Storage boundary and availability envelopes exist. | Not activated. Directed draw transitions, reviewed model validation, true Monte Carlo advancement output, structured citations, and preserved evaluation slices remain required. |

## Required next implementation patch after this review

The following work is intentionally **not** included in this local patch. It needs a distinct reviewed diff and tests, rather than being inferred from source labels or made live prematurely.

1. Extend the direct-PDF topology format with explicit directed predecessor/successor edges, round cardinality, byes, and node revision hashes. The parser must continue to produce `PENDING_REVIEW`; publication requires reviewer acceptance of all edges and canonical match reconciliation.
2. Add immutable forecast evaluation rows linked to the exact pre-match snapshot, official result, data cutoff, model version, and calibration slice. Calculate accuracy, Brier score, and log loss only from those records; do not retroactively overwrite forecasts.
3. Implement a true deterministic-seed Monte Carlo bracket engine using the validated directed topology and persisted pairwise forecasts. Persist advancement probabilities, favourite ordering, draw difficulty, run seed/count, cutoff, model/topology revisions, and result-driven re-simulation lineage.
4. Add a constrained analyst response contract whose every sporting assertion carries an evidence reference. The service must return a typed unavailable response when no cited structured evidence exists.
5. Add a deployment migration only if the directed topology and evaluation tables require new columns/tables. The patch reviewed here contains **no migration**, because its changes reuse existing snapshot tables and add only an endpoint/schema behavior.

## Validation performed locally

The provider project was installed and tested only in the isolated sandbox with `DATABASE_URL=sqlite+pysqlite:///:memory:`. No production database was contacted.

| Check | Result |
| --- | --- |
| Baseline `main` regression suite | 118 passed; one upstream FastAPI/TestClient deprecation warning. |
| Focused local patch suites | 17 passed; one upstream warning. |
| Complete local patch suite | 121 passed; one upstream warning. |
| Diff integrity | `git diff --check` passed. |
| Remote state | No commit, push, pull request, Render action, deployment, migration application, environment-variable edit, or collector invocation was performed. |

## Approval gates

> **No remote action is approved by this local patch alone.**

Before any push, the reviewer should approve the local file diff and the new `MODELING_PUBLICATION_APPROVED` default-false gate. Before any deploy, the reviewer should separately approve the exact branch/commit and confirm the established calendar schedule, collection lock, source budget, OOM controls, authorised BWF-only boundary, Render environment, and Neon schema are unchanged. After deployment, a read-only OpenAPI and representative endpoint check must confirm the deployed contract version, populated calendar/document metadata, and all unavailable states before the website consumes a new capability.
