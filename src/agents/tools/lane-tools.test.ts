import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetAllLanes } from "../../process/command-queue.js";
import { resetLaneStoreForTest } from "../../process/lane-store.js";
import {
  configureLaneWatchdog,
  getLaneWatchdogState,
  stopLaneWatchdog,
} from "../../process/lane-supervisor.js";
import { createOpenClawTools } from "../openclaw-tools.js";
import { createLaneSpawnTool, createLaneSupervisorTool } from "./lane-tools.js";

describe("lane tools", () => {
  let stateDir = "";
  const previousStateDir = process.env.OPENCLAW_STATE_DIR;

  beforeEach(() => {
    stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "lane-tools-test-"));
    process.env.OPENCLAW_STATE_DIR = stateDir;
    resetAllLanes();
    resetLaneStoreForTest();
    stopLaneWatchdog();
    configureLaneWatchdog({ enabled: false });
  });

  afterEach(() => {
    stopLaneWatchdog();
    resetAllLanes();
    resetLaneStoreForTest();
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    fs.rmSync(stateDir, { recursive: true, force: true });
  });

  it("supports spawn -> status -> recover -> clear workflow", async () => {
    const lane = `lane-${Date.now()}`;
    const spawnTool = createLaneSpawnTool();
    const supervisorTool = createLaneSupervisorTool();

    const spawnResult = await spawnTool.execute("tc-1", {
      task: "noop lane run",
      lane,
      kind: "noop",
    });
    const spawnDetails = spawnResult.details as {
      status: string;
      runId: string;
      lane: string;
    };
    expect(spawnDetails.status).toBe("ok");

    await vi.waitFor(async () => {
      const status = (await supervisorTool.execute("tc-2", {
        action: "status",
        lane,
      })) as { details?: { runs?: Array<{ runId: string; status: string }> } };
      const run = status.details?.runs?.find((entry) => entry.runId === spawnDetails.runId);
      expect(run?.status).toBe("done");
    });

    const recover = (await supervisorTool.execute("tc-3", {
      action: "recover",
      lane,
    })) as { details?: { count?: number } };
    expect(recover.details?.count).toBe(0);

    const clear = (await supervisorTool.execute("tc-4", {
      action: "clear",
      lane,
    })) as { details?: { count?: number } };
    expect((clear.details?.count ?? 0) >= 1).toBe(true);
  });

  it("keeps watchdog default-off and enables with diagnostic flag", () => {
    createOpenClawTools();
    expect(getLaneWatchdogState().enabled).toBe(false);

    createOpenClawTools({
      config: {
        diagnostics: {
          flags: ["lane.watchdog"],
        },
      },
    });

    const state = getLaneWatchdogState();
    expect(state.enabled).toBe(true);
    expect(state.running).toBe(true);
  });
});
