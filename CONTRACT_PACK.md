# BWF // Supercomputer Website Contract Pack

**Contract source:** provider repository `main` at `2ad9e3e440618294692c50fd96453d3198fd74a4`  
**Live contract version:** `website-2026-08`  
**Purpose:** define what the website may display and how it must represent the provider’s uncertainty.

The provider is the canonical source for sports data. The website must not maintain a browser-side shadow database, infer missing records, or call the provider directly from browser code. Browser requests go to the website server; the website server calls the provider with `BADMINTON_API_BASE_URL` kept server-side.

## Shared vocabulary

```text
MatchScope = "all" | "live" | "scheduled" | "completed"
CapabilityState = "available" | "partial" | "withheld" | "unavailable" | "error"
Discipline = "MS" | "WS" | "MD" | "WD" | "XD" | "UNKNOWN"
```

The provider emits boolean `available` fields inside `ContractAvailability`. The website may map them to `CapabilityState`, but must preserve the provider’s exact `reason`, `prerequisites`, counts, nulls, and provenance.

## Common response metadata

`ApiMeta`:

| Field | Type | Rule |
|---|---|---|
| `api_version` | literal `"v1"` | Preserve. |
| `contract_version` | literal `"website-2026-08"` | Preserve and surface in diagnostics. |
| `timestamp` | ISO date-time | The provider response time, not the source event time. |
| `source` | string | Preserve values such as `BWF_CORPORATE_CALENDAR`, `BWF_LIVE`, `BWF_OFFICIAL_PLAYER_PROFILES`, `BWF_OFFICIAL_RANKINGS`, `PLATFORM`, and `PLATFORM_MODEL`. |

`PageInfo`:

```ts
type PageInfo = {
  page: number;       // >= 1
  page_size: number;  // 1..100 for website contracts
  total: number;      // >= 0
};
```

## Canonical website data types

### Participant and identity

```ts
type ParticipantSummary = {
  id: string;
  kind: "player" | "pair";
  display_name: string;
  identity_status: string;
  members: MemberSummary[]; // max 2
};

type MemberSummary = {
  id: string;
  name: string;
  country_code: string | null;
  identity_status: string;
  resolved_player_id: string | null;
};

type SeniorParticipant = {
  id: string;
  kind: "player" | "pair";
  display_name: string;
  member_ids: string[]; // 1 for player, 2 for pair
  identity_status: "CONFIRMED";
  activity_status: "ACTIVE_RECENT_OFFICIAL_PARTICIPATION";
  recent_eligible_match_count: number; // >= 1
  latest_eligible_match_date: string;
  eligibility_rationale: string;
};
```

An active participant is public only when every required member is provider-confirmed and the participant has a completed or retired match within 52 weeks in the approved senior scope. Do not use name matching in the website.

### Tournament, event, and match

```ts
type TournamentSummary = {
  id: string;
  name: string;
  location_raw: string | null;
  country_code: string | null;
  start_date: string | null;
  end_date: string | null;
  status: string;
  classification: string | null;
  available_disciplines: string[];
};

type EventSummary = {
  id: string;
  tournament_id: string;
  raw_type: string;
  discipline: Discipline;
  competition_level: "senior" | "youth" | "other";
  category: string | null;
};

type GameSummary = {
  game_number: number; // 1..5
  participant_1_score: number | null;
  participant_2_score: number | null;
  winner_participant_id: string | null;
  status: string;
  parse_confidence: string;
};

type LiveStateSummary = {
  game_number: number;
  participant_1_score: number;
  participant_2_score: number;
  observed_at: string;
  source_observed_at: string | null;
  match_status: string;
  source_precision: "SOURCE_TIME" | "COLLECTION_TIME";
};
```

`WebsiteMatch` includes the IDs and source key, nullable scheduling/start fields, provider status plus normalized status, completeness, historical-seed flag, optional tournament/event/participants, round/court, winner, raw score, score parse/validation statuses, games, latest live state, and source URL.

Rules:

- A scheduled match without scores is displayed as unplayed, for example `VS`; do not display a fabricated score.
- A live state must show `observed_at`, and must explain when `source_precision=COLLECTION_TIME`.
- `source_observed_at=null` is meaningful; do not replace it with the collection time.
- Completed official results supersede any forecast in the UI.
- Preserve `score_raw`, parse status, validation status, and nulls even when a parsed score is not available.
- `status` is upstream text. `normalized_status` is one of `scheduled`, `live`, `completed`, `cancelled`, `retired`, `walkover`, or `unknown`.

### Calendar and provenance

```ts
type CalendarProvenance = {
  source_code: "BWF_CORPORATE_CALENDAR";
  snapshot_id: string;
  source_url: string;
  retrieved_at: string;
  content_hash: string;
  parser_version: string;
  snapshot_status: string;
};

type CalendarEntry = {
  id: string;
  source_tournament_id: string;
  name: string;
  country_code: string | null;
  city: string | null;
  start_date: string;
  end_date: string;
  category: string | null;
  event_url: string | null;
  draw_date_text: string | null;
  eligibility_status: "ELIGIBLE";
  eligibility_rationale: string;
  provenance: CalendarProvenance;
};
```

Only persisted eligible calendar entries are public. The website may display the direct event URL and provenance, but must not scrape BWF pages in the browser.

### Draw document metadata

```ts
type DrawDocument = {
  id: string;
  calendar_entry_id: string;
  source_url: string;
  document_label: string;
  retrieved_at: string;
  content_hash: string;
  content_type: string | null;
  byte_size: number;
  parser_version: string;
  parser_status: string;
  parser_issue: string | null;
};
```

