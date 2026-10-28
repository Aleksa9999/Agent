"use client";

import { useEffect, useState } from "react";

import { type Home, loadHome } from "@/lib/home";
import { tap } from "@/lib/haptics";
import { type Locale, t } from "@/lib/messages";

type Props = {
  locale: Locale;
  initData: string;
  tenant: string;
  onLocale: (locale: Locale) => void;
  onOpenProfile: () => void;
};

export function SettingsScreen({ locale, initData, tenant, onLocale, onOpenProfile }: Props) {
  const [home, setHome] = useState<Home | null>(null);

  useEffect(() => {
    void loadHome(initData, tenant).then((state) => {
      if (state.kind === "ready") setHome(state.home);
    });
  }, [initData, tenant]);

  return (
    <section className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">{t(locale, "set_title")}</h2>

      <Group title={t(locale, "set_you")}>
        <Row label={t(locale, "set_level")} value={home ? String(home.level) : "…"} />
        <Row label={t(locale, "set_counter")} value={home ? String(home.counter) : "…"} />
        <button type="button" onClick={onOpenProfile} className="flex w-full items-center justify-between px-4 py-3 text-left">
          <span>{t(locale, "tab_profile")}</span>
          <span aria-hidden="true" className="text-[var(--tg-hint)]">›</span>
        </button>
      </Group>

      <Group title={t(locale, "set_app")}>
        <div className="flex items-center justify-between px-4 py-3">
          <span>{t(locale, "set_language")}</span>
          <div role="group" aria-label={t(locale, "set_language")} className="flex gap-1 rounded-full bg-[var(--tg-hint)]/15 p-1">
            {(["ru", "en"] as const).map((code) => (
              <button
                key={code}
                type="button"
                aria-pressed={locale === code}
                onClick={() => {
                  tap();
                  onLocale(code);
                }}
                className={`rounded-full px-3 py-1 text-sm ${locale === code ? "bg-[var(--tg-button)] text-[var(--tg-button-text)]" : "text-[var(--tg-hint)]"}`}
              >
                {t(locale, code === "ru" ? "set_lang_ru" : "set_lang_en")}
              </button>
            ))}
          </div>
        </div>
      </Group>

      <Group title={t(locale, "set_about")}>
        <p className="px-4 py-3 text-sm text-[var(--tg-hint)]">{t(locale, "set_about_text")}</p>
      </Group>

      <Group title={t(locale, "set_data")}>
        <p className="px-4 py-3 text-sm text-[var(--tg-hint)]">{t(locale, "set_data_text")}</p>
      </Group>
    </section>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="px-1 text-sm font-medium text-[var(--tg-hint)]">{title}</h3>
      <div className="flex flex-col divide-y divide-[var(--tg-hint)]/20 overflow-hidden rounded-3xl bg-[var(--tg-hint)]/10">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-3">
      <span>{label}</span>
      <span className="text-[var(--tg-hint)]">{value}</span>
    </div>
  );
}
