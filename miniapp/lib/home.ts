/** "My Googlagent": the home view and the first result. */

export type HomeSkill = {
  slug: string;
  title: string;
  branch: string;
  version: string;
  status: "unverified" | "verified";
  extra: boolean;
};
export type FirstResult = { kind: "routines" | "idea" | "plan"; track: string; text: string; code: string | null; seconds: number };
export type Home = {
  track: string | null;
  level: number;
  counter: number;
  branches: { id: string; assigned: number; verified: number }[];
  skills: HomeSkill[];
  first_result: FirstResult | null;
  first_result_input: "text" | "none";
  voice_available: boolean;
};

export type HomeState = { kind: "ready"; home: Home } | { kind: "error" };
export type RunState =
  | { kind: "done"; home: Home }
  | { kind: "failed"; reason: string };

type Fetch = typeof fetch;
const base = (tenant: string) => `/api/miniapp/${encodeURIComponent(tenant)}`;

export async function loadHome(initData: string, tenant: string, fetchFn: Fetch = fetch): Promise<HomeState> {
  try {
    const response = await fetchFn(`${base(tenant)}/home`, {
      headers: { Authorization: `tma ${initData}` },
      cache: "no-store",
    });
    if (!response.ok) return { kind: "error" };
    return { kind: "ready", home: (await response.json()) as Home };
  } catch {
    return { kind: "error" };
  }
}

async function run(url: string, init: RequestInit, initData: string, fetchFn: Fetch): Promise<RunState> {
  let response: Response;
  try {
    response = await fetchFn(url, {
      ...init,
      method: "POST",
      headers: { ...(init.headers as Record<string, string>), Authorization: `tma ${initData}` },
      cache: "no-store",
    });
  } catch {
    return { kind: "failed", reason: "network" };
  }
  const body = (await response.json().catch(() => ({}))) as { error?: string; home?: Home };
  if (response.ok && body.home) return { kind: "done", home: body.home };
  if (response.status === 413) return { kind: "failed", reason: "too_big" };
  if (response.status === 415) return { kind: "failed", reason: "unsupported" };
  return { kind: "failed", reason: body.error ?? "failed" };
}

export const runFirstResult = (initData: string, tenant: string, text: string | null, fetchFn: Fetch = fetch) =>
  run(
    `${base(tenant)}/first-result`,
    { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) },
    initData,
    fetchFn,
  );

export const runFirstResultVoice = (initData: string, tenant: string, audio: Blob, fetchFn: Fetch = fetch) =>
  run(
    `${base(tenant)}/first-result/voice`,
    { headers: { "Content-Type": audio.type || "audio/webm" }, body: audio },
    initData,
    fetchFn,
  );
