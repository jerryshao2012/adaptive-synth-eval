"use client";

import { useQuery } from "@tanstack/react-query";
import type {
  EvaluationRecord,
  EvaluationsResponse,
  TimePeriodPreset,
} from "@/types/evaluation";
import { getTimePeriod, formatIntervalParam } from "@/lib/time-periods";

const API_BASE = process.env.NEXT_PUBLIC_EVAL_API_URL || "/api/evaluations";

async function fetchEvaluations(
  period: TimePeriodPreset
): Promise<EvaluationRecord[]> {
  const { from, to } = getTimePeriod(period);
  const params = new URLSearchParams({
    from: formatIntervalParam(from),
    to: formatIntervalParam(to),
    limit: "2000",
  });

  const res = await fetch(`${API_BASE}/history?${params}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  const data: EvaluationsResponse = await res.json();
  return data.evaluations;
}

export function useEvaluations(period: TimePeriodPreset) {
  return useQuery({
    queryKey: ["evaluations", period],
    queryFn: () => fetchEvaluations(period),
    select: (data) => data,
  });
}

// Fetch previous period for trend comparison
export function usePreviousPeriodEvaluations(period: TimePeriodPreset) {
  const { from, to } = getTimePeriod(period);
  const durationMs = to.getTime() - from.getTime();
  const prevTo = new Date(from.getTime() - 1); // 1ms before current period start
  const prevFrom = new Date(prevTo.getTime() - durationMs);

  return useQuery({
    queryKey: ["evaluations", "previous", period],
    queryFn: async () => {
      const params = new URLSearchParams({
        from: formatIntervalParam(prevFrom),
        to: formatIntervalParam(prevTo),
        limit: "2000",
      });
      const res = await fetch(`${API_BASE}/history?${params}`);
      if (!res.ok) return [] as EvaluationRecord[];
      const data: EvaluationsResponse = await res.json();
      return data.evaluations;
    },
  });
}
