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
