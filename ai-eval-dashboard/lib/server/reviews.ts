import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import type {
  EvaluationRecord,
  HumanReview,
  ReviewQueueFilters,
  ReviewQueueItem,
  ReviewQueueResponse,
  ReviewStats,
  MetricScoreStatus,
} from "@/types/evaluation";
import { METRIC_THRESHOLDS } from "@/lib/metrics";
import {
  listRunSummaries,
  getMonitoringEvaluations,
} from "@/lib/server/monitoring";

const REPO_ROOT = path.resolve(process.cwd(), "..");
const RUNS_DIR = path.join(REPO_ROOT, "outputs", "runs");
const REVIEW_STATE_PATH = path.join(REPO_ROOT, "outputs", "review_state.json");
const HUMAN_REVIEWS_FILE = "human_reviews.jsonl";

// ---- Helpers (mirror monitoring.ts utilities) ----

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readJsonFile<T>(filePath: string): Promise<T | null> {
  try {
    const content = await fs.readFile(filePath, "utf-8");
    return JSON.parse(content) as T;
  } catch {
    return null;
  }
}

async function readJsonLines<T>(filePath: string): Promise<T[]> {
  try {
    const content = await fs.readFile(filePath, "utf-8");
    return content
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .flatMap((line) => {
        try {
          return [JSON.parse(line) as T];
        } catch {
          return [] as T[];
        }
      });
  } catch {
    return [];
  }
}

async function appendJsonLine(
  filePath: string,
  row: Record<string, unknown>
): Promise<void> {
  const dir = path.dirname(filePath);
  await fs.mkdir(dir, { recursive: true });
  await fs.appendFile(filePath, JSON.stringify(row) + "\n", "utf-8");
}

function runDirPath(runId: string): string {
  return path.join(RUNS_DIR, runId);
}

function metricKeys(): string[] {
  return Object.keys(METRIC_THRESHOLDS);
}

function avgAiScore(record: EvaluationRecord): number {
  const allMetrics = [
    ...Object.values(record.safety_metrics),
    ...Object.values(record.performance_metrics),
  ];
  if (allMetrics.length === 0) return 0;
  return Math.round(
    allMetrics.reduce((sum, m) => sum + m.percent, 0) / allMetrics.length
  );
}

function compositeKey(
  runId: string,
  conversationId: string,
  turnId: string
): string {
  return `${runId}::${conversationId}::${turnId}`;
}

// ---- Human Review CRUD ----

export async function getHumanReviews(
  runId: string
): Promise<HumanReview[]> {
  const filePath = path.join(runDirPath(runId), HUMAN_REVIEWS_FILE);
  return readJsonLines<HumanReview>(filePath);
}

export async function saveHumanReview(
  review: HumanReview
): Promise<void> {
  const filePath = path.join(runDirPath(review.runId), HUMAN_REVIEWS_FILE);

  // Read existing, deduplicate by reviewId
  const existing = await getHumanReviews(review.runId);
  const filtered = existing.filter((r) => r.reviewId !== review.reviewId);

  // Rewrite file with deduplicated + new review
  const dir = path.dirname(filePath);
  await fs.mkdir(dir, { recursive: true });
  const lines = [...filtered, review]
    .map((r) => JSON.stringify(r))
    .join("\n");
  await fs.writeFile(filePath, lines + (lines ? "\n" : ""), "utf-8");
}

// ---- Review Queue Builder ----

