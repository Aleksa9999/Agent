"use client";

import type { ReactNode } from "react";

import { tap } from "@/lib/haptics";
import { type Locale, type MessageKey, t } from "@/lib/messages";

export type Tab = "home" | "skills" | "profile" | "settings";

const icons: Record<Tab, ReactNode> = {
  home: (
    <path d="M4 11.5 12 4l8 7.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z" />
  ),
  skills: (
    <>
      <path d="M12 3l2.4 5.3 5.6.6-4.2 3.8 1.2 5.6L12 15.4 7 18.3l1.2-5.6L4 8.9l5.6-.6z" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8" />
    </>
  ),
  profile: (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20c.8-3.6 3.5-5.5 7-5.5s6.2 1.9 7 5.5" />
    </>
  ),
};

const order: { id: Tab; label: MessageKey }[] = [
  { id: "home", label: "tab_home" },
  { id: "skills", label: "tab_skills" },
  { id: "profile", label: "tab_profile" },
  { id: "settings", label: "tab_settings" },
];

export function TabBar({ locale, active, onChange }: { locale: Locale; active: Tab; onChange: (tab: Tab) => void }) {
  return (
    <nav
      aria-label={t(locale, "tabs_label")}
      className="fixed inset-x-0 bottom-0 z-10 mx-auto max-w-md px-4 pb-[max(env(safe-area-inset-bottom),12px)]"
    >
      <ul className="flex gap-1 rounded-full border border-[var(--tg-hint)]/25 bg-[var(--tg-bg)]/90 p-1.5 shadow-lg backdrop-blur">
        {order.map((tab) => {
          const on = tab.id === active;
          return (
            <li key={tab.id} className="flex-1">
              <button
                type="button"
                aria-current={on ? "page" : undefined}
                onClick={() => {
                  tap();
                  onChange(tab.id);
                }}
                className={`flex w-full flex-col items-center gap-0.5 rounded-full px-3 py-2 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 ${
                  on ? "bg-[var(--tg-button)]/15 text-[var(--tg-button)]" : "text-[var(--tg-hint)]"
                }`}
              >
                <svg
                  viewBox="0 0 24 24"
                  className="h-6 w-6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  {icons[tab.id]}
                </svg>
                {t(locale, tab.label)}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
