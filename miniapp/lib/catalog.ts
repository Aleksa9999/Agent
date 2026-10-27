/** Loads the skill catalog with the same signed launch data as the session. */

export type Tier = { id: "economy" | "standard" | "premium"; includes: string; roles: string[] };

export type CatalogSkill = {
  slug: string;
  title: string;
  branch: string;
  version: string;
  kind: string;
  roads: string[];
  estimate: { price_source: string; tiers: Tier[] };
  unlock: { min_level: number; proof: string };
};

export type Catalog = {
  total: number;
  directions: CatalogSkill[];
  branches: { id: string; skills: CatalogSkill[] }[];
};

export type CatalogState = { kind: "loading" } | { kind: "ready"; catalog: Catalog } | { kind: "error" };

export async function loadCatalog(
  initData: string,
  tenant: string,
  fetchFn: typeof fetch = fetch,
): Promise<CatalogState> {
  try {
    const response = await fetchFn(`/api/miniapp/${encodeURIComponent(tenant)}/catalog`, {
      headers: { Authorization: `tma ${initData}` },
      cache: "no-store",
    });
    if (!response.ok) return { kind: "error" };
    const catalog = (await response.json()) as Catalog;
    if (!Array.isArray(catalog.directions) || !Array.isArray(catalog.branches)) return { kind: "error" };
    return { kind: "ready", catalog };
  } catch {
    return { kind: "error" };
  }
}
