/* What the skills page knows without asking the server.
 *
 * A person names a skill in their own words; the machine name, the parameter
 * list and the SKILL.md file are all derived from that. The server validates
 * everything again — none of this is trusted — but being told at the keyboard
 * beats being told on save. Anything that yields a sentence returns an i18n
 * key, so the component that shows it can speak the reader's language. */

import type {
  Connector,
  SkillDefinition,
  SkillDefinitionInput,
  SkillKind,
  SkillResource,
} from "@/lib/api";

export const MAX_NAME = 64;
/** One line: the model selects on this, so it has to stay short. */
export const MAX_DESCRIPTION = 200;

/* ---------- kinds ---------- */

export function isProcedure(s: { kind: SkillKind }): boolean {
  return s.kind === "agent";
}

export function isLookupKind(kind: SkillKind): kind is "sql" | "rest" {
  return kind === "sql" || kind === "rest";
}

/** A connection can only serve a lookup of its own family. */
export function connectorFits(c: Connector, kind: SkillKind): boolean {
  if (kind === "rest") return c.kind === "rest";
  if (kind === "sql") return c.kind === "sql_sqlite" || c.kind === "sql_postgres" || c.kind === "sql_mysql";
  return false;
}

/* ---------- names ---------- */

/* Cyrillic → Latin, the everyday transliteration people use for logins. The
   machine name is derived from the title, so a Russian title must still yield
   a legal name without anyone being asked to invent one. */
const CYRILLIC: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "yo", ж: "zh", з: "z",
  и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r",
  с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "ts", ч: "ch", ш: "sh", щ: "sch",
  ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
  // Tajik letters
  ғ: "g", ӣ: "i", қ: "q", ӯ: "u", ҳ: "h", ҷ: "j",
};

export function transliterate(text: string): string {
  return Array.from(text.toLowerCase(), (ch) => CYRILLIC[ch] ?? ch).join("");
}

/** The legal name a title turns into: hyphens for a procedure, underscores for a lookup. */
export function machineName(title: string, kind: SkillKind): string {
  const sep = kind === "agent" ? "-" : "_";
  let name = transliterate(title)
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, sep)
    .replace(new RegExp(`^${sep}+|${sep}+$`, "g"), "")
    .slice(0, MAX_NAME)
    .replace(new RegExp(`${sep}+$`), "");
  // a lookup name must start with a letter
  if (kind !== "agent") name = name.replace(/^[0-9_]+/, "");
  return name;
}

