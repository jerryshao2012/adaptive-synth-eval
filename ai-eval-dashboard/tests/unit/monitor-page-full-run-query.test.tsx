// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  EvaluationRecord,
  EvaluationsResponse,
  MetricValue,
  MonitoringRunStatus,
  RunSummary,
  TimePeriodPreset,
} from "@/types/evaluation";
import {
  createQueryClientWrapper,
  createTestQueryClient,
} from "./test-utils";

const runs: RunSummary[] = ["run-1", "run-2"].map((runId) => ({
  runId,
  mode: "unified",
  monitoringStatus: "completed",
  progress: { completed: 1, total: 1, percent: 100 },
  hasMonitoringState: true,
  hasMonitoringScores: true,
  canStart: false,
  canContinue: false,
  canReevaluate: true,
}));

const metric = (
  percent: number,
  status: MetricValue["status"] = "pass"
): MetricValue => ({
  score: percent / 100,
  percent,
  status,
  detail: "ok",
});

function evaluation(
  runId: string,
  timestamp: string,
  turnId: string,
  failed = false
): EvaluationRecord {
  return {
    timestamp,
    turn_id: turnId,
    user_text: "hello",
    response_text: "hi",
    variant: "monitoring",
    safety_status: failed ? "fail" : "pass",
    performance_status: "pass",
    safety_metrics: {
      toxicity: metric(failed ? 20 : 90, failed ? "fail" : "pass"),
      bias_fairness: metric(90),
      robustness: metric(90),
      compliance: metric(90),
    },
    performance_metrics: {
      relevance: metric(90),
      groundedness: metric(90),
      correctness: metric(90),
      completeness: metric(90),
      style: metric(90),
      precision: metric(90),
    },
    system_reliability: {
      llm_latency_ms: 100,
      llm_latency_status: "pass",
      guardrail_latency_ms: 20,
      guardrail_latency_status: "pass",
      total_latency_ms: 120,
      total_latency_status: "pass",
      availability: 1,
      availability_status: "pass",
    },
    run_id: runId,
  };
}

vi.mock("@/hooks/use-evaluations", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("@/hooks/use-evaluations")
  >();
  return {
    ...actual,
    useRunList: () => ({ data: runs, isLoading: false, refetch: vi.fn() }),
    useMonitoringStatus: (runId?: string) => ({
      data: runId
        ? ({
            runId,
            monitoringStatus: "completed",
            progress: { completed: 1, total: 1, percent: 100 },
            progressMarkdown: null,
            state: {},
            hasMonitoringScores: true,
          } satisfies MonitoringRunStatus)
        : undefined,
      latestSuccessfulRequestId: 1,
      prepareRefreshAfterLaunch: vi.fn(),
      refetch: vi.fn(),
    }),
    usePreviousPeriodEvaluations: () => ({ data: [] }),
    useStartMonitoring: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useTraceDetails: () => ({
      data: null,
      isLoading: false,
      isFetching: false,
      error: null,
    }),
  };
});

vi.mock("@/components/dashboard/time-period-selector", () => ({
  TimePeriodSelector: ({
    value,
    onChange,
    ariaLabel,
  }: {
    value: TimePeriodPreset;
    onChange: (period: TimePeriodPreset) => void;
    ariaLabel?: string;
  }) => (
    <select
      aria-label={ariaLabel ?? "Chart period"}
      value={value}
      onChange={(event) => onChange(event.target.value as TimePeriodPreset)}
    >
      <option value="last-90-days">Last 90 Days</option>
      <option value="last-7-days">Last 7 Days</option>
      <option value="full-run">Full Run</option>
    </select>
  ),
}));

vi.mock("@/components/dashboard/metric-line-chart", () => ({
  MetricLineChart: ({
    data,
    period,
  }: {
    data: Array<unknown>;
    period?: TimePeriodPreset;
  }) => (
    <div
      data-testid="metric-chart"
      data-period={period}
      data-points={data.length}
    />
  ),
}));

