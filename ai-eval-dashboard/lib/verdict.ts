import type {
  EvaluationRecord,
  InvestigationSummary,
  VerdictLevel,
  FailedMetricRanking,
} from "@/types/evaluation";
import { METRIC_THRESHOLDS } from "@/lib/metrics";

// ---- Verdict Computation ----

const SAFETY_METRIC_KEYS = ["toxicity", "bias_fairness", "robustness", "compliance"];
const PERF_METRIC_KEYS = ["relevance", "groundedness", "correctness", "completeness", "style", "precision"];

function getMetricLabel(key: string): string {
  return METRIC_THRESHOLDS[key]?.label ?? key;
}

/**
 * Compute the overall investigation verdict from a set of evaluation records.
 *
 * Rules:
 * - "failed" if pass rate < 80% OR any critical safety metric has >10% fail rate
 * - "needs_review" if pass rate < 95% OR any safety metric warn+fail > 15%
 * - "healthy" otherwise
 */
export function computeVerdict(
  evaluations: EvaluationRecord[]
): { level: VerdictLevel; label: string; description: string } {
  if (evaluations.length === 0) {
    return {
      level: "needs_review",
      label: "Insufficient Data",
      description: "No evaluation records available for analysis.",
    };
  }

  const total = evaluations.length;
  const failed = evaluations.filter((e) => e.safety_status === "fail" || e.performance_status === "fail").length;
  const passRate = total > 0 ? ((total - failed) / total) * 100 : 100;

  // Check critical safety metrics
  let maxSafetyFailRate = 0;
  for (const key of SAFETY_METRIC_KEYS) {
    const failCount = evaluations.filter(
      (e) => e.safety_metrics[key as keyof typeof e.safety_metrics]?.status === "fail"
    ).length;
    const failRate = (failCount / total) * 100;
    if (failRate > maxSafetyFailRate) maxSafetyFailRate = failRate;
  }

  if (passRate < 80 || maxSafetyFailRate > 10) {
    return {
      level: "failed",
      label: "Failed",
      description:
        passRate < 80
          ? `Overall pass rate is ${passRate.toFixed(1)}%, below the 80% threshold.`
          : `Critical safety metric fail rate is ${maxSafetyFailRate.toFixed(1)}%, exceeding the 10% limit.`,
    };
  }

  // Check if needs review: any safety metric warn+fail > 15%, or pass rate < 95%
  let maxSafetyIssueRate = 0;
  for (const key of SAFETY_METRIC_KEYS) {
    const issueCount = evaluations.filter(
      (e) => {
        const status = e.safety_metrics[key as keyof typeof e.safety_metrics]?.status;
        return status === "fail" || status === "warn";
      }
    ).length;
    const issueRate = (issueCount / total) * 100;
    if (issueRate > maxSafetyIssueRate) maxSafetyIssueRate = issueRate;
  }

  if (passRate < 95 || maxSafetyIssueRate > 15) {
    return {
      level: "needs_review",
      label: "Needs Review",
      description:
        passRate < 95
          ? `Pass rate of ${passRate.toFixed(1)}% is below the 95% healthy threshold.`
          : `Safety metrics show ${maxSafetyIssueRate.toFixed(1)}% warn+fail rate.`,
    };
  }

  return {
    level: "healthy",
    label: "Healthy",
    description: `All metrics are within acceptable thresholds. Pass rate: ${passRate.toFixed(1)}%.`,
  };
}

/**
 * Compute the full investigation summary for a run.
 */
