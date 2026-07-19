import { EventEmitter } from "node:events";
import { promises as fs, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MONITORING_LAUNCH_LOCK_FILE,
  createMonitoringLauncher,
  getActiveMonitoringLaunch,
  projectMonitoringRun,
  type LaunchChild,
  type MonitoringLaunchDependencies,
} from "@/lib/server/monitoring-launch";
import {
  RunNotFoundError,
  RunPathValidationError,
  resolveRunDirectory,
} from "@/lib/server/run-paths";
import type { MonitoringStartRequest } from "@/types/evaluation";

const tempRoots: string[] = [];

async function makeRepo(runId = "run-1"): Promise<{ repoRoot: string; runDir: string }> {
  const repoRoot = await fs.mkdtemp(path.join(os.tmpdir(), "monitoring-launch-"));
  tempRoots.push(repoRoot);
  const runDir = path.join(repoRoot, "outputs", "runs", runId);
  await fs.mkdir(runDir, { recursive: true });
  return { repoRoot, runDir };
}

afterEach(async () => {
  await Promise.all(tempRoots.splice(0).map((root) => fs.rm(root, { recursive: true, force: true })));
});

class FakeChild extends EventEmitter implements LaunchChild {
  pid: number | undefined;
  unref = vi.fn();
  kill = vi.fn<LaunchChild["kill"]>(() => true);

  constructor(pid = 4321) {
    super();
    this.pid = pid;
  }
}

function spawnSuccessfully(child: FakeChild): MonitoringLaunchDependencies["spawn"] {
  return () => {
    queueMicrotask(() => child.emit("spawn"));
    return child;
  };
}

function request(overrides: Partial<MonitoringStartRequest> = {}): MonitoringStartRequest {
  return {
    runId: "run-1",
    action: "start",
    samplingStrategy: "all",
    sampleSize: 1000,
    intervalMinutes: 60,
    maxWindows: null,
    ...overrides,
  };
}

describe("resolveRunDirectory", () => {
  it("trims and resolves one safe run segment below outputs/runs", async () => {
    const { repoRoot, runDir } = await makeRepo();
    await expect(resolveRunDirectory("  run-1  ", repoRoot)).resolves.toBe(runDir);
  });

  it.each(["", " ", ".", "..", "../run-1", "nested/run", "nested\\run", "run\0id"])(
    "rejects unsafe run id %j",
    async (runId) => {
      const { repoRoot } = await makeRepo();
      await expect(resolveRunDirectory(runId, repoRoot)).rejects.toBeInstanceOf(
        RunPathValidationError
      );
    }
  );

  it("distinguishes a missing but syntactically valid run", async () => {
    const { repoRoot } = await makeRepo();
    await expect(resolveRunDirectory("missing-run", repoRoot)).rejects.toBeInstanceOf(
      RunNotFoundError
    );
  });

  it("rejects a run symlink that resolves outside outputs/runs", async () => {
    const { repoRoot } = await makeRepo();
    const outside = await fs.mkdtemp(path.join(os.tmpdir(), "monitoring-outside-"));
    tempRoots.push(outside);
    await fs.symlink(outside, path.join(repoRoot, "outputs", "runs", "escaped-run"));

    await expect(resolveRunDirectory("escaped-run", repoRoot)).rejects.toBeInstanceOf(
      RunPathValidationError
    );
  });
});

