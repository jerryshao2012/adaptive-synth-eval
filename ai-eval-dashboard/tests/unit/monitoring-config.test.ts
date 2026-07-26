import { describe, expect, it } from "vitest";

import {
  buildMonitoringArgs,
  DEFAULT_MONITORING_PARAMETERS,
  MonitoringRequestValidationError,
  normalizeMonitoringParameters,
  parseMonitoringStartRequest,
} from "@/lib/monitoring-config";

describe("monitoring parameter defaults and state normalization", () => {
  it("defines the live monitoring defaults", () => {
    expect(DEFAULT_MONITORING_PARAMETERS).toEqual({
      samplingStrategy: "all",
      sampleSize: 1000,
      intervalMinutes: 60,
      maxWindows: null,
    });
  });

  it("normalizes snake_case monitoring state", () => {
    expect(
      normalizeMonitoringParameters({
        sampling_strategy: "systematic",
        sample_size: 100,
        interval_minutes: 30,
        max_windows: 2,
      })
    ).toEqual({
      samplingStrategy: "systematic",
      sampleSize: 100,
      intervalMinutes: 30,
      maxWindows: 2,
    });
  });

  it("preserves valid legacy values while defaulting fields older state omitted", () => {
    expect(
      normalizeMonitoringParameters({
        sample_size: 250,
        interval_minutes: 15,
      })
    ).toEqual({
      samplingStrategy: "all",
      sampleSize: 250,
      intervalMinutes: 15,
      maxWindows: null,
    });
  });

  it("uses defaults for missing, malformed, or invalid state values", () => {
    expect(normalizeMonitoringParameters(undefined)).toEqual(
      DEFAULT_MONITORING_PARAMETERS
    );
    expect(
      normalizeMonitoringParameters({
        sampling_strategy: "ALL",
        sample_size: "100",
        interval_minutes: 0,
        max_windows: -1,
      })
    ).toEqual(DEFAULT_MONITORING_PARAMETERS);
  });
});

describe("parseMonitoringStartRequest", () => {
  it("applies defaults to the minimal supported request", () => {
    expect(
      parseMonitoringStartRequest({ runId: "run-1", action: "start" })
    ).toEqual({
      runId: "run-1",
      action: "start",
      ...DEFAULT_MONITORING_PARAMETERS,
    });
  });

  it.each(["start", "continue", "reevaluate"] as const)(
    "accepts the %s action",
    (action) => {
      expect(
        parseMonitoringStartRequest({ runId: "run-1", action }).action
      ).toBe(action);
    }
  );

  it.each(["all", "random", "systematic"] as const)(
    "accepts the %s sampling strategy",
    (samplingStrategy) => {
      expect(
        parseMonitoringStartRequest({
          runId: "run-1",
          action: "start",
          samplingStrategy,
        }).samplingStrategy
      ).toBe(samplingStrategy);
    }
  );

  it("accepts null or a positive integer for maxWindows", () => {
    expect(
      parseMonitoringStartRequest({
        runId: "run-1",
        action: "start",
        maxWindows: null,
      }).maxWindows
    ).toBeNull();
    expect(
      parseMonitoringStartRequest({
        runId: "run-1",
        action: "start",
        maxWindows: 3,
      }).maxWindows
    ).toBe(3);
  });

  it("accepts zero context and omits triggered fields for other strategies", () => {
    const triggered = parseMonitoringStartRequest({
      runId: "run-1",
      action: "start",
      samplingStrategy: "triggered",
      triggeredLookback: 0,
      triggeredLookahead: 0,
    });
    expect(triggered.triggeredLookback).toBe(0);
    expect(triggered.triggeredLookahead).toBe(0);

    const random = parseMonitoringStartRequest({
      runId: "run-1",
      action: "start",
      samplingStrategy: "random",
    });
    expect(random).not.toHaveProperty("triggeredLookback");
    expect(random).not.toHaveProperty("triggeredLookahead");
  });

  it("rejects the removed duplicate capture-budget field", () => {
    expect(() =>
      parseMonitoringStartRequest({
        runId: "run-1",
        action: "start",
        samplingStrategy: "triggered",
        triggeredCaptureBudget: 5,
      })
    ).toThrow(/Unsupported request field/);
  });

  it.each([
    null,
    [],
    "run-1",
    { runId: "run-1" },
    { runId: "run-1", action: "START" },
    { runId: "run-1", action: "start", samplingStrategy: "first" },
  ])("rejects invalid request shapes and enums: %j", (value) => {
    expect(() => parseMonitoringStartRequest(value)).toThrow(
      MonitoringRequestValidationError
    );
  });

  it.each([
    { sampleSize: 0 },
    { sampleSize: -1 },
    { sampleSize: 1.5 },
    { sampleSize: "10" },
    { sampleSize: "10items" },
    { intervalMinutes: 0 },
    { intervalMinutes: -1 },
    { intervalMinutes: 1.5 },
    { intervalMinutes: "30" },
    { maxWindows: 0 },
    { maxWindows: -1 },
    { maxWindows: 1.5 },
    { maxWindows: "2" },
  ])("rejects invalid integer fields: %j", (patch) => {
    expect(() =>
      parseMonitoringStartRequest({
        runId: "run-1",
        action: "start",
        ...patch,
      })
    ).toThrow(MonitoringRequestValidationError);
  });

  it.each([
    "",
    "   ",
    ".",
    "..",
    "../escape",
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
  ])("rejects an unsafe run ID: %j", (runId) => {
    expect(() =>
      parseMonitoringStartRequest({ runId, action: "start" })
    ).toThrow(MonitoringRequestValidationError);
  });

  it.each([
    { dryRun: true },
    { dry_run: true },
    { metricsConfig: {} },
    { metrics_config: {} },
    { model: "custom-model" },
    { customField: "value" },
  ])("rejects unsupported or unknown fields: %j", (extra) => {
    expect(() =>
      parseMonitoringStartRequest({
        runId: "run-1",
        action: "start",
        ...extra,
      })
    ).toThrow(MonitoringRequestValidationError);
  });
});

