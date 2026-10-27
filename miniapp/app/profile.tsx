"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AnswerInput,
  type Profile,
  type ProfileResult,
  type Question,
  confirmProfile,
  editLine,
  goBack,
  loadProfile,
  sendAnswer,
  sendVoice,
} from "@/lib/profile";
import { type Locale, type MessageKey, t, tByName } from "@/lib/messages";
import { type RecordError, type Recording, browserMicSupport, recordError, startRecording } from "@/lib/recorder";

type Props = { locale: Locale; initData: string; tenant: string };
type Screen = "start" | "record" | "questions";
type Rec = "idle" | "recording" | "sending";

export function ProfileScreen({ locale, initData, tenant }: Props) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [failed, setFailed] = useState(false);
  const [screen, setScreen] = useState<Screen>("start");
  const [note, setNote] = useState<string | null>(null);

  const apply = useCallback(
    (result: ProfileResult, keepScreen = false) => {
      if (result.kind === "ready") {
        setProfile(result.profile);
        setFailed(false);
        if (!keepScreen) setScreen(result.profile.status === "collecting" ? "questions" : "start");
        return true;
      }
      return false;
    },
    [],
  );

  const load = useCallback(async () => {
    const result = await loadProfile(initData, tenant);
    if (!apply(result)) setFailed(true);
  }, [initData, tenant, apply]);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    return (
      <section className="flex flex-col gap-3">
        <p className="text-[var(--tg-hint)]">{t(locale, "catalog_error")}</p>
        <button type="button" onClick={() => void load()} className={primary}>
          {t(locale, "retry")}
        </button>
      </section>
    );
  }
  if (!profile) return <p className="text-[var(--tg-hint)]">{t(locale, "loading")}</p>;
  if (profile.card) {
    return (
      <Card
        locale={locale}
        profile={profile}
        initData={initData}
        tenant={tenant}
        onChange={(result) => {
          if (result.kind === "ready") {
            setProfile(result.profile);
            setScreen("questions");
            return true;
          }
          if (result.kind === "stale") void load();
          return false;
        }}
      />
    );
  }

  if (screen === "record") {
    return (
      <Recorder
        locale={locale}
        initData={initData}
        tenant={tenant}
        onHeard={(next, count) => {
          setProfile(next);
          setNote(t(locale, "q_heard", { count: String(count) }));
          setScreen(next.status === "complete" ? "start" : "questions");
        }}
        onForm={() => setScreen("questions")}
        onRefresh={load}
        onCancel={() => setScreen("start")}
      />
    );
  }
  if ((screen === "questions" || profile.status === "complete") && profile.question) {
    return (
      <Questions
        locale={locale}
        initData={initData}
        tenant={tenant}
        profile={profile}
        note={note ?? (profile.answers.length > 0 ? t(locale, "profile_continue") : null)}
        onChange={(result) => {
          if (result.kind === "stale") {
            setNote(t(locale, "q_stale"));
            void load();
            return true;
          }
          return apply(result, true);
        }}
      />
    );
  }
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold">{t(locale, "profile_title")}</h2>
      <p className="text-[var(--tg-hint)]">{t(locale, "profile_intro")}</p>
      {profile.voice_available ? (
        <button type="button" onClick={() => setScreen("record")} className={primary}>
          🎙 {t(locale, "profile_record")}
        </button>
      ) : (
        <p className="text-sm text-[var(--tg-hint)]">{t(locale, "profile_voice_off")}</p>
      )}
      <button type="button" onClick={() => setScreen("questions")} className={secondary}>
        {t(locale, "profile_form")}
      </button>
    </section>
  );
}

