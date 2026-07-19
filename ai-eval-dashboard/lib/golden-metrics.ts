import type { GoldenMetricKey } from "@/types/evaluation";

export const GOLDEN_METRIC_KEYS: readonly GoldenMetricKey[] = [
  "toxicity",
  "bias_fairness",
  "robustness",
  "compliance",
  "relevance",
  "groundedness",
  "correctness",
  "completeness",
  "style",
  "precision",
] as const;