export async function getReviewQueue(
  filters: ReviewQueueFilters = {}
): Promise<ReviewQueueResponse> {
  const page = filters.page ?? 1;
  const pageSize = filters.pageSize ?? 50;

  // 1. Get all runs
  const runs = await listRunSummaries();
  const runIds = filters.runId ? [filters.runId] : runs.map((r) => r.runId);

  // 2. For each run, load evaluations and existing reviews
  const allItems: ReviewQueueItem[] = [];

  for (const runId of runIds) {
    const evalResp = await getMonitoringEvaluations(runId);
    if (!evalResp) continue;

    const reviews = await getHumanReviews(runId);
    const reviewMap = new Map<string, HumanReview>();
    for (const r of reviews) {
      reviewMap.set(compositeKey(r.runId, r.conversationId, r.turnId), r);
    }

    for (const record of evalResp.evaluations) {
      const key = compositeKey(
        runId,
        record.conversation_id || "",
        String(record.turn_id)
      );
      const review = reviewMap.get(key) || null;

      const item: ReviewQueueItem = {
        runId,
        conversationId: record.conversation_id || "",
        turnId: String(record.turn_id),
        userText: record.user_text,
        responseText: record.response_text,
        timestamp: record.timestamp,
        safetyStatus: record.safety_status,
        performanceStatus: record.performance_status,
        avgAiScore: avgAiScore(record),
        hasHumanReview: Boolean(review),
        reviewStatus: review?.reviewStatus ?? null,
        flags: review?.flags ?? [],
        reviewedAt: review?.reviewedAt ?? null,
      };

      allItems.push(item);
    }
  }

  // 3. Apply filters
  let filtered = allItems.filter((item) => {
    if (filters.status) {
      if (
        item.safetyStatus !== filters.status &&
        item.performanceStatus !== filters.status
      ) {
        return false;
      }
    }
    if (filters.searchText) {
      const q = filters.searchText.toLowerCase();
      if (
        !item.userText.toLowerCase().includes(q) &&
        !item.responseText.toLowerCase().includes(q)
      ) {
        return false;
      }
    }
    if (filters.disputedOnly) {
      if (!item.flags.includes("disputed")) return false;
    }
    if (filters.unreviewedOnly) {
      if (item.hasHumanReview) return false;
    }
    return true;
  });

  // 4. Sort
  const sortBy = filters.sortBy || "timestamp";
  const sortOrder = filters.sortOrder || "desc";
  filtered.sort((a, b) => {
    let cmp = 0;
    switch (sortBy) {
      case "timestamp":
        cmp = a.timestamp.localeCompare(b.timestamp);
        break;
      case "avgAiScore":
        cmp = a.avgAiScore - b.avgAiScore;
        break;
      case "safetyStatus":
        cmp = a.safetyStatus.localeCompare(b.safetyStatus);
        break;
      case "reviewStatus":
        cmp = (a.reviewStatus || "").localeCompare(b.reviewStatus || "");
        break;
    }
    return sortOrder === "asc" ? cmp : -cmp;
  });

  // 5. Paginate
  const total = filtered.length;
  const start = (page - 1) * pageSize;
  const items = filtered.slice(start, start + pageSize);

  return { items, total, page, pageSize };
}

// ---- Review Detail ----

export async function getReviewDetail(
  runId: string,
  turnId: string
): Promise<{
  evaluation: EvaluationRecord;
  existingReview: HumanReview | null;
} | null> {
  const evalResp = await getMonitoringEvaluations(runId);
  if (!evalResp) return null;

  const evaluation = evalResp.evaluations.find(
    (e) => String(e.turn_id) === turnId
  );
  if (!evaluation) return null;

  const reviews = await getHumanReviews(runId);
  const existingReview =
    reviews.find(
      (r) => r.runId === runId && r.turnId === turnId
    ) ?? null;

  return { evaluation, existingReview };
}

// ---- Bulk Operations ----

export async function bulkApprove(
  recordRefs: Array<{ runId: string; turnId: string }>
): Promise<number> {
  let count = 0;
  for (const { runId, turnId } of recordRefs) {
    const detail = await getReviewDetail(runId, turnId);
    if (!detail) continue;

    const { evaluation, existingReview } = detail;

    // Build human scores from AI scores
    const safetyScores: HumanReview["safetyScores"] = {};
    for (const [key, m] of Object.entries(evaluation.safety_metrics)) {
      safetyScores[key] = {
        aiScore: m.percent,
        humanScore: m.percent,
        status: m.status,
      };
    }
    const performanceScores: HumanReview["performanceScores"] = {};
    for (const [key, m] of Object.entries(evaluation.performance_metrics)) {
      performanceScores[key] = {
        aiScore: m.percent,
        humanScore: m.percent,
        status: m.status,
      };
    }

    const now = new Date().toISOString();
    const review: HumanReview = {
      reviewId: existingReview?.reviewId ?? randomUUID(),
      evaluationRecordId: compositeKey(
        runId,
        evaluation.conversation_id || "",
        String(evaluation.turn_id)
      ),
      runId,
      conversationId: evaluation.conversation_id || "",
      turnId: String(evaluation.turn_id),
      reviewerId: "auto-approved",
      reviewStatus: "approved",
      safetyScores,
      performanceScores,
      overallStatus:
        evaluation.safety_status === "fail" ||
        evaluation.performance_status === "fail"
          ? "fail"
          : evaluation.safety_status === "warn" ||
              evaluation.performance_status === "warn"
            ? "warn"
            : "pass",
      notes: existingReview?.notes ?? "",
      flags: existingReview?.flags ?? ["reviewed_ok"],
      reviewedAt: now,
      createdAt: existingReview?.createdAt ?? now,
      updatedAt: now,
    };

    await saveHumanReview(review);
    count++;
  }
  return count;
}

