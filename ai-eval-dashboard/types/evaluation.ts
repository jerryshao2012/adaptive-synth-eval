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

export interface MetricPointIdentity {
  runId: string;
  conversationId?: string;
  turnId: string;
  timestamp: string;
  metricGroup: "safety" | "performance" | "reliability";
  metricKey: string;
}

export interface TraceDetailsResponse {
  point: MetricPointIdentity;
  evaluationRecord: EvaluationRecord | null;
  chatHistoryRecord: Record<string, unknown> | null;
  turnRecord: Record<string, unknown> | null;
  notFoundReason?: string;
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
  description: string;
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

// ---- HITL Review Types ----

export type MetricScoreStatus = "pass" | "warn" | "fail";

export interface HumanReview {
  reviewId: string;
  evaluationRecordId: string;
  runId: string;
  conversationId: string;
  turnId: string;
  reviewerId: string;
  reviewStatus: "draft" | "submitted" | "approved";

  safetyScores: Record<
    string,
    { aiScore: number; humanScore: number; status: MetricScoreStatus }
  >;
  performanceScores: Record<
    string,
    { aiScore: number; humanScore: number; status: MetricScoreStatus }
  >;

  overallStatus: MetricScoreStatus;
  notes: string;
  flags: Array<
    "disputed" | "needs_discussion" | "exemplar" | "reviewed_ok"
  >;
  reviewedAt: string;
  createdAt: string;
  updatedAt: string;
}

export interface ReviewQueueItem {
  runId: string;
  conversationId: string;
  turnId: string;
  userText: string;
  responseText: string;
  timestamp: string;
  safetyStatus: MetricScoreStatus;
  performanceStatus: MetricScoreStatus;
  avgAiScore: number;
  hasHumanReview: boolean;
  reviewStatus: "none" | "draft" | "submitted" | "approved" | null;
  flags: HumanReview["flags"];
  reviewedAt: string | null;
}

export interface ReviewQueueFilters {
  status?: MetricScoreStatus;
  metricKey?: string;
  metricMaxScore?: number;
  metricMinScore?: number;
  runId?: string;
  searchText?: string;
  disputedOnly?: boolean;
  unreviewedOnly?: boolean;
  page?: number;
  pageSize?: number;
  sortBy?: "timestamp" | "avgAiScore" | "safetyStatus" | "reviewStatus";
  sortOrder?: "asc" | "desc";
}

export interface ReviewQueueResponse {
  items: ReviewQueueItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ReviewStats {
  totalRecords: number;
  reviewedCount: number;
  draftCount: number;
  approvedCount: number;
  disputedCount: number;
  averageAgreement: number;
  perMetricAgreement: Record<string, number>;
}

export interface GoldenDataset {
  datasetId: string;
  name: string;
  version: string;
  status: "draft" | "published" | "archived";
  recordRefs: Array<{
    runId: string;
    conversationId: string;
    turnId: string;
  }>;
  filters: {
    runIds?: string[];
    metricKeys?: string[];
    minScore?: number;
  };
  stats: {
    totalRecords: number;
    reviewedCount: number;
    interRaterAgreement: number;
  };
  createdAt: string;
  updatedAt: string;
}
