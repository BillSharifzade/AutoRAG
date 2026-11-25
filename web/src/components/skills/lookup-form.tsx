"use client";

/* A lookup in four numbered steps, in the order the decisions actually come:
   where the data is, what to fetch, who may use it, what to call it — then a
   panel to try it. Parameters are never typed by hand: every :name in the
   statement (or {name} in an API path) becomes a row with a type picker. */

import { Play, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import {
  api,
  type ApiError,
  type Connector,
  type SkillDefinition,
  type SkillDefinitionInput,
  type SkillTestRun,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLocale, useT, type Locale } from "@/i18n";
import { errorWords } from "@/lib/words";
import {
  MAX_DESCRIPTION,
  PARAM_TYPES,
  blankInput,
  buildSchema,
  coerceArgs,
  connectorFits,
  detectPlaceholders,
  humanTitle,
  looksReadOnly,
  machineName,
  mergeParams,
  nameProblem,
  rowsFromSchema,
  type ParamRow,
  type ParamType,
} from "@/lib/skills";
import { Button, Input, Picker, Textarea } from "@/components/ui";
import { ConfirmAction, Notice, Step, Steps } from "@/components/pro";
import { AccessBlock, Field, KindIcon, TitleField, WhenField } from "./bits";
import { ConnectionForm, useConnectorKindLabel } from "./connection-form";

function plural(locale: Locale, n: number): "one" | "few" | "many" {
  if (locale === "ru") {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return "one";
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "few";
    return "many";
  }
  return n === 1 ? "one" : "many";
}

export function LookupForm({
  kind,
  existing,
  connectors,
  onConnectorAdded,
  onSaved,
  onDeleted,
  onCancel,
}: {
  kind: "sql" | "rest";
  existing?: SkillDefinition;
  connectors: Connector[];
  onConnectorAdded: (c: Connector) => void;
  onSaved: (s: SkillDefinition) => void;
  onDeleted?: (id: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const { token } = useAuth();
  const kindLabel = useConnectorKindLabel();

  const [step, setStep] = useState(existing ? 3 : 0);
  const [connectorId, setConnectorId] = useState(existing?.connector_id ?? "");
  const [adding, setAdding] = useState(false);
  const [statement, setStatement] = useState(
    existing ? (kind === "sql" ? existing.sql : existing.path) : "",
  );
  const [rows, setRows] = useState<ParamRow[]>(
    existing ? rowsFromSchema(existing.param_schema) : [],
  );
  const [audience, setAudience] = useState<string>(existing?.required_data_class ?? "operational");
  const [roleValues, setRoleValues] = useState<string[]>(existing?.required_roles ?? []);
  const [shared, setShared] = useState(existing?.shared ?? false);
  const [title, setTitle] = useState(existing ? humanTitle(existing.name) : "");
  const [name, setName] = useState(existing?.name ?? "");
  const [nameTouched, setNameTouched] = useState(Boolean(existing));
  const [description, setDescription] = useState(existing?.description ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // try-it
  const [args, setArgs] = useState<Record<string, string>>({});
  const [run, setRun] = useState<SkillTestRun | null>(null);
  const [running, setRunning] = useState(false);

  const fitting = useMemo(() => connectors.filter((c) => connectorFits(c, kind)), [connectors, kind]);
  const connector = fitting.find((c) => c.id === connectorId);

  /* A new lookup starts with the audience of the connection it reads — the
     server refuses one that would show the data to more people than that. */
  function inheritAudience(c: Connector) {
    const cls = c.metadata?.data_class;
    if (!existing && cls) setAudience(cls);
  }

  function changeStatement(v: string) {
    setStatement(v);
    setRows((prev) => mergeParams(detectPlaceholders(v, kind), prev));
  }

  function changeTitle(v: string) {
    setTitle(v);
    if (!nameTouched) setName(machineName(v, kind));
  }

  const statementOk =
    statement.trim().length > 0 && (kind === "rest" || looksReadOnly(statement));
  const nameOk = !nameProblem(name, kind) && description.trim().length > 0;
  const ready = Boolean(connector) && statementOk && nameOk;

  async function save() {
    setBusy(true);
    setErr("");
    const body: SkillDefinitionInput = {
      ...blankInput(kind),
      name,
      description: description.trim(),
      connector_id: connectorId,
      param_schema: buildSchema(rows),
      sql: kind === "sql" ? statement : "",
      path: kind === "rest" ? statement.trim() : "",
      required_data_class: audience as SkillDefinitionInput["required_data_class"],
      required_roles: roleValues,
      shared,
      enabled: existing?.enabled ?? true,
    };
    try {
      const saved = existing
        ? await api.skillDefs.update(token, existing.id, body)
        : await api.skillDefs.create(token, body);
      onSaved(saved);
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  async function tryIt() {
    if (!existing) return;
    setRunning(true);
    setRun(null);
    try {
      setRun(await api.skillDefs.test(token, existing.id, coerceArgs(rows, args)));
    } catch (e) {
      setRun({
        ok: false, query_shown: "", data: null, row_count: null,
        error: errorWords((e as ApiError).message),
      });
    } finally {
      setRunning(false);
    }
  }

  const typeLabel = (p: ParamType) => t(`skills.params.type.${p}`);
  const resultRows: Record<string, unknown>[] | null =
    run?.ok && run.data && typeof run.data === "object" && "rows" in (run.data as object)
      ? ((run.data as { rows: Record<string, unknown>[] }).rows ?? [])
      : null;

  return (
    <div className="flex flex-col gap-6">
      <Steps current={step} onGo={setStep}>
        {/* 1 — where */}
        <Step
          index={0}
          title={t("skills.step.where")}
          summary={connector ? `${connector.name} · ${kindLabel(connector.kind)}` : undefined}
          done={Boolean(connector)}
        >
          <div className="flex flex-col gap-3">
            {fitting.length === 0 && !adding && (
              <p className="text-[13px] text-mut">{t("skills.conn.none")}</p>
            )}
            {fitting.length > 0 && (
              <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t("skills.conn.pick")}>
                {fitting.map((c) => {
                  const active = c.id === connectorId;
                  return (
                    <button
                      key={c.id}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      onClick={() => {
                        setConnectorId(c.id);
                        inheritAudience(c);
                        setStep(1);
                      }}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3.5 text-left transition-colors ${
                        active
                          ? "border-accent bg-accent-soft/50"
                          : "border-line bg-surface hover:border-line-strong hover:bg-surface-2"
                      }`}
                    >
                      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-accent">
                        <KindIcon kind={c.kind === "rest" ? "rest" : "sql"} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-[13.5px] font-semibold">{c.name}</span>
                        <span className="block text-[12px] text-mut">{kindLabel(c.kind)}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
            {adding ? (
              <ConnectionForm
                allowed={kind === "rest" ? ["rest"] : ["sql_sqlite", "sql_postgres", "sql_mysql"]}
                onDone={(c) => {
                  onConnectorAdded(c);
                  setConnectorId(c.id);
                  inheritAudience(c);
                  setAdding(false);
                  setStep(1);
                }}
                onCancel={() => setAdding(false)}
              />
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setAdding(true)} className="w-fit">
                {t("skills.conn.add")}
              </Button>
            )}
          </div>
        </Step>

        {/* 2 — what */}
        <Step
          index={1}
          title={t("skills.step.what")}
          summary={statementOk ? statement.trim().slice(0, 80) : undefined}
          done={statementOk}
        >
          <div className="flex flex-col gap-4">
            {kind === "sql" ? (
              <Field label={t("skills.sql.label")} hint={t("skills.sql.hint")}>
                <Textarea
                  value={statement}
                  onChange={(e) => changeStatement(e.target.value)}
                  rows={5}
                  spellCheck={false}
                  placeholder={t("skills.sql.ph")}
                  className="min-h-28 font-mono text-[13px]"
                />
                {statement.trim() && !looksReadOnly(statement) && (
                  <p className="mt-1.5 text-[12px] text-bad">{t("skills.sql.readOnly")}</p>
                )}
              </Field>
            ) : (
              <Field label={t("skills.rest.path")} hint={t("skills.rest.hint")}>
                <Input
                  value={statement}
                  onChange={(e) => changeStatement(e.target.value)}
                  spellCheck={false}
                  placeholder={t("skills.rest.ph")}
                  className="font-mono text-[13px]"
                />
              </Field>
            )}

            <Field label={t("skills.params.title")}>
              {rows.length === 0 ? (
                <p className="text-[12.5px] text-faint">{t("skills.params.none")}</p>
              ) : (
                <div className="flex flex-col gap-2">
                  {rows.map((r) => (
                    <div key={r.name} className="flex items-center gap-3">
                      <code className="min-w-32 rounded-md bg-surface-2 px-2 py-1 font-mono text-[12.5px]">
                        {r.name}
                      </code>
                      <Picker
                        value={r.type}
                        onChange={(v) =>
                          setRows((rs) => rs.map((x) => (x.name === r.name ? { ...x, type: v as ParamType } : x)))
                        }
                        options={PARAM_TYPES.map((p) => ({ value: p, label: typeLabel(p) }))}
                        ariaLabel={r.name}
                        className="w-44"
                      />
                    </div>
                  ))}
                </div>
              )}
            </Field>
            <Button size="sm" variant="soft" disabled={!statementOk} onClick={() => setStep(2)} className="w-fit">
              {t("common.next")}
            </Button>
          </div>
        </Step>

        {/* 3 — who */}
        <Step index={2} title={t("skills.step.who")} summary={t(`aud.${audience}.label`)} done={step > 2 || Boolean(existing)}>
          <div className="flex flex-col gap-4">
            <AccessBlock
              audience={audience}
              onAudience={setAudience}
              roleValues={roleValues}
              onRoles={setRoleValues}
              shared={shared}
              onShared={setShared}
            />
            <Button size="sm" variant="soft" onClick={() => setStep(3)} className="w-fit">
              {t("common.next")}
            </Button>
          </div>
        </Step>

        {/* 4 — name */}
        <Step index={3} title={t("skills.step.name")} summary={nameOk ? title || name : undefined} done={nameOk}>
          <div className="flex flex-col gap-5">
            <TitleField
              title={title}
              name={name}
              kind={kind}
              onTitle={changeTitle}
              onName={(v) => {
                setNameTouched(true);
                setName(v);
              }}
              autoFocus={!existing}
            />
            <WhenField
              value={description}
              onChange={setDescription}
              max={MAX_DESCRIPTION}
              placeholder={t("skills.field.when.phLookup")}
            />
          </div>
        </Step>
      </Steps>

      {/* try it — needs a saved skill, because the test runs the stored one */}
      <div className="rounded-2xl border border-line bg-surface p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="font-display text-[15px] font-semibold">{t("skills.try.title")}</p>
          {existing && (
            <Button size="sm" onClick={tryIt} busy={running}>
              <Play className="size-3.5" /> {t("skills.try.run")}
            </Button>
          )}
        </div>
        {!existing ? (
          <p className="mt-2 text-[13px] text-mut">{t("skills.try.saveFirst")}</p>
        ) : (
          <div className="mt-4 flex flex-col gap-4">
            {rows.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {rows.map((r) => (
                  <Field key={r.name} label={r.name}>
                    {r.type === "boolean" ? (
                      <Picker
                        value={args[r.name] ?? ""}
                        onChange={(v) => setArgs((a) => ({ ...a, [r.name]: v }))}
                        options={[
                          { value: "true", label: t("skills.try.yes") },
                          { value: "false", label: t("skills.try.no") },
                        ]}
                      />
                    ) : (
                      <Input
                        value={args[r.name] ?? ""}
                        onChange={(e) => setArgs((a) => ({ ...a, [r.name]: e.target.value }))}
                        placeholder={typeLabel(r.type)}
                        inputMode={r.type === "string" ? "text" : "decimal"}
                      />
                    )}
                  </Field>
                ))}
              </div>
            )}
            {run && !run.ok && <Notice tone="bad">{run.error}</Notice>}
            {run?.ok && (
              <div className="flex flex-col gap-3">
                <Notice tone="good">
                  {t("skills.try.ok")}{" "}
                  {resultRows &&
                    t(`skills.try.rows.${plural(locale, resultRows.length)}`, { n: resultRows.length })}
                </Notice>
                {resultRows && resultRows.length > 0 ? (
                  <div className="overflow-x-auto rounded-xl border border-line">
                    <table className="w-full text-[12.5px]">
                      <thead className="bg-surface-2 text-left text-[11px] uppercase tracking-wide text-mut">
                        <tr>
                          {Object.keys(resultRows[0]).map((k) => (
                            <th key={k} className="px-3 py-2 font-semibold">{k}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {resultRows.slice(0, 20).map((row, i) => (
                          <tr key={i} className="border-t border-line">
                            {Object.keys(resultRows[0]).map((k) => (
                              <td key={k} className="px-3 py-1.5 font-mono tabular-nums">{String(row[k] ?? "")}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : resultRows ? (
                  <p className="text-[13px] text-mut">{t("skills.try.empty")}</p>
                ) : (
                  <pre className="overflow-x-auto rounded-xl border border-line bg-bg-deep p-3 font-mono text-[12px]">
                    {JSON.stringify(run.data, null, 2)}
                  </pre>
                )}
                {run.query_shown && (
                  <Field label={t("skills.try.query")}>
                    <code className="block overflow-x-auto rounded-lg border border-line bg-bg-deep p-2.5 font-mono text-[11.5px] text-mut">
                      {run.query_shown}
                    </code>
                  </Field>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {err && <Notice tone="bad">{err}</Notice>}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
        <Button variant="cta" onClick={save} busy={busy} disabled={!ready}>
          {existing ? t("common.save") : t("skills.save.newLookup")}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        {existing && onDeleted && (
          <span className="ml-auto">
            <ConfirmAction
              question={t("skills.delete.q")}
              onConfirm={async () => {
                await api.skillDefs.remove(token, existing.id);
                onDeleted(existing.id);
              }}
            >
              {(start) => (
                <Button variant="danger" size="sm" onClick={start}>
                  <Trash2 className="size-3.5" /> {t("common.delete")}
                </Button>
              )}
            </ConfirmAction>
          </span>
        )}
      </div>
    </div>
  );
}
