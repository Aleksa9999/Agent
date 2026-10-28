/** A short tap of vibration through Telegram. Nothing happens where it is not supported. */

type Haptics = { impactOccurred?: (style: string) => void };

export function tap(haptics: Haptics | undefined = typeof window === "undefined" ? undefined : (window.Telegram?.WebApp as { HapticFeedback?: Haptics } | undefined)?.HapticFeedback): void {
  try {
    haptics?.impactOccurred?.("light");
  } catch {
    // vibration is a nicety: never a reason to fail
  }
}
