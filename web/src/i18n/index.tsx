"use client";

/* Interface language.
 *
 * Russian is the console's first language; English stays one click away. The
 * choice is per browser (localStorage), independent of any account setting —
 * and it never touches the assistant's answers, which always follow the
 * language of the question.
 *
 * Dictionaries live next to the pages they belong to (`./chat`, `./skills`,
 * …) so a page can be translated without touching any other. Keys are plain
 * strings; a missing Russian entry falls back to English, and a key missing
 * from both is shown as-is so the gap is visible rather than silent. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { admin } from "./admin";
import { assistants } from "./assistants";
import { audit } from "./audit";
import { chat } from "./chat";
import { common } from "./common";
import { data } from "./data";
import { documents } from "./documents";
import { engineering } from "./engineering";
import { skills } from "./skills";
import { usage } from "./usage";

export type Locale = "ru" | "en";
export const LOCALES: { value: Locale; label: string; short: string }[] = [
  { value: "ru", label: "Русский", short: "RU" },
  { value: "en", label: "English", short: "EN" },
];
export const DEFAULT_LOCALE: Locale = "ru";
const STORAGE_KEY = "karag_locale";

export type Dictionary = { en: Record<string, string>; ru: Record<string, string> };

function merge(...dicts: Dictionary[]): Dictionary {
  const out: Dictionary = { en: {}, ru: {} };
  for (const d of dicts) {
    Object.assign(out.en, d.en);
    Object.assign(out.ru, d.ru);
  }
  return out;
}

const ALL = merge(common, chat, assistants, skills, data, documents, admin, audit, usage, engineering);

/* The active locale is also kept outside React so plain helpers (`words.ts`)
   can read it without a hook. It is written at the moment the locale changes
   (never during a render), and every change re-renders the whole tree, so the
   two never disagree while rendering. */
let active: Locale = DEFAULT_LOCALE;
export function activeLocale(): Locale {
  return active;
}

export type Vars = Record<string, string | number>;

function fill(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (m, k: string) =>
    k in vars ? String(vars[k]) : m,
  );
}

/** Translate a key in a given locale — the hook-free form. */
export function translate(locale: Locale, key: string, vars?: Vars): string {
  const hit = ALL[locale][key] ?? ALL.en[key] ?? key;
  return fill(hit, vars);
}

export type T = (key: string, vars?: Vars) => string;

interface LocaleState {
  locale: Locale;
  setLocale: (l: Locale) => void;
  ready: boolean;
  t: T;
}

const Ctx = createContext<LocaleState | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  const [ready, setReady] = useState(false);

  /* localStorage is unavailable on the server; read it once on the client and
     let the shell wait for `ready`, exactly like the auth token. */
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(STORAGE_KEY);
    } catch {
      /* private mode, blocked storage — the default stands */
    }
    const initial: Locale = stored === "en" || stored === "ru" ? stored : DEFAULT_LOCALE;
    active = initial;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLocaleState(initial);
    setReady(true);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
    if (!ready) return;
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* ignore */
    }
  }, [locale, ready]);

  const setLocale = useCallback((l: Locale) => {
    active = l;
    setLocaleState(l);
  }, []);
  const t = useCallback<T>((key, vars) => translate(locale, key, vars), [locale]);

  const value = useMemo(() => ({ locale, setLocale, ready, t }), [locale, setLocale, ready, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLocale(): LocaleState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLocale outside LocaleProvider");
  return ctx;
}

/** The translator for the current interface language. */
export function useT(): T {
  return useLocale().t;
}
