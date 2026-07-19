// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { RunSelectorHeader } from "@/components/dashboard/run-selector-header";
import type {
  MonitoringRunStatus,
  RunSummary,
} from "@/types/evaluation";

function makeRun(
  monitoringStatus: RunSummary["monitoringStatus"]
): RunSummary {
  return {
    runId: "run-1",
    mode: "unified",
    monitoringStatus,
    progress: { completed: 0, total: 10, percent: 0 },
    hasMonitoringState: monitoringStatus !== "not_started",
    hasMonitoringScores: monitoringStatus === "completed",
    canStart: monitoringStatus === "not_started",
    canContinue: monitoringStatus === "incomplete",
    canReevaluate: monitoringStatus === "completed",
  };
}

function makeStatus(
  monitoringStatus: MonitoringRunStatus["monitoringStatus"]
): MonitoringRunStatus {
  return {
    runId: "run-1",
    monitoringStatus,
    progress: { completed: 0, total: 10, percent: 0 },
    progressMarkdown: null,
    state: null,
    hasMonitoringScores: monitoringStatus === "completed",
  };
}

function renderHeader(
  status: RunSummary["monitoringStatus"],
  overrides: Partial<React.ComponentProps<typeof RunSelectorHeader>> = {}
) {
  const selectedRun = makeRun(status);
  const props: React.ComponentProps<typeof RunSelectorHeader> = {
    selectedRun,
    monitoringStatus: makeStatus(status),
    runs: [selectedRun],
    onSelectRun: vi.fn(),
    onLaunchIntent: vi.fn(),
    pendingLaunchKey: null,
    onRefresh: vi.fn(),
    ...overrides,
  };

  return { ...render(<RunSelectorHeader {...props} />), props };
}

beforeAll(() => {
  vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(cleanup);

describe("RunSelectorHeader evaluation actions", () => {
  it.each([
    ["not_started", "Start"],
    ["incomplete", "Continue"],
    ["completed", "Re-evaluate"],
  ] as const)("shows only %s run action as %s", (status, label) => {
    renderHeader(status);

    expect(screen.getByRole("button", { name: label })).toBeTruthy();
    for (const otherLabel of ["Start", "Continue", "Re-evaluate"]) {
      if (otherLabel !== label) {
        expect(
          screen.queryByRole("button", { name: otherLabel })
        ).toBeNull();
      }
    }
  });

  it.each(["queued", "in_progress"] as const)(
    "offers no launch action while the run is %s",
    (status) => {
      renderHeader(status);

      expect(screen.queryByRole("button", { name: "Start" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Re-evaluate" })
      ).toBeNull();
    }
  );

  it.each([
    ["not_started", "Start", "start"],
    ["incomplete", "Continue", "continue"],
    ["completed", "Re-evaluate", "reevaluate"],
  ] as const)(
    "reports a typed %s intent without launching directly",
    async (status, label, action) => {
      const user = userEvent.setup();
      const onLaunchIntent = vi.fn();
      renderHeader(status, { onLaunchIntent });

      await user.click(screen.getByRole("button", { name: label }));

      expect(onLaunchIntent).toHaveBeenCalledWith({ action, runId: "run-1" });
      expect(onLaunchIntent).toHaveBeenCalledTimes(1);
    }
  );

  it("disables the available action while any launch submission is pending", () => {
    renderHeader("completed", { pendingLaunchKey: "reevaluate:run-1" });

    expect(
      (screen.getByRole("button", { name: "Re-evaluate" }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
  });

  it("uses the fresher monitoring status when run summaries have not polled yet", () => {
    renderHeader("completed", { monitoringStatus: makeStatus("queued") });

    expect(
      screen.queryByRole("button", { name: "Re-evaluate" })
    ).toBeNull();
  });
});
