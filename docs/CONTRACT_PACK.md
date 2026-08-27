# Senior-Safe Website Contract Pack

This pack adds **read-only public contracts** and **staged internal structures** only. It does not alter Render or Neon environment values, collection cadence, the calendar source budget, the global collection lock, live-worker cadence, or OOM safeguards. Public reads use only persisted data; no endpoint in this pack initiates source collection.

| Area | Implemented contract | Publication boundary |
|---|---|---|
| Calendar | `GET /api/v1/website/calendar` | Returns only the latest eligible persisted BWF Corporate calendar entries, with immutable snapshot provenance. |
| Draw documents | `GET /api/v1/website/calendar/{calendar_entry_id}/draw-documents` | Returns metadata only for direct BWF draw PDFs associated with an eligible calendar entry; it never returns document bytes. |
| Active competitors | `GET /api/v1/website/active-participants` | Requires confirmed single or pair identity plus a completed/retired match within 52 weeks in an approved senior scope. |
| Brackets | `GET /api/v1/website/calendar/{calendar_entry_id}/brackets/{discipline}` | Withheld unless a captured direct PDF has a parser-validated, fully canonical-reconciled topology. |
| Model readiness | `GET /api/v1/website/model-contract` | Describes availability and prerequisites for model, forecast, head-to-head, and simulation contracts without synthesising outcomes. |
| Per-match forecast | `GET /api/v1/website/matches/{match_id}/forecast` | Returns an immutable published pre-match snapshot with typed values, or an independent availability reason for every forecast field. |
| Tournament simulation | `GET /api/v1/website/calendar/{calendar_entry_id}/simulation` | Returns a published simulation only where the calendar entry has a safe canonical tournament link and a reconciled direct-BWF-draw topology. |

## Approved-senior boundary

The shared `classify_approved_senior_scope` function allows only BWF World Tour including Super 100, individual BWF World Championships, Continental Individual Championships, and Multi-Sport Games. It blocks Para, junior/U-age, International Challenge, International Series, Future Series, Continental Team Championships, World Team Championships, and unrecognised senior categories before canonical live persistence. Public active-participant delivery reruns this approved scope check over stored match context, so an old ineligible record cannot become public merely because it was previously stored.

## Bracket topology and reconciliation lifecycle

`stage_topology_from_extracted_text` receives text extracted from an already captured direct BWF PDF, and it rechecks both the authorised extranet document URL and the immutable document content hash. It can only create `PENDING_REVIEW` candidate nodes. It does not infer winners, advancement, player identities, or canonical matches. A reviewer must link each source node to an existing canonical match with a rationale through `record_canonical_reconciliation`; only then can `publish_topology_after_full_reconciliation` set `VALIDATED_RECONCILED`. The public bracket endpoint rejects every other state.

## Prediction-model prerequisites

No prediction model is included in this repository yet, and the pack does not claim one exists. The schema requires a versioned model snapshot, declared input contract, training cutoff, calibration/evaluation status, and activation before forecasts can be considered. Each forecast must be immutable, pre-match, identify its source cutoff, include probabilities in basis points, contributors, uncertainty, and provenance. Head-to-head snapshots require eligible confirmed participants and their own cutoff. Tournament simulations additionally require a published official topology and canonical reconciliation. The contract endpoints remain explicitly unavailable until those records are real and validated.
