import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetAllLanes, setCommandLaneConcurrency } from "./command-queue.js";
import { registerLaneRun, resetLaneStoreForTest } from "./lane-store.js";
import {
  clearLane,
  configureLaneWatchdog,
  getLaneStatus,
  getLaneWatchdogState,
  recoverLane,
  spawnInLane,
  stopLaneWatchdog,
} from "./lane-supervisor.js";

describe("lane-supervisor", () => {
  let stateDir = "";
  const previousStateDir = process.env.OPENCLAW_STATE_DIR;

  beforeEach(() => {
    stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "lane-supervisor-test-"));
    process.env.OPENCLAW_STATE_DIR = stateDir;
    resetLaneStoreForTest();
    resetAllLanes();
    stopLaneWatchdog();
    configureLaneWatchdog({ enabled: false });
  });

  afterEach(() => {
    stopLaneWatchdog();
    resetLaneStoreForTest();
    resetAllLanes();
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    fs.rmSync(stateDir, { recursive: true, force: true });
  });

  it("spawns and tracks a lane run to completion", async () => {
    const lane = `lane-${Date.now()}`;
    setCommandLaneConcurrency(lane, 1);

    const runId = spawnInLane(lane, "test task", async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });

    await vi.waitFor(() => {
      const status = getLaneStatus(lane);
      const run = status.runs.find((candidate) => candidate.runId === runId);
      expect(run?.status).toBe("done");
    });

    clearLane(lane);
  });

  it("recovers pending/running runs as stale", () => {
    registerLaneRun({ runId: "r1", lane: "recover-lane", status: "pending", task: "t1" });
    registerLaneRun({ runId: "r2", lane: "recover-lane", status: "running", task: "t2" });

    const recovered = recoverLane("recover-lane");
    const status = getLaneStatus("recover-lane");

    expect(recovered).toBe(2);
    expect(status.runs.map((run) => run.status)).toEqual(["stale", "stale"]);
  });

  it("keeps lane watchdog default-off unless explicitly enabled", () => {
    const initial = getLaneWatchdogState();
    expect(initial.enabled).toBe(false);
    expect(initial.running).toBe(false);

    const enabled = configureLaneWatchdog({ enabled: true, intervalMs: 25, staleThresholdMs: 50 });
    expect(enabled.enabled).toBe(true);
    expect(enabled.running).toBe(true);
    expect(enabled.intervalMs).toBe(25);

    const disabled = configureLaneWatchdog({ enabled: false });
    expect(disabled.enabled).toBe(false);
    expect(disabled.running).toBe(false);
  });
});
