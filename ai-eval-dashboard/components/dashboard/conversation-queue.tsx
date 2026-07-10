"use client";

import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Search,
  Filter,
  ChevronRight,
  MessageSquare,
  Shield,
  Activity,
  Gauge,
  Clock,
  AlertTriangle,
  FileText,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import type {
  EvaluationRecord,
  ConversationQueueItem,
  ConversationQueueFilters,
  MetricPointIdentity,
  MetricScoreStatus,
} from "@/types/evaluation";
import { rankConversations, computeRecordSeverity } from "@/lib/verdict";
import { cn } from "@/lib/utils";

interface ConversationQueueProps {
  evaluations: EvaluationRecord[];
  activeRunId: string;
  onSelectConversation: (point: MetricPointIdentity) => void;
  groupFilter?: { groupType: string; groupKey: string } | null;
}

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/10 text-red-500 border-red-500/30",
  high: "bg-orange-500/10 text-orange-500 border-orange-500/30",
  medium: "bg-amber-500/10 text-amber-500 border-amber-500/30",
  low: "bg-muted text-muted-foreground border-muted",
};

const STATUS_COLORS: Record<string, string> = {
  pass: "text-emerald-500",
  warn: "text-amber-500",
  fail: "text-red-500",
};

export function ConversationQueue({
  evaluations,
  activeRunId,
  onSelectConversation,
  groupFilter,
}: ConversationQueueProps) {
  const [searchText, setSearchText] = useState("");
  const [outcomeFilter, setOutcomeFilter] = useState<ConversationQueueFilters["outcome"]>("all");
  const [severityFilter, setSeverityFilter] = useState<ConversationQueueFilters["severity"]>("all");
  const [sortBy, setSortBy] = useState<ConversationQueueFilters["sortBy"]>("severity");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  // Build conversation queue items from evaluations
  const allItems = useMemo(() => {
    // First, filter by group if active
    let filtered = evaluations;
    if (groupFilter) {
      filtered = evaluations.filter((e) => {
        if (groupFilter.groupType === "metric") {
          // Check if this record has a failure in the specified metric
          const m =
            e.safety_metrics[groupFilter.groupKey as keyof typeof e.safety_metrics] ??
            e.performance_metrics[groupFilter.groupKey as keyof typeof e.performance_metrics];
          return m?.status === "fail" || m?.status === "warn";
        }
        if (groupFilter.groupType === "response_status") {
          if (groupFilter.groupKey === "status:fail")
            return e.safety_status === "fail" || e.performance_status === "fail";
          if (groupFilter.groupKey === "status:warn")
            return (
              (e.safety_status === "warn" || e.performance_status === "warn") &&
              e.safety_status !== "fail" &&
              e.performance_status !== "fail"
            );
          return false;
        }
        if (groupFilter.groupType === "scenario") {
          return e.scenario === groupFilter.groupKey.replace("scenario:", "");
        }
        if (groupFilter.groupType === "persona") {
          return e.persona === groupFilter.groupKey.replace("persona:", "");
        }
        if (groupFilter.groupType === "attack_category") {
          return e.attack_category === groupFilter.groupKey.replace("attack:", "");
        }
        return false;
      });
    }

    // Rank by severity then recency
    const ranked = rankConversations(filtered);

    return ranked.map((record) => {
      const { severity, failedMetrics } = computeRecordSeverity(record);
      const safetyScores: Record<string, number> = {};
      for (const key of ["toxicity", "bias_fairness", "robustness", "compliance"]) {
        const m = record.safety_metrics[key as keyof typeof record.safety_metrics];
        if (m) safetyScores[key] = m.percent;
      }
      const perfScores: Record<string, number> = {};
      for (const key of ["relevance", "groundedness", "correctness", "completeness", "style", "precision"]) {
        const m = record.performance_metrics[key as keyof typeof record.performance_metrics];
        if (m) perfScores[key] = m.percent;
      }

      return {
        runId: record.run_id ?? activeRunId,
        conversationId: record.conversation_id ?? "",
        turnId: record.turn_id,
        timestamp: record.timestamp,
        userText: record.user_text,
        responseText: record.response_text,
        safetyStatus: record.safety_status,
        performanceStatus: record.performance_status,
        overallSeverity: severity,
        failedMetrics,
        safetyScores,
        performanceScores: perfScores,
        latencyMs: record.system_reliability.total_latency_ms,
        scenario: record.scenario,
        persona: record.persona,
        attackCategory: record.attack_category,
      } satisfies ConversationQueueItem;
    });
  }, [evaluations, activeRunId, groupFilter]);

  // Apply filters
  const filteredItems = useMemo(() => {
    let items = allItems;

    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      items = items.filter(
        (item) =>
          item.userText.toLowerCase().includes(q) ||
          item.responseText.toLowerCase().includes(q) ||
          item.turnId.toLowerCase().includes(q) ||
          item.failedMetrics.some((m) => m.toLowerCase().includes(q))
      );
    }

    if (outcomeFilter && outcomeFilter !== "all") {
      if (outcomeFilter === "safety") {
        items = items.filter((item) => item.safetyStatus === "fail" || item.safetyStatus === "warn");
      } else if (outcomeFilter === "performance") {
        items = items.filter((item) => item.performanceStatus === "fail" || item.performanceStatus === "warn");
      } else if (outcomeFilter === "reliability") {
        items = items.filter((item) => item.failedMetrics.includes("total_latency_ms"));
      }
    }

    if (severityFilter && severityFilter !== "all") {
      items = items.filter((item) => item.overallSeverity === severityFilter);
    }

    // Sort
    if (sortBy === "severity") {
      items = [...items].sort(
        (a, b) => (SEVERITY_ORDER[a.overallSeverity] ?? 99) - (SEVERITY_ORDER[b.overallSeverity] ?? 99)
      );
    } else if (sortBy === "recency") {
      items = [...items].sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      );
    } else if (sortBy === "score") {
      items = [...items].sort((a, b) => {
        const avgA =
          Object.values(a.safetyScores).reduce((s, v) => s + v, 0) /
          Math.max(1, Object.values(a.safetyScores).length);
        const avgB =
          Object.values(b.safetyScores).reduce((s, v) => s + v, 0) /
          Math.max(1, Object.values(b.safetyScores).length);
        return avgA - avgB;
      });
    }

    return items;
  }, [allItems, searchText, outcomeFilter, severityFilter, sortBy]);

  const totalPages = Math.ceil(filteredItems.length / PAGE_SIZE);
  const pagedItems = filteredItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleSelect = (item: ConversationQueueItem) => {
    // Find first failed metric to navigate to
    const firstFailedMetric = item.failedMetrics[0];
    const metricGroup: MetricPointIdentity["metricGroup"] =
      ["toxicity", "bias_fairness", "robustness", "compliance"].includes(firstFailedMetric)
        ? "safety"
        : firstFailedMetric === "total_latency_ms"
          ? "reliability"
          : "performance";

    onSelectConversation({
      runId: item.runId,
      conversationId: item.conversationId,
      turnId: item.turnId,
      timestamp: item.timestamp,
      metricGroup,
      metricKey: firstFailedMetric || "relevance",
    });
  };

  // Empty state
  if (allItems.length === 0) {
    return (
      <Card className="border-border bg-card mb-6">
        <CardContent className="py-12 text-center">
          <div className="rounded-full bg-emerald-500/10 p-4 mb-4 inline-flex">
            <MessageSquare className="h-8 w-8 text-emerald-500" />
          </div>
          <h3 className="text-lg font-semibold text-foreground mb-2">No Failed Conversations</h3>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            There are no conversations with safety or performance issues to review.
            {groupFilter ? " Try clearing the group filter to see all conversations." : ""}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border bg-card mb-6">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-sm font-semibold text-foreground flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Evidence Queue
            <Badge variant="secondary" className="text-xs ml-1">
              {filteredItems.length} records
            </Badge>
          </CardTitle>
          <div className="flex items-center gap-1.5">
            {/* Sort */}
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as ConversationQueueFilters["sortBy"])}
              className="h-7 rounded-md border border-border bg-background px-2 text-xs text-foreground outline-none"
            >
              <option value="severity">By Severity</option>
              <option value="recency">By Recency</option>
              <option value="score">By Score</option>
            </select>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Search and filters */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search conversations..."
              value={searchText}
              onChange={(e) => {
                setSearchText(e.target.value);
                setPage(1);
              }}
              className="h-8 w-full rounded-md border border-border bg-background pl-8 pr-3 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50 placeholder:text-muted-foreground"
            />
          </div>

          {/* Outcome filter chips */}
          <div className="flex items-center gap-1">
            {(["all", "safety", "performance", "reliability"] as const).map((f) => (
              <Button
                key={f}
                variant={outcomeFilter === f ? "secondary" : "ghost"}
                size="xs"
                onClick={() => {
                  setOutcomeFilter(f);
                  setPage(1);
                }}
                className="text-xs h-7 capitalize"
              >
                {f === "all" ? "All" : f}
              </Button>
            ))}
          </div>

          {/* Severity filter */}
          <select
            value={severityFilter}
            onChange={(e) => {
              setSeverityFilter(e.target.value as ConversationQueueFilters["severity"]);
              setPage(1);
            }}
            className="h-7 rounded-md border border-border bg-background px-2 text-xs text-foreground outline-none"
          >
            <option value="all">All Severity</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>

        {/* Queue items */}
        <ScrollArea className="h-[500px]">
          <div className="space-y-1.5">
            {pagedItems.map((item) => (
              <button
                key={`${item.conversationId}-${item.turnId}-${item.timestamp}`}
                type="button"
                onClick={() => handleSelect(item)}
                className="flex w-full items-start gap-3 rounded-lg border border-border bg-background px-4 py-3 text-left transition-colors hover:bg-muted/50 hover:border-primary/30"
              >
                {/* Severity indicator */}
                <div
                  className={cn(
                    "mt-0.5 h-2.5 w-2.5 rounded-full shrink-0",
                    item.overallSeverity === "critical" && "bg-red-500",
                    item.overallSeverity === "high" && "bg-orange-500",
                    item.overallSeverity === "medium" && "bg-amber-500",
                    item.overallSeverity === "low" && "bg-muted-foreground"
                  )}
                />

                <div className="flex-1 min-w-0">
                  {/* Header row */}
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="text-xs font-mono text-muted-foreground truncate">
                      {item.turnId}
                    </span>
                    <Badge
                      variant="outline"
                      className={cn("text-[10px] px-1.5 py-0", SEVERITY_COLORS[item.overallSeverity])}
                    >
                      {item.overallSeverity}
                    </Badge>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                      <Shield
                        className={cn("h-2.5 w-2.5 mr-0.5", STATUS_COLORS[item.safetyStatus])}
                      />
                      Safety
                    </Badge>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                      <Activity
                        className={cn("h-2.5 w-2.5 mr-0.5", STATUS_COLORS[item.performanceStatus])}
                      />
                      Perf
                    </Badge>
                    {item.latencyMs > 0 && (
                      <span className="text-[10px] text-muted-foreground">
                        <Clock className="h-2.5 w-2.5 inline mr-0.5" />
                        {item.latencyMs}ms
                      </span>
                    )}
                  </div>

                  {/* User text preview */}
                  <p className="text-xs text-foreground line-clamp-2 mb-1">
                    <span className="text-muted-foreground">User:</span> {item.userText}
                  </p>

                  {/* Response text preview */}
                  <p className="text-xs text-muted-foreground line-clamp-1 mb-1.5">
                    <span className="text-muted-foreground">Response:</span> {item.responseText}
                  </p>

                  {/* Failed metrics chips */}
                  <div className="flex items-center gap-1 flex-wrap">
                    {item.failedMetrics.slice(0, 4).map((metric) => (
                      <Badge
                        key={metric}
                        variant="outline"
                        className="text-[9px] px-1 py-0 border-red-500/30 text-red-500"
                      >
                        {metric}
                      </Badge>
                    ))}
                    {item.failedMetrics.length > 4 && (
                      <span className="text-[9px] text-muted-foreground">
                        +{item.failedMetrics.length - 4}
                      </span>
                    )}
                  </div>

                  {/* Timestamp */}
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    {formatDistanceToNow(new Date(item.timestamp), { addSuffix: true })}
                    {item.scenario && (
                      <span className="ml-2">Scenario: {item.scenario}</span>
                    )}
                    {item.persona && (
                      <span className="ml-2">Persona: {item.persona}</span>
                    )}
                    {item.attackCategory && (
                      <span className="ml-2">Attack: {item.attackCategory}</span>
                    )}
                  </div>
                </div>

                <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 mt-1" />
              </button>
            ))}

            {pagedItems.length === 0 && (
              <div className="py-12 text-center">
                <p className="text-sm text-muted-foreground">
                  No conversations match the current filters.
                </p>
              </div>
            )}
          </div>
        </ScrollArea>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between pt-2">
            <span className="text-xs text-muted-foreground">
              Page {page} of {totalPages} · {filteredItems.length} total
            </span>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="xs"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                Prev
              </Button>
              <Button
                variant="outline"
                size="xs"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