function Recorder(props: {
  locale: Locale;
  initData: string;
  tenant: string;
  onHeard: (profile: Profile, count: number) => void;
  onForm: () => void;
  onRefresh: () => Promise<void>;
  onCancel: () => void;
}) {
  const { locale } = props;
  const [state, setState] = useState<Rec>("idle");
  const [problem, setProblem] = useState<MessageKey | null>(null);
  const [micOff, setMicOff] = useState<"mic_unavailable_body" | "mic_denied_body" | "mic_none_body" | null>(
    browserMicSupport() === "ok" ? null : "mic_unavailable_body",
  );
  const recording = useRef<Recording | null>(null);

  useEffect(() => () => recording.current?.cancel(), []);

  const finish = useCallback(async () => {
    const active = recording.current;
    if (!active) return;
    recording.current = null;
    setState("sending");
    const result = await sendVoice(props.initData, props.tenant, await active.stop());
    if (result.kind === "heard") {
      props.onHeard(result.profile, result.newFields);
      return;
    }
    setState("idle");
    setProblem(`voice_err_${result.reason}` as MessageKey);
  }, [props]);

  const start = async () => {
    setProblem(null);
    try {
      recording.current = await startRecording(() => void finish());
      setState("recording");
    } catch (error) {
      const reason: RecordError = recordError(error);
      setMicOff(reason === "denied" ? "mic_denied_body" : reason === "no_device" ? "mic_none_body" : "mic_unavailable_body");
    }
  };

  if (micOff) {
    return (
      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold">{t(locale, "mic_unavailable_title")}</h2>
        <p className="text-[var(--tg-hint)]">{t(locale, micOff)}</p>
        <button type="button" onClick={() => window.Telegram?.WebApp?.close?.()} className={primary}>
          {t(locale, "open_chat")}
        </button>
        <button type="button" onClick={() => void props.onRefresh()} className={secondary}>
          {t(locale, "check_again")}
        </button>
        <button type="button" onClick={props.onForm} className={secondary}>
          {t(locale, "profile_form")}
        </button>
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold">{t(locale, "profile_title")}</h2>
      <p className="text-[var(--tg-hint)]">{t(locale, "rec_hint")}</p>
      {state === "idle" && (
        <button type="button" onClick={() => void start()} className={primary}>
          🎙 {t(locale, "rec_start")}
        </button>
      )}
      {state === "recording" && (
        <>
          <p role="status" className="font-medium">
            ● {t(locale, "rec_recording")}
          </p>
          <button type="button" onClick={() => void finish()} className={primary}>
            {t(locale, "rec_stop")}
          </button>
        </>
      )}
      {state === "sending" && (
        <p role="status" className="text-[var(--tg-hint)]">
          {t(locale, "rec_sending")}
        </p>
      )}
      {problem && (
        <p role="alert" className="text-sm">
          {t(locale, problem)}
        </p>
      )}
      {state !== "sending" && (
        <button type="button" onClick={props.onCancel} className={secondary}>
          {t(locale, "q_back")}
        </button>
      )}
    </section>
  );
}

function Questions(props: {
  locale: Locale;
  initData: string;
  tenant: string;
  profile: Profile;
  note: string | null;
  onChange: (result: ProfileResult) => boolean;
}) {
  const { locale, profile } = props;
  const question = profile.question as Question;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [custom, setCustom] = useState(false);
  const [compare, setCompare] = useState(false);
  const [text, setText] = useState("");

  useEffect(() => {
    setCustom(false);
    setCompare(false);
    setText("");
  }, [question.field]);

  const run = async (job: Promise<ProfileResult>) => {
    setBusy(true);
    setError(false);
    const ok = props.onChange(await job);
    setBusy(false);
    if (!ok) setError(true);
  };
  const answer = (input: AnswerInput) =>
    run(sendAnswer(props.initData, props.tenant, question.field, input));

  return (
    <section className="flex flex-col gap-4" aria-busy={busy}>
      {props.note && <p className="text-sm text-[var(--tg-hint)]">{props.note}</p>}
      <p className="text-sm text-[var(--tg-hint)]">
        {profile.position &&
          t(locale, "q_counter", { index: String(profile.position.index), size: String(profile.position.size) })}
        {" · "}
        {t(locale, "q_progress", {
          done: String(profile.progress.answered),
          total: String(profile.progress.total),
        })}
      </p>
      <h2 className="text-xl font-semibold">{question.text}</h2>
      <ul className="flex flex-col gap-2">
        {question.options.map((option) => {
          const chosen = question.selected?.code === option.code;
          return (
            <li key={option.code}>
              <button
                type="button"
                disabled={busy}
                aria-pressed={chosen}
                onClick={() => void answer({ kind: "option", code: option.code })}
                className={`${choice} ${chosen ? "border-[var(--tg-button)] border-2" : ""}`}
              >
                {option.recommended ? "⭐ " : ""}
                {option.title}
              </button>
            </li>
          );
        })}
      </ul>
      {question.selected && question.selected.kind !== "option" && (
        <p className="text-sm text-[var(--tg-hint)]">
          {t(locale, "q_chosen", {
            text: question.selected.kind === "unknown" ? t(locale, "answer_unknown") : question.selected.text,
          })}
        </p>
      )}
      <div className="grid grid-cols-2 gap-2">
        <button type="button" disabled={busy} onClick={() => setCustom(!custom)} className={control}>
          {t(locale, "q_custom")}
        </button>
        <button type="button" disabled={busy} onClick={() => void answer({ kind: "unknown" })} className={control}>
          {t(locale, "q_unknown")}
        </button>
        <button
          type="button"
          disabled={busy || !profile.can_go_back}
          onClick={() => void run(goBack(props.initData, props.tenant))}
          className={control}
        >
          {t(locale, "q_back")}
        </button>
        <button type="button" disabled={busy} onClick={() => setCompare(!compare)} className={control}>
          {t(locale, "q_compare")}
        </button>
      </div>
      {custom && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (text.trim()) void answer({ kind: "custom", text: text.trim() });
          }}
        >
          <textarea
            value={text}
            maxLength={300}
            onChange={(event) => setText(event.target.value)}
            placeholder={t(locale, "q_custom_placeholder")}
            className="min-h-24 rounded-xl border border-[var(--tg-hint)]/40 bg-transparent p-3"
          />
          <button type="submit" disabled={busy || !text.trim()} className={primary}>
            {t(locale, "q_send")}
          </button>
        </form>
      )}
      {compare && (
        <div className="rounded-xl border border-[var(--tg-hint)]/30 p-3 text-sm">
          <p className="font-medium">{t(locale, "q_why")}</p>
          <p className="text-[var(--tg-hint)]">{question.why}</p>
          <p className="pt-2 text-[var(--tg-hint)]">{question.star_hint}</p>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm">
          {t(locale, "q_error")}
        </p>
      )}
    </section>
  );
}

