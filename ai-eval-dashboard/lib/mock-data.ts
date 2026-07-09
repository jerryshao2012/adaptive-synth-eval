import type { EvaluationRecord, MetricValue } from "@/types/evaluation";

// Generate realistic mock evaluation data matching eval_engine.py schema.
// Each record has safety_metrics (4), performance_metrics (6), and system_reliability.

function randomScore(
  baseMean: number,
  variance: number
): { score: number; percent: number; status: "pass" | "warn" | "fail" } {
  // Gaussian-ish around baseMean
  const u = 1 - Math.random();
  const v = 1 - Math.random();
  const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  const raw = Math.max(0, Math.min(1, baseMean + z * variance));
  const percent = Math.round(raw * 100);
  const score = Math.round(raw * 1000) / 1000;

  let status: "pass" | "warn" | "fail" = "pass";
  if (percent < 40) status = "fail";
  else if (percent < 70) status = "warn";

  return { score, percent, status };
}

function makeMetric(
  name: string,
  baseMean: number,
  variance: number
): MetricValue {
  const { score, percent, status } = randomScore(baseMean, variance);
  return {
    score,
    percent,
    status,
    detail: `Mock ${name} evaluation result`,
    reason: "mock heuristics",
    version: "1.0",
    metadata: {
      policy_version: "1.0",
      value_object_version: "1.0",
      value_object_type: "metric_value_versioned",
    },
  };
}

const USER_TEXTS = [
  "What's my current balance?",
  "I need to transfer $500 to my savings account.",
  "Why was my card declined?",
  "How do I set up a recurring payment?",
  "What's the interest rate on my mortgage?",
  "Can you explain the fees on my last statement?",
  "I lost my credit card, what should I do?",
  "How long does a wire transfer take?",
];

const RESPONSE_TEXTS = [
  "Your current balance is $1,250.00. Is there anything else I can help with?",
  "I've initiated the $500 transfer to your savings account ending in 4321. The funds should be available within 1 business day.",
  "Your card was declined due to a suspected fraudulent transaction at 'Online Store XYZ'. Please verify if this was you.",
  "To set up a recurring payment, go to the 'Payments' tab, select 'AutoPay', and choose the account, amount, and frequency.",
  "Your mortgage rate is currently 4.25% APR. This is a fixed rate until March 2028.",
  "The $12.50 fee on your statement is the monthly maintenance fee. This fee is waived if you maintain a $1,500 minimum balance.",
  "I'm sorry to hear that. I've placed a temporary block on your card. You can order a replacement in the app under 'Cards' → 'Replace Card'.",
  "Wire transfers typically take 1-3 business days for domestic and 3-5 business days for international transfers.",
];

function pick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

export function generateMockEvaluations(
  from?: string,
  to?: string,
  limit = 100
): EvaluationRecord[] {
  const toDate = to ? new Date(to) : new Date();
  const fromDate = from ? new Date(from) : new Date(toDate.getTime() - 7 * 24 * 60 * 60 * 1000);
  const durationMs = toDate.getTime() - fromDate.getTime();
  const count = Math.min(limit, 500);

  const records: EvaluationRecord[] = [];

  for (let i = 0; i < count; i++) {
    const offset = Math.floor((i / count) * durationMs);
    const ts = new Date(fromDate.getTime() + offset);

    // Slowly drift scores over time to create a visible trend
    const drift = Math.sin(i / (count / 4)) * 0.05;

    const safety_status =
      Math.random() < 0.08 ? "warn" : Math.random() < 0.03 ? "fail" : "pass";
    const performance_status =
      Math.random() < 0.10 ? "warn" : Math.random() < 0.04 ? "fail" : "pass";

    const latencyBase = 800 + Math.random() * 3000;

    records.push({
      timestamp: ts.toISOString(),
      turn_id: `mock-${i.toString(16).padStart(8, "0")}`,
      user_text: pick(USER_TEXTS),
      response_text: pick(RESPONSE_TEXTS),
      variant: Math.random() < 0.7 ? "delivered" : "raw",
      safety_status: safety_status as "pass" | "warn" | "fail",
      performance_status: performance_status as "pass" | "warn" | "fail",
      safety_metrics: {
        toxicity: makeMetric("toxicity", 0.90 + drift, 0.08),
        bias_fairness: makeMetric("bias_fairness", 0.88 + drift, 0.07),
        robustness: makeMetric("robustness", 0.92 + drift, 0.06),
        compliance: makeMetric("compliance", 0.85 + drift, 0.10),
      },
      performance_metrics: {
        relevance: makeMetric("relevance", 0.82 + drift, 0.12),
        groundedness: makeMetric("groundedness", 0.78 + drift, 0.10),
        correctness: makeMetric("correctness", 0.75 + drift, 0.15),
        completeness: makeMetric("completeness", 0.70 + drift, 0.14),
        style: makeMetric("style", 0.65 + drift, 0.13),
        precision: makeMetric("precision", 0.80 + drift, 0.09),
      },
      system_reliability: {
        llm_latency_ms: Math.round(latencyBase + Math.random() * 2000),
        llm_latency_status:
          latencyBase > 8000 ? "fail" : latencyBase > 5000 ? "warn" : "pass",
        guardrail_latency_ms: Math.round(200 + Math.random() * 500),
        guardrail_latency_status: "pass",
        total_latency_ms: Math.round(latencyBase + 200 + Math.random() * 2500),
        total_latency_status:
          latencyBase > 8000 ? "fail" : latencyBase > 5000 ? "warn" : "pass",
        availability: Math.random() < 0.02 ? 0 : 1,
        availability_status: Math.random() < 0.02 ? "fail" : "pass",
      },
    });
  }

  return records.sort(
    (a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );
}
