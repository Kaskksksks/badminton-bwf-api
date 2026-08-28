import { Router, type IRouter } from "express";
import healthRouter from "./health";
import providerRouter from "./provider";

const router: IRouter = Router();

router.use(healthRouter);
router.use(providerRouter);

export default router;
