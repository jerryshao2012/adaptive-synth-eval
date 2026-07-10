"use client";

import { useMemo, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Shield,
  Gauge,
  Activity,
  BarChart3,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { EvalRunParameters, EvaluationRecord, TimePeriodPreset } from "@/types/evaluation";
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
  useEvaluations,
  useMonitoringStatus,
  usePreviousPeriodEvaluations,
  useRunList,
  useStartMonitoring,
  useTraceDetails,
} from "@/hooks/use-evaluations";

import { KpiCard } from "@/components/dashboard/kpi-card";
import { ChartCard, ChartSummaryBar } from "@/components/dashboard/chart-card";
import { MetricLineChart } from "@/components/dashboard/metric-line-chart";
import { RunThreadList } from "@/components/dashboard/run-thread-list";
import { EmptyState, ErrorCard } from "@/components/shared/empty-state";
import { TraceDrawer } from "@/components/dashboard/trace-drawer";
import type { MetricPointIdentity } from "@/types/evaluation";

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

const DEFAULT_MONITORING_CONFIG: EvalRunParameters = {
  sampleSize: 1000,
  intervalMinutes: 30,
  metricVersion: "v1",
  thresholdVersion: "v1",
};

function monitoringStatusLabel(status: "not_started" | "queued" | "in_progress" | "completed" | undefined): string {
  switch (status) {
    case "completed":
      return "Completed";
    case "in_progress":
      return "In Progress";
    case "queued":
      return "Queued";
    default:
      return "Not Started";
  }
}

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

