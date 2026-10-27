import { describe, expect, it, vi } from "vitest";

import { startSkill } from "./skills";

const reply = (status: number, body: unknown = {}) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));

describe("startSkill", () => {
  it("asks the server to open the skill in the chat", async () => {
    const fetchFn = reply(200, { started: true, error: null });
    expect(await startSkill("a=1", "acme", "idea-card", fetchFn)).toEqual({ kind: "started" });
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/miniapp/acme/skills/idea-card/start");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("tma a=1");
  });

  it("names why it did not start", async () => {
    const failed = (reason: string) => ({ kind: "failed", reason });
    expect(await startSkill("x", "d", "s", reply(409, { started: false, error: "no_chat" }))).toEqual(failed("no_chat"));
    expect(await startSkill("x", "d", "s", reply(404, { error: "unknown_skill" }))).toEqual(failed("unknown_skill"));
    expect(await startSkill("x", "d", "s", reply(500))).toEqual(failed("unavailable"));
    expect(await startSkill("x", "d", "s", vi.fn().mockRejectedValue(new Error("off")))).toEqual(failed("network"));
  });
});
