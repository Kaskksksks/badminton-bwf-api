export type MatchScope = "all" | "live" | "scheduled" | "completed";
export type CapabilityState = "available" | "partial" | "withheld" | "unavailable" | "error";
export type Discipline = "MS" | "WS" | "MD" | "WD" | "XD" | "UNKNOWN";

export interface ApiResponse<T> {
  data: T | null;
  state: CapabilityState;
  reason?: string;
  metadata?: any;
}

export interface ProviderHealth {
  apiStatus: string;
  databaseStatus: string;
  collectorStatus: string;
  sourceStatus: string;
  lastSuccessfulCollection: string;
  latestDataTimestamp: string;
  liveMatchCount: number;
  errorsLast24Hours: number;
  message: string;
}

export interface Capability {
  key: string;
  state: CapabilityState;
  reason: string;
  caveat?: string;
}

export interface DataStatus {
  historicalStatus: string;
  historicalCutoff: string;
  historicalVerificationTime: string;
  liveStatus: string;
  liveStartDate: string;
  liveGameState: string;
  livePrecisionRule: string;
}

export interface Member {
  id: string;
  name: string;
  countryCode?: string;
  identityStatus: string;
}

export interface Participant {
  id: string;
  name: string;
  kind?: "player" | "pair";
  countryCode?: string;
  identityStatus: string;
  members: Member[];
}

export interface GameScore {
  gameNumber: number;
  score1: number;
  score2: number;
  winnerParticipantId?: string;
  status: string;
  parseConfidence: number;
}

export interface LiveState {
  gameNumber?: number;
  score1?: number;
  score2?: number;
  observedTimestamp?: string;
  sourceObservedTimestamp?: string;
  matchStatus?: string;
  sourcePrecision?: string;
}

export interface TournamentSummary {
  id: string;
  name: string;
  location: string;
  countryCode: string;
  startDate: string;
  endDate: string;
  status: string;
  classification: string;
  supportedDisciplines: Discipline[];
}

export interface MatchRecord {
  id: string;
  sourceKey: string;
  datesAndTimes: string;
  sourceStatus: string;
  normalizedStatus: string;
  sourceCompleteness: string;
  historicalSeedFlag: boolean;
  scoreParseStatus: string;
  scoreValidationStatus: string;
  scoreSourceConfidence: string;
  tournament: TournamentSummary;
  discipline: Discipline;
  round: string;
  court: string;
  eventType: string;
  eventCategory: string;
  competitionLevel: string;
  participant1: Participant;
  participant2: Participant;
  winnerId?: string;
  rawScore: string;
  games: GameScore[];
  latestLiveState?: LiveState;
  sourceUrl?: string;
  observedTimestamp: string;
}

export interface CalendarEntry {
  sourceTournamentId: string;
  name: string;
  countryCity: string;
  startDate: string;
  endDate: string;
  category: string;
  eventUrl: string;
  drawDateText: string;
  eligibilityStatus: "ELIGIBLE" | "INELIGIBLE";
  eligibilityRationale: string;
  immutableProvenance: {
    sourceCode: string;
    snapshotId: string;
    sourceUrl: string;
    retrievedAt: string;
    contentHash: string;
    parserVersion: string;
    snapshotStatus: string;
  };
}

export interface DrawDocument {
  id: string;
  calendarEntryId: string;
  sourceUrl: string;
  documentLabel: string;
  retrievalTimestamp: string;
  contentHash: string;
  contentType: string;
  byteSize: number;
  parserVersion: string;
  parserStatus: string;
  parserIssue?: string;
}

export interface ActiveParticipant {
  id: string;
  kind: "player" | "pair";
  name: string;
  memberIds: string[];
  identityStatus: "CONFIRMED";
  activityStatus: "ACTIVE_RECENT_OFFICIAL_PARTICIPATION";
  recentEligibleMatchCount: number;
  latestEligibleMatchDate: string;
  eligibilityRationale: string;
}

export interface BracketNode {
  sourceNodeKey: string;
  roundLabel: string;
  displayOrder: number;
  participantLabels: string[];
  winnerLabel: string;
  scoreText: string;
  reconciliationStatus: string;
  canonicalMatchId?: string;
}

export interface OfficialBracket {
  availability: CapabilityState;
  discipline: Discipline;
  calendarEntryId: string;
  documentId?: string;
  topologyId?: string;
  bracketNodes: BracketNode[];
  metadata?: any;
}

export interface MatchForecastResponse {
  matchId: string;
  overallAvailability: CapabilityState;
  independentAvailability: {
    winProbability: CapabilityState;
    confidence: CapabilityState;
    evidenceContributors: CapabilityState;
    uncertainty: CapabilityState;
  };
  snapshot: {
    modelKey: string;
    modelVersion: string;
    inputCutoff: string;
    generationTime: string;
    participant1WinProbabilityBp: number;
    participant2WinProbabilityBp: number;
    confidenceLabel: string;
    uncertaintySummary: string;
    evidenceContributors: string[];
    provenance: string;
  } | null;
  metadata?: any;
}
