function generateMockMatches() {
  return [
    {
      id: "match-1001",
      sourceKey: "bwf-m-1001",
      datesAndTimes: "2026-08-31 14:00",
      sourceStatus: "COMPLETED",
      normalizedStatus: "completed",
      sourceCompleteness: "FULL",
      historicalSeedFlag: false,
      scoreParseStatus: "VALID",
      scoreValidationStatus: "CONFIRMED",
      scoreSourceConfidence: "HIGH",
      tournament: { id: "tourney-2026-1", name: "BWF World Championships", location: "Tokyo, Japan", countryCode: "JP", startDate: "2026-08-25", endDate: "2026-08-31", status: "ACTIVE", classification: "Grade 1", supportedDisciplines: ["MS", "WS", "MD", "WD", "XD"] },
      discipline: "MS",
      round: "Final",
      court: "Court 1",
      eventType: "Main",
      eventCategory: "Super 1000",
      competitionLevel: "Senior",
      participant1: { id: "p1-viktor", name: "Viktor AXELSEN", kind: "player", countryCode: "DK", identityStatus: "CONFIRMED", members: [{ id: "m-viktor", name: "Viktor AXELSEN", identityStatus: "CONFIRMED", countryCode: "DK" }] },
      participant2: { id: "p2-shi", name: "SHI Yu Qi", kind: "player", countryCode: "CN", identityStatus: "CONFIRMED", members: [{ id: "m-shi", name: "SHI Yu Qi", identityStatus: "CONFIRMED", countryCode: "CN" }] },
      winnerId: "p1-viktor",
      rawScore: "21-18, 21-15",
      games: [
        { gameNumber: 1, score1: 21, score2: 18, winnerParticipantId: "p1-viktor", status: "COMPLETED", parseConfidence: 100 },
        { gameNumber: 2, score1: 21, score2: 15, winnerParticipantId: "p1-viktor", status: "COMPLETED", parseConfidence: 100 }
      ],
      observedTimestamp: new Date().toISOString()
    }
  ];
}

function generateMockForecast() {
  return {
    matchId: "match-1001",
    overallAvailability: "available",
    independentAvailability: { winProbability: "available", confidence: "available", evidenceContributors: "available", uncertainty: "available" },
    snapshot: { modelKey: "BWF-XGB-2026.4", modelVersion: "4.2.1", inputCutoff: "2026-08-30T23:59:59Z", generationTime: new Date().toISOString(), participant1WinProbabilityBp: 6250, participant2WinProbabilityBp: 3750, confidenceLabel: "HIGH", uncertaintySummary: "Standard variance.", evidenceContributors: ["H2H_ADVANTAGE", "RECENT_FORM_30D", "COURT_SPEED_INDEX"], provenance: "GENERATED_ON_PREMISE" }
  };
}

function generateMockRankings() {
  return {
    publicationDate: "2026-08-25",
    discipline: "MS",
    snapshotId: "rk-2026-08-25-MS",
    entries: [
      { rank: 1, participant: { name: "Viktor AXELSEN", countryCode: "DK" }, points: 104520, tournaments: 14, movement: 0 },
      { rank: 2, participant: { name: "SHI Yu Qi", countryCode: "CN" }, points: 98310, tournaments: 15, movement: 1 },
      { rank: 3, participant: { name: "Anders ANTONSEN", countryCode: "DK" }, points: 92430, tournaments: 14, movement: -1 },
      { rank: 4, participant: { name: "Li Shifeng", countryCode: "CN" }, points: 87120, tournaments: 16, movement: 0 }
    ]
  };
}

function generateMockH2H() {
  return {
    availability: "available",
    participant1Id: "p1",
    participant2Id: "p2",
    discipline: "MS",
    totalMatches: 10,
    participant1Wins: 6,
    participant2Wins: 4,
    matches: generateMockMatches(),
    lastEncounter: generateMockMatches()[0]
  };
}

function generateMockAccuracy() {
  return {
    availability: "available",
    period: "Last 30 Days",
    metrics: {
      overallAccuracy: 84.5,
      totalPredictions: 125,
      calibrationScore: 0.92,
      brierScore: 0.15
    },
    byDiscipline: {
      "MS": 86.2, "WS": 83.1, "MD": 81.5, "WD": 85.0, "XD": 84.8
    }
  };
}

function generateMockHealth() {
  return {
    apiStatus: "OPERATIONAL",
    databaseStatus: "CONNECTED",
    collectorStatus: "ACTIVE",
    sourceStatus: "OK",
    lastSuccessfulCollection: new Date().toISOString(),
    latestDataTimestamp: new Date().toISOString(),
    liveMatchCount: 12,
    errorsLast24Hours: 0
  };
}

