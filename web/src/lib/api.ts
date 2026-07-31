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
  plane: "knowledge" | "data" | "mixed" | "refusal";
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
  allowed_skill_names: string[] | null;
  language: Language;
}

/* ---------- language (§2: RU / TJ are the moat) ---------- */

export type Language = "auto" | "ru" | "tg" | "en";

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

export type ConnectorKind = "sql_sqlite" | "sql_postgres" | "rest";

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
}

export interface SkillDefinition {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  kind: "sql" | "rest";
  connector_id: string;
  param_schema: Record<string, unknown>;
  sql: string;
  path: string;
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
  kind: "sql" | "rest";
  connector_id: string;
  param_schema: Record<string, unknown> | null;
  sql: string;
  path: string;
  required_data_class: DataClass;
  required_roles: string[];
  row_limit: number | null;
  shared: boolean;
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

  ask: (
    token: string,
    query: string,
    assistantId?: string,
    attachments?: ChatAttachment[],
    language?: Language,
  ) =>
    request<Answer>(
      token,
      assistantId ? `/v1/assistants/${assistantId}/ask` : "/v1/ask",
      {
        method: "POST",
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
    update: (
      token: string,
      id: string,
      body: {
        name: string;
        instruction: string;
        allowed_skill_names: string[] | null;
        language?: Language;
      },
    ) => request<Assistant>(token, `/v1/assistants/${id}`, {
      method: "PUT",
      body: JSON.stringify({ language: "auto", ...body }),
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
    import: (token: string, id: string, connectorId: string, name?: string) =>
      request<SkillDefinition>(token, `/v1/skills/library/${id}/import`, {
        method: "POST",
        body: JSON.stringify({ connector_id: connectorId, name: name ?? null }),
      }),
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
    request<{ document_id: string; data_class: string }>(token, "/v1/ingest", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  ingestFile: (token: string, file: File, dataClass: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("data_class", dataClass);
    return request<{ document_id: string; data_class: string }>(
      token,
      "/v1/ingest/file",
      { method: "POST", body: fd },
    );
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
    ) =>
      request<ChatAskResult>(token, `/v1/chats/${id}/ask`, {
        method: "POST",
        body: JSON.stringify({
          query,
          attachments: attachments ?? [],
          language: language ?? null,
        }),
      }),
  },

  audit: (token: string) =>
    request<{ events: AuditEvent[] }>(token, "/v1/audit"),

  usage: (token: string) => request<UsageTotals>(token, "/v1/usage"),
};

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
