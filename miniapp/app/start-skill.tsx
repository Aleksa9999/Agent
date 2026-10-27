"use client";

import { useState } from "react";

import { type Locale, type MessageKey, t } from "@/lib/messages";
import { startSkill } from "@/lib/skills";

type Props = { locale: Locale; initData: string; tenant: string; slug: string };

export function StartSkillButton({ locale, initData, tenant, slug }: Props) {
  const [state, setState] = useState<"idle" | "busy" | "started">("idle");
  const [error, setError] = useState<MessageKey | null>(null);

  const start = async () => {
    setState("busy");
    setError(null);
    const result = await startSkill(initData, tenant, slug);
    if (result.kind === "started") {
      setState("started");
      return;
    }
    setState("idle");
    setError(`skill_error_${result.reason}` as MessageKey);
  };

  if (state === "started") {
    return (
      <div role="status" className="flex flex-col gap-2 text-sm">
        <p>{t(locale, "skill_started")}</p>
        <button
          type="button"
          onClick={() => window.Telegram?.WebApp?.close?.()}
          className="self-start rounded-xl border border-[var(--tg-hint)]/40 px-4 py-2 focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t(locale, "open_chat")}
        </button>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        disabled={state === "busy"}
        onClick={() => void start()}
        className="self-start rounded-xl bg-[var(--tg-button)] px-4 py-2 text-sm font-medium text-[var(--tg-button-text)] focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50"
      >
        {t(locale, "skill_start")}
      </button>
      {error && (
        <p role="alert" className="text-xs">
          {t(locale, error)}
        </p>
      )}
    </div>
  );
}
