import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

import {
  handleCollectionsPost,
} from "@/app/api/golden-dataset/collections/route";
import {
  handlePublishPost,
} from "@/app/api/golden-dataset/collections/[id]/publish/route";
import { handleExamplesPost } from "@/app/api/golden-dataset/examples/route";
import {
  handleMembersDelete,
  handleMembersPost,
} from "@/app/api/golden-dataset/collections/[id]/members/route";
import { handleVersionExportGet } from "@/app/api/golden-dataset/collections/[id]/versions/[version]/export/route";
import { GoldenConflictError } from "@/lib/server/golden-catalog";
import { GET as getLegacyDataset } from "@/app/api/golden-dataset/[id]/route";

function jsonRequest(url: string, body: unknown): NextRequest {
  return new NextRequest(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("golden collection API", () => {
  it("rejects unknown fields and invalid metric dimensions", async () => {
    const create = vi.fn();
    const response = await handleCollectionsPost(
      jsonRequest("http://localhost/api/golden-dataset/collections", {
        name: "Toxicity",
        description: "Safety cases",
        dimensions: ["not_a_metric"],
        tags: [],
        unexpected: true,
      }),
      { createCollection: create }
    );

    expect(response.status).toBe(400);
    expect((await response.json()).error).toMatch(/unexpected/i);
    expect(create).not.toHaveBeenCalled();
  });

  it("passes normalized collection input to the service", async () => {
    const create = vi.fn().mockResolvedValue({ collectionId: "collection-1" });
    const response = await handleCollectionsPost(
      jsonRequest("http://localhost/api/golden-dataset/collections", {
        name: " Toxicity ",
        description: " Safety cases ",
        dimensions: ["toxicity"],
        tags: ["Safety"],
      }),
      { createCollection: create }
    );

    expect(response.status).toBe(201);
    expect(create).toHaveBeenCalledWith({
      name: "Toxicity",
      description: "Safety cases",
      dimensions: ["toxicity"],
      tags: ["Safety"],
    });
  });

  it("maps optimistic publication conflicts to 409", async () => {
    const publish = vi
      .fn()
      .mockRejectedValue(new GoldenConflictError("revision changed"));
    const response = await handlePublishPost(
      jsonRequest(
        "http://localhost/api/golden-dataset/collections/collection-1/publish",
        { version: "1.0.0", expectedRevision: 2, publisherId: "curator" }
      ),
      "collection-1",
      { publishCollection: publish }
    );

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({
      error: "revision changed",
      code: "conflict",
    });
  });

  it("requires approved review snapshots before importing an example", async () => {
    const importExample = vi.fn();
    const response = await handleExamplesPost(
      jsonRequest("http://localhost/api/golden-dataset/examples", {
        content: { userText: "hello", responseText: "world" },
        source: {
          runId: "run-1",
          conversationId: "c-1",
          turnId: "t-1",
          reviewId: "review-1",
          reviewerId: "curator",
          reviewedAt: "2026-07-19T12:00:00Z",
        },
        review: {
          reviewStatus: "draft",
          overallStatus: "pass",
          safetyScores: {},
          performanceScores: {},
          notes: "",
          flags: [],
        },
      }),
      { importExample }
    );

    expect(response.status).toBe(400);
    expect(importExample).not.toHaveBeenCalled();
  });

  it("accepts a membership upsert with explicit concurrency revision", async () => {
    const upsertMembership = vi.fn().mockResolvedValue({ revision: 3 });
    const response = await handleMembersPost(
      jsonRequest(
        "http://localhost/api/golden-dataset/collections/collection-1/members",
        {
          expectedRevision: 2,
          exampleId: "example-1",
          annotations: {
            toxicity: {
              expectedStatus: "fail",
              expectedScore: 10,
              rationale: "Unsafe",
              reviewerId: "curator",
              reviewedAt: "2026-07-19T12:00:00Z",
            },
          },
          weight: 2,
          notes: "high priority",
        }
      ),
      "collection-1",
      { upsertMembership }
    );

    expect(response.status).toBe(200);
    expect(upsertMembership).toHaveBeenCalledWith("collection-1", {
      expectedRevision: 2,
      exampleId: "example-1",
      annotations: expect.objectContaining({
        toxicity: expect.objectContaining({ expectedStatus: "fail" }),
      }),
      weight: 2,
      notes: "high priority",
    });
  });

  it("preserves omitted membership annotations and notes", async () => {
    const upsertMembership = vi.fn().mockResolvedValue({ revision: 3 });
    const response = await handleMembersPost(
      jsonRequest(
        "http://localhost/api/golden-dataset/collections/collection-1/members",
        { expectedRevision: 2, exampleId: "example-1", weight: 3 }
      ),
      "collection-1",
      { upsertMembership }
    );

    expect(response.status).toBe(200);
    expect(upsertMembership).toHaveBeenCalledWith("collection-1", {
      expectedRevision: 2,
      exampleId: "example-1",
      weight: 3,
    });
  });

  it("accepts a bulk membership request as one atomic service call", async () => {
    const upsertMemberships = vi.fn().mockResolvedValue({ revision: 3 });
    const members = [
      {
        exampleId: "example-1",
        annotations: {
          toxicity: {
            expectedStatus: "fail",
            rationale: "Unsafe",
            reviewerId: "curator",
            reviewedAt: "2026-07-19T12:00:00Z",
          },
        },
      },
      {
        exampleId: "example-2",
        annotations: {
          toxicity: {
            expectedStatus: "warn",
            rationale: "Borderline",
            reviewerId: "curator",
            reviewedAt: "2026-07-19T12:00:00Z",
          },
        },
      },
    ];
    const response = await handleMembersPost(
      jsonRequest(
        "http://localhost/api/golden-dataset/collections/collection-1/members",
        { expectedRevision: 2, members }
      ),
      "collection-1",
      { upsertMemberships }
    );

    expect(response.status).toBe(200);
    expect(upsertMemberships).toHaveBeenCalledWith("collection-1", {
      expectedRevision: 2,
      members: expect.arrayContaining([
        expect.objectContaining({ exampleId: "example-1" }),
        expect.objectContaining({ exampleId: "example-2" }),
      ]),
    });
  });

  it("removes selected memberships as one atomic service call", async () => {
    const removeMemberships = vi.fn().mockResolvedValue({ revision: 4 });
    const response = await handleMembersDelete(
      jsonRequest(
        "http://localhost/api/golden-dataset/collections/collection-1/members",
        { expectedRevision: 3, exampleIds: ["example-1", "example-2"] }
      ),
      "collection-1",
      { removeMemberships }
    );

    expect(response.status).toBe(200);
    expect(removeMemberships).toHaveBeenCalledWith("collection-1", {
      expectedRevision: 3,
      exampleIds: ["example-1", "example-2"],
    });
  });

  it("rejects unsupported version export formats", async () => {
    const exportCollectionVersion = vi.fn();
    const request = new NextRequest(
      "http://localhost/api/golden-dataset/collections/c-1/versions/1.0.0/export?format=xml"
    );
    const response = await handleVersionExportGet(
      request,
      "c-1",
      "1.0.0",
      { exportCollectionVersion }
    );

    expect(response.status).toBe(400);
    expect(exportCollectionVersion).not.toHaveBeenCalled();
  });

  it("rejects unsafe identifiers on the legacy compatibility endpoint", async () => {
    const response = await getLegacyDataset(
      new NextRequest("http://localhost/api/golden-dataset/escape"),
      { params: Promise.resolve({ id: "../escape" }) }
    );

    expect(response.status).toBe(400);
  });
});
