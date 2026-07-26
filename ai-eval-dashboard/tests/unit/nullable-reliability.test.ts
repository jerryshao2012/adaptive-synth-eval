import { describe, expect, it } from "vitest";

import { extractLatencyTimeSeries } from "@/lib/aggregation";
import { computeInvestigationSummary } from "@/lib/verdict";
import type { EvaluationRecord } from "@/types/evaluation";

function unknownReliabilityRecord(): EvaluationRecord {
  return {
    timestamp: "2026-01-01T00:00:00Z",
    turn_id: "1",
    user_text: "hello",
    response_text: "",
    variant: "raw",
    safety_status: "pass",
    performance_status: "pass",
    safety_metrics: {} as EvaluationRecord["safety_metrics"],
    performance_metrics: {} as EvaluationRecord["performance_metrics"],
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
  };
}

describe("nullable reliability", () => {
  it("does not chart missing latency as zero", () => {
    expect(
      extractLatencyTimeSeries(
        [unknownReliabilityRecord()],
        "total_latency_ms"
      )
    ).toEqual([]);
  });

  it("reports an unknown average when no observed latency exists", () => {
    expect(
      computeInvestigationSummary([unknownReliabilityRecord()]).avgLatencyMs
    ).toBeNull();
  });
});