The endpoint returns metadata only. `source_url` is provenance, not permission to fetch document bytes from the browser. The current live example is `CAPTURED_REVIEW_REQUIRED`; that is not a public bracket.

### Capability and withheld contracts

```ts
type ContractAvailability = {
  available: boolean;
  reason: string;
  prerequisites: string[];
  eligible_record_count: number;
};
```

For an unavailable intelligence feature, render the exact reason and prerequisites in plain language. Do not substitute a probability, ranking, bracket, or analyst explanation.

### Official bracket

```ts
type OfficialBracketNode = {
  source_node_key: string;
  round_label: string | null;
  display_order: number;
  participant_1_label: string | null;
  participant_2_label: string | null;
  winner_label: string | null;
  score_text: string | null;
  reconciliation_status: string;
  canonical_match_id: string | null;
};

type OfficialBracketResponse = {
  availability: ContractAvailability;
  discipline: "MS" | "WS" | "MD" | "WD" | "XD";
  calendar_entry_id: string;
  document_id: string | null;
  topology_id: string | null;
  data: OfficialBracketNode[];
  meta: ApiMeta;
};
```

Public bracket data requires a direct BWF PDF emitted by the approved calendar, parser validation, a full topology, and canonical reconciliation of every node. Never infer a bracket from match rows.

### Model, forecast, H2H, and simulation

The model contract provides independent availability for `model`, `predictions`, `head_to_head`, and `simulations`.

Forecast snapshot fields, when available:

```ts
type MatchForecastSnapshot = {
  match_id: string;
  model_key: string;
  model_version: string;
  input_cutoff: string;
  generated_at: string;
  participant_1_win_probability_bps: number; // 0..10000
  participant_2_win_probability_bps: number; // 0..10000
  confidence_label: string;
  uncertainty_summary: string;
  evidence_contributors: string[];
  provenance: Record<string, unknown>;
};
```

The probabilities must sum to exactly 10,000 basis points. The response also carries field-level availability for win probability, confidence, evidence contributors, and uncertainty. A missing one is withheld, not estimated locally.

H2H snapshot fields:

```ts
type HeadToHeadSnapshot = {
  participant_a: string;
  participant_b: string;
  meetings: number;
  wins: Record<string, number>;
  input_cutoff: string;
  snapshot_status: "VALIDATED";
  evidence: Record<string, unknown>;
};
```

H2H requires distinct confirmed active participants and eligible completed history. A successful contract availability count does not authorize the website to invent a pair response for missing IDs.

Simulation snapshot fields:

```ts
type TournamentSimulationSnapshot = {
  calendar_entry_id: string;
  tournament_id: string;
  model_key: string;
  model_version: string;
  draw_topology_id: string;
  input_cutoff: string;
  simulation_count: number;
  probability_payload: Record<string, unknown>;
  provenance: Record<string, unknown>;
};
```

Simulation requires the eligible calendar entry to resolve to exactly one approved canonical tournament, a published reconciled official topology, an active evaluated model, and a published snapshot.

## Approved senior classifier

The provider’s shared classifier is `classify_approved_senior_scope` in `app/ingestion/approved_scope.py`. It permits:

1. BWF World Tour, including BWF/Tour Super 100 categories.
2. Individual BWF World Championships, excluding team championships.
3. Continental Individual Championships.
4. Multi-Sport Games.

It excludes before public delivery:

- Para/Paralympic, wheelchair, and explicit Para event codes such as `WH1`, `WH2`, `SL3`, `SL4`, `SU5`, and `SH6`.
- Junior, U-age, and youth markers.
- International Challenge.
- International Series.
- Future Series.
- Continental Team Championships.
- World Team Championships.
- Missing, unrecognised, or otherwise outside-scope categories.

The website must reuse the provider’s public results and must not implement a weaker browser-side classifier.

## State behavior

The provider has no browser loading state; the website owns `loading`. All other states must remain explicit:

| Website state | When to use | Required behavior |
|---|---|---|
| `loading` | Request is in flight | Show a non-assertive loading state; do not show stale-looking fabricated values. |
| `available` | Provider returned a valid populated contract | Display values with `meta.source`, response timestamp, and provenance where present. |
| `partial` | Provider returned useful data with a documented caveat, such as a live score with collection-time precision or a record with null optional fields | Display the data and the caveat beside it. Never silently fill nulls. |
| `empty` | Provider returned HTTP 200 with an empty collection and no capability failure, such as zero live matches at that moment | Say there are no records in the requested scope/time, not that the provider is broken. |
| `withheld` | Provider returned HTTP 200 with `available=false` and a specific reason/prerequisite contract | Explain what is withheld and why. Do not show an inferred substitute. |
| `unavailable` | Provider returned a valid explicit unavailable contract such as rankings with `snapshot=null` and `ranking_snapshot_unavailable` | Preserve the issue and offer no locally generated replacement. |
| `error` | HTTP 429, 502, 503, timeout, malformed JSON, schema mismatch, or unexpected 5xx | Show the failure class, provider timestamp if present, and a retry path. Do not convert it to empty data. |

The website server should keep independent endpoint failures independent. For example, a rankings failure must not blank the calendar, and a withheld bracket must not hide match results.

## Security and integration boundary

- `BADMINTON_API_BASE_URL` remains server-side.
- No provider credentials, Render values, Neon values, or API keys enter browser bundles.
- Browser code calls only the website server.
- Public website reads never call collectors, admin endpoints, or modeling jobs.
- Admin routes and `X-API-Key` are not part of the public website contract.
