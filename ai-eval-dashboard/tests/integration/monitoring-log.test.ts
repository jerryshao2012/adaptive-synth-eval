import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { handleMonitoringLogGet } from "@/app/api/evaluations/monitoring/log/route";
import {
  MONITORING_LOG_FILE,
  MONITORING_LOG_TAIL_MAX_BYTES,
  readMonitoringLogTail,
} from "@/lib/server/monitoring-launch";
import { createGetRequest } from "./test-utils";

const temporaryDirectories: string[] = [];

async function createRepository(runId = "run-1"): Promise<{
  repoRoot: string;
  runDirectory: string;
}> {
  const repoRoot = await fs.mkdtemp(path.join(os.tmpdir(), "monitoring-log-"));
  temporaryDirectories.push(repoRoot);
  const runDirectory = path.join(repoRoot, "outputs", "runs", runId);
  await fs.mkdir(runDirectory, { recursive: true });
  return { repoRoot, runDirectory };
}

function logRequest(runId?: string) {
  return createGetRequest("http://localhost/api/evaluations/monitoring/log", {
    runId,
  });
}

afterEach(async () => {
  vi.restoreAllMocks();
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      fs.rm(directory, { recursive: true, force: true })
    )
  );
});

describe("readMonitoringLogTail", () => {
  it("returns an empty successful response when the run has no monitoring log", async () => {
    const { repoRoot } = await createRepository();

    await expect(readMonitoringLogTail("run-1", repoRoot)).resolves.toEqual({
      runId: "run-1",
      content: "",
      size: 0,
      truncated: false,
    });
  });

  it("returns a small log exactly", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    const content = "launch boundary\nfirst line\nsecond line 😀\n";
    await fs.writeFile(path.join(runDirectory, MONITORING_LOG_FILE), content);

    const result = await readMonitoringLogTail("run-1", repoRoot);

    expect(result).toMatchObject({
      runId: "run-1",
      content,
      size: Buffer.byteLength(content),
      truncated: false,
      updatedAt: expect.any(String),
    });
    expect(Number.isNaN(Date.parse(result.updatedAt ?? ""))).toBe(false);
  });

  it("returns all content when the log is exactly the byte limit", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    const content = Buffer.alloc(MONITORING_LOG_TAIL_MAX_BYTES, "x");
    await fs.writeFile(path.join(runDirectory, MONITORING_LOG_FILE), content);

    const result = await readMonitoringLogTail("run-1", repoRoot);

    expect(result.truncated).toBe(false);
    expect(result.size).toBe(MONITORING_LOG_TAIL_MAX_BYTES);
    expect(Buffer.byteLength(result.content, "utf8")).toBe(
      MONITORING_LOG_TAIL_MAX_BYTES
    );
  });

  it("drops the partial first line from an oversized tail", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    const discardedLine = Buffer.from("0123456789partial-line-fragment\n");
    const completeSuffix = Buffer.from("complete-line\nremaining output\n");
    const cutoff = 5;
    const padding = Buffer.alloc(
      MONITORING_LOG_TAIL_MAX_BYTES + cutoff - discardedLine.length - completeSuffix.length,
      "z"
    );
    const fullLog = Buffer.concat([discardedLine, completeSuffix, padding]);
    expect(fullLog.length - MONITORING_LOG_TAIL_MAX_BYTES).toBe(cutoff);
    await fs.writeFile(path.join(runDirectory, MONITORING_LOG_FILE), fullLog);

    const result = await readMonitoringLogTail("run-1", repoRoot);

    expect(result).toMatchObject({
      runId: "run-1",
      size: fullLog.length,
      truncated: true,
      updatedAt: expect.any(String),
    });
    expect(Buffer.byteLength(result.content, "utf8")).toBeLessThanOrEqual(
      MONITORING_LOG_TAIL_MAX_BYTES
    );
    expect(result.content.startsWith("complete-line\n")).toBe(true);
    expect(result.content).not.toContain("partial-line-fragment");
  });

  it("decodes multibyte UTF-8 only after the discarded newline", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    const expectedStart = "complete-line 😀 café 漢字\n";
    const discardedLine = Buffer.from("😀fragment-before-newline\n");
    const expected = Buffer.from(expectedStart);
    const cutoff = 2;
    const padding = Buffer.alloc(
      MONITORING_LOG_TAIL_MAX_BYTES + cutoff - discardedLine.length - expected.length,
      "q"
    );
    const fullLog = Buffer.concat([discardedLine, expected, padding]);
    expect(fullLog.length - MONITORING_LOG_TAIL_MAX_BYTES).toBe(cutoff);
    expect(discardedLine.subarray(cutoff, cutoff + 1)[0] & 0xc0).toBe(0x80);
    await fs.writeFile(path.join(runDirectory, MONITORING_LOG_FILE), fullLog);

    const result = await readMonitoringLogTail("run-1", repoRoot);

    expect(result.truncated).toBe(true);
    expect(result.content.startsWith(expectedStart)).toBe(true);
    expect(result.content).not.toContain("�");
  });

  it("returns empty content when an oversized tail has no complete line", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    const fullLog = Buffer.alloc(MONITORING_LOG_TAIL_MAX_BYTES + 17, "x");
    await fs.writeFile(path.join(runDirectory, MONITORING_LOG_FILE), fullLog);

    const result = await readMonitoringLogTail("run-1", repoRoot);

    expect(result).toMatchObject({
      size: fullLog.length,
      truncated: true,
      content: "",
    });
  });

  it("rejects a monitoring log symlink without reading its outside target", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    const outside = await fs.mkdtemp(path.join(os.tmpdir(), "monitoring-log-outside-"));
    temporaryDirectories.push(outside);
    const secret = "outside secret must not be exposed";
    const outsideLog = path.join(outside, "outside.log");
    await fs.writeFile(outsideLog, secret);
    await fs.symlink(outsideLog, path.join(runDirectory, MONITORING_LOG_FILE));

    const response = await handleMonitoringLogGet(
      logRequest("run-1"),
      (runId) => readMonitoringLogTail(runId, repoRoot)
    );
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body).toEqual({
      error: "monitoring.log must be a regular file inside the selected run.",
    });
    expect(JSON.stringify(body)).not.toContain(secret);
  });

  it("rejects a non-regular monitoring log", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    await fs.mkdir(path.join(runDirectory, MONITORING_LOG_FILE));

    const response = await handleMonitoringLogGet(
      logRequest("run-1"),
      (runId) => readMonitoringLogTail(runId, repoRoot)
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      error: "monitoring.log must be a regular file inside the selected run.",
    });
  });

  it("rejects an intermediate run-directory swap before exposing log content", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    const runsDirectory = path.dirname(runDirectory);
    const parkedRunDirectory = path.join(runsDirectory, "parked-run-1");
    const outside = await fs.mkdtemp(path.join(os.tmpdir(), "monitoring-log-swap-"));
    temporaryDirectories.push(outside);
    const secret = "outside swap secret must not be exposed";
    await fs.writeFile(path.join(runDirectory, MONITORING_LOG_FILE), "safe\n");
    await fs.writeFile(path.join(outside, MONITORING_LOG_FILE), secret);
    const canonicalLogPath = path.join(
      await fs.realpath(runDirectory),
      MONITORING_LOG_FILE
    );

    const originalOpen = fs.open.bind(fs);
    let swapped = false;
    vi.spyOn(fs, "open").mockImplementation(async (target, flags, mode) => {
      if (!swapped && path.resolve(String(target)) === canonicalLogPath) {
        swapped = true;
        await fs.rename(runDirectory, parkedRunDirectory);
        await fs.symlink(outside, runDirectory);
      }
      return originalOpen(target, flags, mode);
    });

    const response = await handleMonitoringLogGet(
      logRequest("run-1"),
      (runId) => readMonitoringLogTail(runId, repoRoot)
    );
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(JSON.stringify(body)).not.toContain(secret);
  });
});

