"use client";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { TrendIndicator } from "@/components/shared/empty-state";
import type { ReactNode } from "react";

interface KpiCardProps {
  label: string;
  value: string | number;
  trend?: number;
  trendLabel?: string;
  icon?: ReactNode;
  className?: string;
}

export function KpiCard({
  label,
  value,
  trend,
  trendLabel,
  icon,
  className,
}: KpiCardProps) {
  return (
    <Card
      className={cn(
        "border-border bg-card p-4 transition-colors",
        "hover:border-[color-mix(in_srgb,var(--primary)_20%,transparent)]",
        className
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          {label}
        </span>
        {icon && (
          <span className="text-muted-foreground">{icon}</span>
        )}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-foreground tabular-nums">
          {value}
        </span>
      </div>
      {(trend !== undefined) && (
        <div className="mt-1">
          <TrendIndicator value={trend} label={trendLabel} />
        </div>
      )}
    </Card>
  );
}
