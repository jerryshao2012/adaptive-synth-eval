import { NextRequest, NextResponse } from "next/server";

import {
  assertExactKeys,
  goldenErrorResponse,
  readJsonObject,
  stringArray,
} from "@/lib/server/golden-api";
import { GoldenValidationError, goldenCatalog } from "@/lib/server/golden-catalog";
import { getMonitoringEvaluations } from "@/lib/server/monitoring";
import { getHumanReviews } from "@/lib/server/reviews";
import { resolveRunDirectory } from "@/lib/server/run-paths";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  try {
    const body = await readJsonObject(request);
    assertExactKeys(body, ["runIds"]);
    const runIds = stringArray(body.runIds, "runIds");
    if (runIds.length === 0) throw new GoldenValidationError("runIds cannot be empty.");
    const existingIds = new Set((await goldenCatalog.listExamples()).map((item) => item.exampleId));
    let imported = 0;
    let reused = 0;
    let skipped = 0;
    for (const runId of runIds) {
      await resolveRunDirectory(runId);
      const [reviews, evaluations] = await Promise.all([
        getHumanReviews(runId),
        getMonitoringEvaluations(runId),
      ]);
      for (const review of reviews.filter((item) => item.reviewStatus === "approved")) {
        const evaluation = evaluations?.evaluations.find(
          (item) =>
            String(item.turn_id) === review.turnId &&
            String(item.conversation_id ?? "") === review.conversationId
        );
        if (!evaluation) {
          skipped += 1;
          continue;
        }
        const example = await goldenCatalog.importExample({
          content: {
            userText: evaluation.user_text,
            responseText: evaluation.response_text,
          },
          source: {
            runId,
            conversationId: review.conversationId,
            turnId: review.turnId,
            reviewId: review.reviewId,
            reviewerId: review.reviewerId,
            reviewedAt: review.reviewedAt,
            evaluationFingerprint: evaluation.value_versions?.evaluation_fingerprint,
          },
          review: {
            reviewStatus: "approved",
            overallStatus: review.overallStatus,
            safetyScores: review.safetyScores,
            performanceScores: review.performanceScores,
            notes: review.notes,
            flags: review.flags,
          },
          tags: [evaluation.scenario, evaluation.persona, evaluation.attack_category].filter(
            (value): value is string => Boolean(value)
          ),
        });
        if (existingIds.has(example.exampleId)) reused += 1;
        else {
          existingIds.add(example.exampleId);
          imported += 1;
        }
      }
    }
    return NextResponse.json({ imported, reused, skipped });
  } catch (error) {
    return goldenErrorResponse(error);
  }
}
