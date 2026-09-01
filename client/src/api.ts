import type { ApiResponse, ProviderHealth, Capability, CalendarEntry, MatchRecord, ActiveParticipant, OfficialBracket, MatchForecastResponse } from "./types/badminton";

export async function fetchHealth(): Promise<ApiResponse<ProviderHealth>> {
  const res = await fetch("/api/v1/health");
  return res.json();
}

export async function fetchCapabilities(): Promise<ApiResponse<Capability[]>> {
  const res = await fetch("/api/v1/website/capabilities");
  return res.json();
}

export async function fetchCalendar(): Promise<ApiResponse<CalendarEntry[]>> {
  const res = await fetch("/api/v1/website/calendar");
  return res.json();
}

export async function fetchMatches(params?: Record<string, string>): Promise<ApiResponse<MatchRecord[]>> {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await fetch(`/api/v1/website/matches${query}`);
  return res.json();
}

export async function fetchActiveParticipants(): Promise<ApiResponse<ActiveParticipant[]>> {
  const res = await fetch("/api/v1/website/active-participants");
  return res.json();
}

export async function fetchModelContract(): Promise<ApiResponse<any>> {
  const res = await fetch("/api/v1/website/model-contract");
  return res.json();
}

export async function fetchBracket(calendarEntryId: string, discipline: string): Promise<ApiResponse<OfficialBracket>> {
  const res = await fetch(`/api/v1/website/calendar/${calendarEntryId}/brackets/${discipline}`);
  return res.json();
}

export async function fetchForecast(matchId: string): Promise<ApiResponse<MatchForecastResponse>> {
  const res = await fetch(`/api/v1/website/matches/${matchId}/forecast`);
  return res.json();
}

export async function fetchRankings(): Promise<ApiResponse<any>> {
  const res = await fetch("/api/v1/website/rankings");
  return res.json();
}

export async function fetchHeadToHead(p1: string, p2: string, discipline: string): Promise<ApiResponse<any>> {
  const res = await fetch(`/api/v1/website/head-to-head?p1=${p1}&p2=${p2}&discipline=${discipline}`);
  return res.json();
}

export async function fetchAccuracy(): Promise<ApiResponse<any>> {
  const res = await fetch("/api/v1/website/accuracy");
  return res.json();
}
