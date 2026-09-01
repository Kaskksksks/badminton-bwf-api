import { Router } from "express";
import { fetchFromProvider } from "./badminton/provider.js";

const router = Router();

// Generic proxy for any path
router.all("*", async (req, res) => {
  const result = await fetchFromProvider(req.originalUrl.replace('/api/v1', ''));
  // Note: fetchFromProvider appends the path to BADMINTON_API_BASE_URL.
  // req.originalUrl could be /api/v1/website/calendar
  // We want to pass /website/calendar
  res.json(result);
});

export default router;
