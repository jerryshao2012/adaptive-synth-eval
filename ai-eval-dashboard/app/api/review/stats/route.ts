import { NextResponse } from "next/server";
import { getReviewStats } from "@/lib/server/reviews";

export const runtime = "nodejs";

export async function GET() {
  try {
    const stats = await getReviewStats();
    return NextResponse.json(stats);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to load review stats.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
