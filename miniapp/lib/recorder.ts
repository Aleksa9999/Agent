/** Microphone access from the Mini App. Not every device allows it; the caller offers the chat then. */

export type MicEnvironment = {
  isSecureContext?: boolean;
  mediaDevices?: { getUserMedia?: unknown };
  hasMediaRecorder: boolean;
};

export type MicSupport = "ok" | "unsupported";

export function detectMic(env: MicEnvironment): MicSupport {
  if (env.isSecureContext === false) return "unsupported";
  if (typeof env.mediaDevices?.getUserMedia !== "function") return "unsupported";
  return env.hasMediaRecorder ? "ok" : "unsupported";
}

export function browserMicSupport(): MicSupport {
  if (typeof window === "undefined") return "unsupported";
  return detectMic({
    isSecureContext: window.isSecureContext,
    mediaDevices: navigator.mediaDevices,
    hasMediaRecorder: typeof MediaRecorder !== "undefined",
  });
}

export type RecordError = "denied" | "no_device" | "failed";

/** Maps what the browser throws to a reason the person can act on. */
export function recordError(error: unknown): RecordError {
  const name = (error as { name?: string } | null)?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError") return "denied";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "no_device";
  return "failed";
}

const PREFERRED = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

export function pickMime(isSupported: (type: string) => boolean): string | undefined {
  return PREFERRED.find((type) => isSupported(type));
}

export const MAX_RECORDING_MS = 5 * 60 * 1000;

export type Recording = { stop: () => Promise<Blob>; cancel: () => void };

export async function startRecording(onLimit: () => void): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mime = pickMime((type) => MediaRecorder.isTypeSupported(type));
  const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  const release = () => stream.getTracks().forEach((track) => track.stop());
  const timer = setTimeout(onLimit, MAX_RECORDING_MS);
  recorder.start();
  return {
    stop: () =>
      new Promise<Blob>((resolve) => {
        clearTimeout(timer);
        recorder.onstop = () => {
          release();
          resolve(new Blob(chunks, { type: recorder.mimeType || mime || "audio/webm" }));
        };
        recorder.stop();
      }),
    cancel: () => {
      clearTimeout(timer);
      recorder.onstop = null;
      if (recorder.state !== "inactive") recorder.stop();
      release();
    },
  };
}
