import { diagnosticLogger as diag } from "../logging/diagnostic.js";
import {
  clearCommandLane,
  enqueueCommandInLane,
  getQueueSize,
  getTotalQueueSize,
} from "./command-queue.js";
import {
  type LaneRunRecord,
  registerLaneRun,
  updateLaneRun,
  listLaneRuns,
  clearLaneRuns,
} from "./lane-store.js";

export interface LaneStatus {
  lane: string;
  queueSize: number;
  runs: LaneRunRecord[];
}

export type LaneWatchdogState = {
  enabled: boolean;
  running: boolean;
  intervalMs: number;
  staleThresholdMs: number;
};

const DEFAULT_WATCHDOG_INTERVAL_MS = 60_000;
const DEFAULT_STALE_THRESHOLD_MS = 300_000;

let watchdogInterval: NodeJS.Timeout | null = null;
const watchdogState: LaneWatchdogState = {
  enabled: false,
  running: false,
  intervalMs: DEFAULT_WATCHDOG_INTERVAL_MS,
  staleThresholdMs: DEFAULT_STALE_THRESHOLD_MS,
};

function normalizeMs(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  return Math.max(1, Math.floor(value));
}

export function getLaneStatus(lane?: string): LaneStatus {
  const laneName = lane?.trim() || "default";
  const runs = listLaneRuns(laneName);
  const queueSize = getQueueSize(laneName);
  return {
    lane: laneName,
    queueSize,
    runs: runs.slice(-20),
  };
}

export function spawnInLane(
  lane: string,
  task: string,
  cmd: () => Promise<unknown>,
  metadata?: Record<string, unknown>,
): string {
  const laneName = lane.trim() || "default";
  const runId = `lane-${laneName}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  registerLaneRun({
    runId,
    lane: laneName,
    status: "pending",
    task,
    metadata,
  });

  void enqueueCommandInLane(laneName, async () => {
    updateLaneRun(runId, { status: "running", startedAt: Date.now() });
    try {
      await cmd();
      updateLaneRun(runId, { status: "done", endedAt: Date.now() });
    } catch (err) {
      diag.error(`Lane run ${runId} failed: ${String(err)}`);
      updateLaneRun(runId, { status: "failed", endedAt: Date.now(), error: String(err) });
    }
  });

  return runId;
}

export function recoverLane(lane?: string): number {
  const laneName = lane?.trim();
  const runs = listLaneRuns(laneName);
  const toRecover = runs.filter((r) => r.status === "running" || r.status === "pending");
  let recovered = 0;
  for (const run of toRecover) {
    updateLaneRun(run.runId, {
      status: "stale",
      endedAt: Date.now(),
      error: "Recovered after process restart or timeout",
    });
    recovered++;
  }
  return recovered;
}

export function clearLane(lane?: string): number {
  const laneName = lane?.trim();
  if (laneName) {
    clearCommandLane(laneName);
  }
  return clearLaneRuns(laneName);
}

export function checkStaleRuns(staleThresholdMs: number = DEFAULT_STALE_THRESHOLD_MS) {
  const allRuns = listLaneRuns();
  const now = Date.now();
  let updatedCount = 0;
  for (const run of allRuns) {
    if (
      (run.status === "running" || run.status === "pending") &&
      now - run.updatedAt > staleThresholdMs
    ) {
      updateLaneRun(run.runId, {
        status: "stale",
        endedAt: now,
        error: "Watchdog detected stale run",
      });
      updatedCount++;
    }
  }
  return updatedCount;
}

export function startLaneWatchdog(intervalMs: number = DEFAULT_WATCHDOG_INTERVAL_MS) {
  const normalizedInterval = normalizeMs(intervalMs, DEFAULT_WATCHDOG_INTERVAL_MS);
  if (watchdogInterval && watchdogState.intervalMs === normalizedInterval) {
    watchdogState.running = true;
    return;
  }

  stopLaneWatchdog();
  watchdogState.running = true;
  watchdogState.intervalMs = normalizedInterval;
  watchdogInterval = setInterval(() => {
    checkStaleRuns(watchdogState.staleThresholdMs);
  }, normalizedInterval);
  watchdogInterval.unref?.();
}

export function stopLaneWatchdog() {
  if (watchdogInterval) {
    clearInterval(watchdogInterval);
    watchdogInterval = null;
  }
  watchdogState.running = false;
}

export function configureLaneWatchdog(config?: {
  enabled?: boolean;
  intervalMs?: number;
  staleThresholdMs?: number;
}): LaneWatchdogState {
  const enabled = config?.enabled === true;
  watchdogState.enabled = enabled;
  watchdogState.intervalMs = normalizeMs(config?.intervalMs, watchdogState.intervalMs);
  watchdogState.staleThresholdMs = normalizeMs(
    config?.staleThresholdMs,
    watchdogState.staleThresholdMs,
  );

  if (!enabled) {
    stopLaneWatchdog();
    return getLaneWatchdogState();
  }

  startLaneWatchdog(watchdogState.intervalMs);
  return getLaneWatchdogState();
}

export function getLaneWatchdogState(): LaneWatchdogState {
  return {
    enabled: watchdogState.enabled,
    running: watchdogState.running,
    intervalMs: watchdogState.intervalMs,
    staleThresholdMs: watchdogState.staleThresholdMs,
  };
}

export function getLaneSupervisorTotals() {
  return {
    queueSize: getTotalQueueSize(),
    runs: listLaneRuns().length,
  };
}