export default function DashboardPage() {
  const [globalPeriod] = useState<TimePeriodPreset>("this-week");
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [isThreadPanelOpen, setIsThreadPanelOpen] = useState(false);
  const [globalEvalDefaults, setGlobalEvalDefaults] =
    useState<EvalRunParameters>(DEFAULT_MONITORING_CONFIG);
  const [threadParamOverrides, setThreadParamOverrides] =
    useState<Record<string, Partial<EvalRunParameters>>>({});
  const [expandedOverrideRunId, setExpandedOverrideRunId] = useState<string | null>(null);
  const [pendingActionRunId, setPendingActionRunId] = useState<string | undefined>(undefined);
  const [chartPeriods, setChartPeriods] = useState<
    Record<string, TimePeriodPreset>
  >({});
  const [selectedPoint, setSelectedPoint] = useState<MetricPointIdentity | null>(null);

  const {
    data: runSummaries = [],
    isLoading: isRunsLoading,
    refetch: refetchRuns,
  } = useRunList();

  const activeRunId = useMemo(() => {
    if (
      selectedRunId &&
      runSummaries.some((run) => run.runId === selectedRunId)
    ) {
      return selectedRunId;
    }
    return runSummaries[0]?.runId || "";
  }, [runSummaries, selectedRunId]);

  const selectedRun = useMemo(
    () => runSummaries.find((run) => run.runId === activeRunId) || null,
    [activeRunId, runSummaries]
  );
  const hasLeftPanel = isThreadPanelOpen && runSummaries.length > 0;

  const {
    data: monitoringStatus,
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
  } = useEvaluations("last-90-days", activeRunId || undefined, canLoadEvaluations);
  const { data: previousEvaluations } =
    usePreviousPeriodEvaluations(globalPeriod, activeRunId || undefined, canLoadEvaluations);

  async function handleMonitoringAction(
    runId: string,
    action: "start" | "continue"
  ) {
    if (!runId) {
      return;
    }

    setPendingActionRunId(runId);
    setSelectedRunId(runId);

    const run = runSummaries.find((item) => item.runId === runId) || null;
    const override = threadParamOverrides[runId] || {};
    const metricVersion =
      override.metricVersion ||
      monitoringStatus?.metricVersion ||
      run?.metricVersion ||
      globalEvalDefaults.metricVersion;
    const thresholdVersion =
      override.thresholdVersion ||
      monitoringStatus?.thresholdVersion ||
      run?.thresholdVersion ||
      globalEvalDefaults.thresholdVersion;

    const sampleSize = Number(override.sampleSize ?? globalEvalDefaults.sampleSize);
    const intervalMinutes = Number(
      override.intervalMinutes ?? globalEvalDefaults.intervalMinutes
    );

    try {
      await startMonitoring.mutateAsync({
        runId,
        action,
        sampleSize,
        intervalMinutes,
        metricVersion,
        thresholdVersion,
      });
      await Promise.all([refetchRuns(), refetchMonitoringStatus()]);
    } finally {
      setPendingActionRunId(undefined);
    }
  }

  function refreshAll() {
    void refetchRuns();
    if (activeRunId) {
      void refetchMonitoringStatus();
    }
    void refetch();
  }

  // KPI aggregation
  const kpiEvaluations = useMemo(
    () => filterEvaluationsByPeriod(evaluations || [], globalPeriod),
    [evaluations, globalPeriod]
  );
  const kpi = useMemo(
    () => computeKpiSummary(kpiEvaluations, previousEvaluations || []),
    [kpiEvaluations, previousEvaluations]
  );

  // Per-chart period resolution
  function getChartPeriod(chartKey: string): TimePeriodPreset {
    return chartPeriods[chartKey] || globalPeriod;
  }

  // ---- Render helpers ----
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
            <ChartSummaryBar avg={summary.avg} min={summary.min} max={summary.max} valueFormatter={(v) => `${v}%`} />
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
      const points = extractMetricTimeSeries(
        scopedEvaluations,
        "performance",
        key,
        activeRunId
      );
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
            <ChartSummaryBar avg={summary.avg} min={summary.min} max={summary.max} valueFormatter={(v) => `${v}%`} />
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
                <ChartSummaryBar avg={summary.avg} min={summary.min} max={summary.max} valueFormatter={(v) => `${v}ms`} />
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
                <ChartSummaryBar avg={summary.avg} min={summary.min} max={summary.max} valueFormatter={(v) => `${v}%`} />
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
      {/* Main content */}
      <main className="flex-1 overflow-y-auto relative">
        {isThreadPanelOpen && (
          <button
            type="button"
            aria-label="Close thread list"
            className="fixed inset-0 z-30 bg-black/35 lg:hidden"
            onClick={() => setIsThreadPanelOpen(false)}
          />
        )}

        {runSummaries.length > 0 && (
          <aside
            className={cn(
              "fixed top-14 bottom-0 left-0 z-40 border-r border-border bg-background/95 px-4 py-4 backdrop-blur transition-all duration-300 ease-out lg:left-[var(--dashboard-sidebar-width)] lg:w-[var(--thread-panel-width)]",
              isThreadPanelOpen
                ? "translate-x-0 opacity-100 pointer-events-auto"
                : "-translate-x-full opacity-0 pointer-events-none"
            )}
          >
            <RunThreadList
              runs={runSummaries}
              selectedRunId={activeRunId}
              onSelectRun={setSelectedRunId}
              globalDefaults={globalEvalDefaults}
              onGlobalChange={setGlobalEvalDefaults}
              overrides={threadParamOverrides}
              expandedOverrideRunId={expandedOverrideRunId}
              onToggleOverrideEditor={(runId) =>
                setExpandedOverrideRunId((prev) => (prev === runId ? null : runId))
              }
              onOverrideChange={(runId, patch) => {
                setThreadParamOverrides((prev) => ({
                  ...prev,
                  [runId]: {
                    ...prev[runId],
                    ...patch,
                  },
                }));
              }}
              onClearOverride={(runId) => {
                setThreadParamOverrides((prev) => {
                  const next = { ...prev };
                  delete next[runId];
                  return next;
                });
              }}
              pendingActionRunId={pendingActionRunId}
              onStartRun={(runId) => void handleMonitoringAction(runId, "start")}
              onResumeRun={(runId) => void handleMonitoringAction(runId, "continue")}
            />
          </aside>
        )}

        <div
          className={cn(
            "monitor-content min-w-0 px-6 py-6 transition-[margin] duration-300 ease-out",
            hasLeftPanel && "monitor-content--left",
            selectedPoint && "monitor-content--right"
          )}
        >
          {runSummaries.length > 0 && (
            <div className="mb-4 flex items-center">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsThreadPanelOpen((prev) => !prev)}
                aria-label={isThreadPanelOpen ? "Hide thread list" : "Show thread list"}
                className="gap-2"
              >
                {isThreadPanelOpen ? (
                  <PanelLeftClose className="h-4 w-4" />
                ) : (
                  <PanelLeftOpen className="h-4 w-4" />
                )}
                <span>{isThreadPanelOpen ? "Hide Threads" : "Show Threads"}</span>
              </Button>
            </div>
          )}

          {!isRunsLoading && runSummaries.length === 0 && (
            <EmptyState
              message="No run folders found under outputs/runs."
              suggestion="Generate a run first, then start monitoring from the dashboard."
            />
          )}

          {runSummaries.length > 0 && (
            <div className="mb-6">
              <Card className="border-border bg-card">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-foreground">
                    Monitoring Progress
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-foreground">
                        {selectedRun ? monitoringStatusLabel(selectedRun.monitoringStatus) : "No run selected"}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {monitoringStatus?.updatedAt
                          ? `Updated ${formatDistanceToNow(new Date(monitoringStatus.updatedAt), { addSuffix: true })}`
                          : "No monitoring state yet"}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {selectedRun?.canStart && (
                        <Button
                          size="sm"
                          onClick={() => void handleMonitoringAction(selectedRun.runId, "start")}
                          disabled={startMonitoring.isPending || !activeRunId || !!pendingActionRunId}
                        >
                          Start Eval
                        </Button>
                      )}
                      {selectedRun?.canContinue && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void handleMonitoringAction(selectedRun.runId, "continue")}
                          disabled={startMonitoring.isPending || !activeRunId || !!pendingActionRunId}
                        >
                          Continue Eval
                        </Button>
                      )}
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
                      <span>Completion</span>
                      <span>{monitoringStatus?.progress.percent ?? selectedRun?.progress.percent ?? 0}%</span>
                    </div>
                    <progress
                      className="h-2 w-full overflow-hidden rounded-full [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary [&::-moz-progress-bar]:bg-primary"
                      max={100}
                      value={monitoringStatus?.progress.percent ?? selectedRun?.progress.percent ?? 0}
                    />
                  </div>

                  <div className="rounded-md border border-border bg-background p-3 text-xs text-muted-foreground">
                    <div className="mb-2 font-medium text-foreground">Progress Notes</div>
                    <div className="max-h-[320px] overflow-y-auto whitespace-normal leading-5 text-xs text-muted-foreground [&_h1]:mb-2 [&_h1]:text-sm [&_h1]:font-semibold [&_h1]:text-foreground [&_h2]:mb-2 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-foreground [&_h3]:mb-1 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-foreground [&_p]:mb-2 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:mb-1 [&_code]:rounded [&_code]:bg-muted/50 [&_code]:px-1 [&_code]:py-0.5 [&_pre]:mb-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted/40 [&_pre]:p-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {monitoringStatus?.progressMarkdown || "Progress markdown will appear here after monitoring starts."}
                      </ReactMarkdown>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Error state */}
          {isError && (
            <ErrorCard
              message={(error as Error)?.message || "Failed to load evaluation data."}
              onRetry={() => refetch()}
            />
          )}

          {/* Empty state */}
          {!isLoading && !isError && evaluations?.length === 0 && (
            <EmptyState
              message={
                selectedRun?.monitoringStatus === "completed"
                  ? "No evaluation data for this period."
                  : "Monitoring results are not complete for this run yet."
              }
              suggestion={
                selectedRun?.monitoringStatus === "completed"
                  ? "Try widening the time range or choose another run."
                  : "Start or continue evaluation from the progress panel, then refresh when rows have been scored."
              }
              onAction={refreshAll}
              actionLabel="Refresh"
            />
          )}

          {/* Dashboard content */}
          {(!isError && (isLoading || (evaluations && evaluations.length > 0))) && (
            <>
              {/* KPI Row */}
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

              {/* Skeleton loading */}
              {isLoading && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div
                      key={i}
                      className={
                        i === 0 ? "col-span-2" : "col-span-1"
                      }
                    >
                      <div className="rounded-lg border border-border bg-card p-4">
                        <Skeleton className="h-5 w-32 mb-4" />
                        <Skeleton className="h-[200px] w-full" />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Metric Tabs */}
              {!isLoading && evaluations && evaluations.length > 0 && (
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
            </>
          )}
        </div>
      </main>

      <TraceDrawer
        open={Boolean(selectedPoint)}
        point={selectedPoint}
        trace={traceDetails}
        isLoading={isTraceLoading || isTraceFetching}
        errorMessage={traceError instanceof Error ? traceError.message : undefined}
        onClose={() => setSelectedPoint(null)}
      />
    </div>
  );
}
