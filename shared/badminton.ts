export type MatchScope = "all" | "live" | "scheduled" | "completed";
export type CapabilityState = "available" | "partial" | "withheld" | "unavailable" | "error";
export type Discipline = "MS" | "WS" | "MD" | "WD" | "XD" | "UNKNOWN";

export interface ApiResponse<T> {
  data: T | null;
  state: CapabilityState;
  reason?: string;
  metadata?: any;
}
