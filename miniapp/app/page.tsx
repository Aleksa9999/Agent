"use client";

import { useCallback, useEffect, useState } from "react";

import { type Locale, type MessageKey, pickLocale, t } from "@/lib/messages";
import { CatalogScreen } from "./catalog";
import { HomeScreen } from "./home";
import { ProfileScreen } from "./profile";
import { type SessionState, loadSession, tenantFromSearch } from "@/lib/session";
import { waitForInitData } from "@/lib/telegram";

type TelegramWebApp = {
  initData?: string;
  ready: () => void;
  expand: () => void;
  initDataUnsafe?: { user?: { language_code?: string } };
  close?: () => void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export default function Home() {
  const [state, setState] = useState<SessionState>({ kind: "loading" });
  const [locale, setLocale] = useState<Locale>("ru");
  const [homeKey, setHomeKey] = useState(0);
  const [initData, setInitData] = useState("");

  const open = useCallback(async () => {
    setState({ kind: "loading" });
    const app = window.Telegram?.WebApp;
    app?.ready();
    app?.expand();
    setLocale(pickLocale(app?.initDataUnsafe?.user?.language_code));
    const data = await waitForInitData({
      app: window.Telegram?.WebApp,
      hash: window.location.hash,
      sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    });
    setInitData(data ?? "");
    const next = await loadSession(data, tenantFromSearch(window.location.search));
    if (next.kind === "ready") setLocale(pickLocale(next.locale));
    setState(next);
  }, []);

  useEffect(() => {
    void open();
  }, [open]);

  const screen = (title: MessageKey, body: MessageKey, retry = false) => (
    <Message title={t(locale, title)} body={t(locale, body)} retry={retry ? { label: t(locale, "retry"), run: open } : undefined} />
  );

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col gap-4 px-5 py-8">
      {state.kind === "loading" && <p className="text-[var(--tg-hint)]">{t(locale, "loading")}</p>}
      {state.kind === "outside_telegram" && screen("outside_title", "outside_body", true)}
      {state.kind === "expired" && screen("expired_title", "expired_body")}
      {state.kind === "denied" && screen("denied_title", "denied_body")}
      {state.kind === "error" && screen("error_title", "error_body", true)}
      {state.kind === "ready" && (
        <>
          <Message
            title={t(locale, "hello", { name: state.user.first_name })}
            body={t(locale, "ready_body")}
          />
          <HomeScreen
            locale={locale}
            initData={initData}
            tenant={tenantFromSearch(window.location.search)}
            refreshKey={homeKey}
          />
          <ProfileScreen
            onConfirmed={() => setHomeKey((key) => key + 1)}
            locale={locale}
            initData={initData}
            tenant={tenantFromSearch(window.location.search)}
          />
          <CatalogScreen
            locale={locale}
            initData={initData}
            tenant={tenantFromSearch(window.location.search)}
          />
        </>
      )}
    </main>
  );
}

function Message({ title, body, retry }: { title: string; body: string; retry?: { label: string; run: () => void } }) {
  return (
    <>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-[var(--tg-hint)]">{body}</p>
      {retry && (
        <button
          type="button"
          onClick={retry.run}
          className="self-start rounded-xl bg-[var(--tg-button)] px-5 py-3 font-medium text-[var(--tg-button-text)] focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {retry.label}
        </button>
      )}
    </>
  );
}
