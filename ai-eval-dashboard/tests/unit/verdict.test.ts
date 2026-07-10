import { describe, it, expect } from "vitest";
import type { EvaluationRecord } from "@/types/evaluation";
import {
  computeVerdict,
  computeInvestigationSummary,
  rankFailedMetrics,
  rankConversations,
  computeRecordSeverity,
} from "@/lib/verdict";

// ---- Test fixtures ----

function makeRecord(overrides: Partial<EvaluationRecord> = {}): EvaluationRecord {
  return {
    timestamp: "2026-07-10T12:00:00Z",
    turn_id: "turn-001",
    user_text: "Hello",
    response_text: "Hi there",
    variant: "monitoring",
    safety_status: "pass",
    performance_status: "pass",
    safety_metrics: {
      toxicity: { score: 0.95, percent: 95, status: "pass", detail: "ok" },
      bias_fairness: { score: 0.92, percent: 92, status: "pass", detail: "ok" },
      robustness: { score: 0.93, percent: 93, status: "pass", detail: "ok" },
      compliance: { score: 0.94, percent: 94, status: "pass", detail: "ok" },
    },
    performance_metrics: {
      relevance: { score: 0.88, percent: 88, status: "pass", detail: "ok" },
      groundedness: { score: 0.85, percent: 85, status: "pass", detail: "ok" },
      correctness: { score: 0.7, percent: 70, status: "pass", detail: "ok" },
      completeness: { score: 0.68, percent: 68, status: "pass", detail: "ok" },
      style: { score: 0.72, percent: 72, status: "pass", detail: "ok" },
      precision: { score: 0.78, percent: 78, status: "pass", detail: "ok" },
    },
    system_reliability: {
      llm_latency_ms: 1200,
      llm_latency_status: "pass",
      guardrail_latency_ms: 300,
      guardrail_latency_status: "pass",
      total_latency_ms: 1500,
      total_latency_status: "pass",
      availability: 0.995,
      availability_status: "pass",
    },
    ...overrides,
  };
}

function makeFailingRecord(): EvaluationRecord {
  return makeRecord({
    turn_id: "turn-fail-001",
    safety_status: "fail",
    performance_status: "fail",
    safety_metrics: {
      toxicity: { score: 0.4, percent: 40, status: "fail", detail: "toxic content" },
      bias_fairness: { score: 0.5, percent: 50, status: "fail", detail: "biased" },
      robustness: { score: 0.3, percent: 30, status: "fail", detail: "vulnerable" },
      compliance: { score: 0.2, percent: 20, status: "fail", detail: "non-compliant" },
    },
    performance_metrics: {
      relevance: { score: 0.4, percent: 40, status: "fail", detail: "irrelevant" },
      groundedness: { score: 0.35, percent: 35, status: "fail", detail: "hallucination" },
      correctness: { score: 0.3, percent: 30, status: "fail", detail: "incorrect" },
      completeness: { score: 0.25, percent: 25, status: "fail", detail: "incomplete" },
      style: { score: 0.45, percent: 45, status: "fail", detail: "poor style" },
      precision: { score: 0.4, percent: 40, status: "fail", detail: "imprecise" },
    },
    system_reliability: {
      llm_latency_ms: 9000,
      llm_latency_status: "fail",
      guardrail_latency_ms: 2000,
      guardrail_latency_status: "warn",
      total_latency_ms: 11000,
      total_latency_status: "fail",
      availability: 0.92,
      availability_status: "fail",
    },
  });
}

// ============================================================
// computeVerdict
// ============================================================

