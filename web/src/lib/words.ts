/* The UI's vocabulary.
 *
 * KARAG's API speaks in platform terms — data classes, tenants, principals,
 * skill allow-lists. The people using the console are pharmacists, finance
 * leads and store managers, so the screen speaks their language instead and
 * translates at the edge. The API contract is untouched: these are labels.
 *
 * One place, so "operational" reads as "Staff" / «Сотрудники» on every page.
 * Every helper reads the active interface language, so a component can keep
 * calling `audience(v).label` without threading a locale through. */

import { activeLocale, translate, type Locale } from "@/i18n";

function tr(key: string, vars?: Record<string, string | number>, locale?: Locale): string {
  return translate(locale ?? activeLocale(), key, vars);
}

/* ---------- who can see this (API: data_class) ---------- */

export interface Audience {
  /** wire value — what the API stores */
  value: string;
  /** what the reader sees */
  label: string;
  /** one line: who, in terms of people not roles */
  who: string;
  /** the swatch that carries this class across the app */
  dot: string;
  /** rank, least → most restricted; drives the sensitivity meter */
  level: number;
}

const AUDIENCE_BASE = [
  { value: "public", dot: "var(--good)", level: 1 },
  { value: "operational", dot: "var(--accent-2)", level: 2 },
  { value: "hr", dot: "var(--warn)", level: 3 },
  { value: "financial", dot: "var(--accent)", level: 4 },
  { value: "regulated", dot: "var(--bad)", level: 5 },
] as const;

function audienceFor(base: (typeof AUDIENCE_BASE)[number], locale?: Locale): Audience {
  return {
    ...base,
    label: tr(`aud.${base.value}.label`, undefined, locale),
    who: tr(`aud.${base.value}.who`, undefined, locale),
  };
}

/** The five audiences in the active language, least → most restricted. */
export function audiences(locale?: Locale): Audience[] {
  return AUDIENCE_BASE.map((b) => audienceFor(b, locale));
}

/** @deprecated read `audiences()` inside a component so the language is current */
export const AUDIENCES: Audience[] = audiences("en");

export function audience(value: string | null | undefined, locale?: Locale): Audience {
  const base = AUDIENCE_BASE.find((a) => a.value === value) ?? AUDIENCE_BASE[1];
  return audienceFor(base, locale);
}

/* ---------- who someone is (API: role) ---------- */

export interface RoleWord {
  value: string;
  label: string;
  who: string;
}

export const ROLE_VALUES = [
  "employee", "hr", "finance", "skill_author", "admin", "ceo",
  "platform_admin", "karag_engineer",
] as const;

export function roles(locale?: Locale): RoleWord[] {
  return ROLE_VALUES.map((v) => role(v, locale));
}

/** @deprecated read `roles()` inside a component so the language is current */
export const ROLES: RoleWord[] = roles("en");

export function role(value: string, locale?: Locale): RoleWord {
  const label = tr(`role.${value}`, undefined, locale);
  if (label !== `role.${value}`) {
    return { value, label, who: tr(`role.${value}.who`, undefined, locale) };
  }
  // A role the UI hasn't been taught yet still has to read as a name.
  const words = value.replace(/_/g, " ");
  return {
    value,
    label: words.charAt(0).toUpperCase() + words.slice(1),
    who: "",
  };
}

export function roleLabel(value: string): string {
  return role(value).label;
}

/* ---------- what happened (API: audit action) ---------- */

/* The wire values are snake_case verbs — verified against the running app's
   audit table and the `_log(principal, "...")` call sites, not guessed.
   Whether it was allowed lives in `decision`, so these are phrased neutrally
   and the screen adds the refusal. */
export function actionWords(action: string): string {
  const hit = tr(`act.${action}`);
  if (hit !== `act.${action}`) return hit;

  /* Operational skills are logged as `agent_<skill_name>` — the assistant
     acting on someone's behalf. Say that plainly. */
  if (action.startsWith("agent_"))
    return tr("act.agent", { what: action.slice(6).replace(/_/g, " ") });

  // Anything new: readable rather than hidden.
  return action.replace(/_/g, " ");
}

/* ---------- time ---------- */

/** "just now" / "12 min ago" / "Tue 14:03" — never a raw timestamp. */
export function whenWords(tsSeconds: number): string {
  const diff = Date.now() / 1000 - tsSeconds;
  const lang = activeLocale() === "ru" ? "ru-RU" : "en-US";
  if (diff < 45) return tr("time.now");
  if (diff < 3600) return tr("time.min", { n: Math.round(diff / 60) });
  if (diff < 86400) return tr("time.h", { n: Math.round(diff / 3600) });
  const d = new Date(tsSeconds * 1000);
  if (diff < 7 * 86400)
    return d.toLocaleDateString(lang, {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  return d.toLocaleDateString(lang, { day: "numeric", month: "short" });
}

/* ---------- sizes ---------- */

export function sizeWords(bytes: number): string {
  const ru = activeLocale() === "ru";
  if (bytes < 1024) return `${bytes} ${ru ? "Б" : "B"}`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} ${ru ? "КБ" : "KB"}`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} ${ru ? "МБ" : "MB"}`;
}

/* ---------- errors ---------- */

/** Turn an API failure into something that says what to do next. */
export function errorWords(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("403") || m.includes("forbidden") || m.includes("denied"))
    return tr("err.forbidden");
  if (m.includes("401") || m.includes("unauthorized")) return tr("err.expired");
  if (m.includes("404") || m.includes("not found")) return tr("err.gone");
  if (m.includes("413") || m.includes("too large")) return tr("err.large");
  if (m.includes("502") || m.includes("anthropic") || m.includes("openai") || m.includes("model could not"))
    return tr("err.model");
  if (m.includes("fetch") || m.includes("network") || m.includes("failed to fetch"))
    return tr("err.network");
  return message;
}
