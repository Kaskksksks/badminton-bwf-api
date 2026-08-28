export type ProviderState =
  | "available"
  | "partial"
  | "empty"
  | "withheld"
  | "unavailable"
  | "error";

export type ProviderErrorKind =
  | "configuration"
  | "rate_limited"
  | "upstream"
  | "timeout"
  | "malformed_payload"
  | "missing_field"
  | "network";

export type Discipline = "MS" | "WS" | "MD" | "WD" | "XD" | "UNKNOWN";
export type MatchScope = "all" | "live" | "scheduled" | "completed";

export interface ProviderError {
  kind: ProviderErrorKind;
  message: string;
  status: number | null;
  retryable: boolean;
  field: string | null;
}

export interface ProviderMeta {
  api_version: string | null;
  contract_version: string | null;
  timestamp: string | null;
  source: string | null;
}

export interface PageInfo {
  page: number | null;
  page_size: number | null;
  total: number | null;
}

export interface ContractAvailability {
  available: boolean | null;
  reason: string | null;
  prerequisites: string[];
  eligible_record_count: number | null;
}

export interface ProviderEnvelope<T> {
  data: T;
  meta: ProviderMeta;
  pagination: PageInfo | null;
  availability: ContractAvailability | null;
  issues: string[];
  snapshot: Record<string, unknown> | null;
}

export interface ProviderResult<T> {
  state: ProviderState;
  data: T | null;
  meta: ProviderMeta | null;
  error: ProviderError | null;
  status: number | null;
  cached: boolean;
}

export interface NormalizedMember {
  id: string | null;
  name: string | null;
  country_code: string | null;
  identity_status: string | null;
  resolved_player_id: string | null;
}

export interface NormalizedParticipant {
  id: string | null;
  kind: "player" | "pair" | "unknown";
  display_name: string | null;
  identity_status: string | null;
  member_ids: string[];
  members: NormalizedMember[];
  activity_status: string | null;
  recent_eligible_match_count: number | null;
  latest_eligible_match_date: string | null;
  eligibility_rationale: string | null;
}

export interface NormalizedTournament {
  id: string | null;
  name: string | null;
  location_raw: string | null;
  country_code: string | null;
  start_date: string | null;
  end_date: string | null;
  status: string | null;
  classification: string | null;
  available_disciplines: Discipline[];
}

export interface NormalizedEvent {
  id: string | null;
  tournament_id: string | null;
  raw_type: string | null;
  discipline: Discipline;
  competition_level: "senior" | "youth" | "other" | "unknown";
  category: string | null;
}

export interface NormalizedGame {
  game_number: number | null;
  participant_1_score: number | null;
  participant_2_score: number | null;
  winner_participant_id: string | null;
  status: string | null;
  parse_confidence: string | null;
}

export interface NormalizedLiveState {
  game_number: number | null;
  participant_1_score: number | null;
  participant_2_score: number | null;
  observed_at: string | null;
  source_observed_at: string | null;
  match_status: string | null;
  source_precision: "SOURCE_TIME" | "COLLECTION_TIME" | "UNKNOWN";
}

export interface NormalizedScore {
  raw: string | null;
  parse_status: string | null;
  validation_status: string | null;
  games: NormalizedGame[];
}

export interface NormalizedMatch {
  id: string | null;
  source_match_key: string | null;
  provider_status: string | null;
  normalized_status:
    | "scheduled"
    | "live"
    | "completed"
    | "cancelled"
    | "retired"
    | "walkover"
    | "unknown";
  completeness: string | null;
  historical_seed: boolean | null;
  tournament: NormalizedTournament | null;
  event: NormalizedEvent | null;
  participant_1: NormalizedParticipant | null;
  participant_2: NormalizedParticipant | null;
  round: string | null;
  court: string | null;
  winner_participant_id: string | null;
  score: NormalizedScore;
  latest_live_state: NormalizedLiveState | null;
  source_url: string | null;
  score_precedence: "OFFICIAL" | "NONE";
  forecast_display_policy: "HIDDEN_BY_OFFICIAL_SCORE" | "MAY_DISPLAY";
}

