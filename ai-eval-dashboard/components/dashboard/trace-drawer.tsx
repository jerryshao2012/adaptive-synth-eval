"use client";

import { format, parseISO } from "date-fns";
import { X, AlertTriangle, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { MetricBadge } from "@/components/shared/empty-state";
import { cn } from "@/lib/utils";
import type { MetricPointIdentity, TraceDetailsResponse } from "@/types/evaluation";

interface TraceDrawerProps {
  open: boolean;
  point: MetricPointIdentity | null;
  trace: TraceDetailsResponse | undefined;
  isLoading: boolean;
  errorMessage?: string;
  onClose: () => void;
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function TraceDrawer({
  open,
  point,
  trace,
  isLoading,
  errorMessage,
  onClose,
}: TraceDrawerProps) {
  const resolvedMetricStatus =
    trace && trace.evaluationRecord
      ? trace.point.metricGroup === "safety"
        ? trace.evaluationRecord.safety_status
        : trace.point.metricGroup === "performance"
          ? trace.evaluationRecord.performance_status
          : trace.point.metricKey === "llm_latency_ms"
            ? trace.evaluationRecord.system_reliability.llm_latency_status
            : trace.point.metricKey === "guardrail_latency_ms"
              ? trace.evaluationRecord.system_reliability.guardrail_latency_status
              : trace.point.metricKey === "total_latency_ms"
                ? trace.evaluationRecord.system_reliability.total_latency_status
                : trace.evaluationRecord.system_reliability.availability_status
      : null;

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close details panel"
          className="fixed inset-0 z-40 bg-black/35 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "fixed top-16 right-0 bottom-0 z-50 w-full max-w-[520px] border-l border-border bg-card shadow-2xl transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        <div className="flex h-14 items-center justify-between border-b border-border px-4">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Trace Details</div>
            {point ? (
              <div className="truncate text-xs text-muted-foreground">
                {point.metricGroup} / {point.metricKey}
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">Select a chart point to inspect source records.</div>
            )}
          </div>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close details panel">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <ScrollArea className="h-[calc(100%-3.5rem)] p-4">
          {point && (
            <div className="mb-4 rounded-md border border-border bg-background p-3 text-xs text-muted-foreground">
              <div className="mb-1 flex items-center gap-2 text-foreground">
                <span className="font-medium">Point Identity</span>
                <Badge variant="outline" className="text-[10px] font-mono">
                  {point.turnId}
                </Badge>
              </div>
              <div>Run: {point.runId}</div>
              <div>Conversation: {point.conversationId || "(not provided)"}</div>
              <div>Timestamp: {point.timestamp}</div>
            </div>
          )}

          {isLoading && (
            <div className="flex items-center gap-2 rounded-md border border-border bg-background p-3 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Resolving source records for this point...
            </div>
          )}

          {!isLoading && errorMessage && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>{errorMessage}</div>
            </div>
          )}

          {!isLoading && !errorMessage && trace && (
            <div className="space-y-4">
              {trace.evaluationRecord && (
                <section className="rounded-md border border-border bg-background p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Monitoring Score Row
                    </h3>
                    {resolvedMetricStatus && <MetricBadge status={resolvedMetricStatus} />}
                  </div>
                  <p className="mb-2 text-xs text-muted-foreground">
                    {format(parseISO(trace.evaluationRecord.timestamp), "PPpp")}
                  </p>
                  <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[11px] leading-5 text-foreground">
                    {pretty(trace.evaluationRecord)}
                  </pre>
                </section>
              )}

              <section className="rounded-md border border-border bg-background p-3">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Chat History Row
                </h3>
                {trace.chatHistoryRecord ? (
                  <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[11px] leading-5 text-foreground">
                    {pretty(trace.chatHistoryRecord)}
                  </pre>
                ) : (
                  <p className="text-xs text-muted-foreground">No chat_history row matched this point.</p>
                )}
              </section>

              <section className="rounded-md border border-border bg-background p-3">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Turns Row
                </h3>
                {trace.turnRecord ? (
                  <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[11px] leading-5 text-foreground">
                    {pretty(trace.turnRecord)}
                  </pre>
                ) : (
                  <p className="text-xs text-muted-foreground">No turns row matched this point.</p>
                )}
              </section>

              {!trace.evaluationRecord && !trace.chatHistoryRecord && !trace.turnRecord && (
                <div className="rounded-md border border-border bg-background p-3 text-xs text-muted-foreground">
                  {trace.notFoundReason || "No source artifacts were found for this selected point."}
                </div>
              )}
            </div>
          )}

          {!isLoading && !errorMessage && !trace && !point && (
            <div className="rounded-md border border-border bg-background p-3 text-sm text-muted-foreground">
              Click a point in any line chart to load the exact monitoring row and related source records.
            </div>
          )}
        </ScrollArea>
      </aside>
    </>
  );
}