/** "weekly-report" / "store_sales" → "Weekly report" / "Store sales". */
export function humanTitle(name: string): string {
  const words = name.replace(/[-_]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

const RESERVED = ["anthropic", "claude"];

/** The i18n key of the reason this name is illegal, or "" when it is fine. */
export function nameProblem(name: string, kind: SkillKind): string {
  if (!name) return "skills.name.err.empty";
  if (name.length > MAX_NAME) return "skills.name.err.long";
  if (kind === "agent") {
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(name) || name.length < 3)
      return "skills.name.err.hyphen";
    if (RESERVED.some((w) => name.includes(w))) return "skills.name.err.reserved";
    return "";
  }
  if (!/^[a-z][a-z0-9_]{2,63}$/.test(name)) return "skills.name.err.snake";
  return "";
}

/* ---------- parameters ---------- */

export type ParamType = "string" | "integer" | "number" | "boolean";
export const PARAM_TYPES: ParamType[] = ["string", "number", "integer", "boolean"];

export interface ParamRow {
  name: string;
  type: ParamType;
}

/* `tenant_id` is bound by the platform on every call and must never be
   declared, so it is filtered out wherever placeholders are read. */
const PLATFORM_BOUND = new Set(["tenant_id"]);

/** The `:name` / `%(name)s` placeholders of a statement, or the `{name}` ones of a path. */
export function detectPlaceholders(text: string, kind: SkillKind): string[] {
  const found: string[] = [];
  const add = (n: string) => {
    if (!PLATFORM_BOUND.has(n) && !found.includes(n)) found.push(n);
  };
  if (kind === "rest") {
    for (const m of text.matchAll(/\{([a-zA-Z_]\w*)\}/g)) add(m[1]);
  } else {
    for (const m of text.matchAll(/(?<![:\w]):([a-zA-Z_]\w*)/g)) add(m[1]);
    for (const m of text.matchAll(/%\((\w+)\)s/g)) add(m[1]);
  }
  return found;
}

/** The same guess the server makes from a placeholder's name. */
export function guessType(name: string): ParamType {
  const n = name.toLowerCase();
  if (/(_id|_count)$/.test(n) || ["days", "year", "month"].includes(n)) return "integer";
  if (/(amount|price|total|sum|rate)/.test(n)) return "number";
  if (/^(is|has)_/.test(n)) return "boolean";
  return "string";
}

/** Placeholders as rows, keeping any type the person already chose. */
export function mergeParams(names: string[], previous: ParamRow[]): ParamRow[] {
  return names.map(
    (name) => previous.find((p) => p.name === name) ?? { name, type: guessType(name) },
  );
}

/** The closed schema the server requires — every placeholder, nothing more. */
export function buildSchema(rows: ParamRow[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  for (const r of rows) properties[r.name] = { type: r.type };
  return {
    type: "object",
    properties,
    required: rows.map((r) => r.name),
    additionalProperties: false,
  };
}

export function rowsFromSchema(schema: Record<string, unknown> | null): ParamRow[] {
  const props = (schema?.properties ?? {}) as Record<string, { type?: string }>;
  return Object.entries(props).map(([name, spec]) => ({
    name,
    type: PARAM_TYPES.includes(spec.type as ParamType) ? (spec.type as ParamType) : "string",
  }));
}

/** Turn what was typed into the Try-it inputs into typed arguments. */
export function coerceArgs(
  rows: ParamRow[],
  raw: Record<string, string>,
): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  for (const r of rows) {
    const v = raw[r.name];
    if (v === undefined || v === "") continue;
    if (r.type === "integer" || r.type === "number") args[r.name] = Number(v);
    else if (r.type === "boolean") args[r.name] = v === "true";
    else args[r.name] = v;
  }
  return args;
}

/* ---------- statements ---------- */

/** The server refuses anything but SELECT / WITH; say so before it has to. */
export function looksReadOnly(sql: string): boolean {
  const s = sql.trim().toLowerCase();
  return s === "" || s.startsWith("select") || s.startsWith("with");
}

/* ---------- reference files ---------- */

/** The i18n key of what is wrong with this file name, or "". */
export function resourceProblem(path: string, others: SkillResource[]): string {
  const p = path.trim();
  if (!p) return "skills.res.err.empty";
  if (
    p.startsWith("/") ||
    p.includes("\\") ||
    !/^[A-Za-z0-9._-]+(\/[A-Za-z0-9._-]+)*$/.test(p) ||
    p.split("/").includes("..")
  )
    return "skills.res.err.chars";
  if (others.filter((r) => r.path.trim() === p).length > 1) return "skills.res.err.dup";
  return "";
}

/* ---------- the file itself ---------- */

/** Exactly what the server stores and what Claude Code would read. */
export function renderSkillMd(name: string, description: string, instructions: string): string {
  return `---\nname: ${name}\ndescription: ${description.trim()}\n---\n\n${instructions.replace(
    /^\n+|\n+$/g,
    "",
  )}\n`;
}

/* ---------- to and from the wire ---------- */

export function toInput(s: SkillDefinition): SkillDefinitionInput {
  return {
    name: s.name,
    description: s.description,
    kind: s.kind,
    connector_id: s.connector_id,
    param_schema: s.param_schema,
    sql: s.sql,
    path: s.path,
    instructions: s.instructions,
    resources: s.resources,
    required_data_class: s.required_data_class,
    required_roles: s.required_roles,
    row_limit: s.row_limit,
    shared: s.shared,
    enabled: s.enabled,
  };
}

export function blankInput(kind: SkillKind): SkillDefinitionInput {
  return {
    name: "",
    description: "",
    kind,
    connector_id: "",
    param_schema: null,
    sql: "",
    path: "",
    instructions: "",
    resources: [],
    required_data_class: "operational",
    required_roles: [],
    row_limit: null,
    shared: false,
  };
}

/** The line a card shows under the title. */
export function summarise(s: SkillDefinition): string {
  return s.description || s.name;
}

/** Search matches the words a person would type, not the machine name alone. */
export function matches(s: SkillDefinition, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    s.name.toLowerCase().includes(q) ||
    humanTitle(s.name).toLowerCase().includes(q) ||
    s.description.toLowerCase().includes(q)
  );
}
