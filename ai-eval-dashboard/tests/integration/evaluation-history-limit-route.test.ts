import { afterEach, describe, expect, it, vi } from "vitest";

import { createGetRequest } from "./test-utils";

const mocks = vi.hoisted(() => ({
  getMonitoringEvaluations: vi.fn(),
}));

vi.mock("@/lib/server/monitoring", () => ({
  getMonitoringEvaluations: mocks.getMonitoringEvaluations,
}));

import { GET } from "@/app/api/evaluations/history/route";

afterEach(() => {
  mocks.getMonitoringEvaluations.mockReset();
});

describe("GET /api/evaluations/history limit validation", () => {
  it("passes an explicit all limit to the local monitoring reader", async () => {
    const evaluations = Array.from({ length: 2005 }, (_, index) => ({
      timestamp: new Date(Date.UTC(2020, 0, 1, 0, 0, index)).toISOString(),
      turn_id: `turn-${index}`,
    }));
    mocks.getMonitoringEvaluations.mockResolvedValue({
      evaluations,
      profilePeriods: [],
      total: evaluations.length,
      from: "",
      to: "",
    });

    const response = await GET(
      createGetRequest("http://localhost/api/evaluations/history", {
        runId: "large-run",
        limit: "all",
      })
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(mocks.getMonitoringEvaluations).toHaveBeenCalledWith(
      "large-run",
      undefined,
      undefined,
      null
    );
    expect(payload.evaluations).toHaveLength(2005);
    expect(payload.evaluations.at(-1).turn_id).toBe("turn-2004");
    expect(payload.total).toBe(2005);
  });

  it.each(["0", "-1", "2.5", "invalid"])(
    "rejects invalid limit %s before reading a run",
    async (limit) => {
      const response = await GET(
        createGetRequest("http://localhost/api/evaluations/history", {
          runId: "large-run",
          limit,
        })
      );

      expect(response.status).toBe(400);
      expect(mocks.getMonitoringEvaluations).not.toHaveBeenCalled();
    }
  );

  it("retains numeric local limits", async () => {
    mocks.getMonitoringEvaluations.mockResolvedValue({
      evaluations: [],
      profilePeriods: [],
      total: 0,
      from: "",
      to: "",
    });

    await GET(
      createGetRequest("http://localhost/api/evaluations/history", {
        runId: "numeric-run",
        limit: "25",
      })
    );

    expect(mocks.getMonitoringEvaluations).toHaveBeenCalledWith(
      "numeric-run",
      undefined,
      undefined,
      25
    );
  });
});
