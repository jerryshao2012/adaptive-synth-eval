"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  ArtifactValidation,
  EvaluationRecord,
  EvaluationsResponse,
  MetricPointIdentity,
  MonitoringLogResponse,
  MonitoringRunStatus,
  MonitoringStartRequest,
  MonitoringStartResponse,
  ReviewQueueResponse,
  ReviewStats,
  RunSummary,
  TimePeriodPreset,
  TraceDetailsResponse,
} from "@/types/evaluation";
import { getTimePeriod, formatIntervalParam } from "@/lib/time-periods";

const API_BASE = process.env.NEXT_PUBLIC_EVAL_API_URL || "/api/evaluations";

async function fetchEvaluations(
  period: TimePeriodPreset,
  runId?: string
): Promise<EvaluationRecord[]> {
  const { from, to } = getTimePeriod(period);
  const params = new URLSearchParams({
    from: formatIntervalParam(from),
    to: formatIntervalParam(to),
    limit: "2000",
  });
  if (runId) {
    params.set("runId", runId);
  }

  const res = await fetch(`${API_BASE}/history?${params}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  const data: EvaluationsResponse = await res.json();
  return data.evaluations;
}

export function useEvaluations(
  period: TimePeriodPreset,
  runId?: string,
  enabled = true
) {
  return useQuery({
    queryKey: ["evaluations", period, runId ?? "all"],
    queryFn: () => fetchEvaluations(period, runId),
    select: (data) => data,
    enabled,
  });
}

// Fetch previous period for trend comparison
export function usePreviousPeriodEvaluations(
  period: TimePeriodPreset,
  runId?: string,
  enabled = true
) {
  const { from, to } = getTimePeriod(period);
  const durationMs = to.getTime() - from.getTime();
  const prevTo = new Date(from.getTime() - 1); // 1ms before current period start
  const prevFrom = new Date(prevTo.getTime() - durationMs);

  return useQuery({
    queryKey: ["evaluations", "previous", period, runId ?? "all"],
    queryFn: async () => {
      const params = new URLSearchParams({
        from: formatIntervalParam(prevFrom),
        to: formatIntervalParam(prevTo),
        limit: "2000",
      });
      if (runId) {
        params.set("runId", runId);
      }
      const res = await fetch(`${API_BASE}/history?${params}`);
      if (!res.ok) return [] as EvaluationRecord[];
      const data: EvaluationsResponse = await res.json();
      return data.evaluations;
    },
    enabled,
  });
}

export function useRunList() {
  return useQuery({
    queryKey: ["evaluation-runs"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/runs`);
      if (!res.ok) {
        throw new Error(`API error: ${res.status} ${res.statusText}`);
      }
      const data = (await res.json()) as { runs: RunSummary[] };
      return data.runs;
    },
    refetchInterval: 5000,
  });
}

export function useMonitoringStatus(runId?: string) {
  const queryClient = useQueryClient();
  const queryKey = ["monitoring-status", runId ?? "none"] as const;
  const query = useQuery({
    queryKey,
    queryFn: async () => {
      const params = new URLSearchParams({ runId: runId || "" });
      const res = await fetch(`${API_BASE}/monitoring?${params}`);
      if (!res.ok) {
        throw new Error(`API error: ${res.status} ${res.statusText}`);
      }
      return (await res.json()) as MonitoringRunStatus;
    },
    enabled: Boolean(runId),
    refetchInterval: 5000,
  });

  return {
    ...query,
    prepareRefreshAfterLaunch: async () => {
      await queryClient.cancelQueries({ queryKey, exact: true });
      return {
        baseline: queryClient.getQueryData<MonitoringRunStatus>(queryKey),
        result: query.refetch({ cancelRefetch: true, throwOnError: true }),
      };
    },
  };
}

export function useMonitoringLog(
  runId?: string,
  open = false,
  active = false
) {
  return useQuery({
    queryKey: ["monitoring-log", runId ?? "none"],
    queryFn: async () => {
      const params = new URLSearchParams({ runId: runId || "" });
      const res = await fetch(`${API_BASE}/monitoring/log?${params}`);
      if (!res.ok) {
        const body = await res
          .json()
          .catch(() => ({ error: "Failed to load the evaluation log." }));
        throw new Error(
          body.error || `API error: ${res.status} ${res.statusText}`
        );
      }
      return (await res.json()) as MonitoringLogResponse;
    },
    enabled: open && Boolean(runId),
    refetchInterval: open && active ? 2_000 : false,
  });
}

