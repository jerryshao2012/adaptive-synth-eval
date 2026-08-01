"use client";

import { Card, CardContent } from "@/components/ui/card";
import { TimePeriodSelector } from "@/components/dashboard/time-period-selector";
import type { TimePeriodPreset } from "@/types/evaluation";

interface DashboardPeriodSelectorProps {
  value: TimePeriodPreset;
  onChange: (period: TimePeriodPreset) => void;
}

export function DashboardPeriodSelector({
  value,
  onChange,
}: DashboardPeriodSelectorProps) {
  return (
    <Card size="sm" className="mb-4 py-0 border-border bg-card">
      <CardContent className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-medium text-foreground">
            Dashboard period
          </p>
          <p className="text-xs text-muted-foreground">
            Scopes summaries, queues, counts, and default chart ranges.
          </p>
        </div>
        <TimePeriodSelector
          value={value}
          onChange={onChange}
          ariaLabel="Dashboard period"
          className="w-36"
        />
      </CardContent>
    </Card>
  );
}
