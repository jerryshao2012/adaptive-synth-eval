import { promises as fs } from "node:fs";
import path from "node:path";

import type {
  ArtifactIssue,
  ArtifactValidation,
} from "@/types/evaluation";

async function statArtifact(filePath: string): Promise<{
  exists: boolean;
  lastModified?: string;
}> {
  try {
    const stat = await fs.stat(filePath);
    return {
      exists: stat.isFile(),
      lastModified: stat.mtime.toISOString(),
    };
  } catch {
    return { exists: false };
  }
}

async function readJsonObject(filePath: string): Promise<{
  valid: boolean;
  value: Record<string, unknown> | null;
}> {
  try {
    const value: unknown = JSON.parse(await fs.readFile(filePath, "utf-8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { valid: false, value: null };
    }
    return { valid: true, value: value as Record<string, unknown> };
  } catch {
    return { valid: false, value: null };
  }
}

async function inspectJsonLines(filePath: string): Promise<{
  recordCount: number;
  malformedCount: number;
}> {
  const content = await fs.readFile(filePath, "utf-8");
  let recordCount = 0;
  let malformedCount = 0;

  for (const rawLine of content.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    try {
      const record: unknown = JSON.parse(line);
      recordCount += 1;
      if (
        !record ||
        typeof record !== "object" ||
        Array.isArray(record) ||
        !("turn_id" in record) ||
        !("safety_status" in record) ||
        !("performance_status" in record)
      ) {
        malformedCount += 1;
      }
    } catch {
      malformedCount += 1;
    }
  }

  return { recordCount, malformedCount };
}

export async function validateRunArtifacts(
  runDir: string,
  runId: string
): Promise<ArtifactValidation> {
  const issues: ArtifactIssue[] = [];
  const runStatePath = path.join(runDir, "run_state.json");
  const runSummaryPath = path.join(runDir, "run_summary.json");
  const monitoringStatePath = path.join(runDir, "monitoring_state.json");
  const scoresPath = path.join(runDir, "monitoring_scores.jsonl");

  const [runStateFile, runSummaryFile, monitoringStateFile, scoresFile] =
    await Promise.all([
      statArtifact(runStatePath),
      statArtifact(runSummaryPath),
      statArtifact(monitoringStatePath),
      statArtifact(scoresPath),
    ]);

  const artifactFreshness: ArtifactValidation["artifactFreshness"] = {
    monitoringScores: {
      exists: scoresFile.exists,
      recordCount: 0,
      lastModified: scoresFile.lastModified,
    },
    monitoringState: monitoringStateFile,
    runState: { exists: runStateFile.exists },
    runSummary: { exists: runSummaryFile.exists },
  };

  if (!runStateFile.exists) {
    issues.push({
      artifact: "run_state.json",
      severity: "error",
      message: "Run state file is missing. This run may be corrupted.",
    });
  } else if (!(await readJsonObject(runStatePath)).valid) {
    issues.push({
      artifact: "run_state.json",
      severity: "error",
      message: "Run state file is malformed or empty.",
    });
  }

  if (!runSummaryFile.exists) {
    issues.push({
      artifact: "run_summary.json",
      severity: "warning",
      message: "Run summary has not been generated yet.",
    });
  }

  let monitoringStatus: unknown;
  if (monitoringStateFile.exists) {
    const monitoringState = await readJsonObject(monitoringStatePath);
    if (!monitoringState.valid) {
      issues.push({
        artifact: "monitoring_state.json",
        severity: "error",
        message: "Monitoring state file is malformed or contains invalid data.",
      });
    } else {
      monitoringStatus = monitoringState.value?.status;
    }
  }

  if (scoresFile.exists) {
    try {
      const inspection = await inspectJsonLines(scoresPath);
      artifactFreshness.monitoringScores.recordCount = inspection.recordCount;
      if (inspection.malformedCount > 0) {
        issues.push({
          artifact: "monitoring_scores.jsonl",
          severity: "warning",
          message:
            `${inspection.malformedCount} record(s) are malformed or ` +
            "missing required fields.",
          details:
            "Expected fields: turn_id, safety_status, performance_status",
        });
      }
      if (monitoringStatus === "completed" && inspection.recordCount === 0) {
        issues.push({
          artifact: "monitoring_scores.jsonl",
          severity: "warning",
          message: "Monitoring is marked completed but scores file is empty.",
        });
      }
    } catch {
      issues.push({
        artifact: "monitoring_scores.jsonl",
        severity: "error",
        message: "Failed to parse monitoring_scores.jsonl.",
      });
    }
  } else if (monitoringStatus === "completed") {
    issues.push({
      artifact: "monitoring_scores.jsonl",
      severity: "error",
      message: "Monitoring is marked completed but no scores file was found.",
    });
  }

  return {
    runId,
    isValid: !issues.some((issue) => issue.severity === "error"),
    issues,
    artifactFreshness,
  };
}

export function isRunInvestigationReady(
  validation: ArtifactValidation
): boolean {
  return (
    validation.isValid &&
    validation.artifactFreshness.monitoringScores.exists &&
    validation.artifactFreshness.monitoringScores.recordCount > 0
  );
}

export function getArtifactFreshnessSummary(
  validation: ArtifactValidation
): string {
  const freshness = validation.artifactFreshness;
  const parts = freshness.monitoringScores.exists
    ? [`${freshness.monitoringScores.recordCount} evaluation records`]
    : ["No evaluation data"];

  if (freshness.monitoringState.exists) {
    parts.push("Monitoring state available");
  }
  if (freshness.runSummary.exists) {
    parts.push("Run summary available");
  }
  return parts.join(" · ");
}