export async function bulkFlag(
  recordRefs: Array<{ runId: string; turnId: string }>,
  flag: string
): Promise<number> {
  let count = 0;
  for (const { runId, turnId } of recordRefs) {
    const detail = await getReviewDetail(runId, turnId);
    if (!detail) continue;

    const { evaluation, existingReview } = detail;
    const now = new Date().toISOString();

    // If no review exists, create a draft one with the flag
    const safetyScores =
      existingReview?.safetyScores ??
      Object.fromEntries(
        Object.entries(evaluation.safety_metrics).map(([key, m]) => [
          key,
          { aiScore: m.percent, humanScore: m.percent, status: m.status },
        ])
      );

    const performanceScores =
      existingReview?.performanceScores ??
      Object.fromEntries(
        Object.entries(evaluation.performance_metrics).map(([key, m]) => [
          key,
          { aiScore: m.percent, humanScore: m.percent, status: m.status },
        ])
      );

    const existingFlags = existingReview?.flags ?? [];
    const newFlags = existingFlags.includes(flag as HumanReview["flags"][number])
      ? existingFlags
      : [...existingFlags, flag as HumanReview["flags"][number]];

    const review: HumanReview = {
      reviewId: existingReview?.reviewId ?? randomUUID(),
      evaluationRecordId: compositeKey(
        runId,
        evaluation.conversation_id || "",
        String(evaluation.turn_id)
      ),
      runId,
      conversationId: evaluation.conversation_id || "",
      turnId: String(evaluation.turn_id),
      reviewerId: existingReview?.reviewerId ?? "bulk-flag",
      reviewStatus: existingReview?.reviewStatus ?? "draft",
      safetyScores,
      performanceScores,
      overallStatus:
        existingReview?.overallStatus ??
        (evaluation.safety_status === "fail" ||
        evaluation.performance_status === "fail"
          ? "fail"
          : evaluation.safety_status === "warn" ||
              evaluation.performance_status === "warn"
            ? "warn"
            : "pass"),
      notes: existingReview?.notes ?? "",
      flags: newFlags,
      reviewedAt: existingReview?.reviewedAt ?? now,
      createdAt: existingReview?.createdAt ?? now,
      updatedAt: now,
    };

    await saveHumanReview(review);
    count++;
  }
  return count;
}

// ---- Review Stats ----

export async function getReviewStats(): Promise<ReviewStats> {
  const runs = await listRunSummaries();

  let totalRecords = 0;
  let reviewedCount = 0;
  let draftCount = 0;
  let approvedCount = 0;
  let disputedCount = 0;
  const totalAgreementSum = 0;
  const totalAgreementCount = 0;
  const perMetricAgreementSums: Record<string, number> = {};
  const perMetricAgreementCounts: Record<string, number> = {};
  for (const key of metricKeys()) {
    perMetricAgreementSums[key] = 0;
    perMetricAgreementCounts[key] = 0;
  }

  for (const run of runs) {
    const evalResp = await getMonitoringEvaluations(run.runId);
    if (!evalResp) continue;

    const reviews = await getHumanReviews(run.runId);
    const reviewMap = new Map<string, HumanReview>();
    for (const r of reviews) {
      reviewMap.set(compositeKey(r.runId, r.conversationId, r.turnId), r);
    }

    for (const record of evalResp.evaluations) {
      totalRecords++;
      const key = compositeKey(
        run.runId,
        record.conversation_id || "",
        String(record.turn_id)
      );
      const review = reviewMap.get(key);

      if (review) {
        reviewedCount++;
        if (review.reviewStatus === "draft") draftCount++;
        if (review.reviewStatus === "approved") approvedCount++;
        if (review.flags.includes("disputed")) disputedCount++;

        // Per-metric agreement
        const allScores = {
          ...review.safetyScores,
          ...review.performanceScores,
        };
        for (const [metricKey, scores] of Object.entries(allScores)) {
          if (perMetricAgreementSums[metricKey] === undefined) {
            perMetricAgreementSums[metricKey] = 0;
            perMetricAgreementCounts[metricKey] = 0;
          }
          const delta = Math.abs(scores.aiScore - scores.humanScore);
          const agreed = delta <= 5 ? 1 : 0;
          perMetricAgreementSums[metricKey] += agreed;
          perMetricAgreementCounts[metricKey] += 1;
        }
      }
    }
  }

  // Compute per-metric agreement percentages
  const perMetricAgreement: Record<string, number> = {};
  for (const key of Object.keys(perMetricAgreementSums)) {
    const count = perMetricAgreementCounts[key];
    perMetricAgreement[key] = count > 0
      ? Math.round((perMetricAgreementSums[key] / count) * 100)
      : 100;
  }

  const agreementCount = Object.values(perMetricAgreementCounts).reduce(
    (sum, c) => sum + c,
    0
  );
  const agreementSum = Object.values(perMetricAgreementSums).reduce(
    (sum, s) => sum + s,
    0
  );

  return {
    totalRecords,
    reviewedCount,
    draftCount,
    approvedCount,
    disputedCount,
    averageAgreement:
      agreementCount > 0
        ? Math.round((agreementSum / agreementCount) * 100)
        : 100,
    perMetricAgreement,
  };
}
