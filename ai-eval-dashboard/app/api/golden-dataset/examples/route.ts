import { NextRequest, NextResponse } from "next/server";

import {
  assertExactKeys,
  goldenErrorResponse,
  metricArray,
  objectValue,
  optionalString,
  queryList,
  readJsonObject,
  requiredString,
  stringArray,
} from "@/lib/server/golden-api";
import {
  GoldenValidationError,
  goldenCatalog,
  type GoldenExampleImport,
} from "@/lib/server/golden-catalog";
import type { GoldenMetricKey } from "@/types/evaluation";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  try {
    const rawDimensions = queryList(request.nextUrl.searchParams.get("dimensions"));
    const dimensions = rawDimensions ? metricArray(rawDimensions) : undefined;
    return NextResponse.json(
      await goldenCatalog.listExamples({
        search: request.nextUrl.searchParams.get("search") ?? undefined,
        tags: queryList(request.nextUrl.searchParams.get("tags")),
        dimensions: dimensions as GoldenMetricKey[] | undefined,
        collectionId: request.nextUrl.searchParams.get("collectionId") ?? undefined,
        runId: request.nextUrl.searchParams.get("runId") ?? undefined,
      })
    );
  } catch (error) {
    return goldenErrorResponse(error);
  }
}

type ImportService = Pick<typeof goldenCatalog, "importExample">;

function parseImport(body: Record<string, unknown>): GoldenExampleImport {
  assertExactKeys(body, ["content", "source", "review", "tags"]);
  const content = objectValue(body.content, "content");
  const source = objectValue(body.source, "source");
  const review = objectValue(body.review, "review");
  if (review.reviewStatus !== "approved") {
    throw new GoldenValidationError("Only approved human reviews can be imported.");
  }
  const overallStatus = requiredString(review.overallStatus, "review.overallStatus");
  if (!["pass", "warn", "fail"].includes(overallStatus)) {
    throw new GoldenValidationError("review.overallStatus is invalid.");
  }
  return {
    content: {
      userText: requiredString(content.userText, "content.userText"),
      responseText: requiredString(content.responseText, "content.responseText"),
      conversationContext: optionalString(
        content.conversationContext,
        "content.conversationContext"
      ),
      referenceContext: optionalString(content.referenceContext, "content.referenceContext"),
      referenceAnswer: optionalString(content.referenceAnswer, "content.referenceAnswer"),
    },
    source: {
      runId: requiredString(source.runId, "source.runId"),
      conversationId: requiredString(source.conversationId, "source.conversationId"),
      turnId: requiredString(source.turnId, "source.turnId"),
      reviewId: requiredString(source.reviewId, "source.reviewId"),
      reviewerId: requiredString(source.reviewerId, "source.reviewerId"),
      reviewedAt: requiredString(source.reviewedAt, "source.reviewedAt"),
      evaluationFingerprint: optionalString(
        source.evaluationFingerprint,
        "source.evaluationFingerprint"
      ),
    },
    review: {
      reviewStatus: "approved",
      overallStatus: overallStatus as "pass" | "warn" | "fail",
      safetyScores: objectValue(review.safetyScores, "review.safetyScores") as GoldenExampleImport["review"]["safetyScores"],
      performanceScores: objectValue(
        review.performanceScores,
        "review.performanceScores"
      ) as GoldenExampleImport["review"]["performanceScores"],
      notes: optionalString(review.notes, "review.notes") ?? "",
      flags: (review.flags === undefined ? [] : stringArray(review.flags, "review.flags")) as GoldenExampleImport["review"]["flags"],
    },
    tags: body.tags === undefined ? [] : stringArray(body.tags, "tags"),
  };
}

export async function handleExamplesPost(
  request: NextRequest,
  service: ImportService = goldenCatalog
) {
  try {
    const example = await service.importExample(parseImport(await readJsonObject(request)));
    return NextResponse.json(example, { status: 201 });
  } catch (error) {
    const response = goldenErrorResponse(error);
    if (response.status === 422) {
      return NextResponse.json(await response.json(), { status: 400 });
    }
    return response;
  }
}

export async function POST(request: NextRequest) {
  return handleExamplesPost(request);
}
