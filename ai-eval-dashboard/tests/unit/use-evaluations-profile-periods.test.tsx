// @vitest-environment jsdom

import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  useEvaluations,
  usePreviousPeriodEvaluations,
} from "@/hooks/use-evaluations";
import type { EvaluationsResponse } from "@/types/evaluation";
import type { EvaluationRecord, ProfilePeriod } from "@/types/evaluation";
import { computeProfilePeriodSummaries } from "@/lib/aggregation";
import {
  createQueryClientWrapper,
  createTestQueryClient,
} from "./test-utils";

const profilePeriod = {
  instanceId: "business-hours:2026-01-02",
  periodId: "business-hours",
  start: "2026-01-02T09:00:00Z",
  end: "2026-01-02T17:00:00Z",
  conversationMode: "synth",
  behaviorMode: "benign",
  plannedConversations: 10,
};

function response(overrides: Partial<EvaluationsResponse> = {}): EvaluationsResponse {
  return {
    evaluations: [],
    profilePeriods: [],
    total: 0,
    from: "",
    to: "",
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useEvaluations profile response", () => {
  it("preserves array data compatibility while exposing profile periods from an empty result", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(response({ profilePeriods: [profilePeriod] })))
    );
    const client = createTestQueryClient();

    const { result } = renderHook(
      () => useEvaluations("last-90-days", "profiled-run"),
      { wrapper: createQueryClientWrapper(client) }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
    expect(result.current.profilePeriods).toEqual([profilePeriod]);
  });

  it("omits from and to API bounds for full-run while retaining run and limit", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(response())));
    const client = createTestQueryClient();

    const { result } = renderHook(
      () => useEvaluations("full-run", "profiled-run"),
      { wrapper: createQueryClientWrapper(client) }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]), "http://localhost");
    expect(url.searchParams.get("runId")).toBe("profiled-run");
    expect(url.searchParams.get("limit")).toBe("all");
    expect(url.searchParams.has("from")).toBe(false);
    expect(url.searchParams.has("to")).toBe(false);
  });

  it("keeps from and to API bounds for legacy presets", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(response())));
    const client = createTestQueryClient();

    const { result } = renderHook(
      () => useEvaluations("last-90-days", "legacy-run"),
      { wrapper: createQueryClientWrapper(client) }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]), "http://localhost");
    expect(url.searchParams.has("from")).toBe(true);
    expect(url.searchParams.has("to")).toBe(true);
    expect(url.searchParams.get("limit")).toBe("all");
  });

  it("keeps every full-run row so phase summaries include records beyond 2,000", async () => {
    const profilePeriods: ProfilePeriod[] = [
      {
        instanceId: "phase-a:day-1",
        periodId: "phase-a",
        start: "2020-01-01T00:00:00Z",
        end: "2020-01-01T12:00:00Z",
        conversationMode: "synth",
        behaviorMode: "benign",
        plannedConversations: 2000,
      },
      {
        instanceId: "phase-b:day-1",
        periodId: "phase-b",
        start: "2020-01-01T12:00:00Z",
        end: "2020-01-02T00:00:00Z",
        conversationMode: "adversarial",
        behaviorMode: "stress",
        plannedConversations: 5,
      },
    ];
    const evaluations = Array.from({ length: 2005 }, (_, index) =>
      ({
        timestamp: new Date(Date.UTC(2020, 0, 1, 0, 0, index)).toISOString(),
        turn_id: `turn-${index}`,
        safety_status: "pass",
        performance_status: "pass",
        safety_metrics: {},
        performance_metrics: {},
        profile_period_id: index < 2000 ? "phase-a" : "phase-b",
      }) as EvaluationRecord
    );
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify(
          response({ evaluations, profilePeriods, total: evaluations.length })
        )
      )
    );
    const client = createTestQueryClient();

    const { result } = renderHook(
      () => useEvaluations("full-run", "large-profiled-run"),
      { wrapper: createQueryClientWrapper(client) }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2005);
    expect(result.current.data?.at(-1)?.turn_id).toBe("turn-2004");
    expect(
      computeProfilePeriodSummaries(
        result.current.data || [],
        result.current.profilePeriods
      ).map((summary) => summary.evaluationCount)
    ).toEqual([2000, 5]);
  });

  it("has no synthetic previous-period API request for full-run", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(response())));
    const client = createTestQueryClient();
    const { result } = renderHook(
      () => usePreviousPeriodEvaluations("full-run", "profiled-run"),
      { wrapper: createQueryClientWrapper(client) }
    );

    const refreshed = await result.current.refetch();

    expect(refreshed.data).toEqual([]);
    expect(fetch).not.toHaveBeenCalled();
  });
});
