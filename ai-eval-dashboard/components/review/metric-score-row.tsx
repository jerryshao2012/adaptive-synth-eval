"use client";

import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MetricBadge } from "@/components/shared/empty-state";
import { Info, ArrowRight, TrendingUp, TrendingDown } from "lucide-react";
import type { MetricScoreStatus, MetricThreshold } from "@/types/evaluation";

const SCORE_OPTIONS = Array.from({ length: 21 }, (_, i) => {
  const pct = i * 5;
  return { value: String(pct), label: `${pct}%` };
});

interface MetricScoreRowProps {
  label: string;
  metricKey: string;
  description?: string;
  aiScore: number;
  aiStatus: MetricScoreStatus;
  humanScore: number;
  humanStatus: MetricScoreStatus;
  threshold: MetricThreshold;
  onScoreChange: (metricKey: string, score: number) => void;
  onStatusChange: (metricKey: string, status: MetricScoreStatus) => void;
  disabled?: boolean;
}

export function MetricScoreRow({
  label,
  metricKey,
  description,
  aiScore,
  aiStatus,
  humanScore,
  humanStatus,
  threshold,
  onScoreChange,
  onStatusChange,
  disabled = false,
}: MetricScoreRowProps) {
  const delta = humanScore - aiScore;
  const hasDelta = Math.abs(delta) >= 5;
  const showWarning = Math.abs(delta) >= 10;

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-md border px-3 py-2.5 transition-colors",
        showWarning
          ? "border-warning/30 bg-warning/5"
          : "border-border bg-transparent"
      )}
    >
      {/* Label + Tooltip */}
      <div className="w-[180px] shrink-0 flex items-center gap-1.5 min-w-0">
        <span className="text-xs font-medium text-foreground truncate">
          {label}
        </span>
        {description && (
          <Tooltip>
            <TooltipTrigger>
              <Info className="h-3 w-3 text-muted-foreground cursor-help shrink-0" />
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-[320px] text-xs leading-relaxed">
              <p className="mb-1">{description}</p>
              <p className="text-muted-foreground">
                Fail below {threshold.failBelow}% · Warn below {threshold.warnBelow}%
              </p>
            </TooltipContent>
          </Tooltip>
        )}
      </div>

      {/* AI Score (read-only) */}
      <div className="flex items-center gap-1.5 shrink-0">
        <span
          className="text-xs font-mono tabular-nums font-medium px-1.5 py-0.5 rounded"
          style={{ color: "var(--ai-review)", backgroundColor: "color-mix(in srgb, var(--ai-review) 15%, transparent)" }}
        >
          {aiScore}%
        </span>
        <MetricBadge status={aiStatus} />
      </div>

      {/* Arrow */}
      <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />

      {/* Human Score (editable) */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Select
          value={String(humanScore)}
          onValueChange={(v) => onScoreChange(metricKey, Number(v))}
          disabled={disabled}
        >
          <SelectTrigger
            className="h-7 w-[80px] text-xs font-mono tabular-nums"
            style={{ borderColor: "var(--human-review)" }}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SCORE_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={humanStatus}
          onValueChange={(v) =>
            onStatusChange(metricKey, v as MetricScoreStatus)
          }
          disabled={disabled}
        >
          <SelectTrigger className="h-7 w-[80px] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="pass">Pass</SelectItem>
            <SelectItem value="warn">Warn</SelectItem>
            <SelectItem value="fail">Fail</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Delta indicator */}
      {hasDelta && (
        <span
          className={cn(
            "flex items-center gap-0.5 text-[11px] font-medium shrink-0",
            delta > 0 ? "text-[var(--delta-positive)]" : "text-[var(--delta-negative)]"
          )}
        >
          {delta > 0 ? (
            <TrendingUp className="h-3 w-3" />
          ) : (
            <TrendingDown className="h-3 w-3" />
          )}
          {delta > 0 ? "+" : ""}
          {delta}%
        </span>
      )}
    </div>
  );
}
