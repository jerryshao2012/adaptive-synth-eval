import type { EvaluationRecord, MetricPointIdentity } from "@/types/evaluation";

export interface KpiSummary {
  totalEvaluations: number;
  passRate: number; // 0–100
  failRate: number; // 0–100
  avgScore: number; // 0–100
  trendTotal: number; // % change vs previous period
  trendPassRate: number;
  trendFailRate: number;
  trendAvgScore: number;
}

export function computeKpiSummary(
  evaluations: EvaluationRecord[],
  previousEvaluations: EvaluationRecord[] = []
): KpiSummary {
  const total = evaluations.length;
  if (total === 0) {
    return {
      totalEvaluations: 0,
      passRate: 0,
      failRate: 0,
      avgScore: 0,
      trendTotal: 0,
      trendPassRate: 0,
      trendFailRate: 0,
      trendAvgScore: 0,
    };
  }

  const passCount = evaluations.filter(
    (e) => e.safety_status === "pass" && e.performance_status === "pass"
  ).length;
  const failCount = evaluations.filter(
    (e) =>
      e.safety_status === "fail" || e.performance_status === "fail"
  ).length;

  const allPercents: number[] = [];
  for (const e of evaluations) {
    const metrics = [
      ...Object.values(e.safety_metrics),
      ...Object.values(e.performance_metrics),
    ];
    for (const m of metrics) {
      allPercents.push(m.percent);
    }
  }
  const avgScore =
    allPercents.length > 0
      ? Math.round(allPercents.reduce((a, b) => a + b, 0) / allPercents.length)
      : 0;

  const passRate = Math.round((passCount / total) * 100);
  const failRate = Math.round((failCount / total) * 100);

  // Trend calculations
  const prevTotal = previousEvaluations.length;
  const trendTotal = prevTotal > 0 ? Math.round(((total - prevTotal) / prevTotal) * 100) : 0;

  let trendPassRate = 0;
  let trendFailRate = 0;
  let trendAvgScore = 0;

  if (prevTotal > 0) {
    const prevPassCount = previousEvaluations.filter(
      (e) => e.safety_status === "pass" && e.performance_status === "pass"
    ).length;
    const prevFailCount = previousEvaluations.filter(
      (e) => e.safety_status === "fail" || e.performance_status === "fail"
    ).length;
    const prevPassRate = Math.round((prevPassCount / prevTotal) * 100);
    const prevFailRate = Math.round((prevFailCount / prevTotal) * 100);
    trendPassRate = passRate - prevPassRate;
    trendFailRate = failRate - prevFailRate;

    const prevAllPercents: number[] = [];
    for (const e of previousEvaluations) {
      const metrics = [
        ...Object.values(e.safety_metrics),
        ...Object.values(e.performance_metrics),
      ];
      for (const m of metrics) {
        prevAllPercents.push(m.percent);
      }
    }
    const prevAvg =
      prevAllPercents.length > 0
        ? Math.round(
            prevAllPercents.reduce((a, b) => a + b, 0) / prevAllPercents.length
          )
        : 0;
    trendAvgScore = avgScore - prevAvg;
  }

  return {
    totalEvaluations: total,
    passRate,
    failRate,
    avgScore,
    trendTotal,
    trendPassRate,
    trendFailRate,
    trendAvgScore,
  };
}

export interface MetricTimeSeriesPoint {
  timestamp: string;
  value: number;
  status: "pass" | "warn" | "fail";
  detail: string;
  version?: string;
  pointIdentity?: MetricPointIdentity;
}

export type ChartSummary = {
  avg: number;
  min: number;
  max: number;
};

export function extractMetricTimeSeries(
  evaluations: EvaluationRecord[],
  metricGroup: "safety" | "performance",
  metricKey: string,
  defaultRunId?: string
): MetricTimeSeriesPoint[] {
  const points: MetricTimeSeriesPoint[] = [];
  for (const e of evaluations) {
    // Use type-safe access without converting to Record<string,...>
    const metrics = metricGroup === "safety" ? e.safety_metrics : e.performance_metrics;
    const metric = (metrics as unknown as Record<string, { percent: number; status: "pass" | "warn" | "fail"; detail: string; version?: string }>)[metricKey];
    if (metric) {
      points.push({
        timestamp: e.timestamp,
        value: metric.percent,
        status: metric.status,
        detail: metric.detail,
        version: metric.version,
        pointIdentity: {
          runId: e.run_id || defaultRunId || "",
          conversationId: e.conversation_id,
          turnId: String(e.turn_id),
          timestamp: e.timestamp,
          metricGroup,
          metricKey,
        },
      });
    }
  }
  return points.sort(
    (a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );
}

export function extractLatencyTimeSeries(
  evaluations: EvaluationRecord[],
  latencyKey: "llm_latency_ms" | "guardrail_latency_ms" | "total_latency_ms",
  defaultRunId?: string
): {
  timestamp: string;
  value: number;
  status: "pass" | "warn" | "fail";
  pointIdentity?: MetricPointIdentity;
}[] {
  return evaluations
    .map((e) => {
      const r = e.system_reliability;
      const statusKey = `${latencyKey.replace("_ms", "")}_status` as keyof typeof r;
      return {
        timestamp: e.timestamp,
        value: r[latencyKey] as number,
        status: r[statusKey] as "pass" | "warn" | "fail",
        pointIdentity: {
          runId: e.run_id || defaultRunId || "",
          conversationId: e.conversation_id,
          turnId: String(e.turn_id),
          timestamp: e.timestamp,
          metricGroup: "reliability" as const,
          metricKey: latencyKey,
        },
      };
    })
    .sort(
      (a, b) =>
        new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
}

export function computeChartSummary(
  points: { value: number }[]
): ChartSummary {
  if (points.length === 0) return { avg: 0, min: 0, max: 0 };
  const values = points.map((p) => p.value);
  return {
    avg: Math.round(values.reduce((a, b) => a + b, 0) / values.length),
    min: Math.min(...values),
    max: Math.max(...values),
  };
}