describe("computeVerdict", () => {
  it("returns needs_review for empty evaluations", () => {
    const result = computeVerdict([]);
    expect(result.level).toBe("needs_review");
    expect(result.label).toContain("Insufficient");
  });

  it("returns healthy when all metrics pass with high scores", () => {
    const records = Array.from({ length: 100 }, (_, i) =>
      makeRecord({ turn_id: `turn-${i}` })
    );
    const result = computeVerdict(records);
    expect(result.level).toBe("healthy");
    expect(result.label).toBe("Healthy");
  });

  it("returns failed when pass rate is below 80%", () => {
    const records = [
      ...Array.from({ length: 30 }, (_, i) => makeFailingRecord()),
      ...Array.from({ length: 70 }, (_, i) => makeRecord({ turn_id: `pass-${i}` })),
    ];
    const result = computeVerdict(records);
    expect(result.level).toBe("failed");
    expect(result.label).toBe("Failed");
  });

  it("returns failed when a safety metric has >10% fail rate", () => {
    const records = [
      ...Array.from({ length: 15 }, (_, i) => {
        const rec = makeRecord({ turn_id: `tox-${i}` });
        rec.safety_metrics.toxicity.status = "fail";
        rec.safety_metrics.toxicity.score = 0.4;
        return rec;
      }),
      ...Array.from({ length: 85 }, (_, i) => makeRecord({ turn_id: `pass-${i}` })),
    ];
    const result = computeVerdict(records);
    expect(result.level).toBe("failed");
  });

  it("returns needs_review when pass rate is between 80-95%", () => {
    const records = [
      ...Array.from({ length: 10 }, (_, i) => makeFailingRecord()),
      ...Array.from({ length: 90 }, (_, i) => makeRecord({ turn_id: `pass-${i}` })),
    ];
    const result = computeVerdict(records);
    expect(result.level).toBe("needs_review");
    expect(result.label).toBe("Needs Review");
  });

  it("returns needs_review when safety metrics have >15% warn+fail", () => {
    const records = [
      ...Array.from({ length: 20 }, (_, i) => {
        const rec = makeRecord({ turn_id: `warn-${i}` });
        rec.safety_metrics.toxicity.status = "warn";
        rec.safety_metrics.toxicity.score = 0.7;
        return rec;
      }),
      ...Array.from({ length: 80 }, (_, i) => makeRecord({ turn_id: `pass-${i}` })),
    ];
    const result = computeVerdict(records);
    expect(result.level).toBe("needs_review");
  });
});

// ============================================================
// computeInvestigationSummary
// ============================================================

describe("computeInvestigationSummary", () => {
  it("returns correct counts for healthy data", () => {
    const records = Array.from({ length: 50 }, (_, i) => makeRecord({ turn_id: `turn-${i}` }));
    const summary = computeInvestigationSummary(records);
    expect(summary.verdict).toBe("healthy");
    expect(summary.totalEvaluations).toBe(50);
    expect(summary.failedTurnCount).toBe(0);
    expect(summary.failRate).toBe(0);
    expect(summary.passRate).toBe(100);
  });

  it("identifies worst-performing metric", () => {
    const records = [
      makeRecord({ turn_id: "bad-1" }),
      makeRecord({
        turn_id: "fail-1",
        safety_metrics: {
          ...makeRecord().safety_metrics,
          toxicity: { score: 0.3, percent: 30, status: "fail", detail: "toxic" },
        },
        safety_status: "fail",
      }),
      makeRecord({
        turn_id: "fail-2",
        safety_metrics: {
          ...makeRecord().safety_metrics,
          toxicity: { score: 0.2, percent: 20, status: "fail", detail: "toxic" },
        },
        safety_status: "fail",
      }),
    ];
    const summary = computeInvestigationSummary(records);
    expect(summary.worstPerformingMetric).not.toBeNull();
    expect(summary.worstPerformingMetric!.metricKey).toBe("toxicity");
    expect(summary.worstPerformingMetric!.failCount).toBe(2);
  });

  it("computes comparison with prior period", () => {
    const current = Array.from({ length: 50 }, (_, i) => makeRecord({ turn_id: `cur-${i}` }));
    const prior = [
      ...Array.from({ length: 45 }, (_, i) => makeRecord({ turn_id: `prev-${i}` })),
      ...Array.from({ length: 5 }, (_, i) => makeFailingRecord()),
    ];
    const summary = computeInvestigationSummary(current, prior);
    expect(summary.comparisonWithPrior).not.toBeNull();
    expect(summary.comparisonWithPrior!.hasPriorData).toBe(true);
    expect(summary.comparisonWithPrior!.passRateChange).toBeGreaterThan(0);
  });

  it("handles empty previous period", () => {
    const current = Array.from({ length: 50 }, (_, i) => makeRecord({ turn_id: `cur-${i}` }));
    const summary = computeInvestigationSummary(current, []);
    expect(summary.comparisonWithPrior).toBeNull();
  });

  it("computes average latency correctly", () => {
    const records = [
      makeRecord({ turn_id: "a", system_reliability: { ...makeRecord().system_reliability, total_latency_ms: 1000 } }),
      makeRecord({ turn_id: "b", system_reliability: { ...makeRecord().system_reliability, total_latency_ms: 2000 } }),
      makeRecord({ turn_id: "c", system_reliability: { ...makeRecord().system_reliability, total_latency_ms: 3000 } }),
    ];
    const summary = computeInvestigationSummary(records);
    expect(summary.avgLatencyMs).toBe(2000);
  });
});

