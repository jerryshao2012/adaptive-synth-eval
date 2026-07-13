import { promises as fs } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";

import type {
  EvaluationRecord,
  EvaluationsResponse,
  MetricPointIdentity,
  MonitoringRunStatus,
  MonitoringStartRequest,
  MonitoringStartResponse,
  RunSummary,
  TraceDetailsResponse,
} from "@/types/evaluation";

const REPO_ROOT = path.resolve(process.cwd(), "..");
const RUNS_DIR = path.join(REPO_ROOT, "outputs", "runs");
const DEFAULT_LIMIT = 2000;
const MONITORING_LAUNCH_LOCK_FILE = ".monitoring-launch.lock.json";
const MONITORING_LAUNCH_LOCK_TTL_MS = 30000;

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

function monitoringLaunchLockPath(runDir: string): string {
  return path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
}

async function removeLaunchLock(runDir: string): Promise<void> {
  try {
    await fs.unlink(monitoringLaunchLockPath(runDir));
  } catch {
    // Ignore missing or concurrently-removed locks.
  }
}

async function isLaunchLockActive(runDir: string): Promise<boolean> {
  const lock = await readJsonFile<{ expiresAt?: number }>(
    monitoringLaunchLockPath(runDir)
  );
  if (!lock) {
    return false;
  }

  if (typeof lock.expiresAt === "number" && lock.expiresAt > Date.now()) {
    return true;
  }

  await removeLaunchLock(runDir);
  return false;
}

async function acquireLaunchLock(
  runDir: string,
  payload: Record<string, unknown>
): Promise<boolean> {
  const lockPath = monitoringLaunchLockPath(runDir);

  try {
    await fs.writeFile(lockPath, JSON.stringify(payload, null, 2), {
      encoding: "utf-8",
      flag: "wx",
    });
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
      throw error;
    }
  }

  if (await isLaunchLockActive(runDir)) {
    return false;
  }

  await removeLaunchLock(runDir);

  try {
    await fs.writeFile(lockPath, JSON.stringify(payload, null, 2), {
      encoding: "utf-8",
      flag: "wx",
    });
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      return false;
    }
    throw error;
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

function statusLabel(
  stateStatus: string | undefined,
  hasScores: boolean,
  hasLaunchLock = false
): RunSummary["monitoringStatus"] {
  const normalized = (stateStatus || "").toLowerCase();
  if (normalized === "completed") {
    return "completed";
  }
  if (normalized === "queued") {
    return "queued";
  }
  if (normalized === "in_progress") {
    return "in_progress";
  }
  if (hasLaunchLock) {
    return "queued";
  }
  if (hasScores) {
    return "in_progress";
  }
  return "not_started";
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
        const hasLaunchLock = await isLaunchLockActive(runDir);
        const monitoringStateStatus =
          typeof monitoringState?.status === "string" ? monitoringState.status.toLowerCase() : "";

        const progressCompleted = safeNumber(
          monitoringState?.next_line_index ?? monitoringState?.evaluated_rows ?? 0
        );
        const progressTotal = safeNumber(monitoringState?.total_lines ?? 0);

        const summary: RunSummary = {
          runId,
          mode: String(runSummary?.mode || runState?.mode || "unknown"),
          monitoringStatus: statusLabel(
            typeof monitoringState?.status === "string" ? monitoringState.status : undefined,
            hasScores,
            hasLaunchLock
          ),
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
          canStart: !monitoringState && !hasLaunchLock,
          canContinue:
            Boolean(monitoringState) &&
            monitoringStateStatus !== "completed" &&
            monitoringStateStatus !== "in_progress" &&
            !hasLaunchLock,
        };

        return summary;
      })
  );

  return runs.sort(sortRuns);
}