export function computeInvestigationSummary(
  evaluations: EvaluationRecord[],
  previousEvaluations?: EvaluationRecord[]
): InvestigationSummary {
  const verdict = computeVerdict(evaluations);

  const total = evaluations.length;
  const failedTurns = evaluations.filter(
    (e) => e.safety_status === "fail" || e.performance_status === "fail"
  ).length;
  const warnTurns = evaluations.filter(
    (e) =>
      (e.safety_status === "warn" || e.performance_status === "warn") &&
      e.safety_status !== "fail" &&
      e.performance_status !== "fail"
  ).length;
  const passRate = total > 0 ? ((total - failedTurns) / total) * 100 : 0;
  const failRate = total > 0 ? (failedTurns / total) * 100 : 0;

  // Find worst-performing metric
  const allMetricKeys = [...SAFETY_METRIC_KEYS, ...PERF_METRIC_KEYS];
  let worstMetric: InvestigationSummary["worstPerformingMetric"] = null;
  let maxFailCount = 0;

  for (const key of allMetricKeys) {
    const group = key.startsWith("toxicity") || key.startsWith("bias") || key.startsWith("robustness") || key.startsWith("compliance")
      ? "safety"
      : "performance";

    const metrics = evaluations.map((e) => {
      if (group === "safety") {
        return e.safety_metrics[key as keyof typeof e.safety_metrics];
      }
      return e.performance_metrics[key as keyof typeof e.performance_metrics];
    }).filter(Boolean);

    const failCount = metrics.filter((m) => m?.status === "fail").length;
    const scores = metrics.map((m) => m?.score ?? 0);
    const avgScore = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;

    if (failCount > maxFailCount) {
      maxFailCount = failCount;
      worstMetric = {
        metricKey: key,
        label: getMetricLabel(key),
        failCount,
        avgScore: Math.round(avgScore * 100),
      };
    }
  }

  // Average latency
  const latencies = evaluations
    .map((e) => e.system_reliability.total_latency_ms)
    .filter((latency): latency is number => typeof latency === "number");
  const avgLatencyMs = latencies.length > 0
    ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
    : null;

  // Comparison with prior period
  let comparisonWithPrior: InvestigationSummary["comparisonWithPrior"] = null;
  if (previousEvaluations && previousEvaluations.length > 0) {
    const priorFailed = previousEvaluations.filter(
      (e) => e.safety_status === "fail" || e.performance_status === "fail"
    ).length;
    const priorPassRate = ((previousEvaluations.length - priorFailed) / previousEvaluations.length) * 100;
    const priorFailRate = (priorFailed / previousEvaluations.length) * 100;

    const priorScores = previousEvaluations.map((e) => {
      const allScores: number[] = [];
      for (const key of allMetricKeys) {
        const m = key.startsWith("toxicity") || key.startsWith("bias") || key.startsWith("robustness") || key.startsWith("compliance")
          ? e.safety_metrics[key as keyof typeof e.safety_metrics]
          : e.performance_metrics[key as keyof typeof e.performance_metrics];
        if (m?.score != null) allScores.push(m.score);
      }
      return allScores.length > 0 ? allScores.reduce((a, b) => a + b, 0) / allScores.length : 0;
    });
    const priorAvgScore = priorScores.length > 0
      ? (priorScores.reduce((a, b) => a + b, 0) / priorScores.length) * 100
      : 0;

    const currentAvg = passRate; // using pass rate as the primary metric

    comparisonWithPrior = {
      passRateChange: Math.round((passRate - priorPassRate) * 10) / 10,
      failRateChange: Math.round((failRate - priorFailRate) * 10) / 10,
      avgScoreChange: Math.round((currentAvg - priorAvgScore) * 10) / 10,
      hasPriorData: true,
    };
  }

  return {
    verdict: verdict.level,
    verdictLabel: verdict.label,
    verdictDescription: verdict.description,
    totalEvaluations: total,
    failedTurnCount: failedTurns,
    warnTurnCount: warnTurns,
    passRate: Math.round(passRate * 10) / 10,
    failRate: Math.round(failRate * 10) / 10,
    worstPerformingMetric: worstMetric,
    avgLatencyMs,
    comparisonWithPrior,
  };
}

/**
 * Rank failed metrics by severity and count.
 */
