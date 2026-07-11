"use client";

import { useMemo } from "react";
import {
  CheckCircle2,
  Circle,
  Loader2,
  Play,
  RotateCcw,
  SlidersHorizontal,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { EvalRunParameters, RunSummary } from "@/types/evaluation";

interface RunThreadListProps {
  runs: RunSummary[];
  selectedRunId: string;
  onSelectRun: (runId: string) => void;
  globalDefaults: EvalRunParameters;
  onGlobalChange: (next: EvalRunParameters) => void;
  overrides: Record<string, Partial<EvalRunParameters>>;
  expandedOverrideRunId: string | null;
  onToggleOverrideEditor: (runId: string) => void;
  onOverrideChange: (runId: string, patch: Partial<EvalRunParameters>) => void;
  onClearOverride: (runId: string) => void;
  pendingActionRunId?: string;
  onStartRun: (runId: string, params: EvalRunParameters) => void;
  onResumeRun: (runId: string, params: EvalRunParameters) => void;
}

function effectiveParams(
  runId: string,
  defaults: EvalRunParameters,
  overrides: Record<string, Partial<EvalRunParameters>>
): EvalRunParameters {
  const patch = overrides[runId] || {};
  return {
    sampleSize: Number(patch.sampleSize ?? defaults.sampleSize),
    intervalMinutes: Number(patch.intervalMinutes ?? defaults.intervalMinutes),
  };
}

function rowStatusIcon(run: RunSummary) {
  if (run.monitoringStatus === "completed") {
    return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
  }
  if (run.monitoringStatus === "in_progress") {
    return <Loader2 className="h-4 w-4 text-amber-400 animate-spin" />;
  }
  if (run.monitoringStatus === "queued") {
    return <Circle className="h-4 w-4 text-sky-400" />;
  }
  return <Circle className="h-4 w-4 text-muted-foreground" />;
}

function rowStatusText(run: RunSummary): string {
  switch (run.monitoringStatus) {
    case "completed":
      return "Done";
    case "in_progress":
      return "Running";
    case "queued":
      return "Queued";
    default:
      return "Not Started";
  }
}

function NumberField({
  label,
  value,
  onChange,
  min,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <input
        type="number"
        min={min}
        value={value}
        onChange={(event) => onChange(Number(event.target.value || 0))}
        className="h-8 rounded-md border border-border bg-background px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      />
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 rounded-md border border-border bg-background px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      />
    </label>
  );
}

export function RunThreadList({
  runs,
  selectedRunId,
  onSelectRun,
  globalDefaults,
  onGlobalChange,
  overrides,
  expandedOverrideRunId,
  onToggleOverrideEditor,
  onOverrideChange,
  onClearOverride,
  pendingActionRunId,
  onStartRun,
  onResumeRun,
}: RunThreadListProps) {
  const orderedRuns = useMemo(() => runs, [runs]);

  return (
    <Card className="border-border bg-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold text-foreground">
          Threads
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-md border border-border bg-background p-3">
          <div className="mb-2 text-xs font-medium text-foreground">Global Eval Defaults</div>
          <div className="grid grid-cols-2 gap-2">
            <NumberField
              label="Sample Size"
              value={globalDefaults.sampleSize}
              min={1}
              onChange={(sampleSize) => onGlobalChange({ ...globalDefaults, sampleSize })}
            />
            <NumberField
              label="Interval Min"
              value={globalDefaults.intervalMinutes}
              min={1}
              onChange={(intervalMinutes) => onGlobalChange({ ...globalDefaults, intervalMinutes })}
            />
          </div>
        </div>

        <ScrollArea className="h-95 pr-2">
          <div className="space-y-2">
            {orderedRuns.map((run) => {
              const isSelected = selectedRunId === run.runId;
              const params = effectiveParams(run.runId, globalDefaults, overrides);
              const isExpanded = expandedOverrideRunId === run.runId;
              const isPending = pendingActionRunId === run.runId;

              return (
                <div key={run.runId} className="space-y-2">
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelectRun(run.runId)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectRun(run.runId);
                      }
                    }}
                    className={cn(
                      "group w-full rounded-md border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                      isSelected
                        ? "border-primary bg-accent"
                        : "border-border bg-background hover:bg-muted/50"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          {rowStatusIcon(run)}
                          <span className="truncate text-sm font-medium text-foreground">{run.runId}</span>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {rowStatusText(run)} · {run.progress.completed}/{run.progress.total} rows · {run.progress.percent}%
                        </div>
                      </div>

                      <div className="flex items-center gap-1">
                        {run.canStart && (
                          <Button
                            type="button"
                            size="icon-xs"
                            variant="ghost"
                            onClick={(event) => {
                              event.stopPropagation();
                              onStartRun(run.runId, params);
                            }}
                            disabled={isPending}
                            title="Start evaluation"
                          >
                            {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                          </Button>
                        )}
                        {run.canContinue && (
                          <Button
                            type="button"
                            size="icon-xs"
                            variant="ghost"
                            onClick={(event) => {
                              event.stopPropagation();
                              onResumeRun(run.runId, params);
                            }}
                            disabled={isPending}
                            title="Resume evaluation"
                          >
                            {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                          </Button>
                        )}
                        <Button
                          type="button"
                          size="icon-xs"
                          variant={isExpanded ? "secondary" : "ghost"}
                          onClick={(event) => {
                            event.stopPropagation();
                            onToggleOverrideEditor(run.runId);
                          }}
                          title="Override eval parameters"
                        >
                          <SlidersHorizontal className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="rounded-md border border-border bg-background p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <div className="text-xs font-medium text-foreground">Per-Thread Override</div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="xs"
                          onClick={() => onClearOverride(run.runId)}
                        >
                          Clear
                        </Button>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <NumberField
                          label="Sample Size"
                          value={params.sampleSize}
                          min={1}
                          onChange={(sampleSize) => onOverrideChange(run.runId, { sampleSize })}
                        />
                        <NumberField
                          label="Interval Min"
                          value={params.intervalMinutes}
                          min={1}
                          onChange={(intervalMinutes) => onOverrideChange(run.runId, { intervalMinutes })}
                        />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
