import { NextRequest } from "next/server";

export function createJsonPostRequest(url: string, body: unknown): NextRequest {
  return new NextRequest(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function createMalformedJsonPostRequest(url: string): NextRequest {
  return new NextRequest(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{not-json",
  });
}

export function createGetRequest(
  url: string,
  query: Record<string, string | undefined> = {}
): NextRequest {
  const parsed = new URL(url);
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined) {
      parsed.searchParams.set(key, value);
    }
  });
  return new NextRequest(parsed);
}