function Card(props: {
  locale: Locale;
  profile: Profile;
  initData: string;
  tenant: string;
  onChange: (result: ProfileResult) => boolean;
}) {
  const { locale, profile } = props;
  const card = profile.card as NonNullable<Profile["card"]>;
  const [busy, setBusy] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [failed, setFailed] = useState(false);
  const passport = card.passport;

  const run = async (job: Promise<ProfileResult>) => {
    setBusy(true);
    setFailed(false);
    const ok = props.onChange(await job);
    setBusy(false);
    if (!ok) setFailed(true);
  };

  return (
    <section className="flex flex-col gap-4" aria-busy={busy}>
      <h2 className="text-xl font-semibold">{t(locale, "card_title")}</h2>
      <p className="text-[var(--tg-hint)]">{t(locale, "card_intro")}</p>
      <dl className="flex flex-col gap-2 text-sm">
        {card.lines.map((line) => (
          <div key={line.id} className="rounded-xl border border-[var(--tg-hint)]/30 px-4 py-3">
            <dt className="text-[var(--tg-hint)]">{line.label}</dt>
            <dd>{line.text}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-[var(--tg-hint)]">{t(locale, "card_private_note")}</p>
      {passport && (
        <div role="status" className="rounded-xl border border-[var(--tg-button)] px-4 py-3 text-sm">
          <p className="font-medium">
            {t(locale, passport.current ? "passport_done" : "passport_old", { version: String(passport.version) })}
          </p>
          <p className="text-[var(--tg-hint)]">
            {t(locale, passport.published ? "passport_published" : "passport_not_published")}
          </p>
        </div>
      )}
      {!fixing ? (
        <div className="flex gap-2">
          {!passport?.current && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(confirmProfile(props.initData, props.tenant))}
              className={primary}
            >
              {t(locale, "card_ok")}
            </button>
          )}
          <button type="button" disabled={busy} onClick={() => setFixing(true)} className={secondary}>
            {t(locale, "card_fix")}
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="font-medium">{t(locale, "card_fix_pick")}</p>
          {card.lines.map((line) => (
            <button
              key={line.id}
              type="button"
              disabled={busy}
              onClick={() => void run(editLine(props.initData, props.tenant, line.id))}
              className={choice}
            >
              {line.label}
            </button>
          ))}
          <button type="button" onClick={() => setFixing(false)} className={secondary}>
            {t(locale, "card_cancel")}
          </button>
        </div>
      )}
      {failed && (
        <p role="alert" className="text-sm">
          {t(locale, "card_error")}
        </p>
      )}
    </section>
  );
}

const primary =
  "self-start rounded-xl bg-[var(--tg-button)] px-5 py-3 font-medium text-[var(--tg-button-text)] focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50";
const secondary =
  "self-start rounded-xl border border-[var(--tg-hint)]/40 px-5 py-3 focus-visible:outline-2 focus-visible:outline-offset-2";
const choice =
  "w-full rounded-xl border border-[var(--tg-hint)]/40 px-4 py-3 text-left focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50";
const control =
  "rounded-xl border border-[var(--tg-hint)]/30 px-3 py-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-40";
