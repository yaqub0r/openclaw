import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  getLaneRun,
  listLaneRuns,
  registerLaneRun,
  resetLaneStoreForTest,
  updateLaneRun,
} from "./lane-store.js";

describe("lane-store", () => {
  let stateDir = "";
  const previousStateDir = process.env.OPENCLAW_STATE_DIR;

  beforeEach(() => {
    stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "lane-store-test-"));
    process.env.OPENCLAW_STATE_DIR = stateDir;
    resetLaneStoreForTest();
  });

  afterEach(() => {
    resetLaneStoreForTest();
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    fs.rmSync(stateDir, { recursive: true, force: true });
  });

  it("persists and reloads lane runs from disk", () => {
    registerLaneRun({
      runId: "run-1",
      lane: "default",
      status: "pending",
      task: "demo",
      metadata: { kind: "noop" },
    });
    updateLaneRun("run-1", { status: "done", endedAt: Date.now() });

    resetLaneStoreForTest();
    const restored = getLaneRun("run-1");

    expect(restored).toBeDefined();
    expect(restored?.status).toBe("done");
    expect(restored?.task).toBe("demo");
  });

  it("ignores malformed persisted records", () => {
    const runsPath = path.join(stateDir, "lanes", "runs.json");
    fs.mkdirSync(path.dirname(runsPath), { recursive: true });
    fs.writeFileSync(
      runsPath,
      JSON.stringify(
        {
          version: 1,
          runs: [
            {
              runId: "good-run",
              lane: "default",
              status: "pending",
              task: "ok",
              createdAt: Date.now(),
              updatedAt: Date.now(),
            },
            {
              runId: "",
              lane: "default",
              status: "pending",
              task: "bad",
            },
            {
              runId: "bad-status",
              lane: "default",
              status: "unknown",
              task: "bad",
            },
          ],
        },
        null,
        2,
      ),
      "utf8",
    );

    resetLaneStoreForTest();
    const runs = listLaneRuns();

    expect(runs).toHaveLength(1);
    expect(runs[0]?.runId).toBe("good-run");
  });
});
