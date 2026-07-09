import type { TimePeriodPreset } from "@/types/evaluation";
import {
  startOfWeek,
  startOfMonth,
  startOfQuarter,
  subDays,
  endOfDay,
  type Interval,
} from "date-fns";

interface TimePeriod {
  from: Date;
  to: Date;
}

export const TIME_PERIOD_PRESETS: Record<
  TimePeriodPreset,
  { label: string; fn: (now: Date) => TimePeriod }
> = {
  "this-week": {
    label: "This Week",
    fn: (now) => ({ from: startOfWeek(now, { weekStartsOn: 1 }), to: now }),
  },
  "this-month": {
    label: "This Month",
    fn: (now) => ({ from: startOfMonth(now), to: now }),
  },
  "this-quarter": {
    label: "This Quarter",
    fn: (now) => ({ from: startOfQuarter(now), to: now }),
  },
  "last-7-days": {
    label: "Last 7 Days",
    fn: (now) => ({ from: subDays(now, 7), to: now }),
  },
  "last-30-days": {
    label: "Last 30 Days",
    fn: (now) => ({ from: subDays(now, 30), to: now }),
  },
  "last-90-days": {
    label: "Last 90 Days",
    fn: (now) => ({ from: subDays(now, 90), to: now }),
  },
};

export function getTimePeriod(
  preset: TimePeriodPreset,
  now: Date = new Date()
): TimePeriod {
  return TIME_PERIOD_PRESETS[preset].fn(now);
}

export function formatIntervalParam(date: Date): string {
  return date.toISOString();
}
