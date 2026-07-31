"use client";

/* Skill authoring — §5's core promise made real: a technical specialist builds
   a verified, parameterised query once, tests it here, and everyone uses it.
   Three panes: data connections · the skill editor · the test run. */

import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Globe,
  Library,
  Play,
  Plus,
  Share2,
  Trash2,
  Wrench,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type Connector,
  type ConnectorKind,
  type DataClass,
  type SkillDefinition,
  type SkillDefinitionInput,
  type SkillTestRun,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Button,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  Input,
  Label,
  Picker,
  Rise,
  Textarea,
} from "@/components/ui";
import { AssistantsSkeleton } from "@/components/skeleton";

const DATA_CLASSES: { value: DataClass; label: string; hint: string }[] = [
  { value: "public", label: "Public", hint: "Anyone in the tenant" },
  { value: "operational", label: "Operational", hint: "Day-to-day business data" },
  { value: "hr", label: "HR", hint: "People data — never visible to finance" },
  { value: "financial", label: "Financial", hint: "Never visible to HR" },
  { value: "regulated", label: "Regulated", hint: "SOP / GxP / controlled" },
];

const CONNECTOR_KINDS: { value: ConnectorKind; label: string; hint: string }[] = [
  { value: "sql_sqlite", label: "SQLite file", hint: "Read-only file path" },
  { value: "sql_postgres", label: "PostgreSQL", hint: "Read replica DSN" },
  { value: "rest", label: "REST API", hint: "Company-exposed read-only endpoint" },
];

const ROLES = ["employee", "hr", "finance", "legal", "qa", "ceo", "admin"];

const BLANK: SkillDefinitionInput = {
  name: "",
  description: "",
  kind: "sql",
  connector_id: "",
  param_schema: null,
  sql: "",
  path: "",
  required_data_class: "operational",
  required_roles: [],
  row_limit: null,
  shared: false,
};

/** Declared parameters, edited as rows rather than raw JSON schema. */
interface ParamRow {
  name: string;
  type: "string" | "integer" | "number" | "boolean";
  description: string;
  required: boolean;
}

