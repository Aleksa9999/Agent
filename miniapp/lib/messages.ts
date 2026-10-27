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
