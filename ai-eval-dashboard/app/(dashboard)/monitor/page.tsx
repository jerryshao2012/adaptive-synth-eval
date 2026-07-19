"use client";

import { useMemo, useState, useCallback, useRef } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Shield,
  Gauge,
  Activity,
  BarChart3,
} from "lucide-react";
import type {
  EvalRunParameters,
  EvaluationRecord,
  FailureGroup,
  MetricPointIdentity,
  MonitoringAction,
  MonitoringRunStatus,
  TimePeriodPreset,
} from "@/types/evaluation";
import { normalizeMonitoringParameters } from "@/lib/monitoring-config";
import { METRIC_THRESHOLDS, LATENCY_WARN_MS, LATENCY_FAIL_MS, LATENCY_DESCRIPTIONS, AVAILABILITY_DESCRIPTION } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import { getTimePeriod } from "@/lib/time-periods";
import {
  computeKpiSummary,
  extractMetricTimeSeries,
  extractLatencyTimeSeries,
  computeChartSummary,
} from "@/lib/aggregation";
import {
  computeInvestigationSummary,
  rankFailedMetrics,
} from "@/lib/verdict";
import {
  useEvaluations,
  useMonitoringStatus,
  usePreviousPeriodEvaluations,
  useRunList,
  useStartMonitoring,
  useTraceDetails,
} from "@/hooks/use-evaluations";

// New investigation workbench components
import { RunSelectorHeader } from "@/components/dashboard/run-selector-header";
import { EvaluationLogPanel } from "@/components/dashboard/evaluation-log-panel";
import { EvaluationConfigDialog } from "@/components/dashboard/evaluation-config-dialog";
import { InvestigationSummaryCard } from "@/components/dashboard/investigation-summary";
import { FailureAnalysis } from "@/components/dashboard/failure-analysis";
import { ConversationQueue } from "@/components/dashboard/conversation-queue";

// Existing components (kept for charts)
import { KpiCard } from "@/components/dashboard/kpi-card";
import ChartSummaryBar, { ChartCard } from "@/components/dashboard/chart-card";
import { MetricLineChart } from "@/components/dashboard/metric-line-chart";
import { EmptyState, ErrorCard } from "@/components/shared/empty-state";
import { TraceDrawer } from "@/components/dashboard/trace-drawer";

// ---- Constants ----
const SAFETY_METRICS = ["toxicity", "bias_fairness", "robustness", "compliance"] as const;
const PERF_METRICS = [
  "relevance",
  "groundedness",
  "correctness",
  "completeness",
  "style",
  "precision",
] as const;

const LATENCY_METRICS = [
  { key: "total_latency_ms" as const, label: "Total Latency", fullWidth: true },
  { key: "llm_latency_ms" as const, label: "LLM Latency", fullWidth: false },
  { key: "guardrail_latency_ms" as const, label: "Guardrail Latency", fullWidth: false },
];

function filterEvaluationsByPeriod(
  rows: EvaluationRecord[],
  preset: TimePeriodPreset
): EvaluationRecord[] {
  const { from, to } = getTimePeriod(preset);
  const fromMs = from.getTime();
  const toMs = to.getTime();
  return rows.filter((row) => {
    const ts = new Date(row.timestamp).getTime();
    return Number.isFinite(ts) && ts >= fromMs && ts <= toMs;
  });
}

interface AcceptedLaunchOverlay {
  key: string;
  runId: string;
  baselineReady: boolean;
  baselineUpdatedAtMs: number | null;
}

function statusUpdatedAtMs(
  status: MonitoringRunStatus | undefined
): number | null {
  if (!status) return null;

  const stateUpdatedAt = status.state?.updated_at;
  const candidates = [
    status.updatedAt,
    typeof stateUpdatedAt === "string" ? stateUpdatedAt : undefined,
  ];
  const timestamps = candidates
    .map((value) => (value ? Date.parse(value) : Number.NaN))
    .filter(Number.isFinite);
  return timestamps.length > 0 ? Math.max(...timestamps) : null;
}