// ============================================================
// rankFailedMetrics
// ============================================================

describe("rankFailedMetrics", () => {
  it("returns empty for all-passing data", () => {
    const records = Array.from({ length: 20 }, (_, i) => makeRecord({ turn_id: `turn-${i}` }));
    const ranked = rankFailedMetrics(records);
    expect(ranked).toHaveLength(0);
  });

  it("ranks metrics by severity then fail count", () => {
    const records = [
      // 5 toxicity failures -> critical
      ...Array.from({ length: 5 }, (_, i) => {
        const rec = makeRecord({ turn_id: `tox-${i}` });
        rec.safety_metrics.toxicity.status = "fail";
        rec.safety_metrics.toxicity.score = 0.3;
        rec.safety_status = "fail";
        return rec;
      }),
      // 2 relevance failures -> medium
      ...Array.from({ length: 2 }, (_, i) => {
        const rec = makeRecord({ turn_id: `rel-${i}` });
        rec.performance_metrics.relevance.status = "fail";
        rec.performance_metrics.relevance.score = 0.4;
        rec.performance_status = "fail";
        return rec;
      }),
      // 15 passing records
      ...Array.from({ length: 15 }, (_, i) => makeRecord({ turn_id: `pass-${i}` })),
    ];
    const ranked = rankFailedMetrics(records);
    expect(ranked.length).toBeGreaterThan(0);

    // Toxicity should be first (more failures = critical)
    const toxicityRank = ranked.find((r) => r.metricKey === "toxicity");
    expect(toxicityRank).toBeDefined();
    expect(toxicityRank!.severity).toBe("critical");
    expect(toxicityRank!.failCount).toBe(5);

    // Relevance should be after toxicity
    const relevanceRank = ranked.find((r) => r.metricKey === "relevance");
    expect(relevanceRank).toBeDefined();
  });

  it("assigns correct severity levels", () => {
    const total = 30;
    // 6 failures = 20% fail rate -> critical
    const records = Array.from({ length: 6 }, (_, i) => {
      const rec = makeRecord({ turn_id: `crit-${i}` });
      rec.safety_metrics.toxicity.status = "fail";
      rec.safety_metrics.toxicity.score = 0.2;
      rec.safety_status = "fail";
      return rec;
    }).concat(Array.from({ length: total - 6 }, (_, i) => makeRecord({ turn_id: `pass-${i}` })));

    const ranked = rankFailedMetrics(records);
    const toxicity = ranked.find((r) => r.metricKey === "toxicity");
    expect(toxicity).toBeDefined();
    expect(toxicity!.severity).toBe("critical");
    expect(toxicity!.failRate).toBeGreaterThan(15);
  });

  it("handles warn-only metrics", () => {
    const records = Array.from({ length: 5 }, (_, i) => {
      const rec = makeRecord({ turn_id: `warn-${i}` });
      rec.safety_metrics.compliance.status = "warn";
      rec.safety_metrics.compliance.score = 0.75;
      return rec;
    }).concat(Array.from({ length: 25 }, (_, i) => makeRecord({ turn_id: `pass-${i}` })));

    const ranked = rankFailedMetrics(records);
    const compliance = ranked.find((r) => r.metricKey === "compliance");
    expect(compliance).toBeDefined();
    expect(compliance!.warnCount).toBe(5);
    expect(compliance!.failCount).toBe(0);
  });
});

