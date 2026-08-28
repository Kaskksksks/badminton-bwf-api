import type {
  ContractAvailability,
  Discipline,
  NormalizedBracketNode,
  NormalizedCalendarEntry,
  NormalizedCalendarProvenance,
  NormalizedCapabilities,
  NormalizedCapability,
  NormalizedDrawDocument,
  NormalizedEvent,
  NormalizedForecast,
  NormalizedGame,
  NormalizedH2H,
  NormalizedHealth,
  NormalizedLiveState,
  NormalizedMatch,
  NormalizedMember,
  NormalizedModelContract,
  NormalizedModelReadiness,
  NormalizedParticipant,
  NormalizedRanking,
  NormalizedScore,
  NormalizedSimulation,
  NormalizedTournament,
  PageInfo,
  ProviderEnvelope,
  ProviderError,
  ProviderMeta,
} from "./types.ts";

export type SafeObject = Record<string, unknown>;

export function safeObject(value: unknown): SafeObject | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as SafeObject;
}

export function safeArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function safeText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function safeNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function safeBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

export function safeDate(value: unknown): string | null {
  if (typeof value !== "string" || Number.isNaN(Date.parse(value))) {
    return null;
  }
  return value;
}

export function safeKey(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

export function safeStringList(value: unknown): string[] {
  return safeArray(value).flatMap((item) => {
    const text = safeText(item);
    return text === null ? [] : [text];
  });
}

function hasOwn(object: SafeObject, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function pick(object: SafeObject, ...keys: string[]): unknown {
  for (const key of keys) {
    if (hasOwn(object, key)) return object[key];
  }
  return null;
}

function normalizeDiscipline(value: unknown): Discipline {
  const text = safeText(value)?.toUpperCase();
  return text === "MS" ||
    text === "WS" ||
    text === "MD" ||
    text === "WD" ||
    text === "XD"
    ? text
    : "UNKNOWN";
}

function normalizeMeta(value: unknown): ProviderMeta | null {
  const object = safeObject(value);
  if (!object) return null;
  return {
    api_version: safeText(object["api_version"]),
    contract_version: safeText(object["contract_version"]),
    timestamp: safeDate(object["timestamp"]),
    source: safeText(object["source"]),
  };
}

function normalizePagination(value: unknown): PageInfo | null {
  const object = safeObject(value);
  if (!object) return null;
  return {
    page: safeNumber(object["page"]),
    page_size: safeNumber(object["page_size"]),
    total: safeNumber(object["total"]),
  };
}

export function normalizeAvailability(
  value: unknown,
): ContractAvailability | null {
  const object = safeObject(value);
  if (!object) return null;
  return {
    available: safeBoolean(object["available"]),
    reason: safeText(object["reason"]),
    prerequisites: safeStringList(object["prerequisites"]),
    eligible_record_count: safeNumber(object["eligible_record_count"]),
  };
}

export function normalizeEnvelope<T>(
  value: unknown,
  normalizeData: (value: unknown) => T,
): { envelope: ProviderEnvelope<T> | null; error: ProviderError | null } {
  const object = safeObject(value);
  if (!object) {
    return {
      envelope: null,
      error: {
        kind: "malformed_payload",
        message: "Provider returned a non-object JSON payload.",
        status: null,
        retryable: false,
        field: null,
      },
    };
  }

  if (!hasOwn(object, "data")) {
    return {
      envelope: null,
      error: {
        kind: "missing_field",
        message: "Provider response is missing required field: data.",
        status: null,
        retryable: false,
        field: "data",
      },
    };
  }

  const meta = normalizeMeta(object["meta"]);
  if (!meta) {
    return {
      envelope: null,
      error: {
        kind: "missing_field",
        message: "Provider response is missing required field: meta.",
        status: null,
        retryable: false,
        field: "meta",
      },
    };
  }

  const snapshot = safeObject(object["snapshot"]);
  return {
    envelope: {
      data: normalizeData(object["data"]),
      meta,
      pagination: normalizePagination(object["pagination"]),
      availability: normalizeAvailability(object["availability"]),
      issues: safeStringList(object["issues"]),
      snapshot,
    },
    error: null,
  };
}

function normalizeMember(value: unknown): NormalizedMember {
  const object = safeObject(value) ?? {};
  return {
    id: safeKey(pick(object, "id", "player_id")),
    name: safeText(pick(object, "name", "full_name")),
    country_code: safeText(object["country_code"]),
    identity_status: safeText(object["identity_status"]),
    resolved_player_id: safeKey(object["resolved_player_id"]),
  };
}

export function normalizeParticipant(value: unknown): NormalizedParticipant {
  const object = safeObject(value) ?? {};
  const members = safeArray(object["members"]).map(normalizeMember);
  return {
    id: safeKey(object["id"]),
    kind:
      object["kind"] === "player" || object["kind"] === "pair"
        ? object["kind"]
        : "unknown",
    display_name: safeText(pick(object, "display_name", "full_name")),
    identity_status: safeText(object["identity_status"]),
    member_ids: safeArray(object["member_ids"]).flatMap((item) => {
      const key = safeKey(item);
      return key === null ? [] : [key];
    }),
    members,
    activity_status: safeText(object["activity_status"]),
    recent_eligible_match_count: safeNumber(
      object["recent_eligible_match_count"],
    ),
    latest_eligible_match_date: safeDate(
      object["latest_eligible_match_date"],
    ),
    eligibility_rationale: safeText(object["eligibility_rationale"]),
  };
}

export function normalizeActiveParticipant(
  value: unknown,
): NormalizedParticipant {
  return normalizeParticipant(value);
}

export function normalizeTournament(value: unknown): NormalizedTournament {
  const object = safeObject(value) ?? {};
  return {
    id: safeKey(object["id"]),
    name: safeText(object["name"]),
    location_raw: safeText(object["location_raw"]),
    country_code: safeText(object["country_code"]),
    start_date: safeDate(object["start_date"]),
    end_date: safeDate(object["end_date"]),
    status: safeText(object["status"]),
    classification: safeText(object["classification"]),
    available_disciplines: safeArray(object["available_disciplines"]).map(
      normalizeDiscipline,
    ),
  };
}

export function normalizeEvent(value: unknown): NormalizedEvent {
  const object = safeObject(value) ?? {};
  const rawLevel = safeText(object["competition_level"]);
  return {
    id: safeKey(object["id"]),
    tournament_id: safeKey(object["tournament_id"]),
    raw_type: safeText(object["raw_type"]),
    discipline: normalizeDiscipline(object["discipline"] ?? object["raw_type"]),
    competition_level:
      rawLevel === "senior" ||
      rawLevel === "youth" ||
      rawLevel === "other"
        ? rawLevel
        : "unknown",
    category: safeText(object["category"]),
  };
}

function normalizeGame(value: unknown): NormalizedGame {
  const object = safeObject(value) ?? {};
  return {
    game_number: safeNumber(object["game_number"]),
    participant_1_score: safeNumber(object["participant_1_score"]),
    participant_2_score: safeNumber(object["participant_2_score"]),
    winner_participant_id: safeKey(object["winner_participant_id"]),
    status: safeText(object["status"]),
    parse_confidence: safeText(object["parse_confidence"]),
  };
}

function normalizeLiveState(value: unknown): NormalizedLiveState {
  const object = safeObject(value) ?? {};
  const precision = safeText(object["source_precision"]);
  return {
    game_number: safeNumber(object["game_number"]),
    participant_1_score: safeNumber(object["participant_1_score"]),
    participant_2_score: safeNumber(object["participant_2_score"]),
    observed_at: safeDate(object["observed_at"]),
    source_observed_at: safeDate(object["source_observed_at"]),
    match_status: safeText(object["match_status"]),
    source_precision:
      precision === "SOURCE_TIME" || precision === "COLLECTION_TIME"
        ? precision
        : "UNKNOWN",
  };
}

function normalizeScore(value: unknown): NormalizedScore {
  const object = safeObject(value) ?? {};
  return {
    raw: safeText(pick(object, "raw", "score_raw")),
    parse_status: safeText(pick(object, "parse_status", "score_parse_status")),
    validation_status: safeText(
      pick(object, "validation_status", "score_validation_status"),
    ),
    games: safeArray(object["games"]).map(normalizeGame),
  };
}

function normalizeMatchStatus(value: unknown): NormalizedMatch["normalized_status"] {
  const text = safeText(value)?.toLowerCase();
  if (
    text === "scheduled" ||
    text === "live" ||
    text === "completed" ||
    text === "cancelled" ||
    text === "retired" ||
    text === "walkover"
  ) {
    return text;
  }
  return "unknown";
}

export function normalizeMatch(value: unknown): NormalizedMatch {
  const object = safeObject(value) ?? {};
  const status = normalizeMatchStatus(
    pick(object, "normalized_status", "status"),
  );
  const score = normalizeScore(object["score"]);
  const hasOfficialScore =
    status === "completed" &&
    (score.games.length > 0 ||
      score.raw !== null ||
      safeKey(object["winner_participant_id"]) !== null);
  return {
    id: safeKey(object["id"]),
    source_match_key: safeKey(object["source_match_key"]),
    provider_status: safeText(object["provider_status"]),
    normalized_status: status,
    completeness: safeText(object["completeness"]),
    historical_seed: safeBoolean(object["historical_seed"]),
    tournament: object["tournament"] ? normalizeTournament(object["tournament"]) : null,
    event: object["event"] ? normalizeEvent(object["event"]) : null,
    participant_1: object["participant_1"]
      ? normalizeParticipant(object["participant_1"])
      : null,
    participant_2: object["participant_2"]
      ? normalizeParticipant(object["participant_2"])
      : null,
    round: safeText(object["round"]),
    court: safeText(object["court"]),
    winner_participant_id: safeKey(object["winner_participant_id"]),
    score,
    latest_live_state: object["latest_live_state"]
      ? normalizeLiveState(object["latest_live_state"])
      : null,
    source_url: safeText(object["source_url"]),
    score_precedence: hasOfficialScore ? "OFFICIAL" : "NONE",
    forecast_display_policy: hasOfficialScore
      ? "HIDDEN_BY_OFFICIAL_SCORE"
      : "MAY_DISPLAY",
  };
}

export function normalizeCalendarProvenance(
  value: unknown,
): NormalizedCalendarProvenance | null {
  const object = safeObject(value);
  if (!object) return null;
  return {
    source_code: safeText(object["source_code"]),
    snapshot_id: safeKey(object["snapshot_id"]),
    source_url: safeText(object["source_url"]),
    retrieved_at: safeDate(object["retrieved_at"]),
    content_hash: safeText(object["content_hash"]),
    parser_version: safeText(object["parser_version"]),
    snapshot_status: safeText(object["snapshot_status"]),
  };
}

export function normalizeCalendarEntry(
  value: unknown,
): NormalizedCalendarEntry {
  const object = safeObject(value) ?? {};
  return {
    id: safeKey(object["id"]),
    source_tournament_id: safeKey(object["source_tournament_id"]),
    name: safeText(object["name"]),
    country_code: safeText(object["country_code"]),
    city: safeText(object["city"]),
    start_date: safeDate(object["start_date"]),
    end_date: safeDate(object["end_date"]),
    category: safeText(object["category"]),
    event_url: safeText(object["event_url"]),
    draw_date_text: safeText(object["draw_date_text"]),
    eligibility_status: safeText(object["eligibility_status"]),
    eligibility_rationale: safeText(object["eligibility_rationale"]),
    provenance: normalizeCalendarProvenance(object["provenance"]),
  };
}

export function normalizeDrawDocument(value: unknown): NormalizedDrawDocument {
  const object = safeObject(value) ?? {};
  return {
    id: safeKey(object["id"]),
    calendar_entry_id: safeKey(object["calendar_entry_id"]),
    source_url: safeText(object["source_url"]),
    document_label: safeText(object["document_label"]),
    retrieved_at: safeDate(object["retrieved_at"]),
    content_hash: safeText(object["content_hash"]),
    content_type: safeText(object["content_type"]),
    byte_size: safeNumber(object["byte_size"]),
    parser_version: safeText(object["parser_version"]),
    parser_status: safeText(object["parser_status"]),
    parser_issue: safeText(object["parser_issue"]),
  };
}

export function normalizeBracketNode(value: unknown): NormalizedBracketNode {
  const object = safeObject(value) ?? {};
  return {
    source_node_key: safeKey(object["source_node_key"]),
    round_label: safeText(object["round_label"]),
    display_order: safeNumber(object["display_order"]),
    participant_1_label: safeText(object["participant_1_label"]),
    participant_2_label: safeText(object["participant_2_label"]),
    winner_label: safeText(object["winner_label"]),
    score_text: safeText(object["score_text"]),
    reconciliation_status: safeText(object["reconciliation_status"]),
    canonical_match_id: safeKey(object["canonical_match_id"]),
  };
}

export function normalizeForecast(value: unknown): NormalizedForecast {
  const object = safeObject(value) ?? {};
  return {
    match_id: safeKey(object["match_id"]),
    model_key: safeText(object["model_key"]),
    model_version: safeText(object["model_version"]),
    input_cutoff: safeDate(object["input_cutoff"]),
    generated_at: safeDate(object["generated_at"]),
    participant_1_win_probability_bps: safeNumber(
      object["participant_1_win_probability_bps"],
    ),
    participant_2_win_probability_bps: safeNumber(
      object["participant_2_win_probability_bps"],
    ),
    confidence_label: safeText(object["confidence_label"]),
    uncertainty_summary: safeText(object["uncertainty_summary"]),
    evidence_contributors: safeStringList(object["evidence_contributors"]),
    provenance: safeObject(object["provenance"]) ?? {},
  };
}

export function normalizeRanking(value: unknown): NormalizedRanking {
  const object = safeObject(value) ?? {};
  return {
    participant_id: safeKey(object["participant_id"]),
    participant_name: safeText(object["participant_name"]),
    discipline: normalizeDiscipline(object["discipline"]),
    rank: safeNumber(object["rank"]),
    points: safeNumber(object["points"]),
    snapshot_date: safeDate(object["snapshot_date"]),
    country_code: safeText(object["country_code"]),
  };
}

export function normalizeH2H(value: unknown): NormalizedH2H {
  const object = safeObject(value) ?? {};
  const rawWins = safeObject(object["wins"]) ?? {};
  const wins = Object.fromEntries(
    Object.entries(rawWins).flatMap(([key, count]) => {
      const value = safeNumber(count);
      return value === null ? [] : [[key, value]];
    }),
  );
  return {
    participant_a: safeKey(object["participant_a"]),
    participant_b: safeKey(object["participant_b"]),
    meetings: safeNumber(object["meetings"]),
    wins,
    input_cutoff: safeDate(object["input_cutoff"]),
    snapshot_status: safeText(object["snapshot_status"]),
    evidence: safeObject(object["evidence"]) ?? {},
  };
}

export function normalizeSimulation(value: unknown): NormalizedSimulation {
  const object = safeObject(value) ?? {};
  return {
    calendar_entry_id: safeKey(object["calendar_entry_id"]),
    tournament_id: safeKey(object["tournament_id"]),
    model_key: safeText(object["model_key"]),
    model_version: safeText(object["model_version"]),
    draw_topology_id: safeKey(object["draw_topology_id"]),
    input_cutoff: safeDate(object["input_cutoff"]),
    simulation_count: safeNumber(object["simulation_count"]),
    probability_payload: safeObject(object["probability_payload"]) ?? {},
    provenance: safeObject(object["provenance"]) ?? {},
  };
}

export function normalizeHealth(value: unknown): NormalizedHealth {
  const object = safeObject(value) ?? {};
  return {
    api_status: safeText(object["api_status"]),
    database_status: safeText(object["database_status"]),
    collector_status: safeText(object["collector_status"]),
    source_status: safeText(object["source_status"]),
    live_match_count: safeNumber(object["live_match_count"]),
    last_successful_collection_at: safeDate(
      object["last_successful_collection_at"],
    ),
    latest_data_timestamp: safeDate(object["latest_data_timestamp"]),
    errors_last_24h: safeNumber(object["errors_last_24h"]),
  };
}

function normalizeCapability(value: unknown): NormalizedCapability {
  const object = safeObject(value) ?? {};
  return {
    available: safeBoolean(object["available"]),
    reason: safeText(object["reason"]),
    caveat: safeText(object["caveat"]),
    prerequisites: safeStringList(object["prerequisites"]),
    eligible_record_count: safeNumber(object["eligible_record_count"]),
  };
}

export function normalizeCapabilities(value: unknown): NormalizedCapabilities {
  const object = safeObject(value) ?? {};
  return {
    rankings: normalizeCapability(object["rankings"]),
    draws: normalizeCapability(object["draws"]),
    point_events: normalizeCapability(object["point_events"]),
    predictions: normalizeCapability(object["predictions"]),
    head_to_head: normalizeCapability(object["head_to_head"]),
    tournament_simulations: normalizeCapability(object["tournament_simulations"]),
    live_states: normalizeCapability(object["live_states"]),
  };
}

export function normalizeModelContract(value: unknown): NormalizedModelContract {
  const object = safeObject(value) ?? {};
  return {
    model: normalizeCapability(object["model"]),
    predictions: normalizeCapability(object["predictions"]),
    head_to_head: normalizeCapability(object["head_to_head"]),
    simulations: normalizeCapability(object["simulations"]),
  };
}

export function normalizeModelReadiness(
  value: unknown,
): NormalizedModelReadiness {
  const object = safeObject(value) ?? {};
  return {
    publication_ready: safeBoolean(object["publication_ready"]),
    confirmed_participants: safeNumber(object["confirmed_participants"]),
    approved_dated_validated_completed_matches: safeNumber(
      object["approved_dated_validated_completed_matches"],
    ),
    minimum_matches_required: safeNumber(object["minimum_matches_required"]),
    earliest_match_date: safeDate(object["earliest_match_date"]),
    latest_match_date: safeDate(object["latest_match_date"]),
    event_types: safeArray(object["event_types"]).map(normalizeDiscipline),
    source_scope: safeText(object["source_scope"]),
    write_side_effects: safeBoolean(object["write_side_effects"]),
  };
}

export function envelopeState<T>(
  envelope: ProviderEnvelope<T>,
): "available" | "partial" | "empty" | "withheld" | "unavailable" {
  if (envelope.availability?.available === false) {
    const reason = envelope.availability.reason ?? "";
    return reason.includes("not_yet_ingested") ||
      reason.includes("unavailable")
      ? "unavailable"
      : "withheld";
  }
  if (Array.isArray(envelope.data) && envelope.data.length === 0) {
    return envelope.issues.length > 0 ? "unavailable" : "empty";
  }
  if (
    envelope.availability &&
    (envelope.availability.available === null ||
      envelope.availability.reason === null)
  ) {
    return "partial";
  }
  return "available";
}