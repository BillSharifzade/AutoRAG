/* Pure helpers for the assistants page — no React in here. */

import type { Locale } from "@/i18n";

/* Six tones drawn from the theme's own tokens, so an avatar reads the same in
   light and dark. Hashed from the name: the same assistant looks the same on
   its card, in the detail view and anywhere else it shows up. */
const TONES = [
  "bg-accent-soft text-accent-strong",
  "bg-accent-2-soft text-accent-2",
  "bg-good-soft text-good",
  "bg-warn-soft text-warn",
  "bg-bad-soft text-bad",
  "bg-surface-2 text-ink",
];

export function toneFor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return TONES[h % TONES.length];
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/** `create_spreadsheet` → "create spreadsheet" */
export function humanise(skillName: string): string {
  return skillName.replace(/[_-]+/g, " ").trim();
}

/* `allowed_skill_names` on the wire: null = everything the person may use,
   [] = documents only, a list = exactly those. The page speaks in three
   modes instead. */
export type AccessMode = "all" | "docs" | "some";

export function accessOf(allowed: string[] | null): AccessMode {
  if (allowed === null) return "all";
  return allowed.length === 0 ? "docs" : "some";
}

export function sameAccess(a: string[] | null, b: string[] | null): boolean {
  if (a === null || b === null) return a === b;
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((s) => set.has(s));
}

/** Which plural form a count takes: Russian has three, English two. */
export function pluralKey(locale: Locale, n: number): "one" | "few" | "many" {
  if (locale === "ru") {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return "one";
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "few";
    return "many";
  }
  return n === 1 ? "one" : "many";
}
