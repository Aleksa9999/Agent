import { describe, expect, it, vi } from "vitest";

import { loadCatalog } from "./catalog";

const reply = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));

describe("loadCatalog", () => {
  it("asks with the signed launch data and returns the catalog", async () => {
    const body = { total: 1, directions: [], branches: [{ id: "code", skills: [] }] };
    const fetchFn = reply(200, body);
    expect(await loadCatalog("a=1&hash=x", "acme", fetchFn)).toEqual({ kind: "ready", catalog: body });
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/miniapp/acme/catalog");
    expect(init.headers.Authorization).toBe("tma a=1&hash=x");
  });

  it("turns server errors, odd bodies and a lost network into one retryable error", async () => {
    expect(await loadCatalog("x", "default", reply(401, {}))).toEqual({ kind: "error" });
    expect(await loadCatalog("x", "default", reply(200, { total: 0 }))).toEqual({ kind: "error" });
    expect(await loadCatalog("x", "default", vi.fn().mockRejectedValue(new Error("offline")))).toEqual({ kind: "error" });
  });
});
