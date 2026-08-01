import { promises as fs } from "node:fs";
import path from "node:path";

function inferDefaultRepoRoot(): string {
  return process.env.ASE_REPO_ROOT || path.resolve(process.cwd(), "..");
}

const DEFAULT_REPO_ROOT = inferDefaultRepoRoot();
export function resolveRunsDirectory(repoRoot = DEFAULT_REPO_ROOT): string {
  return (
    process.env.ASE_DASHBOARD_RUNS_DIR ||
    process.env.ASE_RUNS_DIR ||
    path.resolve(repoRoot, "outputs", "runs")
  );
}

const DEFAULT_RUNS_DIR = resolveRunsDirectory();

process.env.ASE_REPO_ROOT ??= DEFAULT_REPO_ROOT;

export class RunPathValidationError extends Error {
  constructor(message = "runId must be one safe path segment.") {
    super(message);
    this.name = "RunPathValidationError";
  }
}

export class RunNotFoundError extends Error {
  readonly runId: string;

  constructor(runId: string) {
    super(`Run '${runId}' was not found.`);
    this.name = "RunNotFoundError";
    this.runId = runId;
  }
}

export async function resolveRunDirectory(
  runId: string,
  repoRoot = DEFAULT_REPO_ROOT
): Promise<string> {
  const hasControlCharacters = /[\u0000-\u001f\u007f-\u009f]/u.test(runId);
  const normalized = runId.trim();
  if (
    hasControlCharacters ||
    !normalized ||
    normalized === "." ||
    normalized === ".." ||
    normalized.includes("/") ||
    normalized.includes("\\")
  ) {
    throw new RunPathValidationError();
  }

  const runsDirectory = resolveRunsDirectory(repoRoot);
  const runDirectory = path.resolve(runsDirectory, normalized);
  const relative = path.relative(runsDirectory, runDirectory);
  if (
    relative !== normalized ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new RunPathValidationError();
  }

  try {
    const stat = await fs.stat(runDirectory);
    if (!stat.isDirectory()) {
      throw new RunNotFoundError(normalized);
    }
    const [realRunsDirectory, realRunDirectory] = await Promise.all([
      fs.realpath(runsDirectory),
      fs.realpath(runDirectory),
    ]);
    const realRelative = path.relative(realRunsDirectory, realRunDirectory);
    if (
      !realRelative ||
      realRelative === ".." ||
      realRelative.startsWith(`..${path.sep}`) ||
      path.isAbsolute(realRelative)
    ) {
      throw new RunPathValidationError(
        "runId must resolve below the repository runs directory."
      );
    }
    return realRunDirectory;
  } catch (error) {
    if (error instanceof RunNotFoundError || error instanceof RunPathValidationError) {
      throw error;
    }
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      throw new RunNotFoundError(normalized);
    }
    throw error;
  }

}
