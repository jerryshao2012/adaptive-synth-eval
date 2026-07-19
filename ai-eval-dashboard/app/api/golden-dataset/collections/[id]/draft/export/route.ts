import { NextRequest, NextResponse } from "next/server";

import { exportFormat, goldenErrorResponse } from "@/lib/server/golden-api";
import { goldenCatalog } from "@/lib/server/golden-catalog";

export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const result = await goldenCatalog.exportCollectionDraft(
      id,
      exportFormat(request.nextUrl.searchParams.get("format"))
    );
    return new NextResponse(result.content, {
      headers: {
        "Content-Type": result.contentType,
        "Content-Disposition": `attachment; filename="${result.filename}"`,
        "X-Golden-Dataset-Preview": "true",
      },
    });
  } catch (error) {
    return goldenErrorResponse(error);
  }
}
