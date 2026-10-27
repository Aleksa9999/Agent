import { describe, expect, it, vi } from "vitest";

import ru from "../messages/ru.json";
import en from "../messages/en.json";
import { loadSession, tenantFromSearch } from "./session";

const json = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));

describe("loadSession", () => {
  it("does not call the server outside Telegram", async () => {
    const fetchFn = vi.fn();
    expect(await loadSession(undefined, "default", fetchFn)).toEqual({ kind: "outside_telegram" });
    expect(await loadSession("", "default", fetchFn)).toEqual({ kind: "outside_telegram" });
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("sends the signed launch data in the Authorization header", async () => {
    const fetchFn = json(200, { user: { id: 7, first_name: "Anna", role: "member" }, brand: "B", locale: "ru" });
    const state = await loadSession("auth_date=1&hash=abc", "default", fetchFn);
    expect(state).toMatchObject({ kind: "ready", brand: "B", user: { id: 7 } });
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/miniapp/default/session");
    expect(init.headers.Authorization).toBe("tma auth_date=1&hash=abc");
  });

  it("separates an expired session from a rejected one", async () => {
    expect(await loadSession("x", "default", json(401, { error: "expired" }))).toEqual({ kind: "expired" });
    expect(await loadSession("x", "default", json(401, { error: "invalid_signature" }))).toEqual({ kind: "denied" });
    expect(await loadSession("x", "default", json(401, {}))).toEqual({ kind: "denied" });
  });

  it("reports server and network failures as a retryable error", async () => {
    expect(await loadSession("x", "default", json(503, { error: "not_configured" }))).toEqual({ kind: "error" });
    expect(await loadSession("x", "default", vi.fn().mockRejectedValue(new Error("offline")))).toEqual({ kind: "error" });
    expect(await loadSession("x", "default", vi.fn().mockResolvedValue(new Response("not json", { status: 200 })))).toEqual({ kind: "error" });
  });
});

describe("tenantFromSearch", () => {
  it("takes a valid tenant and falls back to default for anything else", () => {
    expect(tenantFromSearch("?tenant=acme")).toBe("acme");
    expect(tenantFromSearch("")).toBe("default");
    expect(tenantFromSearch("?tenant=../etc")).toBe("default");
  });
});

describe("messages", () => {
  it("has the same keys in every language", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort());
  });
});
