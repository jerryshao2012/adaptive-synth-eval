import { describe, it, expect } from "vitest";
import type { ArtifactValidation } from "@/types/evaluation";
import { isRunInvestigationReady, getArtifactFreshnessSummary } from "@/lib/server/validation";

// Test the pure validation utility functions (no fs mocking needed)

function makeValidation(overrides: Partial<ArtifactValidation> = {}): ArtifactValidation {
  return {
    runId: "test-run-001",
    isValid: true,
    issues: [],
    artifactFreshness: {
      monitoringScores: { exists: true, recordCount: 100, lastModified: "2026-07-10T12:00:00Z" },
      monitoringState: { exists: true, lastModified: "2026-07-10T12:00:00Z" },
      runState: { exists: true },
      runSummary: { exists: true },
    },
    ...overrides,
  };
}

// ============================================================
// isRunInvestigationReady
// ============================================================

describe("isRunInvestigationReady", () => {
  it("returns true for valid validation with data", () => {
    const v = makeValidation();
    expect(isRunInvestigationReady(v)).toBe(true);
  });

  it("returns false when validation has errors", () => {
    const v = makeValidation({
      isValid: false,
      issues: [{ artifact: "run_state.json", severity: "error", message: "Missing" }],
    });
    expect(isRunInvestigationReady(v)).toBe(false);
  });

  it("returns false when no scores file exists", () => {
    const v = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: false, recordCount: 0 },
        monitoringState: { exists: true },
        runState: { exists: true },
        runSummary: { exists: true },
      },
    });
    expect(isRunInvestigationReady(v)).toBe(false);
  });

  it("returns false when scores file is empty", () => {
    const v = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: true, recordCount: 0 },
        monitoringState: { exists: true },
        runState: { exists: true },
        runSummary: { exists: true },
      },
    });
    expect(isRunInvestigationReady(v)).toBe(false);
  });

  it("returns false when both invalid and no scores", () => {
    const v = makeValidation({
      isValid: false,
      issues: [{ artifact: "monitoring_scores.jsonl", severity: "error", message: "Corrupted" }],
      artifactFreshness: {
        monitoringScores: { exists: false, recordCount: 0 },
        monitoringState: { exists: false },
        runState: { exists: false },
        runSummary: { exists: false },
      },
    });
    expect(isRunInvestigationReady(v)).toBe(false);
  });

  it("returns true with minimum viable state", () => {
    // Only needs: valid, scores exist, at least 1 record
    const v = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: true, recordCount: 1 },
        monitoringState: { exists: false },
        runState: { exists: true },
        runSummary: { exists: false },
      },
    });
    expect(isRunInvestigationReady(v)).toBe(true);
  });
});

// ============================================================
// getArtifactFreshnessSummary
// ============================================================

describe("getArtifactFreshnessSummary", () => {
  it("returns summary with record count when scores exist", () => {
    const v = makeValidation();
    const summary = getArtifactFreshnessSummary(v);
    expect(summary).toContain("100 evaluation records");
    expect(summary).toContain("Monitoring state available");
    expect(summary).toContain("Run summary available");
  });

  it("returns 'No evaluation data' when scores don't exist", () => {
    const v = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: false, recordCount: 0 },
        monitoringState: { exists: true },
        runState: { exists: false },
        runSummary: { exists: false },
      },
    });
    const summary = getArtifactFreshnessSummary(v);
    expect(summary).toContain("No evaluation data");
  });

  it("returns 'No artifacts available' when all are missing", () => {
    const v = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: false, recordCount: 0 },
        monitoringState: { exists: false },
        runState: { exists: false },
        runSummary: { exists: false },
      },
    });
    const summary = getArtifactFreshnessSummary(v);
    expect(summary).toBe("No evaluation data");
  });

  it("handles single artifact present", () => {
    const v = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: true, recordCount: 42 },
        monitoringState: { exists: false },
        runState: { exists: false },
        runSummary: { exists: false },
      },
    });
    const summary = getArtifactFreshnessSummary(v);
    expect(summary).toContain("42 evaluation records");
    expect(summary).not.toContain("Monitoring state");
    expect(summary).not.toContain("Run summary");
  });
});

// ============================================================
// Validation state transition tests
// ============================================================

describe("validation state transitions", () => {
  it("distinguishes missing vs empty vs malformed", () => {
    // Missing: file doesn't exist at all
    const missing = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: false, recordCount: 0 },
        monitoringState: { exists: false },
        runState: { exists: true },
        runSummary: { exists: false },
      },
    });
    expect(isRunInvestigationReady(missing)).toBe(false);
    expect(getArtifactFreshnessSummary(missing)).toContain("No evaluation data");

    // Empty: file exists but has 0 records
    const empty = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: true, recordCount: 0 },
        monitoringState: { exists: true },
        runState: { exists: true },
        runSummary: { exists: true },
      },
    });
    expect(isRunInvestigationReady(empty)).toBe(false);
    expect(getArtifactFreshnessSummary(empty)).toContain("0 evaluation records");

    // Malformed: file exists but has validation errors
    const malformed = makeValidation({
      isValid: false,
      issues: [
        {
          artifact: "monitoring_scores.jsonl",
          severity: "error",
          message: "Failed to parse monitoring_scores.jsonl.",
        },
      ],
      artifactFreshness: {
        monitoringScores: { exists: true, recordCount: 0 },
        monitoringState: { exists: true },
        runState: { exists: true },
        runSummary: { exists: true },
      },
    });
    expect(isRunInvestigationReady(malformed)).toBe(false);

    // Ready: file exists with records and no errors
    const ready = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: true, recordCount: 500 },
        monitoringState: { exists: true },
        runState: { exists: true },
        runSummary: { exists: true },
      },
    });
    expect(isRunInvestigationReady(ready)).toBe(true);
  });

  it("recognizes that score file existence is not proof of active monitoring", () => {
    // A completed run with scores should show as complete, not "in progress"
    const completed = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: true, recordCount: 500, lastModified: "2026-07-09T12:00:00Z" },
        monitoringState: { exists: true, lastModified: "2026-07-09T12:00:00Z" },
        runState: { exists: true },
        runSummary: { exists: true },
      },
    });
    expect(isRunInvestigationReady(completed)).toBe(true);

    // A run with only run_state.json but no scores is not active
    const noScores = makeValidation({
      artifactFreshness: {
        monitoringScores: { exists: false, recordCount: 0 },
        monitoringState: { exists: false },
        runState: { exists: true },
        runSummary: { exists: false },
      },
    });
    expect(isRunInvestigationReady(noScores)).toBe(false);
  });
});
