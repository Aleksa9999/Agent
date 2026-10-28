import { describe, expect, it, vi } from "vitest";

import { loadHome, runFirstResult, runFirstResultVoice } from "./home";
import { parseBlocks, parseInline } from "./markdown";

const reply = (status: number, body: unknown = {}) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));

describe("home", () => {
  it("loads the home view with the signed launch data", async () => {
    const home = { track: "business", level: 1 };
    const fetchFn = reply(200, home);
    expect(await loadHome("a=1", "acme", fetchFn)).toEqual({ kind: "ready", home });
    expect(fetchFn.mock.calls[0][0]).toBe("/api/miniapp/acme/home");
    expect(fetchFn.mock.calls[0][1].headers.Authorization).toBe("tma a=1");
    expect(await loadHome("a=1", "acme", reply(503))).toEqual({ kind: "error" });
    expect(await loadHome("a=1", "acme", vi.fn().mockRejectedValue(new Error("off")))).toEqual({ kind: "error" });
  });

  it("runs the first result from text or voice and names the failures", async () => {
    const home = { track: "business" };
    const ok = reply(200, { result: {}, home });
    expect(await runFirstResult("x", "default", "дела", ok)).toEqual({ kind: "done", home });
    expect(JSON.parse(ok.mock.calls[0][1].body)).toEqual({ text: "дела" });
    const failed = (reason: string) => ({ kind: "failed", reason });
    expect(await runFirstResult("x", "d", "a", reply(422, { error: "need_text" }))).toEqual(failed("need_text"));
    expect(await runFirstResult("x", "d", "a", reply(429, { error: "rate_limited" }))).toEqual(failed("rate_limited"));
    expect(await runFirstResult("x", "d", "a", vi.fn().mockRejectedValue(new Error("off")))).toEqual(failed("network"));
    const audio = new Blob(["a"], { type: "audio/webm" });
    expect(await runFirstResultVoice("x", "d", audio, reply(413))).toEqual(failed("too_big"));
    expect(await runFirstResultVoice("x", "d", audio, reply(503, { error: "no_asr" }))).toEqual(failed("no_asr"));
  });
});

describe("parseBlocks", () => {
  it("splits a table from the text around it", () => {
    const source = "Итог\n\n| Дело | Часы |\n|---|---|\n| Заявки | 22 |\n| Отчёт | 8 |\n\nТоп-3: заявки";
    expect(parseBlocks(source)).toEqual([
      { kind: "text", text: "Итог" },
      { kind: "table", header: ["Дело", "Часы"], rows: [["Заявки", "22"], ["Отчёт", "8"]] },
      { kind: "text", text: "Топ-3: заявки" },
    ]);
  });

  it("keeps a lone bar line as text and survives empty input", () => {
    expect(parseBlocks("| не таблица")).toEqual([{ kind: "text", text: "| не таблица" }]);
    expect(parseBlocks("")).toEqual([]);
  });
});

describe("markdown for results", () => {
  it("turns headings and bullet lists into blocks", () => {
    expect(parseBlocks("## Карточка идеи\n\n- **Для кого:** эксперты\n- Проблема\n\nИтог")).toEqual([
      { kind: "heading", level: 2, text: "Карточка идеи" },
      { kind: "list", items: ["**Для кого:** эксперты", "Проблема"] },
      { kind: "text", text: "Итог" },
    ]);
  });

  it("reads bold and italic and leaves unclosed marks alone", () => {
    expect(parseInline("a **b** c *d* e")).toEqual([
      { kind: "text", text: "a " },
      { kind: "bold", text: "b" },
      { kind: "text", text: " c " },
      { kind: "italic", text: "d" },
      { kind: "text", text: " e" },
    ]);
    expect(parseInline("2 * 3 и **без конца")).toEqual([{ kind: "text", text: "2 * 3 и **без конца" }]);
    expect(parseInline("<b>html</b>")).toEqual([{ kind: "text", text: "<b>html</b>" }]);
  });
});
