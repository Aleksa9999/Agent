/** The entrance test API: read the profile, answer a question, go back, send a recording. */

export type Option = { code: string; title: string; recommended: boolean };
export type Selected = { kind: string; code: string | null; text: string };
export type Question = {
  field: string;
  text: string;
  why: string;
  star_hint: string;
  options: Option[];
  selected: Selected | null;
};
export type CardLine = { id: string; label: string; text: string };
export type Card = {
  lines: CardLine[];
  passport: { version: number; current: boolean; published: boolean } | null;
};
export type Profile = {
  card: Card | null;
  status: "new" | "collecting" | "complete";
  answers: { field: string; kind: string; text: string }[];
  progress: { answered: number; total: number };
  question: Question | null;
  position: { index: number; size: number } | null;
  can_go_back: boolean;
  voice_available: boolean;
};

export type AnswerInput =
  | { kind: "option"; code: string }
  | { kind: "custom"; text: string }
  | { kind: "unknown" };

export type ProfileResult =
  | { kind: "ready"; profile: Profile }
  | { kind: "stale" } // the screen was old: the question had already moved on
  | { kind: "rejected" }
  | { kind: "error" };

export type VoiceOutcome = "ok" | "no_asr" | "asr_error" | "empty" | "nothing";
export type VoiceResult =
  | { kind: "heard"; profile: Profile; newFields: number }
  | { kind: "failed"; reason: VoiceOutcome | "rate_limited" | "too_big" | "unsupported" | "network" };

type Fetch = typeof fetch;
const base = (tenant: string) => `/api/miniapp/${encodeURIComponent(tenant)}/profile`;

async function request(
  url: string,
  init: RequestInit,
  initData: string,
  fetchFn: Fetch,
): Promise<ProfileResult> {
  let response: Response;
  try {
    response = await fetchFn(url, {
      ...init,
      headers: { ...(init.headers as Record<string, string>), Authorization: `tma ${initData}` },
      cache: "no-store",
    });
  } catch {
    return { kind: "error" };
  }
  if (response.status === 409) return { kind: "stale" };
  if (response.status === 422) return { kind: "rejected" };
  if (!response.ok) return { kind: "error" };
  try {
    return { kind: "ready", profile: (await response.json()) as Profile };
  } catch {
    return { kind: "error" };
  }
}

export const loadProfile = (initData: string, tenant: string, fetchFn: Fetch = fetch) =>
  request(base(tenant), { method: "GET" }, initData, fetchFn);

export const sendAnswer = (
  initData: string,
  tenant: string,
  field: string,
  answer: AnswerInput,
  fetchFn: Fetch = fetch,
) =>
  request(
    `${base(tenant)}/answer`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field, ...answer }),
    },
    initData,
    fetchFn,
  );

export const goBack = (initData: string, tenant: string, fetchFn: Fetch = fetch) =>
  request(`${base(tenant)}/back`, { method: "POST" }, initData, fetchFn);

export async function sendVoice(
  initData: string,
  tenant: string,
  audio: Blob,
  fetchFn: Fetch = fetch,
): Promise<VoiceResult> {
  let response: Response;
  try {
    response = await fetchFn(`${base(tenant)}/voice`, {
      method: "POST",
      headers: { Authorization: `tma ${initData}`, "Content-Type": audio.type || "audio/webm" },
      body: audio,
      cache: "no-store",
    });
  } catch {
    return { kind: "failed", reason: "network" };
  }
  if (response.status === 429) return { kind: "failed", reason: "rate_limited" };
  if (response.status === 413) return { kind: "failed", reason: "too_big" };
  if (response.status === 415) return { kind: "failed", reason: "unsupported" };
  if (!response.ok) return { kind: "failed", reason: "network" };
  try {
    const body = (await response.json()) as {
      outcome: VoiceOutcome;
      profile: Profile | null;
      new_fields: number;
    };
    if (body.outcome === "ok" && body.profile) {
      return { kind: "heard", profile: body.profile, newFields: body.new_fields };
    }
    return { kind: "failed", reason: body.outcome };
  } catch {
    return { kind: "failed", reason: "network" };
  }
}

export const confirmProfile = (initData: string, tenant: string, fetchFn: Fetch = fetch) =>
  requestConfirm(`${base(tenant)}/confirm`, initData, fetchFn);

async function requestConfirm(url: string, initData: string, fetchFn: Fetch): Promise<ProfileResult> {
  let response: Response;
  try {
    response = await fetchFn(url, {
      method: "POST",
      headers: { Authorization: `tma ${initData}` },
      cache: "no-store",
    });
  } catch {
    return { kind: "error" };
  }
  if (response.status === 409) return { kind: "stale" }; // not ready: reload and show the questions
  if (!response.ok) return { kind: "error" };
  try {
    const body = (await response.json()) as { profile: Profile };
    return { kind: "ready", profile: body.profile };
  } catch {
    return { kind: "error" };
  }
}

export const editLine = (initData: string, tenant: string, line: string, fetchFn: Fetch = fetch) =>
  request(
    `${base(tenant)}/edit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ line }),
    },
    initData,
    fetchFn,
  );
