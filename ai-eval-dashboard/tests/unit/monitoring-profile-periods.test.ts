import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { getMonitoringEvaluations } from "@/lib/server/monitoring";

const roots: string[] = [];

async function runFixture(runId: string) {
  const repoRoot = await fs.mkdtemp(path.join(os.tmpdir(), "profile-periods-"));
  roots.push(repoRoot);
  const runDir = path.join(repoRoot, "outputs", "runs", runId);
  await fs.mkdir(runDir, { recursive: true });
  return { repoRoot, runDir };
}

afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) => fs.rm(root, { recursive: true, force: true }))
  );
});

describe("monitoring profile periods", () => {
  it("returns every eligible row, including the latest, when limit is null", async () => {
    const { repoRoot, runDir } = await runFixture("large-profiled-run");
    const rows = Array.from({ length: 2005 }, (_, index) => ({
      timestamp: new Date(Date.UTC(2020, 0, 1, 0, 0, index)).toISOString(),
      turn_id: `turn-${index}`,
      selected_for_monitoring: true,
    }));
    await fs.writeFile(
      path.join(runDir, "monitoring_scores.jsonl"),
      rows.map((row) => JSON.stringify(row)).join("\n")
    );

    const response = await getMonitoringEvaluations(
      "large-profiled-run",
      undefined,
      undefined,
      null,
      repoRoot
    );

    expect(response?.evaluations).toHaveLength(2005);
    expect(response?.evaluations.at(-1)?.turn_id).toBe("turn-2004");
    expect(response?.total).toBe(2005);
  });

  it("retains numeric limiting behavior", async () => {
    const { repoRoot, runDir } = await runFixture("numeric-limit-run");
    await fs.writeFile(
      path.join(runDir, "monitoring_scores.jsonl"),
      [0, 1, 2]
        .map((index) =>
          JSON.stringify({
            timestamp: `2020-01-01T00:00:0${index}Z`,
            turn_id: `turn-${index}`,
          })
        )
        .join("\n")
    );

    const response = await getMonitoringEvaluations(
      "numeric-limit-run",
      undefined,
      undefined,
      2,
      repoRoot
    );

    expect(response?.evaluations.map((row) => row.turn_id)).toEqual([
      "turn-0",
      "turn-1",
    ]);
    expect(response?.total).toBe(2);
  });
  it("returns ordered repeated daily period instances when scores are absent", async () => {
    const { repoRoot, runDir } = await runFixture("profiled-zero-scores");
    const rows = [
      {
        profile_period_instance_id: "2026-06-02/morning",
        profile_period_id: "morning",
        profile_period_start: "2026-06-02T08:00:00",
        profile_period_end: "2026-06-02T10:00:00",
        conversation_mode: "support",
        behavior_mode: "polite",
        synthetic_day: "2026-06-02",
      },
      {
        profile_period_instance_id: "2026-06-01/afternoon",
        profile_period_id: "afternoon",
        profile_period_start: "2026-06-01T13:00:00",
        profile_period_end: "2026-06-01T17:00:00",
        conversation_mode: "mixed",
        behavior_mode: "stressed",
        synthetic_day: "2026-06-01",
      },
      {
        profile_period_instance_id: "2026-06-01/morning",
        profile_period_id: "morning",
        profile_period_start: "2026-06-01T08:00:00",
        profile_period_end: "2026-06-01T10:00:00",
        conversation_mode: "support",
        behavior_mode: "polite",
        synthetic_day: "2026-06-01",
      },
      {
        profile_period_instance_id: "2026-06-01/morning",
        profile_period_id: "morning",
        profile_period_start: "2026-06-01T08:00:00",
        profile_period_end: "2026-06-01T10:00:00",
        conversation_mode: "support",
        behavior_mode: "polite",
        synthetic_day: "2026-06-01",
      },
    ];
    await fs.writeFile(path.join(runDir, "run_plan.json"), JSON.stringify(rows));

    const response = await getMonitoringEvaluations(
      "profiled-zero-scores",
      undefined,
      undefined,
      100,
      repoRoot
    );

    expect(response?.evaluations).toEqual([]);
    expect(response?.profilePeriods).toEqual([
      {
        instanceId: "2026-06-01/morning",
        periodId: "morning",
        start: "2026-06-01T08:00:00",
        end: "2026-06-01T10:00:00",
        conversationMode: "support",
        behaviorMode: "polite",
        plannedConversations: 2,
        syntheticDay: "2026-06-01",
      },
      {
        instanceId: "2026-06-01/afternoon",
        periodId: "afternoon",
        start: "2026-06-01T13:00:00",
        end: "2026-06-01T17:00:00",
        conversationMode: "mixed",
        behaviorMode: "stressed",
        plannedConversations: 1,
        syntheticDay: "2026-06-01",
      },
      {
        instanceId: "2026-06-02/morning",
        periodId: "morning",
        start: "2026-06-02T08:00:00",
        end: "2026-06-02T10:00:00",
        conversationMode: "support",
        behaviorMode: "polite",
        plannedConversations: 1,
        syntheticDay: "2026-06-02",
      },
    ]);
  });

  it.each([
    ["missing", null],
    ["malformed JSON", "{"],
    ["unexpected shape", JSON.stringify({ rows: [] })],
    ["legacy plan", JSON.stringify([{ conversation_id: "conv-1" }])],
  ])("returns an empty profile period list for a %s run plan", async (_name, content) => {
    const { repoRoot, runDir } = await runFixture(`plan-${_name}`);
    if (content !== null) {
      await fs.writeFile(path.join(runDir, "run_plan.json"), content);
    }

    const response = await getMonitoringEvaluations(
      `plan-${_name}`,
      undefined,
      undefined,
      100,
      repoRoot
    );

    expect(response?.profilePeriods).toEqual([]);
  });
});