// ============================================================
// computeRecordSeverity
// ============================================================

describe("computeRecordSeverity", () => {
  it("returns low severity for passing record", () => {
    const record = makeRecord();
    const result = computeRecordSeverity(record);
    expect(result.severity).toBe("low");
    expect(result.failedMetrics).toHaveLength(0);
  });

  it("returns critical for safety failure", () => {
    const record = makeFailingRecord();
    const result = computeRecordSeverity(record);
    expect(result.severity).toBe("critical");
    expect(result.failedMetrics.length).toBeGreaterThan(0);
    // Should include safety metrics
    expect(result.failedMetrics).toContain("toxicity");
  });

  it("returns high for performance failure", () => {
    const record = makeRecord({
      turn_id: "perf-fail",
      performance_status: "fail",
      performance_metrics: {
        ...makeRecord().performance_metrics,
        relevance: { score: 0.3, percent: 30, status: "fail", detail: "bad" },
      },
    });
    const result = computeRecordSeverity(record);
    expect(result.severity).toBe("high");
    expect(result.failedMetrics).toContain("relevance");
  });

  it("returns medium for warnings only", () => {
    const record = makeRecord({
      turn_id: "warn-only",
      safety_status: "warn",
      safety_metrics: {
        ...makeRecord().safety_metrics,
        bias_fairness: { score: 0.7, percent: 70, status: "warn", detail: "borderline" },
      },
    });
    const result = computeRecordSeverity(record);
    expect(result.severity).toBe("medium");
  });

  it("includes latency failures in failed metrics", () => {
    const record = makeRecord({
      turn_id: "slow",
      system_reliability: {
        ...makeRecord().system_reliability,
        total_latency_ms: 10000,
        total_latency_status: "fail",
      },
    });
    const result = computeRecordSeverity(record);
    expect(result.failedMetrics).toContain("total_latency_ms");
    expect(result.severity).toBe("high");
  });
});

// ============================================================
// rankConversations
// ============================================================

describe("rankConversations", () => {
  it("returns empty for all-passing records", () => {
    const records = Array.from({ length: 10 }, (_, i) => makeRecord({ turn_id: `turn-${i}` }));
    const ranked = rankConversations(records);
    expect(ranked).toHaveLength(0);
  });

  it("ranks by severity then recency", () => {
    const older = makeFailingRecord();
    older.turn_id = "older";
    older.timestamp = "2026-07-09T12:00:00Z";

    const newer = makeFailingRecord();
    newer.turn_id = "newer";
    newer.timestamp = "2026-07-10T12:00:00Z";

    const warn = makeRecord({
      turn_id: "warn",
      safety_status: "warn",
      timestamp: "2026-07-10T14:00:00Z",
      safety_metrics: {
        ...makeRecord().safety_metrics,
        toxicity: { score: 0.75, percent: 75, status: "warn", detail: "borderline" },
      },
    });

    const rankings = rankConversations([warn, older, newer]);

    // Critical records first (failingRecord = critical)
    expect(rankings.length).toBeGreaterThanOrEqual(2);

    // Critical should come before medium (warn only)
    const firstCritical = rankings.findIndex((r) => r.turn_id === "newer");
    const warnIndex = rankings.findIndex((r) => r.turn_id === "warn");
    expect(firstCritical).toBeLessThan(warnIndex);

    // Among critical, newer should be before older
    const newerIdx = rankings.findIndex((r) => r.turn_id === "newer");
    const olderIdx = rankings.findIndex((r) => r.turn_id === "older");
    expect(newerIdx).toBeLessThan(olderIdx);
  });
});

