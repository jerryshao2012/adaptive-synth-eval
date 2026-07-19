import { spawn as nodeSpawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

import { buildMonitoringArgs } from "@/lib/monitoring-config";
import { resolveRunDirectory } from "@/lib/server/run-paths";
import type {
  MonitoringAction,
  MonitoringStartRequest,
  MonitoringStartResponse,
  RunSummary,
} from "@/types/evaluation";

export const MONITORING_LAUNCH_LOCK_FILE = ".monitoring-launch.lock.json";
export const MONITORING_LOG_FILE = "monitoring.log";
const QUEUED_LOCK_TTL_MS = 30_000;
const TERMINATION_GRACE_MS = 5_000;

export type MonitoringLaunchPhase = "queued" | "running" | "rollback_failed";

export interface MonitoringLaunchLock {
  launchId: string;
  action: MonitoringAction;
  phase?: MonitoringLaunchPhase;
  createdAt: string;
  expiresAt: number;
  pid?: number;
}

interface RollbackFailureMarker {
  lock: MonitoringLaunchLock;
  closeConfirmed: boolean;
}

const inProcessRollbackFailures = new Map<string, RollbackFailureMarker>();

export interface LaunchChild {
  pid?: number;
  exitCode?: number | null;
  signalCode?: NodeJS.Signals | null;
  kill(signal?: NodeJS.Signals | number): boolean;
  once(event: "spawn", listener: () => void): this;
  once(event: "error", listener: (error: Error) => void): this;
  once(event: "close", listener: (...args: unknown[]) => void): this;
  removeListener(event: "spawn", listener: () => void): this;
  removeListener(event: "error", listener: (error: Error) => void): this;
  removeListener(event: "close", listener: (...args: unknown[]) => void): this;
  unref(): void;
}

export interface LaunchLogHandle {
  fd: number;
  appendFile(data: string): Promise<unknown>;
  close(): Promise<unknown>;
}

export interface LaunchOptions {
  cwd: string;
  detached: true;
  shell: false;
  stdio: ["ignore", number, number];
}

export interface MonitoringLaunchDependencies {
  repoRoot?: string;
  spawn: (file: string, args: string[], options: LaunchOptions) => LaunchChild;
  kill?: (pid: number, signal?: NodeJS.Signals | 0) => boolean;
  now?: () => Date;
  launchId?: () => string;
  openLog?: (logPath: string) => Promise<LaunchLogHandle>;
  promoteLock?: (
    lockPath: string,
    lock: MonitoringLaunchLock
  ) => Promise<void>;
  persistRollbackFailedLock?: (
    lockPath: string,
    lock: MonitoringLaunchLock
  ) => Promise<void>;
  removeMatchingLock?: (lockPath: string, launchId: string) => Promise<void>;
  readLockFile?: (lockPath: string) => Promise<string>;
  reportLogCloseError?: (error: unknown) => void;
  terminationGraceMs?: number;
}

type LivenessDependencies = Pick<
  MonitoringLaunchDependencies,
  "kill" | "now" | "readLockFile" | "removeMatchingLock"
>;

export class MonitoringLaunchRollbackError extends Error {
  readonly launchError: unknown;
  readonly rollbackError?: unknown;

  constructor(message: string, launchError: unknown, rollbackError?: unknown) {
    super(message);
    this.name = "MonitoringLaunchRollbackError";
    this.launchError = launchError;
    this.rollbackError = rollbackError;
    this.cause = launchError;
  }
}

export class MonitoringLaunchLockReadError extends Error {
  readonly lockPath: string;

  constructor(lockPath: string, cause: unknown) {
    super(`Could not read monitoring launch lock '${lockPath}': ${errorMessage(cause)}`);
    this.name = "MonitoringLaunchLockReadError";
    this.lockPath = lockPath;
    this.cause = cause;
  }
}

function defaultRepoRoot(): string {
  return path.resolve(process.cwd(), "..");
}

function lockPathFor(runDirectory: string): string {
  return path.join(runDirectory, MONITORING_LAUNCH_LOCK_FILE);
}

async function readLock(
  lockPath: string,
  readLockFile: (lockPath: string) => Promise<string> = (candidate) =>
    fs.readFile(candidate, "utf8")
): Promise<MonitoringLaunchLock | null> {
  let content: string;
  try {
    content = await readLockFile(lockPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return null;
    }
    throw new MonitoringLaunchLockReadError(lockPath, error);
  }

  try {
    const value = JSON.parse(content) as Record<string, unknown>;
    const action = value.action;
    if (action !== "start" && action !== "continue" && action !== "reevaluate") {
      throw new Error("lock action is invalid");
    }
    if (typeof value.launchId !== "string" || !value.launchId) {
      throw new Error("lock launchId is invalid");
    }
    if (typeof value.createdAt !== "string" || !value.createdAt) {
      throw new Error("lock createdAt is invalid");
    }
    const createdAt = value.createdAt;
    const phase = value.phase;
    if (
      phase !== undefined &&
      phase !== "queued" &&
      phase !== "running" &&
      phase !== "rollback_failed"
    ) {
      throw new Error("lock phase is invalid");
    }
    return {
      launchId: value.launchId,
      action,
      phase:
        phase === "running" || phase === "rollback_failed" ? phase : "queued",
      createdAt,
      expiresAt:
        typeof value.expiresAt === "number"
          ? value.expiresAt
          : Date.parse(createdAt) + QUEUED_LOCK_TTL_MS,
      pid:
        typeof value.pid === "number" && Number.isInteger(value.pid) && value.pid > 0
          ? value.pid
          : undefined,
    };
  } catch (error) {
    throw new MonitoringLaunchLockReadError(lockPath, error);
  }
}

async function removeLockSnapshot(
  lockPath: string,
  snapshot: MonitoringLaunchLock,
  readLockFile?: (lockPath: string) => Promise<string>
): Promise<void> {
  const current = await readLock(lockPath, readLockFile);
  if (
    !current ||
    (snapshot.launchId
      ? current.launchId !== snapshot.launchId
      : current.createdAt !== snapshot.createdAt || current.pid !== snapshot.pid)
  ) {
    return;
  }
  try {
    await fs.unlink(lockPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }
}

export async function removeMatchingMonitoringLock(
  lockPath: string,
  launchId: string
): Promise<void> {
  const current = await readLock(lockPath);
  if (!current || current.launchId !== launchId) {
    return;
  }
  await removeLockSnapshot(lockPath, current);
}

export async function promoteMonitoringLock(
  lockPath: string,
  lock: MonitoringLaunchLock
): Promise<void> {
  const current = await readLock(lockPath);
  if (!current || current.launchId !== lock.launchId) {
    throw new Error("Monitoring launch lock ownership changed before PID persistence.");
  }

  const temporaryPath = `${lockPath}.${lock.launchId}.tmp`;
  try {
    await fs.writeFile(temporaryPath, JSON.stringify(lock, null, 2), {
      encoding: "utf8",
      flag: "wx",
    });
    await fs.rename(temporaryPath, lockPath);
  } catch (error) {
    try {
      await fs.unlink(temporaryPath);
    } catch {
      // The temporary file may not have been created.
    }
    throw error;
  }
}

async function retryRollbackFailureCleanup(
  lockPath: string,
  marker: RollbackFailureMarker,
  dependencies: LivenessDependencies
): Promise<void> {
  const current = await readLock(lockPath, dependencies.readLockFile);
  if (
    current?.launchId === marker.lock.launchId &&
    (current.phase === "rollback_failed" || current.phase === "queued")
  ) {
    const removeMatchingLock =
      dependencies.removeMatchingLock ?? removeMatchingMonitoringLock;
    await removeMatchingLock(lockPath, marker.lock.launchId);
  }
  if (inProcessRollbackFailures.get(lockPath) === marker) {
    inProcessRollbackFailures.delete(lockPath);
  }
}

function pidIsAlive(pid: number, kill: NonNullable<MonitoringLaunchDependencies["kill"]>): boolean {
  try {
    kill(pid, 0);
    return true;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "EPERM") {
      return true;
    }
    if (code === "ESRCH") {
      return false;
    }
    throw error;
  }
}

export async function getActiveMonitoringLaunch(
  runDirectory: string,
  dependencies: LivenessDependencies = {}
): Promise<MonitoringLaunchLock | null> {
  const lockPath = lockPathFor(runDirectory);
  const inProcessFailure = inProcessRollbackFailures.get(lockPath);
  if (inProcessFailure) {
    if (!inProcessFailure.closeConfirmed) {
      return inProcessFailure.lock;
    }
    try {
      await retryRollbackFailureCleanup(lockPath, inProcessFailure, dependencies);
    } catch {
      return inProcessFailure.lock;
    }
    const remainingFailure = inProcessRollbackFailures.get(lockPath);
    if (remainingFailure) {
      return remainingFailure.lock;
    }
  }
  const lock = await readLock(lockPath, dependencies.readLockFile);
  if (!lock) {
    return null;
  }

  const kill = dependencies.kill ?? process.kill.bind(process);
  const now = dependencies.now ?? (() => new Date());
  let active: boolean;
  if (lock.phase === "rollback_failed") {
    active =
      !lock.pid || pidIsAlive(lock.pid, kill);
  } else {
    active = lock.pid ? pidIsAlive(lock.pid, kill) : lock.expiresAt > now().getTime();
  }
  if (active) {
    return lock;
  }

  await removeLockSnapshot(lockPath, lock, dependencies.readLockFile);
  return null;
}

export function projectMonitoringRun(
  state: Record<string, unknown> | null,
  activeLaunch: MonitoringLaunchLock | null
): Pick<RunSummary, "monitoringStatus" | "canStart" | "canContinue" | "canReevaluate"> {
  let monitoringStatus: RunSummary["monitoringStatus"];
  if (activeLaunch) {
    const stateStatus = typeof state?.status === "string" ? state.status.toLowerCase() : "";
    const updatedAtValue = state?.updated_at ?? state?.updatedAt;
    const stateUpdatedAt = typeof updatedAtValue === "string" ? Date.parse(updatedAtValue) : NaN;
    const launchCreatedAt = Date.parse(activeLaunch.createdAt);
    monitoringStatus =
      stateStatus === "in_progress" &&
      Number.isFinite(stateUpdatedAt) &&
      Number.isFinite(launchCreatedAt) &&
      stateUpdatedAt > launchCreatedAt
        ? "in_progress"
        : "queued";
  } else if (!state) {
    monitoringStatus = "not_started";
  } else if (
    typeof state.status === "string" &&
    state.status.toLowerCase() === "completed"
  ) {
    monitoringStatus = "completed";
  } else {
    monitoringStatus = "incomplete";
  }

  return {
    monitoringStatus,
    canStart: monitoringStatus === "not_started",
    canContinue: monitoringStatus === "incomplete",
    canReevaluate: monitoringStatus === "completed",
  };
}

function waitForSpawn(child: LaunchChild): Promise<void> {
  return new Promise((resolve, reject) => {
    const onSpawn = () => {
      child.removeListener("error", onError);
      resolve();
    };
    const onError = (error: Error) => {
      child.removeListener("spawn", onSpawn);
      reject(error);
    };
    child.once("spawn", onSpawn);
    child.once("error", onError);
  });
}

interface CloseWaiter {
  promise: Promise<boolean>;
  cancel(): void;
}

function waitForClose(child: LaunchChild, timeoutMs: number): CloseWaiter {
  if (child.exitCode !== null && child.exitCode !== undefined) {
    return { promise: Promise.resolve(true), cancel: () => undefined };
  }
  if (child.signalCode !== null && child.signalCode !== undefined) {
    return { promise: Promise.resolve(true), cancel: () => undefined };
  }
  let settle: ((closed: boolean) => void) | undefined;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let onClose: (...args: unknown[]) => void = () => undefined;
  const promise = new Promise<boolean>((resolve) => {
    settle = resolve;
    onClose = () => {
      if (timeout) clearTimeout(timeout);
      settle = undefined;
      resolve(true);
    };
    child.once("close", onClose);
    timeout = setTimeout(() => {
      child.removeListener("close", onClose);
      settle = undefined;
      resolve(false);
    }, timeoutMs);
  });
  return {
    promise,
    cancel: () => {
      if (!settle) return;
      if (timeout) clearTimeout(timeout);
      child.removeListener("close", onClose);
      const resolve = settle;
      settle = undefined;
      resolve(false);
    },
  };
}

function signalDetachedChild(
  child: LaunchChild,
  pid: number | undefined,
  signal: NodeJS.Signals,
  kill: NonNullable<MonitoringLaunchDependencies["kill"]>,
): "sent" | "absent" {
  try {
    if (pid) kill(-pid, signal);
    else child.kill(signal);
    return "sent";
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") {
      return "absent";
    }
    throw error;
  }
}

