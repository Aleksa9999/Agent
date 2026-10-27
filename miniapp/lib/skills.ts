/** Opens a skill in the chat with the bot. */

export type StartResult = { kind: "started" } | { kind: "failed"; reason: string };

export async function startSkill(
  initData: string,
  tenant: string,
  slug: string,
  fetchFn: typeof fetch = fetch,
): Promise<StartResult> {
  let response: Response;
  try {
    response = await fetchFn(
      `/api/miniapp/${encodeURIComponent(tenant)}/skills/${encodeURIComponent(slug)}/start`,
      { method: "POST", headers: { Authorization: `tma ${initData}` }, cache: "no-store" },
    );
  } catch {
    return { kind: "failed", reason: "network" };
  }
  if (response.ok) return { kind: "started" };
  const body = (await response.json().catch(() => ({}))) as { error?: string | null };
  return { kind: "failed", reason: body.error ?? "unavailable" };
}
