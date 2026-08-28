import { ProviderConfigurationError } from "./config.ts";
import { ProviderAdapter } from "./client.ts";
import type { ProviderError, ProviderResult } from "./types.ts";

let adapter: ProviderAdapter | null = null;

export function getProviderAdapter(): ProviderAdapter {
  if (!adapter) adapter = ProviderAdapter.fromEnvironment();
  return adapter;
}

export function resetProviderAdapterForTests(): void {
  adapter = null;
}

export function configurationResult<T>(
  error: unknown,
): ProviderResult<T> {
  const message =
    error instanceof ProviderConfigurationError
      ? error.message
      : "Provider configuration is unavailable.";
  const providerError: ProviderError = {
    kind: "configuration",
    message,
    status: null,
    retryable: false,
    field: "BADMINTON_API_BASE_URL",
  };
  return {
    state: "error",
    data: null,
    meta: null,
    error: providerError,
    status: null,
    cached: false,
  };
}

async function invoke<T>(
  operation: (provider: ProviderAdapter) => Promise<ProviderResult<T>>,
): Promise<ProviderResult<T>> {
  try {
    return await operation(getProviderAdapter());
  } catch (error) {
    return configurationResult<T>(error);
  }
}

export const providerProcedures = {
  health: () => invoke((provider) => provider.health()),
  dataStatus: () => invoke((provider) => provider.dataStatus()),
  capabilities: () => invoke((provider) => provider.capabilities()),
  calendar: (page = 1, pageSize = 50) =>
    invoke((provider) => provider.calendar(page, pageSize)),
  activeParticipants: (page = 1, pageSize = 50) =>
    invoke((provider) => provider.activeParticipants(page, pageSize)),
  matches: (scope = "all" as const, page = 1, pageSize = 50) =>
    invoke((provider) => provider.matches(scope, page, pageSize)),
  match: (matchId: string) => invoke((provider) => provider.match(matchId)),
  forecast: (matchId: string) =>
    invoke((provider) => provider.forecast(matchId)),
  drawDocuments: (calendarEntryId: string) =>
    invoke((provider) => provider.drawDocuments(calendarEntryId)),
  brackets: (
    calendarEntryId: string,
    discipline: "MS" | "WS" | "MD" | "WD" | "XD",
  ) => invoke((provider) => provider.brackets(calendarEntryId, discipline)),
  rankings: (page = 1, pageSize = 50) =>
    invoke((provider) => provider.rankings(page, pageSize)),
  headToHead: (participantA: string, participantB: string) =>
    invoke((provider) => provider.headToHead(participantA, participantB)),
  simulations: (calendarEntryId: string) =>
    invoke((provider) => provider.simulations(calendarEntryId)),
  tournaments: (page = 1, pageSize = 50) =>
    invoke((provider) => provider.tournaments(page, pageSize)),
  events: (tournamentId: string) =>
    invoke((provider) => provider.events(tournamentId)),
  players: (page = 1, pageSize = 50) =>
    invoke((provider) => provider.players(page, pageSize)),
  playerMatches: (playerId: string, page = 1, pageSize = 50) =>
    invoke((provider) => provider.playerMatches(playerId, page, pageSize)),
  modelContract: () => invoke((provider) => provider.modelContract()),
  modelReadiness: () => invoke((provider) => provider.modelReadiness()),
};