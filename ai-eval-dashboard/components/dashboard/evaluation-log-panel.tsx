"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { ChevronDown, FileText, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useMonitoringLog } from "@/hooks/use-evaluations";
import { cn } from "@/lib/utils";
import type { RunSummary } from "@/types/evaluation";

type MonitoringStatus = RunSummary["monitoringStatus"];

interface EvaluationLogPanelProps {
  runId: string;
  monitoringStatus?: MonitoringStatus;
}

export function EvaluationLogPanel({
  runId,
  monitoringStatus,
}: EvaluationLogPanelProps) {
  const panelId = useId();
  const viewportRef = useRef<HTMLPreElement>(null);
  const wasAtBottomRef = useRef(true);
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const open = openRunId === runId;

  useEffect(() => {
    wasAtBottomRef.current = true;
    if (viewportRef.current) viewportRef.current.scrollTop = 0;
  }, [runId]);
  const active =
    monitoringStatus === "queued" || monitoringStatus === "in_progress";
  const canRefresh =
    monitoringStatus === "completed" || monitoringStatus === "incomplete";
  const { data, error, isError, isFetching, isLoading, refetch } =
    useMonitoringLog(runId, open, active);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!open || !viewport || !wasAtBottomRef.current) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [data?.content, open]);

  function updateScrollPosition() {
    const viewport = viewportRef.current;
    if (!viewport) return;
    wasAtBottomRef.current =
      viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop <= 2;
  }

  return (
    <Card className="mb-6 border-border bg-card">
      <CardContent className="py-3">
        <div className="flex items-center justify-between gap-3">
          <Button
            type="button"
            variant="ghost"
            className="min-w-0 justify-start px-1 text-foreground"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={open ? "Hide evaluation log" : "Show evaluation log"}
            onClick={() => setOpenRunId(open ? null : runId)}
          >
            <FileText aria-hidden="true" />
            <span>Evaluation log</span>
            <ChevronDown
              aria-hidden="true"
              className={cn(
                "transition-transform",
                open && "rotate-180"
              )}
            />
          </Button>

          {open && canRefresh && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label="Refresh evaluation log"
              disabled={isFetching}
              onClick={() => void refetch()}
            >
              <RefreshCw
                aria-hidden="true"
                className={cn(isFetching && "animate-spin")}
              />
              Refresh
            </Button>
          )}
        </div>

        {open && (
          <div id={panelId} className="mt-3 border-t border-border pt-3">
            {isLoading ? (
              <p role="status" className="text-sm text-muted-foreground">
                Loading evaluation log…
              </p>
            ) : isError ? (
              <p role="alert" className="text-sm text-destructive">
                {error instanceof Error
                  ? error.message
                  : "Failed to load the evaluation log."}
              </p>
            ) : !data?.content ? (
              <p className="text-sm text-muted-foreground">
                No dashboard evaluation log is available yet.
              </p>
            ) : (
              <>
                {data.truncated && (
                  <p role="status" className="mb-2 text-xs text-muted-foreground">
                    Showing the most recent 256 KiB of this evaluation log.
                  </p>
                )}
                <pre
                  ref={viewportRef}
                  role="log"
                  aria-label={`Evaluation log for ${runId}`}
                  onScroll={updateScrollPosition}
                  className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs leading-relaxed text-foreground"
                >
                  {data.content}
                </pre>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