vi.mock("@/components/dashboard/evaluation-log-panel", () => ({
  EvaluationLogPanel: () => null,
}));
vi.mock("@/components/dashboard/investigation-summary", () => ({
  InvestigationSummaryCard: ({
    summary,
    hasData,
  }: {
    summary: { totalEvaluations: number; failedTurnCount: number } | null;
    hasData: boolean;
  }) => (
    <div
      data-testid="investigation-summary"
      data-has-data={String(hasData)}
      data-total={summary?.totalEvaluations ?? 0}
      data-failed={summary?.failedTurnCount ?? 0}
    />
  ),
}));
vi.mock("@/components/dashboard/failure-analysis", () => ({
  FailureAnalysis: ({ evaluations }: { evaluations: EvaluationRecord[] }) => (
    <div data-testid="failure-analysis" data-count={evaluations.length} />
  ),
}));
vi.mock("@/components/dashboard/conversation-queue", () => ({
  ConversationQueue: ({ evaluations }: { evaluations: EvaluationRecord[] }) => (
    <div data-testid="conversation-queue" data-count={evaluations.length} />
  ),
}));
vi.mock("@/components/dashboard/kpi-card", () => ({
  KpiCard: ({ label, value }: { label: string; value: string | number }) => (
    <div data-testid={`kpi-${label}`}>{value}</div>
  ),
}));
vi.mock("@/components/dashboard/trace-drawer", () => ({
  TraceDrawer: () => null,
}));

import DashboardPage from "@/app/(dashboard)/monitor/page";

