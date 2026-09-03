/* Typed client for the KARAG REST API.
   Requests go to same-origin /v1/* and are proxied to FastAPI by next.config. */

export interface Citation {
  marker: string;
  document_id: string;
  chunk_id: string;
  title: string;
  source_uri: string | null;
  snippet: string;
}

export interface ArtifactPayload {
  filename: string;
  mime: string;
  size_bytes: number;
  // absent for artifacts reloaded from saved history (bytes aren't persisted)
  content_base64?: string;
}

export interface Answer {
  text: string;
  citations: Citation[];
  /** `error` / `stopped` only appear on turns reloaded from history */
  plane: "knowledge" | "data" | "mixed" | "refusal" | "error" | "stopped";
  skills_used: string[];
  queries_shown: string[];
  artifacts: ArtifactPayload[];
  diagnostics?: Record<string, unknown>;
}

export interface SkillInfo {
  name: string;
  description: string;
}

export interface Assistant {
  id: string;
  name: string;
  instruction: string;
  /** null = everything the person may use · [] = documents only · list = exactly those */
  allowed_skill_names: string[] | null;
  /** kept by the API for compatibility; answers always follow the question */
  language: Language;
  created_by: string;
  /** the caller made it, or holds an administrator role */
  can_edit: boolean;
}

/** Fields omitted from an update stay as they were. */
export interface AssistantUpdate {
  name?: string;
  instruction?: string;
  allowed_skill_names?: string[] | null;
}

/* ---------- language (§2: RU / TJ are the moat) ---------- */

export type Language = "auto" | "ru" | "tg" | "en";

/** @deprecated the answer always follows the question; kept for old payloads */
export const LANGUAGE_LABELS: Record<Language, string> = {
  auto: "Match the question",
  ru: "Русский",
  tg: "Тоҷикӣ",
  en: "English",
};

export interface Me {
  tenant_id: string;
  user_id: string;
  roles: string[];
  language: Language;
  can_author_skills: boolean;
  can_edit_code: boolean;
}

/* ---------- platform self-knowledge ---------- */

export interface Onboarding {
  roles: string[];
  guides: { role: string; guide: string }[];
  /** the question the "show me around" tip asks on the user's behalf */
  prompt: string;
}

/* ---------- AI-authored code changes ---------- */

export interface CodeProposal {
  id: string;
  author: string;
  summary: string;
  branch: string;
  files_changed: string[];
  insertions: number;
  deletions: number;
  tests_passed: boolean;
  tests_summary: string;
  status: "pending" | "applied" | "discarded";
  model: string;
  created_at: number;
  resolved_at: number;
  resolved_by: string;
  /** present only on the detail fetch */
  diff?: string;
}

/* ---------- knowledge catalogue ---------- */

export type DataClass =
  | "public"
  | "operational"
  | "hr"
  | "financial"
  | "regulated";

export interface DocumentSummary {
  document_id: string;
  title: string;
  data_class: DataClass;
  source_uri: string | null;
  chunks: number;
}

/** §7: advisory only — the uploader always confirms before ingesting. */
export interface Classification {
  suggested: DataClass;
  confidence: number;
  matched: Record<string, string[]>;
  rationale: string;
  advisory: true;
}

/* ---------- connectors + authored skills (§5, §6) ---------- */

export type ConnectorKind = "sql_sqlite" | "sql_postgres" | "sql_mysql" | "rest";

/** What the guided database flow learned and decided (empty for a connector
    made by hand on the Skills page). */
export interface ConnectorMeta {
  source?: "connect" | "upload";
  description?: string;
  summary?: string;
  table_meanings?: Record<string, string>;
  schema_summary?: string;
  table_count?: number;
  data_class?: DataClass;
  required_roles?: string[];
  free_query?: boolean;
  knowledge?: boolean;
  language?: string;
  comment?: string;
  document_id?: string;
  host?: string;
  database?: string;
  filename?: string;
  bytes?: number;
  import?: {
    statements: number;
    executed: number;
    failed: { statement: string; error: string }[];
    failed_count: number;
    tables: string[];
    rows: number;
  };
}

export interface Connector {
  id: string;
  name: string;
  kind: ConnectorKind;
  /** secret values arrive redacted as "••••••" */
  config: Record<string, string>;
  row_limit: number;
  timeout_s: number;
  created_by: string;
  created_at: number;
  metadata: ConnectorMeta;
}

