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
  RefreshCw,
  BarChart3,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import type { EvalRunParameters, TimePeriodPreset } from "@/types/evaluation";
import { METRIC_THRESHOLDS, LATENCY_WARN_MS, LATENCY_FAIL_MS } from "@/lib/metrics";
import { cn } from "@/lib/utils";
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
} from "@/hooks/use-evaluations";

import { KpiCard } from "@/components/dashboard/kpi-card";
import { ChartCard, ChartSummaryBar } from "@/components/dashboard/chart-card";
import { MetricLineChart } from "@/components/dashboard/metric-line-chart";
import { RunThreadList } from "@/components/dashboard/run-thread-list";
import { EmptyState, ErrorCard } from "@/components/shared/empty-state";
import { DetailDialog } from "@/components/dashboard/detail-dialog";
import type { EvaluationRecord } from "@/types/evaluation";

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

export default function DashboardPage() {
  const [globalPeriod] = useState<TimePeriodPreset>("this-week");
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [isThreadPanelOpen, setIsThreadPanelOpen] = useState(true);
  const [globalEvalDefaults, setGlobalEvalDefaults] =
    useState<EvalRunParameters>(DEFAULT_MONITORING_CONFIG);
  const [threadParamOverrides, setThreadParamOverrides] =
    useState<Record<string, Partial<EvalRunParameters>>>({});
  const [expandedOverrideRunId, setExpandedOverrideRunId] = useState<string | null>(null);
  const [pendingActionRunId, setPendingActionRunId] = useState<string | undefined>(undefined);
  const [chartPeriods, setChartPeriods] = useState<
    Record<string, TimePeriodPreset>
  >({});
  const [detailDialog, setDetailDialog] = useState<{
    record: EvaluationRecord;
    metricGroup: "safety" | "performance";
    metricKey: string;
  } | null>(null);

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

  const {
    data: monitoringStatus,
    refetch: refetchMonitoringStatus,
  } = useMonitoringStatus(activeRunId || undefined);
  const startMonitoring = useStartMonitoring();
  const canLoadEvaluations = Boolean(activeRunId);

  const {
    data: evaluations,
    isLoading,
    isError,
    error,
    refetch,
    dataUpdatedAt,
  } = useEvaluations(globalPeriod, activeRunId || undefined, canLoadEvaluations);
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
  const kpi = useMemo(
    () => computeKpiSummary(evaluations || [], previousEvaluations || []),
    [evaluations, previousEvaluations]
  );

  // Per-chart period resolution
  function getChartPeriod(chartKey: string): TimePeriodPreset {
    return chartPeriods[chartKey] || globalPeriod;
  }

  // ---- Render helpers ----
  function renderSafetyCharts() {
    if (!evaluations) return null;
    return SAFETY_METRICS.map((key, i) => {
      const threshold = METRIC_THRESHOLDS[key];
      const points = extractMetricTimeSeries(evaluations, "safety", key);
      const summary = computeChartSummary(points);
      const latest = points[points.length - 1];
      const period = getChartPeriod(key);

      return (
        <ChartCard
          key={key}
          title={threshold.label}
          tooltip={`Measures ${key.replace("_", " ")} in LLM responses. Range: 0–100%. Fail below ${threshold.failBelow}%, Warn below ${threshold.warnBelow}%.`}
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
            latest
              ? () =>
                  setDetailDialog({
                    record: evaluations[evaluations.length - 1],
                    metricGroup: "safety",
                    metricKey: key as string,
                  })
              : undefined
          }
        >
          <MetricLineChart
            data={points}
            warnThreshold={threshold.warnBelow}
            failThreshold={threshold.failBelow}
            valueFormatter={(v) => `${v}%`}
          />
        </ChartCard>
      );
    });
  }

  function renderPerformanceCharts() {
    if (!evaluations) return null;
    return PERF_METRICS.map((key, i) => {
      const threshold = METRIC_THRESHOLDS[key];
      const points = extractMetricTimeSeries(evaluations, "performance", key);
      const summary = computeChartSummary(points);
      const latest = points[points.length - 1];
      const period = getChartPeriod(key);

      return (
        <ChartCard
          key={key}
          title={threshold.label}
          tooltip={`Measures ${key} of LLM responses. Range: 0–100%. Fail below ${threshold.failBelow}%, Warn below ${threshold.warnBelow}%.`}
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
            latest
              ? () =>
                  setDetailDialog({
                    record: evaluations[evaluations.length - 1],
                    metricGroup: "performance",
                    metricKey: key as string,
                  })
              : undefined
          }
        >
          <MetricLineChart
            data={points}
            warnThreshold={threshold.warnBelow}
            failThreshold={threshold.failBelow}
            valueFormatter={(v) => `${v}%`}
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
          const points = extractLatencyTimeSeries(evaluations, key);
          const summary = computeChartSummary(points);
          const latest = points[points.length - 1];
          const period = getChartPeriod(key);

          return (
            <ChartCard
              key={key}
              title={label}
              tooltip={`Latency in milliseconds. Warn > ${LATENCY_WARN_MS}ms, Fail > ${LATENCY_FAIL_MS}ms.`}
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
                warnThreshold={LATENCY_WARN_MS}
                failThreshold={LATENCY_FAIL_MS}
                yDomain={[0, "auto"]}
                valueFormatter={(v) => `${v}ms`}
              />
            </ChartCard>
          );
        })}
        {/* Availability chart */}
        {(() => {
          const key = "availability";
          const period = getChartPeriod(key);
          const points = (evaluations || [])
            .map((e) => ({
              timestamp: e.timestamp,
              value: e.system_reliability.availability * 100,
              status: e.system_reliability.availability_status,
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
              tooltip="System availability as a percentage. Fail below 95%, Warn below 99%."
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
                warnThreshold={99}
                failThreshold={95}
                valueFormatter={(v) => `${v}%`}
              />
            </ChartCard>
          );
        })()}
      </>
    );
  }

  // ---- Main render ----
  return (
    <div className="flex flex-col min-h-full">
      {/* Header */}
      <header className="h-16 flex items-center justify-between border-b border-border bg-header-bg px-6 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-primary" />
            <h1 className="text-base font-semibold text-foreground">
              AI Eval Monitor
            </h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setIsThreadPanelOpen((prev) => !prev)}
            title={isThreadPanelOpen ? "Close thread list" : "Open thread list"}
          >
            {isThreadPanelOpen ? (
              <ChevronLeft className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </Button>
          {dataUpdatedAt && (
            <span className="text-xs text-muted-foreground">
              Updated {formatDistanceToNow(dataUpdatedAt, { addSuffix: true })}
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={refreshAll}
            disabled={isLoading}
          >
            <RefreshCw
              className={`h-4 w-4 mr-1.5 ${isLoading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
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
              "fixed top-16 bottom-0 left-0 z-40 w-[360px] border-r border-border bg-background/95 px-4 py-4 backdrop-blur transition-transform duration-300 ease-out",
              isThreadPanelOpen ? "translate-x-0" : "-translate-x-full"
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
            "mx-auto max-w-[1280px] px-6 py-6 transition-[padding] duration-300 ease-out",
            isThreadPanelOpen ? "lg:pl-[390px]" : "lg:pl-6"
          )}
        >
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
                    <pre className="whitespace-pre-wrap font-sans leading-5">
                      {monitoringStatus?.progressMarkdown || "Progress markdown will appear here after monitoring starts."}
                    </pre>
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

      {/* Detail Dialog */}
      <DetailDialog
        open={!!detailDialog}
        onOpenChange={(open) => {
          if (!open) setDetailDialog(null);
        }}
        record={detailDialog?.record || null}
        metricGroup={detailDialog?.metricGroup || null}
        metricKey={detailDialog?.metricKey || null}
      />
    </div>
  );
}
