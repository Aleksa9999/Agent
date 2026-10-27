/** Opens a Mini App session: sends Telegram's signed launch data, maps the answer to a screen state. */

export type SessionUser = { id: number; first_name: string; role: "owner" | "member" };

export type SessionState =
  | { kind: "loading" }
  | { kind: "outside_telegram" }
  | { kind: "ready"; user: SessionUser; brand: string; locale: string }
  | { kind: "expired" }
  | { kind: "denied" }
  | { kind: "error" };

type Fetch = typeof fetch;

export async function loadSession(
  initData: string | undefined,
  tenant: string,
  fetchFn: Fetch = fetch,
): Promise<SessionState> {
  if (!initData) return { kind: "outside_telegram" };
  let response: Response;
  try {
    response = await fetchFn(`/api/miniapp/${encodeURIComponent(tenant)}/session`, {
      method: "POST",
      headers: { Authorization: `tma ${initData}` },
      cache: "no-store",
    });
  } catch {
    return { kind: "error" };
  }
  if (response.status === 401) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    return body.error === "expired" ? { kind: "expired" } : { kind: "denied" };
  }
  if (!response.ok) return { kind: "error" };
  try {
    const body = (await response.json()) as { user: SessionUser; brand: string; locale: string };
    return { kind: "ready", user: body.user, brand: body.brand, locale: body.locale };
  } catch {
    return { kind: "error" };
  }
}

export function tenantFromSearch(search: string): string {
  const value = new URLSearchParams(search).get("tenant") ?? "default";
  return /^[a-z0-9][a-z0-9-]{0,62}$/.test(value) ? value : "default";
}