export async function getMonitoringStatus(runId: string): Promise<MonitoringRunStatus | null> {
  const runDir = runDirPath(runId);
  const exists = await fileExists(runDir);
  if (!exists) {
    return null;
  }

  const monitoringState = await readJsonFile<Record<string, unknown>>(
    path.join(runDir, "monitoring_state.json")
  );
  const progressMarkdown = await readTextFile(path.join(runDir, "eval_progress.md"));
  const hasScores = await fileExists(path.join(runDir, "monitoring_scores.jsonl"));
  const hasLaunchLock = await isLaunchLockActive(runDir);

  const completed = safeNumber(
    monitoringState?.next_line_index ?? monitoringState?.evaluated_rows ?? 0
  );
  const total = safeNumber(monitoringState?.total_lines ?? 0);

  return {
    runId,
    monitoringStatus: statusLabel(
      typeof monitoringState?.status === "string" ? monitoringState.status : undefined,
      hasScores,
      hasLaunchLock
    ),
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
  };
}

export async function getMonitoringEvaluations(
  runId: string,
  from?: string,
  to?: string,
  limit = DEFAULT_LIMIT
): Promise<EvaluationsResponse | null> {
  const runDir = runDirPath(runId);
  const scoresPath = path.join(runDir, "monitoring_scores.jsonl");
  if (!(await fileExists(runDir))) {
    return null;
  }
  if (!(await fileExists(scoresPath))) {
    return {
      evaluations: [],
      total: 0,
      from: from || "",
      to: to || "",
    };
  }

  const rows = await readJsonLines<EvaluationRecord & Record<string, unknown>>(scoresPath);
  const filtered = rows
    .filter((row) => {
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
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    .slice(0, limit)
    .map((row) => ({
      ...row,
      run_id: runId,
      variant: row.variant || "raw",
    }));

  return {
    evaluations: filtered,
    total: filtered.length,
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

  const evaluationRows = await readJsonLines<EvaluationRecord & Record<string, unknown>>(
    scoresPath
  );

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

function quoteArg(value: string): string {
  if (!value.includes(" ")) {
    return value;
  }
  return `"${value}"`;
}

export async function startMonitoringRun(
  request: MonitoringStartRequest
): Promise<MonitoringStartResponse> {
  const runId = request.runId.trim();
  const runFolder = runDirPath(runId);
  const sampleSize = Number(request.sampleSize ?? 1000);
  const intervalMinutes = Number(request.intervalMinutes ?? 30);
  const incompleteAction = request.action === "continue" ? "resume" : "restart";

  if (!(await fileExists(runFolder))) {
    throw new Error(`Run folder not found: ${runFolder}`);
  }
  if (!Number.isFinite(sampleSize) || sampleSize <= 0) {
    throw new Error("sampleSize must be a positive number.");
  }
  if (!Number.isFinite(intervalMinutes) || intervalMinutes <= 0) {
    throw new Error("intervalMinutes must be a positive number.");
  }

  const command = [
    "uv",
    "run",
    "ase",
    "monitor",
    "run",
    "--run-folder",
    quoteArg(path.relative(REPO_ROOT, runFolder) || runFolder),
    "--sample-size",
    String(sampleSize),
    "--interval-minutes",
    String(intervalMinutes),
    "--incomplete-run-action",
    incompleteAction,
  ].join(" ");

  const monitoringState = await readJsonFile<Record<string, unknown>>(
    path.join(runFolder, "monitoring_state.json")
  );
  const normalizedStateStatus =
    typeof monitoringState?.status === "string" ? monitoringState.status.toLowerCase() : "";

  if (normalizedStateStatus === "in_progress") {
    return {
      runId,
      started: false,
      command,
      monitoringStatus: "in_progress",
    };
  }

  const lockAcquired = await acquireLaunchLock(runFolder, {
    runId,
    action: request.action,
    createdAt: new Date().toISOString(),
    expiresAt: Date.now() + MONITORING_LAUNCH_LOCK_TTL_MS,
  });

  if (!lockAcquired) {
    return {
      runId,
      started: false,
      command,
      monitoringStatus: normalizedStateStatus === "in_progress" ? "in_progress" : "queued",
    };
  }

  try {
    const child = spawn(command, [], {
      cwd: REPO_ROOT,
      detached: true,
      stdio: "ignore",
      shell: true,
    });
    child.unref();
  } catch (error) {
    await removeLaunchLock(runFolder);
    throw error;
  }

  return {
    runId,
    started: true,
    command,
    monitoringStatus: incompleteAction === "resume" ? "in_progress" : "queued",
  };
}
