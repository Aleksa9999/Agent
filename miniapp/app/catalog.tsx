"use client";

import { useEffect, useState } from "react";

import { type Catalog, type CatalogSkill, loadCatalog } from "@/lib/catalog";
import { type Locale, t, tByName } from "@/lib/messages";

type Props = { locale: Locale; initData: string; tenant: string };
type View = { kind: "loading" } | { kind: "error" } | { kind: "ready"; catalog: Catalog };

export function CatalogScreen({ locale, initData, tenant }: Props) {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [open, setOpen] = useState<CatalogSkill | null>(null);

  const load = async () => {
    setView({ kind: "loading" });
    setView(await loadCatalog(initData, tenant));
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initData, tenant]);

  if (view.kind === "loading") return <p className="text-[var(--tg-hint)]">{t(locale, "catalog_loading")}</p>;
  if (view.kind === "error") {
    return (
      <>
        <p className="text-[var(--tg-hint)]">{t(locale, "catalog_error")}</p>
        <button type="button" onClick={() => void load()} className={primary}>
          {t(locale, "retry")}
        </button>
      </>
    );
  }
  if (open) return <SkillCard locale={locale} skill={open} onBack={() => setOpen(null)} />;

  return (
    <section className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">{t(locale, "catalog_title")}</h2>
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-medium text-[var(--tg-hint)]">{t(locale, "directions_title")}</h3>
        <ul className="grid grid-cols-2 gap-3">
          {view.catalog.directions.map((skill) => (
            <li key={skill.slug}>
              <button type="button" onClick={() => setOpen(skill)} className={card}>
                <span className="font-medium">{skill.title}</span>
                <span className="text-xs text-[var(--tg-hint)]">{tByName(locale, `branch_${skill.branch}`)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-[var(--tg-hint)]">{t(locale, "tree_title")}</h3>
        {view.catalog.branches.map((branch) => (
          <details key={branch.id} className="rounded-xl border border-[var(--tg-hint)]/30 px-4 py-3">
            <summary className="cursor-pointer font-medium">
              {tByName(locale, `branch_${branch.id}`)} · {branch.skills.length}
            </summary>
            {branch.skills.length === 0 ? (
              <p className="pt-2 text-sm text-[var(--tg-hint)]">{t(locale, "empty_branch")}</p>
            ) : (
              <ul className="flex flex-col gap-1 pt-2">
                {branch.skills.map((skill) => (
                  <li key={skill.slug}>
                    <button type="button" onClick={() => setOpen(skill)} className="w-full py-2 text-left">
                      {skill.title}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </details>
        ))}
      </div>
    </section>
  );
}

function SkillCard({ locale, skill, onBack }: { locale: Locale; skill: CatalogSkill; onBack: () => void }) {
  return (
    <article className="flex flex-col gap-5">
      <button type="button" onClick={onBack} className="self-start text-[var(--tg-hint)]">
        ← {t(locale, "back")}
      </button>
      <header className="flex flex-col gap-1">
        <h2 className="text-xl font-semibold">{skill.title}</h2>
        <p className="text-sm text-[var(--tg-hint)]">
          {tByName(locale, `branch_${skill.branch}`)} · {t(locale, "skill_version", { version: skill.version })}
        </p>
      </header>
      <section className="flex flex-col gap-2">
        <h3 className="font-medium">{t(locale, "road_title")}</h3>
        <ul className="flex flex-col gap-1 text-sm">
          {skill.roads.map((road) => (
            <li key={road}>{tByName(locale, `road_${road}`)}</li>
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-2">
        <h3 className="font-medium">{t(locale, "estimate_title")}</h3>
        <ul className="flex flex-col gap-2">
          {skill.estimate.tiers.map((tier) => (
            <li key={tier.id} className="rounded-xl border border-[var(--tg-hint)]/30 px-4 py-3 text-sm">
              <p className="font-medium">{tByName(locale, `tier_${tier.id}`)}</p>
              {tier.includes && <p>{tier.includes}</p>}
              <p className="text-[var(--tg-hint)]">{tier.roles.join(", ")}</p>
            </li>
          ))}
        </ul>
        <p className="text-xs text-[var(--tg-hint)]">{t(locale, "price_note")}</p>
      </section>
      <section className="flex flex-col gap-2">
        <h3 className="font-medium">{t(locale, "unlock_title")}</h3>
        <p className="text-sm">{t(locale, "unlock_level", { level: String(skill.unlock.min_level) })}</p>
        <p className="text-sm text-[var(--tg-hint)]">{t(locale, "unlock_proof")}</p>
        <p className="text-sm whitespace-pre-line">{skill.unlock.proof}</p>
      </section>
    </article>
  );
}

const primary =
  "self-start rounded-xl bg-[var(--tg-button)] px-5 py-3 font-medium text-[var(--tg-button-text)] focus-visible:outline-2 focus-visible:outline-offset-2";
const card =
  "flex h-full w-full flex-col gap-1 rounded-xl border border-[var(--tg-hint)]/30 px-3 py-3 text-left focus-visible:outline-2 focus-visible:outline-offset-2";
