// @vitest-environment jsdom

import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  QueryClient,
  QueryClientProvider,
  type QueryKey,
} from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EvaluationLogPanel } from "@/components/dashboard/evaluation-log-panel";
import { useMonitoringLog } from "@/hooks/use-evaluations";
import type { MonitoringLogResponse } from "@/types/evaluation";
import { createQueryClientWrapper, createTestQueryClient } from "./test-utils";

const fetchMock = vi.fn<typeof fetch>();

function logResponse(
  content: string,
  overrides: Partial<MonitoringLogResponse> = {}
): MonitoringLogResponse {
  return {
    runId: "run-1",
    content,
    size: new TextEncoder().encode(content).byteLength,
    truncated: false,
    ...overrides,
  };
}

function jsonFetch(data: MonitoringLogResponse): ReturnType<typeof fetch> {
  return Promise.resolve(
    new Response(JSON.stringify(data), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  );
}

const createClient = () => createTestQueryClient();

function renderPanel(
  props: Partial<React.ComponentProps<typeof EvaluationLogPanel>> = {},
  client = createClient()
) {
  const Wrapper = createQueryClientWrapper(client);
  const result = render(
    <Wrapper>
      <EvaluationLogPanel
        runId="run-1"
        monitoringStatus="completed"
        {...props}
      />
    </Wrapper>
  );
  return { ...result, client };
}

function queryOptions(client: QueryClient, key: QueryKey) {
  return client.getQueryCache().find({ queryKey: key })?.options as
    | {
        refetchInterval?: unknown;
        refetchOnReconnect?: unknown;
        refetchOnWindowFocus?: unknown;
      }
    | undefined;
}

async function flushTimers(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useMonitoringLog", () => {
  it("does not fetch while closed and fetches the selected run when opened", async () => {
    const client = createClient();
    fetchMock.mockImplementation(() => jsonFetch(logResponse("started\n")));
    const { rerender } = renderHook(
      ({ open }) => useMonitoringLog("run-1", open, false),
      {
        initialProps: { open: false },
        wrapper: createQueryClientWrapper(client),
      }
    );

    expect(fetchMock).not.toHaveBeenCalled();

    rerender({ open: true });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/evaluations/monitoring/log?runId=run-1"
    );
  });

  it("configures terminal log reads to ignore focus and reconnect refreshes", () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
    const inactiveClient = createClient();
    renderHook(() => useMonitoringLog("run-1", true, false), {
      wrapper: createQueryClientWrapper(inactiveClient),
    });
    const options = queryOptions(inactiveClient, ["monitoring-log", "run-1"]);
    expect(options?.refetchInterval).toBe(false);
    expect(options?.refetchOnWindowFocus).toBe(false);
    expect(options?.refetchOnReconnect).toBe(false);
  });

  it("starts two-second requests while active and stops them when collapsed", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(() => jsonFetch(logResponse("active\n")));
    const client = createClient();
    const { rerender } = renderHook(
      ({ open }) => useMonitoringLog("run-1", open, true),
      {
        initialProps: { open: true },
        wrapper: createQueryClientWrapper(client),
      }
    );

    await flushTimers();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await flushTimers(1_999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await flushTimers(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    rerender({ open: false });
    await flushTimers(4_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stops two-second requests when an active run becomes terminal", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(() => jsonFetch(logResponse("done\n")));
    const client = createClient();
    const { rerender } = renderHook(
      ({ active }) => useMonitoringLog("run-1", true, active),
      {
        initialProps: { active: true },
        wrapper: createQueryClientWrapper(client),
      }
    );

    await flushTimers();
    await flushTimers(2_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    rerender({ active: false });
    await flushTimers(4_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stops the old poller on a run switch until the new panel is opened", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(() => jsonFetch(logResponse("output\n")));
    const client = createClient();
    const { rerender } = renderHook(
      ({ runId, open }) => useMonitoringLog(runId, open, true),
      {
        initialProps: { runId: "run-1", open: true },
        wrapper: createQueryClientWrapper(client),
      }
    );

    await flushTimers();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender({ runId: "run-2", open: false });
    await flushTimers(4_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender({ runId: "run-2", open: true });
    await flushTimers();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/evaluations/monitoring/log?runId=run-2"
    );
  });
});

describe("EvaluationLogPanel", () => {
  it.each(["completed", "incomplete"] as const)(
    "allows a manual refresh for a %s run",
    async (monitoringStatus) => {
      const user = userEvent.setup();
      fetchMock
        .mockImplementationOnce(() => jsonFetch(logResponse("first\n")))
        .mockImplementationOnce(() => jsonFetch(logResponse("second\n")));
      renderPanel({ monitoringStatus });

      await user.click(
        screen.getByRole("button", { name: "Show evaluation log" })
      );
      await screen.findByText("first");
      await user.click(
        screen.getByRole("button", { name: "Refresh evaluation log" })
      );

      await screen.findByText("second");
      expect(fetchMock).toHaveBeenCalledTimes(2);
    }
  );

  it("shows loading, empty, truncated, and monospace log states", async () => {
    const user = userEvent.setup();
    let resolveFetch!: (response: Response) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        })
    );
    const { client } = renderPanel();

    await user.click(
      screen.getByRole("button", { name: "Show evaluation log" })
    );
    expect(screen.getByRole("status").textContent).toContain(
      "Loading evaluation log"
    );

    resolveFetch(
      new Response(JSON.stringify(logResponse("")), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    expect(
      await screen.findByText("No dashboard evaluation log is available yet.")
    ).toBeTruthy();

    act(() => {
      client.setQueryData(
        ["monitoring-log", "run-1"],
        logResponse("judge batch complete\n", {
          truncated: true,
          size: 300_000,
        })
      );
    });

    expect(
      await screen.findByText(/showing the most recent 256 KiB/i)
    ).toBeTruthy();
    const output = screen.getByText("judge batch complete");
    expect(output.tagName).toBe("PRE");
    expect(output.className).toContain("font-mono");
    expect(output.getAttribute("tabindex")).toBe("0");
  });

  it("announces an error and keeps manual refresh available", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ error: "Log unavailable" }), {
        status: 503,
        statusText: "Service Unavailable",
        headers: { "Content-Type": "application/json" },
      })
    );
    renderPanel({ monitoringStatus: "completed" });

    await user.click(
      screen.getByRole("button", { name: "Show evaluation log" })
    );

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Log unavailable"
    );
    expect(
      screen.getByRole("button", { name: "Refresh evaluation log" })
    ).toBeTruthy();
  });

  it("auto-scrolls after an update when the viewport was already at the bottom", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
    const client = createClient();
    client.setQueryData(
      ["monitoring-log", "run-1"],
      logResponse("line one\n")
    );
    renderPanel({}, client);
    await user.click(
      screen.getByRole("button", { name: "Show evaluation log" })
    );
    const viewport = screen.getByRole("log");
    Object.defineProperties(viewport, {
      clientHeight: { configurable: true, value: 20 },
      scrollHeight: { configurable: true, value: 100 },
      scrollTop: { configurable: true, value: 80, writable: true },
    });
    fireEvent.scroll(viewport);

    act(() => {
      client.setQueryData(
        ["monitoring-log", "run-1"],
        logResponse("line one\nline two\n")
      );
    });

    await waitFor(() => expect(viewport.scrollTop).toBe(100));
  });

  it("does not yank a scrolled-up viewport after an update", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
    const client = createClient();
    client.setQueryData(
      ["monitoring-log", "run-1"],
      logResponse("older line\n")
    );
    renderPanel({}, client);
    await user.click(
      screen.getByRole("button", { name: "Show evaluation log" })
    );
    const viewport = screen.getByRole("log");
    Object.defineProperties(viewport, {
      clientHeight: { configurable: true, value: 20 },
      scrollHeight: { configurable: true, value: 100 },
      scrollTop: { configurable: true, value: 10, writable: true },
    });
    fireEvent.scroll(viewport);

    act(() => {
      client.setQueryData(
        ["monitoring-log", "run-1"],
        logResponse("older line\nnew line\n")
      );
    });

    await waitFor(() =>
      expect(screen.getByText(/new line/)).toBeTruthy()
    );
    expect(viewport.scrollTop).toBe(10);
  });

  it("collapses and resets log fetching when the selected run changes", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => jsonFetch(logResponse("run output\n")));
    const { rerender, client } = renderPanel();
    const show = screen.getByRole("button", { name: "Show evaluation log" });

    await user.click(show);
    await screen.findByText("run output");
    expect(show.getAttribute("aria-expanded")).toBe("true");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender(
      <QueryClientProvider client={client}>
        <EvaluationLogPanel
          runId="run-2"
          monitoringStatus="in_progress"
        />
      </QueryClientProvider>
    );

    const nextShow = screen.getByRole("button", {
      name: "Show evaluation log",
    });
    expect(nextShow.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("log")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps a previously opened run closed after switching away and back", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => jsonFetch(logResponse("run output\n")));
    const { rerender, client } = renderPanel();

    await user.click(
      screen.getByRole("button", { name: "Show evaluation log" })
    );
    await screen.findByText("run output");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender(
      <QueryClientProvider client={client}>
        <EvaluationLogPanel runId="run-2" monitoringStatus="in_progress" />
      </QueryClientProvider>
    );
    rerender(
      <QueryClientProvider client={client}>
        <EvaluationLogPanel runId="run-1" monitoringStatus="completed" />
      </QueryClientProvider>
    );

    expect(
      screen.getByRole("button", { name: "Show evaluation log" })
        .getAttribute("aria-expanded")
    ).toBe("false");
    expect(screen.queryByRole("log")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
