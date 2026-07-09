"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Maximize2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Info } from "lucide-react";
import { TimePeriodSelector } from "./time-period-selector";
import type { TimePeriodPreset } from "@/types/evaluation";
import { MetricBadge } from "@/components/shared/empty-state";

interface ChartCardProps {
  title: string;
  tooltip?: string;
  status?: "pass" | "warn" | "fail";
  latestValue?: string;
  period: TimePeriodPreset;
  onPeriodChange: (p: TimePeriodPreset) => void;
  isLoading?: boolean;
  colSpan?: "full" | "half";
  children: ReactNode;
  summary?: ReactNode;
  footer?: ReactNode;
  onViewDetails?: () => void;
}

export function ChartCard({
  title,
  tooltip,
  status,
  latestValue,
  period,
  onPeriodChange,
  isLoading = false,
  colSpan = "half",
  children,
  summary,
  footer,
  onViewDetails,
}: ChartCardProps) {
  if (isLoading) {
    return (
      <Card
        className={cn(
          "border-border bg-card",
          colSpan === "full" ? "col-span-2" : "col-span-1"
        )}
      >
        <CardHeader className="pb-2">
          <Skeleton className="h-5 w-32" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[200px] w-full" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      className={cn(
        "border-border bg-card transition-colors",
        "hover:border-[color-mix(in_srgb,var(--primary)_30%,transparent)]",
        colSpan === "full" ? "col-span-2" : "col-span-1"
      )}
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <CardTitle className="text-sm font-semibold text-foreground truncate">
              {title}
            </CardTitle>
            {tooltip && (
              <Tooltip>
                <TooltipTrigger>
                  <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help shrink-0" />
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[280px] text-xs">
                  {tooltip}
                </TooltipContent>
              </Tooltip>
            )}
            {status && <MetricBadge status={status} />}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {latestValue && (
              <span className="text-xs font-mono tabular-nums text-muted-foreground">
                {latestValue}
              </span>
            )}
            <TimePeriodSelector value={period} onChange={onPeriodChange} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="pb-2">
        {children}
        {summary && (
          <div className="flex items-center justify-between mt-3 pt-2 border-t border-border-light">
            {summary}
          </div>
        )}
      </CardContent>
      {onViewDetails && (
        <div className="px-6 pb-4">
          <Button
            variant="ghost"
            size="sm"
            className="w-full text-xs text-muted-foreground hover:text-foreground"
            onClick={onViewDetails}
          >
            <Maximize2 className="h-3.5 w-3.5 mr-1.5" />
            View Details
          </Button>
        </div>
      )}
      {footer && !onViewDetails && (
        <div className="px-6 pb-4">{footer}</div>
      )}
    </Card>
  );
}

export function ChartSummaryBar({
  avg,
  min,
  max,
  valueFormatter = (v) => `${v}`,
}: {
  avg: number;
  min: number;
  max: number;
  valueFormatter?: (v: number) => string;
}) {
  return (
    <div className="flex items-center gap-4 text-xs text-muted-foreground w-full">
      <span>
        Avg:{" "}
        <span className="font-medium text-foreground">
          {valueFormatter(avg)}
        </span>
      </span>
      <span>
        Min:{" "}
        <span className="font-medium text-foreground">
          {valueFormatter(min)}
        </span>
      </span>
      <span>
        Max:{" "}
        <span className="font-medium text-foreground">
          {valueFormatter(max)}
        </span>
      </span>
    </div>
  );
}
