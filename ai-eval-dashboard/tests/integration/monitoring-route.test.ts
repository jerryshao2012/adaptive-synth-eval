import { describe, expect, it, vi } from "vitest";

import {
  GET,
  handleMonitoringPost,
} from "@/app/api/evaluations/monitoring/route";
import {
  RunNotFoundError,
  RunPathValidationError,
} from "@/lib/server/run-paths";
import type {
  MonitoringStartRequest,
  MonitoringStartResponse,
} from "@/types/evaluation";
import {
  createGetRequest,
  createJsonPostRequest,
  createMalformedJsonPostRequest,
} from "./test-utils";

type StartFn = (
  request: MonitoringStartRequest
) => Promise<MonitoringStartResponse>;

function statusRequest(runId?: string) {
  return createGetRequest("http://localhost/api/evaluations/monitoring", {
    runId,
  });
}

describe("GET /api/evaluations/monitoring", () => {
  it.each(["../escape", "run\nid", "run\rid", "run\u001bid", "run\u0085id"])(
    "returns 400 for unsafe run ID %j",
    async (runId) => {
      const response = await GET(statusRequest(runId));

      expect(response.status).toBe(400);
      expect(await response.json()).toEqual({
        error: "runId must be one safe path segment.",
      });
    }
  );

  it("returns 404 for a missing safe run", async () => {
    const response = await GET(statusRequest("missing-safe-run"));

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({
      error: "Run 'missing-safe-run' was not found.",
    });
  });
});

describe("handleMonitoringPost", () => {
  it("passes only a validated and normalized request to the launcher", async () => {
    const startFn = vi.fn<StartFn>().mockResolvedValue({
      runId: "run-1",
      started: true,
      command: "uv run ase monitor run",
      monitoringStatus: "queued",
    });

    const response = await handleMonitoringPost(
      createJsonPostRequest("http://localhost/api/evaluations/monitoring", {
        runId: "run-1",
        action: "reevaluate",
        samplingStrategy: "systematic",
        sampleSize: 100,
        intervalMinutes: 30,
        maxWindows: 2,
      }),
      startFn
    );

    expect(response.status).toBe(202);
    expect(startFn).toHaveBeenCalledOnce();
    expect(startFn).toHaveBeenCalledWith({
      runId: "run-1",
      action: "reevaluate",
      samplingStrategy: "systematic",
      sampleSize: 100,
      intervalMinutes: 30,
      maxWindows: 2,
    });
  });

  it("returns 400 for malformed JSON without invoking the launcher", async () => {
    const startFn = vi.fn<StartFn>();

    const response = await handleMonitoringPost(
      createMalformedJsonPostRequest("http://localhost/api/evaluations/monitoring"),
      startFn
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "Invalid JSON body." });
    expect(startFn).not.toHaveBeenCalled();
  });

  it.each([
    { runId: "../escape", action: "start" },
    { runId: "run-1", action: "start", sampleSize: "100" },
    { runId: "run-1", action: "start", dryRun: true },
    { runId: "run-1", action: "start", metrics_config: {} },
    { runId: "run-1", action: "start", unexpected: true },
  ])("returns 400 without launching for invalid request %j", async (body) => {
    const startFn = vi.fn<StartFn>();

    const response = await handleMonitoringPost(
      createJsonPostRequest("http://localhost/api/evaluations/monitoring", body),
      startFn
    );

    expect(response.status).toBe(400);
    expect((await response.json()).error).toEqual(expect.any(String));
    expect(startFn).not.toHaveBeenCalled();
  });

  it("keeps launcher failures as 500 responses", async () => {
    const startFn = vi
      .fn<StartFn>()
      .mockRejectedValue(new Error("launcher failed"));

    const response = await handleMonitoringPost(
      createJsonPostRequest("http://localhost/api/evaluations/monitoring", {
        runId: "run-1",
        action: "start",
      }),
      startFn
    );

    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({ error: "launcher failed" });
  });

  it("maps typed run path validation failures to 400", async () => {
    const startFn = vi.fn<StartFn>().mockRejectedValue(
      new RunPathValidationError("runId must be one safe path segment.")
    );

    const response = await handleMonitoringPost(
      createJsonPostRequest("http://localhost/api/evaluations/monitoring", {
        runId: "run-1",
        action: "start",
      }),
      startFn
    );

    expect(response.status).toBe(400);
  });

  it("maps a missing valid run to 404", async () => {
    const startFn = vi.fn<StartFn>().mockRejectedValue(
      new RunNotFoundError("missing-run")
    );

    const response = await handleMonitoringPost(
      createJsonPostRequest("http://localhost/api/evaluations/monitoring", {
        runId: "missing-run",
        action: "start",
      }),
      startFn
    );

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "Run 'missing-run' was not found." });
  });
});