export function useStartMonitoring() {
  return useMutation({
    mutationFn: async (payload: MonitoringStartRequest) => {
      const res = await fetch(`${API_BASE}/monitoring`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: "Failed to start monitoring." }));
        throw new Error(error.error || `API error: ${res.status} ${res.statusText}`);
      }
      return (await res.json()) as MonitoringStartResponse;
    },
  });
}

export function useTraceDetails(point: MetricPointIdentity | null) {
  return useQuery({
    queryKey: ["trace-details", point],
    queryFn: async () => {
      if (!point) {
        throw new Error("No point selected.");
      }
      const params = new URLSearchParams({
        runId: point.runId,
        turnId: point.turnId,
        timestamp: point.timestamp,
        metricGroup: point.metricGroup,
        metricKey: point.metricKey,
      });
      if (point.conversationId) {
        params.set("conversationId", point.conversationId);
      }

      const res = await fetch(`${API_BASE}/trace?${params}`);
      if (!res.ok) {
        const error = await res
          .json()
          .catch(() => ({ error: "Failed to fetch trace details." }));
        throw new Error(error.error || `API error: ${res.status} ${res.statusText}`);
      }
      return (await res.json()) as TraceDetailsResponse;
    },
    enabled: Boolean(point),
    staleTime: Infinity,
    refetchInterval: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false,
  });
}

// ---- HITL Review Hooks ----

export function useReviewQueue(filters: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: ["review-queue", filters],
    queryFn: async () => {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(filters)) {
        if (value !== undefined && value !== null && value !== "") {
          params.set(key, String(value));
        }
      }
      const res = await fetch("/api/review/queue?" + params.toString());
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return (await res.json()) as ReviewQueueResponse;
    },
    staleTime: 60_000,
    refetchInterval: false,
  });
}

export function useReviewStats() {
  return useQuery<ReviewStats>({
    queryKey: ["review-stats"],
    queryFn: async () => {
      const res = await fetch("/api/review/stats");
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return (await res.json()) as ReviewStats;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useReviewDetail(
  runId: string | undefined,
  turnId: string | undefined
) {
  return useQuery({
    queryKey: ["review-detail", runId, turnId],
    queryFn: async () => {
      const res = await fetch(`/api/review/${runId}/${turnId}`);
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return await res.json();
    },
    enabled: Boolean(runId) && Boolean(turnId),
    staleTime: 30_000,
  });
}

export function useSaveReview() {
  return useMutation({
    mutationFn: async ({
      runId,
      turnId,
      review,
    }: {
      runId: string;
      turnId: string;
      review: Record<string, unknown>;
    }) => {
      const res = await fetch(`/api/review/${runId}/${turnId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(review),
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return res.json();
    },
  });
}

export function useBulkReviewAction() {
  return useMutation({
    mutationFn: async (payload: {
      action: string;
      records: Array<{ runId: string; turnId: string }>;
      flag?: string;
    }) => {
      const res = await fetch("/api/review/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return res.json();
    },
  });
}

export function useGoldenDatasets() {
  return useQuery({
    queryKey: ["golden-datasets"],
    queryFn: async () => {
      const res = await fetch("/api/golden-dataset");
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return await res.json();
    },
    staleTime: 60_000,
    refetchInterval: false,
  });
}

export function useGoldenDataset(id: string | undefined) {
  return useQuery({
    queryKey: ["golden-dataset", id],
    queryFn: async () => {
      const res = await fetch(`/api/golden-dataset/${id}`);
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return await res.json();
    },
    enabled: Boolean(id),
  });
}

export function useCreateDataset() {
  return useMutation({
    mutationFn: async (payload: {
      name: string;
      version: string;
      filters: Record<string, unknown>;
    }) => {
      const res = await fetch("/api/golden-dataset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return res.json();
    },
  });
}

/**
 * Fetch artifact validation status for a run.
 */
export function useValidation(runId?: string) {
  return useQuery({
    queryKey: ["validation", runId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/validation?runId=${encodeURIComponent(runId!)}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { error?: string }).error || `API error: ${res.status}`);
      }
      return res.json() as Promise<ArtifactValidation>;
    },
    enabled: Boolean(runId),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}
