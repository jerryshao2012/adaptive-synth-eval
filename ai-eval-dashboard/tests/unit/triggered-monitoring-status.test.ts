import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  getMonitoringEvaluations,
  getMonitoringStatus,
} from "@/lib/server/monitoring";

const roots: string[] = [];

async function runFixture() {
  const repoRoot = await fs.mkdtemp(path.join(os.tmpdir(), "trigger-status-"));
  roots.push(repoRoot);
  const runDir = path.join(repoRoot, "outputs", "runs", "run-1");
  await fs.mkdir(runDir, { recursive: true });
  return { repoRoot, runDir };
}

afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) => fs.rm(root, { recursive: true, force: true }))
  );
});

describe("triggered monitoring status", () => {
  it("maps all persisted trigger counters", async () => {
    const { repoRoot, runDir } = await runFixture();
    await fs.writeFile(
      path.join(runDir, "monitoring_state.json"),
      JSON.stringify({
        status: "completed",
        next_line_index: 10,
        total_lines: 10,
        sample_size: 5,
        trigger_policy_fingerprint: "policy-fp",
        trigger_metrics: {
          triggers_detected: 3,
          rows_promoted: 5,
          budget_used: 5,
          budget_drops: 2,
          deduplicated_context: 4,
          pending_lookahead: 1,
        },
      })
    );

    const status = await getMonitoringStatus("run-1", repoRoot);
    expect(status?.triggerMetrics).toEqual({
      triggersDetected: 3,
      rowsPromoted: 5,
      budgetUsed: 5,
      budgetAvailable: 5,
      budgetDrops: 2,
      deduplicatedContext: 4,
      pendingLookahead: 1,
      policyFingerprint: "policy-fp",
    });
  });

  it("omits inactive reconciled score-cache rows", async () => {
    const { repoRoot, runDir } = await runFixture();
    const base = {
      timestamp: "2026-01-01T00:00:00",
      turn_id: "1",
      variant: "raw",
    };
    await fs.writeFile(
      path.join(runDir, "monitoring_scores.jsonl"),
      [
        JSON.stringify({ ...base, selected_for_monitoring: false }),
        JSON.stringify({
          ...base,
          turn_id: "2",
          selected_for_monitoring: true,
        }),
      ].join("\n")
    );

    const response = await getMonitoringEvaluations(
      "run-1",
      undefined,
      undefined,
      100,
      repoRoot
    );
    expect(response?.evaluations.map((row) => row.turn_id)).toEqual(["2"]);
  });
});
