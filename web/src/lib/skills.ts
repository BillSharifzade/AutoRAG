/* What the skill editor knows about the SKILL.md format.
 *
 * The rules here are Anthropic's published ones for an Agent Skill, moved
 * forward to the moment of typing: a name is checked as it is written, a
 * description is reviewed against the guidance that decides whether the skill
 * will ever fire, and the file the assistant would actually read is rendered
 * live. The server validates all of this again — none of it is trusted — but
 * being told at the keyboard beats being told on save. */

import type { SkillDefinition, SkillKind, SkillResource } from "@/lib/api";

export const MAX_NAME = 64;
export const MAX_DESCRIPTION = 1024;
/** Guidance, not a limit: past this, split the body into bundled files. */
export const ADVISED_MAX_BODY_LINES = 500;

/* ---------- the two kinds, in the reader's words ---------- */

export interface KindWord {
  value: SkillKind;
  label: string;
  /** one line, for a card or a badge tooltip */
  who: string;
}

export const KINDS: Record<"agent" | "lookup", KindWord> = {
  agent: {
    value: "agent",
    label: "Procedure",
    who: "How your company does something. Written once, followed every time.",
  },
  lookup: {
    value: "sql",
    label: "Lookup",
    who: "A real figure, fetched from a system you connect. Never a guess.",
  },
};

export function kindLabel(kind: SkillKind): string {
  return kind === "agent" ? KINDS.agent.label : KINDS.lookup.label;
}

export function isProcedure(s: { kind: SkillKind }): boolean {
  return s.kind === "agent";
}

/* ---------- name ---------- */

/** Turn anything a person types into a legal skill name. */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_NAME)
    .replace(/-+$/g, "");
}

const RESERVED = ["anthropic", "claude"];

/** The reason this name is illegal, or "" when it is fine. */
export function nameProblem(name: string): string {
  if (!name) return "";
  if (name.length > MAX_NAME) return `Too long — ${MAX_NAME} characters at most.`;
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(name))
    return "Lowercase letters, numbers and single hyphens only.";
  const reserved = RESERVED.find((w) => name.includes(w));
  if (reserved) return `Can't contain the word “${reserved}”.`;
  return "";
}

/* ---------- description: the part that decides everything ---------- */

export interface DescriptionNote {
  ok: boolean;
  /** what was checked, phrased as the thing to do */
  label: string;
  /** why it matters — shown when the check fails */
  why: string;
}

const WHEN_MARKERS =
  /\b(use (this )?(when|for|if|whenever)|when (the user|someone|asked|a|you)|for when|whenever)\b/i;
const FIRST_PERSON = /^\s*(i |i'|we |you can|you should|this (skill )?(lets|helps) you|helps you)/i;

/**
 * Review a description the way the model will read it.
 *
 * Only the length rules are enforced by the server; the rest is the published
 * authoring guidance, which is where a skill usually fails — not by being
 * rejected, but by never being selected.
 */
export function reviewDescription(text: string): DescriptionNote[] {
  const d = text.trim();
  const words = d ? d.split(/\s+/).length : 0;
  return [
    {
      ok: d.length > 0 && d.length <= MAX_DESCRIPTION,
      label: `Within ${MAX_DESCRIPTION} characters`,
      why: d.length === 0
        ? "This is the only thing the assistant sees before deciding to use the skill."
        : "Too long to sit in the assistant's working memory alongside everything else.",
    },
    {
      ok: words >= 8,
      label: "Says specifically what it does",
      why: "“Helps with documents” matches nothing. Name the actual task and the things it touches.",
    },
    {
      ok: WHEN_MARKERS.test(d),
      label: "Says when to use it",
      why: "Add a sentence starting “Use when…” with the words someone would actually say.",
    },
    {
      ok: d.length === 0 || !FIRST_PERSON.test(d),
      label: "Written in the third person",
      why: "Write “Produces the weekly report”, not “I can help you write reports” — it is read as a description, not as speech.",
    },
  ];
}

export const EXAMPLE_DESCRIPTION =
  "Produces the weekly store performance report in the company's format, " +
  "including the week-on-week comparison. Use when asked for the weekly " +
  "report, a store performance summary, or how a store did last week.";

/* ---------- the file itself ---------- */

/** Exactly what the server stores and what Claude Code would read. */
export function renderSkillMd(
  name: string,
  description: string,
  instructions: string,
): string {
  return `---\nname: ${name}\ndescription: ${description.trim()}\n---\n\n${instructions.replace(
    /^\n+|\n+$/g,
    "",
  )}\n`;
}

export function bodyLines(instructions: string): number {
  return instructions.trim() ? instructions.trim().split("\n").length : 0;
}

/* ---------- bundled files ---------- */

export function resourceProblem(path: string, others: SkillResource[]): string {
  const p = path.trim();
  if (!p) return "Give the file a name.";
  if (p.startsWith("/") || p.includes("\\"))
    return "Use a relative path with forward slashes, e.g. reference/regions.md";
  if (!/^[A-Za-z0-9._-]+(\/[A-Za-z0-9._-]+)*$/.test(p) || p.split("/").includes(".."))
    return "Letters, numbers, dots, dashes and / only.";
  if (others.filter((r) => r.path.trim() === p).length > 1)
    return "Another bundled file already has this name.";
  return "";
}

/** Bundled files the instructions never mention will never be read. */
export function unreferencedResources(
  instructions: string,
  resources: SkillResource[],
): string[] {
  return resources
    .map((r) => r.path.trim())
    .filter((p) => p && !instructions.includes(p));
}

/* ---------- what the assistant is holding ---------- */

/** What level 1 costs, in the only unit a reader can picture: words. */
export function metadataWords(name: string, description: string): number {
  const d = description.trim();
  return (d ? d.split(/\s+/).length : 0) + (name.trim() ? 1 : 0);
}

export function summarise(s: SkillDefinition): string {
  return s.description || s.name;
}
