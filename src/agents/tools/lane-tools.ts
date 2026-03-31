import { Type } from "@sinclair/typebox";
import {
  clearLane,
  getLaneStatus,
  getLaneSupervisorTotals,
  getLaneWatchdogState,
  recoverLane,
  spawnInLane,
} from "../../process/lane-supervisor.js";
import type { GatewayMessageChannel } from "../../utils/message-channel.js";
import { optionalStringEnum } from "../schema/typebox.js";
import { spawnSubagentDirect } from "../subagent-spawn.js";
import type { AnyAgentTool } from "./common.js";
import { jsonResult, readStringParam } from "./common.js";

const LANE_ACTIONS = ["status", "recover", "clear"] as const;

export const LaneSupervisorToolSchema = Type.Object({
  action: optionalStringEnum(LANE_ACTIONS),
  lane: Type.Optional(Type.String()),
  task: Type.Optional(Type.String()),
});

export function createLaneSupervisorTool(): AnyAgentTool {
  return {
    label: "Lane Supervisor",
    name: "lane_supervisor",
    description: "Inspect and manage lane runs and lifecycle.",
    parameters: LaneSupervisorToolSchema,
    execute: async (_toolCallId, args) => {
      const params = args as Record<string, unknown>;
      const action = (readStringParam(params, "action") ??
        "status") as (typeof LANE_ACTIONS)[number];
      const lane = readStringParam(params, "lane");

      if (action === "status") {
        const laneName = lane || "default";
        const status = getLaneStatus(laneName);
        return jsonResult({
          status: "ok",
          action: "status",
          ...status,
          totals: getLaneSupervisorTotals(),
          watchdog: getLaneWatchdogState(),
        });
      }

      if (action === "recover") {
        const count = recoverLane(lane);
        return jsonResult({ status: "ok", action: "recover", lane: lane ?? "all", count });
      }

      const count = clearLane(lane);
      return jsonResult({ status: "ok", action: "clear", lane: lane ?? "all", count });
    },
  };
}

export function createLaneSpawnTool(opts?: {
  agentSessionKey?: string;
  agentChannel?: GatewayMessageChannel;
  agentAccountId?: string;
  agentTo?: string;
  agentThreadId?: string | number;
  agentGroupId?: string | null;
  agentGroupChannel?: string | null;
  agentGroupSpace?: string | null;
  requesterAgentIdOverride?: string;
}): AnyAgentTool {
  return {
    label: "Lane Spawn",
    name: "lane_spawn",
    description: "Spawn a persistent run in a dedicated lane with continuity rails.",
    parameters: Type.Object({
      task: Type.String(),
      lane: Type.Optional(Type.String()),
      kind: Type.Optional(Type.String()), // subagent, announce, etc.
      model: Type.Optional(Type.String()),
      thinking: Type.Optional(Type.String()),
    }),
    execute: async (_toolCallId, args) => {
      const params = args as Record<string, unknown>;
      const task = readStringParam(params, "task", { required: true });
      const lane = readStringParam(params, "lane") || "default";
      const kind = readStringParam(params, "kind") || "subagent";
      const model = readStringParam(params, "model");
      const thinking = readStringParam(params, "thinking");

      const runId = spawnInLane(
        lane,
        task,
        async () => {
          if (kind === "subagent") {
            return await spawnSubagentDirect(
              {
                task,
                label: `lane-${lane}`,
                model,
                thinking,
                expectsCompletionMessage: true,
              },
              {
                agentSessionKey: opts?.agentSessionKey,
                agentChannel: opts?.agentChannel,
                agentAccountId: opts?.agentAccountId,
                agentTo: opts?.agentTo,
                agentThreadId: opts?.agentThreadId,
                agentGroupId: opts?.agentGroupId,
                agentGroupChannel: opts?.agentGroupChannel,
                agentGroupSpace: opts?.agentGroupSpace,
                requesterAgentIdOverride: opts?.requesterAgentIdOverride,
              },
            );
          }
          // Fallback or other kinds
          return { status: "ok", message: "Task completed (no-op kind)" };
        },
        { kind, model, thinking },
      );

      return jsonResult({ status: "ok", action: "spawn", runId, lane, task, kind });
    },
  };
}