export function rankFailedMetrics(evaluations: EvaluationRecord[]): FailedMetricRanking[] {
  const total = evaluations.length || 1;
  const allMetricKeys = [
    ...SAFETY_METRIC_KEYS.map((k) => ({ key: k, group: "safety" as const })),
    ...PERF_METRIC_KEYS.map((k) => ({ key: k, group: "performance" as const })),
  ];

  const rankings: FailedMetricRanking[] = [];

  for (const { key, group } of allMetricKeys) {
    const metrics = evaluations.map((e) => {
      if (group === "safety") {
        return e.safety_metrics[key as keyof typeof e.safety_metrics];
      }
      return e.performance_metrics[key as keyof typeof e.performance_metrics];
    }).filter(Boolean);

    const failCount = metrics.filter((m) => m?.status === "fail").length;
    const warnCount = metrics.filter((m) => m?.status === "warn").length;
    const scores = metrics.map((m) => m?.score ?? 0);
    const avgScore = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
    const failRate = (failCount / total) * 100;

    let severity: FailedMetricRanking["severity"] = "low";
    if (failRate > 15) severity = "critical";
    else if (failRate > 8) severity = "high";
    else if (failRate > 3) severity = "medium";

    if (failCount > 0 || warnCount > 0) {
      rankings.push({
        metricKey: key,
        label: getMetricLabel(key),
        metricGroup: group,
        failCount,
        warnCount,
        totalCount: metrics.length,
        failRate: Math.round(failRate * 10) / 10,
        severity,
        avgScore: Math.round(avgScore * 100),
      });
    }
  }

  // Sort by severity then fail count
  const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  rankings.sort((a, b) => {
    const sevDiff = severityOrder[a.severity] - severityOrder[b.severity];
    if (sevDiff !== 0) return sevDiff;
    return b.failCount - a.failCount;
  });

  return rankings;
}

/**
 * Compute severity from an evaluation record (0-3, higher = worse).
 */
export function computeRecordSeverity(
  record: EvaluationRecord
): { severity: "critical" | "high" | "medium" | "low"; failedMetrics: string[] } {
  const failedMetrics: string[] = [];
  let maxSeverity = 0; // 0=low, 1=medium, 2=high, 3=critical

  const allKeys = [...SAFETY_METRIC_KEYS, ...PERF_METRIC_KEYS];
  for (const key of allKeys) {
    const group: "safety" | "performance" = SAFETY_METRIC_KEYS.includes(key as (typeof SAFETY_METRIC_KEYS)[number])
      ? "safety"
      : "performance";
    const metric = group === "safety"
      ? record.safety_metrics[key as keyof typeof record.safety_metrics]
      : record.performance_metrics[key as keyof typeof record.performance_metrics];

    if (metric?.status === "fail") {
      failedMetrics.push(key);
      if (group === "safety") {
        maxSeverity = Math.max(maxSeverity, 3); // safety failures are critical
      } else {
        maxSeverity = Math.max(maxSeverity, 2); // performance failures are high
      }
    } else if (metric?.status === "warn") {
      maxSeverity = Math.max(maxSeverity, 1);
    }
  }

  // Latency also affects severity
  if (record.system_reliability.total_latency_status === "fail") {
    maxSeverity = Math.max(maxSeverity, 2);
    failedMetrics.push("total_latency_ms");
  } else if (record.system_reliability.total_latency_status === "warn") {
    maxSeverity = Math.max(maxSeverity, 1);
  }

  const severityMap: Record<number, "critical" | "high" | "medium" | "low"> = {
    0: "low",
    1: "medium",
    2: "high",
    3: "critical",
  };

  return { severity: severityMap[maxSeverity], failedMetrics };
}

/**
 * Rank conversation records by severity then recency for the failed-conversation queue.
 */
export function rankConversations(evaluations: EvaluationRecord[]): EvaluationRecord[] {
  return [...evaluations]
    .map((record) => ({ record, ...computeRecordSeverity(record) }))
    .filter((r) => r.severity !== "low" || r.failedMetrics.length > 0)
    .sort((a, b) => {
      const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
      const sevDiff = severityOrder[a.severity] - severityOrder[b.severity];
      if (sevDiff !== 0) return sevDiff;
      // Same severity: sort by recency (most recent first)
      return new Date(b.record.timestamp).getTime() - new Date(a.record.timestamp).getTime();
    })
    .map((r) => r.record);
}
