import type { EvaluationRecord, TimePeriodPreset } from "@/types/evaluation";
import {
  startOfWeek,
  startOfMonth,
  startOfQuarter,
  subDays,
} from "date-fns";

interface TimePeriod {
  from: Date;
  to: Date;
}

export const TIME_PERIOD_PRESETS: Record<
  TimePeriodPreset,
  { label: string; fn: (now: Date) => TimePeriod | null }
> = {
  "full-run": {
    label: "Full Run",
    fn: () => null,
  },
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
): TimePeriod | null {
  return TIME_PERIOD_PRESETS[preset].fn(now);
}

export function resolveWidestTimePeriod(
  presets: TimePeriodPreset[],
  now: Date = new Date()
): TimePeriodPreset {
  if (presets.length === 0) return "last-90-days";
  if (presets.includes("full-run")) return "full-run";

  const bounded = presets.map((preset) => ({
    preset,
    interval: getTimePeriod(preset, now)!,
  }));
  const earliestFrom = Math.min(
    ...bounded.map(({ interval }) => interval.from.getTime())
  );
  const latestTo = Math.max(
    ...bounded.map(({ interval }) => interval.to.getTime())
  );
  const covering = bounded
    .filter(
      ({ interval }) =>
        interval.from.getTime() <= earliestFrom &&
        interval.to.getTime() >= latestTo
    )
    .sort(
      (left, right) =>
        left.interval.to.getTime() - left.interval.from.getTime() -
        (right.interval.to.getTime() - right.interval.from.getTime())
    );

  return (covering[0] ?? bounded[0]).preset;
}

export function filterEvaluationsByPeriod(
  rows: EvaluationRecord[],
  preset: TimePeriodPreset,
  now: Date = new Date()
): EvaluationRecord[] {
  const interval = getTimePeriod(preset, now);
  if (!interval) return rows;

  const fromMs = interval.from.getTime();
  const toMs = interval.to.getTime();
  return rows.filter((row) => {
    const timestampMs = Date.parse(row.timestamp);
    return (
      Number.isFinite(timestampMs) &&
      timestampMs >= fromMs &&
      timestampMs <= toMs
    );
  });
}

export function formatIntervalParam(date: Date): string {
  return date.toISOString();
}
