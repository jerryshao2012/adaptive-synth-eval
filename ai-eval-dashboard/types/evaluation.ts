// Metric evaluation record matching the backend API response schema.
// Mirrors the eval_engine.py run_monitoring() output + AI Eval Framework MetricValueVersioned.

export interface MetricValue {
  score: number; // 0.0–1.0
  percent: number; // 0–100
  status: "pass" | "warn" | "fail";
  detail: string;
  reason?: string;
  version?: string; // from MetricValueVersioned
  metadata?: {
    policy_version?: string;
    value_object_version?: string;
    value_object_type?: string;
  };
}

export interface SafetyMetrics {
  toxicity: MetricValue;
  bias_fairness: MetricValue;
  robustness: MetricValue;
  compliance: MetricValue;
}

export interface PerformanceMetrics {
  relevance: MetricValue;
  groundedness: MetricValue;
  correctness: MetricValue;
  completeness: MetricValue;
  style: MetricValue;
  precision: MetricValue;
}

export interface SystemReliability {
  llm_latency_ms: number;
  llm_latency_status: "pass" | "warn" | "fail";
  guardrail_latency_ms: number;
  guardrail_latency_status: "pass" | "warn" | "fail";
  total_latency_ms: number;
  total_latency_status: "pass" | "warn" | "fail";
  availability: number;
  availability_status: "pass" | "warn" | "fail";
}

export interface EvaluationRecord {
  timestamp: string; // ISO 8601
  turn_id: string;
  user_text: string;
  response_text: string;
  variant: "raw" | "delivered" | "monitoring";
  safety_status: "pass" | "warn" | "fail";
  performance_status: "pass" | "warn" | "fail";
  safety_metrics: SafetyMetrics;
  performance_metrics: PerformanceMetrics;
  system_reliability: SystemReliability;
  run_id?: string;
  conversation_id?: string;
  metric_version?: string;
  threshold_version?: string;
  sample_window_id?: number;
  source_line_index?: number;
}

export interface EvaluationsResponse {
  evaluations: EvaluationRecord[];
  total: number;
  from: string;
  to: string;
}

export interface BatchEvalStatus {
  running: boolean;
  progress?: {
    completed: number;
    total: number;
  };
  started_at?: string;
}

export interface RunSummary {
  runId: string;
  mode: string;
  monitoringStatus: "not_started" | "queued" | "in_progress" | "completed";
  startedAt?: string;
  updatedAt?: string;
  completedAt?: string;
  progress: {
    completed: number;
    total: number;
    percent: number;
  };
  metricVersion?: string;
  thresholdVersion?: string;
  hasMonitoringState: boolean;
  hasMonitoringScores: boolean;
  canStart: boolean;
  canContinue: boolean;
}

export interface MonitoringRunStatus {
  runId: string;
  monitoringStatus: "not_started" | "queued" | "in_progress" | "completed";
  progress: {
    completed: number;
    total: number;
    percent: number;
  };
  metricVersion?: string;
  thresholdVersion?: string;
  progressMarkdown: string | null;
  state: Record<string, unknown> | null;
  hasMonitoringScores: boolean;
  updatedAt?: string;
}

export interface EvalRunParameters {
  sampleSize: number;
  intervalMinutes: number;
  metricVersion: string;
  thresholdVersion: string;
}

export interface MonitoringStartRequest {
  runId: string;
  sampleSize?: number;
  intervalMinutes?: number;
  metricVersion: string;
  thresholdVersion?: string;
  action: "start" | "continue";
}

export interface MonitoringStartResponse {
  runId: string;
  started: boolean;
  command: string;
  monitoringStatus: "queued" | "in_progress";
}

// Per-metric threshold configuration
export interface MetricThreshold {
  metricKey: string;
  label: string;
  warnBelow: number;
  failBelow: number;
}

// Time period selection
export type TimePeriodPreset =
  | "this-week"
  | "this-month"
  | "this-quarter"
  | "last-7-days"
  | "last-30-days"
  | "last-90-days";
