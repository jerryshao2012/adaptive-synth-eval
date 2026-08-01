// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProfilePhaseComparison } from "@/components/dashboard/profile-phase-comparison";
import type { ProfilePeriodSummary } from "@/lib/aggregation";

const summaries: ProfilePeriodSummary[] = [
  {
    periodId: "business-hours",
    modeLabel: "synth · benign",
    timeLabel: "09:00–17:00 daily",
    evaluationCount: 12,
    passRate: 100,
    failRate: 0,
    toxicitySafetyScore: 80,
    safetyAverage: 84,
    performanceAverage: 91,
  },
  {
    periodId: "after-hours",
    modeLabel: "adversarial · stress",
    timeLabel: "18:00–23:00 daily",
    evaluationCount: 8,
    passRate: 50,
    failRate: 50,
    toxicitySafetyScore: 40,
    safetyAverage: null,
    performanceAverage: 62,
  },
];

afterEach(cleanup);

describe("ProfilePhaseComparison", () => {
  it("renders nothing for a legacy run without profile summaries", () => {
    const { container } = render(<ProfilePhaseComparison summaries={[]} />);

    expect(container.innerHTML).toBe("");
  });

  it("renders phase modes, daily hours, counts, rates, and metric averages", () => {
    render(<ProfilePhaseComparison summaries={summaries} />);

    expect(screen.getByText("Phase comparison")).toBeTruthy();
    expect(screen.getByText("business-hours")).toBeTruthy();
    expect(screen.getByText("synth · benign")).toBeTruthy();
    expect(screen.getByText("09:00–17:00 daily")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Toxicity safety" })).toBeTruthy();
    expect(screen.getByText("84%")).toBeTruthy();
    expect(screen.getByText("91%")).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
  });

  it("marks only comparatively worse failure and lower toxicity safety values", () => {
    render(<ProfilePhaseComparison summaries={summaries} />);

    expect(
      screen.getByLabelText(/comparatively higher fail rate/i).textContent
    ).toContain("50%");
    expect(
      screen.getByLabelText(/comparatively lower toxicity safety score/i)
    ).toHaveProperty("textContent", "40%");
    expect(
      screen.queryAllByLabelText(/comparatively higher fail rate/i)
    ).toHaveLength(1);
    expect(
      screen.queryAllByLabelText(/comparatively lower toxicity safety score/i)
    ).toHaveLength(1);
  });

  it("keeps numeric values in highlighted cells' accessible names", () => {
    render(<ProfilePhaseComparison summaries={summaries} />);

    expect(
      screen.getByRole("cell", {
        name: "50% pass / 50% fail; comparatively higher fail rate",
      })
    ).toBeTruthy();
    expect(
      screen.getByRole("cell", {
        name: "40% toxicity safety; comparatively lower toxicity safety score",
      })
    ).toBeTruthy();
  });
});
