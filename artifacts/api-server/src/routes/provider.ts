import { Router, type IRouter, type Request, type Response } from "express";
import { providerProcedures } from "../provider/procedures.ts";
import type { ProviderResult } from "../provider/types.ts";

const router: IRouter = Router();

function positiveInteger(value: unknown, fallback: number): number {
  const parsed = typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function pageArgs(req: Request): [number, number] {
  return [
    positiveInteger(req.query["page"], 1),
    Math.min(100, positiveInteger(req.query["page_size"], 50)),
  ];
}

function sendProviderResult<T>(
  response: Response,
  result: ProviderResult<T>,
): void {
  const status =
    result.state === "error"
      ? result.status === 429
        ? 429
        : result.status === 502 || result.status === 503
          ? result.status
          : 502
      : 200;
  response.status(status).json(result);
}

function route<T>(
  handler: (request: Request) => Promise<ProviderResult<T>>,
) {
  return async (request: Request, response: Response) => {
    sendProviderResult(response, await handler(request));
  };
}

router.get("/provider/health", route(() => providerProcedures.health()));
router.get(
  "/provider/data-status",
  route(() => providerProcedures.dataStatus()),
);
router.get(
  "/provider/capabilities",
  route(() => providerProcedures.capabilities()),
);
router.get(
  "/provider/calendar",
  route((req) => {
    const [page, pageSize] = pageArgs(req);
    return providerProcedures.calendar(page, pageSize);
  }),
);
router.get(
  "/provider/active-participants",
  route((req) => {
    const [page, pageSize] = pageArgs(req);
    return providerProcedures.activeParticipants(page, pageSize);
  }),
);
router.get(
  "/provider/matches",
  route((req) => {
    const scope =
      typeof req.query["scope"] === "string" &&
      ["all", "live", "scheduled", "completed"].includes(req.query["scope"])
        ? (req.query["scope"] as "all" | "live" | "scheduled" | "completed")
        : "all";
    const [page, pageSize] = pageArgs(req);
    return providerProcedures.matches(scope, page, pageSize);
  }),
);
router.get(
  "/provider/matches/:matchId",
  route((req) => providerProcedures.match(req.params["matchId"] ?? "")),
);
router.get(
  "/provider/matches/:matchId/forecast",
  route((req) => providerProcedures.forecast(req.params["matchId"] ?? "")),
);
router.get(
  "/provider/calendar/:calendarEntryId/draw-documents",
  route((req) =>
    providerProcedures.drawDocuments(req.params["calendarEntryId"] ?? ""),
  ),
);
router.get(
  "/provider/calendar/:calendarEntryId/brackets/:discipline",
  route((req) => {
    const discipline = req.params["discipline"]?.toUpperCase();
    if (!["MS", "WS", "MD", "WD", "XD"].includes(discipline ?? "")) {
      return providerProcedures.brackets(
        req.params["calendarEntryId"] ?? "",
        "MS",
      ).then((result) => ({
        ...result,
        state: "error" as const,
        data: null,
        error: {
          kind: "malformed_payload" as const,
          message: "Unknown discipline. Expected MS, WS, MD, WD, or XD.",
          status: 400,
          retryable: false,
          field: "discipline",
        },
        status: 400,
      }));
    }
    return providerProcedures.brackets(
      req.params["calendarEntryId"] ?? "",
      discipline as "MS" | "WS" | "MD" | "WD" | "XD",
    );
  }),
);
router.get(
  "/provider/rankings",
  route((req) => {
    const [page, pageSize] = pageArgs(req);
    return providerProcedures.rankings(page, pageSize);
  }),
);
router.get(
  "/provider/head-to-head/:participantA/:participantB",
  route((req) =>
    providerProcedures.headToHead(
      req.params["participantA"] ?? "",
      req.params["participantB"] ?? "",
    ),
  ),
);
router.get(
  "/provider/calendar/:calendarEntryId/simulation",
  route((req) =>
    providerProcedures.simulations(req.params["calendarEntryId"] ?? ""),
  ),
);
router.get(
  "/provider/tournaments",
  route((req) => {
    const [page, pageSize] = pageArgs(req);
    return providerProcedures.tournaments(page, pageSize);
  }),
);
router.get(
  "/provider/tournaments/:tournamentId/events",
  route((req) =>
    providerProcedures.events(req.params["tournamentId"] ?? ""),
  ),
);
router.get(
  "/provider/players",
  route((req) => {
    const [page, pageSize] = pageArgs(req);
    return providerProcedures.players(page, pageSize);
  }),
);
router.get(
  "/provider/players/:playerId/matches",
  route((req) => {
    const [page, pageSize] = pageArgs(req);
    return providerProcedures.playerMatches(
      req.params["playerId"] ?? "",
      page,
      pageSize,
    );
  }),
);
router.get(
  "/provider/model-contract",
  route(() => providerProcedures.modelContract()),
);
router.get(
  "/provider/model-readiness",
  route(() => providerProcedures.modelReadiness()),
);

export default router;