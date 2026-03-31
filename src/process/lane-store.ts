import path from "node:path";
import { resolveStateDir } from "../config/paths.js";
import { loadJsonFile, saveJsonFile } from "../infra/json-file.js";

export type LaneRunStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "paused"
  | "stale"
  | "cancelled";

export interface LaneRunRecord {
  runId: string;
  lane: string;
  status: LaneRunStatus;
  task: string;
  createdAt: number;
  updatedAt: number;
  startedAt?: number;
  endedAt?: number;
  metadata?: Record<string, unknown>;
  error?: string;
  retryCount?: number;
  nextRetryAt?: number;
}

const VALID_STATUSES = new Set<LaneRunStatus>([
  "pending",
  "running",
  "done",
  "failed",
  "paused",
  "stale",
  "cancelled",
]);

function resolveLaneStorePath(): string {
  return path.join(resolveStateDir(), "lanes", "runs.json");
}

let memoryStore: Map<string, LaneRunRecord> = new Map();
let loaded = false;

function normalizeTimestamp(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  return fallback;
}

function normalizeOptionalTimestamp(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  return undefined;
}

function normalizeLaneRunRecord(raw: unknown): LaneRunRecord | undefined {
  if (!raw || typeof raw !== "object") {
    return undefined;
  }

  const obj = raw as Record<string, unknown>;
  const runId = typeof obj.runId === "string" ? obj.runId.trim() : "";
  const lane = typeof obj.lane === "string" ? obj.lane.trim() : "";
  const statusRaw = typeof obj.status === "string" ? obj.status.trim() : "";
  const task = typeof obj.task === "string" ? obj.task.trim() : "";
  if (!runId || !lane || !task || !VALID_STATUSES.has(statusRaw as LaneRunStatus)) {
    return undefined;
  }

  const now = Date.now();
  const createdAt = normalizeTimestamp(obj.createdAt, now);
  const updatedAt = normalizeTimestamp(obj.updatedAt, createdAt);
  const startedAt = normalizeOptionalTimestamp(obj.startedAt);
  const endedAt = normalizeOptionalTimestamp(obj.endedAt);
  const metadata =
    obj.metadata && typeof obj.metadata === "object" && !Array.isArray(obj.metadata)
      ? (obj.metadata as Record<string, unknown>)
      : undefined;
  const error = typeof obj.error === "string" ? obj.error : undefined;
  const retryCount =
    typeof obj.retryCount === "number" && Number.isFinite(obj.retryCount) && obj.retryCount >= 0
      ? Math.floor(obj.retryCount)
      : undefined;
  const nextRetryAt = normalizeOptionalTimestamp(obj.nextRetryAt);

  return {
    runId,
    lane,
    status: statusRaw as LaneRunStatus,
    task,
    createdAt,
    updatedAt: Math.max(createdAt, updatedAt),
    startedAt,
    endedAt,
    metadata,
    error,
    retryCount,
    nextRetryAt,
  };
}

function loadLaneRunsFromDisk(): Map<string, LaneRunRecord> {
  const pathname = resolveLaneStorePath();
  const raw = loadJsonFile(pathname);
  const parsed = new Map<string, LaneRunRecord>();
  if (!raw || typeof raw !== "object") {
    return parsed;
  }
  const runs = (raw as { runs?: unknown }).runs;
  if (!Array.isArray(runs)) {
    return parsed;
  }
  for (const candidate of runs) {
    const normalized = normalizeLaneRunRecord(candidate);
    if (!normalized) {
      continue;
    }
    parsed.set(normalized.runId, normalized);
  }
  return parsed;
}

export function loadLaneStore(): Map<string, LaneRunRecord> {
  if (loaded) {
    return memoryStore;
  }
  memoryStore = loadLaneRunsFromDisk();
  loaded = true;
  return memoryStore;
}

export function saveLaneStore(): void {
  const pathname = resolveLaneStorePath();
  const runs = Array.from(memoryStore.values()).toSorted((a, b) => a.createdAt - b.createdAt);
  saveJsonFile(pathname, { version: 1, runs });
}

export function registerLaneRun(record: Omit<LaneRunRecord, "createdAt" | "updatedAt">): void {
  const store = loadLaneStore();
  const now = Date.now();
  store.set(record.runId, {
    ...record,
    createdAt: now,
    updatedAt: now,
  });
  saveLaneStore();
}

export function updateLaneRun(runId: string, patch: Partial<LaneRunRecord>): void {
  const store = loadLaneStore();
  const existing = store.get(runId);
  if (!existing) {
    return;
  }
  store.set(runId, { ...existing, ...patch, updatedAt: Date.now() });
  saveLaneStore();
}

export function getLaneRun(runId: string): LaneRunRecord | undefined {
  return loadLaneStore().get(runId);
}

export function listLaneRuns(lane?: string): LaneRunRecord[] {
  const all = Array.from(loadLaneStore().values()).toSorted((a, b) => a.createdAt - b.createdAt);
  if (!lane) {
    return all;
  }
  return all.filter((r) => r.lane === lane);
}

export function clearLaneRuns(lane?: string): number {
  const store = loadLaneStore();
  if (!lane) {
    const count = store.size;
    store.clear();
    saveLaneStore();
    return count;
  }
  let count = 0;
  for (const [runId, record] of store.entries()) {
    if (record.lane === lane) {
      store.delete(runId);
      count++;
    }
  }
  if (count > 0) {
    saveLaneStore();
  }
  return count;
}

export function resetLaneStoreForTest(): void {
  memoryStore = new Map();
  loaded = false;
}
