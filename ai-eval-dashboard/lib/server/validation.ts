import type { ArtifactValidation, ArtifactIssue } from "@/types/evaluation";
import { readJsonFile, readJsonLines, fileExists } from "@/lib/server/monitoring";

// Re-export from monitoring for local use
async function checkFileExists(filePath: string): Promise<boolean> {
  try {
    return await fileExists(filePath);
  } catch {
    return false;
  }
}

/**
 * Validate all artifacts for a run at the server boundary.
 * Distinguishes missing artifacts, malformed records, and empty completed runs.
 */
export async function validateRunArtifacts(runDir: string, runId: string): Promise<ArtifactValidation> {
  const issues: ArtifactIssue[] = [];
  const artifactFreshness: ArtifactValidation["artifactFreshness"] = {
    monitoringScores: { exists: false, recordCount: 0 },
    monitoringState: { exists: false },
    runState: { exists: false },
    runSummary: { exists: false },
  };

  // Check run_state.json
  const runStatePath = `${runDir}/run_state.json`;
  const runStateExists = await checkFileExists(runStatePath);
  artifactFreshness.runState.exists = runStateExists;
  if (!runStateExists) {
    issues.push({
      artifact: "run_state.json",
      severity: "error",
      message: "Run state file is missing. This run may be corrupted.",
    });
  } else {
    try {
      const runState = await readJsonFile(runStatePath);
      if (!runState || typeof runState !== "object") {
        issues.push({
          artifact: "run_state.json",
          severity: "error",
          message: "Run state file is malformed or empty.",
        });
      }
    } catch {
      issues.push({
        artifact: "run_state.json",
        severity: "error",
        message: "Failed to parse run_state.json. File may be corrupted.",
      });
    }
  }

  // Check run_summary.json
  const runSummaryPath = `${runDir}/run_summary.json`;
  const runSummaryExists = await checkFileExists(runSummaryPath);
  artifactFreshness.runSummary.exists = runSummaryExists;
  if (!runSummaryExists) {
    issues.push({
      artifact: "run_summary.json",
      severity: "warning",
      message: "Run summary has not been generated yet.",
    });
  }

  // Check monitoring_state.json
  const monitoringStatePath = `${runDir}/monitoring_state.json`;
  const monitoringStateExists = await checkFileExists(monitoringStatePath);
  artifactFreshness.monitoringState.exists = monitoringStateExists;
  if (monitoringStateExists) {
    try {
      const state = await readJsonFile(monitoringStatePath);
      if (state && typeof state === "object") {
        const status = (state as Record<string, unknown>).status;
        // A score file existing doesn't prove active monitoring
        if (status === "completed") {
          // Verify that scores file actually has records
          const scoresPath = `${runDir}/monitoring_scores.jsonl`;
          const scoresExist = await checkFileExists(scoresPath);
          if (scoresExist) {
            try {
              const records = await readJsonLines(scoresPath);
              artifactFreshness.monitoringScores.exists = true;
              artifactFreshness.monitoringScores.recordCount = Array.isArray(records) ? records.length : 0;

              if (records.length === 0) {
                issues.push({
                  artifact: "monitoring_scores.jsonl",
                  severity: "warning",
                  message: "Monitoring is marked completed but scores file is empty.",
                  details: "The monitoring process may have completed without producing any evaluations.",
                });
              }

              // Validate each record for required fields
              if (Array.isArray(records) && records.length > 0) {
                let malformedCount = 0;
                for (let i = 0; i < records.length; i++) {
                  const record = records[i];
                  if (!record || typeof record !== "object") {
                    malformedCount++;
                    continue;
                  }
                  const hasRequired =
                    "turn_id" in record &&
                    "safety_status" in record &&
                    "performance_status" in record;
                  if (!hasRequired) {
                    malformedCount++;
                  }
                }
                if (malformedCount > 0) {
                  issues.push({
                    artifact: "monitoring_scores.jsonl",
                    severity: "warning",
                    message: `${malformedCount} of ${records.length} records are malformed or missing required fields.`,
                    details: "Expected fields: turn_id, safety_status, performance_status",
                  });
                }
              }
            } catch {
              issues.push({
                artifact: "monitoring_scores.jsonl",
                severity: "error",
                message: "Monitoring scores file exists but could not be parsed.",
              });
            }
          } else {
            issues.push({
              artifact: "monitoring_scores.jsonl",
              severity: "error",
              message: "Monitoring is marked completed but no scores file was found.",
            });
          }
        }
      } else {
        // File exists but could not be parsed as a valid object
        issues.push({
          artifact: "monitoring_state.json",
          severity: "error",
          message: "Monitoring state file is malformed or contains invalid data.",
        });
      }
    } catch {
      issues.push({
        artifact: "monitoring_state.json",
        severity: "error",
        message: "Failed to parse monitoring_state.json.",
      });
    }
  }

  // Check monitoring_scores.jsonl independently
  const scoresPath = `${runDir}/monitoring_scores.jsonl`;
  const scoresExist = await checkFileExists(scoresPath);
  if (scoresExist && !artifactFreshness.monitoringScores.exists) {
    artifactFreshness.monitoringScores.exists = true;
    try {
      const records = await readJsonLines(scoresPath);
      artifactFreshness.monitoringScores.recordCount = Array.isArray(records) ? records.length : 0;

      // Validate each record
      if (Array.isArray(records)) {
        let malformedCount = 0;
        for (let i = 0; i < records.length; i++) {
          const record = records[i];
          if (!record || typeof record !== "object") {
            malformedCount++;
            continue;
          }
          // Check required fields
          const hasRequired =
            "turn_id" in record &&
            "safety_status" in record &&
            "performance_status" in record;
          if (!hasRequired) {
            malformedCount++;
          }
        }
        if (malformedCount > 0) {
          issues.push({
            artifact: "monitoring_scores.jsonl",
            severity: "warning",
            message: `${malformedCount} of ${records.length} records are malformed or missing required fields.`,
            details: "Expected fields: turn_id, safety_status, performance_status",
          });
        }
      }
    } catch {
      issues.push({
        artifact: "monitoring_scores.jsonl",
        severity: "error",
        message: "Failed to parse monitoring_scores.jsonl.",
      });
    }
  }

  const isValid = !issues.some((i) => i.severity === "error");

  return {
    runId,
    isValid,
    issues,
    artifactFreshness,
  };
}

/**
 * Determine if a run is ready for investigation.
 * A run is "ready" if:
 * 1. It has a valid run_state.json
 * 2. It has monitoring_scores.jsonl with at least one valid record
 * 3. It has no critical validation errors
 */
export function isRunInvestigationReady(validation: ArtifactValidation): boolean {
  if (!validation.isValid) return false;
  if (!validation.artifactFreshness.monitoringScores.exists) return false;
  if (validation.artifactFreshness.monitoringScores.recordCount === 0) return false;
  return true;
}

/**
 * Get a human-readable freshness summary for a run's artifacts.
 */
export function getArtifactFreshnessSummary(validation: ArtifactValidation): string {
  const { artifactFreshness: af } = validation;
  const parts: string[] = [];

  if (af.monitoringScores.exists) {
    parts.push(`${af.monitoringScores.recordCount} evaluation records`);
  } else {
    parts.push("No evaluation data");
  }

  if (af.monitoringState.exists) {
    parts.push("Monitoring state available");
  }

  if (af.runSummary.exists) {
    parts.push("Run summary available");
  }

  return parts.length > 0 ? parts.join(" · ") : "No artifacts available";
}
