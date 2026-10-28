import { describe, expect, it, vi } from "vitest";

import { tap } from "./haptics";

describe("tap", () => {
  it("asks Telegram for a light impact", () => {
    const impactOccurred = vi.fn();
    tap({ impactOccurred });
    expect(impactOccurred).toHaveBeenCalledWith("light");
  });

  it("does nothing without support and never throws", () => {
    expect(() => tap(undefined)).not.toThrow();
    expect(() => tap({})).not.toThrow();
    expect(() => tap({ impactOccurred: () => { throw new Error("no"); } })).not.toThrow();
  });
});
