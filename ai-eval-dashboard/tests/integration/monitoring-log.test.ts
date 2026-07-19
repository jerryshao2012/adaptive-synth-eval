import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";

import { handleMonitoringLogGet } from "@/app/api/evaluations/monitoring/log/route";
import {
  MONITORING_LOG_FILE,
  MONITORING_LOG_TAIL_MAX_BYTES,
  readMonitoringLogTail,
} from "@/lib/server/monitoring-launch";

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

function logRequest(runId?: string): NextRequest {
  const url = new URL("http://localhost/api/evaluations/monitoring/log");
  if (runId !== undefined) {
    url.searchParams.set("runId", runId);
  }
  return new NextRequest(url);
}

afterEach(async () => {
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
    const completeSuffix = Buffer.from("complete-line\nremaining output\n");
    const partialPrefix = Buffer.from("partial-line-fragment\n");
    const padding = Buffer.alloc(
      MONITORING_LOG_TAIL_MAX_BYTES - partialPrefix.length - completeSuffix.length,
      "z"
    );
    const tail = Buffer.concat([partialPrefix, completeSuffix, padding]);
    const fullLog = Buffer.concat([Buffer.from("outside-tail"), tail]);
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
    const prefix = Buffer.from("fragment-that-may-start-mid-character\n");
    const expected = Buffer.from(expectedStart);
    const padding = Buffer.alloc(
      MONITORING_LOG_TAIL_MAX_BYTES - prefix.length - expected.length,
      "q"
    );
    const fullLog = Buffer.concat([
      Buffer.from("😀outside"),
      prefix,
      expected,
      padding,
    ]);
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
