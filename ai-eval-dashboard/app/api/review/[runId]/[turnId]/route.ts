import { NextRequest, NextResponse } from "next/server";
import { getReviewDetail, saveHumanReview } from "@/lib/server/reviews";
import type { HumanReview } from "@/types/evaluation";

export const runtime = "nodejs";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string; turnId: string }> }
) {
  const { runId, turnId } = await params;

  try {
    const detail = await getReviewDetail(runId, turnId);
    if (!detail) {
      return NextResponse.json(
        { error: "Record not found." },
        { status: 404 }
      );
    }
    return NextResponse.json(detail);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to load review detail.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string; turnId: string }> }
) {
  const { runId, turnId } = await params;

  let review: HumanReview;
  try {
    review = (await request.json()) as HumanReview;
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body." },
      { status: 400 }
    );
  }

  if (review.runId !== runId || review.turnId !== turnId) {
    return NextResponse.json(
      { error: "runId/turnId mismatch between URL and body." },
      { status: 400 }
    );
  }

  try {
    await saveHumanReview(review);
    return NextResponse.json({ success: true });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to save review.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
