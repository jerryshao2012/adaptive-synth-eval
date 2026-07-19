import { NextRequest, NextResponse } from "next/server";

import {
  assertExactKeys,
  goldenErrorResponse,
  metricArray,
  optionalString,
  queryList,
  readJsonObject,
  requiredString,
  stringArray,
} from "@/lib/server/golden-api";
import { goldenCatalog } from "@/lib/server/golden-catalog";
import type { GoldenCollection, GoldenMetricKey } from "@/types/evaluation";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  try {
    const status = request.nextUrl.searchParams.get("status") ?? undefined;
    if (status && !["draft", "published", "archived"].includes(status)) {
      return NextResponse.json({ error: "Invalid collection status." }, { status: 400 });
    }
    const dimensions = queryList(request.nextUrl.searchParams.get("dimensions"));
    return NextResponse.json(
      await goldenCatalog.listCollections({
        search: request.nextUrl.searchParams.get("search") ?? undefined,
        tags: queryList(request.nextUrl.searchParams.get("tags")),
        dimensions: dimensions as GoldenMetricKey[] | undefined,
        status: status as GoldenCollection["status"] | undefined,
      })
    );
  } catch (error) {
    return goldenErrorResponse(error);
  }
}

type CreateCollectionService = Pick<typeof goldenCatalog, "createCollection">;

export async function handleCollectionsPost(
  request: NextRequest,
  service: CreateCollectionService = goldenCatalog
) {
  try {
    const body = await readJsonObject(request);
    assertExactKeys(body, ["name", "description", "dimensions", "tags"]);
    const collection = await service.createCollection({
      name: requiredString(body.name, "name"),
      description: optionalString(body.description, "description") ?? "",
      dimensions: metricArray(body.dimensions),
      tags: body.tags === undefined ? [] : stringArray(body.tags, "tags"),
    });
    return NextResponse.json(collection, { status: 201 });
  } catch (error) {
    const response = goldenErrorResponse(error);
    if (response.status === 422) {
      return NextResponse.json(await response.json(), { status: 400 });
    }
    return response;
  }
}

export async function POST(request: NextRequest) {
  return handleCollectionsPost(request);
}