describe("monitoring launch transaction", () => {
  it("uses buildMonitoringArgs at the production boundary for reevaluate", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));
    const launcher = createMonitoringLauncher({ repoRoot, spawn });

    const result = await launcher(
      request({
        action: "reevaluate",
        samplingStrategy: "systematic",
        sampleSize: 37,
        intervalMinutes: 15,
        maxWindows: 4,
      })
    );

    expect(spawn).toHaveBeenCalledWith(
      "uv",
      [
        "run", "ase", "monitor", "run",
        "--run-folder", path.relative(repoRoot, runDir),
        "--sampling-strategy", "systematic",
        "--sample-size", "37",
        "--interval-minutes", "15",
        "--max-windows", "4",
        "--incomplete-run-action", "resume",
        "--rescan",
      ],
      expect.objectContaining({ cwd: repoRoot, detached: true, shell: false })
    );
    expect(result.command).not.toContain("--dry-run");
  });

  it.each([
    {
      action: "start" as const,
      samplingStrategy: "all" as const,
      expectedTail: ["--sampling-strategy", "all", "--interval-minutes", "60", "--incomplete-run-action", "restart"],
    },
    {
      action: "continue" as const,
      samplingStrategy: "random" as const,
      expectedTail: ["--sampling-strategy", "random", "--sample-size", "23", "--interval-minutes", "60", "--incomplete-run-action", "resume"],
    },
  ])("honors $action arguments without dry-run", async ({ action, samplingStrategy, expectedTail }) => {
    const { repoRoot } = await makeRepo();
    const child = new FakeChild();
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));
    const launcher = createMonitoringLauncher({ repoRoot, spawn });

    await launcher(request({ action, samplingStrategy, sampleSize: 23 }));

    const args = spawn.mock.calls[0][1];
    expect(args.slice(-expectedTail.length)).toEqual(expectedTail);
    expect(args).not.toContain("--dry-run");
  });

  it("writes the boundary before spawn and sends stdout and stderr to one append fd", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    let logAtSpawn = "";
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>((_file, _args, options) => {
      logAtSpawn = readFileSync(path.join(runDir, "monitoring.log"), "utf8");
      expect(options.stdio[0]).toBe("ignore");
      expect(options.stdio[1]).toBe(options.stdio[2]);
      queueMicrotask(() => child.emit("spawn"));
      return child;
    });

    await createMonitoringLauncher({
      repoRoot,
      spawn,
      now: () => new Date("2026-07-19T12:00:00.000Z"),
      launchId: () => "launch-boundary",
    })(request({ action: "continue", samplingStrategy: "random", sampleSize: 11 }));

    expect(logAtSpawn).toContain("2026-07-19T12:00:00.000Z");
    expect(logAtSpawn).toContain("action=continue");
    expect(logAtSpawn).toContain("--sample-size 11");
  });

  it("persists the PID before unref and promotes the exclusive queued lock", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    child.unref.mockImplementation(() => {
      const lock = readFileSync(
        path.join(runDir, MONITORING_LAUNCH_LOCK_FILE),
        "utf8"
      );
      expect(JSON.parse(lock).pid).toBe(4321);
    });

    await createMonitoringLauncher({ repoRoot, spawn: spawnSuccessfully(child) })(request());

    expect(child.unref).toHaveBeenCalledOnce();
  });

  it("acquires the initial lock exclusively and prevents a second spawn", async () => {
    const { repoRoot } = await makeRepo();
    const firstChild = new FakeChild(4321);
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(() => firstChild);
    const launcher = createMonitoringLauncher({ repoRoot, spawn });

    const first = launcher(request());
    await vi.waitFor(() => expect(spawn).toHaveBeenCalledOnce());
    const duplicate = await launcher(request({ action: "continue" }));
    expect(duplicate).toMatchObject({ started: false, monitoringStatus: "queued" });
    expect(spawn).toHaveBeenCalledOnce();

    firstChild.emit("spawn");
    await first;
  });

  it.each(["unsafe/segment", "missing-run"])(
    "validates existence before lock, log, or spawn for %s",
    async (runId) => {
      const { repoRoot } = await makeRepo();
      const openLog = vi.fn<NonNullable<MonitoringLaunchDependencies["openLog"]>>();
      const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>();
      const launcher = createMonitoringLauncher({ repoRoot, openLog, spawn });

      await expect(launcher(request({ runId }))).rejects.toBeInstanceOf(
        runId.includes("/") ? RunPathValidationError : RunNotFoundError
      );
      expect(openLog).not.toHaveBeenCalled();
      expect(spawn).not.toHaveBeenCalled();
      await expect(fs.access(path.join(repoRoot, "outputs", "runs", runId, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
    }
  );

  it("removes its lock when opening the log fails", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>();
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn,
      openLog: async () => { throw new Error("log open failed"); },
      launchId: () => "log-failure",
    });

    await expect(launcher(request())).rejects.toThrow("log open failed");
    expect(spawn).not.toHaveBeenCalled();
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
  });

  it("closes the log and removes its lock when writing the launch boundary fails", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const close = vi.fn(async () => undefined);
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>();
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn,
      openLog: async () => ({
        fd: 99,
        appendFile: async () => { throw new Error("boundary write failed"); },
        close,
      }),
      launchId: () => "boundary-failure",
    });

    await expect(launcher(request())).rejects.toThrow("boundary write failed");
    expect(spawn).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
  });

  it("closes the log and removes its lock when spawn emits an error", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const close = vi.fn(async () => undefined);
    const child = new FakeChild(undefined);
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn: () => {
        queueMicrotask(() => child.emit("error", new Error("spawn failed")));
        return child;
      },
      openLog: async () => ({ fd: 99, appendFile: async () => undefined, close }),
      launchId: () => "spawn-failure",
    });

    await expect(launcher(request())).rejects.toThrow("spawn failed");
    expect(close).toHaveBeenCalledOnce();
    expect(child.unref).not.toHaveBeenCalled();
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
  });

  it("terminates and reaps a spawned process before removing the lock when PID promotion fails", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const events: string[] = [];
    const child = new FakeChild();
    const close = vi.fn(async () => { events.push("fd-close"); });
    const removeMatchingLock = vi.fn(async (lockPath: string, launchId: string) => {
      events.push("lock-remove");
      const lock = JSON.parse(await fs.readFile(lockPath, "utf8"));
      if (lock.launchId === launchId) await fs.unlink(lockPath);
    });
    const kill = vi.fn((_pid: number, signal?: NodeJS.Signals | 0) => {
      events.push(`kill-${signal}`);
      if (signal === "SIGTERM") queueMicrotask(() => { events.push("child-close"); child.emit("close", 143); });
      return true;
    });
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      openLog: async () => ({ fd: 99, appendFile: async () => undefined, close }),
      promoteLock: async () => { throw new Error("promotion failed"); },
      removeMatchingLock,
      kill,
      launchId: () => "promotion-failure",
    });

    await expect(launcher(request())).rejects.toThrow("promotion failed");
    expect(kill).toHaveBeenCalledWith(-4321, "SIGTERM");
    expect(events.indexOf("child-close")).toBeLessThan(events.indexOf("lock-remove"));
    expect(child.unref).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
  });

  it("escalates from SIGTERM to SIGKILL and confirms close before removing the lock", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const events: string[] = [];
    const child = new FakeChild();
    const removeMatchingLock = vi.fn(async (lockPath: string, launchId: string) => {
      events.push("lock-remove");
      const lock = JSON.parse(await fs.readFile(lockPath, "utf8"));
      if (lock.launchId === launchId) await fs.unlink(lockPath);
    });
    const kill = vi.fn((_pid: number, signal?: NodeJS.Signals | 0) => {
      events.push(`kill-${signal}`);
      if (signal === "SIGKILL") {
        queueMicrotask(() => {
          events.push("child-close");
          child.emit("close", null, "SIGKILL");
        });
      }
      return true;
    });

    await expect(createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      promoteLock: async () => { throw new Error("promotion failed"); },
      removeMatchingLock,
      kill,
      terminationGraceMs: 1,
    })(request())).rejects.toThrow("promotion failed");

    expect(kill.mock.calls).toEqual([[-4321, "SIGTERM"], [-4321, "SIGKILL"]]);
    expect(events.indexOf("child-close")).toBeLessThan(events.indexOf("lock-remove"));
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
  });

  it("retains the lock and surfaces rollback failure when group signaling throws", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    const close = vi.fn(async () => undefined);
    const removeMatchingLock = vi.fn<NonNullable<MonitoringLaunchDependencies["removeMatchingLock"]>>();
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      openLog: async () => ({ fd: 99, appendFile: async () => undefined, close }),
      promoteLock: async () => { throw new Error("promotion failed"); },
      removeMatchingLock,
      kill: () => { throw Object.assign(new Error("signal denied"), { code: "EACCES" }); },
      terminationGraceMs: 1,
    });

    await expect(launcher(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
      message: expect.stringContaining("lock retained"),
    });
    expect(removeMatchingLock).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).resolves.toBeUndefined();
  });

  it("bounds the SIGKILL wait and retains the lock when the child never closes", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    const close = vi.fn(async () => undefined);
    const kill = vi.fn(() => true);
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      openLog: async () => ({ fd: 99, appendFile: async () => undefined, close }),
      promoteLock: async () => { throw new Error("promotion failed"); },
      kill,
      terminationGraceMs: 1,
    });

    await expect(launcher(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
      message: expect.stringContaining("lock retained"),
    });
    expect(kill.mock.calls).toEqual([[-4321, "SIGTERM"], [-4321, "SIGKILL"]]);
    expect(close).toHaveBeenCalledOnce();
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).resolves.toBeUndefined();
  });

  it("uses the child handle for a spawned child without a PID and removes the lock after close", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const events: string[] = [];
    const child = new FakeChild();
    child.pid = undefined;
    child.kill.mockImplementation((signal) => {
      events.push(`child-kill-${signal}`);
      queueMicrotask(() => {
        events.push("child-close");
        child.emit("close", null, signal);
      });
      return true;
    });
    const removeMatchingLock = vi.fn(async (lockPath: string, launchId: string) => {
      events.push("lock-remove");
      const lock = JSON.parse(await fs.readFile(lockPath, "utf8"));
      if (lock.launchId === launchId) await fs.unlink(lockPath);
    });
    const groupKill = vi.fn(() => true);

    await expect(createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      removeMatchingLock,
      kill: groupKill,
      terminationGraceMs: 1,
    })(request())).rejects.toThrow("spawned without a PID");

    expect(child.kill).toHaveBeenCalledWith("SIGTERM");
    expect(groupKill).not.toHaveBeenCalled();
    expect(events.indexOf("child-close")).toBeLessThan(events.indexOf("lock-remove"));
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
  });

  it("retains the lock when a no-PID child does not close after handle termination", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    child.pid = undefined;
    const close = vi.fn(async () => undefined);
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      openLog: async () => ({ fd: 99, appendFile: async () => undefined, close }),
      kill: vi.fn(() => true),
      terminationGraceMs: 1,
    });

    await expect(launcher(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
      message: expect.stringContaining("lock retained"),
    });
    expect(child.kill.mock.calls).toEqual([["SIGTERM"], ["SIGKILL"]]);
    expect(close).toHaveBeenCalledOnce();
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).resolves.toBeUndefined();
  });

  it("surfaces matching-lock cleanup failure and still closes the descriptor", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const close = vi.fn(async () => undefined);
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn: vi.fn<MonitoringLaunchDependencies["spawn"]>(),
      openLog: async () => ({
        fd: 99,
        appendFile: async () => { throw new Error("boundary write failed"); },
        close,
      }),
      removeMatchingLock: async () => { throw new Error("lock cleanup failed"); },
    });

    await expect(launcher(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
      message: expect.stringContaining("lock cleanup failed"),
    });
    expect(close).toHaveBeenCalledOnce();
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).resolves.toBeUndefined();
  });
});