// ============================================================
// Empty states and edge cases
// ============================================================

describe("empty states and edge cases", () => {
  it("computeInvestigationSummary handles single record", () => {
    const summary = computeInvestigationSummary([makeRecord()]);
    expect(summary.totalEvaluations).toBe(1);
    expect(summary.verdict).toBe("healthy");
    expect(summary.failedTurnCount).toBe(0);
  });

  it("computeInvestigationSummary handles single failing record", () => {
    const summary = computeInvestigationSummary([makeFailingRecord()]);
    expect(summary.totalEvaluations).toBe(1);
    expect(summary.verdict).toBe("failed");
    expect(summary.failedTurnCount).toBe(1);
    expect(summary.passRate).toBe(0);
  });

  it("rankFailedMetrics handles empty array", () => {
    expect(rankFailedMetrics([])).toEqual([]);
  });

  it("rankConversations handles empty array", () => {
    expect(rankConversations([])).toEqual([]);
  });

  it("handles records with zero latency", () => {
    const record = makeRecord({
      system_reliability: {
        ...makeRecord().system_reliability,
        total_latency_ms: 0,
      },
    });
    const summary = computeInvestigationSummary([record]);
    // Zero latencies should be filtered out in average calculation
    expect(summary.avgLatencyMs).toBe(0);
  });

  it("handles records with missing optional fields", () => {
    const record: EvaluationRecord = {
      timestamp: "2026-07-10T12:00:00Z",
      turn_id: "minimal",
      user_text: "",
      response_text: "",
      variant: "monitoring",
      safety_status: "pass",
      performance_status: "pass",
      safety_metrics: {
        toxicity: { score: 1.0, percent: 100, status: "pass", detail: "" },
        bias_fairness: { score: 1.0, percent: 100, status: "pass", detail: "" },
        robustness: { score: 1.0, percent: 100, status: "pass", detail: "" },
        compliance: { score: 1.0, percent: 100, status: "pass", detail: "" },
      },
      performance_metrics: {
        relevance: { score: 1.0, percent: 100, status: "pass", detail: "" },
        groundedness: { score: 1.0, percent: 100, status: "pass", detail: "" },
        correctness: { score: 1.0, percent: 100, status: "pass", detail: "" },
        completeness: { score: 1.0, percent: 100, status: "pass", detail: "" },
        style: { score: 1.0, percent: 100, status: "pass", detail: "" },
        precision: { score: 1.0, percent: 100, status: "pass", detail: "" },
      },
      system_reliability: {
        llm_latency_ms: 0,
        llm_latency_status: "pass",
        guardrail_latency_ms: 0,
        guardrail_latency_status: "pass",
        total_latency_ms: 0,
        total_latency_status: "pass",
        availability: 1.0,
        availability_status: "pass",
      },
    };
    const summary = computeInvestigationSummary([record]);
    expect(summary.verdict).toBe("healthy");
    expect(summary.avgLatencyMs).toBe(0);
  });

  it("handles many records without performance degradation", () => {
    const records = Array.from({ length: 500 }, (_, i) => {
      if (i % 10 === 0) return makeFailingRecord();
      return makeRecord({ turn_id: `turn-${i}` });
    });
    const start = performance.now();
    const summary = computeInvestigationSummary(records);
    const ranked = rankFailedMetrics(records);
    const conversations = rankConversations(records);
    const elapsed = performance.now() - start;

    expect(summary).toBeDefined();
    expect(ranked).toBeDefined();
    expect(conversations).toBeDefined();
    // Should complete in under 1 second
    expect(elapsed).toBeLessThan(1000);
  });
});
