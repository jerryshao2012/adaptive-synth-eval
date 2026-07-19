// @vitest-environment jsdom

import type { PropsWithChildren } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMonitoringStatus } from "@/hooks/use-evaluations";
import type { MonitoringRunStatus } from "@/types/evaluation";

const terminalStatus: MonitoringRunStatus = {
  runId: "run-1",
  monitoringStatus: "completed",
  progress: { completed: 1, total: 1, percent: 100 },
  progressMarkdown: null,
  state: null,
  hasMonitoringScores: true,
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useMonitoringStatus request evidence", () => {
  it("advances only after successful requests and captures the post-launch boundary", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(terminalStatus))
      .mockResolvedValueOnce(jsonResponse(terminalStatus))
      .mockRejectedValueOnce(new Error("status unavailable"));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useMonitoringStatus("run-1"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.latestSuccessfulRequestId).toBe(1);

    let prepared!: Awaited<
      ReturnType<typeof result.current.prepareRefreshAfterLaunch>
    >;
    await act(async () => {
      prepared = await result.current.prepareRefreshAfterLaunch();
      await prepared.result;
    });
    expect(prepared.baselineRequestId).toBe(1);
    await waitFor(() =>
      expect(result.current.latestSuccessfulRequestId).toBe(2)
    );

    const successfulRequestId = result.current.latestSuccessfulRequestId;
    await act(async () => {
      await result.current.refetch();
    });
    expect(result.current.latestSuccessfulRequestId).toBe(successfulRequestId);
  });
});
