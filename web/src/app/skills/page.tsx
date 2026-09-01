"use client";

/* Skills — the two ways to make the assistant better at your work.
 *
 * A **procedure** is an Agent Skill: a SKILL.md holding how your company does
 * something, disclosed progressively so holding many of them is cheap. A
 * **lookup** is the verified data plane: parameterised, read-only, bound to a
 * connection you control, so a figure is fetched rather than guessed.
 *
 * They are genuinely different objects and the page says so rather than
 * flattening them into one form. Writing a procedure is a document editor with
 * the file previewed live; building a lookup stays a stepped flow that admits
 * which step needs someone who knows the database. Neither is published on a
 * promise — both end at a panel showing what actually came back. */

import {
  ArrowRight,
  BookOpenCheck,
  Check,
  Copy,
  Database,
  Play,
  Plus,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useMemo, useState } from "react";
import {
  api,
  type ApiError,
  type Connector,
  type ConnectorKind,
  type DataClass,
  type SkillDefinition,
  type SkillDefinitionInput,
  type SkillTestRun,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AUDIENCES, audience, errorWords, roleLabel } from "@/lib/words";
import { isProcedure } from "@/lib/skills";
import { useLoad } from "@/lib/use-load";
import { Button, Input, Picker, Textarea } from "@/components/ui";
import {
  ConfirmAction,
  EASE,
  Empty,
  Notice,
  PageHero,
  Restricted,
  Segmented,
  Stagger,
  StaggerItem,
  Step,
  Steps,
} from "@/components/pro";
import { ProcedureBuilder } from "@/components/procedure-builder";
import { AssistantsSkeleton } from "@/components/skeleton";

const SOURCE_KINDS: { value: ConnectorKind; label: string; hint: string }[] = [
  { value: "sql_sqlite", label: "A database file", hint: "SQLite file on the server" },
  { value: "sql_postgres", label: "A company database", hint: "PostgreSQL, read-only copy" },
  { value: "rest", label: "An internal web service", hint: "A read-only address your systems expose" },
];

