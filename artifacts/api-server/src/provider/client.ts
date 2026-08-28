import { getProviderConfig, type ProviderConfig } from "./config.ts";
import {
  envelopeState,
  normalizeActiveParticipant,
  normalizeAvailability,
  normalizeBracketNode,
  normalizeCalendarEntry,
  normalizeCapabilities,
  normalizeDrawDocument,
  normalizeEnvelope,
  normalizeEvent,
  normalizeForecast,
  normalizeH2H,
  normalizeHealth,
  normalizeMatch,
  normalizeModelContract,
  normalizeModelReadiness,
  normalizeParticipant,
  normalizeRanking,
  normalizeSimulation,
  normalizeTournament,
} from "./normalizers.ts";
import type {
  Discipline,
  MatchScope,
  NormalizedBracketNode,
  NormalizedCalendarEntry,
  NormalizedCapabilities,
  NormalizedDrawDocument,
  NormalizedEvent,
  NormalizedForecast,
  NormalizedH2H,
  NormalizedHealth,
  NormalizedMatch,
  NormalizedModelContract,
  NormalizedModelReadiness,
  NormalizedParticipant,
  NormalizedRanking,
  NormalizedSimulation,
  NormalizedTournament,
  ProviderEnvelope,
  ProviderError,
  ProviderResult,
} from "./types.ts";

type FetchLike = typeof fetch;

export interface ProviderAdapterOptions extends Partial<ProviderConfig> {
  fetchImpl?: FetchLike;
  timeoutMs?: number;
  cacheTtlMs?: number;
  retryDelayMs?: number;
  now?: () => number;
}

interface CacheEntry {
  expiresAt: number;
  envelope: ProviderEnvelope<unknown>;
}

interface UpstreamSuccess {
  ok: true;
  status: number;
  body: unknown;
}

interface UpstreamFailure {
  ok: false;
  error: ProviderError;
}

type UpstreamResponse = UpstreamSuccess | UpstreamFailure;

function providerError(
  kind: ProviderError["kind"],
  message: string,
  status: number | null,
  retryable = false,
  field: string | null = null,
): ProviderError {
  return { kind, message, status, retryable, field };
}

