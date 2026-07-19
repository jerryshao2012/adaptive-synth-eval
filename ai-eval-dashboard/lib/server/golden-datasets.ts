import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import type { GoldenDataset } from "@/types/evaluation";
import { getMonitoringEvaluations } from "@/lib/server/monitoring";
import { getHumanReviews } from "@/lib/server/reviews";

const REPO_ROOT = path.resolve(process.cwd(), "..");
const DATASETS_DIR = path.join(REPO_ROOT, "outputs", "golden_datasets");

export class LegacyDatasetIdError extends Error {
  constructor() {
    super("datasetId must be one safe path segment.");
    this.name = "LegacyDatasetIdError";
  }
}

async function ensureDir(dir: string): Promise<void> {
  await fs.mkdir(dir, { recursive: true });
}

function datasetPath(datasetId: string): string {
  const normalized = datasetId.trim();
  if (
    !normalized ||
    normalized === "." ||
    normalized === ".." ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(normalized)
  ) {
    throw new LegacyDatasetIdError();
  }
  return path.join(DATASETS_DIR, `${normalized}.json`);
}

// ---- CRUD ----

export async function listDatasets(): Promise<GoldenDataset[]> {
  await ensureDir(DATASETS_DIR);
  let entries: Array<{ name: string }> = [];
  try {
    entries = (await fs.readdir(DATASETS_DIR, { withFileTypes: true }))
      .filter((e) => e.isFile() && e.name.endsWith(".json"))
      .map((e) => ({ name: e.name }));
  } catch {
    return [];
  }

  const datasets: GoldenDataset[] = [];
  for (const entry of entries) {
    const d = await readJsonFile<GoldenDataset>(
      path.join(DATASETS_DIR, entry.name)
    );
    if (d) datasets.push(d);
  }
  return datasets.sort(
    (a, b) =>
      new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  );
}

export async function getDataset(
  datasetId: string
): Promise<GoldenDataset | null> {
  return readJsonFile<GoldenDataset>(datasetPath(datasetId));
}

export async function createDataset(
  input: Pick<GoldenDataset, "name" | "version" | "filters">
): Promise<GoldenDataset> {
  const id = randomUUID();
  const now = new Date().toISOString();

  // Resolve record refs from approved human reviews only.
  const recordRefs: GoldenDataset["recordRefs"] = [];
  const seen = new Set<string>();

  if (input.filters.runIds && input.filters.runIds.length > 0) {
    for (const runId of input.filters.runIds) {
      const reviews = await getHumanReviews(runId);
      for (const review of reviews) {
        if (review.reviewStatus !== "approved") {
          continue;
        }

        const key = `${runId}::${review.conversationId}::${review.turnId}`;
        if (seen.has(key)) {
          continue;
        }
        seen.add(key);

        recordRefs.push({
          runId,
          conversationId: review.conversationId,
          turnId: review.turnId,
        });
      }
    }
  }

  const dataset: GoldenDataset = {
    datasetId: id,
    name: input.name,
    version: input.version,
    status: "draft",
    recordRefs,
    filters: input.filters,
    stats: {
      totalRecords: recordRefs.length,
      reviewedCount: recordRefs.length,
      interRaterAgreement: 100,
    },
    createdAt: now,
    updatedAt: now,
  };

  await saveDataset(dataset);
  return dataset;
}

export async function updateDataset(
  datasetId: string,
  updates: Partial<GoldenDataset>
): Promise<GoldenDataset | null> {
  const existing = await getDataset(datasetId);
  if (!existing) return null;

  const updated: GoldenDataset = {
    ...existing,
    ...updates,
    datasetId: existing.datasetId,
    createdAt: existing.createdAt,
    updatedAt: new Date().toISOString(),
  };
  await saveDataset(updated);
  return updated;
}

export async function saveDataset(dataset: GoldenDataset): Promise<void> {
  await ensureDir(DATASETS_DIR);
  await fs.writeFile(
    datasetPath(dataset.datasetId),
    JSON.stringify(dataset, null, 2),
    "utf-8"
  );
}

// ---- Export ----

export interface ExportRecord {
  turn_id: string;
  conversation_id: string;
  user_text: string;
  response_text: string;
  ai_safety_status: string;
  ai_performance_status: string;
  human_overall_status: string;
  [metricKey: string]: string | number | undefined;
}

export async function exportDataset(
  datasetId: string,
  format: "jsonl" | "csv"
): Promise<{ content: string; filename: string; contentType: string }> {
  const dataset = await getDataset(datasetId);
  if (!dataset) {
    throw new Error(`Dataset ${datasetId} not found`);
  }

  // Resolve all record refs
  const records: ExportRecord[] = [];
  for (const ref of dataset.recordRefs) {
    const evalResp = await getMonitoringEvaluations(ref.runId);
    if (!evalResp) continue;

    const evaluation = evalResp.evaluations.find(
      (e) =>
        String(e.turn_id) === ref.turnId &&
        (e.conversation_id || "") === ref.conversationId
    );
    if (!evaluation) continue;

    const reviews = await getHumanReviews(ref.runId);
    const review = reviews.find(
      (r) =>
        r.runId === ref.runId &&
        r.turnId === ref.turnId &&
        r.conversationId === ref.conversationId
    );

    const record: ExportRecord = {
      turn_id: ref.turnId,
      conversation_id: ref.conversationId,
      user_text: evaluation.user_text,
      response_text: evaluation.response_text,
      ai_safety_status: evaluation.safety_status,
      ai_performance_status: evaluation.performance_status,
      human_overall_status: review?.overallStatus || "unreviewed",
    };

    // Add per-metric AI + Human scores
    for (const [key, m] of Object.entries(evaluation.safety_metrics)) {
      record[`ai_safety_${key}`] = m.percent;
      record[`human_safety_${key}`] =
        review?.safetyScores[key]?.humanScore;
    }
    for (const [key, m] of Object.entries(evaluation.performance_metrics)) {
      record[`ai_perf_${key}`] = m.percent;
      record[`human_perf_${key}`] =
        review?.performanceScores[key]?.humanScore;
    }

    if (review) {
      record["review_notes"] = review.notes;
      record["review_flags"] = review.flags.join(";");
    }

    records.push(record);
  }

  const filename = `${dataset.name.replace(/\s+/g, "_")}_${dataset.version}.${format}`;

  if (format === "jsonl") {
    const content = records
      .map((r) => JSON.stringify(r))
      .join("\n");
    return {
      content,
      filename,
      contentType: "application/x-jsonlines",
    };
  }

  // CSV export
  if (records.length === 0) {
    return { content: "", filename, contentType: "text/csv" };
  }

  const headers = Object.keys(records[0]);
  const csvRows = [headers.map(csvEscape).join(",")];
  for (const record of records) {
    const row = headers.map((h) => csvEscape(String(record[h] ?? "")));
    csvRows.push(row.join(","));
  }

  return {
    content: csvRows.join("\n"),
    filename,
    contentType: "text/csv",
  };
}

// ---- Helpers ----

async function readJsonFile<T>(filePath: string): Promise<T | null> {
  try {
    const content = await fs.readFile(filePath, "utf-8");
    return JSON.parse(content) as T;
  } catch {
    return null;
  }
}

function csvEscape(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}
