const PARA_PATTERN =
  /\b(para|paralympic|wheelchair|wh1|wh2|sl3|sl4|su5|sh6)\b/i;
const YOUTH_PATTERN = /\b(junior|youth|u[-\s]?(?:19|17|15|13|11))\b/i;
const WORLD_TOUR_PATTERN = /\bbwf\s+(?:world\s+tour|tour\s+super\s+100)\b/i;
const WORLD_CHAMPIONSHIP_PATTERN =
  /\b(?:bwf\s+)?world\s+championships?\b/i;
const CONTINENTAL_INDIVIDUAL_PATTERN =
  /\b(?:badminton\s+)?continental\s+(?:individual\s+)?championships?\b/i;
const MULTI_SPORT_PATTERN =
  /\b(?:olympic|asian\s+games|commonwealth\s+games|pan\s+am\s+games|multi[-\s]?sport)\b/i;
const EXCLUDED_SERIES_PATTERN =
  /\b(international\s+(?:challenge|series)|future\s+series)\b/i;
const TEAM_PATTERN = /\b(?:team|sudirman|thomas|uber)\b/i;

export type SeniorScopeDecision =
  | "APPROVED_SENIOR"
  | "EXCLUDED_PARA"
  | "EXCLUDED_YOUTH"
  | "EXCLUDED_TEAM"
  | "EXCLUDED_SERIES"
  | "UNRECOGNIZED";

export function classifySeniorScope(
  classification: string | null | undefined,
): SeniorScopeDecision {
  const value = classification?.trim() ?? "";
  if (!value) return "UNRECOGNIZED";
  if (PARA_PATTERN.test(value)) return "EXCLUDED_PARA";
  if (YOUTH_PATTERN.test(value)) return "EXCLUDED_YOUTH";
  if (TEAM_PATTERN.test(value)) return "EXCLUDED_TEAM";
  if (EXCLUDED_SERIES_PATTERN.test(value)) return "EXCLUDED_SERIES";
  if (
    WORLD_TOUR_PATTERN.test(value) ||
    WORLD_CHAMPIONSHIP_PATTERN.test(value) ||
    CONTINENTAL_INDIVIDUAL_PATTERN.test(value) ||
    MULTI_SPORT_PATTERN.test(value)
  ) {
    return "APPROVED_SENIOR";
  }
  return "UNRECOGNIZED";
}

export function isApprovedSeniorScope(
  classification: string | null | undefined,
): boolean {
  return classifySeniorScope(classification) === "APPROVED_SENIOR";
}