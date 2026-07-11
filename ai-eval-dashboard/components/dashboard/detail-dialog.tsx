"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { MetricBadge } from "@/components/shared/empty-state";
import type { EvaluationRecord, MetricValue } from "@/types/evaluation";
import { METRIC_THRESHOLDS } from "@/lib/metrics";
import { format, parseISO } from "date-fns";
import { Clock, Cpu, Hash, FileText, MessageSquare, User } from "lucide-react";

interface DetailDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  record: EvaluationRecord | null;
  metricGroup: "safety" | "performance" | null;
  metricKey: string | null;
}

export function DetailDialog({
  open,
  onOpenChange,
  record,
  metricGroup,
  metricKey,
}: DetailDialogProps) {
  if (!record || !metricGroup || !metricKey) return null;

  const metrics =
    metricGroup === "safety"
      ? (record.safety_metrics as unknown as Record<string, MetricValue>)
      : (record.performance_metrics as unknown as Record<string, MetricValue>);
  const metric = metrics[metricKey];
  if (!metric) return null;

  const threshold = METRIC_THRESHOLDS[metricKey];
  const gaugeAngle = (metric.percent / 100) * 180;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg border-border bg-card text-foreground">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <DialogTitle className="text-base font-semibold">
              {threshold?.label || metricKey}
            </DialogTitle>
            {record.value_versions && (
              <Badge variant="outline" className="text-[10px] font-mono">
                {record.value_versions.evaluation_fingerprint.substring(0, 8)}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {format(parseISO(record.timestamp), "PPpp")} · Turn {record.turn_id}
          </p>
        </DialogHeader>

        <div className="space-y-4">
          {/* Score gauge */}
          <div className="flex items-center gap-4">
            <div className="relative flex items-center justify-center">
              <svg width="100" height="56" viewBox="0 0 100 56">
                <path
                  d="M10 50 A40 40 0 0 1 90 50"
                  fill="none"
                  stroke="hsl(214 26% 24%)"
                  strokeWidth="8"
                  strokeLinecap="round"
                />
                <path
                  d="M10 50 A40 40 0 0 1 90 50"
                  fill="none"
                  stroke={
                    metric.status === "pass"
                      ? "hsl(142 71% 45%)"
                      : metric.status === "warn"
                        ? "hsl(43 74% 66%)"
                        : "hsl(0 100% 47%)"
                  }
                  strokeWidth="8"
                  strokeLinecap="round"
                  strokeDasharray={`${gaugeAngle} 180`}
                />
              </svg>
              <span className="absolute text-2xl font-bold tabular-nums">
                {metric.percent}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <MetricBadge status={metric.status} />
              <span className="text-sm font-medium">
                Score: {metric.score.toFixed(3)}
              </span>
              <span className="text-xs text-muted-foreground">
                Fail below {threshold?.failBelow}% · Warn below {threshold?.warnBelow}%
              </span>
            </div>
          </div>

          {/* Detail & Reason */}
          <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
            <div className="flex items-start gap-2">
              <FileText className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
              <div>
                <p className="text-xs font-medium text-foreground">Detail</p>
                <p className="text-xs text-muted-foreground">{metric.detail}</p>
              </div>
            </div>
            {metric.reason && (
              <div className="flex items-start gap-2">
                <Cpu className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs font-medium text-foreground">Reason</p>
                  <p className="text-xs text-muted-foreground">{metric.reason}</p>
                </div>
              </div>
            )}
            {record.value_versions && (
              <div className="flex items-start gap-2">
                <Hash className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs font-medium text-foreground">
                    Evaluation Version
                  </p>
                  <p className="text-xs text-muted-foreground font-mono">
                    fingerprint: {record.value_versions.evaluation_fingerprint}
                  </p>
                  <p className="text-xs text-muted-foreground font-mono">
                    model: {record.value_versions.resolved_model.provider}/
                    {record.value_versions.resolved_model.deployment}
                  </p>
                  {record.value_versions.metrics[metricKey] && (
                    <p className="text-xs text-muted-foreground font-mono">
                      policy: {record.value_versions.metrics[metricKey].policy_fingerprint}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* User / Response text */}
          <div className="space-y-2">
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <User className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  User Input
                </span>
              </div>
              <p className="text-xs text-foreground line-clamp-4">
                {record.user_text}
              </p>
            </div>
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  LLM Response
                </span>
              </div>
              <p className="text-xs text-foreground line-clamp-4">
                {record.response_text}
              </p>
            </div>
          </div>

          {/* Latency context */}
          <div className="flex items-center gap-4 text-xs text-muted-foreground border-t border-border pt-3">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              LLM: {record.system_reliability.llm_latency_ms}ms
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Guardrail: {record.system_reliability.guardrail_latency_ms}ms
            </span>
            <span>
              Variant: {record.variant}
            </span>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