/* ---------- guided integrations: API sources ---------- */

export interface PayloadField {
  name: string;
  types: string[];
  samples: unknown[];
  filled: number;
}

export interface PayloadProfile {
  kind: "records" | "object" | "scalar" | "text";
  record_count: number;
  fields: PayloadField[];
  records_path: string;
  sample: unknown[];
  text_preview: string;
  top_level_keys: string[];
}

export interface PayloadAnalysis {
  summary: string;
  suggested_name: string;
  suggested_description: string;
  fields: { name: string; meaning: string }[];
  concerns: string[];
  looks_right: boolean;
  source: "model" | "model_text" | "heuristic";
}

export interface ProbeResult {
  url: string;
  content_type: string;
  kind: "json" | "csv" | "text";
  bytes: number;
  truncated: boolean;
  profile: PayloadProfile;
  analysis: PayloadAnalysis;
}

export interface DataSource {
  id: string;
  tenant_id: string;
  name: string;
  url: string;
  description: string;
  field_notes: Record<string, string>;
  data_class: DataClass;
  required_roles: string[];
  skill_enabled: boolean;
  skill_name: string;
  sync_enabled: boolean;
  sync_interval_s: number;
  created_by: string;
  created_at: number;
  updated_at: number;
  last_synced_at: number;
  last_checked_at: number;
  last_status: "" | "ok" | "unchanged" | "error";
  last_error: string;
  last_records: number;
  document_id: string;
}

export interface DataSourceInput {
  name: string;
  url: string;
  description: string;
  field_notes: Record<string, string>;
  data_class: DataClass;
  required_roles: string[];
  skill_enabled: boolean;
  sync_enabled: boolean;
  sync_interval_s: number;
}

/* ---------- guided integrations: databases ---------- */

export interface DbColumn {
  name: string;
  type: string;
}

export interface DbTable {
  name: string;
  kind: "table" | "view";
  schema: string;
  columns: DbColumn[];
  row_estimate: number | null;
  sample: Record<string, unknown>[];
}

export interface DbSchema {
  backend: "sqlite" | "postgres" | "mysql";
  table_count: number;
  truncated: boolean;
  tables: DbTable[];
}

export interface DbReport {
  summary: string;
  suggested_description: string;
  tables: { name: string; meaning: string }[];
  concerns: string[];
  source: "model" | "model_text" | "heuristic";
}

export interface DbConnectResult {
  connector: Connector;
  schema: DbSchema;
  report: DbReport;
}

export interface DbLogin {
  kind: "sql_postgres" | "sql_mysql";
  host: string;
  port: number | null;
  database: string;
  username: string;
  password: string;
  ssl: boolean;
}

/** `sql`/`rest` fetch a number; `agent` is a SKILL.md that teaches a procedure. */
export type SkillKind = "sql" | "rest" | "agent";

/** A bundled reference file — level 3, read only when the instructions cite it. */
export interface SkillResource {
  path: string;
  content: string;
}

export interface SkillDefinition {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  kind: SkillKind;
  connector_id: string;
  param_schema: Record<string, unknown>;
  sql: string;
  path: string;
  /** agent kind: the SKILL.md body */
  instructions: string;
  resources: SkillResource[];
  required_data_class: DataClass;
  required_roles: string[];
  row_limit: number | null;
  inject_tenant: boolean;
  enabled: boolean;
  shared: boolean;
  created_by: string;
  created_at: number;
  updated_at: number;
}

export interface SkillDefinitionInput {
  name: string;
  description: string;
  kind: SkillKind;
  connector_id: string;
  param_schema: Record<string, unknown> | null;
  sql: string;
  path: string;
  instructions: string;
  resources: SkillResource[];
  required_data_class: DataClass;
  required_roles: string[];
  row_limit: number | null;
  shared: boolean;
  /** omit to leave as is; false keeps the skill stored but not offered */
  enabled?: boolean;
  inject_tenant?: boolean;
}

export interface SkillTestRun {
  ok: boolean;
  query_shown: string;
  data: unknown;
  error: string;
  row_count: number | null;
}

/* ---------- proactive alerts (§15) ---------- */