function historyUrls(): URL[] {
  return vi
    .mocked(fetch)
    .mock.calls.map(([input]) => String(input))
    .filter((url) => url.includes("/history?"))
    .map((url) => new URL(url, "http://localhost"));
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const runId = url.searchParams.get("runId") || "run-1";
      const current = evaluation(runId, new Date().toISOString(), "current");
      const old = evaluation(
        runId,
        "2020-01-01T00:00:00Z",
        "old",
        true
      );
      const rows =
        runId === "run-2"
          ? url.searchParams.has("from")
            ? []
            : [old]
          : url.searchParams.has("from")
            ? [current]
            : [old, current];
      const response: EvaluationsResponse = {
        evaluations: rows,
        profilePeriods: [],
        total: rows.length,
        from: url.searchParams.get("from") || "",
        to: url.searchParams.get("to") || "",
      };
      return new Response(JSON.stringify(response));
    })
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Monitor page full-run chart data", () => {
  it("uses an unbounded history query for a legacy full-run chart and isolates it by run", async () => {
    const user = userEvent.setup();
    const client = createTestQueryClient();
    render(<DashboardPage />, {
      wrapper: createQueryClientWrapper(client),
    });

    const initialSelectors = await screen.findAllByLabelText("Chart period");
    expect(
      historyUrls().some(
        (url) =>
          url.searchParams.get("runId") === "run-1" &&
          url.searchParams.has("from") &&
          url.searchParams.has("to")
      )
    ).toBe(true);

    await user.selectOptions(initialSelectors[0], "full-run");

    await waitFor(() =>
      expect(
        historyUrls().some(
          (url) =>
            url.searchParams.get("runId") === "run-1" &&
            !url.searchParams.has("from") &&
            !url.searchParams.has("to")
        )
      ).toBe(true)
    );
    await waitFor(() =>
      expect(
        screen
          .getAllByTestId("metric-chart")
          .some(
            (chart) =>
              chart.getAttribute("data-period") === "full-run" &&
              chart.getAttribute("data-points") === "2"
          )
      ).toBe(true)
    );
    expect(
      client
        .getQueryCache()
        .find({ queryKey: ["evaluations", "full-run", "run-1"] })
        ?.getObserversCount()
    ).toBe(1);
    expect(screen.getByTestId("investigation-summary").getAttribute("data-total")).toBe("1");
    expect(screen.getByTestId("investigation-summary").getAttribute("data-failed")).toBe("0");
    expect(screen.queryByTestId("failure-analysis")).toBeNull();
    expect(screen.getByTestId("conversation-queue").getAttribute("data-count")).toBe("1");
    expect(screen.getByTestId("kpi-Total Evaluations").textContent).toBe("1");

    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-2"
    );

    await waitFor(() =>
      expect(
        historyUrls().some(
          (url) =>
            url.searchParams.get("runId") === "run-2" &&
            url.searchParams.has("from") &&
            url.searchParams.has("to")
        )
      ).toBe(true)
    );
    expect(
      client
        .getQueryCache()
        .find({ queryKey: ["evaluations", "last-90-days", "run-2"] })
        ?.getObserversCount()
    ).toBe(1);

    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-1"
    );
    await waitFor(() =>
      expect(
        client
          .getQueryCache()
          .find({ queryKey: ["evaluations", "full-run", "run-1"] })
          ?.getObserversCount()
      ).toBe(1)
    );

    const restoredSelectors = screen.getAllByLabelText("Chart period");
    const fullRunSelector = restoredSelectors.find(
      (selector) => (selector as HTMLSelectElement).value === "full-run"
    );
    expect(fullRunSelector).toBeTruthy();
    await user.selectOptions(fullRunSelector!, "last-90-days");

    await waitFor(() =>
      expect(
        client
          .getQueryCache()
          .find({ queryKey: ["evaluations", "last-90-days", "run-1"] })
          ?.getObserversCount()
      ).toBe(1)
    );
    expect(
      screen
        .getAllByTestId("metric-chart")
        .every((chart) => chart.getAttribute("data-points") === "1")
    ).toBe(true);
  });

  it("lets an old-only legacy run use the dashboard period selector to load full history", async () => {
    const user = userEvent.setup();
    const client = createTestQueryClient();
    render(<DashboardPage />, {
      wrapper: createQueryClientWrapper(client),
    });

    await screen.findAllByLabelText("Chart period");
    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-2"
    );
    await waitFor(() =>
      expect(
        historyUrls().some(
          (url) =>
            url.searchParams.get("runId") === "run-2" &&
            url.searchParams.has("from") &&
            url.searchParams.has("to")
        )
      ).toBe(true)
    );

    expect(screen.queryByTestId("metric-chart")).toBeNull();
    expect(screen.getByTestId("investigation-summary").getAttribute("data-has-data")).toBe("false");
    const dashboardPeriod = screen.getByLabelText(
      "Dashboard period"
    ) as HTMLSelectElement;
    expect(dashboardPeriod.value).toBe("last-90-days");

    await user.selectOptions(dashboardPeriod, "full-run");

    await waitFor(() =>
      expect(
        historyUrls().some(
          (url) =>
            url.searchParams.get("runId") === "run-2" &&
            !url.searchParams.has("from") &&
            !url.searchParams.has("to")
        )
      ).toBe(true)
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("metric-chart")[0].getAttribute("data-points")).toBe("1")
    );
    expect(screen.getByTestId("investigation-summary").getAttribute("data-total")).toBe("1");
    expect(screen.getByTestId("conversation-queue").getAttribute("data-count")).toBe("1");
    expect(screen.getByTestId("kpi-Total Evaluations").textContent).toBe("1");

    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-1"
    );
    expect(
      (screen.getByLabelText("Dashboard period") as HTMLSelectElement).value
    ).toBe("last-90-days");
    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-2"
    );
    expect(
      (screen.getByLabelText("Dashboard period") as HTMLSelectElement).value
    ).toBe("full-run");
  });

  it("fetches the widest bounded chart period and restores the narrower current-run query", async () => {
    const user = userEvent.setup();
    const client = createTestQueryClient();
    render(<DashboardPage />, {
      wrapper: createQueryClientWrapper(client),
    });

    await screen.findAllByLabelText("Chart period");
    await user.selectOptions(
      screen.getByLabelText("Dashboard period"),
      "last-7-days"
    );
    await waitFor(() =>
      expect(
        client
          .getQueryCache()
          .find({ queryKey: ["evaluations", "last-7-days", "run-1"] })
          ?.getObserversCount()
      ).toBe(1)
    );

    const chartPeriod = screen.getAllByLabelText("Chart period")[0];
    await user.selectOptions(chartPeriod, "last-90-days");
    await waitFor(() =>
      expect(
        client
          .getQueryCache()
          .find({ queryKey: ["evaluations", "last-90-days", "run-1"] })
          ?.getObserversCount()
      ).toBe(1)
    );

    await user.selectOptions(chartPeriod, "last-7-days");
    await waitFor(() =>
      expect(
        client
          .getQueryCache()
          .find({ queryKey: ["evaluations", "last-7-days", "run-1"] })
          ?.getObserversCount()
      ).toBe(1)
    );

    await user.selectOptions(
      screen.getByLabelText("Select evaluation run"),
      "run-2"
    );
    await waitFor(() =>
      expect(
        client
          .getQueryCache()
          .find({ queryKey: ["evaluations", "last-90-days", "run-2"] })
          ?.getObserversCount()
      ).toBe(1)
    );
  });
});