function hasPostAcceptanceStatusEvidence(
  overlay: AcceptedLaunchOverlay,
  status: MonitoringRunStatus | undefined
): boolean {
  if (!status || status.runId !== overlay.runId) return false;
  if (
    status.monitoringStatus === "queued" ||
    status.monitoringStatus === "in_progress"
  ) {
    return true;
  }

  const updatedAtMs = statusUpdatedAtMs(status);
  return (
    overlay.baselineReady &&
    overlay.baselineUpdatedAtMs !== null &&
    updatedAtMs !== null &&
    updatedAtMs > overlay.baselineUpdatedAtMs
  );
}

export default function DashboardPage() {
  // ---- State ----
  const [globalPeriod] = useState<TimePeriodPreset>("last-90-days");
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [chartPeriods, setChartPeriods] = useState<Record<string, TimePeriodPreset>>({});
  const [selectedPoint, setSelectedPoint] = useState<MetricPointIdentity | null>(null);

  // Failure analysis group filter state
  const [activeGroupFilter, setActiveGroupFilter] = useState<FailureGroup["groupType"] | null>(null);
  const [activeGroupKey, setActiveGroupKey] = useState<string | null>(null);

  const [launchIntent, setLaunchIntent] = useState<{
    action: MonitoringAction;
    runId: string;
    initialValues: EvalRunParameters;
  } | null>(null);
  const [acceptedLaunches, setAcceptedLaunches] = useState<
    Record<string, AcceptedLaunchOverlay>
  >({});
  const pendingLaunchRef = useRef<string | null>(null);
  const [pendingLaunchKey, setPendingLaunchKey] = useState<string | null>(null);

  // ---- Data fetching ----
  const {
    data: runSummaries = [],
    isLoading: isRunsLoading,
    refetch: refetchRuns,
  } = useRunList();

  const activeRunId = useMemo(() => {
    if (selectedRunId && runSummaries.some((run) => run.runId === selectedRunId)) {
      return selectedRunId;
    }
    return runSummaries[0]?.runId || "";
  }, [runSummaries, selectedRunId]);

  const selectedRun = useMemo(
    () => runSummaries.find((run) => run.runId === activeRunId) || null,
    [activeRunId, runSummaries]
  );

  const {
    data: monitoringStatus,
    prepareRefreshAfterLaunch: prepareMonitoringStatusRefreshAfterLaunch,
    refetch: refetchMonitoringStatus,
  } = useMonitoringStatus(activeRunId || undefined);

  const {
    data: traceDetails,
    isLoading: isTraceLoading,
    isFetching: isTraceFetching,
    error: traceError,
  } = useTraceDetails(selectedPoint);

  const startMonitoring = useStartMonitoring();
  const canLoadEvaluations = Boolean(activeRunId);

  const {
    data: evaluations,
    isLoading,
    isError,
    error,
    refetch,
  } = useEvaluations(
    "last-90-days",
    activeRunId || undefined,
    canLoadEvaluations
  );
  const { data: previousEvaluations } =
    usePreviousPeriodEvaluations(
      globalPeriod,
      activeRunId || undefined,
      canLoadEvaluations
    );

  // ---- Actions ----
  const acceptedLaunch = acceptedLaunches[activeRunId] ?? null;
  const retainedAcceptedLaunch =
    acceptedLaunch &&
    !hasPostAcceptanceStatusEvidence(acceptedLaunch, monitoringStatus)
      ? acceptedLaunch
      : null;

  const displayedMonitoringStatus = useMemo<
    MonitoringRunStatus | undefined
  >(() => {
    if (
      !retainedAcceptedLaunch ||
      retainedAcceptedLaunch.runId !== activeRunId
    ) {
      return monitoringStatus;
    }

    return {
      runId: retainedAcceptedLaunch.runId,
      monitoringStatus: "queued",
      progress:
        monitoringStatus?.progress ??
        selectedRun?.progress ?? { completed: 0, total: 0, percent: 0 },
      evaluationFingerprint: monitoringStatus?.evaluationFingerprint,
      progressMarkdown: monitoringStatus?.progressMarkdown ?? null,
      state: monitoringStatus?.state ?? null,
      hasMonitoringScores:
        monitoringStatus?.hasMonitoringScores ??
        selectedRun?.hasMonitoringScores ??
        false,
      updatedAt: monitoringStatus?.updatedAt,
    };
  }, [activeRunId, monitoringStatus, retainedAcceptedLaunch, selectedRun]);

  const handleLaunchIntent = useCallback(
    (intent: { action: MonitoringAction; runId: string }) => {
      const needsSavedParameters = intent.action !== "start";
      const requiredStatus =
        intent.action === "continue"
          ? "incomplete"
          : intent.action === "reevaluate"
            ? "completed"
            : "not_started";
      const hasMatchingSavedParameters =
        monitoringStatus?.runId === intent.runId &&
        monitoringStatus.monitoringStatus === requiredStatus &&
        monitoringStatus.state !== null;

      if (needsSavedParameters && !hasMatchingSavedParameters) {
        return;
      }

      setLaunchIntent({
        ...intent,
        initialValues: normalizeMonitoringParameters(
          needsSavedParameters ? monitoringStatus?.state : null
        ),
      });
    },
    [monitoringStatus]
  );

  const submitMonitoringLaunch = useCallback(
    async (parameters: EvalRunParameters) => {
      if (!launchIntent) {
        throw new Error("No evaluation launch is selected.");
      }

      const launchKey = `${launchIntent.action}:${launchIntent.runId}`;
      if (pendingLaunchRef.current !== null) {
        throw new Error("An evaluation launch is already being submitted.");
      }

      pendingLaunchRef.current = launchKey;
      setPendingLaunchKey(launchKey);

      try {
        await startMonitoring.mutateAsync({
          runId: launchIntent.runId,
          action: launchIntent.action,
          ...parameters,
        });
        const acceptedOverlay: AcceptedLaunchOverlay = {
          key: launchKey,
          runId: launchIntent.runId,
          baselineReady: false,
          baselineUpdatedAtMs: null,
        };
        setAcceptedLaunches((current) => ({
          ...current,
          [launchIntent.runId]: acceptedOverlay,
        }));
        setLaunchIntent(null);
        const postAcceptanceStatusRefresh =
          prepareMonitoringStatusRefreshAfterLaunch().then(
            async ({ baseline, result }) => {
              const preparedOverlay: AcceptedLaunchOverlay = {
                ...acceptedOverlay,
                baselineReady: true,
                baselineUpdatedAtMs: statusUpdatedAtMs(baseline),
              };
              setAcceptedLaunches((current) =>
                current[launchIntent.runId]?.key === launchKey
                  ? {
                      ...current,
                      [launchIntent.runId]: preparedOverlay,
                    }
                  : current
              );

              const refreshedStatus = await result;
              setAcceptedLaunches((current) => {
                const overlay = current[launchIntent.runId];
                if (
                  !overlay ||
                  overlay.key !== launchKey ||
                  refreshedStatus.isSuccess !== true ||
                  refreshedStatus.data?.runId !== launchIntent.runId
                ) {
                  return current;
                }

                const next = { ...current };
                delete next[launchIntent.runId];
                return next;
              });
            }
          );
        void Promise.allSettled([
          refetchRuns(),
          postAcceptanceStatusRefresh,
          refetch(),
        ]);
      } finally {
        if (pendingLaunchRef.current === launchKey) {
          pendingLaunchRef.current = null;
        }
        setPendingLaunchKey((current) =>
          current === launchKey ? null : current
        );
      }
    },
    [
      launchIntent,
      prepareMonitoringStatusRefreshAfterLaunch,
      refetch,
      refetchRuns,
      startMonitoring,
    ]
  );

  function refreshAll() {
    void refetchRuns();
    if (activeRunId) void refetchMonitoringStatus();
    void refetch();
  }

  // ---- Computed data ----
  const kpiEvaluations = useMemo(
    () => filterEvaluationsByPeriod(evaluations || [], globalPeriod),
    [evaluations, globalPeriod]
  );

  const kpi = useMemo(
    () => computeKpiSummary(kpiEvaluations, previousEvaluations || []),
    [kpiEvaluations, previousEvaluations]
  );

  // Investigation summary
  const investigationSummary = useMemo(
    () => {
      if (!evaluations || evaluations.length === 0) return null;
      return computeInvestigationSummary(evaluations, previousEvaluations);
    },
    [evaluations, previousEvaluations]
  );

  // Failed metric rankings
  const failedMetrics = useMemo(
    () => {
      if (!evaluations || evaluations.length === 0) return [];
      return rankFailedMetrics(evaluations);
    },
    [evaluations]
  );

  // Group filter handlers
  const handleGroupSelect = useCallback(
    (groupType: FailureGroup["groupType"], groupKey: string) => {
      if (activeGroupFilter === groupType && activeGroupKey === groupKey) {
        // Toggle off
        setActiveGroupFilter(null);
        setActiveGroupKey(null);
      } else {
        setActiveGroupFilter(groupType);
        setActiveGroupKey(groupKey);
      }
    },
    [activeGroupFilter, activeGroupKey]
  );

  const handleClearGroupFilter = useCallback(() => {
    setActiveGroupFilter(null);
    setActiveGroupKey(null);
  }, []);

  // Per-chart period resolution
  function getChartPeriod(chartKey: string): TimePeriodPreset {
    return chartPeriods[chartKey] || globalPeriod;
  }

  const hasData = Boolean(evaluations && evaluations.length > 0);
  const runStatus =
    displayedMonitoringStatus?.monitoringStatus ??
    selectedRun?.monitoringStatus;

  // ---- Chart render helpers (kept from original) ----
  function renderSafetyCharts() {
    if (!evaluations) return null;
    return SAFETY_METRICS.map((key, i) => {
      const period = getChartPeriod(key);
      const scopedEvaluations = filterEvaluationsByPeriod(evaluations, period);
      const threshold = METRIC_THRESHOLDS[key];
      const points = extractMetricTimeSeries(scopedEvaluations, "safety", key, activeRunId);
      const summary = computeChartSummary(points);
      const latest = points[points.length - 1];

      return (
        <ChartCard
          key={key}
          title={threshold.label}
          tooltip={threshold.description}
          status={latest?.status}
          latestValue={latest ? `${latest.value}%` : undefined}
          period={period}
          onPeriodChange={(p) =>
            setChartPeriods((prev) => ({ ...prev, [key]: p }))
          }
          isLoading={isLoading}
          colSpan={i === 0 ? "full" : "half"}
          summary={
            <ChartSummaryBar
              avg={summary.avg}
              min={summary.min}
              max={summary.max}
              warnThreshold={threshold.warnBelow}
              failThreshold={threshold.failBelow}
              valueFormatter={(v) => `${v}%`}
            />
          }
          onViewDetails={
            latest?.pointIdentity
              ? () => setSelectedPoint(latest.pointIdentity || null)
              : undefined
          }
        >
          <MetricLineChart
            data={points}
            period={period}
            warnThreshold={threshold.warnBelow}
            failThreshold={threshold.failBelow}
            valueFormatter={(v) => `${v}%`}
            onPointClick={(point) => setSelectedPoint(point)}
          />
        </ChartCard>
      );
    });
  }

  function renderPerformanceCharts() {
    if (!evaluations) return null;
    return PERF_METRICS.map((key, i) => {
      const period = getChartPeriod(key);
      const scopedEvaluations = filterEvaluationsByPeriod(evaluations, period);
      const threshold = METRIC_THRESHOLDS[key];
      const points = extractMetricTimeSeries(scopedEvaluations, "performance", key, activeRunId);
      const summary = computeChartSummary(points);
      const latest = points[points.length - 1];

      return (
        <ChartCard
          key={key}
          title={threshold.label}
          tooltip={threshold.description}
          status={latest?.status}
          latestValue={latest ? `${latest.value}%` : undefined}
          period={period}
          onPeriodChange={(p) =>
            setChartPeriods((prev) => ({ ...prev, [key]: p }))
          }
          colSpan={i === 0 ? "full" : "half"}
          summary={
            <ChartSummaryBar
              avg={summary.avg}
              min={summary.min}
              max={summary.max}
              warnThreshold={threshold.warnBelow}
              failThreshold={threshold.failBelow}
              valueFormatter={(v) => `${v}%`}
            />
          }
          onViewDetails={
            latest?.pointIdentity
              ? () => setSelectedPoint(latest.pointIdentity || null)
              : undefined
          }
        >
          <MetricLineChart
            data={points}
            period={period}
            warnThreshold={threshold.warnBelow}
            failThreshold={threshold.failBelow}
            valueFormatter={(v) => `${v}%`}
            onPointClick={(point) => setSelectedPoint(point)}
          />
        </ChartCard>
      );
    });
  }

  function renderReliabilityCharts() {
    if (!evaluations) return null;
    return (
      <>
        {LATENCY_METRICS.map(({ key, label, fullWidth }) => {
          const period = getChartPeriod(key);
          const scopedEvaluations = filterEvaluationsByPeriod(evaluations, period);
          const points = extractLatencyTimeSeries(scopedEvaluations, key, activeRunId);
          const summary = computeChartSummary(points);
          const latest = points[points.length - 1];

          return (
            <ChartCard
              key={key}
              title={label}
              tooltip={LATENCY_DESCRIPTIONS[key] || `Latency in milliseconds. Warn > ${LATENCY_WARN_MS}ms, Fail > ${LATENCY_FAIL_MS}ms.`}
              status={latest?.status}
              latestValue={latest ? `${latest.value}ms` : undefined}
              period={period}
              onPeriodChange={(p) =>
                setChartPeriods((prev) => ({ ...prev, [key]: p }))
              }
              colSpan={fullWidth ? "full" : "half"}
              summary={
                <ChartSummaryBar
                  avg={summary.avg}
                  min={summary.min}
                  max={summary.max}
                  warnThreshold={LATENCY_WARN_MS}
                  failThreshold={LATENCY_FAIL_MS}
                  valueFormatter={(v) => `${v}ms`}
                />
              }
            >
              <MetricLineChart
                data={points}
                period={period}
                warnThreshold={LATENCY_WARN_MS}
                failThreshold={LATENCY_FAIL_MS}
                yDomain={[0, "auto"]}
                valueFormatter={(v) => `${v}ms`}
                onPointClick={(point) => setSelectedPoint(point)}
              />
            </ChartCard>
          );
        })}
        {/* Availability chart */}
        {(() => {
          const key = "availability";
          const period = getChartPeriod(key);
          const scopedEvaluations = filterEvaluationsByPeriod(evaluations || [], period);
          const points = scopedEvaluations
            .map((e) => ({
              timestamp: e.timestamp,
              value: e.system_reliability.availability * 100,
              status: e.system_reliability.availability_status,
              pointIdentity: {
                runId: e.run_id || activeRunId,
                conversationId: e.conversation_id,
                turnId: String(e.turn_id),
                timestamp: e.timestamp,
                metricGroup: "reliability" as const,
                metricKey: key,
              },
            }))
            .sort(
              (a, b) =>
                new Date(a.timestamp).getTime() -
                new Date(b.timestamp).getTime()
            );
          const summary = computeChartSummary(points);
          const latest = points[points.length - 1];

          return (
            <ChartCard
              key={key}
              title="Availability"
              tooltip={AVAILABILITY_DESCRIPTION}
              status={latest?.status}
              latestValue={latest ? `${latest.value}%` : undefined}
              period={period}
              onPeriodChange={(p) =>
                setChartPeriods((prev) => ({ ...prev, [key]: p }))
              }
              colSpan="half"
              summary={
                <ChartSummaryBar
                  avg={summary.avg}
                  min={summary.min}
                  max={summary.max}
                  warnThreshold={99}
                  failThreshold={95}
                  valueFormatter={(v) => `${v}%`}
                />
              }
            >
              <MetricLineChart
                data={points}
                period={period}
                warnThreshold={99}
                failThreshold={95}
                valueFormatter={(v) => `${v}%`}
                onPointClick={(point) => setSelectedPoint(point)}
              />
            </ChartCard>
          );
        })()}
      </>
    );
  }

  // ---- Main render ----
  return (
    <div className="monitor-layout flex flex-col min-h-full">
      <main className="flex-1 overflow-y-auto">
        <div
          className={cn(
            "monitor-content min-w-0 px-6 py-6 transition-[margin] duration-300 ease-out",
            selectedPoint && "monitor-content--right"
          )}
        >
          {/* ============================================
              1. RUN SELECTOR HEADER
              ============================================ */}
          {!isRunsLoading && runSummaries.length === 0 && (
            <EmptyState
              message="No run folders found under outputs/runs."
              suggestion="Generate a run first, then start monitoring from the dashboard."
            />
          )}

          {runSummaries.length > 0 && (
            <>
              <RunSelectorHeader
                selectedRun={selectedRun}
                monitoringStatus={displayedMonitoringStatus ?? null}
                runs={runSummaries}
                onSelectRun={setSelectedRunId}
                onLaunchIntent={handleLaunchIntent}
                pendingLaunchKey={
                  pendingLaunchKey ??
                  (retainedAcceptedLaunch?.runId === activeRunId
                    ? retainedAcceptedLaunch.key
                    : null)
                }
                onRefresh={refreshAll}
              />
              <EvaluationLogPanel
                runId={activeRunId}
                monitoringStatus={runStatus}
              />
            </>
          )}

          {/* Error state */}
          {isError && (
            <ErrorCard
              message={(error as Error)?.message || "Failed to load evaluation data."}
              onRetry={() => refetch()}
            />
          )}

          {/* ============================================
              2. INVESTIGATION SUMMARY
              ============================================ */}
          {runSummaries.length > 0 && !isError && (
            <InvestigationSummaryCard
              summary={investigationSummary}
              isLoading={isLoading}
              hasData={hasData}
              runStatus={runStatus}
            />
          )}

          {/* ============================================
              3. FAILURE ANALYSIS (when failures exist)
              ============================================ */}
          {hasData && !isLoading && failedMetrics.length > 0 && (
            <FailureAnalysis
              evaluations={evaluations!}
              failedMetrics={failedMetrics}
              activeGroupFilter={activeGroupFilter}
              activeGroupKey={activeGroupKey}
              onGroupSelect={handleGroupSelect}
              onClearGroupFilter={handleClearGroupFilter}
            />
          )}

          {/* ============================================
              4. FAILED CONVERSATION QUEUE
              ============================================ */}
          {hasData && !isLoading && (
            <ConversationQueue
              evaluations={evaluations!}
              activeRunId={activeRunId}
              onSelectConversation={(point) => setSelectedPoint(point)}
              groupFilter={
                activeGroupFilter && activeGroupKey
                  ? { groupType: activeGroupFilter, groupKey: activeGroupKey }
                  : null
              }
            />
          )}

          {/* Loading skeleton for sections 2-4 */}
          {isLoading && runSummaries.length > 0 && !isError && (
            <div className="space-y-4 mb-6">
              <Skeleton className="h-32 w-full rounded-lg" />
              <Skeleton className="h-48 w-full rounded-lg" />
            </div>
          )}

          {/* ============================================
              5. KPI CARDS (moved down)
              ============================================ */}
          {hasData && !isLoading && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <KpiCard
                label="Total Evaluations"
                value={kpi.totalEvaluations.toLocaleString()}
                trend={kpi.trendTotal}
                trendLabel="vs prev"
                icon={<Activity className="h-4 w-4" />}
              />
              <KpiCard
                label="Pass Rate"
                value={`${kpi.passRate}%`}
                trend={kpi.trendPassRate}
                trendLabel="vs prev"
                icon={<Shield className="h-4 w-4" />}
              />
              <KpiCard
                label="Fail Rate"
                value={`${kpi.failRate}%`}
                trend={kpi.trendFailRate}
                trendLabel="vs prev"
                icon={<Gauge className="h-4 w-4" />}
              />
              <KpiCard
                label="Avg Score"
                value={`${kpi.avgScore}/100`}
                trend={kpi.trendAvgScore}
                trendLabel="vs prev"
                icon={<BarChart3 className="h-4 w-4" />}
              />
            </div>
          )}

          {/* ============================================
              6. METRIC CHARTS (moved to end)
              ============================================ */}
          {hasData && !isLoading && (
            <Tabs defaultValue="safety" className="w-full">
              <TabsList className="mb-4">
                <TabsTrigger value="safety" className="text-sm">
                  <Shield className="h-4 w-4 mr-1.5" />
                  Safety Metrics
                </TabsTrigger>
                <TabsTrigger value="performance" className="text-sm">
                  <Activity className="h-4 w-4 mr-1.5" />
                  Performance Metrics
                </TabsTrigger>
                <TabsTrigger value="reliability" className="text-sm">
                  <Gauge className="h-4 w-4 mr-1.5" />
                  Reliability
                </TabsTrigger>
              </TabsList>

              <TabsContent value="safety">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {renderSafetyCharts()}
                </div>
              </TabsContent>

              <TabsContent value="performance">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {renderPerformanceCharts()}
                </div>
              </TabsContent>

              <TabsContent value="reliability">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {renderReliabilityCharts()}
                </div>
              </TabsContent>
            </Tabs>
          )}

          {/* Loading skeleton for charts */}
          {isLoading && runSummaries.length > 0 && !isError && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={i}
                  className={i === 0 ? "col-span-2" : "col-span-1"}
                >
                  <div className="rounded-lg border border-border bg-card p-4">
                    <Skeleton className="h-5 w-32 mb-4" />
                    <Skeleton className="h-50 w-full" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Empty state for no evaluation data */}
          {!isLoading && !isError && evaluations?.length === 0 && runSummaries.length > 0 && (
            <EmptyState
              message={
                selectedRun?.monitoringStatus === "completed"
                  ? "No evaluation data for this period."
                  : "Monitoring results are not complete for this run yet."
              }
              suggestion={
                selectedRun?.monitoringStatus === "completed"
                  ? "Try widening the time range or choose another run."
                  : "Start or continue evaluation from the run header, then refresh when rows have been scored."
              }
              onAction={refreshAll}
              actionLabel="Refresh"
            />
          )}
        </div>
      </main>

      {/* Trace Drawer (kept from original) */}
      <TraceDrawer
        open={Boolean(selectedPoint)}
        point={selectedPoint}
        trace={traceDetails}
        isLoading={isTraceLoading || isTraceFetching}
        errorMessage={traceError instanceof Error ? traceError.message : undefined}
        onClose={() => setSelectedPoint(null)}
      />

      {launchIntent && (
        <EvaluationConfigDialog
          open
          action={launchIntent.action}
          initialValues={launchIntent.initialValues}
          onOpenChange={(open) => {
            if (!open && pendingLaunchKey === null) {
              setLaunchIntent(null);
            }
          }}
          onSubmit={submitMonitoringLaunch}
        />
      )}
    </div>
  );
}
