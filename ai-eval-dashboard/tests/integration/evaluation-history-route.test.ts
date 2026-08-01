import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/evaluations/history/route";
import { createGetRequest } from "./test-utils";

const originalBackendUrl = process.env.EVAL_BACKEND_URL;

afterEach(() => {
  if (originalBackendUrl === undefined) {
    delete process.env.EVAL_BACKEND_URL;
  } else {
    process.env.EVAL_BACKEND_URL = originalBackendUrl;
  }
  vi.unstubAllGlobals();
});

describe("GET /api/evaluations/history profile period compatibility", () => {
  it("includes an empty profile period list in mock responses", async () => {
    delete process.env.EVAL_BACKEND_URL;

    const response = await GET(
      createGetRequest("http://localhost/api/evaluations/history", { limit: "1" })
    );
    const payload = await response.json();

    expect(payload.profilePeriods).toEqual([]);
    expect(payload.evaluations).toHaveLength(1);
  });

  it("normalizes legacy backend responses that omit profile periods", async () => {
    process.env.EVAL_BACKEND_URL = "http://backend.invalid";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ evaluations: [], total: 0, from: "", to: "" }),
          { status: 200, headers: { "content-type": "application/json" } }
        )
      )
    );

    const response = await GET(
      createGetRequest("http://localhost/api/evaluations/history")
    );

    expect(await response.json()).toEqual({
      evaluations: [],
      profilePeriods: [],
      total: 0,
      from: "",
      to: "",
    });
  });
});