describe("launch liveness", () => {
  async function writeLock(runDir: string, lock: Record<string, unknown>) {
    await fs.writeFile(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE), JSON.stringify(lock));
  }

  it("keeps live PID locks active regardless of queued expiry", async () => {
    const { runDir } = await makeRepo();
    await writeLock(runDir, { launchId: "live", action: "start", createdAt: "2026-01-01T00:00:00Z", expiresAt: 1, pid: 7 });
    const kill = vi.fn(() => true);
    await expect(getActiveMonitoringLaunch(runDir, { kill, now: () => new Date("2026-07-19") })).resolves.toMatchObject({ pid: 7 });
    expect(kill).toHaveBeenCalledWith(7, 0);
  });

  it("treats EPERM as alive", async () => {
    const { runDir } = await makeRepo();
    await writeLock(runDir, { launchId: "eperm", action: "start", createdAt: "2026-01-01T00:00:00Z", pid: 8 });
    const kill = () => { throw Object.assign(new Error("denied"), { code: "EPERM" }); };
    await expect(getActiveMonitoringLaunch(runDir, { kill })).resolves.toMatchObject({ pid: 8 });
  });

  it("removes an ESRCH/dead PID lock", async () => {
    const { runDir } = await makeRepo();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    await writeLock(runDir, { launchId: "dead", action: "start", createdAt: "2026-01-01T00:00:00Z", pid: 9 });
    const kill = () => { throw Object.assign(new Error("gone"), { code: "ESRCH" }); };
    await expect(getActiveMonitoringLaunch(runDir, { kill })).resolves.toBeNull();
    await expect(fs.access(lockPath)).rejects.toBeTruthy();
  });

  it("keeps queued legacy locks only until their short TTL", async () => {
    const { runDir } = await makeRepo();
    await writeLock(runDir, { launchId: "queued", action: "start", createdAt: "2026-07-19T11:59:59Z", expiresAt: Date.parse("2026-07-19T12:00:10Z") });
    await expect(getActiveMonitoringLaunch(runDir, { now: () => new Date("2026-07-19T12:00:00Z") })).resolves.toMatchObject({ launchId: "queued" });
    await expect(getActiveMonitoringLaunch(runDir, { now: () => new Date("2026-07-19T12:00:11Z") })).resolves.toBeNull();
  });
});

