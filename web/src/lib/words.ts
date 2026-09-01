/* The UI's vocabulary.
 *
 * KARAG's API speaks in platform terms — data classes, tenants, principals,
 * skill allow-lists. The people using the console are pharmacists, finance
 * leads and store managers, so the screen speaks their language instead and
 * translates at the edge. The API contract is untouched: these are labels.
 *
 * One place, so "operational" reads as "Staff" on every page. */

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

export const AUDIENCES: Audience[] = [
  {
    value: "public",
    label: "Everyone",
    who: "Anyone at your company can see this.",
    dot: "var(--good)",
    level: 1,
  },
  {
    value: "operational",
    label: "Staff",
    who: "Employees and managers. Not visible to outside accounts.",
    dot: "var(--accent-2)",
    level: 2,
  },
  {
    value: "hr",
    label: "HR only",
    who: "People records — only HR and leadership.",
    dot: "var(--warn)",
    level: 3,
  },
  {
    value: "financial",
    label: "Finance only",
    who: "Money and numbers — only finance and leadership.",
    dot: "var(--accent)",
    level: 4,
  },
  {
    value: "regulated",
    label: "Restricted",
    who: "The most sensitive material. Almost no one sees this.",
    dot: "var(--bad)",
    level: 5,
  },
];

export function audience(value: string | null | undefined): Audience {
  return AUDIENCES.find((a) => a.value === value) ?? AUDIENCES[1];
}

/* ---------- who someone is (API: role) ---------- */

export interface RoleWord {
  value: string;
  label: string;
  who: string;
}

export const ROLES: RoleWord[] = [
  { value: "employee", label: "Employee", who: "Everyday access to shared knowledge." },
  { value: "hr", label: "HR", who: "Can also see people records." },
  { value: "finance", label: "Finance", who: "Can also see financial figures." },
  { value: "skill_author", label: "Data author", who: "Can also set up live data lookups." },
  { value: "admin", label: "Administrator", who: "Manages people and settings for this company." },
  { value: "ceo", label: "Leadership", who: "Sees everything belonging to this company." },
  { value: "platform_admin", label: "Platform operator", who: "Runs KARAG itself, across all companies." },
  { value: "karag_engineer", label: "Platform engineer", who: "May propose changes to KARAG's own code." },
];

export function role(value: string): RoleWord {
  const known = ROLES.find((r) => r.value === value);
  if (known) return known;
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
const ACTIONS: Record<string, string> = {
  ask: "asked a question",
  retrieve: "searched the knowledge base",
  ingest: "added knowledge",
  document_delete: "removed a document",

  skill_execute: "looked up live data",
  skill_test: "tested a lookup",
  skill_create: "created a lookup",
  skill_update: "changed a lookup",
  skill_delete: "removed a lookup",
  skill_get: "opened a lookup",
  skill_list: "listed the lookups",

  connector_create: "connected a data source",
  connector_delete: "disconnected a data source",
  connector_list: "listed the data sources",

  library_import: "copied a shared lookup",
  library_list: "browsed shared lookups",

  alert_create: "created an alert",
  alert_delete: "deleted an alert",
  alert_run: "ran an alert",
  alert_tick: "checked an alert on schedule",

  code_propose: "proposed a change to KARAG",
  code_apply: "applied a change to KARAG",
  code_discard: "discarded a proposed change",
};

export function actionWords(action: string): string {
  if (ACTIONS[action]) return ACTIONS[action];

  /* Operational skills are logged as `agent_<skill_name>` — the assistant
     acting on someone's behalf. Say that plainly. */
  if (action.startsWith("agent_"))
    return `asked the assistant to ${action.slice(6).replace(/_/g, " ")}`;

  // Anything new: readable rather than hidden.
  return action.replace(/_/g, " ");
}

/* ---------- time ---------- */

/** "just now" / "12 min ago" / "Tue 14:03" — never a raw timestamp. */
export function whenWords(tsSeconds: number): string {
  const diff = Date.now() / 1000 - tsSeconds;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  const d = new Date(tsSeconds * 1000);
  if (diff < 7 * 86400)
    return d.toLocaleDateString(undefined, {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/* ---------- sizes ---------- */

export function sizeWords(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ---------- errors ---------- */

/** Turn an API failure into something that says what to do next. */
export function errorWords(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("403") || m.includes("forbidden") || m.includes("denied"))
    return "Your access level doesn't cover this. Ask an administrator if you need it.";
  if (m.includes("401") || m.includes("unauthorized"))
    return "Your session has expired. Sign in again to continue.";
  if (m.includes("404") || m.includes("not found"))
    return "That's no longer here — it may have been removed.";
  if (m.includes("413") || m.includes("too large"))
    return "That file is too big. Try one under 20 MB.";
  if (m.includes("fetch") || m.includes("network") || m.includes("failed to fetch"))
    return "Can't reach the server. Check your connection and try again.";
  return message;
}