function toSchema(rows: ParamRow[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  for (const r of rows) {
    if (!r.name.trim()) continue;
    properties[r.name.trim()] = {
      type: r.type,
      ...(r.description ? { description: r.description } : {}),
    };
    if (r.required) required.push(r.name.trim());
  }
  // additionalProperties:false is required by the backend — an open schema
  // would let a model smuggle extra bindings into the query.
  return { type: "object", properties, required, additionalProperties: false };
}

function fromSchema(schema: Record<string, unknown>): ParamRow[] {
  const props = (schema?.properties ?? {}) as Record<
    string,
    { type?: string; description?: string }
  >;
  const required = new Set((schema?.required ?? []) as string[]);
  return Object.entries(props).map(([name, spec]) => ({
    name,
    type: (spec.type as ParamRow["type"]) ?? "string",
    description: spec.description ?? "",
    required: required.has(name),
  }));
}

export default function SkillsPage() {
  const { token, me } = useAuth();
  const [loading, setLoading] = useState(true);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [library, setLibrary] = useState<SkillDefinition[]>([]);
  const [error, setError] = useState("");

  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<SkillDefinitionInput>(BLANK);
  const [params, setParams] = useState<ParamRow[]>([]);
  const [saving, setSaving] = useState(false);

  const [testArgs, setTestArgs] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState(false);
  const [run, setRun] = useState<SkillTestRun | null>(null);

  const [showConnector, setShowConnector] = useState(false);

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      const [c, s, l] = await Promise.all([
        api.connectors.list(token),
        api.skillDefs.list(token),
        api.skillDefs.library(token),
      ]);
      setConnectors(c.connectors);
      setSkills(s.skills);
      setLibrary(l.skills);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the catalogue");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectSkill = (s: SkillDefinition) => {
    setSelected(s.id);
    setDraft({
      name: s.name,
      description: s.description,
      kind: s.kind,
      connector_id: s.connector_id,
      param_schema: s.param_schema,
      sql: s.sql,
      path: s.path,
      required_data_class: s.required_data_class,
      required_roles: s.required_roles,
      row_limit: s.row_limit,
      shared: s.shared,
    });
    setParams(fromSchema(s.param_schema));
    setTestArgs({});
    setRun(null);
    setError("");
  };

  const startNew = () => {
    setSelected(null);
    setDraft({ ...BLANK, connector_id: connectors[0]?.id ?? "" });
    setParams([]);
    setTestArgs({});
    setRun(null);
    setError("");
  };

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const body: SkillDefinitionInput = { ...draft, param_schema: toSchema(params) };
      const saved = selected
        ? await api.skillDefs.update(token, selected, body)
        : await api.skillDefs.create(token, body);
      await refresh();
      selectSkill(saved);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the skill");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    await api.skillDefs.remove(token, id).catch(() => {});
    if (selected === id) startNew();
    void refresh();
  };

  const runTest = async () => {
    if (!selected) return;
    setTesting(true);
    try {
      // params are typed; the editor collects strings, so coerce on the way out
      const args: Record<string, unknown> = {};
      for (const row of params) {
        const raw = testArgs[row.name];
        if (raw === undefined || raw === "") continue;
        args[row.name] =
          row.type === "integer" ? parseInt(raw, 10)
          : row.type === "number" ? Number(raw)
          : row.type === "boolean" ? raw === "true"
          : raw;
      }
      setRun(await api.skillDefs.test(token, selected, args));
    } catch (e) {
      setRun({
        ok: false,
        query_shown: "",
        data: null,
        error: e instanceof ApiError ? e.message : "Test failed",
        row_count: null,
      });
    } finally {
      setTesting(false);
    }
  };

  const importFromLibrary = async (id: string) => {
    if (!connectors.length) {
      setError("Register a data connection first — an imported skill binds yours.");
      return;
    }
    try {
      const copy = await api.skillDefs.import(token, id, connectors[0].id);
      await refresh();
      selectSkill(copy);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not import");
    }
  };

  const connectorLabel = useMemo(() => {
    const byId = new Map(connectors.map((c) => [c.id, c.name]));
    return (id: string) => byId.get(id) ?? "—";
  }, [connectors]);

  if (me && !me.can_author_skills) {
    return (
      <EmptyState
        icon={<Wrench className="size-6" />}
        title="Skill authoring is restricted"
        hint="Building data connections and skills needs an admin or skill_author role. Ask your administrator if you need access."
      />
    );
  }

  if (loading) return <AssistantsSkeleton />;

  return (
    <div className="flex flex-col gap-6">
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="flex items-start gap-2.5 rounded-xl border border-bad/30 bg-bad-soft px-4 py-3 text-[13.5px] text-bad"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)_360px]">
        {/* ---- connections + skill list ---- */}
        <div className="flex flex-col gap-5">
          <Card>
            <CardHeader
              title="Data connections"
              sub="Read-only, always"
              icon={<Database className="size-4" />}
              right={
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowConnector((s) => !s)}
                >
                  <Plus className="size-3.5" />
                </Button>
              }
            />
            <div className="flex flex-col gap-1.5 p-3.5 pt-0">
              {connectors.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2.5"
                >
                  <div className="min-w-0">
                    <p className="truncate text-[13.5px] font-semibold">{c.name}</p>
                    <p className="text-[11.5px] text-mut">
                      {c.kind === "rest" ? "REST" : c.kind === "sql_postgres" ? "PostgreSQL" : "SQLite"}
                      {" · "}
                      {c.row_limit} rows · {c.timeout_s}s
                    </p>
                  </div>
                  <button
                    onClick={() =>
                      api.connectors
                        .remove(token, c.id)
                        .then(refresh)
                        .catch((e) =>
                          setError(e instanceof ApiError ? e.message : "Could not delete"),
                        )
                    }
                    title="Remove connection"
                    className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              ))}
              {!connectors.length && !showConnector && (
                <p className="px-1 py-2 text-[13px] text-mut">
                  No data sources yet. A skill needs one.
                </p>
              )}
              <AnimatePresence>
                {showConnector && (
                  <ConnectorForm
                    onCancel={() => setShowConnector(false)}
                    onCreated={() => {
                      setShowConnector(false);
                      void refresh();
                    }}
                  />
                )}
              </AnimatePresence>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Skills"
              sub={`${skills.length} defined`}
              icon={<Wrench className="size-4" />}
              right={
                <Button size="sm" variant="soft" onClick={startNew}>
                  <Plus className="size-3.5" /> New
                </Button>
              }
            />
            <div className="flex flex-col gap-1.5 p-3.5 pt-0">
              {skills.map((s, i) => (
                <Rise key={s.id} delay={i * 0.03}>
                  <button
                    onClick={() => selectSkill(s)}
                    className={`flex w-full cursor-pointer flex-col gap-1 rounded-xl border px-3 py-2.5 text-left transition-colors ${
                      selected === s.id
                        ? "border-accent bg-accent-soft"
                        : "border-line hover:border-line-strong"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="truncate font-mono text-[13px] font-semibold">
                        {s.name}
                      </span>
                      {s.shared && <Share2 className="size-3 shrink-0 text-accent" />}
                    </span>
                    <span className="truncate text-[11.5px] text-mut">
                      {s.required_data_class} · {connectorLabel(s.connector_id)}
                    </span>
                  </button>
                </Rise>
              ))}
              {!skills.length && (
                <p className="px-1 py-2 text-[13px] text-mut">
                  No skills yet. Managers&apos; questions resolve to skills, not
                  improvised SQL.
                </p>
              )}
            </div>
          </Card>

          {library.length > 0 && (
            <Card>
              <CardHeader
                title="Skill library"
                sub="Shared by other companies"
                icon={<Library className="size-4" />}
              />
              <div className="flex flex-col gap-1.5 p-3.5 pt-0">
                {library.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-mono text-[13px] font-semibold">
                        {s.name}
                      </p>
                      <p className="truncate text-[11.5px] text-mut">{s.description}</p>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => importFromLibrary(s.id)}
                    >
                      Import
                    </Button>
                  </div>
                ))}
                <p className="px-1 pt-1 text-[11.5px] text-faint">
                  Importing copies the query only — it binds your own connection,
                  so no data crosses companies.
                </p>
              </div>
            </Card>
          )}
        </div>

        {/* ---- editor ---- */}
        <Card>
          <CardHeader
            title={selected ? "Edit skill" : "New skill"}
            sub="A human writes and verifies the query once"
            icon={<Wrench className="size-4" />}
            right={
              selected ? (
                <Button size="sm" variant="danger" onClick={() => remove(selected)}>
                  <Trash2 className="size-3.5" /> Delete
                </Button>
              ) : undefined
            }
          />
          <div className="p-5 pt-0">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label>Name</Label>
                <Input
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder="sales_by_store"
                  className="font-mono"
                />
                <p className="mt-1.5 text-[11.5px] text-faint">
                  snake_case — this is the tool name the model sees.
                </p>
              </div>
              <div>
                <Label>Data source</Label>
                <Picker
                  value={draft.connector_id}
                  onChange={(v) => setDraft({ ...draft, connector_id: v })}
                  options={connectors.map((c) => ({
                    value: c.id,
                    label: c.name,
                    hint: c.kind,
                  }))}
                  placeholder="Choose a connection…"
                  ariaLabel="Data source"
                />
              </div>
            </div>

            <Label>Description</Label>
            <Input
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              placeholder="Total sales for a store on a given date."
            />
            <p className="mt-1.5 text-[11.5px] text-faint">
              The model picks a skill by its description — be precise.
            </p>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label>Kind</Label>
                <Picker
                  value={draft.kind}
                  onChange={(v) => setDraft({ ...draft, kind: v as "sql" | "rest" })}
                  options={[
                    { value: "sql", label: "SQL on a view", hint: "SELECT / WITH only" },
                    { value: "rest", label: "REST endpoint", hint: "GET, fixed path" },
                  ]}
                  ariaLabel="Skill kind"
                />
              </div>
              <div>
                <Label>Requires clearance</Label>
                <Picker
                  value={draft.required_data_class}
                  onChange={(v) =>
                    setDraft({ ...draft, required_data_class: v as DataClass })
                  }
                  options={DATA_CLASSES}
                  ariaLabel="Data class"
                />
              </div>
            </div>

            {draft.kind === "sql" ? (
              <>
                <Label>Query</Label>
                <Textarea
                  value={draft.sql}
                  onChange={(e) => setDraft({ ...draft, sql: e.target.value })}
                  placeholder={
                    "SELECT SUM(amount) AS total\nFROM sales_view\nWHERE tenant = :tenant_id AND store_id = :store_id"
                  }
                  className="min-h-36 font-mono text-[13px]"
                  spellCheck={false}
                />
                <p className="mt-1.5 text-[11.5px] text-faint">
                  Read-only, single statement. <code>:tenant_id</code> is bound by
                  the platform — never declare it as a parameter.
                </p>
              </>
            ) : (
              <>
                <Label>Endpoint path</Label>
                <Input
                  value={draft.path}
                  onChange={(e) => setDraft({ ...draft, path: e.target.value })}
                  placeholder="/reports/sales"
                  className="font-mono"
                />
                <p className="mt-1.5 text-[11.5px] text-faint">
                  Relative to the connection&apos;s base URL. The model supplies
                  query parameters, never the path.
                </p>
              </>
            )}

            <div className="mt-4 flex items-center justify-between">
              <Label>Parameters</Label>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setParams([
                    ...params,
                    { name: "", type: "string", description: "", required: true },
                  ])
                }
              >
                <Plus className="size-3.5" /> Add
              </Button>
            </div>
            <div className="flex flex-col gap-2">
              {params.map((row, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    value={row.name}
                    onChange={(e) => {
                      const next = [...params];
                      next[i] = { ...row, name: e.target.value };
                      setParams(next);
                    }}
                    placeholder="store_id"
                    className="font-mono"
                  />
                  <Picker
                    value={row.type}
                    onChange={(v) => {
                      const next = [...params];
                      next[i] = { ...row, type: v as ParamRow["type"] };
                      setParams(next);
                    }}
                    options={[
                      { value: "string", label: "string" },
                      { value: "integer", label: "integer" },
                      { value: "number", label: "number" },
                      { value: "boolean", label: "boolean" },
                    ]}
                    className="w-36 shrink-0"
                    ariaLabel="Parameter type"
                  />
                  <button
                    onClick={() => setParams(params.filter((_, j) => j !== i))}
                    className="grid size-9 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                    title="Remove parameter"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              ))}
              {!params.length && (
                <p className="text-[13px] text-mut">
                  No parameters — the query runs as written.
                </p>
              )}
            </div>

            <Label>Roles allowed to use it</Label>
            <div className="flex flex-wrap gap-2">
              {ROLES.map((role) => {
                const on = draft.required_roles.includes(role);
                return (
                  <button
                    key={role}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        required_roles: on
                          ? draft.required_roles.filter((r) => r !== role)
                          : [...draft.required_roles, role],
                      })
                    }
                    className={`cursor-pointer rounded-full border px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
                      on
                        ? "border-accent bg-accent-soft text-accent-strong"
                        : "border-line text-mut hover:border-line-strong hover:text-ink"
                    }`}
                  >
                    {role}
                  </button>
                );
              })}
            </div>
            <p className="mt-1.5 text-[11.5px] text-faint">
              Empty means any authenticated user who also holds the data-class
              clearance above.
            </p>

            <label className="mt-4 flex cursor-pointer items-start gap-2.5 rounded-xl border border-line p-3.5">
              <input
                type="checkbox"
                checked={draft.shared}
                onChange={(e) => setDraft({ ...draft, shared: e.target.checked })}
                className="mt-0.5 size-4 accent-[var(--accent-2)]"
              />
              <span>
                <span className="block text-[13.5px] font-semibold">
                  Publish to the group skill library
                </span>
                <span className="block text-[11.5px] text-mut">
                  Other companies can copy the query — bound to their own data
                  source, never yours.
                </span>
              </span>
            </label>

            <div className="mt-5 flex items-center gap-2.5">
              <Button
                onClick={save}
                busy={saving}
                disabled={!draft.name || !draft.description || !draft.connector_id}
              >
                {selected ? "Save changes" : "Create skill"}
              </Button>
              {selected && (
                <span className="text-[12.5px] text-mut">
                  Live for cleared users as soon as it saves.
                </span>
              )}
            </div>
          </div>
        </Card>

        {/* ---- test run ---- */}
        <Card>
          <CardHeader
            title="Test run"
            sub="Verify before anyone relies on it"
            icon={<Play className="size-4" />}
          />
          <div className="p-5 pt-0">
            {!selected ? (
              <p className="text-[13.5px] text-mut">
                Save the skill first, then try it here with real arguments. §5:
                a skill is trusted because a human tested it.
              </p>
            ) : (
              <>
                {params.map((row) => (
                  <div key={row.name}>
                    <Label>{row.name || "unnamed"}</Label>
                    <Input
                      value={testArgs[row.name] ?? ""}
                      onChange={(e) =>
                        setTestArgs({ ...testArgs, [row.name]: e.target.value })
                      }
                      placeholder={row.type}
                    />
                  </div>
                ))}
                <Button
                  onClick={runTest}
                  busy={testing}
                  variant="soft"
                  className="mt-4 w-full"
                >
                  <Play className="size-4" /> Run
                </Button>

                <AnimatePresence mode="wait">
                  {run && (
                    <motion.div
                      key={run.ok ? "ok" : "err"}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      className="mt-4 flex flex-col gap-3"
                    >
                      <div className="flex items-center gap-2">
                        {run.ok ? (
                          <Chip tone="good">
                            <CheckCircle2 className="size-3" />
                            {run.row_count ?? 0} row(s)
                          </Chip>
                        ) : (
                          <Chip tone="bad">
                            <AlertTriangle className="size-3" /> Failed
                          </Chip>
                        )}
                      </div>

                      {run.error && (
                        <p className="rounded-xl bg-bad-soft px-3.5 py-2.5 text-[12.5px] text-bad">
                          {run.error}
                        </p>
                      )}

                      {run.query_shown && (
                        <div>
                          <Label>Executed query</Label>
                          <pre className="overflow-x-auto rounded-xl bg-surface-2 p-3 font-mono text-[11.5px] leading-relaxed">
                            {run.query_shown}
                          </pre>
                        </div>
                      )}

                      {run.ok && (
                        <div>
                          <Label>Result</Label>
                          <pre className="max-h-72 overflow-auto rounded-xl bg-surface-2 p-3 font-mono text-[11.5px] leading-relaxed">
                            {JSON.stringify(run.data, null, 2)}
                          </pre>
                        </div>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ---------------- connector form ---------------- */

function ConnectorForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: () => void;
}) {
  const { token } = useAuth();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<ConnectorKind>("sql_sqlite");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const field = kind === "rest" ? "base_url" : kind === "sql_postgres" ? "dsn" : "path";
  const placeholder =
    kind === "rest"
      ? "https://erp.example.com/api"
      : kind === "sql_postgres"
        ? "env:SALES_REPLICA_DSN"
        : "/srv/replicas/sales.db";

  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      await api.connectors.create(token, {
        name,
        kind,
        config: { [field]: secret },
      });
      onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not create the connection");
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className="overflow-hidden"
    >
      <div className="mt-1 rounded-xl border border-line p-3.5">
        <Label>Name</Label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Sales read replica"
        />
        <Label>Kind</Label>
        <Picker
          value={kind}
          onChange={(v) => setKind(v as ConnectorKind)}
          options={CONNECTOR_KINDS}
          ariaLabel="Connector kind"
        />
        <Label>{kind === "rest" ? "Base URL" : kind === "sql_postgres" ? "DSN" : "File path"}</Label>
        <Input
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          placeholder={placeholder}
          className="font-mono text-[13px]"
        />
        <p className="mt-1.5 flex items-start gap-1.5 text-[11.5px] text-faint">
          <Globe className="mt-0.5 size-3 shrink-0" />
          Prefix with <code className="mx-1">env:</code> to keep the real value in
          the server environment — only the pointer is stored.
        </p>
        {err && <p className="mt-2 text-[12.5px] text-bad">{err}</p>}
        <div className="mt-3.5 flex gap-2">
          <Button size="sm" onClick={submit} busy={busy} disabled={!name || !secret}>
            Create
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </div>
    </motion.div>
  );
}