describe("buildMonitoringArgs", () => {
  it("builds start args for the all strategy without sample or max-window flags", () => {
    const request = parseMonitoringStartRequest({
      runId: "run-1",
      action: "start",
      samplingStrategy: "all",
    });

    expect(buildMonitoringArgs(request, "outputs/runs/run-1")).toEqual([
      "run",
      "ase",
      "monitor",
      "run",
      "--run-folder",
      "outputs/runs/run-1",
      "--sampling-strategy",
      "all",
      "--interval-minutes",
      "60",
      "--incomplete-run-action",
      "restart",
    ]);
  });

  it("builds continue args for random sampling", () => {
    const request = parseMonitoringStartRequest({
      runId: "run-1",
      action: "continue",
      samplingStrategy: "random",
      sampleSize: 50,
      intervalMinutes: 10,
    });

    expect(buildMonitoringArgs(request, "outputs/runs/run-1")).toEqual([
      "run",
      "ase",
      "monitor",
      "run",
      "--run-folder",
      "outputs/runs/run-1",
      "--sampling-strategy",
      "random",
      "--sample-size",
      "50",
      "--interval-minutes",
      "10",
      "--incomplete-run-action",
      "resume",
    ]);
  });

  it("builds reevaluation args for systematic sampling and bounded windows", () => {
    const request = parseMonitoringStartRequest({
      runId: "run-1",
      action: "reevaluate",
      samplingStrategy: "systematic",
      sampleSize: 100,
      intervalMinutes: 30,
      maxWindows: 2,
    });

    expect(buildMonitoringArgs(request, "outputs/runs/run-1")).toEqual([
      "run",
      "ase",
      "monitor",
      "run",
      "--run-folder",
      "outputs/runs/run-1",
      "--sampling-strategy",
      "systematic",
      "--sample-size",
      "100",
      "--interval-minutes",
      "30",
      "--max-windows",
      "2",
      "--incomplete-run-action",
      "resume",
      "--rescan",
    ]);
  });

  it("returns argv entries, never a shell command or unsupported flags", () => {
    const args = buildMonitoringArgs(
      parseMonitoringStartRequest({ runId: "run-1", action: "start" }),
      "outputs/runs/run 1"
    );

    expect(args[0]).toBe("run");
    expect(args).toContain("outputs/runs/run 1");
    expect(args).not.toContain("uv");
    expect(args).not.toContain("--dry-run");
    expect(args.join(" ")).not.toContain("--model");
    expect(args.join(" ")).not.toContain("--metrics-config");
  });

  it("uses sample size as the only triggered capture budget", () => {
    const request = parseMonitoringStartRequest({
      runId: "run-1",
      action: "start",
      samplingStrategy: "triggered",
      sampleSize: 5,
      triggeredLookback: 0,
      triggeredLookahead: 0,
    });
    const args = buildMonitoringArgs(request, "outputs/runs/run-1");
    expect(args).toContain("--sample-size");
    expect(args).not.toContain("--triggered-capture-budget");
    expect(args).toContain("--triggered-lookback");
    expect(args).toContain("0");
  });
});