export interface NormalizedCalendarProvenance {
  source_code: string | null;
  snapshot_id: string | null;
  source_url: string | null;
  retrieved_at: string | null;
  content_hash: string | null;
  parser_version: string | null;
  snapshot_status: string | null;
}

export interface NormalizedCalendarEntry {
  id: string | null;
  source_tournament_id: string | null;
  name: string | null;
  country_code: string | null;
  city: string | null;
  start_date: string | null;
  end_date: string | null;
  category: string | null;
  event_url: string | null;
  draw_date_text: string | null;
  eligibility_status: string | null;
  eligibility_rationale: string | null;
  provenance: NormalizedCalendarProvenance | null;
}

export interface NormalizedDrawDocument {
  id: string | null;
  calendar_entry_id: string | null;
  source_url: string | null;
  document_label: string | null;
  retrieved_at: string | null;
  content_hash: string | null;
  content_type: string | null;
  byte_size: number | null;
  parser_version: string | null;
  parser_status: string | null;
  parser_issue: string | null;
}

export interface NormalizedBracketNode {
  source_node_key: string | null;
  round_label: string | null;
  display_order: number | null;
  participant_1_label: string | null;
  participant_2_label: string | null;
  winner_label: string | null;
  score_text: string | null;
  reconciliation_status: string | null;
  canonical_match_id: string | null;
}

export interface NormalizedForecast {
  match_id: string | null;
  model_key: string | null;
  model_version: string | null;
  input_cutoff: string | null;
  generated_at: string | null;
  participant_1_win_probability_bps: number | null;
  participant_2_win_probability_bps: number | null;
  confidence_label: string | null;
  uncertainty_summary: string | null;
  evidence_contributors: string[];
  provenance: Record<string, unknown>;
}

export interface NormalizedRanking {
  participant_id: string | null;
  participant_name: string | null;
  discipline: Discipline;
  rank: number | null;
  points: number | null;
  snapshot_date: string | null;
  country_code: string | null;
}

export interface NormalizedH2H {
  participant_a: string | null;
  participant_b: string | null;
  meetings: number | null;
  wins: Record<string, number>;
  input_cutoff: string | null;
  snapshot_status: string | null;
  evidence: Record<string, unknown>;
}

export interface NormalizedSimulation {
  calendar_entry_id: string | null;
  tournament_id: string | null;
  model_key: string | null;
  model_version: string | null;
  draw_topology_id: string | null;
  input_cutoff: string | null;
  simulation_count: number | null;
  probability_payload: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export interface NormalizedHealth {
  api_status: string | null;
  database_status: string | null;
  collector_status: string | null;
  source_status: string | null;
  live_match_count: number | null;
  last_successful_collection_at: string | null;
  latest_data_timestamp: string | null;
  errors_last_24h: number | null;
}

export interface NormalizedCapability {
  available: boolean | null;
  reason: string | null;
  caveat: string | null;
  prerequisites: string[];
  eligible_record_count: number | null;
}

export interface NormalizedCapabilities {
  rankings: NormalizedCapability;
  draws: NormalizedCapability;
  point_events: NormalizedCapability;
  predictions: NormalizedCapability;
  head_to_head: NormalizedCapability;
  tournament_simulations: NormalizedCapability;
  live_states: NormalizedCapability;
}

export interface NormalizedModelContract {
  model: NormalizedCapability;
  predictions: NormalizedCapability;
  head_to_head: NormalizedCapability;
  simulations: NormalizedCapability;
}

export interface NormalizedModelReadiness {
  publication_ready: boolean | null;
  confirmed_participants: number | null;
  approved_dated_validated_completed_matches: number | null;
  minimum_matches_required: number | null;
  earliest_match_date: string | null;
  latest_match_date: string | null;
  event_types: Discipline[];
  source_scope: string | null;
  write_side_effects: boolean | null;
}