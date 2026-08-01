import { describe, expect, it } from "vitest";

import { computeProfilePeriodSummaries } from "@/lib/aggregation";
import type {
  EvaluationRecord,
  MetricValue,
  ProfilePeriod,
} from "@/types/evaluation";

const metric = (percent: number): MetricValue => ({
  score: percent / 100,
  percent,
  status: "pass",
  detail: "",
});

const periods: ProfilePeriod[] = [
  {
    instanceId: "night:day-1",
    periodId: "night",
    start: "2026-01-01T18:00:00Z",
    end: "2026-01-01T23:00:00Z",
    conversationMode: "adversarial",
    behaviorMode: "stress",
    plannedConversations: 2,
  },
  {
    instanceId: "day:day-1",
    periodId: "day",
    start: "2026-01-01T09:00:00Z",
    end: "2026-01-01T17:00:00Z",
    conversationMode: "synth",
    behaviorMode: "benign",
    plannedConversations: 2,
  },
  {
    instanceId: "night:day-2",
    periodId: "night",
    start: "2026-01-02T18:00:00Z",
    end: "2026-01-02T23:00:00Z",
    conversationMode: "adversarial",
    behaviorMode: "stress",
    plannedConversations: 2,
  },
];

function evaluation(
  periodId: string,
  safetyStatus: EvaluationRecord["safety_status"],
  performanceStatus: EvaluationRecord["performance_status"],
  safety: Record<string, MetricValue>,
  performance: Record<string, MetricValue>
): EvaluationRecord {
  return {
    timestamp: "2026-01-01T12:00:00Z",
    turn_id: `${periodId}-${safetyStatus}-${performanceStatus}`,
    user_text: "hello",
    response_text: "hi",
    variant: "monitoring",
    safety_status: safetyStatus,
    performance_status: performanceStatus,
    safety_metrics: safety as unknown as EvaluationRecord["safety_metrics"],
    performance_metrics:
      performance as unknown as EvaluationRecord["performance_metrics"],
    system_reliability: {
      llm_latency_ms: null,
      llm_latency_status: "unknown",
      guardrail_latency_ms: null,
      guardrail_latency_status: "unknown",
      total_latency_ms: null,
      total_latency_status: "unknown",
      availability: null,
      availability_status: "unknown",
    },
    profile_period_id: periodId,
  };
}

describe("profile period summaries", () => {
  it("groups repeated instances and keeps the first profile-period order", () => {
    const summaries = computeProfilePeriodSummaries([], periods);

    expect(summaries.map((summary) => summary.periodId)).toEqual([
      "night",
      "day",
    ]);
    expect(summaries[0]).toMatchObject({
      modeLabel: "adversarial · stress",
      timeLabel: "18:00–23:00 daily",
      evaluationCount: 0,
    });
  });

  it("computes pass, fail, toxicity safety, safety, and performance averages", () => {
    const rows = [
      evaluation(
        "night",
        "pass",
        "pass",
        { toxicity: metric(30), compliance: metric(70) },
        { relevance: metric(80), style: metric(100) }
      ),
      evaluation(
        "night",
        "fail",
        "pass",
        { toxicity: metric(50) },
        { relevance: metric(60) }
      ),
    ];

    expect(computeProfilePeriodSummaries(rows, periods)[0]).toMatchObject({
      evaluationCount: 2,
      passRate: 50,
      failRate: 50,
      toxicitySafetyScore: 40,
      safetyAverage: 50,
      performanceAverage: 80,
    });
  });

  it("uses null metric averages when no finite metrics are available", () => {
    const rows = [evaluation("day", "warn", "warn", {}, {})];
    const day = computeProfilePeriodSummaries(rows, periods)[1];

    expect(day).toMatchObject({
      evaluationCount: 1,
      passRate: 0,
      failRate: 0,
      toxicitySafetyScore: null,
      safetyAverage: null,
      performanceAverage: null,
    });
  });

  it("ignores null and partial metric payloads instead of treating them as zero", () => {
    const row = evaluation(
      "day",
      "pass",
      "pass",
      { toxicity: metric(90) },
      { relevance: metric(70) }
    );
    row.safety_metrics = {
      toxicity: metric(90),
      compliance: null,
    } as unknown as EvaluationRecord["safety_metrics"];
    row.performance_metrics = {
      relevance: metric(70),
      style: undefined,
    } as unknown as EvaluationRecord["performance_metrics"];

    const day = computeProfilePeriodSummaries([row], periods)[1];

    expect(day.safetyAverage).toBe(90);
    expect(day.performanceAverage).toBe(70);
  });
});
