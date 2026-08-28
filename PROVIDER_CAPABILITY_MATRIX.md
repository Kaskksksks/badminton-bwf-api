# Provider Capability Matrix

**Audit date:** 2026-08-28  
**Evidence rule:** a capability is marked available only when a deployed response supports it. Repository implementation alone is marked source-only.

| Capability | State | Live evidence | Source evidence | Website decision |
|---|---|---|---|---|
| OpenAPI/route discovery | available | `/openapi.json` HTTP 200; FastAPI document at version 0.1.0 | `app/main.py` and routers | Use the website route group and typed contract, not generic internal payloads. |
| Provider health | partial | `/api/v1/health` returned a healthy 200 once, including database ok and collector configured; a separate probe observed 502 | `app/health/service.py` | Show timestamped health; treat 502/503/timeout as error, not empty data. |
| Stored BWF Corporate calendar | available | HTTP 200; 19 eligible entries; provenance `BWF_CORPORATE_CALENDAR`, parsed snapshot | `app/ingestion/calendar_draws/service.py`; migrations 0004 | Build calendar browsing from persisted metadata only. |
| Direct draw-document metadata | available | HTTP 200; China Masters returned one captured PDF metadata record | migration 0004; `website_contract_service.py` | Display document provenance and parser status, never PDF bytes in the browser. |
| Draw PDF capture | partial | Document exists with `CAPTURED_REVIEW_REQUIRED` | `capture_draw_document` stores immutable metadata and review-required state | Do not present a bracket from capture alone. |
| Parser-validated official brackets | withheld | MS bracket returned HTTP 200 with `official_document_captured_parser_not_validated`, no nodes | migration 0005; `official_bracket` requires `VALIDATED_RECONCILED` | Bracket UI must visibly explain withholding. |
| Canonical draw reconciliation | withheld/not verified | No public response demonstrated reconciled topology; bracket data empty | `record_canonical_reconciliation` and publication gate exist | Treat parser/reconciliation as provider-side pending work. |
| Tournament list | available | HTTP 200; 267 eligible tournaments | `website_routes.py` reruns approved classifier | Build tournament index/detail against website routes. |
| Tournament events | source contract only | Route exists; not safely sampled with a valid tournament ID during this audit | `normalize_event` emits `Discipline` and competition level | Build only after a normal read confirms response. |
| Players and confirmed identities | available | HTTP 200; 2759 players; sampled player `CONFIRMED` | player-profile service and typed player route | Build search/details with identity status and null-safe fields. |
| Active participants | available | HTTP 200 sample returned confirmed players/pairs with recent eligible participation; readiness reports 3441 confirmed participants | `active_senior_participants` requires complete membership and 52-week eligible context | Use for participant selectors; do not name-match or locally reclassify. |
| Completed official results | available | Model readiness reports 16514 approved dated validated completed matches through 2026-08-22; tournament/player surfaces return stored data | core match/game models and website match contract | Display official results and parsed games when returned. |
| Scheduled matches | source contract only | Route schema supports `scheduled`; no separate valid scheduled sample was required | `WebsiteMatch.normalized_status` and scheduled scope | Display `VS`/unplayed when score is null; do not claim live forecast availability. |
| Live states | partial | Health reported 193 live matches at one timestamp; live website read later returned empty total 0 | `LiveStateSummary` preserves collection/source timestamps | Show source/collection timestamp and partial-score caveat; empty is time-scoped. |
| Live interval/rally precision | withheld/partial | No deployed sample verified rally-time precision | source contract limits `source_precision` to source vs collection time | Never fabricate duration, rally order, or interval time. |
| Official rankings | unavailable | HTTP 200 with empty data, null snapshot, `ranking_snapshot_unavailable`; capability says `not_yet_ingested` | rankings are opt-in and snapshot-gated | Keep ranking panels unavailable, not zero-valued. |
| Model contract | available | HTTP 200: model available true, eligible count 1 | model snapshot requires active/evaluated/cutoff/evaluation data | Show model readiness only with returned metadata. |
| Model details/methodology | source contract only | Route not independently sampled | `ActiveModelDetails` requires persisted methodology, input contract, evaluation summary | Do not claim details until endpoint response is confirmed. |
| Pre-match forecasts | withheld | Model contract says `no_published_pre_match_forecast_snapshot`, count 0 | forecast route requires active evaluated model, published immutable snapshot, 10,000 bps total | No probabilities/confidence/contributors/uncertainty in the website yet. |
| Head-to-head | available by provider capability contract | Model contract says validated H2H available, count 9851 | H2H route requires validated snapshot and distinct participant IDs | Build only from returned snapshot; no local aggregation. |
| Tournament simulations | withheld | Model contract count 0; simulation response says `canonical_tournament_link_not_available` | requires reconciled official topology plus active model and published snapshot | Keep simulation/probability UI withheld. |
| Point events | unavailable | Capabilities response says `not_exposed_by_provider` | no point-event website contract | Do not create a point-event visualisation from score rows. |
| Public reads trigger collectors | available as a safety property | Calendar/draw response descriptions and read behavior are persisted reads; no collector side effect observed | scheduler separates jobs; public routes call DB services | Website server must never call admin/worker operations. |

## Senior-scope gate

The provider allows only:

- BWF World Tour, including Super 100.
- Individual BWF World Championships.
- Continental Individual Championships.
- Multi-Sport Games.

The provider excludes Para/Paralympic, wheelchair and explicit Para event codes, junior/U-age/youth, International Challenge, International Series, Future Series, Continental Team Championships, World Team Championships, and all unrecognised categories. The website must not broaden this list.

## Activation and infrastructure verification gaps

The repository includes six Alembic revisions through `0006_model_contracts`, but the deployed API does not expose its migration revision. The source defaults for scheduler and opt-in source flags are false, while the live health response reports only that the collector is configured and gives a last-successful-collection timestamp. Therefore the following remain **not verified**:

1. Render environment flags and scheduler activation.
2. Neon schema revision and migration application.
3. Calendar/draw parser review completion.
4. Canonical topology reconciliation and publication.
5. Model pipeline execution provenance and forecast publication.
6. Any production environment or credential change.
