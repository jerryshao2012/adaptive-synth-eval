// Metric evaluation record matching the backend API response schema.
// Mirrors the eval_engine.py run_monitoring() output + AI Eval Framework MetricValueVersioned.

export interface ValueVersions {
  evaluation_fingerprint: string;
  evaluation_group: string;
  generated_at: string;
  resolved_model: {
    provider: string;
    deployment: string;
  };
  prompt_hash: string;
  metrics: Record<string, { policy_fingerprint: string }>;
}

export interface MetricValue {
  score: number; // 0.0–1.0
  percent: number; // 0–100
  status: "pass" | "warn" | "fail";
  detail: string;
  reason?: string;
  version?: string;
  metadata?: {
    policy_version?: string;
    value_object_version?: string;
    value_object_type?: string;
    [key: string]: unknown;
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
  value_versions?: ValueVersions;
  sample_window_id?: number;
  source_line_index?: number;
  // Optional metadata from the evaluation pipeline
  scenario?: string;
  persona?: string;
  attack_category?: string;
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
  monitoringStatus: "not_started" | "queued" | "in_progress" | "incomplete" | "completed";
  startedAt?: string;
  updatedAt?: string;
  completedAt?: string;
  progress: {
    completed: number;
    total: number;
    percent: number;
  };
  evaluationFingerprint?: string;
  hasMonitoringState: boolean;
  hasMonitoringScores: boolean;
  canStart: boolean;
  canContinue: boolean;
  canReevaluate: boolean;
}

export interface MonitoringRunStatus {
  runId: string;
  monitoringStatus: "not_started" | "queued" | "in_progress" | "incomplete" | "completed";
  progress: {
    completed: number;
    total: number;
    percent: number;
  };
  evaluationFingerprint?: string;
  progressMarkdown: string | null;
  state: Record<string, unknown> | null;
  hasMonitoringScores: boolean;
  updatedAt?: string;
}

export type MonitoringAction = "start" | "continue" | "reevaluate";

export type SamplingStrategy = "all" | "random" | "systematic";

export interface EvalRunParameters {
  samplingStrategy: SamplingStrategy;
  sampleSize: number;
  intervalMinutes: number;
  maxWindows: number | null;
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

export interface MonitoringStartRequest extends EvalRunParameters {
  runId: string;
  action: MonitoringAction;
}

export interface MonitoringStartResponse {
  runId: string;
  started: boolean;
  command: string;
  monitoringStatus: "queued" | "in_progress";
}

export interface MonitoringLogResponse {
  runId: string;
  content: string;
  size: number;
  truncated: boolean;
  updatedAt?: string;
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

// ---- Investigation Workbench Types ----

export type VerdictLevel = "healthy" | "needs_review" | "failed";

export interface InvestigationSummary {
  verdict: VerdictLevel;
  verdictLabel: string;
  verdictDescription: string;
  totalEvaluations: number;
  failedTurnCount: number;
  warnTurnCount: number;
  passRate: number;
  failRate: number;
  worstPerformingMetric: {
    metricKey: string;
    label: string;
    failCount: number;
    avgScore: number;
  } | null;
  avgLatencyMs: number;
  comparisonWithPrior: {
    passRateChange: number;
    failRateChange: number;
    avgScoreChange: number;
    hasPriorData: boolean;
  } | null;
}

export interface FailureGroup {
  groupKey: string;
  groupLabel: string;
  groupType: "scenario" | "persona" | "attack_category" | "response_status" | "metric";
  count: number;
  failCount: number;
  severity: "critical" | "high" | "medium" | "low";
  items: string[]; // item identifiers within the group
  representativeMetric?: string;
}

export interface FailedMetricRanking {
  metricKey: string;
  label: string;
  metricGroup: "safety" | "performance" | "reliability";
  failCount: number;
  warnCount: number;
  totalCount: number;
  failRate: number;
  severity: "critical" | "high" | "medium" | "low";
  avgScore: number;
}

export interface ConversationQueueItem {
  runId: string;
  conversationId: string;
  turnId: string;
  timestamp: string;
  userText: string;
  responseText: string;
  safetyStatus: MetricScoreStatus;
  performanceStatus: MetricScoreStatus;
  overallSeverity: "critical" | "high" | "medium" | "low";
  failedMetrics: string[];
  safetyScores: Record<string, number>;
  performanceScores: Record<string, number>;
  latencyMs: number;
  scenario?: string;
  persona?: string;
  attackCategory?: string;
}

export interface ConversationQueueFilters {
  searchText?: string;
  outcome?: "safety" | "performance" | "reliability" | "all";
  severity?: "critical" | "high" | "medium" | "low" | "all";
  groupFilter?: {
    groupType: FailureGroup["groupType"];
    groupKey: string;
  };
  sortBy?: "severity" | "recency" | "score";
  page?: number;
  pageSize?: number;
}

export interface ConversationQueueResponse {
  items: ConversationQueueItem[];
  total: number;
  page: number;
  pageSize: number;
  availableGroups: FailureGroup[];
}

// Artifact validation result from server boundary
export interface ArtifactValidation {
  runId: string;
  isValid: boolean;
  issues: ArtifactIssue[];
  artifactFreshness: {
    monitoringScores: { exists: boolean; lastModified?: string; recordCount: number };
    monitoringState: { exists: boolean; lastModified?: string };
    runState: { exists: boolean };
    runSummary: { exists: boolean };
  };
}

export interface ArtifactIssue {
  artifact: string;
  severity: "error" | "warning";
  message: string;
  details?: string;
}
