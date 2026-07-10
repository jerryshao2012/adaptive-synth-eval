import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import path from "node:path";
import os from "node:os";
import fs from "node:fs/promises";
import { validateRunArtifacts, isRunInvestigationReady } from "@/lib/server/validation";

/**
 * Integration tests for the validation pipeline using real temp directories.
 * Tests the full flow: completed, failed, empty, and in-progress run fixtures.
 */
describe("validation flow with file fixtures", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "ase-validation-test-"));
  });

  afterEach(async () => {
    await fs.rm(tmpDir, { recursive: true, force: true });
  });

  async function writeJson(name: string, data: unknown) {
    await fs.writeFile(path.join(tmpDir, name), JSON.stringify(data, null, 2), "utf-8");
  }

  async function writeJsonLines(name: string, records: unknown[]) {
    const content = records.map((r) => JSON.stringify(r)).join("\n") + "\n";
    await fs.writeFile(path.join(tmpDir, name), content, "utf-8");
  }

  // ============================================================
  // Completed run fixture
  // ============================================================

  it("validates a completed run with all artifacts", async () => {
    await writeJson("run_state.json", { runId: "test-complete", mode: "unified" });
    await writeJson("run_summary.json", { runId: "test-complete", status: "completed" });
    await writeJson("monitoring_state.json", { runId: "test-complete", status: "completed" });
    await writeJsonLines("monitoring_scores.jsonl", [
      { turn_id: "t1", safety_status: "pass", performance_status: "pass", timestamp: "2026-07-10T12:00:00Z" },
      { turn_id: "t2", safety_status: "pass", performance_status: "pass", timestamp: "2026-07-10T12:01:00Z" },
      { turn_id: "t3", safety_status: "fail", performance_status: "warn", timestamp: "2026-07-10T12:02:00Z" },
    ]);

    const result = await validateRunArtifacts(tmpDir, "test-complete");
    expect(result.isValid).toBe(true);
    expect(result.issues).toHaveLength(0);
    expect(result.artifactFreshness.monitoringScores.exists).toBe(true);
    expect(result.artifactFreshness.monitoringScores.recordCount).toBe(3);
    expect(result.artifactFreshness.runState.exists).toBe(true);
    expect(result.artifactFreshness.runSummary.exists).toBe(true);
    expect(isRunInvestigationReady(result)).toBe(true);
  });

  it("completed run with empty scores file raises a warning", async () => {
    await writeJson("run_state.json", { runId: "empty-scores" });
    await writeJson("monitoring_state.json", { runId: "empty-scores", status: "completed" });
    await fs.writeFile(path.join(tmpDir, "monitoring_scores.jsonl"), "", "utf-8");

    const result = await validateRunArtifacts(tmpDir, "empty-scores");
    expect(result.isValid).toBe(true);
    expect(result.artifactFreshness.monitoringScores.recordCount).toBe(0);
    const hasEmptyWarning = result.issues.some(
      (i) => i.artifact === "monitoring_scores.jsonl" && i.message.includes("empty")
    );
    expect(hasEmptyWarning).toBe(true);
    expect(isRunInvestigationReady(result)).toBe(false);
  });

  // ============================================================
  // Failed/corrupted run fixtures
  // ============================================================

  it("detects missing run_state.json", async () => {
    // No run_state.json at all
    const result = await validateRunArtifacts(tmpDir, "no-state");
    expect(result.isValid).toBe(false);
    expect(result.issues.some((i) => i.artifact === "run_state.json" && i.severity === "error")).toBe(true);
    expect(isRunInvestigationReady(result)).toBe(false);
  });

  it("detects malformed JSON in run_state.json", async () => {
    await fs.writeFile(path.join(tmpDir, "run_state.json"), "not valid json {{{", "utf-8");

    const result = await validateRunArtifacts(tmpDir, "malformed-state");
    expect(result.isValid).toBe(false);
    expect(result.issues.some((i) => i.artifact === "run_state.json" && i.severity === "error")).toBe(true);
  });

  it("detects malformed JSONL records in scores file", async () => {
    await writeJson("run_state.json", { runId: "malformed-scores" });
    await writeJson("monitoring_state.json", { runId: "malformed-scores", status: "completed" });

    // Write some valid and some malformed records
    const content = [
      JSON.stringify({ turn_id: "t1", safety_status: "pass", performance_status: "pass" }),
      "not valid json {{{",
      "", // empty line
      JSON.stringify({ turn_id: "t2", safety_status: "fail", performance_status: "fail" }),
      JSON.stringify({ wrong_key: "missing required fields" }),
    ].join("\n") + "\n";
    await fs.writeFile(path.join(tmpDir, "monitoring_scores.jsonl"), content, "utf-8");

    const result = await validateRunArtifacts(tmpDir, "malformed-scores");
    expect(result.isValid).toBe(true); // only warnings for malformed records
    expect(result.artifactFreshness.monitoringScores.recordCount).toBe(3); // 2 valid JSON + 1 with wrong keys = 3 parsed
    const hasMalformedWarning = result.issues.some(
      (i) => i.artifact === "monitoring_scores.jsonl" && i.message.includes("malformed")
    );
    expect(hasMalformedWarning).toBe(true);
  });

  it("detects monitoring marked completed but no scores file", async () => {
    await writeJson("run_state.json", { runId: "completed-no-scores" });
    await writeJson("monitoring_state.json", { runId: "completed-no-scores", status: "completed" });
    // Intentionally don't create monitoring_scores.jsonl

    const result = await validateRunArtifacts(tmpDir, "completed-no-scores");
    expect(result.isValid).toBe(false);
    expect(result.issues.some((i) => i.message.includes("no scores file"))).toBe(true);
  });

  it("handles corrupted monitoring_state.json", async () => {
    await writeJson("run_state.json", { runId: "bad-monitoring" });
    await fs.writeFile(path.join(tmpDir, "monitoring_state.json"), "{broken json", "utf-8");

    const result = await validateRunArtifacts(tmpDir, "bad-monitoring");
    expect(result.isValid).toBe(false);
    expect(result.issues.some((i) => i.artifact === "monitoring_state.json")).toBe(true);
  });

  // ============================================================
  // Empty run fixture
  // ============================================================

  it("validates an empty run (only run_state.json)", async () => {
    await writeJson("run_state.json", { runId: "empty-run" });

    const result = await validateRunArtifacts(tmpDir, "empty-run");
    expect(result.isValid).toBe(true);
    expect(result.artifactFreshness.runState.exists).toBe(true);
    expect(result.artifactFreshness.monitoringScores.exists).toBe(false);
    expect(result.artifactFreshness.monitoringState.exists).toBe(false);
    expect(result.artifactFreshness.runSummary.exists).toBe(false);

    // Empty run is NOT ready for investigation
    expect(isRunInvestigationReady(result)).toBe(false);

    // Should have a warning about missing run summary
    expect(result.issues.some((i) => i.artifact === "run_summary.json")).toBe(true);
  });

  // ============================================================
  // In-progress run fixture
  // ============================================================

  it("validates an in-progress run correctly", async () => {
    await writeJson("run_state.json", { runId: "in-progress" });
    await writeJson("monitoring_state.json", {
      runId: "in-progress",
      status: "in_progress",
      next_line_index: 50,
      total_lines: 100,
    });
    // Partially written scores
    await writeJsonLines("monitoring_scores.jsonl", [
      { turn_id: "t1", safety_status: "pass", performance_status: "pass" },
      { turn_id: "t2", safety_status: "pass", performance_status: "warn" },
    ]);

    const result = await validateRunArtifacts(tmpDir, "in-progress");
    expect(result.isValid).toBe(true);
    expect(result.artifactFreshness.monitoringScores.exists).toBe(true);
    expect(result.artifactFreshness.monitoringScores.recordCount).toBe(2);
    expect(isRunInvestigationReady(result)).toBe(true); // has data, should be ready
  });

  it("in-progress with no scores yet is not ready for investigation", async () => {
    await writeJson("run_state.json", { runId: "just-started" });
    await writeJson("monitoring_state.json", {
      runId: "just-started",
      status: "in_progress",
      next_line_index: 0,
      total_lines: 100,
    });
    // No scores file yet

    const result = await validateRunArtifacts(tmpDir, "just-started");
    expect(isRunInvestigationReady(result)).toBe(false);
  });

  // ============================================================
  // Edge cases
  // ============================================================

  it("handles run directory with no files at all", async () => {
    const result = await validateRunArtifacts(tmpDir, "ghost-run");
    expect(result.isValid).toBe(false);
    expect(result.issues.length).toBeGreaterThan(0);
    expect(result.artifactFreshness.runState.exists).toBe(false);
    expect(isRunInvestigationReady(result)).toBe(false);
  });

  it("detects empty run_state.json object", async () => {
    await writeJson("run_state.json", null);

    const result = await validateRunArtifacts(tmpDir, "null-state");
    expect(result.isValid).toBe(false);
    expect(result.issues.some((i) => i.artifact === "run_state.json" && i.severity === "error")).toBe(true);
  });

  it("distinguishes completed monitoring from just having a score file", async () => {
    // Scenario: scores file exists but monitoring_state says "not_started"
    await writeJson("run_state.json", { runId: "stale-scores" });
    await writeJson("monitoring_state.json", { runId: "stale-scores", status: "not_started" });
    await writeJsonLines("monitoring_scores.jsonl", [
      { turn_id: "old1", safety_status: "pass", performance_status: "pass" },
    ]);

    const result = await validateRunArtifacts(tmpDir, "stale-scores");
    expect(result.isValid).toBe(true);
    expect(result.artifactFreshness.monitoringScores.exists).toBe(true);
    expect(result.artifactFreshness.monitoringScores.recordCount).toBe(1);
    // Has data, so investigation ready (even if monitoring says not_started)
    // This prevents treating score file existence as active monitoring
    expect(isRunInvestigationReady(result)).toBe(true);
  });
});