describe("handleMonitoringLogGet", () => {
  it("returns 400 for an unsafe run ID", async () => {
    const { repoRoot } = await createRepository();

    const response = await handleMonitoringLogGet(
      logRequest("../escape"),
      (runId) => readMonitoringLogTail(runId, repoRoot)
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      error: "runId must be one safe path segment.",
    });
  });

  it("returns 404 for a syntactically valid missing run", async () => {
    const { repoRoot } = await createRepository();

    const response = await handleMonitoringLogGet(
      logRequest("missing-run"),
      (runId) => readMonitoringLogTail(runId, repoRoot)
    );

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({
      error: "Run 'missing-run' was not found.",
    });
  });

  it("returns 400 when runId is omitted", async () => {
    const response = await handleMonitoringLogGet(logRequest(), async () => {
      throw new Error("reader should not be called");
    });

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      error: "runId query parameter is required.",
    });
  });

  it("returns the bounded log response as JSON", async () => {
    const { repoRoot, runDirectory } = await createRepository();
    await fs.writeFile(path.join(runDirectory, MONITORING_LOG_FILE), "ready\n");

    const response = await handleMonitoringLogGet(
      logRequest("run-1"),
      (runId) => readMonitoringLogTail(runId, repoRoot)
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      runId: "run-1",
      content: "ready\n",
      size: 6,
      truncated: false,
      updatedAt: expect.any(String),
    });
  });
});
