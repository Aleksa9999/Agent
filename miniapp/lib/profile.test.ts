import { describe, expect, it, vi } from "vitest";

import { confirmProfile, editLine, goBack, loadProfile, sendAnswer, sendVoice } from "./profile";
import { detectMic, pickMime, recordError } from "./recorder";

const reply = (status: number, body: unknown = {}) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));

describe("profile requests", () => {
  it("sends the signed launch data and the answer", async () => {
    const fetchFn = reply(200, { status: "collecting" });
    const result = await sendAnswer("a=1&hash=x", "acme", "role", { kind: "option", code: "student" }, fetchFn);
    expect(result).toMatchObject({ kind: "ready", profile: { status: "collecting" } });
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/miniapp/acme/profile/answer");
    expect(init.headers.Authorization).toBe("tma a=1&hash=x");
    expect(JSON.parse(init.body)).toEqual({ field: "role", kind: "option", code: "student" });
  });

  it("tells an old screen from a refused answer from a broken server", async () => {
    expect(await loadProfile("x", "default", reply(409))).toEqual({ kind: "stale" });
    expect(await sendAnswer("x", "default", "f", { kind: "unknown" }, reply(422))).toEqual({ kind: "rejected" });
    expect(await goBack("x", "default", reply(503))).toEqual({ kind: "error" });
    expect(await loadProfile("x", "default", vi.fn().mockRejectedValue(new Error("off")))).toEqual({ kind: "error" });
  });
});

describe("sendVoice", () => {
  const audio = new Blob(["abc"], { type: "audio/webm" });

  it("posts the recording with its own type", async () => {
    const profile = { status: "collecting" };
    const fetchFn = reply(200, { outcome: "ok", profile, new_fields: 3 });
    expect(await sendVoice("x", "default", audio, fetchFn)).toEqual({ kind: "heard", profile, newFields: 3 });
    expect(fetchFn.mock.calls[0][1].headers["Content-Type"]).toBe("audio/webm");
  });

  it("names every way it can fail", async () => {
    const failed = (reason: string) => ({ kind: "failed", reason });
    expect(await sendVoice("x", "d", audio, reply(200, { outcome: "nothing", profile: null, new_fields: 0 }))).toEqual(failed("nothing"));
    expect(await sendVoice("x", "d", audio, reply(200, { outcome: "no_asr", profile: null, new_fields: 0 }))).toEqual(failed("no_asr"));
    expect(await sendVoice("x", "d", audio, reply(429))).toEqual(failed("rate_limited"));
    expect(await sendVoice("x", "d", audio, reply(413))).toEqual(failed("too_big"));
    expect(await sendVoice("x", "d", audio, reply(415))).toEqual(failed("unsupported"));
    expect(await sendVoice("x", "d", audio, vi.fn().mockRejectedValue(new Error("off")))).toEqual(failed("network"));
  });
});

describe("microphone", () => {
  const ok = { isSecureContext: true, mediaDevices: { getUserMedia: () => {} }, hasMediaRecorder: true };

  it("is found only when the device can really record", () => {
    expect(detectMic(ok)).toBe("ok");
    expect(detectMic({ ...ok, hasMediaRecorder: false })).toBe("unsupported");
    expect(detectMic({ ...ok, mediaDevices: undefined })).toBe("unsupported");
    expect(detectMic({ ...ok, mediaDevices: {} })).toBe("unsupported");
    expect(detectMic({ ...ok, isSecureContext: false })).toBe("unsupported");
  });

  it("explains a refusal", () => {
    expect(recordError({ name: "NotAllowedError" })).toBe("denied");
    expect(recordError({ name: "NotFoundError" })).toBe("no_device");
    expect(recordError(new Error("x"))).toBe("failed");
    expect(recordError(null)).toBe("failed");
  });

  it("picks the first format the browser can record", () => {
    expect(pickMime((type) => type === "audio/mp4")).toBe("audio/mp4");
    expect(pickMime(() => true)).toBe("audio/webm;codecs=opus");
    expect(pickMime(() => false)).toBeUndefined();
  });
});

describe("card actions", () => {
  it("confirms and returns the profile with the new passport", async () => {
    const profile = { status: "complete", card: { lines: [], passport: { version: 1, current: true, published: true } } };
    const fetchFn = reply(200, { confirm: { version: 1, created: true, published: true }, profile });
    expect(await confirmProfile("a=1", "acme", fetchFn)).toEqual({ kind: "ready", profile });
    expect(fetchFn.mock.calls[0][0]).toBe("/api/miniapp/acme/profile/confirm");
    expect(await confirmProfile("a=1", "acme", reply(409))).toEqual({ kind: "stale" });
    expect(await confirmProfile("a=1", "acme", reply(500))).toEqual({ kind: "error" });
  });

  it("asks to fix one line of the card", async () => {
    const fetchFn = reply(200, { status: "complete" });
    await editLine("a=1", "default", "resources", fetchFn);
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({ line: "resources" });
    expect(await editLine("a=1", "default", "zzz", reply(422))).toEqual({ kind: "rejected" });
  });
});
