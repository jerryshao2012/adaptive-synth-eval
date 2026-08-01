"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  ArtifactValidation,
  EvaluationRecord,
  EvaluationsResponse,
  GoldenCollection,
  GoldenDatasetVersion,
  GoldenExample,
  GoldenMetricKey,
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
): Promise<EvaluationsResponse> {
  const interval = getTimePeriod(period);
  const params = new URLSearchParams({ limit: runId ? "all" : "2000" });
  if (interval) {
    params.set("from", formatIntervalParam(interval.from));
    params.set("to", formatIntervalParam(interval.to));
  }
  if (runId) {
    params.set("runId", runId);
  }

  const res = await fetch(`${API_BASE}/history?${params}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  const data: EvaluationsResponse = await res.json();
  return {
    ...data,
    evaluations: Array.isArray(data.evaluations) ? data.evaluations : [],
    profilePeriods: Array.isArray(data.profilePeriods)
      ? data.profilePeriods
      : [],
  };
}

export function useEvaluations(
  period: TimePeriodPreset,
  runId?: string,
  enabled = true
) {
  const query = useQuery({
    queryKey: ["evaluations", period, runId ?? "all"],
    queryFn: () => fetchEvaluations(period, runId),
    enabled,
  });

  return {
    ...query,
    data: query.data?.evaluations,
    profilePeriods: query.data?.profilePeriods ?? [],
  };
}

// Fetch previous period for trend comparison
export function usePreviousPeriodEvaluations(
  period: TimePeriodPreset,
  runId?: string,
  enabled = true
) {
  const interval = getTimePeriod(period);
  const from = interval?.from;
  const to = interval?.to;
  const durationMs = from && to ? to.getTime() - from.getTime() : 0;
  const prevTo = new Date((from?.getTime() ?? 0) - 1); // 1ms before current period start
  const prevFrom = new Date(prevTo.getTime() - durationMs);

  return useQuery({
    queryKey: ["evaluations", "previous", period, runId ?? "all"],
    queryFn: async () => {
      if (!interval) return [] as EvaluationRecord[];
      const params = new URLSearchParams({
        from: formatIntervalParam(prevFrom),
        to: formatIntervalParam(prevTo),
        limit: runId ? "all" : "2000",
      });
      if (runId) {
        params.set("runId", runId);
      }
      const res = await fetch(`${API_BASE}/history?${params}`);
      if (!res.ok) return [] as EvaluationRecord[];
      const data: EvaluationsResponse = await res.json();
      return data.evaluations;
    },
    enabled: enabled && interval !== null,
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
  const nextRequestIdByRun = useRef(new Map<string, number>());
  const [latestSuccessfulRequestIdByRun, setLatestSuccessfulRequestIdByRun] =
    useState<Record<string, number>>({});
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const requestRunId = runId || "";
      const requestId = (nextRequestIdByRun.current.get(requestRunId) ?? 0) + 1;
      nextRequestIdByRun.current.set(requestRunId, requestId);
      const params = new URLSearchParams({ runId: runId || "" });
      const res = await fetch(`${API_BASE}/monitoring?${params}`, { signal });
      if (!res.ok) {
        throw new Error(`API error: ${res.status} ${res.statusText}`);
      }
      const status = (await res.json()) as MonitoringRunStatus;
      if (!signal.aborted) {
        setLatestSuccessfulRequestIdByRun((current) => ({
          ...current,
          [requestRunId]: Math.max(current[requestRunId] ?? 0, requestId),
        }));
      }
      return status;
    },
    enabled: Boolean(runId),
    refetchInterval: 5000,
  });

  return {
    ...query,
    latestSuccessfulRequestId:
      latestSuccessfulRequestIdByRun[runId || ""] ?? 0,
    prepareRefreshAfterLaunch: async () => {
      await queryClient.cancelQueries({ queryKey, exact: true });
      const baselineRequestId =
        nextRequestIdByRun.current.get(runId || "") ?? 0;
      return {
        baseline: queryClient.getQueryData<MonitoringRunStatus>(queryKey),
        baselineRequestId,
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
    refetchOnWindowFocus: active,
    refetchOnReconnect: active,
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

export interface GoldenExampleQuery {
  search?: string;
  tags?: string[];
  dimensions?: GoldenMetricKey[];
  collectionId?: string;
  runId?: string;
}

export interface GoldenCollectionQuery {
  search?: string;
  tags?: string[];
  dimensions?: GoldenMetricKey[];
  status?: GoldenCollection["status"];
}

function goldenParams(filters: object): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (Array.isArray(value) && value.length) params.set(key, value.join(","));
    else if (typeof value === "string" && value) params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function goldenJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error((body as { error?: string }).error || `API error: ${response.status}`);
  }
  return body as T;
}

export function useGoldenExamplesV2(filters: GoldenExampleQuery = {}) {
  return useQuery({
    queryKey: ["golden-examples-v2", filters],
    queryFn: () =>
      goldenJson<GoldenExample[]>(
        `/api/golden-dataset/examples${goldenParams(filters)}`
      ),
  });
}

export function useGoldenCollections(filters: GoldenCollectionQuery = {}) {
  return useQuery({
    queryKey: ["golden-collections", filters],
    queryFn: () =>
      goldenJson<GoldenCollection[]>(
        `/api/golden-dataset/collections${goldenParams(filters)}`
      ),
  });
}

export function useGoldenCollectionV2(id?: string) {
  return useQuery({
    queryKey: ["golden-collection-v2", id],
    queryFn: () =>
      goldenJson<GoldenCollection & { versions: GoldenDatasetVersion[] }>(
        `/api/golden-dataset/collections/${id}`
      ),
    enabled: Boolean(id),
  });
}

function useGoldenMutation<TInput, TOutput>(
  mutationFn: (input: TInput) => Promise<TOutput>
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["golden-examples-v2"] });
      queryClient.invalidateQueries({ queryKey: ["golden-collections"] });
      queryClient.invalidateQueries({ queryKey: ["golden-collection-v2"] });
    },
  });
}

export function useCreateGoldenCollection() {
  return useGoldenMutation<
    Pick<GoldenCollection, "name" | "description" | "dimensions" | "tags">,
    GoldenCollection
  >((payload) =>
    goldenJson("/api/golden-dataset/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export function useUpdateGoldenCollection() {
  return useGoldenMutation<
    { collectionId: string; expectedRevision: number } & Partial<
      Pick<GoldenCollection, "name" | "description" | "dimensions" | "tags" | "status">
    >,
    GoldenCollection
  >(({ collectionId, ...payload }) =>
    goldenJson(`/api/golden-dataset/collections/${collectionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export function useUpsertGoldenMembership() {
  return useGoldenMutation<
    {
      collectionId: string;
      expectedRevision: number;
      exampleId: string;
      annotations: GoldenCollection["memberships"][number]["annotations"];
      weight?: number;
      notes?: string;
    },
    GoldenCollection
  >(({ collectionId, ...payload }) =>
    goldenJson(`/api/golden-dataset/collections/${collectionId}/members`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export function useUpsertGoldenMemberships() {
  return useGoldenMutation<
    {
      collectionId: string;
      expectedRevision: number;
      members: Array<{
        exampleId: string;
        annotations: GoldenCollection["memberships"][number]["annotations"];
        weight?: number;
        notes?: string;
      }>;
    },
    GoldenCollection
  >(({ collectionId, ...payload }) =>
    goldenJson(`/api/golden-dataset/collections/${collectionId}/members`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export function useRemoveGoldenMembership() {
  return useGoldenMutation<
    { collectionId: string; exampleId: string; expectedRevision: number },
    GoldenCollection
  >(({ collectionId, exampleId, expectedRevision }) =>
    goldenJson(
      `/api/golden-dataset/collections/${collectionId}/members/${exampleId}?expectedRevision=${expectedRevision}`,
      { method: "DELETE" }
    )
  );
}

export function useRemoveGoldenMemberships() {
  return useGoldenMutation<
    { collectionId: string; exampleIds: string[]; expectedRevision: number },
    GoldenCollection
  >(({ collectionId, ...payload }) =>
    goldenJson(`/api/golden-dataset/collections/${collectionId}/members`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export function usePublishGoldenCollection() {
  return useGoldenMutation<
    { collectionId: string; version: string; expectedRevision: number; publisherId: string },
    GoldenDatasetVersion
  >(({ collectionId, ...payload }) =>
    goldenJson(`/api/golden-dataset/collections/${collectionId}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export function useSyncApprovedGoldenExamples() {
  return useGoldenMutation<{ runIds: string[] }, { imported: number; reused: number }>(
    (payload) =>
      goldenJson("/api/golden-dataset/examples/sync-approved", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
  );
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
