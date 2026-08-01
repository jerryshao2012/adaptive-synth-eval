import { describe, expect, it } from "vitest";

import {
  TIME_PERIOD_PRESETS,
  filterEvaluationsByPeriod,
  getTimePeriod,
  resolveWidestTimePeriod,
} from "@/lib/time-periods";
import type { EvaluationRecord } from "@/types/evaluation";

const row = (timestamp: string) => ({ timestamp }) as EvaluationRecord;

describe("full-run time period", () => {
  it("is exposed as an unbounded selector preset", () => {
    expect(TIME_PERIOD_PRESETS["full-run"].label).toBe("Full Run");
    expect(getTimePeriod("full-run")).toBeNull();
  });

  it("does not filter evaluation timestamps", () => {
    const rows = [
      row("2021-01-01T00:00:00Z"),
      row("2031-01-01T00:00:00Z"),
      row("not-a-timestamp"),
    ];

    expect(filterEvaluationsByPeriod(rows, "full-run")).toEqual(rows);
  });

  it("keeps bounded presets filtering invalid and out-of-range timestamps", () => {
    const now = new Date("2026-07-31T12:00:00Z");
    const rows = [
      row("2026-07-30T12:00:00Z"),
      row("2026-06-01T12:00:00Z"),
      row("not-a-timestamp"),
    ];

    expect(filterEvaluationsByPeriod(rows, "last-7-days", now)).toEqual([
      rows[0],
    ]);
  });
});

describe("widest time period resolution", () => {
  const now = new Date("2026-07-31T12:00:00Z");

  it("chooses the bounded preset with the earliest start at one captured now", () => {
    expect(
      resolveWidestTimePeriod(
        ["last-7-days", "this-month", "last-90-days"],
        now
      )
    ).toBe("last-90-days");
    expect(
      resolveWidestTimePeriod(["last-90-days", "last-7-days"], now)
    ).toBe("last-90-days");
  });

  it("always gives full-run precedence", () => {
    expect(
      resolveWidestTimePeriod(["last-90-days", "full-run"], now)
    ).toBe("full-run");
  });
});
