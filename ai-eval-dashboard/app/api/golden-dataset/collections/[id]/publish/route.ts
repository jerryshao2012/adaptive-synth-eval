import { NextRequest, NextResponse } from "next/server";

import {
  assertExactKeys,
  goldenErrorResponse,
  readJsonObject,
  requiredString,
  revision,
} from "@/lib/server/golden-api";
import { goldenCatalog } from "@/lib/server/golden-catalog";

export const runtime = "nodejs";

type PublishService = Pick<typeof goldenCatalog, "publishCollection">;

export async function handlePublishPost(
  request: NextRequest,
  collectionId: string,
  service: PublishService = goldenCatalog
) {
  try {
    const body = await readJsonObject(request);
    assertExactKeys(body, ["version", "expectedRevision", "publisherId"]);
    const version = await service.publishCollection(collectionId, {
      version: requiredString(body.version, "version"),
      expectedRevision: revision(body.expectedRevision),
      publisherId: requiredString(body.publisherId, "publisherId"),
    });
    return NextResponse.json(version, { status: 201 });
  } catch (error) {
    return goldenErrorResponse(error);
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  return handlePublishPost(request, id);
}
