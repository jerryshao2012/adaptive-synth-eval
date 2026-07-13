"use client";

import React, { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CheckCircle2,
  AlertTriangle,
  Clock,
  Hash,
  RefreshCw,
  Play,
  RotateCcw,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import type { RunSummary, MonitoringRunStatus, ArtifactValidation } from "@/types/evaluation";
import { cn } from "@/lib/utils";

// ---- Verdict color and icon maps ----

function formatElapsed(ms: number): string {
  const hours = Math.floor(ms / 3600000);
  const minutes = Math.floor((ms % 3600000) / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  const milliseconds = Math.floor(ms % 1000);

  const padMs = String(milliseconds).padStart(3, "0");

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}.${padMs}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}.${padMs}s`;
  }
  return `${seconds}.${padMs}s`;
}

interface RunSelectorHeaderProps {
  selectedRun: RunSummary | null;
  monitoringStatus: MonitoringRunStatus | null;
  runs: RunSummary[];
  onSelectRun: (runId: string) => void;
  onStartRun: (runId: string) => void;
  onContinueRun: (runId: string) => void;
  isStarting: boolean;
  validation?: ArtifactValidation | null;
  onRefresh: () => void;
}

export function RunSelectorHeader({
  selectedRun,
  monitoringStatus,
  runs,
  onSelectRun,
  onStartRun,
  onContinueRun,
  isStarting,
  validation,
  onRefresh,
}: RunSelectorHeaderProps) {
  const [elapsedMs, setElapsedMs] = useState<number>(0);
  const status = monitoringStatus?.monitoringStatus ?? selectedRun?.monitoringStatus;
  const startedAt = (monitoringStatus?.state?.started_at as string) || selectedRun?.startedAt;

  const isRunning = status === "in_progress";
  const isQueued = status === "queued";
  const isActionDisabled = isStarting || isRunning || isQueued;

  useEffect(() => {
    if (!isRunning) return;

    const startTimestamp = startedAt ? new Date(startedAt).getTime() : Date.now();
    let animationFrameId: number;

    const updateTimer = () => {
      const elapsed = Date.now() - startTimestamp;
      setElapsedMs(elapsed > 0 ? elapsed : 0);
      animationFrameId = requestAnimationFrame(updateTimer);
    };

    animationFrameId = requestAnimationFrame(updateTimer);

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [isRunning, startedAt]);

  const displayElapsedMs = isRunning ? elapsedMs : 0;

  if (!selectedRun) {
    return (
      <Card className="border-border bg-card mb-6">
        <CardContent className="py-6 text-center">
          <p className="text-muted-foreground text-sm">No run selected.</p>
          {runs.length > 0 && (
            <div className="mt-2 flex flex-wrap justify-center gap-2">
              {runs.slice(0, 5).map((run) => (
                <Button
                  key={run.runId}
                  variant="outline"
                  size="sm"
                  onClick={() => onSelectRun(run.runId)}
                >
                  {run.runId}
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  const updatedAt = monitoringStatus?.updatedAt ?? selectedRun.updatedAt;
  const hasIssues = validation?.issues && validation.issues.length > 0;

  return (
    <Card className="border-border bg-card mb-6">
      <CardContent className="py-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          {/* Left: Run identity */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              {/* Run selector dropdown */}
              <div className="relative">
                <select
                  value={selectedRun.runId}
                  onChange={(e) => onSelectRun(e.target.value)}
                  aria-label="Select evaluation run"
                  className="appearance-none h-9 rounded-lg border border-border bg-background px-3 pr-8 text-sm font-semibold text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50 cursor-pointer"
                >
                  {runs.map((run) => (
                    <option key={run.runId} value={run.runId}>
                      {run.runId}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-2 flex items-center">
                  <svg className="h-3 w-3 text-muted-foreground" fill="none" viewBox="0 0 8 5">
                    <path d="M1 1l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </div>
              </div>

              {/* Status badge */}
              <Badge
                variant="outline"
                className={cn(
                  "text-xs font-medium capitalize",
                  status === "completed" && "border-emerald-500/30 text-emerald-500",
                  status === "in_progress" && "border-amber-500/30 text-amber-500",
                  status === "queued" && "border-sky-500/30 text-sky-500",
                  status === "not_started" && "border-muted-foreground/30 text-muted-foreground"
                )}
              >
                {status === "in_progress" ? "In Progress" : status === "not_started" ? "Not Started" : status}
              </Badge>

              {/* Mode */}
              {selectedRun.mode && (
                <Badge variant="secondary" className="text-xs">
                  {selectedRun.mode}
                </Badge>
              )}
            </div>

            {/* Meta row */}
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {updatedAt && (
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  Updated {formatDistanceToNow(new Date(updatedAt), { addSuffix: true })}
                </span>
              )}
              {selectedRun.completedAt && (
                <span>
                  Completed {formatDistanceToNow(new Date(selectedRun.completedAt), { addSuffix: true })}
                </span>
              )}
              {monitoringStatus?.evaluationFingerprint && (
                <span className="inline-flex items-center gap-1">
                  <Hash className="h-3 w-3" />
                  Eval: {monitoringStatus.evaluationFingerprint.substring(0, 8)}
                </span>
              )}
              {validation && (
                <span
                  className={cn(
                    "inline-flex items-center gap-1",
                    validation.isValid ? "text-emerald-500" : "text-amber-500"
                  )}
                >
                  {validation.isValid ? (
                    <CheckCircle2 className="h-3 w-3" />
                  ) : (
                    <AlertTriangle className="h-3 w-3" />
                  )}
                  {validation.artifactFreshness.monitoringScores.recordCount} records
                </span>
              )}
            </div>

            {/* Validation issues */}
            {hasIssues && (
              <div className="mt-2 space-y-1">
                {validation!.issues.map((issue, i) => (
                  <div
                    key={i}
                    className={cn(
                      "text-xs rounded-md px-2 py-1",
                      issue.severity === "error"
                        ? "bg-red-500/10 text-red-500"
                        : "bg-amber-500/10 text-amber-500"
                    )}
                  >
                    <span className="font-medium">{issue.artifact}:</span> {issue.message}
                    {issue.details && (
                      <span className="block text-muted-foreground mt-0.5">{issue.details}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="outline" size="sm" onClick={onRefresh} title="Refresh data">
              <RefreshCw className="h-4 w-4" />
              <span className="hidden sm:inline ml-1.5">Refresh</span>
            </Button>

            {selectedRun.canStart && (
              <Button
                size="sm"
                onClick={() => onStartRun(selectedRun.runId)}
                disabled={isActionDisabled}
              >
                {isStarting ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                <span className="ml-1.5">Start</span>
              </Button>
            )}

            {selectedRun.canContinue && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => onContinueRun(selectedRun.runId)}
                disabled={isActionDisabled}
              >
                <RotateCcw className="h-4 w-4" />
                <span className="ml-1.5">Continue</span>
              </Button>
            )}
          </div>
        </div>

        {/* Progress bar for in-progress runs */}
        {status === "in_progress" && (
          <div className="mt-4">
            <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
              <div className="flex items-center gap-2">
                <span>Evaluation Progress</span>
                <span className="font-mono text-primary bg-primary/10 px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wider animate-pulse">
                  {formatElapsed(displayElapsedMs)}
                </span>
              </div>
              <span>{monitoringStatus?.progress.percent ?? selectedRun.progress.percent}%</span>
            </div>
            <progress
              className="h-1.5 w-full overflow-hidden rounded-full [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary [&::-moz-progress-bar]:bg-primary"
              max={100}
              value={monitoringStatus?.progress.percent ?? selectedRun.progress.percent ?? 0}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
