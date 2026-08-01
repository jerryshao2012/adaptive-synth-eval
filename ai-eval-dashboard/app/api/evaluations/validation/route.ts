import { NextRequest, NextResponse } from "next/server";
import path from "node:path";
import { resolveRunsDirectory } from "@/lib/server/run-paths";
import { validateRunArtifacts } from "@/lib/server/validation";

export const runtime = "nodejs";

const REPO_ROOT = path.resolve(
  process.env.ASE_REPO_ROOT || path.resolve(process.cwd(), "..")
);
const RUNS_DIR = resolveRunsDirectory(REPO_ROOT);

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const runId = searchParams.get("runId");

  if (!runId) {
    return NextResponse.json(
      { error: "Missing required parameter: runId" },
      { status: 400 }
    );
  }

  // Basic path traversal protection
  if (runId.includes("..") || runId.includes("/") || runId.includes("\\")) {
    return NextResponse.json(
      { error: "Invalid runId" },
      { status: 400 }
    );
  }

  const runDir = path.join(RUNS_DIR, runId);

  try {
    const validation = await validateRunArtifacts(runDir, runId);
    return NextResponse.json(validation);
  } catch (error) {
    return NextResponse.json(
      {
        runId,
        isValid: false,
        issues: [
          {
            artifact: "validation",
            severity: "error",
            message: `Validation failed: ${error instanceof Error ? error.message : "Unknown error"}`,
          },
        ],
        artifactFreshness: {
          monitoringScores: { exists: false, recordCount: 0 },
          monitoringState: { exists: false },
          runState: { exists: false },
          runSummary: { exists: false },
        },
      },
      { status: 500 }
    );
  }
}
