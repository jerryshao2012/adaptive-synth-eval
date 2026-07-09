import { NextRequest, NextResponse } from "next/server";
import { bulkApprove, bulkFlag } from "@/lib/server/reviews";

export const runtime = "nodejs";

interface BulkRequest {
  action: "approve" | "flag";
  records: Array<{ runId: string; turnId: string }>;
  flag?: string;
}

export async function POST(request: NextRequest) {
  let payload: BulkRequest;
  try {
    payload = (await request.json()) as BulkRequest;
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body." },
      { status: 400 }
    );
  }

  if (!payload?.action || !Array.isArray(payload?.records)) {
    return NextResponse.json(
      { error: "action and records array are required." },
      { status: 400 }
    );
  }

  if (!["approve", "flag"].includes(payload.action)) {
    return NextResponse.json(
      { error: "action must be 'approve' or 'flag'." },
      { status: 400 }
    );
  }

  try {
    let count: number;
    if (payload.action === "approve") {
      count = await bulkApprove(payload.records);
    } else {
      count = await bulkFlag(payload.records, payload.flag || "needs_discussion");
    }
    return NextResponse.json({ success: true, updated: count });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Bulk operation failed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
