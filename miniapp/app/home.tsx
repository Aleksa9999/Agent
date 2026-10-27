"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type FirstResult, type Home, loadHome, runFirstResult, runFirstResultVoice } from "@/lib/home";
import { type Locale, type MessageKey, t, tByName } from "@/lib/messages";
import { parseBlocks } from "@/lib/markdown";
import { type Recording, browserMicSupport, startRecording } from "@/lib/recorder";
import { StartSkillButton } from "./start-skill";

type Props = { locale: Locale; initData: string; tenant: string; refreshKey: number };

export function HomeScreen({ locale, initData, tenant, refreshKey }: Props) {
  const [home, setHome] = useState<Home | null>(null);

  const load = useCallback(async () => {
    const state = await loadHome(initData, tenant);
    if (state.kind === "ready") setHome(state.home);
  }, [initData, tenant]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  if (!home || !home.track) return null;
  return (
    <section className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h2 className="text-xl font-semibold">{t(locale, "home_title")}</h2>
        <p className="text-sm text-[var(--tg-hint)]">
          {t(locale, "home_level", { level: String(home.level) })} ·{" "}
          {t(locale, "home_counter", { count: String(home.counter) })}
        </p>
        <p className="text-sm text-[var(--tg-hint)]">
          {t(locale, "home_track", { track: tByName(locale, `track_${home.track}`) })}
        </p>
      </header>

      <FirstResultBlock locale={locale} home={home} initData={initData} tenant={tenant} onHome={setHome} />

      <div className="flex flex-col gap-2">
        <h3 className="font-medium">{t(locale, "home_skills")}</h3>
        <ul className="flex flex-col gap-2">
          {home.skills.map((skill) => (
            <li key={skill.slug} className="rounded-xl border border-[var(--tg-hint)]/30 px-4 py-3">
              <p className="font-medium">{skill.title}</p>
              <p className="text-xs text-[var(--tg-hint)]">
                {tByName(locale, `branch_${skill.branch}`)} ·{" "}
                {t(locale, skill.status === "verified" ? "home_status_verified" : "home_status_unverified")}
                {skill.extra ? ` · ${t(locale, "home_extra")}` : ""}
              </p>
              <div className="pt-2">
                <StartSkillButton locale={locale} initData={initData} tenant={tenant} slug={skill.slug} />
              </div>
            </li>
          ))}
        </ul>
        <p className="text-xs text-[var(--tg-hint)]">{t(locale, "home_note")}</p>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="font-medium">{t(locale, "home_tree")}</h3>
        <ul className="grid grid-cols-2 gap-2">
          {home.branches.map((branch) => (
            <li key={branch.id} className="rounded-xl border border-[var(--tg-hint)]/30 px-3 py-2 text-sm">
              <p className="font-medium">{tByName(locale, `branch_${branch.id}`)}</p>
              <p className="text-xs text-[var(--tg-hint)]">
                {t(locale, "home_branch_count", {
                  assigned: String(branch.assigned),
                  verified: String(branch.verified),
                })}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function FirstResultBlock(props: {
  locale: Locale;
  home: Home;
  initData: string;
  tenant: string;
  onHome: (home: Home) => void;
}) {
  const { locale, home } = props;
  const needsText = home.first_result_input === "text";
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "running" | "recording">("idle");
  const [error, setError] = useState<MessageKey | null>(null);
  const recording = useRef<Recording | null>(null);
  const canRecord = needsText && home.voice_available && browserMicSupport() === "ok";

  useEffect(() => () => recording.current?.cancel(), []);

  const apply = (result: Awaited<ReturnType<typeof runFirstResult>>) => {
    if (result.kind === "done") {
      props.onHome(result.home);
      setError(null);
    } else {
      setError(`fr_error_${result.reason}` as MessageKey);
    }
    setState("idle");
  };

  const generate = async () => {
    setState("running");
    apply(await runFirstResult(props.initData, props.tenant, needsText ? text : null));
  };

  const toggleRecording = async () => {
    if (state === "recording" && recording.current) {
      const active = recording.current;
      recording.current = null;
      setState("running");
      apply(await runFirstResultVoice(props.initData, props.tenant, await active.stop()));
      return;
    }
    try {
      recording.current = await startRecording(() => void toggleRecording());
      setState("recording");
    } catch {
      setError("fr_error_no_asr");
    }
  };

  const intro = needsText ? "fr_routines_intro" : home.track === "study" || home.track === "ai_services" || home.track === "teach" ? "fr_plan_intro" : "fr_idea_intro";

  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-medium">{t(locale, "fr_title")}</h3>
      {home.first_result && <Result locale={locale} result={home.first_result} />}
      {(!home.first_result || needsText) && (
        <>
          <p className="text-sm text-[var(--tg-hint)]">{t(locale, intro as MessageKey)}</p>
          {needsText && (
            <textarea
              value={text}
              maxLength={4000}
              onChange={(event) => setText(event.target.value)}
              placeholder={t(locale, "fr_text_placeholder")}
              className="min-h-28 rounded-xl border border-[var(--tg-hint)]/40 bg-transparent p-3"
            />
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={state !== "idle" || (needsText && !text.trim())}
              onClick={() => void generate()}
              className="rounded-xl bg-[var(--tg-button)] px-5 py-3 font-medium text-[var(--tg-button-text)] focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50"
            >
              {t(locale, home.first_result ? "fr_again" : "fr_run")}
            </button>
            {canRecord && state !== "running" && (
              <button
                type="button"
                onClick={() => void toggleRecording()}
                className="rounded-xl border border-[var(--tg-hint)]/40 px-5 py-3 focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                {t(locale, state === "recording" ? "fr_rec_stop" : "fr_rec_start")}
              </button>
            )}
          </div>
        </>
      )}
      {state === "running" && (
        <p role="status" className="text-sm text-[var(--tg-hint)]">
          {t(locale, "fr_running")}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm">
          {t(locale, error)}
        </p>
      )}
    </div>
  );
}

function Result({ locale, result }: { locale: Locale; result: FirstResult }) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-[var(--tg-hint)]/30 p-4 text-sm">
      {parseBlocks(result.text).map((block, index) =>
        block.kind === "table" ? (
          <div key={index} className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr>
                  {block.header.map((cell, i) => (
                    <th key={i} className="border-b border-[var(--tg-hint)]/40 px-2 py-1 font-medium">
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c} className="border-b border-[var(--tg-hint)]/20 px-2 py-1 align-top">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p key={index} className="whitespace-pre-line">
            {block.text}
          </p>
        ),
      )}
      {result.code && (
        <details>
          <summary className="cursor-pointer font-medium">{t(locale, "fr_code")}</summary>
          <pre className="overflow-x-auto pt-2 text-xs whitespace-pre-wrap">{result.code}</pre>
        </details>
      )}
    </div>
  );
}