const BLANK: SkillDefinitionInput = {
  name: "",
  description: "",
  kind: "sql",
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

type Tab = "procedures" | "yours" | "ready" | "sources";

export default function SkillsPage() {
  const { token, me } = useAuth();

  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("procedures");
  const [sources, setSources] = useState<Connector[]>([]);
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [library, setLibrary] = useState<SkillDefinition[]>([]);
  const [problem, setProblem] = useState("");

  const [editing, setEditing] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [draft, setDraft] = useState<SkillDefinitionInput>(BLANK);
  const [params, setParams] = useState<ParamRow[]>([]);
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState("");

  const [testArgs, setTestArgs] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState(false);
  const [run, setRun] = useState<SkillTestRun | null>(null);

  const [addingSource, setAddingSource] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [c, s, l] = await Promise.all([
        api.connectors.list(token),
        api.skillDefs.list(token),
        api.skillDefs.library(token).catch(() => ({ skills: [] })),
      ]);
      setSources(c.connectors);
      setSkills(s.skills);
      setLibrary(l.skills.filter((x) => x.tenant_id !== me?.tenant_id));
      setProblem("");
    } catch (e) {
      setProblem(errorWords((e as ApiError).message));
    } finally {
      setLoading(false);
    }
  }, [token, me?.tenant_id]);

  useLoad(load);

  const procedures = useMemo(() => skills.filter(isProcedure), [skills]);
  const lookups = useMemo(() => skills.filter((s) => !isProcedure(s)), [skills]);

  function startNew(kind: SkillDefinitionInput["kind"]) {
    setEditing(null);
    setBuilding(true);
    setDraft(
      kind === "agent"
        ? { ...BLANK, kind: "agent" }
        : { ...BLANK, connector_id: sources[0]?.id ?? "" },
    );
    setParams([]);
    setRun(null);
    setStep(0);
    setSaved("");
    setProblem("");
    setTab(kind === "agent" ? "procedures" : "yours");
  }

  function open(s: SkillDefinition) {
    setEditing(s.id);
    setBuilding(true);
    setDraft({
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
    });
    setParams(fromSchema(s.param_schema));
    setRun(null);
    setStep(0);
    setSaved("");
    setProblem("");
  }

  async function removeSkill() {
    if (!editing) return;
    await api.skillDefs.remove(token, editing).catch(() => {});
    setBuilding(false);
    setEditing(null);
    void load();
  }

  async function save() {
    setSaving(true);
    setProblem("");
    setSaved("");
    const body: SkillDefinitionInput = {
      ...draft,
      param_schema: params.length ? toSchema(params) : null,
    };
    try {
      const s = editing
        ? await api.skillDefs.update(token, editing, body)
        : await api.skillDefs.create(token, body);
      setEditing(s.id);
      setSaved(
        `“${s.name}” is live — the assistant can use it from the next question on.`,
      );
      await load();
    } catch (e) {
      setProblem(errorWords((e as ApiError).message));
    } finally {
      setSaving(false);
    }
  }

  async function tryIt() {
    if (!editing) return;
    setTesting(true);
    setRun(null);
    try {
      const args: Record<string, unknown> = {};
      for (const p of params) {
        const raw = testArgs[p.name];
        if (raw === undefined || raw === "") continue;
        args[p.name] =
          p.type === "integer" || p.type === "number" ? Number(raw) : raw;
      }
      setRun(await api.skillDefs.test(token, editing, args));
    } catch (e) {
      setRun({
        ok: false,
        query_shown: "",
        data: null,
        error: errorWords((e as ApiError).message),
        row_count: null,
      });
    } finally {
      setTesting(false);
    }
  }

  if (me && !me.can_author_skills) {
    return (
      <Stagger>
        <StaggerItem>
          <Restricted
            what="Only administrators write skills"
            who="A skill changes how the assistant works for everyone at your company — and a lookup reads straight from a company system — so writing one is limited to administrators. You can still use every skill someone has already published: just ask your question in chat and the assistant reaches for the right one."
            yourRole={me.roles.map(roleLabel).join(", ")}
          />
        </StaggerItem>
      </Stagger>
    );
  }

  if (loading) return <AssistantsSkeleton />;

  return (
    <Stagger className="flex flex-col gap-6">
      <PageHero
        eyebrow="Skills"
        title="Teach it your work, once"
        lead="Two kinds. A procedure is how your company does something, written down once and followed the same way every time. A lookup fetches today's real figure from a system you connect, so the assistant never invents a number. Both go live the moment you publish."
        actions={
          <>
            <Button variant="cta" onClick={() => startNew("agent")}>
              <BookOpenCheck className="size-4" />
              Write a procedure
            </Button>
            {sources.length > 0 && (
              <Button variant="ghost" onClick={() => startNew("sql")}>
                <Plus className="size-4" />
                New lookup
              </Button>
            )}
            <Button
              variant="ghost"
              onClick={() => {
                setTab("sources");
                setAddingSource(true);
              }}
            >
              <Database className="size-4" />
              Connect data
            </Button>
          </>
        }
      />

      {problem && (
        <StaggerItem>
          <Notice tone="bad">{problem}</Notice>
        </StaggerItem>
      )}

      <StaggerItem>
        <Segmented
          value={tab}
          onChange={setTab}
          ariaLabel="What to show"
          options={[
            { value: "procedures", label: "Procedures", count: procedures.length },
            { value: "yours", label: "Lookups", count: lookups.length },
            { value: "ready", label: "Shared with you", count: library.length },
            { value: "sources", label: "Connected data", count: sources.length },
          ]}
        />
      </StaggerItem>

      {/* ---------------- procedures ---------------- */}
      {tab === "procedures" && (
        <StaggerItem>
          {building && draft.kind === "agent" ? (
            <ProcedureBuilder
              draft={draft}
              setDraft={setDraft}
              editing={editing}
              saving={saving}
              saved={saved}
              onSave={save}
              onDelete={editing ? removeSkill : undefined}
              onClose={() => {
                setBuilding(false);
                setEditing(null);
              }}
            />
          ) : procedures.length === 0 ? (
            <div className="rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
              <Empty
                icon={<BookOpenCheck className="size-6" />}
                title="No procedures yet"
                hint="Think of the thing you explain to every new joiner — how a weekly report is put together, what happens when a customer asks for a refund. Write it down once here and the assistant follows it from then on."
                action={
                  <Button variant="cta" onClick={() => startNew("agent")}>
                    <Plus className="size-4" /> Write your first one
                  </Button>
                }
              />
            </div>
          ) : (
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {procedures.map((s) => (
                <li key={s.id}>
                  <motion.button
                    layout
                    whileHover={{ y: -2 }}
                    onClick={() => open(s)}
                    className="flex h-full w-full cursor-pointer flex-col items-start gap-2 rounded-2xl border border-line bg-surface p-4 text-left transition-colors hover:border-accent/50 [box-shadow:var(--shadow-sm)]"
                  >
                    <span className="flex w-full items-center gap-2">
                      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                        <BookOpenCheck className="size-4" />
                      </span>
                      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-mut">
                        {s.name}
                      </span>
                      {s.shared && (
                        <span className="shrink-0 rounded-md bg-surface-2 px-1.5 py-0.5 text-[10.5px] font-semibold text-mut">
                          shared
                        </span>
                      )}
                    </span>
                    <span className="line-clamp-3 text-[13px] leading-relaxed">
                      {s.description}
                    </span>
                    <span className="mt-auto flex flex-wrap items-center gap-1.5 pt-1 text-[11.5px] text-mut">
                      <span
                        className="size-2 rounded-full"
                        style={{ background: audience(s.required_data_class).dot }}
                      />
                      {audience(s.required_data_class).label}
                      {s.resources.length > 0 && (
                        <>
                          <span className="text-faint">·</span>
                          {s.resources.length} reference{" "}
                          {s.resources.length === 1 ? "file" : "files"}
                        </>
                      )}
                    </span>
                  </motion.button>
                </li>
              ))}
              <li>
                <button
                  onClick={() => startNew("agent")}
                  className="flex h-full min-h-32 w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-line-strong p-4 text-[13px] font-semibold text-mut transition-colors hover:border-accent hover:text-accent"
                >
                  <Plus className="size-5" />
                  Write another
                </button>
              </li>
            </ul>
          )}
        </StaggerItem>
      )}

      {/* ---------------- your lookups ---------------- */}
      {tab === "yours" && sources.length > 0 && (
        <StaggerItem>
          <div className="grid items-start gap-5 xl:grid-cols-12">
            <aside className="flex flex-col gap-2 xl:col-span-4">
              {lookups.length === 0 ? (
                <div className="rounded-2xl border border-line bg-surface p-2">
                  <Empty
                    icon={<Wrench className="size-6" />}
                    title="No lookups yet"
                    hint="Copy a ready-made one, or build your own if you have someone who knows the database."
                    action={
                      <Button variant="soft" onClick={() => startNew("sql")}>
                        <Plus className="size-4" /> Build one
                      </Button>
                    }
                  />
                </div>
              ) : (
                lookups.map((s) => (
                  <motion.button
                    key={s.id}
                    layout
                    onClick={() => open(s)}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 text-left transition-colors ${
                      editing === s.id
                        ? "border-accent bg-accent-soft"
                        : "border-line bg-surface hover:border-line-strong"
                    }`}
                  >
                    <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                      <Wrench className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-semibold">
                        {s.description || s.name}
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-mut">
                        <span
                          className="size-2 rounded-full"
                          style={{ background: audience(s.required_data_class).dot }}
                        />
                        {audience(s.required_data_class).label}
                        <span className="text-faint">·</span>
                        {sources.find((c) => c.id === s.connector_id)?.name ??
                          "source removed"}
                      </span>
                    </span>
                  </motion.button>
                ))
              )}
            </aside>

            <section className="xl:col-span-8">
              {building && draft.kind !== "agent" ? (
                <Builder
                  draft={draft}
                  setDraft={setDraft}
                  params={params}
                  setParams={setParams}
                  sources={sources}
                  step={step}
                  setStep={setStep}
                  editing={editing}
                  saving={saving}
                  onSave={save}
                  saved={saved}
                  testArgs={testArgs}
                  setTestArgs={setTestArgs}
                  testing={testing}
                  run={run}
                  onTest={tryIt}
                  onDelete={editing ? removeSkill : undefined}
                  onClose={() => {
                    setBuilding(false);
                    setEditing(null);
                  }}
                />
              ) : (
                <div className="rounded-2xl border border-line bg-surface p-2 [box-shadow:var(--shadow)]">
                  <Empty
                    icon={<ArrowRight className="size-6" />}
                    title="Pick one to see how it works"
                    hint="Choose a lookup on the left to read its question, try it with real values, or change who's allowed to use it."
                    action={
                      <Button variant="soft" onClick={() => startNew("sql")}>
                        <Plus className="size-4" /> Build a new one
                      </Button>
                    }
                  />
                </div>
              )}
            </section>
          </div>
        </StaggerItem>
      )}

      {/* A lookup needs somewhere to read from before it can exist at all. */}
      {tab === "yours" && sources.length === 0 && (
        <StaggerItem>
          <div className="rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
            <Empty
              icon={<Database className="size-6" />}
              title="Connect a data source first"
              hint="A lookup fetches a live figure, so it needs somewhere to read from. Connect a database or an internal service — KARAG opens it read-only — and then you can build one."
              action={
                <Button
                  variant="cta"
                  onClick={() => {
                    setTab("sources");
                    setAddingSource(true);
                  }}
                >
                  <Plus className="size-4" /> Connect data
                </Button>
              }
            />
          </div>
        </StaggerItem>
      )}

      {/* ---------------- shared with you ---------------- */}
      {tab === "ready" && (
        <StaggerItem>
          <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
            <header className="border-b border-line px-6 py-4">
              <h2 className="font-display text-[16px] font-semibold">
                What other companies have shared
              </h2>
              <p className="mt-0.5 text-[13px] text-mut">
                A procedure copies whole — it touches no data, so there is
                nothing to point at. A lookup copies as the question only: you
                pick which of your own sources it reads from, and their data
                stays entirely theirs.
              </p>
            </header>
            <div className="p-6 pt-4">
              {library.length === 0 ? (
                <Empty
                  icon={<Copy className="size-6" />}
                  title="Nothing shared yet"
                  hint="When another company on the platform publishes a skill, it appears here ready to copy."
                />
              ) : (
                <ul className="grid gap-3 md:grid-cols-2">
                  {library.map((s) => (
                    <li
                      key={s.id}
                      className="flex flex-col rounded-2xl border border-line bg-surface p-4"
                    >
                      <span className="mb-2 flex items-center gap-2 text-[11.5px] font-semibold text-mut">
                        {isProcedure(s) ? (
                          <>
                            <BookOpenCheck className="size-3.5 text-accent" />
                            Procedure
                          </>
                        ) : (
                          <>
                            <Wrench className="size-3.5 text-accent" />
                            Lookup
                          </>
                        )}
                      </span>
                      <p className="text-[13.5px] font-semibold">
                        {s.description || s.name}
                      </p>
                      <div className="mt-3">
                        {isProcedure(s) ? (
                          <Button
                            variant="soft"
                            size="sm"
                            onClick={async () => {
                              try {
                                await api.skillDefs.import(token, s.id);
                                setTab("procedures");
                                await load();
                              } catch (e) {
                                setProblem(errorWords((e as ApiError).message));
                              }
                            }}
                          >
                            <Copy className="size-3.5" /> Copy it
                          </Button>
                        ) : sources.length === 0 ? (
                          <p className="text-[12px] text-faint">
                            Connect a data source first — a lookup has to read
                            from something of yours.
                          </p>
                        ) : (
                          <Picker
                            value=""
                            placeholder="Copy it and read from…"
                            ariaLabel={`Copy ${s.name}`}
                            onChange={async (cid) => {
                              try {
                                await api.skillDefs.import(token, s.id, cid);
                                setTab("yours");
                                await load();
                              } catch (e) {
                                setProblem(errorWords((e as ApiError).message));
                              }
                            }}
                            options={sources.map((c) => ({
                              value: c.id,
                              label: c.name,
                            }))}
                          />
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </StaggerItem>
      )}

      {/* ---------------- connected data ---------------- */}
      {tab === "sources" && (
        <StaggerItem>
          <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
              <div>
                <h2 className="font-display text-[16px] font-semibold">
                  Connected data
                </h2>
                <p className="mt-0.5 flex items-center gap-1.5 text-[13px] text-mut">
                  <Check className="size-3.5 text-good" />
                  KARAG can only read from these — never change or delete
                  anything.
                </p>
              </div>
              {!addingSource && (
                <Button variant="soft" onClick={() => setAddingSource(true)}>
                  <Plus className="size-4" /> Connect a source
                </Button>
              )}
            </header>
            <div className="p-6 pt-4">
              <AnimatePresence initial={false}>
                {addingSource && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.28, ease: EASE }}
                    className="overflow-hidden"
                  >
                    <NewSource
                      onDone={() => {
                        setAddingSource(false);
                        void load();
                      }}
                      onCancel={() => setAddingSource(false)}
                    />
                  </motion.div>
                )}
              </AnimatePresence>

              {sources.length === 0 && !addingSource ? (
                <Empty
                  icon={<Database className="size-6" />}
                  title="Nothing connected yet"
                  hint="A lookup needs somewhere to read from. Connect a database or an internal service and KARAG will open it read-only."
                  action={
                    <Button variant="cta" onClick={() => setAddingSource(true)}>
                      <Plus className="size-4" />
                      Connect your first source
                    </Button>
                  }
                />
              ) : (
                <ul className="mt-4 flex flex-col gap-2 empty:mt-0">
                  {sources.map((c) => (
                    <li
                      key={c.id}
                      className="flex items-center gap-3.5 rounded-xl border border-line px-4 py-3"
                    >
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                        <Database className="size-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13.5px] font-semibold">
                          {c.name}
                        </p>
                        <p className="text-[12px] text-mut">
                          {SOURCE_KINDS.find((k) => k.value === c.kind)?.label ??
                            c.kind}{" "}
                          · at most {c.row_limit.toLocaleString()} rows per answer
                          · gives up after {c.timeout_s}s
                        </p>
                      </div>
                      <ConfirmAction
                        question="Disconnect it?"
                        confirmLabel="Yes, disconnect"
                        onConfirm={async () => {
                          await api.connectors.remove(token, c.id).catch(() => {});
                          void load();
                        }}
                      >
                        {(start) => (
                          <button
                            onClick={start}
                            aria-label={`Disconnect ${c.name}`}
                            className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        )}
                      </ConfirmAction>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </StaggerItem>
      )}
    </Stagger>
  );
}

/* ---------------- the stepped builder ---------------- */

function Builder({
  draft,
  setDraft,
  params,
  setParams,
  sources,
  step,
  setStep,
  editing,
  saving,
  onSave,
  saved,
  testArgs,
  setTestArgs,
  testing,
  run,
  onTest,
  onDelete,
  onClose,
}: {
  draft: SkillDefinitionInput;
  setDraft: (d: SkillDefinitionInput) => void;
  params: ParamRow[];
  setParams: (p: ParamRow[]) => void;
  sources: Connector[];
  step: number;
  setStep: (n: number) => void;
  editing: string | null;
  saving: boolean;
  onSave: () => void;
  saved: string;
  testArgs: Record<string, string>;
  setTestArgs: (a: Record<string, string>) => void;
  testing: boolean;
  run: SkillTestRun | null;
  onTest: () => void;
  onDelete?: () => void;
  onClose: () => void;
}) {
  const set = <K extends keyof SkillDefinitionInput>(
    k: K,
    v: SkillDefinitionInput[K],
  ) => setDraft({ ...draft, [k]: v });

  const rows = useMemo(() => {
    if (!run?.ok || !Array.isArray(run.data)) return null;
    return run.data as Record<string, unknown>[];
  }, [run]);

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface [box-shadow:var(--shadow)]">
      <header className="flex items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div className="min-w-0">
          <h2 className="font-display truncate text-[16px] font-semibold">
            {editing ? draft.description || draft.name : "Build a lookup"}
          </h2>
          <p className="mt-0.5 text-[13px] text-mut">
            {editing
              ? "Change it, try it, or take it out of service."
              : "Four steps — only one of them needs a database person."}
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <X className="size-4" />
        </button>
      </header>

      <div className="p-6">
        <Steps current={step} onGo={setStep}>
          <Step
            index={0}
            title="What question does it answer?"
            summary={draft.description}
            done={Boolean(draft.description.trim() && draft.name.trim())}
          >
            <p className="mb-3 text-[13px] leading-relaxed text-mut">
              Write it the way someone would ask it out loud. The assistant uses
              this sentence to decide when to reach for this lookup, so being
              precise matters more than being brief.
            </p>
            <Input
              value={draft.description}
              onChange={(e) => set("description", e.target.value)}
              placeholder="Total sales for one store on one day"
            />
            <label className="mb-1.5 mt-4 block text-[12.5px] font-semibold">
              Short name
            </label>
            <Input
              value={draft.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="daily_sales"
              className="font-mono text-[12.5px]"
            />
            <p className="mt-1.5 text-[12px] text-faint">
              Lowercase with underscores. This is an internal handle — nobody
              reads it.
            </p>
            <NextButton
              disabled={!draft.description.trim() || !draft.name.trim()}
              onClick={() => setStep(1)}
            />
          </Step>

          <Step
            index={1}
            title="Where does the answer come from?"
            summary={sources.find((c) => c.id === draft.connector_id)?.name}
            done={Boolean(draft.connector_id)}
          >
            <p className="mb-3 text-[13px] leading-relaxed text-mut">
              Which connected system holds this data?
            </p>
            <Picker
              value={draft.connector_id}
              onChange={(v) => set("connector_id", v)}
              ariaLabel="Data source"
              placeholder="Choose a source…"
              options={sources.map((c) => ({
                value: c.id,
                label: c.name,
                hint: SOURCE_KINDS.find((k) => k.value === c.kind)?.hint,
              }))}
            />
            <NextButton
              disabled={!draft.connector_id}
              onClick={() => setStep(2)}
            />
          </Step>

          <Step
            index={2}
            title="The query"
            summary={draft.sql || draft.path ? "Written" : undefined}
            done={Boolean(draft.sql.trim() || draft.path.trim())}
          >
            <Notice tone="warn">
              This is the one technical step. It needs someone who knows your
              database — ask whoever looks after it. Everything before and after
              this you can do yourself.
            </Notice>
            <div className="mt-4">
              <Textarea
                value={draft.kind === "sql" ? draft.sql : draft.path}
                onChange={(e) =>
                  draft.kind === "sql"
                    ? set("sql", e.target.value)
                    : set("path", e.target.value)
                }
                placeholder={
                  "SELECT store_id, day, SUM(amount) AS total\nFROM sales\nWHERE tenant = :tenant_id AND store_id = :store_id AND day = :day\nGROUP BY store_id, day"
                }
                className="min-h-40 font-mono text-[12.5px]"
              />
              <ul className="mt-3 flex flex-col gap-1.5 text-[12px] text-mut">
                <li className="flex items-start gap-2">
                  <Check className="mt-0.5 size-3.5 shrink-0 text-good" />
                  Reading only — anything that would change data is refused when
                  you publish.
                </li>
                <li className="flex items-start gap-2">
                  <Check className="mt-0.5 size-3.5 shrink-0 text-good" />
                  <span>
                    <code className="font-mono">:tenant_id</code> is filled in by
                    the platform. Never list it below — that&rsquo;s what keeps
                    one company out of another&rsquo;s data.
                  </span>
                </li>
              </ul>
            </div>

            <div className="mt-5 border-t border-line pt-4">
              <p className="text-[13px] font-semibold">
                What has to be filled in each time?
              </p>
              <p className="mt-0.5 text-[12px] leading-relaxed text-mut">
                Anything written as <code className="font-mono">:like_this</code>{" "}
                in the query. The assistant works the values out from whatever
                someone asked.
              </p>
              <div className="mt-3 flex flex-col gap-2">
                {params.map((p, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <Input
                      value={p.name}
                      onChange={(e) => {
                        const next = [...params];
                        next[i] = { ...p, name: e.target.value };
                        setParams(next);
                      }}
                      placeholder="store_id"
                      className="w-36 font-mono text-[12.5px]"
                    />
                    <Picker
                      value={p.type}
                      onChange={(v) => {
                        const next = [...params];
                        next[i] = { ...p, type: v as ParamRow["type"] };
                        setParams(next);
                      }}
                      className="w-36"
                      ariaLabel="Kind of value"
                      options={[
                        { value: "string", label: "Text" },
                        { value: "integer", label: "Whole number" },
                        { value: "number", label: "Number" },
                        { value: "boolean", label: "Yes / no" },
                      ]}
                    />
                    <Input
                      value={p.description}
                      onChange={(e) => {
                        const next = [...params];
                        next[i] = { ...p, description: e.target.value };
                        setParams(next);
                      }}
                      placeholder="Which store"
                      className="min-w-40 flex-1"
                    />
                    <button
                      onClick={() => setParams(params.filter((_, j) => j !== i))}
                      aria-label="Remove"
                      className="grid size-9 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                ))}
                <button
                  onClick={() =>
                    setParams([
                      ...params,
                      { name: "", type: "string", description: "", required: true },
                    ])
                  }
                  className="flex cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-dashed border-line-strong py-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-accent hover:text-accent"
                >
                  <Plus className="size-3.5" />
                  Add one
                </button>
              </div>
            </div>
            <NextButton
              disabled={!draft.sql.trim() && !draft.path.trim()}
              onClick={() => setStep(3)}
            />
          </Step>

          <Step
            index={3}
            title="Who's allowed to use it?"
            summary={audience(draft.required_data_class).label}
            done
          >
            <p className="mb-3 text-[13px] leading-relaxed text-mut">
              Anyone below this level who asks gets a refusal instead of a
              number. You can only pick a level you&rsquo;re cleared for yourself.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {AUDIENCES.map((a) => {
                const on = a.value === draft.required_data_class;
                return (
                  <button
                    key={a.value}
                    onClick={() =>
                      set("required_data_class", a.value as DataClass)
                    }
                    className={`cursor-pointer rounded-xl border p-3 text-left transition-colors ${
                      on
                        ? "border-accent bg-accent-soft/50"
                        : "border-line hover:border-line-strong"
                    }`}
                  >
                    <span className="flex items-center gap-2 text-[13px] font-semibold">
                      <span
                        className="size-2.5 rounded-full"
                        style={{ background: a.dot }}
                      />
                      {a.label}
                    </span>
                    <span className="mt-1 block text-[11.5px] leading-relaxed text-mut">
                      {a.who}
                    </span>
                  </button>
                );
              })}
            </div>

            <label className="mt-5 flex cursor-pointer items-start gap-2.5 rounded-xl border border-line p-3.5">
              <input
                type="checkbox"
                checked={draft.shared}
                onChange={(e) => set("shared", e.target.checked)}
                className="mt-0.5 size-4 accent-[var(--accent)]"
              />
              <span>
                <span className="block text-[13px] font-semibold">
                  Let other companies copy the question
                </span>
                <span className="mt-0.5 block text-[12px] leading-relaxed text-mut">
                  They get the wording only, pointed at their own data. Nothing
                  of yours travels with it.
                </span>
              </span>
            </label>
          </Step>
        </Steps>

        {/* ---- publish + try ---- */}
        <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-line pt-5">
          <Button
            variant="cta"
            onClick={onSave}
            busy={saving}
            disabled={
              !draft.name.trim() ||
              !draft.description.trim() ||
              !draft.connector_id ||
              (!draft.sql.trim() && !draft.path.trim())
            }
          >
            {editing ? "Save changes" : "Publish lookup"}
          </Button>
          {editing && (
            <Button variant="ghost" onClick={onTest} busy={testing}>
              <Play className="size-4" />
              Try it
            </Button>
          )}
          {onDelete && (
            <ConfirmAction
              question="Take it out of service?"
              confirmLabel="Yes, remove"
              onConfirm={onDelete}
            >
              {(start) => (
                <button
                  onClick={start}
                  className="ml-auto cursor-pointer text-[12.5px] font-semibold text-faint transition-colors hover:text-bad"
                >
                  Remove this lookup
                </button>
              )}
            </ConfirmAction>
          )}
        </div>

        {saved && (
          <div className="mt-3">
            <Notice tone="good">{saved}</Notice>
          </div>
        )}

        {editing && params.length > 0 && (
          <div className="mt-4 rounded-xl border border-line bg-surface-2 p-4">
            <p className="text-[12.5px] font-semibold">Values to try it with</p>
            <div className="mt-2.5 flex flex-wrap gap-3">
              {params.map((p) => (
                <span key={p.name} className="flex items-center gap-2">
                  <span className="font-mono text-[12px] text-mut">{p.name}</span>
                  <Input
                    value={testArgs[p.name] ?? ""}
                    onChange={(e) =>
                      setTestArgs({ ...testArgs, [p.name]: e.target.value })
                    }
                    placeholder={p.description || p.type}
                    className="w-40"
                  />
                </span>
              ))}
            </div>
          </div>
        )}

        {/* ---- the signature: what actually came back ---- */}
        <AnimatePresence>
          {run && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, ease: EASE }}
              className="mt-4 overflow-hidden rounded-xl border border-line"
            >
              <div
                className={`flex items-center gap-2 px-4 py-2.5 text-[12.5px] font-semibold ${
                  run.ok ? "bg-good-soft text-good" : "bg-bad-soft text-bad"
                }`}
              >
                {run.ok ? (
                  <>
                    <Check className="size-4 shrink-0" />
                    {run.row_count === 0
                      ? "It ran — nothing matched those values."
                      : `It ran — ${run.row_count} ${run.row_count === 1 ? "row" : "rows"} came back.`}
                  </>
                ) : (
                  <>
                    <X className="size-4 shrink-0" />
                    {run.error}
                  </>
                )}
              </div>
              {run.query_shown && (
                <pre className="overflow-x-auto border-t border-line bg-bg-deep px-4 py-3 font-mono text-[11.5px] leading-relaxed text-mut">
                  {run.query_shown}
                </pre>
              )}
              {rows && rows.length > 0 && (
                <div className="overflow-x-auto border-t border-line">
                  <table className="w-full text-left text-[12.5px]">
                    <thead>
                      <tr className="border-b border-line bg-surface-2">
                        {Object.keys(rows[0]).map((h) => (
                          <th
                            key={h}
                            className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-mut"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.slice(0, 8).map((r, i) => (
                        <tr key={i} className="border-b border-line last:border-0">
                          {Object.values(r).map((v, j) => (
                            <td key={j} className="px-4 py-2 tabular-nums">
                              {String(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function NextButton({
  onClick,
  disabled,
}: {
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <div className="mt-5">
      <Button variant="soft" size="sm" onClick={onClick} disabled={disabled}>
        Next
        <ArrowRight className="size-3.5" />
      </Button>
    </div>
  );
}

/* ---------------- connect a source ---------------- */

function NewSource({
  onDone,
  onCancel,
}: {
  onDone: () => void;
  onCancel: () => void;
}) {
  const { token } = useAuth();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<ConnectorKind>("sql_sqlite");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const field =
    kind === "sql_sqlite"
      ? { label: "Where is the file?", placeholder: "./demo_sales.db", key: "path" }
      : kind === "sql_postgres"
        ? {
            label: "Connection details",
            placeholder: "postgresql://reader@host/db",
            key: "dsn",
          }
        : { label: "Address", placeholder: "https://api.internal/…", key: "base_url" };

  return (
    <div className="rounded-2xl border border-line bg-surface-2 p-5">
      <p className="text-[13.5px] font-semibold">Connect a source</p>
      <p className="mt-0.5 text-[12.5px] leading-relaxed text-mut">
        KARAG opens this read-only — it can never write to it. What you type
        below is stored hidden and never shown again.
      </p>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div>
          <label className="mb-1.5 block text-[12.5px] font-semibold">
            What should we call it?
          </label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Sales database"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-[12.5px] font-semibold">
            What kind is it?
          </label>
          <Picker
            value={kind}
            onChange={(v) => setKind(v as ConnectorKind)}
            ariaLabel="Kind of source"
            options={SOURCE_KINDS.map((k) => ({
              value: k.value,
              label: k.label,
              hint: k.hint,
            }))}
          />
        </div>
      </div>

      <label className="mb-1.5 mt-4 block text-[12.5px] font-semibold">
        {field.label}
      </label>
      <Input
        value={secret}
        onChange={(e) => setSecret(e.target.value)}
        placeholder={field.placeholder}
        className="font-mono text-[12.5px]"
      />

      {err && (
        <div className="mt-3">
          <Notice tone="bad">{err}</Notice>
        </div>
      )}

      <div className="mt-5 flex items-center gap-3">
        <Button
          onClick={async () => {
            setBusy(true);
            setErr("");
            try {
              await api.connectors.create(token, {
                name: name.trim(),
                kind,
                config: { [field.key]: secret.trim() },
              });
              onDone();
            } catch (e) {
              setErr(errorWords((e as ApiError).message));
            } finally {
              setBusy(false);
            }
          }}
          busy={busy}
          disabled={!name.trim() || !secret.trim()}
        >
          Connect
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
