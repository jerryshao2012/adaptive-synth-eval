"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Shield,
  Gauge,
  Activity,
  TrendingUp,
  TrendingDown,
  Minus,
  Zap,
  AlertOctagon,
  Clock,
} from "lucide-react";
import type { InvestigationSummary } from "@/types/evaluation";
import { cn } from "@/lib/utils";

interface InvestigationSummaryCardProps {
  summary: InvestigationSummary | null;
  isLoading: boolean;
  hasData: boolean;
  runStatus?: string;
}

const VERDICT_STYLES: Record<
  string,
  {
    icon: typeof CheckCircle2;
    containerClass: string;
    labelClass: string;
    iconClass: string;
  }
> = {
  healthy: {
    icon: CheckCircle2,
    containerClass: "border-emerald-500/30 bg-emerald-500/5",
    labelClass: "text-emerald-500",
    iconClass: "text-emerald-500",
  },
  needs_review: {
    icon: AlertTriangle,
    containerClass: "border-amber-500/30 bg-amber-500/5",
    labelClass: "text-amber-500",
    iconClass: "text-amber-500",
  },
  failed: {
    icon: XCircle,
    containerClass: "border-red-500/30 bg-red-500/5",
    labelClass: "text-red-500",
    iconClass: "text-red-500",
  },
};

export function InvestigationSummaryCard({
  summary,
  isLoading,
  hasData,
  runStatus,
}: InvestigationSummaryCardProps) {
  // ---- Empty states ----

  if (!hasData && !isLoading) {
    if (runStatus === "not_started") {
      return (
        <Card className="border-border bg-card mb-6">
          <CardContent className="py-12 text-center">
            <div className="rounded-full bg-muted p-4 mb-4 inline-flex">
              <Clock className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-semibold text-foreground mb-2">Monitoring Not Started</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              Start monitoring from the run header above to generate evaluation data.
              Once evaluations are available, the investigation summary will appear here.
            </p>
          </CardContent>
        </Card>
      );
    }

    if (runStatus === "in_progress") {
      return (
        <Card className="border-border bg-card mb-6">
          <CardContent className="py-12 text-center">
            <div className="rounded-full bg-muted p-4 mb-4 inline-flex">
              <Activity className="h-8 w-8 text-muted-foreground animate-pulse" />
            </div>
            <h3 className="text-lg font-semibold text-foreground mb-2">Evaluation In Progress</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              Monitoring is actively generating evaluations. The investigation summary
              will update automatically as new data arrives.
            </p>
          </CardContent>
        </Card>
      );
    }

    return (
      <Card className="border-border bg-card mb-6">
        <CardContent className="py-12 text-center">
          <div className="rounded-full bg-muted p-4 mb-4 inline-flex">
            <AlertOctagon className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold text-foreground mb-2">No Evaluation Data</h3>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            No evaluation records are available for this run. If monitoring has completed,
            check that the scores file was written correctly.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card className="border-border bg-card mb-6">
        <CardContent className="py-12">
          <div className="space-y-4 animate-pulse">
            <div className="h-8 bg-muted rounded w-48 mx-auto" />
            <div className="h-4 bg-muted rounded w-72 mx-auto" />
            <div className="grid grid-cols-4 gap-4 mt-6">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-20 bg-muted rounded-lg" />
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!summary) return null;

  const verdict = VERDICT_STYLES[summary.verdict] ?? VERDICT_STYLES.needs_review;
  const VerdictIcon = verdict.icon;

  // ---- Main render ----

  return (
    <Card className={cn("border mb-6", verdict.containerClass)}>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-3">
          <div className={cn("rounded-full p-2", verdict.iconClass, "bg-current/10")}>
            <VerdictIcon className={cn("h-5 w-5", verdict.iconClass)} />
          </div>
          <div>
            <CardTitle className={cn("text-lg font-bold", verdict.labelClass)}>
              {summary.verdictLabel}
            </CardTitle>
            <p className="text-sm text-muted-foreground mt-0.5">
              {summary.verdictDescription}
            </p>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Stats row */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mt-2">
          <StatItem
            label="Failed Turns"
            value={summary.failedTurnCount.toLocaleString()}
            sub={`${summary.failRate}% fail rate`}
            icon={XCircle}
            tone="fail"
          />
          <StatItem
            label="Pass Rate"
            value={`${summary.passRate}%`}
            sub={summary.warnTurnCount > 0 ? `${summary.warnTurnCount} warnings` : undefined}
            icon={CheckCircle2}
            tone="pass"
          />
          <StatItem
            label="Avg Latency"
            value={
              summary.avgLatencyMs === null
                ? "Unknown"
                : `${summary.avgLatencyMs}ms`
            }
            sub="per turn"
            icon={Zap}
            tone="neutral"
          />
          <StatItem
            label="Worst Metric"
            value={summary.worstPerformingMetric?.label ?? "N/A"}
            sub={
              summary.worstPerformingMetric
                ? `${summary.worstPerformingMetric.failCount} failures`
                : undefined
            }
            icon={AlertTriangle}
            tone={summary.worstPerformingMetric ? "warn" : "neutral"}
          />
          <StatItem
            label="vs Prior Period"
            value={
              summary.comparisonWithPrior?.hasPriorData
                ? `${summary.comparisonWithPrior.passRateChange > 0 ? "+" : ""}${summary.comparisonWithPrior.passRateChange}%`
                : "N/A"
            }
            sub={
              summary.comparisonWithPrior?.hasPriorData
                ? "pass rate change"
                : "no prior data"
            }
            icon={
              (summary.comparisonWithPrior?.passRateChange ?? 0) > 0
                ? TrendingUp
                : (summary.comparisonWithPrior?.passRateChange ?? 0) < 0
                  ? TrendingDown
                  : Minus
            }
            tone={
              summary.comparisonWithPrior?.hasPriorData
                ? (summary.comparisonWithPrior?.passRateChange ?? 0) > 0
                  ? "pass"
                  : (summary.comparisonWithPrior?.passRateChange ?? 0) < 0
                    ? "fail"
                    : "neutral"
                : "neutral"
            }
          />
        </div>
      </CardContent>
    </Card>
  );
}

// ---- Stat item sub-component ----

function StatItem({
  label,
  value,
  sub,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone: "pass" | "fail" | "warn" | "neutral";
}) {
  const toneColors: Record<string, string> = {
    pass: "text-emerald-500",
    fail: "text-red-500",
    warn: "text-amber-500",
    neutral: "text-muted-foreground",
  };

  return (
    <div className="rounded-lg border border-border bg-background/50 p-3">
      <div className="flex items-center gap-2 mb-1">
        <Icon className={cn("h-3.5 w-3.5", toneColors[tone])} />
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <div className="text-lg font-bold text-foreground">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}