async function terminateAndReap(
  child: LaunchChild,
  pid: number | undefined,
  kill: NonNullable<MonitoringLaunchDependencies["kill"]>,
  timeoutMs: number
): Promise<boolean> {
  const closedAfterTerm = waitForClose(child, timeoutMs);
  let termResult: "sent" | "absent";
  try {
    termResult = signalDetachedChild(child, pid, "SIGTERM", kill);
  } catch (error) {
    closedAfterTerm.cancel();
    throw error;
  }
  if (termResult === "absent") {
    return closedAfterTerm.promise;
  }
  if (await closedAfterTerm.promise) return true;

  const closedAfterKill = waitForClose(child, timeoutMs);
  let killResult: "sent" | "absent";
  try {
    killResult = signalDetachedChild(child, pid, "SIGKILL", kill);
  } catch (error) {
    closedAfterKill.cancel();
    throw error;
  }
  if (killResult === "absent") {
    return closedAfterKill.promise;
  }
  return closedAfterKill.promise;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function displayQuote(argument: string): string {
  return /^[A-Za-z0-9_./:=+-]+$/.test(argument)
    ? argument
    : `'${argument.replaceAll("'", `'\\''`)}'`;
}

async function acquireLaunchLock(
  runDirectory: string,
  lock: MonitoringLaunchLock,
  dependencies: LivenessDependencies
): Promise<{ acquired: boolean; active: MonitoringLaunchLock | null }> {
  const lockPath = lockPathFor(runDirectory);
  const write = async () => {
    await fs.writeFile(lockPath, JSON.stringify(lock, null, 2), {
      encoding: "utf8",
      flag: "wx",
    });
  };

  const existingActive = await getActiveMonitoringLaunch(runDirectory, dependencies);
  if (existingActive) {
    return { acquired: false, active: existingActive };
  }

  try {
    await write();
    return { acquired: true, active: lock };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }

  const active = await getActiveMonitoringLaunch(runDirectory, dependencies);
  if (active) {
    return { acquired: false, active };
  }

  try {
    await write();
    return { acquired: true, active: lock };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      return {
        acquired: false,
        active: await getActiveMonitoringLaunch(runDirectory, dependencies),
      };
    }
    throw error;
  }
}

export function createMonitoringLauncher(
  dependencies: MonitoringLaunchDependencies
): (request: MonitoringStartRequest) => Promise<MonitoringStartResponse> {
  const repoRoot = dependencies.repoRoot ?? defaultRepoRoot();
  const now = dependencies.now ?? (() => new Date());
  const makeLaunchId = dependencies.launchId ?? randomUUID;
  const kill = dependencies.kill ?? process.kill.bind(process);
  const openLog =
    dependencies.openLog ??
    (async (logPath: string) => (await fs.open(logPath, "a")) as LaunchLogHandle);
  const promoteLock = dependencies.promoteLock ?? promoteMonitoringLock;
  const persistRollbackFailedLock =
    dependencies.persistRollbackFailedLock ?? promoteMonitoringLock;
  const removeMatchingLock = dependencies.removeMatchingLock ?? removeMatchingMonitoringLock;
  const readLockFile =
    dependencies.readLockFile ?? ((lockPath: string) => fs.readFile(lockPath, "utf8"));
  const reportLogCloseError =
    dependencies.reportLogCloseError ??
    ((error: unknown) => console.error("Failed to close monitoring log descriptor.", error));

  return async (request) => {
    const runDirectory = await resolveRunDirectory(request.runId, repoRoot);
    const runId = request.runId.trim();
    const relativeRunFolder = path.relative(repoRoot, runDirectory);
    const args = buildMonitoringArgs(request, relativeRunFolder);
    const command = ["uv", ...args].map(displayQuote).join(" ");
    const createdAt = now();
    const lock: MonitoringLaunchLock = {
      launchId: makeLaunchId(),
      action: request.action,
      phase: "queued",
      createdAt: createdAt.toISOString(),
      expiresAt: createdAt.getTime() + QUEUED_LOCK_TTL_MS,
    };

    const lockResult = await acquireLaunchLock(runDirectory, lock, {
      kill,
      now,
      readLockFile,
      removeMatchingLock,
    });
    if (!lockResult.acquired) {
      let state: Record<string, unknown> | null = null;
      try {
        state = JSON.parse(
          await fs.readFile(path.join(runDirectory, "monitoring_state.json"), "utf8")
        ) as Record<string, unknown>;
      } catch {
        // The runner may not have created state yet.
      }
      const projected = projectMonitoringRun(state, lockResult.active);
      return {
        runId,
        started: false,
        command,
        monitoringStatus:
          projected.monitoringStatus === "in_progress" ? "in_progress" : "queued",
      };
    }

    const lockPath = lockPathFor(runDirectory);
    let log: LaunchLogHandle | null = null;
    let child: LaunchChild | null = null;
    let spawned = false;
    try {
      log = await openLog(path.join(runDirectory, MONITORING_LOG_FILE));
      await log.appendFile(
        `[${lock.createdAt}] monitoring launch action=${request.action} command=${command}\n`
      );
      child = dependencies.spawn("uv", args, {
        cwd: repoRoot,
        detached: true,
        shell: false,
        stdio: ["ignore", log.fd, log.fd],
      });
      await waitForSpawn(child);
      spawned = true;
      if (!child.pid) {
        throw new Error("Monitoring process spawned without a PID.");
      }
      await promoteLock(lockPath, { ...lock, phase: "running", pid: child.pid });
      child.unref();
      return {
        runId,
        started: true,
        command,
        monitoringStatus: "queued",
      };
    } catch (error) {
      const retainFailedLock = async (
        reason: string,
        rollbackError?: unknown
      ): Promise<never> => {
        const failedLock: MonitoringLaunchLock = {
          ...lock,
          phase: "rollback_failed",
          ...(child?.pid ? { pid: child.pid } : {}),
        };
        let persistenceSettled = false;
        let closeObserved = false;
        const failureMarker: RollbackFailureMarker = {
          lock: failedLock,
          closeConfirmed: false,
        };
        inProcessRollbackFailures.set(lockPath, failureMarker);

        const finishLateCloseCleanup = async () => {
          await retryRollbackFailureCleanup(lockPath, failureMarker, {
            kill,
            now,
            readLockFile,
            removeMatchingLock,
          });
        };
        const onLateClose = () => {
          closeObserved = true;
          failureMarker.closeConfirmed = true;
          if (persistenceSettled) {
            void finishLateCloseCleanup().catch(() => {
              // Keep the in-process fail-closed marker when late cleanup fails.
            });
          }
        };
        child?.once("close", onLateClose);
        if (
          (child?.exitCode !== null && child?.exitCode !== undefined) ||
          (child?.signalCode !== null && child?.signalCode !== undefined)
        ) {
          child.removeListener("close", onLateClose);
          onLateClose();
        }

        let persistenceFailed = false;
        let persistenceError: unknown;
        try {
          await persistRollbackFailedLock(lockPath, failedLock);
        } catch (errorDuringPersistence) {
          persistenceFailed = true;
          persistenceError = errorDuringPersistence;
        } finally {
          persistenceSettled = true;
          if (closeObserved) {
            void finishLateCloseCleanup().catch(() => {
              // Keep the in-process fail-closed marker when late cleanup fails.
            });
          }
        }
        if (persistenceFailed) {
          throw new MonitoringLaunchRollbackError(
            `Monitoring launch failed (${errorMessage(error)}); ${reason}; rollback_failed lock persistence failed (${errorMessage(persistenceError)}). The original launch lock was retained in its best available state.`,
            error,
            rollbackError ?? persistenceError
          );
        }

        throw new MonitoringLaunchRollbackError(
          `Monitoring launch failed (${errorMessage(error)}); ${reason}; rollback_failed lock retained.`,
          error,
          rollbackError
        );
      };

      if (spawned && child) {
        let terminated = false;
        try {
          terminated = await terminateAndReap(
            child,
            child.pid,
            kill,
            dependencies.terminationGraceMs ?? TERMINATION_GRACE_MS
          );
        } catch (rollbackError) {
          return await retainFailedLock(
            `rollback could not confirm child termination (${errorMessage(rollbackError)})`,
            rollbackError
          );
        }
        if (!terminated) {
          return await retainFailedLock(
            "rollback timed out before child termination was confirmed"
          );
        }
      }
      try {
        await removeMatchingLock(lockPath, lock.launchId);
      } catch (rollbackError) {
        throw new MonitoringLaunchRollbackError(
          `Monitoring launch failed (${errorMessage(error)}); lock cleanup failed (${errorMessage(rollbackError)}); launch lock retained.`,
          error,
          rollbackError
        );
      }
      throw error;
    } finally {
      if (log) {
        try {
          await log.close();
        } catch (closeError) {
          try {
            reportLogCloseError(closeError);
          } catch {
            // Diagnostics must never replace the launch outcome.
          }
        }
      }
    }
  };
}

export const startMonitoringRun = createMonitoringLauncher({
  spawn: (file, args, options) => nodeSpawn(file, args, options) as LaunchChild,
});
