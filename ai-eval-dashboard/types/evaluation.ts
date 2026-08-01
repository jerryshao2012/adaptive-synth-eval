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
  target_latency_ms?: number | null;
  llm_latency_ms: number | null;
  llm_latency_status: "pass" | "warn" | "fail" | "unknown";
  guardrail_latency_ms: number | null;
  guardrail_latency_status: "pass" | "warn" | "fail" | "unknown";
  total_latency_ms: number | null;
  total_latency_status: "pass" | "warn" | "fail" | "unknown";
  availability: number | null;
  availability_status: "pass" | "warn" | "fail" | "unknown";
  availability_evidence?: string;
  trace_error_count?: number;
  tool_error_count?: number;
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
  recipe_id?: string;
  profile_period_id?: string;
  profile_period_instance_id?: string;
  profile_period_start?: string;
  profile_period_end?: string;
  conversation_mode?: string;
  behavior_mode?: string;
  synthetic_slot?: number;
  synthetic_day?: string;
  scenario_id?: string;
  adversarial_scenario_id?: string;
  persona_id?: string;
  // Optional metadata from the evaluation pipeline
  scenario?: string;
  persona?: string;
  attack_category?: string;
  // Triggered sampling metadata
  capture_events?: Array<{
    trigger_id: string;
    source: string;
    severity: string;
    reason: string;
  }>;
  selection_provenance?: Array<Record<string, unknown>>;
  selected_for_monitoring?: boolean;
  evaluation_runtime?: {
    elapsed_ms: number;
    status: "pass" | "warn" | "fail";
  };
}

export interface ProfilePeriod {
  instanceId: string;
  periodId: string;
  start: string;
  end: string;
  conversationMode: string;
  behaviorMode: string;
  plannedConversations: number;
  syntheticDay?: string;
}

export interface EvaluationsResponse {
  evaluations: EvaluationRecord[];
  profilePeriods: ProfilePeriod[];
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
  // Triggered sampling metrics (populated when samplingStrategy === "triggered")
  triggerMetrics?: {
    triggersDetected: number;
    rowsPromoted: number;
    budgetUsed: number;
    budgetAvailable: number;
    budgetDrops: number;
    deduplicatedContext: number;
    pendingLookahead: number;
    policyFingerprint?: string;
  };
}

export type MonitoringAction = "start" | "continue" | "reevaluate";

export type SamplingStrategy = "all" | "random" | "systematic" | "triggered";

export interface EvalRunParameters {
  samplingStrategy: SamplingStrategy;
  sampleSize: number;
  intervalMinutes: number;
  maxWindows: number | null;
  // Triggered sampling strategy parameters
  triggeredLookback?: number;
  triggeredLookahead?: number;
  triggerPolicyFingerprint?: string;
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
  | "full-run"
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

// ---- Reusable Golden Dataset Types (schema v2) ----

export type GoldenMetricKey =
  | "toxicity"
  | "bias_fairness"
  | "robustness"
  | "compliance"
  | "relevance"
  | "groundedness"
  | "correctness"
  | "completeness"
  | "style"
  | "precision";

export interface GoldenExampleContent {
  userText: string;
  responseText: string;
  conversationContext?: string;
  referenceContext?: string;
  referenceAnswer?: string;
}

export interface GoldenSourceRef {
  runId: string;
  conversationId: string;
  turnId: string;
  reviewId: string;
  reviewerId: string;
  reviewedAt: string;
  evaluationFingerprint?: string;
}

export interface GoldenReviewSnapshot {
  reviewStatus: "approved";
  overallStatus: MetricScoreStatus;
  safetyScores: HumanReview["safetyScores"];
  performanceScores: HumanReview["performanceScores"];
  notes: string;
  flags: HumanReview["flags"];
}

export interface GoldenExample {
  schemaVersion: 2;
  exampleId: string;
  contentFingerprint: string;
  content: GoldenExampleContent;
  sourceRefs: GoldenSourceRef[];
  reviewSnapshot: GoldenReviewSnapshot;
  tags: string[];
  similarExampleIds: string[];
  createdAt: string;
  updatedAt: string;
}

export interface GoldenAnnotation {
  expectedStatus: MetricScoreStatus;
  expectedScore?: number;
  rationale: string;
  reviewerId: string;
  reviewedAt: string;
}

export interface GoldenMembership {
  exampleId: string;
  annotations: Partial<Record<GoldenMetricKey, GoldenAnnotation>>;
  weight: number;
  notes: string;
  addedAt: string;
  updatedAt: string;
}

export interface GoldenCollection {
  schemaVersion: 2;
  collectionId: string;
  name: string;
  description: string;
  dimensions: GoldenMetricKey[];
  tags: string[];
  status: "draft" | "published" | "archived";
  revision: number;
  memberships: GoldenMembership[];
  latestPublishedVersion?: string;
  latestPublishedAt?: string;
  lastPublishedFingerprint?: string;
  legacyDatasetId?: string;
  createdAt: string;
  updatedAt: string;
}

export interface GoldenVersionRecord {
  exampleId: string;
  contentFingerprint: string;
  content: GoldenExampleContent;
  sourceRefs: GoldenSourceRef[];
  tags: string[];
  annotations: Partial<Record<GoldenMetricKey, GoldenAnnotation>>;
  weight: number;
  notes: string;
}

export interface GoldenDatasetVersion {
  schemaVersion: 2;
  versionId: string;
  collectionId: string;
  collectionName: string;
  version: string;
  dimensions: GoldenMetricKey[];
  tags: string[];
  manifestFingerprint: string;
  records: GoldenVersionRecord[];
  publisherId: string;
  publishedAt: string;
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
  avgLatencyMs: number | null;
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
  latencyMs: number | null;
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