describe("monitoring status projection", () => {
  const active = { launchId: "new", action: "reevaluate" as const, createdAt: "2026-07-19T12:00:00Z", expiresAt: 0, pid: 12 };

  it.each([
    { state: null, launch: null, monitoringStatus: "not_started", canStart: true, canContinue: false, canReevaluate: false },
    { state: null, launch: active, monitoringStatus: "queued", canStart: false, canContinue: false, canReevaluate: false },
    { state: { status: "in_progress", updated_at: "2026-07-19T12:00:01Z" }, launch: active, monitoringStatus: "in_progress", canStart: false, canContinue: false, canReevaluate: false },
    { state: { status: "in_progress" }, launch: null, monitoringStatus: "incomplete", canStart: false, canContinue: true, canReevaluate: false },
    { state: { status: "completed" }, launch: null, monitoringStatus: "completed", canStart: false, canContinue: false, canReevaluate: true },
    { state: { status: "completed", updated_at: "2026-07-19T11:00:00Z" }, launch: active, monitoringStatus: "queued", canStart: false, canContinue: false, canReevaluate: false },
    { state: { status: "partial", current_window: 2, max_windows: 2 }, launch: null, monitoringStatus: "incomplete", canStart: false, canContinue: true, canReevaluate: false },
  ])("projects $monitoringStatus with the correct actions", ({ state, launch, ...expected }) => {
    expect(projectMonitoringRun(state, launch)).toEqual(expected);
  });
});