export interface AlertRule {
  id: string;
  name: string;
  skill_name: string;
  arguments: Record<string, unknown>;
  run_as_user: string;
  run_as_roles: string[];
  interval_s: number;
  condition: "rows_returned" | "field_compare" | "always";
  condition_config: Record<string, unknown>;
  message_template: string;
  channel: string;
  enabled: boolean;
  last_run_at: number;
  last_fired_at: number;
  last_error: string;
}

/* ---------- tenants + accounts (§12, §14) ---------- */

export interface Tenant {
  id: string;
  name: string;
  active: boolean;
  default_language: Language;
  created_at: number;
}

export interface Account {
  id: string;
  tenant_id: string;
  display_name: string;
  roles: string[];
  language: Language;
  active: boolean;
  created_at: number;
  has_token: boolean;
}

export interface AuditEvent {
  action: string;
  tenant_id: string;
  user_id: string;
  decision: "allow" | "deny";
  resource: string;
  detail: Record<string, unknown>;
  ts?: number;
  ip?: string;
  user_agent?: string;
  roles?: string[];
}

export interface UsageEvent {
  ts: number;
  input_tokens: number;
  output_tokens: number;
  model?: string;
}

export interface ModelCost {
  input_usd: number;
  output_usd: number;
  total_usd: number;
  /** false when the model has no configured rate — shown, never guessed */
  priced: boolean;
}

export interface ModelUsage {
  model: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: ModelCost;
}

export interface UsageTotals {
  tenant_id: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  unpriced_models: string[];
  by_model: ModelUsage[];
  events: UsageEvent[];
}

export interface ChatAttachment {
  kind: "image" | "file" | "audio";
  filename: string;
  media_type: string;
  data_b64: string;
}

/* ---------- chat history ---------- */

export interface ChatSummary {
  id: string;
  title: string;
  assistant_id: string | null;
  created_at: number;
  updated_at: number;
  message_count: number;
  preview: string;
}

export interface StoredChatMessage {
  role: "user" | "assistant";
  text: string;
  ts: number;
  answer: Answer | null;
  attachments: { kind: ChatAttachment["kind"]; filename: string }[];
}

export interface ChatDetail {
  id: string;
  title: string;
  assistant_id: string | null;
  created_at: number;
  updated_at: number;
  messages: StoredChatMessage[];
}

export interface ChatAskResult {
  answer: Answer;
  title: string;
  updated_at: number | null;
  /** the chat's assistant has been deleted; this turn ran with the default one */
  assistant_missing?: boolean;
}

/** One Server-Sent Event of a streamed chat turn. */
export type ChatStreamEvent =
  | { type: "status"; stage: "retrieving" | "thinking" }
  | { type: "tool"; name: string; status: "start" | "done" | "error" }
  | { type: "delta"; text: string }
  | ({ type: "done" } & ChatAskResult)
  | { type: "error"; status: number; detail: string };

export interface IngestResult {
  document_id: string;
  data_class: string;
  /** ids of same-titled documents this upload replaced */
  replaced: string[];
}

/** Read a File/Blob into raw base64 (no data-URL prefix). */
export function toBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = reader.result as string;
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(
  token: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : `HTTP ${res.status}`;
    throw new ApiError(detail, res.status);
  }
  return data as T;
}

