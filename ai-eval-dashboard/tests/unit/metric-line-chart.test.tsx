// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MetricPointIdentity, ProfilePeriod } from "@/types/evaluation";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  ComposedChart: ({
    children,
    data,
    onClick,
  }: {
    children: React.ReactNode;
    data: Array<Record<string, unknown>>;
    onClick?: (state: unknown) => void;
  }) => (
    <button
      type="button"
      data-testid="composed-chart"
      onClick={() =>
        onClick?.({ activePayload: [{ payload: data[0] }] })
      }
    >
      {children}
    </button>
  ),
  XAxis: (props: Record<string, unknown>) => (
    <div
      data-testid="x-axis"
      data-axis-type={String(props.type)}
      data-axis-key={String(props.dataKey)}
      data-axis-scale={String(props.scale)}
      data-formatted-tick={String(
        (props.tickFormatter as (value: number) => string)(
          Date.parse("2026-01-01T10:00:00Z")
        )
      )}
    />
  ),
  ReferenceArea: (props: {
    x1: number;
    x2: number;
    fill: string;
    label?: { value?: string };
  }) => (
    <div
      data-testid="profile-band"
      data-x1={props.x1}
      data-x2={props.x2}
      data-fill={props.fill}
    >
      {props.label?.value}
    </div>
  ),
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ReferenceLine: () => null,
  Area: () => null,
  Line: () => null,
}));

import { MetricLineChart } from "@/components/dashboard/metric-line-chart";

const identity: MetricPointIdentity = {
  runId: "run-1",
  conversationId: "conversation-1",
  turnId: "turn-1",
  timestamp: "2026-01-01T10:00:00Z",
  metricGroup: "safety",
  metricKey: "toxicity",
};

const data = [
  {
    timestamp: "2026-01-01T10:00:00Z",
    value: 80,
    status: "pass",
    pointIdentity: identity,
  },
  {
    timestamp: "2026-01-02T12:00:00Z",
    value: 70,
    status: "warn",
  },
];

const periods: ProfilePeriod[] = [
  {
    instanceId: "business:day-1",
    periodId: "business",
    start: "2026-01-01T09:00:00Z",
    end: "2026-01-01T17:00:00Z",
    conversationMode: "synth",
    behaviorMode: "benign",
    plannedConversations: 1,
  },
  {
    instanceId: "business:day-2",
    periodId: "business",
    start: "2026-01-02T09:00:00Z",
    end: "2026-01-02T17:00:00Z",
    conversationMode: "synth",
    behaviorMode: "benign",
    plannedConversations: 1,
  },
];

afterEach(cleanup);

describe("MetricLineChart profile phases", () => {
  it("uses a continuous numeric time axis and clipped repeated phase bands", () => {
    render(
      <MetricLineChart
        data={data}
        period="full-run"
        profilePeriods={periods}
      />
    );

    const axis = screen.getByTestId("x-axis");
    expect(axis.getAttribute("data-axis-type")).toBe("number");
    expect(axis.getAttribute("data-axis-key")).toBe("timeMs");
    expect(axis.getAttribute("data-axis-scale")).toBe("time");
    expect(axis.getAttribute("data-formatted-tick")).toBeTruthy();

    const bands = screen.getAllByTestId("profile-band");
    expect(bands).toHaveLength(2);
    expect(bands[0].getAttribute("data-x1")).toBe(
      String(Date.parse(data[0].timestamp))
    );
    expect(bands[1].getAttribute("data-x2")).toBe(
      String(Date.parse(data[1].timestamp))
    );
    expect(bands[0].getAttribute("data-fill")).toBe(
      bands[1].getAttribute("data-fill")
    );
    expect(bands[0].textContent).toBe("business");
    expect(bands[1].textContent).toBe("");
  });

  it("preserves point identity clicks after converting the x-axis", () => {
    const onPointClick = vi.fn();
    render(
      <MetricLineChart data={data} period="full-run" onPointClick={onPointClick} />
    );

    fireEvent.click(screen.getByTestId("composed-chart"));

    expect(onPointClick).toHaveBeenCalledWith(identity);
    expect(onPointClick).toHaveBeenCalledTimes(1);
  });

  it("keeps legacy charts band-free and preserves the empty state", () => {
    const { rerender } = render(
      <MetricLineChart data={data} period="last-90-days" />
    );
    expect(screen.queryByTestId("profile-band")).toBeNull();

    rerender(<MetricLineChart data={[]} period="last-90-days" />);
    expect(screen.getByText("No data for this period")).toBeTruthy();
  });
});
