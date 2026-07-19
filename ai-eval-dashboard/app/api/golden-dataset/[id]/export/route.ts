import { NextRequest, NextResponse } from "next/server";
import { exportDataset, LegacyDatasetIdError } from "@/lib/server/golden-datasets";

export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { searchParams } = new URL(request.url);
  const format = searchParams.get("format") === "csv" ? "csv" : "jsonl";

  try {
    const result = await exportDataset(id, format);
    return new NextResponse(result.content, {
      headers: {
        "Content-Type": result.contentType,
        "Content-Disposition": `attachment; filename="${result.filename}"`,
      },
    });
  } catch (error) {
    if (error instanceof LegacyDatasetIdError) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    const message =
      error instanceof Error ? error.message : "Failed to export dataset.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
