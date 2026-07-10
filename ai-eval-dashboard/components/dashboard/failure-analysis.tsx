"use client";

import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ChevronRight,
  AlertTriangle,
  Shield,
  Activity,
  Users,
  Crosshair,
  MessageSquare,
  TrendingDown,
  FilterX,
} from "lucide-react";
import type {
  EvaluationRecord,
  FailedMetricRanking,
  FailureGroup,
} from "@/types/evaluation";
import { cn } from "@/lib/utils";
import { computeRecordSeverity } from "@/lib/verdict";

interface FailureAnalysisProps {
  evaluations: EvaluationRecord[];
  failedMetrics: FailedMetricRanking[];
  activeGroupFilter: FailureGroup["groupType"] | null;
  activeGroupKey: string | null;
  onGroupSelect: (groupType: FailureGroup["groupType"], groupKey: string) => void;
  onClearGroupFilter: () => void;
}

const GROUP_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  metric: Shield,
  scenario: Crosshair,
  persona: Users,
  attack_category: AlertTriangle,
  response_status: MessageSquare,
};

const GROUP_LABELS: Record<string, string> = {
  metric: "By Metric",
  scenario: "By Scenario",
  persona: "By Persona",
  attack_category: "By Attack Category",
  response_status: "By Response Status",
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/10 text-red-500 border-red-500/30",
  high: "bg-orange-500/10 text-orange-500 border-orange-500/30",
  medium: "bg-amber-500/10 text-amber-500 border-amber-500/30",
  low: "bg-muted text-muted-foreground border-muted",
};

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export function FailureAnalysis({
  evaluations,
  failedMetrics,
  activeGroupFilter,
  activeGroupKey,
  onGroupSelect,
  onClearGroupFilter,
}: FailureAnalysisProps) {
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);

  // Build failure groups from evaluations
  const failureGroups = useMemo(() => {
    const groups: FailureGroup[] = [];

    // 1. Group by metric (from failedMetrics ranking)
    for (const fm of failedMetrics) {
      groups.push({
        groupKey: fm.metricKey,
        groupLabel: fm.label,
        groupType: "metric",
        count: fm.failCount + fm.warnCount,
        failCount: fm.failCount,
        severity: fm.severity,
        items: evaluations
          .filter((e) => {
            const m =
              fm.metricGroup === "safety"
                ? e.safety_metrics[fm.metricKey as keyof typeof e.safety_metrics]
                : e.performance_metrics[fm.metricKey as keyof typeof e.performance_metrics];
            return m?.status === "fail" || m?.status === "warn";
          })
          .map((e) => e.turn_id),
        representativeMetric: fm.metricKey,
      });
    }

    // 2. Group by response status (safety_status / performance_status)
    const statusGroups = new Map<string, { fail: number; warn: number; items: string[] }>();
    for (const e of evaluations) {
      if (e.safety_status === "fail" || e.performance_status === "fail") {
        const key = `status:fail`;
        if (!statusGroups.has(key)) statusGroups.set(key, { fail: 0, warn: 0, items: [] });
        statusGroups.get(key)!.fail++;
        statusGroups.get(key)!.items.push(e.turn_id);
      }
      if (e.safety_status === "warn" || e.performance_status === "warn") {
        const key = `status:warn`;
        if (!statusGroups.has(key)) statusGroups.set(key, { fail: 0, warn: 0, items: [] });
        statusGroups.get(key)!.warn++;
        statusGroups.get(key)!.items.push(e.turn_id);
      }
    }
    for (const [key, data] of statusGroups) {
      const label = key === "status:fail" ? "Failed Responses" : "Warning Responses";
      groups.push({
        groupKey: key,
        groupLabel: label,
        groupType: "response_status",
        count: data.fail + data.warn,
        failCount: data.fail,
        severity: data.fail > 0 ? "critical" : "medium",
        items: data.items,
      });
    }

    // 3. Group by scenario if scenario data exists in records
    const scenarioMap = new Map<string, { fail: number; warn: number; items: string[] }>();
    for (const e of evaluations) {
      const scenario = e.scenario;
      if (scenario) {
        if (!scenarioMap.has(scenario)) scenarioMap.set(scenario, { fail: 0, warn: 0, items: [] });
        const entry = scenarioMap.get(scenario)!;
        if (e.safety_status === "fail" || e.performance_status === "fail") entry.fail++;
        else if (e.safety_status === "warn" || e.performance_status === "warn") entry.warn++;
        if (e.safety_status !== "pass" || e.performance_status !== "pass") {
          entry.items.push(e.turn_id);
        }
      }
    }
    for (const [scenario, data] of scenarioMap) {
      if (data.fail + data.warn > 0) {
        groups.push({
          groupKey: `scenario:${scenario}`,
          groupLabel: scenario,
          groupType: "scenario",
          count: data.fail + data.warn,
          failCount: data.fail,
          severity: data.fail > 3 ? "high" : data.fail > 0 ? "medium" : "low",
          items: data.items,
        });
      }
    }

    // 4. Group by persona if persona data exists
    const personaMap = new Map<string, { fail: number; warn: number; items: string[] }>();
    for (const e of evaluations) {
      const persona = e.persona;
      if (persona) {
        if (!personaMap.has(persona)) personaMap.set(persona, { fail: 0, warn: 0, items: [] });
        const entry = personaMap.get(persona)!;
        if (e.safety_status === "fail" || e.performance_status === "fail") entry.fail++;
        else if (e.safety_status === "warn" || e.performance_status === "warn") entry.warn++;
        if (e.safety_status !== "pass" || e.performance_status !== "pass") {
          entry.items.push(e.turn_id);
        }
      }
    }
    for (const [persona, data] of personaMap) {
      if (data.fail + data.warn > 0) {
        groups.push({
          groupKey: `persona:${persona}`,
          groupLabel: persona,
          groupType: "persona",
          count: data.fail + data.warn,
          failCount: data.fail,
          severity: data.fail > 3 ? "high" : data.fail > 0 ? "medium" : "low",
          items: data.items,
        });
      }
    }

    // 5. Group by attack category if present
    const attackMap = new Map<string, { fail: number; warn: number; items: string[] }>();
    for (const e of evaluations) {
      const attackCat = e.attack_category;
      if (attackCat) {
        if (!attackMap.has(attackCat)) attackMap.set(attackCat, { fail: 0, warn: 0, items: [] });
        const entry = attackMap.get(attackCat)!;
        if (e.safety_status === "fail" || e.performance_status === "fail") entry.fail++;
        else if (e.safety_status === "warn" || e.performance_status === "warn") entry.warn++;
        if (e.safety_status !== "pass" || e.performance_status !== "pass") {
          entry.items.push(e.turn_id);
        }
      }
    }
    for (const [cat, data] of attackMap) {
      if (data.fail + data.warn > 0) {
        groups.push({
          groupKey: `attack:${cat}`,
          groupLabel: cat,
          groupType: "attack_category",
          count: data.fail + data.warn,
          failCount: data.fail,
          severity: data.fail > 5 ? "critical" : data.fail > 2 ? "high" : "medium",
          items: data.items,
        });
      }
    }

    // Sort by severity then count
    groups.sort((a, b) => {
      const sevDiff = (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99);
      if (sevDiff !== 0) return sevDiff;
      return b.count - a.count;
    });

    return groups;
  }, [evaluations, failedMetrics]);

  // Group groups by type for the sidebar
  const groupsByType = useMemo(() => {
    const map = new Map<string, FailureGroup[]>();
    for (const g of failureGroups) {
      const existing = map.get(g.groupType) ?? [];
      existing.push(g);
      map.set(g.groupType, existing);
    }
    return map;
  }, [failureGroups]);

  const totalFailures = failedMetrics.reduce((sum, m) => sum + m.failCount, 0);

  if (totalFailures === 0) {
    return (
      <Card className="border-border bg-card mb-6">
        <CardContent className="py-12 text-center">
          <div className="rounded-full bg-emerald-500/10 p-4 mb-4 inline-flex">
            <Shield className="h-8 w-8 text-emerald-500" />
          </div>
          <h3 className="text-lg font-semibold text-foreground mb-2">No Failures Detected</h3>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            All evaluation records passed safety and performance checks.
            No failure analysis is needed.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border bg-card mb-6">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-foreground flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            Failure Analysis
          </CardTitle>
          {activeGroupFilter && (
            <Button
              variant="ghost"
              size="xs"
              onClick={onClearGroupFilter}
              className="text-xs gap-1"
            >
              <FilterX className="h-3 w-3" />
              Clear filter
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {totalFailures} failures across {failedMetrics.length} metrics. Click a group to filter the evidence queue.
        </p>
      </CardHeader>

      <CardContent>
        {/* Ranked failed metrics */}
        <div className="mb-4">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Failed Metrics (by severity)
          </h4>
          <div className="space-y-1.5">
            {failedMetrics.slice(0, 6).map((metric) => (
              <button
                key={metric.metricKey}
                type="button"
                onClick={() => onGroupSelect("metric", metric.metricKey)}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted/50",
                  activeGroupFilter === "metric" && activeGroupKey === metric.metricKey
                    ? "bg-accent border border-primary/30"
                    : "border border-transparent"
                )}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Badge
                    variant="outline"
                    className={cn("text-[10px] px-1.5 py-0", SEVERITY_COLORS[metric.severity])}
                  >
                    {metric.severity}
                  </Badge>
                  <span className="font-medium truncate">{metric.label}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0">
                  <span>{metric.failCount} fail</span>
                  <span>{metric.warnCount} warn</span>
                  <span>{(metric.failRate ?? 0).toFixed(1)}%</span>
                  <ChevronRight className="h-3 w-3" />
                </div>
              </button>
            ))}
            {failedMetrics.length > 6 && (
              <p className="text-xs text-muted-foreground text-center py-1">
                +{failedMetrics.length - 6} more metrics
              </p>
            )}
          </div>
        </div>

        {/* Failure groups by type */}
        {Array.from(groupsByType.entries()).map(([groupType, groups]) => {
          const Icon = GROUP_ICONS[groupType] ?? Shield;
          return (
            <div key={groupType} className="mb-3 last:mb-0">
              <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Icon className="h-3 w-3" />
                {GROUP_LABELS[groupType] ?? groupType}
              </h4>
              <div className="space-y-1">
                {groups.slice(0, 4).map((group) => {
                  const isActive =
                    activeGroupFilter === group.groupType && activeGroupKey === group.groupKey;
                  return (
                    <button
                      key={group.groupKey}
                      type="button"
                      onClick={() => onGroupSelect(group.groupType, group.groupKey)}
                      className={cn(
                        "flex w-full items-center justify-between rounded-md px-3 py-1.5 text-left text-xs transition-colors hover:bg-muted/50",
                        isActive
                          ? "bg-accent border border-primary/30"
                          : "border border-transparent"
                      )}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <Badge
                          variant="outline"
                          className={cn("text-[10px] px-1 py-0", SEVERITY_COLORS[group.severity])}
                        >
                          {group.severity}
                        </Badge>
                        <span className="truncate">{group.groupLabel}</span>
                      </div>
                      <span className="text-muted-foreground shrink-0 ml-2">
                        {group.failCount} fail / {group.count} total
                      </span>
                    </button>
                  );
                })}
                {groups.length > 4 && (
                  <p className="text-xs text-muted-foreground text-center py-0.5">
                    +{groups.length - 4} more
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
