// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MonitoringRunStatus,
  MonitoringStartRequest,
  RunSummary,
} from "@/types/evaluation";

const hookState = vi.hoisted(() => ({
  mutateAsync: vi.fn(),
  refetchRuns: vi.fn(),
  refetchStatus: vi.fn(),
  prepareStatusRefreshAfterLaunch: vi.fn(),
  refetchEvaluations: vi.fn(),
  runs: [] as RunSummary[],
  statuses: {} as Record<string, MonitoringRunStatus | undefined>,
  statusUpdatedAt: {} as Record<string, number>,
}));

const completedRun: RunSummary = {
  runId: "run-1",
  mode: "unified",
  monitoringStatus: "completed",
  progress: { completed: 10, total: 10, percent: 100 },
  hasMonitoringState: true,
  hasMonitoringScores: true,
  canStart: false,
  canContinue: false,
  canReevaluate: true,
};

const completedStatus: MonitoringRunStatus = {
  runId: "run-1",
  monitoringStatus: "completed",
  updatedAt: "2026-07-19T10:00:00Z",
  progress: { completed: 10, total: 10, percent: 100 },
  progressMarkdown: null,
  state: {
    sampling_strategy: "systematic",
    sample_size: 24,
    interval_minutes: 15,
    max_windows: 6,
  },
  hasMonitoringScores: true,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

vi.mock("@/hooks/use-evaluations", () => ({
  useRunList: () => ({
    data: hookState.runs,
    isLoading: false,
    refetch: hookState.refetchRuns,
  }),
  useMonitoringStatus: (runId?: string) => ({
    data: runId ? hookState.statuses[runId] : undefined,
    dataUpdatedAt: runId ? hookState.statusUpdatedAt[runId] ?? 0 : 0,
    refetch: () => hookState.refetchStatus(runId),
    prepareRefreshAfterLaunch: () =>
      hookState.prepareStatusRefreshAfterLaunch(runId),
  }),
  useStartMonitoring: () => ({
    mutateAsync: hookState.mutateAsync,
    isPending: false,
  }),
  useEvaluations: () => ({
    data: [],
    isLoading: false,
    isError: false,
    error: null,
    refetch: hookState.refetchEvaluations,
  }),
  usePreviousPeriodEvaluations: () => ({ data: [] }),
  useTraceDetails: () => ({
    data: null,
    isLoading: false,
    isFetching: false,
    error: null,
  }),
  useMonitoringLog: () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/components/dashboard/investigation-summary", () => ({
  InvestigationSummaryCard: () => null,
}));
vi.mock("@/components/dashboard/trace-drawer", () => ({
  TraceDrawer: () => null,
}));

import DashboardPage from "@/app/(dashboard)/monitor/page";

beforeEach(() => {
  hookState.runs = [completedRun];
  hookState.statuses = { "run-1": completedStatus };
  hookState.statusUpdatedAt = { "run-1": 1 };
  hookState.mutateAsync.mockReset();
  hookState.mutateAsync.mockResolvedValue({
    runId: "run-1",
    started: true,
    command: "uv run ase monitor run",
    monitoringStatus: "queued",
  });
  hookState.refetchRuns.mockReset().mockResolvedValue({});
  hookState.refetchStatus.mockReset().mockResolvedValue({});
  hookState.prepareStatusRefreshAfterLaunch
    .mockReset()
    .mockImplementation((runId) =>
      Promise.resolve({
        baseline: runId ? hookState.statuses[runId] : undefined,
        result: Promise.resolve({
          data: runId ? hookState.statuses[runId] : undefined,
          isSuccess: true,
        }),
      })
    );
  hookState.refetchEvaluations.mockReset().mockResolvedValue({});
});

afterEach(cleanup);

describe("Monitor page evaluation configuration", () => {
  it("renders the collapsed evaluation log directly below the selected run header", () => {
    render(<DashboardPage />);

    const runSelector = screen.getByLabelText("Select evaluation run");
    const logToggle = screen.getByRole("button", {
      name: "Show evaluation log",
    });

    expect(
      runSelector.compareDocumentPosition(logToggle) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(logToggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("waits for matching saved state and freezes it when Re-evaluate opens", async () => {
    const user = userEvent.setup();
    hookState.statuses["run-1"] = undefined;
    hookState.statusUpdatedAt["run-1"] = 0;
    const { rerender } = render(<DashboardPage />);

    const actionBeforeState = screen.getByRole("button", {
      name: "Re-evaluate",
    }) as HTMLButtonElement;
    expect(actionBeforeState.disabled).toBe(true);
    await user.click(actionBeforeState);
    expect(
      screen.queryByRole("heading", { name: "Re-evaluate run" })
    ).toBeNull();

    hookState.statuses["run-1"] = completedStatus;
    hookState.statusUpdatedAt["run-1"] = 1;
    rerender(<DashboardPage />);
    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));

    expect(
      (screen.getByLabelText("Interval minutes") as HTMLInputElement).value
    ).toBe("15");
    hookState.statuses["run-1"] = {
      ...completedStatus,
      state: {
        ...completedStatus.state,
        interval_minutes: 99,
      },
    };
    hookState.statusUpdatedAt["run-1"] = 2;
    rerender(<DashboardPage />);
    expect(
      (screen.getByLabelText("Interval minutes") as HTMLInputElement).value
    ).toBe("15");
  });

  it("opens Re-evaluate with normalized selected-run settings", async () => {
    const user = userEvent.setup();
    render(<DashboardPage />);

    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));

    expect(
      screen.getByRole("heading", { name: "Re-evaluate run" })
    ).toBeTruthy();
    expect(
      (screen.getByLabelText("Sampling strategy") as HTMLSelectElement).value
    ).toBe("systematic");
    expect(
      (screen.getByLabelText("Sample size") as HTMLInputElement).value
    ).toBe("24");
    expect(
      (screen.getByLabelText("Interval minutes") as HTMLInputElement).value
    ).toBe("15");
    expect(
      (screen.getByLabelText("Max windows") as HTMLInputElement).value
    ).toBe("6");
    expect(hookState.mutateAsync).not.toHaveBeenCalled();
  });

  it("submits one typed live launch and refetches all run views after acceptance", async () => {
    const user = userEvent.setup();
    render(<DashboardPage />);
    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));
    await user.clear(screen.getByLabelText("Interval minutes"));
    await user.type(screen.getByLabelText("Interval minutes"), "30");

    await user.click(
      screen.getByRole("button", { name: "Re-evaluate run" })
    );

    const expectedRequest: MonitoringStartRequest = {
      runId: "run-1",
      action: "reevaluate",
      samplingStrategy: "systematic",
      sampleSize: 24,
      intervalMinutes: 30,
      maxWindows: 6,
    };
    await waitFor(() =>
      expect(hookState.mutateAsync).toHaveBeenCalledWith(expectedRequest)
    );
    expect(hookState.mutateAsync).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(hookState.refetchRuns).toHaveBeenCalledTimes(1);
      expect(hookState.prepareStatusRefreshAfterLaunch).toHaveBeenCalledTimes(
        1
      );
      expect(hookState.refetchEvaluations).toHaveBeenCalledTimes(1);
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Re-evaluate run" })
      ).toBeNull()
    );
  });

  it("keeps the dialog open with the launch error and skips refetching", async () => {
    const user = userEvent.setup();
    hookState.mutateAsync.mockRejectedValue(
      new Error("The evaluation launch is already active.")
    );
    render(<DashboardPage />);
    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));

    await user.click(
      screen.getByRole("button", { name: "Re-evaluate run" })
    );

    expect(
      await screen.findByText("The evaluation launch is already active.")
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Re-evaluate run" })
    ).toBeTruthy();
    expect(hookState.refetchRuns).not.toHaveBeenCalled();
    expect(hookState.refetchStatus).not.toHaveBeenCalled();
    expect(hookState.refetchEvaluations).not.toHaveBeenCalled();
  });

  it("keeps an accepted launch queued when refresh fails, then yields to canonical completion", async () => {
    const user = userEvent.setup();
    const failedStatusRefresh = deferred<{ data: MonitoringRunStatus }>();
    hookState.refetchRuns.mockRejectedValue(new Error("runs unavailable"));
    hookState.refetchStatus.mockRejectedValue(new Error("status unavailable"));
    hookState.prepareStatusRefreshAfterLaunch.mockResolvedValue({
      baseline: completedStatus,
      result: failedStatusRefresh.promise,
    });
    hookState.refetchEvaluations.mockRejectedValue(
      new Error("evaluations unavailable")
    );
    const { rerender } = render(<DashboardPage />);
    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));

    await user.click(
      screen.getByRole("button", { name: "Re-evaluate run" })
    );

    await waitFor(() =>
      expect(hookState.mutateAsync).toHaveBeenCalledTimes(1)
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Re-evaluate run" })
      ).toBeNull()
    );
    await act(async () => {
      failedStatusRefresh.reject(new Error("status unavailable"));
      await Promise.resolve();
    });
    expect(
      screen.queryByText("status unavailable")
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Re-evaluate" })
    ).toBeNull();

    hookState.statuses["run-1"] = {
      ...completedStatus,
      state: { ...completedStatus.state, updated_at: "2026-07-19T12:00:00Z" },
    };
    hookState.statusUpdatedAt["run-1"] = 2;
    rerender(<DashboardPage />);

    expect(
      await screen.findByRole("button", { name: "Re-evaluate" })
    ).toBeTruthy();
  });

  it("ignores a stale pre-accept poll, then trusts the equal-timestamp explicit result", async () => {
    const user = userEvent.setup();
    const launch = deferred<{
      runId: string;
      started: boolean;
      command: string;
      monitoringStatus: "queued";
    }>();
    const postAcceptanceStatus = deferred<{
      data: MonitoringRunStatus;
      isSuccess: true;
    }>();
    hookState.mutateAsync.mockReturnValue(launch.promise);
    hookState.prepareStatusRefreshAfterLaunch.mockImplementation((runId) =>
      Promise.resolve({
        baseline: runId ? hookState.statuses[runId] : undefined,
        result: postAcceptanceStatus.promise,
      })
    );
    const { rerender } = render(<DashboardPage />);
    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));
    await user.click(
      screen.getByRole("button", { name: "Re-evaluate run" })
    );
    await waitFor(() =>
      expect(hookState.mutateAsync).toHaveBeenCalledTimes(1)
    );

    hookState.statuses["run-1"] = { ...completedStatus };
    hookState.statusUpdatedAt["run-1"] = 2;
    rerender(<DashboardPage />);
    await act(async () => {
      launch.resolve({
        runId: "run-1",
        started: true,
        command: "uv run ase monitor run",
        monitoringStatus: "queued",
      });
      await launch.promise;
    });

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Re-evaluate run" })
      ).toBeNull()
    );
    expect(
      screen.queryByRole("button", { name: "Re-evaluate" })
    ).toBeNull();
    await act(async () => {
      postAcceptanceStatus.resolve({
        data: { ...completedStatus },
        isSuccess: true,
      });
      await postAcceptanceStatus.promise;
    });
    expect(
      await screen.findByRole("button", { name: "Re-evaluate" })
    ).toBeTruthy();
  });

  it("releases a legacy null-timestamp overlay from its explicit matching result", async () => {
    const user = userEvent.setup();
    const legacyStatus: MonitoringRunStatus = {
      ...completedStatus,
      updatedAt: undefined,
      state: {
        sampling_strategy: "systematic",
        sample_size: 24,
        interval_minutes: 15,
        max_windows: null,
      },
    };
    const postAcceptanceStatus = deferred<{
      data: MonitoringRunStatus;
      isSuccess: true;
    }>();
    hookState.statuses["run-1"] = legacyStatus;
    hookState.prepareStatusRefreshAfterLaunch.mockResolvedValue({
      baseline: legacyStatus,
      result: postAcceptanceStatus.promise,
    });
    render(<DashboardPage />);
    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));
    await user.click(
      screen.getByRole("button", { name: "Re-evaluate run" })
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Re-evaluate run" })
      ).toBeNull()
    );
    expect(
      screen.queryByRole("button", { name: "Re-evaluate" })
    ).toBeNull();

    await act(async () => {
      postAcceptanceStatus.resolve({
        data: { ...legacyStatus },
        isSuccess: true,
      });
      await postAcceptanceStatus.promise;
    });

    expect(
      await screen.findByRole("button", { name: "Re-evaluate" })
    ).toBeTruthy();
  });

  it("retains the overlay when a resolved refetch error carries cached matching data", async () => {
    const user = userEvent.setup();
    hookState.prepareStatusRefreshAfterLaunch.mockResolvedValue({
      baseline: completedStatus,
      result: Promise.resolve({
        data: completedStatus,
        error: new Error("status unavailable"),
        isError: true,
        isRefetchError: true,
        isSuccess: false,
      }),
    });
    render(<DashboardPage />);
    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));
    await user.click(
      screen.getByRole("button", { name: "Re-evaluate run" })
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Re-evaluate run" })
      ).toBeNull()
    );
    expect(
      screen.queryByRole("button", { name: "Re-evaluate" })
    ).toBeNull();
  });

  it("retains independent run overlays until each post-acceptance completion arrives", async () => {
    const user = userEvent.setup();
    const runTwo: RunSummary = {
      ...completedRun,
      runId: "run-2",
    };
    const statusTwo: MonitoringRunStatus = {
      ...completedStatus,
      runId: "run-2",
      state: {
        ...completedStatus.state,
        sample_size: 48,
      },
    };
    const runOneConfirmation = deferred<{
      data: MonitoringRunStatus;
      isSuccess: true;
    }>();
    const runTwoConfirmation = deferred<{
      data: MonitoringRunStatus;
      isSuccess: true;
    }>();
    hookState.runs = [completedRun, runTwo];
    hookState.statuses = {
      "run-1": completedStatus,
      "run-2": statusTwo,
    };
    hookState.statusUpdatedAt = { "run-1": 1, "run-2": 1 };
    hookState.prepareStatusRefreshAfterLaunch.mockImplementation((runId) =>
      Promise.resolve({
        baseline: runId ? hookState.statuses[runId] : undefined,
        result:
          runId === "run-1"
            ? runOneConfirmation.promise
            : runTwoConfirmation.promise,
      })
    );
    const { rerender } = render(<DashboardPage />);

    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));
    await user.click(
      screen.getByRole("button", { name: "Re-evaluate run" })
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Re-evaluate run" })
      ).toBeNull()
    );

    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-2"
    );
    await user.click(screen.getByRole("button", { name: "Re-evaluate" }));
    await user.click(
      screen.getByRole("button", { name: "Re-evaluate run" })
    );
    await waitFor(() => expect(hookState.mutateAsync).toHaveBeenCalledTimes(2));

    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-1"
    );
    expect(
      screen.queryByRole("button", { name: "Re-evaluate" })
    ).toBeNull();
    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-2"
    );
    expect(
      screen.queryByRole("button", { name: "Re-evaluate" })
    ).toBeNull();

    hookState.statuses["run-1"] = {
      ...completedStatus,
      updatedAt: "2026-07-19T12:00:00Z",
    };
    await act(async () => {
      runOneConfirmation.resolve({
        data: hookState.statuses["run-1"]!,
        isSuccess: true,
      });
      await runOneConfirmation.promise;
    });
    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-1"
    );
    rerender(<DashboardPage />);
    expect(
      await screen.findByRole("button", { name: "Re-evaluate" })
    ).toBeTruthy();

    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-2"
    );
    expect(
      screen.queryByRole("button", { name: "Re-evaluate" })
    ).toBeNull();
    hookState.statuses["run-2"] = {
      ...statusTwo,
      updatedAt: "2026-07-19T12:00:01Z",
    };
    await act(async () => {
      runTwoConfirmation.resolve({
        data: hookState.statuses["run-2"]!,
        isSuccess: true,
      });
      await runTwoConfirmation.promise;
    });
    rerender(<DashboardPage />);
    expect(
      await screen.findByRole("button", { name: "Re-evaluate" })
    ).toBeTruthy();
  });
});
