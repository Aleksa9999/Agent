import en from "@/messages/en.json";
import ru from "@/messages/ru.json";

const catalogs = { ru, en } as const;
export type MessageKey = keyof typeof ru;
export type Locale = keyof typeof catalogs;

export function pickLocale(value: string | undefined): Locale {
  return value === "en" ? "en" : "ru";
}

export function t(locale: Locale, key: MessageKey, values: Record<string, string> = {}): string {
  let text: string = catalogs[locale][key];
  for (const [name, replacement] of Object.entries(values)) {
    text = text.replaceAll(`{${name}}`, replacement);
  }
  return text;
}

/** For keys built at run time (branch names). A missing key shows the key, never breaks the screen. */
export function tByName(locale: Locale, key: string): string {
  const catalog = catalogs[locale] as Record<string, string>;
  return catalog[key] ?? key;
}
