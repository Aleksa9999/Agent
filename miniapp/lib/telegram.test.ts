import { describe, expect, it } from "vitest";

import { describeLaunch, initDataFromHash, waitForInitData } from "./telegram";

const fast = { sleep: async () => {}, hash: "" };

describe("launch data", () => {
  it("reads it from the launch address when the script gave nothing", () => {
    expect(initDataFromHash("#tgWebAppData=auth_date%3D1%26hash%3Dabc&tgWebAppVersion=9")).toBe("auth_date=1&hash=abc");
    expect(initDataFromHash("")).toBeUndefined();
    expect(initDataFromHash("#tgWebAppVersion=9")).toBeUndefined();
  });

  it("waits for a late script", async () => {
    const app: { initData?: string } = {};
    let sleeps = 0;
    const env = {
      app,
      hash: "",
      sleep: async () => {
        sleeps += 1;
        if (sleeps === 3) app.initData = "late=1";
      },
    };
    expect(await waitForInitData(env)).toBe("late=1");
    expect(sleeps).toBe(3);
  });

  it("falls back to the address, and gives up when there is nothing", async () => {
    expect(await waitForInitData({ ...fast, hash: "#tgWebAppData=a%3D1" })).toBe("a=1");
    expect(await waitForInitData({ ...fast, app: {} })).toBeUndefined();
  });
});

describe("describeLaunch", () => {
  it("says what was and was not given, without any values", () => {
    expect(describeLaunch({ hash: "", href: "https://a.test/?tenant=default" })).toBe(
      "script=no platform=- version=- initData=no hash=[empty] query=yes",
    );
    const line = describeLaunch({
      app: { initData: "secret=1", platform: "ios", version: "9.1" },
      hash: "#tgWebAppData=secret%3D1&tgWebAppVersion=9.1&tgWebAppPlatform=ios",
      href: "https://a.test/",
    });
    expect(line).toBe("script=yes platform=ios version=9.1 initData=yes hash=[Data,Version,Platform] query=no");
    expect(line).not.toContain("secret");
  });
});
