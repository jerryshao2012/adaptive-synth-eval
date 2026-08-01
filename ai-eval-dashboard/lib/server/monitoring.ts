import { promises as fs } from "node:fs";
import path from "node:path";

import {
  getActiveMonitoringLaunch,
  projectMonitoringRun,
  startMonitoringRun,
} from "@/lib/server/monitoring-launch";
import { resolveRunDirectory } from "@/lib/server/run-paths";

import type {
  EvaluationRecord,
  EvaluationsResponse,
  MetricPointIdentity,
  MonitoringRunStatus,
  ProfilePeriod,
  RunSummary,
  TraceDetailsResponse,
} from "@/types/evaluation";

const REPO_ROOT = path.resolve(process.cwd(), "..");
const RUNS_DIR = path.join(REPO_ROOT, "outputs", "runs");
const DEFAULT_LIMIT = 2000;

function stringField(row: Record<string, unknown>, field: string): string | null {
  const value = row[field];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function profilePeriodsFromRunPlan(value: unknown): ProfilePeriod[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const periods = new Map<string, ProfilePeriod>();
  for (const valueRow of value) {
    if (!valueRow || typeof valueRow !== "object" || Array.isArray(valueRow)) {
      continue;
    }
    const row = valueRow as Record<string, unknown>;
    const instanceId = stringField(row, "profile_period_instance_id");
    const periodId = stringField(row, "profile_period_id");
    const start = stringField(row, "profile_period_start");
    const end = stringField(row, "profile_period_end");
    const conversationMode = stringField(row, "conversation_mode");
    const behaviorMode = stringField(row, "behavior_mode");
    if (
      !instanceId ||
      !periodId ||
      !start ||
      !end ||
      !conversationMode ||
      !behaviorMode
    ) {
      continue;
    }

    const existing = periods.get(instanceId);
    if (existing) {
      existing.plannedConversations += 1;
      continue;
    }
    const syntheticDay = stringField(row, "synthetic_day");
    periods.set(instanceId, {
      instanceId,
      periodId,
      start,
      end,
      conversationMode,
      behaviorMode,
      plannedConversations: 1,
      ...(syntheticDay ? { syntheticDay } : {}),
    });
  }

  return [...periods.values()].sort((left, right) => {
    const byStart = left.start.localeCompare(right.start);
    return byStart || left.instanceId.localeCompare(right.instanceId);
  });
}

function runDirPath(runId: string): string {
  return path.join(RUNS_DIR, runId);
}

export async function fileExists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

export async function readJsonFile<T>(filePath: string): Promise<T | null> {
  try {
    const content = await fs.readFile(filePath, "utf-8");
    return JSON.parse(content) as T;
  } catch {
    return null;
  }
}

async function readTextFile(filePath: string): Promise<string | null> {
  try {
    return await fs.readFile(filePath, "utf-8");
  } catch {
    return null;
  }
}

export async function readJsonLines<T>(filePath: string): Promise<T[]> {
  try {
    const content = await fs.readFile(filePath, "utf-8");
    return content
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .flatMap((line) => {
        try {
          return [JSON.parse(line) as T];
        } catch {
          return [] as T[];
        }
      });
  } catch {
    return [];
  }
}

function safeNumber(value: unknown): number {
  return typeof value === "number" ? value : Number(value || 0);
}

function clampPercent(completed: number, total: number): number {
  if (total <= 0) {
    return 0;
  }
  return Math.max(0, Math.min(100, Number(((completed / total) * 100).toFixed(2))));
}

function sortRuns(a: RunSummary, b: RunSummary): number {
  const left = a.updatedAt || a.startedAt || "";
  const right = b.updatedAt || b.startedAt || "";
  return right.localeCompare(left);
}

export async function listRunSummaries(): Promise<RunSummary[]> {
  let entries: Array<{ name: string; isDirectory: () => boolean }> = [];
  try {
    entries = (await fs.readdir(RUNS_DIR, {
      withFileTypes: true,
    })) as Array<{ name: string; isDirectory: () => boolean }>;
  } catch {
    return [];
  }

  const runs = await Promise.all(
    entries
      .filter((entry) => entry.isDirectory())
      .map(async (entry) => {
        const runId = entry.name;
        const runDir = runDirPath(runId);
        const monitoringState = await readJsonFile<Record<string, unknown>>(
          path.join(runDir, "monitoring_state.json")
        );
        const runState = await readJsonFile<Record<string, unknown>>(
          path.join(runDir, "run_state.json")
        );
        const runSummary = await readJsonFile<Record<string, unknown>>(
          path.join(runDir, "run_summary.json")
        );
        const hasScores = await fileExists(path.join(runDir, "monitoring_scores.jsonl"));
        const activeLaunch = await getActiveMonitoringLaunch(runDir);
        const projection = projectMonitoringRun(monitoringState, activeLaunch);

        const progressCompleted = safeNumber(
          monitoringState?.next_line_index ?? monitoringState?.evaluated_rows ?? 0
        );
        const progressTotal = safeNumber(monitoringState?.total_lines ?? 0);

        const summary: RunSummary = {
          runId,
          mode: String(runSummary?.mode || runState?.mode || "unknown"),
          monitoringStatus: projection.monitoringStatus,
          startedAt: String(
            monitoringState?.started_at || runState?.started_at || runSummary?.started_at || ""
          ),
          updatedAt: String(
            monitoringState?.updated_at || runState?.updated_at || runSummary?.completed_at || ""
          ),
          completedAt: runSummary?.completed_at ? String(runSummary.completed_at) : undefined,
          progress: {
            completed: progressCompleted,
            total: progressTotal,
            percent: clampPercent(progressCompleted, progressTotal),
          },
          evaluationFingerprint: monitoringState?.evaluation_fingerprint
            ? String(monitoringState.evaluation_fingerprint)
            : undefined,
          hasMonitoringState: Boolean(monitoringState),
          hasMonitoringScores: hasScores,
          canStart: projection.canStart,
          canContinue: projection.canContinue,
          canReevaluate: projection.canReevaluate,
        };

        return summary;
      })
  );

  return runs.sort(sortRuns);
}

export async function getMonitoringStatus(
  runId: string,
  repoRoot = REPO_ROOT
): Promise<MonitoringRunStatus | null> {
  const normalizedRunId = runId.trim();
  const runDir = await resolveRunDirectory(runId, repoRoot);

  const monitoringState = await readJsonFile<Record<string, unknown>>(
    path.join(runDir, "monitoring_state.json")
  );
  const progressMarkdown = await readTextFile(path.join(runDir, "eval_progress.md"));
  const hasScores = await fileExists(path.join(runDir, "monitoring_scores.jsonl"));
  const activeLaunch = await getActiveMonitoringLaunch(runDir);
  const projection = projectMonitoringRun(monitoringState, activeLaunch);

  const completed = safeNumber(
    monitoringState?.next_line_index ?? monitoringState?.evaluated_rows ?? 0
  );
  const total = safeNumber(monitoringState?.total_lines ?? 0);
  const rawTriggerMetrics =
    monitoringState?.trigger_metrics &&
    typeof monitoringState.trigger_metrics === "object"
      ? (monitoringState.trigger_metrics as Record<string, unknown>)
      : null;

  return {
    runId: normalizedRunId,
    monitoringStatus: projection.monitoringStatus,
    progress: {
      completed,
      total,
      percent: clampPercent(completed, total),
    },
    evaluationFingerprint: monitoringState?.evaluation_fingerprint
      ? String(monitoringState.evaluation_fingerprint)
      : undefined,
    progressMarkdown,
    state: monitoringState,
    hasMonitoringScores: hasScores,
    updatedAt: monitoringState?.updated_at ? String(monitoringState.updated_at) : undefined,
    triggerMetrics: rawTriggerMetrics
      ? {
          triggersDetected: safeNumber(rawTriggerMetrics.triggers_detected),
          rowsPromoted: safeNumber(rawTriggerMetrics.rows_promoted),
          budgetUsed: safeNumber(rawTriggerMetrics.budget_used),
          budgetAvailable: safeNumber(monitoringState?.sample_size),
          budgetDrops: safeNumber(rawTriggerMetrics.budget_drops),
          deduplicatedContext: safeNumber(
            rawTriggerMetrics.deduplicated_context
          ),
          pendingLookahead: safeNumber(rawTriggerMetrics.pending_lookahead),
          policyFingerprint: monitoringState?.trigger_policy_fingerprint
            ? String(monitoringState.trigger_policy_fingerprint)
            : undefined,
        }
      : undefined,
  };
}

export async function getMonitoringEvaluations(
  runId: string,
  from?: string,
  to?: string,
  limit: number | null = DEFAULT_LIMIT,
  repoRoot = REPO_ROOT
): Promise<EvaluationsResponse | null> {
  let runDir: string;
  try {
    runDir = await resolveRunDirectory(runId, repoRoot);
  } catch {
    return null;
  }
  const runPlan = await readJsonFile<unknown>(path.join(runDir, "run_plan.json"));
  const profilePeriods = profilePeriodsFromRunPlan(runPlan);
  const scoresPath = path.join(runDir, "monitoring_scores.jsonl");
  if (!(await fileExists(scoresPath))) {
    return {
      evaluations: [],
      profilePeriods,
      total: 0,
      from: from || "",
      to: to || "",
    };
  }

  const rows = await readJsonLines<EvaluationRecord & Record<string, unknown>>(scoresPath);
  const eligible = rows
    .filter((row) => {
      if (row.selected_for_monitoring === false) {
        return false;
      }
      if (!row.timestamp) {
        return false;
      }
      if (from && row.timestamp < from) {
        return false;
      }
      if (to && row.timestamp > to) {
        return false;
      }
      return true;
    })
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  const returned = limit === null ? eligible : eligible.slice(0, limit);
  const evaluations = returned
    .map((row) => ({
      ...row,
      run_id: runId,
      variant: row.variant || "raw",
    }));

  return {
    evaluations,
    profilePeriods,
    total: evaluations.length,
    from: from || "",
    to: to || "",
  };
}

function sameTurnId(left: unknown, right: unknown): boolean {
  return String(left ?? "") === String(right ?? "");
}

function sameConversationId(left: unknown, right: unknown): boolean {
  return String(left ?? "") === String(right ?? "");
}

export async function getMonitoringTraceDetails(
  point: MetricPointIdentity
): Promise<TraceDetailsResponse | null> {
  const runDir = runDirPath(point.runId);
  if (!(await fileExists(runDir))) {
    return null;
  }

  const scoresPath = path.join(runDir, "monitoring_scores.jsonl");
  const chatHistoryPath = path.join(runDir, "chat_history.jsonl");
  const turnsPath = path.join(runDir, "turns.jsonl");

  const evaluationRows = (
    await readJsonLines<EvaluationRecord & Record<string, unknown>>(scoresPath)
  ).filter((row) => row.selected_for_monitoring !== false);

  const matchedEvaluation =
    evaluationRows.find(
      (row) =>
        sameConversationId(row.conversation_id, point.conversationId) &&
        sameTurnId(row.turn_id, point.turnId)
    ) ||
    evaluationRows.find(
      (row) =>
        row.timestamp === point.timestamp &&
        sameTurnId(row.turn_id, point.turnId)
    ) ||
    null;

  const chatHistoryRows = await readJsonLines<Record<string, unknown>>(chatHistoryPath);
  const matchedChatHistory =
    chatHistoryRows.find(
      (row) =>
        sameConversationId(row.conversation_id, point.conversationId) &&
        sameTurnId(row.turn_id, point.turnId)
    ) || null;

  const turnRows = await readJsonLines<Record<string, unknown>>(turnsPath);
  const matchedTurn =
    turnRows.find(
      (row) =>
        sameConversationId(row.conversation_id, point.conversationId) &&
        sameTurnId(row.turn_id, point.turnId)
    ) || null;

  return {
    point,
    evaluationRecord: matchedEvaluation,
    chatHistoryRecord: matchedChatHistory,
    turnRecord: matchedTurn,
    notFoundReason:
      matchedEvaluation || matchedChatHistory || matchedTurn
        ? undefined
        : "No matching records were found for this chart point in monitoring/chat artifacts.",
  };
}

export { startMonitoringRun };
