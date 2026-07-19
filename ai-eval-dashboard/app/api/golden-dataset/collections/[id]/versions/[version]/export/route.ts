import { NextRequest, NextResponse } from "next/server";

import { exportFormat, goldenErrorResponse } from "@/lib/server/golden-api";
import { goldenCatalog } from "@/lib/server/golden-catalog";

export const runtime = "nodejs";

type ExportService = Pick<typeof goldenCatalog, "exportCollectionVersion">;

export async function handleVersionExportGet(
  request: NextRequest,
  collectionId: string,
  version: string,
  service: ExportService = goldenCatalog
) {
  try {
    const result = await service.exportCollectionVersion(
      collectionId,
      version,
      exportFormat(request.nextUrl.searchParams.get("format"))
    );
    return new NextResponse(result.content, {
      headers: {
        "Content-Type": result.contentType,
        "Content-Disposition": `attachment; filename="${result.filename}"`,
        "X-Golden-Dataset-Preview": "false",
      },
    });
  } catch (error) {
    const response = goldenErrorResponse(error);
    if (response.status === 422) {
      return NextResponse.json(await response.json(), { status: 400 });
    }
    return response;
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; version: string }> }
) {
  const { id, version } = await params;
  return handleVersionExportGet(request, id, version);
}