function queryString(
  query: Record<string, string | number | undefined>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

function resultFromError<T>(
  error: ProviderError,
  cached = false,
): ProviderResult<T> {
  return {
    state: "error",
    data: null,
    meta: null,
    error,
    status: error.status,
    cached,
  };
}

export class ProviderAdapter {
  private readonly baseUrl: string;
  private readonly fetchImpl: FetchLike;
  private readonly timeoutMs: number;
  private readonly cacheTtlMs: number;
  private readonly retryDelayMs: number;
  private readonly now: () => number;
  private readonly cache = new Map<string, CacheEntry>();
  private serialized: Promise<void> = Promise.resolve();

  constructor(options: ProviderAdapterOptions = {}) {
    this.baseUrl = (options.baseUrl ?? getProviderConfig().baseUrl).replace(
      /\/+$/,
      "",
    );
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.timeoutMs = options.timeoutMs ?? 8_000;
    this.cacheTtlMs = options.cacheTtlMs ?? 5_000;
    this.retryDelayMs = options.retryDelayMs ?? 250;
    this.now = options.now ?? Date.now;
  }

  static fromEnvironment(options: Omit<ProviderAdapterOptions, "baseUrl"> = {}) {
    return new ProviderAdapter({ ...options, ...getProviderConfig() });
  }

  get configuredBaseUrl(): string {
    return this.baseUrl;
  }

  private async withSerialization<T>(operation: () => Promise<T>): Promise<T> {
    let release!: () => void;
    const previous = this.serialized;
    this.serialized = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      return await operation();
    } finally {
      release();
    }
  }

  private async fetchJson(path: string, query: Record<string, string | number | undefined>): Promise<UpstreamResponse> {
    const url = `${this.baseUrl}${path}${queryString(query)}`;
    let retried429 = false;

    while (true) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
      try {
        const response = await this.fetchImpl(url, {
          method: "GET",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });

        if (response.status === 429 && !retried429) {
          retried429 = true;
          if (this.retryDelayMs > 0) {
            await new Promise((resolve) => setTimeout(resolve, this.retryDelayMs));
          }
          continue;
        }

        if (!response.ok) {
          const transient = response.status === 429 || response.status === 502 || response.status === 503;
          return {
            ok: false,
            error: providerError(
              response.status === 429 ? "rate_limited" : "upstream",
              `Provider returned HTTP ${response.status}.`,
              response.status,
              transient,
            ),
          };
        }

        const text = await response.text();
        let body: unknown;
        try {
          body = JSON.parse(text);
        } catch {
          return {
            ok: false,
            error: providerError(
              "malformed_payload",
              "Provider returned a successful response that was not valid JSON.",
              response.status,
            ),
          };
        }
        return { ok: true, status: response.status, body };
      } catch (error) {
        const timedOut = controller.signal.aborted;
        return {
          ok: false,
          error: providerError(
            timedOut ? "timeout" : "network",
            timedOut
              ? `Provider request exceeded ${this.timeoutMs}ms.`
              : "Provider request failed before a response was received.",
            null,
            true,
          ),
        };
      } finally {
        clearTimeout(timeout);
      }
    }
  }

  private async get<T>(
    path: string,
    query: Record<string, string | number | undefined>,
    normalizeData: (value: unknown) => T,
  ): Promise<ProviderResult<ProviderEnvelope<T>>> {
    const key = `${path}${queryString(query)}`;
    return this.withSerialization(async () => {
      const cached = this.cache.get(key);
      if (cached && cached.expiresAt > this.now()) {
        const envelope = cached.envelope as ProviderEnvelope<T>;
        return {
          state: envelopeState(envelope),
          data: envelope,
          meta: envelope.meta,
          error: null,
          status: 200,
          cached: true,
        };
      }

      const upstream = await this.fetchJson(path, query);
      if (!upstream.ok) return resultFromError<ProviderEnvelope<T>>(upstream.error);

      const normalized = normalizeEnvelope(upstream.body, normalizeData);
      if (normalized.error || !normalized.envelope) {
        return resultFromError<ProviderEnvelope<T>>({
          ...normalized.error!,
          status: upstream.status,
        });
      }

      this.cache.set(key, {
        expiresAt: this.now() + this.cacheTtlMs,
        envelope: normalized.envelope as ProviderEnvelope<unknown>,
      });
      const envelope = normalized.envelope;
      return {
        state: envelopeState(envelope),
        data: envelope,
        meta: envelope.meta,
        error: null,
        status: upstream.status,
        cached: false,
      };
    });
  }

  health() {
    return this.get<NormalizedHealth>("/api/v1/health", {}, normalizeHealth);
  }

  dataStatus() {
    return this.get<NormalizedHealth>(
      "/api/v1/data-status",
      {},
      normalizeHealth,
    );
  }

  capabilities() {
    return this.get<NormalizedCapabilities>(
      "/api/v1/website/capabilities",
      {},
      normalizeCapabilities,
    );
  }

  calendar(page = 1, pageSize = 50) {
    return this.get<NormalizedCalendarEntry[]>(
      "/api/v1/website/calendar",
      { page, page_size: pageSize },
      (value) => Array.isArray(value) ? value.map(normalizeCalendarEntry) : [],
    );
  }

  activeParticipants(page = 1, pageSize = 50) {
    return this.get<NormalizedParticipant[]>(
      "/api/v1/website/active-participants",
      { page, page_size: pageSize },
      (value) => Array.isArray(value) ? value.map(normalizeActiveParticipant) : [],
    );
  }

  matches(scope: MatchScope = "all", page = 1, pageSize = 50) {
    return this.get<NormalizedMatch[]>(
      "/api/v1/website/matches",
      { scope, page, page_size: pageSize },
      (value) => Array.isArray(value) ? value.map(normalizeMatch) : [],
    );
  }

  match(matchId: string) {
    return this.get<NormalizedMatch>(
      `/api/v1/website/matches/${encodeURIComponent(matchId)}`,
      {},
      normalizeMatch,
    );
  }

  forecast(matchId: string) {
    return this.get<NormalizedForecast>(
      `/api/v1/website/matches/${encodeURIComponent(matchId)}/forecast`,
      {},
      normalizeForecast,
    );
  }

  drawDocuments(calendarEntryId: string) {
    return this.get<NormalizedDrawDocument[]>(
      `/api/v1/website/calendar/${encodeURIComponent(calendarEntryId)}/draw-documents`,
      {},
      (value) => Array.isArray(value) ? value.map(normalizeDrawDocument) : [],
    );
  }

  brackets(calendarEntryId: string, discipline: Exclude<Discipline, "UNKNOWN">) {
    return this.get<NormalizedBracketNode[]>(
      `/api/v1/website/calendar/${encodeURIComponent(calendarEntryId)}/brackets/${discipline}`,
      {},
      (value) => Array.isArray(value) ? value.map(normalizeBracketNode) : [],
    );
  }

  rankings(page = 1, pageSize = 50) {
    return this.get<NormalizedRanking[]>(
      "/api/v1/website/rankings",
      { page, page_size: pageSize },
      (value) => Array.isArray(value) ? value.map(normalizeRanking) : [],
    );
  }

  headToHead(participantA: string, participantB: string) {
    return this.get<NormalizedH2H>(
      `/api/v1/website/head-to-head/${encodeURIComponent(participantA)}/${encodeURIComponent(participantB)}`,
      {},
      normalizeH2H,
    );
  }

  simulations(calendarEntryId: string) {
    return this.get<NormalizedSimulation>(
      `/api/v1/website/calendar/${encodeURIComponent(calendarEntryId)}/simulation`,
      {},
      normalizeSimulation,
    );
  }

  tournaments(page = 1, pageSize = 50) {
    return this.get<NormalizedTournament[]>(
      "/api/v1/website/tournaments",
      { page, page_size: pageSize },
      (value) => Array.isArray(value) ? value.map(normalizeTournament) : [],
    );
  }

  events(tournamentId: string) {
    return this.get<NormalizedEvent[]>(
      `/api/v1/website/tournaments/${encodeURIComponent(tournamentId)}/events`,
      {},
      (value) => Array.isArray(value) ? value.map(normalizeEvent) : [],
    );
  }

  players(page = 1, pageSize = 50) {
    return this.get<NormalizedParticipant[]>(
      "/api/v1/website/players",
      { page, page_size: pageSize },
      (value) => Array.isArray(value) ? value.map(normalizeParticipant) : [],
    );
  }

  playerMatches(playerId: string, page = 1, pageSize = 50) {
    return this.get<NormalizedMatch[]>(
      `/api/v1/website/players/${encodeURIComponent(playerId)}/matches`,
      { page, page_size: pageSize },
      (value) => Array.isArray(value) ? value.map(normalizeMatch) : [],
    );
  }

  modelContract() {
    return this.get<NormalizedModelContract>(
      "/api/v1/website/model-contract",
      {},
      normalizeModelContract,
    );
  }

  modelReadiness() {
    return this.get<NormalizedModelReadiness>(
      "/api/v1/website/model-readiness",
      {},
      normalizeModelReadiness,
    );
  }
}