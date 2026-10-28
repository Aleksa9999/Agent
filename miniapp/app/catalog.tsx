"use client";

import { useEffect, useState } from "react";

import { type Catalog, type CatalogSkill, loadCatalog } from "@/lib/catalog";
import { tap } from "@/lib/haptics";
import { type Locale, t, tByName } from "@/lib/messages";
import { StartSkillButton } from "./start-skill";

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
  if (open) return <SkillCard locale={locale} skill={open} initData={initData} tenant={tenant} onBack={() => setOpen(null)} />;

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
      {view.catalog.branches
        .filter((branch) => branch.skills.length > 0)
        .map((branch) => (
          <div key={branch.id} className="flex flex-col gap-2">
            <h3 className="px-1 text-lg font-semibold">{tByName(locale, `branch_${branch.id}`)}</h3>
            <ul className="flex flex-col divide-y divide-[var(--tg-hint)]/20 overflow-hidden rounded-3xl bg-[var(--tg-hint)]/10">
              {branch.skills.map((skill) => (
                <li key={skill.slug}>
                  <button
                    type="button"
                    onClick={() => {
                      tap();
                      setOpen(skill);
                    }}
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                  >
                    <span className="flex flex-col">
                      <span className="font-medium">{skill.title}</span>
                      <span className="text-xs text-[var(--tg-hint)]">{tByName(locale, `kind_${skill.kind}`)}</span>
                    </span>
                    <span aria-hidden="true" className="text-[var(--tg-hint)]">›</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
    </section>
  );
}

function SkillCard({
  locale,
  skill,
  initData,
  tenant,
  onBack,
}: {
  locale: Locale;
  skill: CatalogSkill;
  initData: string;
  tenant: string;
  onBack: () => void;
}) {
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
      <StartSkillButton locale={locale} initData={initData} tenant={tenant} slug={skill.slug} />
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
  "flex h-full w-full flex-col gap-1 rounded-3xl bg-[var(--tg-hint)]/10 px-4 py-4 text-left focus-visible:outline-2 focus-visible:outline-offset-2";
