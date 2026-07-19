import { NextRequest, NextResponse } from "next/server";

import { goldenErrorResponse, revision } from "@/lib/server/golden-api";
import { GoldenValidationError, goldenCatalog } from "@/lib/server/golden-catalog";

export const runtime = "nodejs";

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; exampleId: string }> }
) {
  try {
    const { id, exampleId } = await params;
    const rawRevision = request.nextUrl.searchParams.get("expectedRevision");
    if (rawRevision === null) {
      throw new GoldenValidationError("expectedRevision is required.");
    }
    return NextResponse.json(
      await goldenCatalog.removeMembership(id, exampleId, revision(Number(rawRevision)))
    );
  } catch (error) {
    return goldenErrorResponse(error);
  }
}