function generateMockCalendar() {
  return [
    {
      sourceTournamentId: "tourney-2026-1",
      name: "BWF World Championships 2026",
      countryCity: "Tokyo, JP",
      startDate: "2026-08-25",
      endDate: "2026-08-31",
      category: "Grade 1",
      eventUrl: "https://bwf.com",
      drawDateText: "2026-08-10",
      eligibilityStatus: "ELIGIBLE",
      eligibilityRationale: "CONFIRMED",
      immutableProvenance: {
        sourceCode: "SRC_01",
        snapshotId: "SNAP_01",
        sourceUrl: "https://bwf.com",
        retrievedAt: new Date().toISOString(),
        contentHash: "abcd123",
        parserVersion: "1.0",
        snapshotStatus: "VERIFIED"
      }
    },
    {
      sourceTournamentId: "tourney-2026-2",
      name: "China Open 2026",
      countryCity: "Changzhou, CN",
      startDate: "2026-09-15",
      endDate: "2026-09-20",
      category: "Super 1000",
      eventUrl: "https://bwf.com",
      drawDateText: "2026-09-01",
      eligibilityStatus: "ELIGIBLE",
      eligibilityRationale: "CONFIRMED",
      immutableProvenance: {
        sourceCode: "SRC_02",
        snapshotId: "SNAP_02",
        sourceUrl: "https://bwf.com",
        retrievedAt: new Date().toISOString(),
        contentHash: "efgh456",
        parserVersion: "1.0",
        snapshotStatus: "VERIFIED"
      }
    }
  ];
}

function generateMockActiveParticipants() {
  return [
    {
      id: "p1-viktor",
      kind: "player",
      name: "Viktor AXELSEN",
      memberIds: ["m-viktor"],
      identityStatus: "CONFIRMED",
      activityStatus: "ACTIVE_RECENT_OFFICIAL_PARTICIPATION",
      recentEligibleMatchCount: 15,
      latestEligibleMatchDate: "2026-08-31",
      eligibilityRationale: "Active player with official participation"
    },
    {
      id: "p2-shi",
      kind: "player",
      name: "SHI Yu Qi",
      memberIds: ["m-shi"],
      identityStatus: "CONFIRMED",
      activityStatus: "ACTIVE_RECENT_OFFICIAL_PARTICIPATION",
      recentEligibleMatchCount: 16,
      latestEligibleMatchDate: "2026-08-31",
      eligibilityRationale: "Active player with official participation"
    },
    {
      id: "p3-antonsen",
      kind: "player",
      name: "Anders ANTONSEN",
      memberIds: ["m-antonsen"],
      identityStatus: "CONFIRMED",
      activityStatus: "ACTIVE_RECENT_OFFICIAL_PARTICIPATION",
      recentEligibleMatchCount: 12,
      latestEligibleMatchDate: "2026-08-30",
      eligibilityRationale: "Active player with official participation"
    }
  ];
}


export async function fetchFromProvider(endpoint) {
  if (endpoint.includes('/website/model-contract')) {
    return {
      data: {
        model: { available: true, reason: "Active and evaluating" },
        predictions: { available: true, reason: "Snapshots published and verified" },
        topology: { available: true, reason: "Draw topologies completely parsed" }
      },
      state: "available"
    };
  }
  
  if (endpoint.includes('/website/matches') && !endpoint.includes('/forecast')) {
    return { data: generateMockMatches(), state: "available" };
  }
  if (endpoint.includes('/forecast')) {
    return { data: generateMockForecast(), state: "available" };
  }
  if (endpoint.includes('/brackets')) {
    return {
      data: {
        availability: "available", discipline: "MS", calendarEntryId: "tourney-2026-1",
        bracketNodes: [
          { sourceNodeKey: "final-1", roundLabel: "Final", displayOrder: 1, participantLabels: ["Viktor AXELSEN", "SHI Yu Qi"], winnerLabel: "Viktor AXELSEN", scoreText: "21-18, 21-15", reconciliationStatus: "RECONCILED", canonicalMatchId: "match-1001" },
          { sourceNodeKey: "sf-1", roundLabel: "Semi Final", displayOrder: 2, participantLabels: ["Viktor AXELSEN", "Anders ANTONSEN"], winnerLabel: "Viktor AXELSEN", scoreText: "21-12, 21-10", reconciliationStatus: "RECONCILED", canonicalMatchId: "match-1002" }
        ]
      },
      state: "available"
    };
  }
  if (endpoint.includes('/website/rankings')) {
    return { data: generateMockRankings(), state: "available" };
  }
  if (endpoint.includes('/website/head-to-head')) {
    return { data: generateMockH2H(), state: "available" };
  }
  if (endpoint.includes('/website/accuracy')) {
    return { data: generateMockAccuracy(), state: "available" };
  }
  if (endpoint.includes('/health')) {
    return { data: generateMockHealth(), state: "available" };
  }
  if (endpoint.includes('/website/calendar')) {
    return { data: generateMockCalendar(), state: "available" };
  }
  if (endpoint.includes('/website/active-participants')) {
    return { data: generateMockActiveParticipants(), state: "available" };
  }

  return { data: null, state: "unavailable", reason: "Data not supplied by provider API" };
}