export const api = {
  health: () =>
    fetch("/health").then((r) => r.json()) as Promise<{
      status: string;
      model: string;
      languages: Language[];
      skill_load_errors: string[];
    }>,

  me: (token: string) => request<Me>(token, "/v1/me"),

  setLanguage: (token: string, language: Language) =>
    request<{ language: Language }>(token, "/v1/me/language", {
      method: "POST",
      body: JSON.stringify({ language }),
    }),

  skills: (token: string) =>
    request<{ skills: SkillInfo[] }>(token, "/v1/skills"),

  onboarding: (token: string) => request<Onboarding>(token, "/v1/onboarding"),

  code: {
    list: (token: string, status?: string) =>
      request<{ proposals: CodeProposal[] }>(
        token,
        `/v1/code/proposals${status ? `?status=${status}` : ""}`,
      ),
    get: (token: string, id: string) =>
      request<CodeProposal>(token, `/v1/code/proposals/${id}`),
    apply: (token: string, id: string) =>
      request<CodeProposal>(token, `/v1/code/proposals/${id}/apply`, {
        method: "POST",
      }),
    discard: (token: string, id: string) =>
      request<CodeProposal>(token, `/v1/code/proposals/${id}/discard`, {
        method: "POST",
      }),
  },

  ask: (
    token: string,
    query: string,
    assistantId?: string,
    attachments?: ChatAttachment[],
    language?: Language,
    /** lets the composer's stop button abandon an answer that is still coming */
    signal?: AbortSignal,
  ) =>
    request<Answer>(
      token,
      assistantId ? `/v1/assistants/${assistantId}/ask` : "/v1/ask",
      {
        method: "POST",
        signal,
        body: JSON.stringify({
          query,
          attachments: attachments ?? [],
          language: language ?? null,
        }),
      },
    ),

  assistants: {
    list: (token: string) =>
      request<{ assistants: Assistant[] }>(token, "/v1/assistants"),
    get: (token: string, id: string) =>
      request<Assistant>(token, `/v1/assistants/${id}`),
    create: (
      token: string,
      body: {
        name: string;
        instruction: string;
        allowed_skill_names: string[] | null;
        language?: Language;
      },
    ) => request<Assistant>(token, "/v1/assistants", {
      method: "POST",
      body: JSON.stringify({ language: "auto", ...body }),
    }),
    update: (token: string, id: string, body: AssistantUpdate) =>
      request<Assistant>(token, `/v1/assistants/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    remove: (token: string, id: string) =>
      request<{ deleted: string }>(token, `/v1/assistants/${id}`, {
        method: "DELETE",
      }),
  },

  documents: {
    list: (token: string) =>
      request<{ documents: DocumentSummary[] }>(token, "/v1/documents"),
    remove: (token: string, id: string) =>
      request<{ deleted: string; chunks: number }>(token, `/v1/documents/${id}`, {
        method: "DELETE",
      }),
    /** Advisory classification — nothing is stored by this call. */
    classify: (token: string, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<Classification>(token, "/v1/documents/classify", {
        method: "POST",
        body: fd,
      });
    },
  },

  sources: {
    /** Fetch the endpoint once and have it explained. Stores nothing. */
    probe: (
      token: string,
      body: { url: string; language?: string; comment?: string; previous?: PayloadAnalysis | null },
    ) => request<ProbeResult>(token, "/v1/sources/probe", {
      method: "POST",
      body: JSON.stringify(body),
    }),
    list: (token: string) => request<{ sources: DataSource[] }>(token, "/v1/sources"),
    create: (token: string, body: DataSourceInput) =>
      request<DataSource>(token, "/v1/sources", { method: "POST", body: JSON.stringify(body) }),
    get: (token: string, id: string) => request<DataSource>(token, `/v1/sources/${id}`),
    update: (token: string, id: string, body: Partial<DataSourceInput>) =>
      request<DataSource>(token, `/v1/sources/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    remove: (token: string, id: string) =>
      request<{ deleted: string }>(token, `/v1/sources/${id}`, { method: "DELETE" }),
    sync: (token: string, id: string) =>
      request<{ status: DataSource["last_status"]; records: number; error: string; source: DataSource }>(
        token,
        `/v1/sources/${id}/sync`,
        { method: "POST" },
      ),
  },

  databases: {
    test: (token: string, body: DbLogin) =>
      request<{ ok: boolean; tables: number; backend: string }>(token, "/v1/databases/test", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    connect: (
      token: string,
      body: DbLogin & {
        name: string;
        data_class: DataClass;
        required_roles: string[];
        free_query: boolean;
        knowledge: boolean;
        language: string;
        comment?: string;
      },
    ) => request<DbConnectResult>(token, "/v1/databases/connect", {
      method: "POST",
      body: JSON.stringify(body),
    }),
    upload: (
      token: string,
      file: File,
      fields: {
        name: string;
        data_class: DataClass;
        required_roles: string[];
        free_query: boolean;
        knowledge: boolean;
        language: string;
        comment?: string;
      },
    ) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", fields.name);
      fd.append("data_class", fields.data_class);
      fd.append("required_roles", fields.required_roles.join(","));
      fd.append("free_query", String(fields.free_query));
      fd.append("knowledge", String(fields.knowledge));
      fd.append("language", fields.language);
      fd.append("comment", fields.comment ?? "");
      return request<DbConnectResult>(token, "/v1/databases/upload", { method: "POST", body: fd });
    },
    schema: (token: string, id: string) => request<DbSchema>(token, `/v1/databases/${id}/schema`),
    describe: (token: string, id: string, body: { comment: string; language?: string }) =>
      request<DbConnectResult>(token, `/v1/databases/${id}/describe`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (
      token: string,
      id: string,
      body: {
        name?: string;
        free_query?: boolean;
        knowledge?: boolean;
        data_class?: DataClass;
        required_roles?: string[];
        description?: string;
      },
    ) => request<Connector>(token, `/v1/databases/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (token: string, id: string) =>
      request<{ deleted: string }>(token, `/v1/databases/${id}`, { method: "DELETE" }),
  },

  connectors: {
    list: (token: string) =>
      request<{ connectors: Connector[] }>(token, "/v1/connectors"),
    create: (
      token: string,
      body: {
        name: string;
        kind: ConnectorKind;
        config: Record<string, string>;
        row_limit?: number;
        timeout_s?: number;
      },
    ) => request<Connector>(token, "/v1/connectors", {
      method: "POST",
      body: JSON.stringify(body),
    }),
    remove: (token: string, id: string) =>
      request<{ deleted: string }>(token, `/v1/connectors/${id}`, {
        method: "DELETE",
      }),
  },

  skillDefs: {
    list: (token: string) =>
      request<{ skills: SkillDefinition[] }>(token, "/v1/skills/definitions"),
    create: (token: string, body: SkillDefinitionInput) =>
      request<SkillDefinition>(token, "/v1/skills/definitions", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (token: string, id: string, body: SkillDefinitionInput) =>
      request<SkillDefinition>(token, `/v1/skills/definitions/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    remove: (token: string, id: string) =>
      request<{ deleted: string }>(token, `/v1/skills/definitions/${id}`, {
        method: "DELETE",
      }),
    test: (token: string, id: string, args: Record<string, unknown>) =>
      request<SkillTestRun>(token, `/v1/skills/definitions/${id}/test`, {
        method: "POST",
        body: JSON.stringify({ arguments: args }),
      }),
    library: (token: string) =>
      request<{ skills: SkillDefinition[] }>(token, "/v1/skills/library"),
    /** A procedure carries no data path, so it copies without a connector. */
    import: (token: string, id: string, connectorId = "", name?: string) =>
      request<SkillDefinition>(token, `/v1/skills/library/${id}/import`, {
        method: "POST",
        body: JSON.stringify({ connector_id: connectorId, name: name ?? null }),
      }),
    /** The stored procedure as a real SKILL.md, portable out of KARAG. */
    skillMd: (token: string, id: string) =>
      request<string>(token, `/v1/skills/definitions/${id}/skill_md`),
    /** Split a pasted SKILL.md into fields. Parses only — stores nothing. */
    parseSkillMd: (token: string, text: string) =>
      request<{ name: string; description: string; instructions: string }>(
        token,
        "/v1/skills/parse_skill_md",
        { method: "POST", body: JSON.stringify({ text }) },
      ),
  },

  alerts: {
    list: (token: string) => request<{ alerts: AlertRule[] }>(token, "/v1/alerts"),
    create: (
      token: string,
      body: {
        name: string;
        skill_name: string;
        arguments?: Record<string, unknown>;
        interval_s: number;
        condition: AlertRule["condition"];
        condition_config?: Record<string, unknown>;
        message_template?: string;
        channel?: string;
      },
    ) => request<AlertRule>(token, "/v1/alerts", {
      method: "POST",
      body: JSON.stringify(body),
    }),
    setEnabled: (token: string, id: string, enabled: boolean) =>
      request<AlertRule>(token, `/v1/alerts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),
    remove: (token: string, id: string) =>
      request<{ deleted: string }>(token, `/v1/alerts/${id}`, {
        method: "DELETE",
      }),
    run: (token: string, id: string) =>
      request<{ ran: boolean; fired: boolean; error: string; message: string }>(
        token,
        `/v1/alerts/${id}/run`,
        { method: "POST" },
      ),
  },

  tenants: {
    list: (token: string) => request<{ tenants: Tenant[] }>(token, "/v1/tenants"),
    create: (
      token: string,
      body: { id: string; name: string; default_language?: Language },
    ) => request<Tenant>(token, "/v1/tenants", {
      method: "POST",
      body: JSON.stringify(body),
    }),
    setActive: (token: string, id: string, active: boolean) =>
      request<{ id: string; active: boolean }>(token, `/v1/tenants/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ active }),
      }),
  },

  accounts: {
    list: (token: string) =>
      request<{ accounts: Account[] }>(token, "/v1/accounts"),
    /** The token comes back exactly once — only its hash is stored. */
    create: (
      token: string,
      body: {
        user_id: string;
        display_name?: string;
        roles: string[];
        language?: Language;
      },
    ) => request<{ account: Account; token: string }>(token, "/v1/accounts", {
      method: "POST",
      body: JSON.stringify(body),
    }),
    setActive: (token: string, id: string, active: boolean) =>
      request<Account>(token, `/v1/accounts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ active }),
      }),
    rotate: (token: string, id: string) =>
      request<{ user_id: string; token: string }>(
        token,
        `/v1/accounts/${id}/rotate`,
        { method: "POST" },
      ),
    remove: (token: string, id: string) =>
      request<{ deleted: string }>(token, `/v1/accounts/${id}`, {
        method: "DELETE",
      }),
  },

  ingestText: (
    token: string,
    body: { title: string; text: string; data_class: string },
  ) =>
    request<IngestResult>(token, "/v1/ingest", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  ingestFile: (token: string, file: File, dataClass: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("data_class", dataClass);
    return request<IngestResult>(token, "/v1/ingest/file", {
      method: "POST",
      body: fd,
    });
  },

  chats: {
    list: (token: string) =>
      request<{ chats: ChatSummary[] }>(token, "/v1/chats"),
    create: (
      token: string,
      body: { title?: string; assistant_id?: string | null } = {},
    ) =>
      request<ChatDetail>(token, "/v1/chats", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    get: (token: string, id: string) =>
      request<ChatDetail>(token, `/v1/chats/${id}`),
    rename: (token: string, id: string, title: string) =>
      request<ChatDetail>(token, `/v1/chats/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      }),
    remove: (token: string, id: string) =>
      request<{ deleted: string }>(token, `/v1/chats/${id}`, {
        method: "DELETE",
      }),
    ask: (
      token: string,
      id: string,
      query: string,
      attachments?: ChatAttachment[],
      language?: Language,
      signal?: AbortSignal,
    ) =>
      request<ChatAskResult>(token, `/v1/chats/${id}/ask`, {
        method: "POST",
        signal,
        body: JSON.stringify({
          query,
          attachments: attachments ?? [],
          language: language ?? null,
        }),
      }),
    /** The same turn as `ask`, but the answer arrives as it is written.
        Aborting the signal closes the connection, which stops the turn on
        the server too. */
    stream: (
      token: string,
      id: string,
      query: string,
      attachments?: ChatAttachment[],
      signal?: AbortSignal,
    ) =>
      streamEvents(token, `/v1/chats/${id}/stream`, {
        query,
        attachments: attachments ?? [],
      }, signal),
  },

  audit: (token: string) =>
    request<{ events: AuditEvent[] }>(token, "/v1/audit"),

  usage: (token: string) => request<UsageTotals>(token, "/v1/usage"),
};

/** POST a JSON body and read the response as Server-Sent Events. */
async function* streamEvents(
  token: string,
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(path, {
    method: "POST",
    signal,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (data && typeof data === "object" && "detail" in data)
        detail = String((data as { detail: unknown }).detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut = buffer.indexOf("\n\n");
      while (cut !== -1) {
        const frame = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        for (const line of frame.split("\n")) {
          if (line.startsWith("data: ")) {
            yield JSON.parse(line.slice(6)) as ChatStreamEvent;
          }
        }
        cut = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** Trigger a browser download for a base64-encoded artifact. */
export function downloadArtifact(a: ArtifactPayload): void {
  if (!a.content_base64) return; // reloaded from history — bytes not persisted
  const bytes = atob(a.content_base64);
  const buf = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([buf], { type: a.mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = a.filename;
  link.click();
  URL.revokeObjectURL(url);
}
