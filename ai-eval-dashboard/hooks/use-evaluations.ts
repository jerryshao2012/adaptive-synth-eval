"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import type {
  EvaluationRecord,
  EvaluationsResponse,
  MonitoringRunStatus,
  MonitoringStartRequest,
  MonitoringStartResponse,
  RunSummary,
  TimePeriodPreset,
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
  return useQuery({
    queryKey: ["monitoring-status", runId ?? "none"],
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
