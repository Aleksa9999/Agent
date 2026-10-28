/** Launch data from Telegram. The script can be a moment late, so it is awaited and, if needed,
 * read from the launch address (the part after #, as Telegram passes it). */

export function initDataFromHash(hash: string): string | undefined {
  const raw = new URLSearchParams(hash.replace(/^#/, "")).get("tgWebAppData");
  return raw ? raw : undefined;
}

type Env = {
  app?: { initData?: string };
  hash: string;
  sleep: (ms: number) => Promise<void>;
};

export async function waitForInitData(env: Env, attempts = 12, stepMs = 250): Promise<string | undefined> {
  for (let i = 0; i < attempts; i += 1) {
    const data = env.app?.initData || initDataFromHash(env.hash);
    if (data) return data;
    await env.sleep(stepMs);
  }
  return undefined;
}

/** A short line about what Telegram gave this page: shown on the "Open from Telegram" screen so
 * that a screenshot says why the launch data is missing. It holds no personal data. */
export function describeLaunch(env: {
  app?: { initData?: string; platform?: string; version?: string };
  hash: string;
  href: string;
}): string {
  const params = new URLSearchParams(env.hash.replace(/^#/, ""));
  const keys = Array.from(params.keys()).map((key) => key.replace(/^tgWebApp/, "")).join(",");
  const query = env.href.includes("?") ? "query=yes" : "query=no";
  return [
    `script=${env.app ? "yes" : "no"}`,
    `platform=${env.app?.platform ?? "-"}`,
    `version=${env.app?.version ?? "-"}`,
    `initData=${env.app?.initData ? "yes" : "no"}`,
    `hash=[${keys || "empty"}]`,
    query,
  ].join(" ");
}
