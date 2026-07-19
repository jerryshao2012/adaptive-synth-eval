import { EventEmitter } from "node:events";
import { execFileSync } from "node:child_process";
import { constants as fsConstants, promises as fs, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MONITORING_LAUNCH_LOCK_FILE,
  createMonitoringLauncher,
  getActiveMonitoringLaunch,
  projectMonitoringRun,
  removeMatchingMonitoringLock,
  type LaunchChild,
  type MonitoringLaunchDependencies,
} from "@/lib/server/monitoring-launch";
import {
  RunNotFoundError,
  RunPathValidationError,
  resolveRunDirectory,
} from "@/lib/server/run-paths";
import { getMonitoringStatus } from "@/lib/server/monitoring";
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
    await expect(resolveRunDirectory("  run-1  ", repoRoot)).resolves.toBe(
      await fs.realpath(runDir)
    );
  });

  it.each([
    "",
    " ",
    ".",
    "..",
    "../run-1",
    "nested/run",
    "nested\\run",
    "run\0id",
    "run\nid",
    "run\rid",
    "run\u001bid",
    "run\u007fid",
    "run\u0085id",
    "\nrun-1",
    "run-1\r",
    "\u001brun-1",
  ])(
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

  it("returns the stable canonical target for a run symlink inside outputs/runs", async () => {
    const { repoRoot, runDir } = await makeRepo();
    await fs.symlink(runDir, path.join(repoRoot, "outputs", "runs", "run-alias"));

    await expect(resolveRunDirectory("run-alias", repoRoot)).resolves.toBe(
      await fs.realpath(runDir)
    );
  });

  it("rejects status traversal before reading or reconciling an outside lock", async () => {
    const { repoRoot } = await makeRepo();
    const outsideDirectory = path.join(repoRoot, "outside");
    await fs.mkdir(outsideDirectory);
    await fs.writeFile(
      path.join(outsideDirectory, "monitoring_state.json"),
      JSON.stringify({ status: "completed" })
    );
    const outsideLockPath = path.join(
      outsideDirectory,
      MONITORING_LAUNCH_LOCK_FILE
    );
    const outsideLock = JSON.stringify({
      launchId: "outside-lock",
      action: "start",
      phase: "queued",
      createdAt: "2026-07-19T00:00:00.000Z",
      expiresAt: 0,
    });
    await fs.writeFile(outsideLockPath, outsideLock);

    await expect(
      getMonitoringStatus("../../outside", repoRoot)
    ).rejects.toBeInstanceOf(RunPathValidationError);
    await expect(fs.readFile(outsideLockPath, "utf8")).resolves.toBe(
      outsideLock
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
    await fs.writeFile(path.join(runDir, "monitoring.log"), "existing output\n");
    const child = new FakeChild();
    let logAtSpawn = "";
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>((_file, _args, options) => {
      logAtSpawn = readFileSync(path.join(runDir, "monitoring.log"), "utf8");
      const queuedLock = JSON.parse(
        readFileSync(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE), "utf8")
      );
      expect(queuedLock.phase).toBe("queued");
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
    expect(logAtSpawn.startsWith("existing output\n")).toBe(true);
    expect(logAtSpawn).toContain("action=continue");
    expect(logAtSpawn).toContain("--sample-size 11");
  });

  it("rejects a monitoring log symlink without changing its outside target or spawning", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const outsideDirectory = await fs.mkdtemp(
      path.join(os.tmpdir(), "monitoring-launch-outside-")
    );
    tempRoots.push(outsideDirectory);
    const outsideLog = path.join(outsideDirectory, "outside.log");
    const originalOutsideContent = "outside content must remain unchanged\n";
    await fs.writeFile(outsideLog, originalOutsideContent);
    await fs.symlink(outsideLog, path.join(runDir, "monitoring.log"));
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>();

    await expect(
      createMonitoringLauncher({ repoRoot, spawn })(request())
    ).rejects.toBeInstanceOf(RunPathValidationError);
    await expect(fs.readFile(outsideLog, "utf8")).resolves.toBe(
      originalOutsideContent
    );
    expect(spawn).not.toHaveBeenCalled();
  });

  it("rejects a monitoring log FIFO promptly without spawning", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const fifoPath = path.join(runDir, "monitoring.log");
    execFileSync("mkfifo", [fifoPath]);
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>();
    const launchPromise = createMonitoringLauncher({ repoRoot, spawn })(request());
    const timeout = Symbol("timeout");
    const outcome = await Promise.race([
      launchPromise.then(
        () => null,
        (error: unknown) => error
      ),
      new Promise<typeof timeout>((resolve) =>
        setTimeout(() => resolve(timeout), 100)
      ),
    ]);

    if (outcome === timeout) {
      const reader = await fs.open(
        fifoPath,
        fsConstants.O_RDONLY | fsConstants.O_NONBLOCK
      );
      try {
        await launchPromise.catch(() => undefined);
      } finally {
        await reader.close();
      }
    }

    expect(outcome).not.toBe(timeout);
    expect(outcome).toBeInstanceOf(RunPathValidationError);
    expect(spawn).not.toHaveBeenCalled();
  });

  it("persists the PID before unref and promotes the exclusive queued lock", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    child.unref.mockImplementation(() => {
      const lock = readFileSync(
        path.join(runDir, MONITORING_LAUNCH_LOCK_FILE),
        "utf8"
      );
      expect(JSON.parse(lock)).toMatchObject({ phase: "running", pid: 4321 });
    });

    await createMonitoringLauncher({ repoRoot, spawn: spawnSuccessfully(child) })(request());

    expect(child.unref).toHaveBeenCalledOnce();
  });

  it("preserves a successful launch when closing the parent log descriptor fails", async () => {
    const { repoRoot } = await makeRepo();
    const child = new FakeChild();
    const reportLogCloseError = vi.fn();
    const dependencies = {
      repoRoot,
      spawn: spawnSuccessfully(child),
      openLog: async () => ({
        fd: 99,
        appendFile: async () => undefined,
        close: async () => { throw new Error("close failed"); },
      }),
      reportLogCloseError,
    } as MonitoringLaunchDependencies & {
      reportLogCloseError: (error: unknown) => void;
    };

    await expect(createMonitoringLauncher(dependencies)(request())).resolves.toMatchObject({
      started: true,
      monitoringStatus: "queued",
    });
    expect(reportLogCloseError).toHaveBeenCalledWith(expect.objectContaining({
      message: "close failed",
    }));
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

  it("treats the exact active legacy lock shape as queued through its TTL", async () => {
    const { repoRoot, runDir } = await makeRepo();
    await fs.writeFile(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE), JSON.stringify({
      runId: "run-1",
      action: "start",
      createdAt: "2026-07-19T12:00:00Z",
      expiresAt: Date.parse("2026-07-19T12:00:30Z"),
    }));
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>();

    await expect(createMonitoringLauncher({
      repoRoot,
      spawn,
      now: () => new Date("2026-07-19T12:00:10Z"),
    })(request())).resolves.toMatchObject({
      started: false,
      monitoringStatus: "queued",
    });
    expect(spawn).not.toHaveBeenCalled();
  });

  it("clears an expired exact legacy lock and allows a new launch", async () => {
    const { repoRoot, runDir } = await makeRepo();
    await fs.writeFile(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE), JSON.stringify({
      runId: "run-1",
      action: "continue",
      createdAt: "2026-07-19T12:00:00Z",
      expiresAt: Date.parse("2026-07-19T12:00:30Z"),
    }));
    const child = new FakeChild();
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));

    await expect(createMonitoringLauncher({
      repoRoot,
      spawn,
      now: () => new Date("2026-07-19T12:01:00Z"),
    })(request())).resolves.toMatchObject({ started: true });
    expect(spawn).toHaveBeenCalledOnce();
  });

  it("preserves the acquired replacement when expired legacy cleanup races a contender", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    const legacyLock = {
      runId: "run-1",
      action: "start",
      createdAt: "2026-07-19T12:01:00Z",
      expiresAt: Date.parse("2026-07-19T12:00:30Z"),
    };
    await fs.writeFile(lockPath, JSON.stringify(legacyLock));

    let releaseLegacyComparison!: () => void;
    const legacyComparisonReleased = new Promise<void>((resolve) => {
      releaseLegacyComparison = resolve;
    });
    let comparisonRead!: () => void;
    const comparisonReadStarted = new Promise<void>((resolve) => {
      comparisonRead = resolve;
    });
    let reads = 0;
    const firstChild = new FakeChild(4101);
    const secondChild = new FakeChild(4102);
    const kill = vi.fn(() => true);
    let spawnCount = 0;
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(() => {
      spawnCount += 1;
      const child: FakeChild = spawnCount === 1 ? firstChild : secondChild;
      queueMicrotask(() => child.emit("spawn"));
      return child;
    });
    const firstLauncher = createMonitoringLauncher({
      repoRoot,
      spawn,
      launchId: () => "first-owner",
      now: () => new Date("2026-07-19T12:01:00Z"),
      kill,
      readLockFile: async (candidatePath) => {
        const content = await fs.readFile(candidatePath, "utf8");
        reads += 1;
        if (reads === 2) {
          comparisonRead();
          await legacyComparisonReleased;
        }
        return content;
      },
    });
    const secondLauncher = createMonitoringLauncher({
      repoRoot,
      spawn,
      launchId: () => "second-owner",
      now: () => new Date("2026-07-19T12:01:00Z"),
      kill,
    });

    const first = firstLauncher(request());
    await comparisonReadStarted;
    const second = secondLauncher(request({ action: "continue" }));
    await new Promise((resolve) => setTimeout(resolve, 25));
    releaseLegacyComparison();

    const [firstResult, secondResult] = await Promise.all([first, second]);

    expect(firstResult).toMatchObject({ started: true });
    expect(secondResult).toMatchObject({ started: false, monitoringStatus: "queued" });
    expect(spawn).toHaveBeenCalledOnce();
    expect(JSON.parse(await fs.readFile(lockPath, "utf8"))).toMatchObject({
      launchId: "first-owner",
      phase: "running",
      pid: 4101,
    });
  });

  it("reclaims a crashed guard owner without leaving a deadlock", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    const token = "00000000-0000-4000-8000-000000000001";
    const stalePid = 999_999;
    const intentFile = `${path.basename(lockPath)}.guard.${stalePid}.${token}.intent`;
    const intentPath = path.join(runDir, intentFile);
    const guardPath = `${lockPath}.guard`;
    await fs.writeFile(intentPath, JSON.stringify({
      token,
      pid: stalePid,
      createdAt: "2026-07-19T12:00:00Z",
      intentFile,
    }));
    await fs.link(intentPath, guardPath);
    const child = new FakeChild();
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));

    await expect(createMonitoringLauncher({ repoRoot, spawn })(request())).resolves.toMatchObject({
      started: true,
    });

    expect(spawn).toHaveBeenCalledOnce();
    await expect(fs.access(intentPath)).rejects.toBeTruthy();
    await expect(fs.access(guardPath)).rejects.toBeTruthy();
  });

  it("does not let owner-based cleanup target an ownerless legacy lock", async () => {
    const { runDir } = await makeRepo();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    const legacyLock = {
      runId: "run-1",
      action: "start",
      createdAt: "2026-07-19T12:00:00Z",
      expiresAt: Date.parse("2026-07-19T12:00:30Z"),
    };
    await fs.writeFile(lockPath, JSON.stringify(legacyLock));

    await removeMatchingMonitoringLock(lockPath, "");

    expect(JSON.parse(await fs.readFile(lockPath, "utf8"))).toEqual(legacyLock);
  });

  it("rejects a near-legacy ownerless lock with additional fields", async () => {
    const { repoRoot, runDir } = await makeRepo();
    await fs.writeFile(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE), JSON.stringify({
      runId: "run-1",
      action: "start",
      createdAt: "2026-07-19T12:00:00Z",
      expiresAt: Date.parse("2026-07-19T12:00:30Z"),
      unexpected: true,
    }));

    await expect(createMonitoringLauncher({
      repoRoot,
      spawn: vi.fn<MonitoringLaunchDependencies["spawn"]>(),
    })(request())).rejects.toMatchObject({ name: "MonitoringLaunchLockReadError" });
  });

  it("fails closed with an explicit error for a corrupt existing lock", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    await fs.writeFile(lockPath, "{not-json");
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>();

    await expect(createMonitoringLauncher({ repoRoot, spawn })(request())).rejects.toMatchObject({
      name: "MonitoringLaunchLockReadError",
      message: expect.stringContaining("Could not read monitoring launch lock"),
    });
    expect(spawn).not.toHaveBeenCalled();
    await expect(fs.readFile(lockPath, "utf8")).resolves.toBe("{not-json");
  });

  it("fails closed when an injected lock read returns an I/O error", async () => {
    const { repoRoot, runDir } = await makeRepo();
    await fs.writeFile(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE), JSON.stringify({
      launchId: "existing",
      action: "start",
      phase: "queued",
      createdAt: "2026-07-19T12:00:00Z",
      expiresAt: Date.now() + 30_000,
    }));
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>();
    const dependencies = {
      repoRoot,
      spawn,
      readLockFile: async () => {
        throw Object.assign(new Error("read denied"), { code: "EACCES" });
      },
    } as MonitoringLaunchDependencies & {
      readLockFile: (lockPath: string) => Promise<string>;
    };

    await expect(createMonitoringLauncher(dependencies)(request())).rejects.toMatchObject({
      name: "MonitoringLaunchLockReadError",
      message: expect.stringContaining("read denied"),
    });
    expect(spawn).not.toHaveBeenCalled();
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

  it("preserves the primary rollback error when log descriptor close also fails", async () => {
    const { repoRoot } = await makeRepo();
    const child = new FakeChild();
    const reportLogCloseError = vi.fn();
    const kill = vi.fn((_pid: number, signal?: NodeJS.Signals | 0) => {
      if (signal === "SIGTERM") queueMicrotask(() => child.emit("close", 143));
      return true;
    });
    const dependencies = {
      repoRoot,
      spawn: spawnSuccessfully(child),
      openLog: async () => ({
        fd: 99,
        appendFile: async () => undefined,
        close: async () => { throw new Error("close failed"); },
      }),
      promoteLock: async () => { throw new Error("promotion failed"); },
      kill,
      reportLogCloseError,
    } as MonitoringLaunchDependencies & {
      reportLogCloseError: (error: unknown) => void;
    };

    await expect(createMonitoringLauncher(dependencies)(request())).rejects.toThrow(
      "promotion failed"
    );
    expect(reportLogCloseError).toHaveBeenCalledWith(expect.objectContaining({
      message: "close failed",
    }));
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

  it("keeps a PID rollback_failed lock active beyond queued TTL and blocks duplicate spawn", async () => {
    const { repoRoot, runDir } = await makeRepo();
    let currentTime = new Date("2026-07-19T12:00:00Z");
    const child = new FakeChild();
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn,
      now: () => currentTime,
      promoteLock: async () => { throw new Error("promotion failed"); },
      kill: vi.fn(() => true),
      terminationGraceMs: 1,
    });

    await expect(launcher(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
    });
    expect(JSON.parse(await fs.readFile(
      path.join(runDir, MONITORING_LAUNCH_LOCK_FILE),
      "utf8"
    ))).toMatchObject({ phase: "rollback_failed", pid: 4321 });

    currentTime = new Date("2026-07-19T12:01:00Z");
    await expect(launcher(request({ action: "continue" }))).resolves.toMatchObject({
      started: false,
      monitoringStatus: "queued",
    });
    expect(spawn).toHaveBeenCalledOnce();
  });

  it("keeps a no-PID rollback_failed lock active beyond queued TTL and blocks duplicate spawn", async () => {
    const { repoRoot, runDir } = await makeRepo();
    let currentTime = new Date("2026-07-19T12:00:00Z");
    const child = new FakeChild();
    child.pid = undefined;
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn,
      now: () => currentTime,
      kill: vi.fn(() => true),
      terminationGraceMs: 1,
    });

    await expect(launcher(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
    });
    const failedLock = JSON.parse(await fs.readFile(
      path.join(runDir, MONITORING_LAUNCH_LOCK_FILE),
      "utf8"
    ));
    expect(failedLock).toMatchObject({ phase: "rollback_failed" });
    expect(failedLock.pid).toBeUndefined();

    currentTime = new Date("2026-07-19T12:01:00Z");
    await expect(launcher(request({ action: "continue" }))).resolves.toMatchObject({
      started: false,
      monitoringStatus: "queued",
    });
    expect(spawn).toHaveBeenCalledOnce();
  });

  it("removes a matching rollback_failed lock when the child closes late", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    await expect(createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      promoteLock: async () => { throw new Error("promotion failed"); },
      kill: vi.fn(() => true),
      terminationGraceMs: 1,
    })(request())).rejects.toMatchObject({ name: "MonitoringLaunchRollbackError" });

    child.emit("close", null, "SIGKILL");

    await vi.waitFor(async () => {
      await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
    });
  });

  it("does not remove a same-owner replacement lock that is no longer rollback_failed", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    await expect(createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      promoteLock: async () => { throw new Error("promotion failed"); },
      kill: vi.fn(() => true),
      terminationGraceMs: 1,
    })(request())).rejects.toMatchObject({ name: "MonitoringLaunchRollbackError" });
    const failedLock = JSON.parse(await fs.readFile(lockPath, "utf8"));
    await fs.writeFile(lockPath, JSON.stringify({
      launchId: failedLock.launchId,
      action: "start",
      phase: "running",
      createdAt: "2026-07-19T13:00:00Z",
      expiresAt: 0,
      pid: 9999,
    }));

    child.emit("close", null, "SIGKILL");
    await new Promise((resolve) => setTimeout(resolve, 5));

    expect(JSON.parse(await fs.readFile(lockPath, "utf8"))).toMatchObject({
      launchId: failedLock.launchId,
      phase: "running",
    });
  });

  it("waits for child close after ESRCH before removing the lock", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const events: string[] = [];
    const child = new FakeChild();
    const removeMatchingLock = vi.fn(async (lockPath: string, launchId: string) => {
      events.push("lock-remove");
      const lock = JSON.parse(await fs.readFile(lockPath, "utf8"));
      if (lock.launchId === launchId) await fs.unlink(lockPath);
    });
    const kill = vi.fn(() => {
      setTimeout(() => {
        events.push("child-close");
        child.emit("close", null, "SIGTERM");
      }, 1);
      throw Object.assign(new Error("gone"), { code: "ESRCH" });
    });

    await expect(createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      promoteLock: async () => { throw new Error("promotion failed"); },
      removeMatchingLock,
      kill,
      terminationGraceMs: 100,
    })(request())).rejects.toThrow("promotion failed");

    expect(events.indexOf("child-close")).toBeLessThan(events.indexOf("lock-remove"));
    await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
  });

  it("persists rollback_failed when ESRCH is not followed by child close", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const child = new FakeChild();
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      promoteLock: async () => { throw new Error("promotion failed"); },
      kill: () => { throw Object.assign(new Error("gone"), { code: "ESRCH" }); },
      terminationGraceMs: 1,
    });

    await expect(launcher(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
      message: expect.stringContaining("lock retained"),
    });
    expect(JSON.parse(await fs.readFile(
      path.join(runDir, MONITORING_LAUNCH_LOCK_FILE),
      "utf8"
    ))).toMatchObject({ phase: "rollback_failed", pid: 4321 });
  });

  it("keeps persistence failures fail-closed beyond TTL and cleans up on matching late close", async () => {
    const { repoRoot, runDir } = await makeRepo();
    let currentTime = new Date("2026-07-19T12:00:00Z");
    const child = new FakeChild();
    const close = vi.fn(async () => undefined);
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));
    const removeMatchingLock = vi.fn(async (lockPath: string, launchId: string) => {
      const lock = JSON.parse(await fs.readFile(lockPath, "utf8"));
      if (lock.launchId === launchId) await fs.unlink(lockPath);
    });
    const dependencies = {
      repoRoot,
      spawn,
      now: () => currentTime,
      openLog: async () => ({ fd: 99, appendFile: async () => undefined, close }),
      promoteLock: async () => { throw new Error("promotion failed"); },
      persistRollbackFailedLock: async () => { throw new Error("failed-lock write failed"); },
      removeMatchingLock,
      kill: vi.fn(() => true),
      terminationGraceMs: 1,
    } as MonitoringLaunchDependencies & {
      persistRollbackFailedLock: () => Promise<void>;
    };

    await expect(createMonitoringLauncher(dependencies)(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
      message: expect.stringContaining("failed-lock write failed"),
    });
    expect(removeMatchingLock).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
    expect(JSON.parse(await fs.readFile(
      path.join(runDir, MONITORING_LAUNCH_LOCK_FILE),
      "utf8"
    ))).toMatchObject({ phase: "queued" });

    currentTime = new Date("2026-07-19T12:01:00Z");
    await expect(createMonitoringLauncher(dependencies)(
      request({ action: "continue" })
    )).resolves.toMatchObject({ started: false, monitoringStatus: "queued" });
    expect(spawn).toHaveBeenCalledOnce();

    child.emit("close", null, "SIGKILL");
    await vi.waitFor(async () => {
      await expect(fs.access(path.join(runDir, MONITORING_LAUNCH_LOCK_FILE))).rejects.toBeTruthy();
    });
    expect(removeMatchingLock).toHaveBeenCalledOnce();
  });

  it("blocks acquisition when failed-lock persistence removed the owned lock file", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    const child = new FakeChild();
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn,
      promoteLock: async () => { throw new Error("promotion failed"); },
      persistRollbackFailedLock: async () => {
        await fs.unlink(lockPath);
        throw new Error("failed-lock disappeared");
      },
      kill: vi.fn(() => true),
      terminationGraceMs: 1,
    });

    const launchFailure = await launcher(request()).catch((error: unknown) => error);
    expect(launchFailure).toMatchObject({
      name: "MonitoringLaunchRollbackError",
      message: expect.stringContaining("failed-lock disappeared"),
    });
    await expect(fs.access(lockPath)).rejects.toBeTruthy();

    await expect(launcher(request({ action: "continue" }))).resolves.toMatchObject({
      started: false,
      monitoringStatus: "queued",
    });
    expect(spawn).toHaveBeenCalledOnce();

    child.emit("close", null, "SIGKILL");
    await new Promise((resolve) => setTimeout(resolve, 5));
    await expect(fs.access(lockPath)).rejects.toBeTruthy();
  });

  it("blocks acquisition without deleting a replacement lock after persistence ownership changes", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    const child = new FakeChild();
    const spawn = vi.fn<MonitoringLaunchDependencies["spawn"]>(spawnSuccessfully(child));
    const replacement = {
      launchId: "replacement-owner",
      action: "start",
      phase: "queued",
      createdAt: "2026-07-19T11:00:00Z",
      expiresAt: 0,
    };
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn,
      promoteLock: async () => { throw new Error("promotion failed"); },
      persistRollbackFailedLock: async () => {
        await fs.writeFile(lockPath, JSON.stringify(replacement));
        throw new Error("lock ownership changed");
      },
      kill: vi.fn(() => true),
      terminationGraceMs: 1,
    });

    const launchFailure = await launcher(request()).catch((error: unknown) => error);
    expect(launchFailure).toMatchObject({
      name: "MonitoringLaunchRollbackError",
      message: expect.stringContaining("lock ownership changed"),
    });

    await expect(launcher(request({ action: "continue" }))).resolves.toMatchObject({
      started: false,
      monitoringStatus: "queued",
    });
    expect(spawn).toHaveBeenCalledOnce();
    expect(JSON.parse(await fs.readFile(lockPath, "utf8"))).toEqual(replacement);

    child.emit("close", null, "SIGKILL");
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(JSON.parse(await fs.readFile(lockPath, "utf8"))).toEqual(replacement);
  });

  it("retries transient late-close cleanup during a subsequent liveness check", async () => {
    const { repoRoot, runDir } = await makeRepo();
    const lockPath = path.join(runDir, MONITORING_LAUNCH_LOCK_FILE);
    const child = new FakeChild();
    const removeMatchingLock = vi.fn(async (candidatePath: string, launchId: string) => {
      if (removeMatchingLock.mock.calls.length === 1) {
        throw new Error("transient cleanup failure");
      }
      const lock = JSON.parse(await fs.readFile(candidatePath, "utf8"));
      if (lock.launchId === launchId) await fs.unlink(candidatePath);
    });
    const kill = vi.fn(() => true);
    const launcher = createMonitoringLauncher({
      repoRoot,
      spawn: spawnSuccessfully(child),
      promoteLock: async () => { throw new Error("promotion failed"); },
      removeMatchingLock,
      kill,
      terminationGraceMs: 1,
    });
    await expect(launcher(request())).rejects.toMatchObject({
      name: "MonitoringLaunchRollbackError",
    });

    child.emit("close", null, "SIGKILL");
    await vi.waitFor(() => expect(removeMatchingLock).toHaveBeenCalledOnce());
    await expect(fs.access(lockPath)).resolves.toBeUndefined();

    const livenessDependencies = {
      kill,
      removeMatchingLock,
    } as NonNullable<Parameters<typeof getActiveMonitoringLaunch>[1]> & {
      removeMatchingLock: typeof removeMatchingLock;
    };
    await expect(getActiveMonitoringLaunch(
      runDir,
      livenessDependencies
    )).resolves.toBeNull();
    expect(removeMatchingLock).toHaveBeenCalledTimes(2);
    await expect(fs.access(lockPath)).rejects.toBeTruthy();
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
