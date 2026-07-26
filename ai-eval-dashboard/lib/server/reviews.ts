import { randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

import { METRIC_THRESHOLDS } from "@/lib/metrics";
import {
  getMonitoringEvaluations,
  listRunSummaries,
} from "@/lib/server/monitoring";
import type {
  EvaluationRecord,
  HumanReview,
  ReviewQueueFilters,
  ReviewQueueItem,
  ReviewQueueResponse,
  ReviewStats,
} from "@/types/evaluation";

const REPO_ROOT = path.resolve(
  process.env.ASE_REPO_ROOT || path.resolve(process.cwd(), "..")
);
const RUNS_DIR =
  process.env.ASE_RUNS_DIR || path.join(REPO_ROOT, "outputs", "runs");
const HUMAN_REVIEWS_FILE = "human_reviews.jsonl";

function runDirPath(runId: string): string {
  return path.join(RUNS_DIR, runId);
}

async function readJsonLines<T>(filePath: string): Promise<T[]> {
  try {
    const content = await fs.readFile(filePath, "utf-8");
    return content
      .split(/\r?\n/u)
      .map((line) => line.trim())
      .filter(Boolean)
      .flatMap((line) => {
        try {
          return [JSON.parse(line) as T];
        } catch {
          return [];
        }
      });
  } catch {
    return [];
  }
}

function compositeKey(
  runId: string,
  conversationId: string,
  turnId: string
): string {
  return `${runId}::${conversationId}::${turnId}`;
}

function avgAiScore(record: EvaluationRecord): number {
  const metrics = [
    ...Object.values(record.safety_metrics),
    ...Object.values(record.performance_metrics),
  ];
  if (metrics.length === 0) {
    return 0;
  }
  return Math.round(
    metrics.reduce((sum, metric) => sum + metric.percent, 0) / metrics.length
  );
}

function overallStatus(record: EvaluationRecord): HumanReview["overallStatus"] {
  if (
    record.safety_status === "fail" ||
    record.performance_status === "fail"
  ) {
    return "fail";
  }
  if (
    record.safety_status === "warn" ||
    record.performance_status === "warn"
  ) {
    return "warn";
  }
  return "pass";
}

function scoresFromMetrics(
  metrics: EvaluationRecord["safety_metrics"]
): HumanReview["safetyScores"];
function scoresFromMetrics(
  metrics: EvaluationRecord["performance_metrics"]
): HumanReview["performanceScores"];
function scoresFromMetrics(
  metrics:
    | EvaluationRecord["safety_metrics"]
    | EvaluationRecord["performance_metrics"]
): HumanReview["safetyScores"] {
  return Object.fromEntries(
    Object.entries(metrics).map(([key, metric]) => [
      key,
      {
        aiScore: metric.percent,
        humanScore: metric.percent,
        status: metric.status,
      },
    ])
  );
}

export async function getHumanReviews(runId: string): Promise<HumanReview[]> {
  return readJsonLines<HumanReview>(
    path.join(runDirPath(runId), HUMAN_REVIEWS_FILE)
  );
}

export async function saveHumanReview(review: HumanReview): Promise<void> {
  const filePath = path.join(runDirPath(review.runId), HUMAN_REVIEWS_FILE);
  const existing = await getHumanReviews(review.runId);
  const rows = [
    ...existing.filter((item) => item.reviewId !== review.reviewId),
    review,
  ];
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(
    filePath,
    rows.map((item) => JSON.stringify(item)).join("\n") + "\n",
    "utf-8"
  );
}

export async function getReviewQueue(
  filters: ReviewQueueFilters = {}
): Promise<ReviewQueueResponse> {
  const page = Math.max(1, filters.page ?? 1);
  const pageSize = Math.max(1, filters.pageSize ?? 50);
  const runs = await listRunSummaries();
  const runIds = filters.runId ? [filters.runId] : runs.map((run) => run.runId);
  const allItems: ReviewQueueItem[] = [];

  for (const runId of runIds) {
    const [evaluations, reviews] = await Promise.all([
      getMonitoringEvaluations(runId),
      getHumanReviews(runId),
    ]);
    if (!evaluations) {
      continue;
    }
    const reviewsByTurn = new Map(
      reviews.map((review) => [
        compositeKey(review.runId, review.conversationId, review.turnId),
        review,
      ])
    );
    for (const record of evaluations.evaluations) {
      const conversationId = record.conversation_id || "";
      const turnId = String(record.turn_id);
      const review =
        reviewsByTurn.get(compositeKey(runId, conversationId, turnId)) || null;
      allItems.push({
        runId,
        conversationId,
        turnId,
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
      });
    }
  }

  const query = filters.searchText?.toLowerCase();
  const filtered = allItems.filter((item) => {
    if (
      filters.status &&
      item.safetyStatus !== filters.status &&
      item.performanceStatus !== filters.status
    ) {
      return false;
    }
    if (
      query &&
      !item.userText.toLowerCase().includes(query) &&
      !item.responseText.toLowerCase().includes(query)
    ) {
      return false;
    }
    if (filters.disputedOnly && !item.flags.includes("disputed")) {
      return false;
    }
    if (filters.unreviewedOnly && item.hasHumanReview) {
      return false;
    }
    return true;
  });

  const sortBy = filters.sortBy ?? "timestamp";
  const direction = filters.sortOrder === "asc" ? 1 : -1;
  filtered.sort((left, right) => {
    if (sortBy === "avgAiScore") {
      return (left.avgAiScore - right.avgAiScore) * direction;
    }
    const leftValue =
      sortBy === "safetyStatus"
        ? left.safetyStatus
        : sortBy === "reviewStatus"
          ? left.reviewStatus || ""
          : left.timestamp;
    const rightValue =
      sortBy === "safetyStatus"
        ? right.safetyStatus
        : sortBy === "reviewStatus"
          ? right.reviewStatus || ""
          : right.timestamp;
    return leftValue.localeCompare(rightValue) * direction;
  });

  const start = (page - 1) * pageSize;
  return {
    items: filtered.slice(start, start + pageSize),
    total: filtered.length,
    page,
    pageSize,
  };
}

export async function getReviewDetail(
  runId: string,
  turnId: string
): Promise<{
  evaluation: EvaluationRecord;
  existingReview: HumanReview | null;
} | null> {
  const evaluations = await getMonitoringEvaluations(runId);
  if (!evaluations) {
    return null;
  }
  const evaluation = evaluations.evaluations.find(
    (record) => String(record.turn_id) === turnId
  );
  if (!evaluation) {
    return null;
  }
  const reviews = await getHumanReviews(runId);
  return {
    evaluation,
    existingReview:
      reviews.find(
        (review) => review.runId === runId && review.turnId === turnId
      ) ?? null,
  };
}

function createReview(
  runId: string,
  evaluation: EvaluationRecord,
  existingReview: HumanReview | null,
  options: {
    reviewerId: string;
    reviewStatus: HumanReview["reviewStatus"];
    flags: HumanReview["flags"];
  }
): HumanReview {
  const now = new Date().toISOString();
  return {
    reviewId: existingReview?.reviewId ?? randomUUID(),
    evaluationRecordId: compositeKey(
      runId,
      evaluation.conversation_id || "",
      String(evaluation.turn_id)
    ),
    runId,
    conversationId: evaluation.conversation_id || "",
    turnId: String(evaluation.turn_id),
    reviewerId: existingReview?.reviewerId ?? options.reviewerId,
    reviewStatus: options.reviewStatus,
    safetyScores:
      existingReview?.safetyScores ??
      scoresFromMetrics(evaluation.safety_metrics),
    performanceScores:
      existingReview?.performanceScores ??
      scoresFromMetrics(evaluation.performance_metrics),
    overallStatus: existingReview?.overallStatus ?? overallStatus(evaluation),
    notes: existingReview?.notes ?? "",
    flags: options.flags,
    reviewedAt: existingReview?.reviewedAt ?? now,
    createdAt: existingReview?.createdAt ?? now,
    updatedAt: now,
  };
}

export async function bulkApprove(
  recordRefs: Array<{ runId: string; turnId: string }>
): Promise<number> {
  let updated = 0;
  for (const { runId, turnId } of recordRefs) {
    const detail = await getReviewDetail(runId, turnId);
    if (!detail) {
      continue;
    }
    await saveHumanReview(
      createReview(runId, detail.evaluation, detail.existingReview, {
        reviewerId: "auto-approved",
        reviewStatus: "approved",
        flags: detail.existingReview?.flags ?? ["reviewed_ok"],
      })
    );
    updated += 1;
  }
  return updated;
}

export async function bulkFlag(
  recordRefs: Array<{ runId: string; turnId: string }>,
  flag: string
): Promise<number> {
  let updated = 0;
  for (const { runId, turnId } of recordRefs) {
    const detail = await getReviewDetail(runId, turnId);
    if (!detail) {
      continue;
    }
    const typedFlag = flag as HumanReview["flags"][number];
    const existingFlags = detail.existingReview?.flags ?? [];
    const flags = existingFlags.includes(typedFlag)
      ? existingFlags
      : [...existingFlags, typedFlag];
    await saveHumanReview(
      createReview(runId, detail.evaluation, detail.existingReview, {
        reviewerId: "bulk-flag",
        reviewStatus: detail.existingReview?.reviewStatus ?? "draft",
        flags,
      })
    );
    updated += 1;
  }
  return updated;
}

export async function getReviewStats(): Promise<ReviewStats> {
  const runs = await listRunSummaries();
  let totalRecords = 0;
  let reviewedCount = 0;
  let draftCount = 0;
  let approvedCount = 0;
  let disputedCount = 0;
  const agreementSums: Record<string, number> = Object.fromEntries(
    Object.keys(METRIC_THRESHOLDS).map((key) => [key, 0])
  );
  const agreementCounts: Record<string, number> = Object.fromEntries(
    Object.keys(METRIC_THRESHOLDS).map((key) => [key, 0])
  );

  for (const run of runs) {
    const [evaluations, reviews] = await Promise.all([
      getMonitoringEvaluations(run.runId),
      getHumanReviews(run.runId),
    ]);
    if (!evaluations) {
      continue;
    }
    totalRecords += evaluations.total;
    for (const review of reviews) {
      reviewedCount += 1;
      draftCount += review.reviewStatus === "draft" ? 1 : 0;
      approvedCount += review.reviewStatus === "approved" ? 1 : 0;
      disputedCount += review.flags.includes("disputed") ? 1 : 0;
      for (const [metricKey, score] of Object.entries({
        ...review.safetyScores,
        ...review.performanceScores,
      })) {
        agreementSums[metricKey] ??= 0;
        agreementCounts[metricKey] ??= 0;
        agreementSums[metricKey] +=
          Math.abs(score.aiScore - score.humanScore) <= 5 ? 1 : 0;
        agreementCounts[metricKey] += 1;
      }
    }
  }

  const perMetricAgreement = Object.fromEntries(
    Object.keys(agreementSums).map((key) => [
      key,
      agreementCounts[key] > 0
        ? Math.round((agreementSums[key] / agreementCounts[key]) * 100)
        : 100,
    ])
  );
  const agreementCount = Object.values(agreementCounts).reduce(
    (sum, count) => sum + count,
    0
  );
  const agreementSum = Object.values(agreementSums).reduce(
    (sum, count) => sum + count,
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
