"use client";

import { useEffect, useMemo, useState } from "react";
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

function JsonPrimitive({ value }: { value: string | number | boolean | null }) {
  if (value === null) {
    return <span className="text-muted-foreground">null</span>;
  }

  if (typeof value === "string") {
    return <span className="text-sky-600 dark:text-sky-300">{value}</span>;
  }

  if (typeof value === "number") {
    return <span className="text-violet-600 dark:text-violet-300">{value}</span>;
  }

  return <span className="text-amber-600 dark:text-amber-300">{String(value)}</span>;
}

function JsonValue({
  value,
  depth = 0,
  suffix,
}: {
  value: unknown;
  depth?: number;
  suffix?: React.ReactNode;
}) {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return (
      <>
        <JsonPrimitive value={value} />
        {suffix}
      </>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <span>
          []{suffix}
        </span>
      );
    }

    return (
      <div>
        <span>[</span>
        <div className="ml-4 border-l border-border/50 pl-3">
          {value.map((item, index) => (
            <JsonValue
              key={`${depth}-${index}`}
              value={item}
              depth={depth + 1}
              suffix={index < value.length - 1 ? "," : undefined}
            />
          ))}
        </div>
        <span>]{suffix}</span>
      </div>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value);

    if (entries.length === 0) {
      return (
        <span>
          {"{}"}{suffix}
        </span>
      );
    }

    return (
      <div>
        <span>{"{"}</span>
        <div className="ml-4 border-l border-border/50 pl-3">
          {entries.map(([key, entryValue], index) => (
            <div key={`${depth}-${key}`}>
              <span className="text-emerald-700 dark:text-emerald-300">{key}</span>
              <span>: </span>
              <JsonValue
                value={entryValue}
                depth={depth + 1}
                suffix={index < entries.length - 1 ? "," : undefined}
              />
            </div>
          ))}
        </div>
        <span>{"}"}{suffix}</span>
      </div>
    );
  }

  return (
    <span>
      {String(value)}
      {suffix}
    </span>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border/70 bg-muted/25 p-3 font-mono text-[11px] leading-5 text-foreground shadow-inner">
      <JsonValue value={value} />
    </div>
  );
}

export function TraceDrawer({
  open,
  point,
  trace,
  isLoading,
  errorMessage,
  onClose,
}: TraceDrawerProps) {
  const [isPointSwitchAnimating, setIsPointSwitchAnimating] = useState(false);
  const pointKey = useMemo(() => {
    if (!point) return "";
    return [
      point.runId,
      point.conversationId || "",
      point.turnId,
      point.timestamp,
      point.metricGroup,
      point.metricKey,
    ].join("|");
  }, [point]);

  useEffect(() => {
    // When a new point is selected, schedule the animation to start.
    // This is deferred via setTimeout to avoid a synchronous setState call
    // within the effect, which would trigger a cascading render.
    if (pointKey) {
      const timerId = setTimeout(() => setIsPointSwitchAnimating(true), 0);
      return () => clearTimeout(timerId);
    }
  }, [pointKey]);

  useEffect(() => {
    // When the animation is active, set a timer to turn it off after a short
    // delay. This ensures the loading transition is visible even for fast loads.
    if (isPointSwitchAnimating) {
      const timerId = window.setTimeout(() => {
        setIsPointSwitchAnimating(false);
      }, 260);
      return () => window.clearTimeout(timerId);
    }
  }, [isPointSwitchAnimating]);

  // The loading state should show if the parent says it's loading, or if
  // our animation is running for a newly selected point.
  const showLoadingState = isLoading || (isPointSwitchAnimating && !!pointKey);

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
          "fixed top-16 right-0 bottom-0 z-50 w-full border-l border-border bg-card shadow-2xl transition-transform duration-300 ease-out lg:w-(--trace-panel-width)",
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

          {showLoadingState && (
            <div className="space-y-3 rounded-md border border-border bg-background p-3 text-sm text-muted-foreground">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Resolving source records for this point...
              </div>
              <div className="space-y-2 animate-pulse">
                <div className="h-3 w-2/5 rounded bg-muted/60" />
                <div className="h-3 w-full rounded bg-muted/50" />
                <div className="h-3 w-[92%] rounded bg-muted/50" />
                <div className="h-3 w-[78%] rounded bg-muted/50" />
              </div>
            </div>
          )}

          {!showLoadingState && errorMessage && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>{errorMessage}</div>
            </div>
          )}

          {!showLoadingState && !errorMessage && trace && (
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
                  <JsonBlock value={trace.evaluationRecord} />
                </section>
              )}

              <section className="rounded-md border border-border bg-background p-3">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Chat History Row
                </h3>
                {trace.chatHistoryRecord ? (
                  <JsonBlock value={trace.chatHistoryRecord} />
                ) : (
                  <p className="text-xs text-muted-foreground">No chat_history row matched this point.</p>
                )}
              </section>

              <section className="rounded-md border border-border bg-background p-3">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Turns Row
                </h3>
                {trace.turnRecord ? (
                  <JsonBlock value={trace.turnRecord} />
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

          {!showLoadingState && !errorMessage && !trace && !point && (
            <div className="rounded-md border border-border bg-background p-3 text-sm text-muted-foreground">
              Click a point in any line chart to load the exact monitoring row and related source records.
            </div>
          )}
        </ScrollArea>
      </aside>
    </>
  );
}
