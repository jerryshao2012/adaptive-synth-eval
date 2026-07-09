import { NextRequest, NextResponse } from "next/server";
import { getReviewQueue } from "@/lib/server/reviews";
import type { ReviewQueueFilters } from "@/types/evaluation";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);

  const filters: ReviewQueueFilters = {};

  const status = searchParams.get("status");
  if (
    status === "pass" ||
    status === "warn" ||
    status === "fail"
  ) {
    filters.status = status;
  }

  const runId = searchParams.get("runId");
  if (runId) filters.runId = runId;

  const metricKey = searchParams.get("metricKey");
  if (metricKey) filters.metricKey = metricKey;

  const searchText = searchParams.get("searchText");
  if (searchText) filters.searchText = searchText;

  const disputedOnly = searchParams.get("disputedOnly");
  if (disputedOnly === "true") filters.disputedOnly = true;

  const unreviewedOnly = searchParams.get("unreviewedOnly");
  if (unreviewedOnly === "true") filters.unreviewedOnly = true;

  const page = searchParams.get("page");
  if (page) filters.page = parseInt(page, 10) || 1;

  const pageSize = searchParams.get("pageSize");
  if (pageSize) filters.pageSize = parseInt(pageSize, 10) || 50;

  const sortBy = searchParams.get("sortBy");
  if (
    sortBy === "timestamp" ||
    sortBy === "avgAiScore" ||
    sortBy === "safetyStatus" ||
    sortBy === "reviewStatus"
  ) {
    filters.sortBy = sortBy;
  }

  const sortOrder = searchParams.get("sortOrder");
  if (sortOrder === "asc" || sortOrder === "desc") {
    filters.sortOrder = sortOrder;
  }

  try {
    const data = await getReviewQueue(filters);
    return NextResponse.json(data);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to load review queue.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
