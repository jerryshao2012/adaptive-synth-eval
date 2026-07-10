"use client";

import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { TimePeriodPreset } from "@/types/evaluation";
import { TIME_PERIOD_PRESETS } from "@/lib/time-periods";

interface TimePeriodSelectorProps {
  value: TimePeriodPreset;
  onChange: (preset: TimePeriodPreset) => void;
  className?: string;
}

export function TimePeriodSelector({
  value,
  onChange,
  className,
}: TimePeriodSelectorProps) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as TimePeriodPreset)}>
      <SelectTrigger
        className={cn(
          "h-7 w-32.5 border-border bg-background text-xs",
          className
        )}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {Object.entries(TIME_PERIOD_PRESETS).map(([key, { label }]) => (
          <SelectItem key={key} value={key} className="text-xs">
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
