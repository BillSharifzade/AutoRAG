"use client";

/* Connecting a database in two steps: where it is (login details, or a file),
   then what the assistant found in it — with room to correct the reading and
   decide what the assistant may do with it. */

import { AlertTriangle, ArrowRight, Check, Database, Globe, Sparkles, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, type ApiError, type Connector, type DbConnectResult } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLocale, useT, type Locale } from "@/i18n";
import { errorWords, sizeWords } from "@/lib/words";
import { Button, Input, Textarea } from "@/components/ui";
import { Notice, Step, Steps } from "@/components/pro";
import { AccessBlock, Field, Switch } from "@/components/skills/bits";

type Way = "sql_postgres" | "sql_mysql" | "file";

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

export function DbWizard({
  onDone,
  onCancel,
}: {
  onDone: (c: Connector) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const { token } = useAuth();
  const [step, setStep] = useState(0);
  const [way, setWay] = useState<Way>("sql_postgres");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [database, setDatabase] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [ssl, setSsl] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [tested, setTested] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<DbConnectResult | null>(null);
  const [comment, setComment] = useState("");
  // chosen in the review step; until then the connection is limited to the
  // narrowest audience the author is cleared for (the server's default)
  const [audience, setAudience] = useState("");
  const [roleValues, setRoleValues] = useState<string[]>([]);
  const [freeQuery, setFreeQuery] = useState(true);
  const [knowledge, setKnowledge] = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);

  const login = {
    kind: way === "file" ? ("sql_postgres" as const) : way,
    host: host.trim(),
    port: port.trim() ? Number(port) : null,
    database: database.trim(),
    username: username.trim(),
    password,
    ssl,
  };
  const loginReady = way === "file" ? Boolean(file) : Boolean(host.trim() && database.trim() && username.trim());

  async function test() {
    setBusy(true);
    setErr("");
    setTested(null);
    try {
      const r = await api.databases.test(token, login);
      setTested(r.tables);
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  async function read() {
    setBusy(true);
    setErr("");
    try {
      const common = {
        name: name.trim() || (file ? file.name.replace(/\.[^.]+$/, "") : database.trim()),
        required_roles: roleValues,
        free_query: freeQuery,
        knowledge,
        language: locale,
      };
      const r =
        way === "file" && file
          ? await api.databases.upload(token, file, common)
          : await api.databases.connect(token, { ...login, ...common });
      setResult(r);
      setName(r.connector.name);
      setStep(1);
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  async function refine() {
    if (!result) return;
    setBusy(true);
    setErr("");
    try {
      setResult(await api.databases.describe(token, result.connector.id, { comment, language: locale }));
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!result) return;
    setBusy(true);
    setErr("");
    try {
      const updated = await api.databases.update(token, result.connector.id, {
        name: name.trim() || undefined,
        free_query: freeQuery,
        knowledge,
        data_class: audience as Connector["metadata"]["data_class"] & string,
        required_roles: roleValues,
      });
      onDone(updated);
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    // a connector made for the review step is removed if the person walks away
    if (result) {
      try {
        await api.databases.remove(token, result.connector.id);
      } catch {
        /* already gone */
      }
    }
    onCancel();
  }

  const ways: { value: Way; label: string; hint: string; icon: typeof Database }[] = [
    { value: "sql_postgres", label: t("data.db.way.postgres"), hint: t("data.db.way.server.hint"), icon: Database },
    { value: "sql_mysql", label: t("data.db.way.mysql"), hint: t("data.db.way.server.hint"), icon: Globe },
    { value: "file", label: t("data.db.way.file"), hint: t("data.db.way.file.hint"), icon: Upload },
  ];

  const meanings = new Map((result?.report.tables ?? []).map((x) => [x.name, x.meaning]));
  const imp = result?.connector.metadata.import;

  return (
    <div className="flex flex-col gap-6">
      <Steps current={step} onGo={(n) => result && setStep(n)}>
        <Step
          index={0}
          title={t("data.db.step.setup")}
          summary={result ? result.connector.name : undefined}
          done={Boolean(result)}
        >
          <div className="flex flex-col gap-5">
            <div role="radiogroup" aria-label={t("data.db.how")} className="grid gap-2 sm:grid-cols-3">
              {ways.map((w) => {
                const active = way === w.value;
                const Icon = w.icon;
                return (
                  <button
                    key={w.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => {
                      setWay(w.value);
                      setTested(null);
                      setErr(""); // a login error does not belong to the file upload
                    }}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 text-left transition-colors ${
                      active ? "border-accent bg-accent-soft/50" : "border-line bg-surface hover:border-line-strong"
                    }`}
                  >
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-accent">
                      <Icon className="size-4" />
                    </span>
                    <span>
                      <span className="block text-[13.5px] font-semibold">{w.label}</span>
                      <span className="block text-[12px] text-mut">{w.hint}</span>
                    </span>
                  </button>
                );
              })}
            </div>

            {way === "file" ? (
              <div
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const f = e.dataTransfer.files?.[0];
                  if (f) setFile(f);
                }}
                onClick={() => fileRef.current?.click()}
                className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line bg-surface-2 px-6 py-8 text-center transition-colors hover:border-accent/50"
              >
                <input
                  ref={fileRef}
                  type="file"
                  hidden
                  accept=".sqlite,.db,.sqlite3,.sql"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
                <Upload className="size-6 text-accent" />
                <p className="text-[13.5px] font-semibold">
                  {file ? t("data.db.file.chosen", { name: file.name, size: sizeWords(file.size) }) : t("data.db.file.drop")}
                </p>
                <p className="text-[12px] text-faint">{t("data.db.way.file.hint")}</p>
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
                  <Field label={t("data.db.host")}>
                    <Input value={host} onChange={(e) => setHost(e.target.value)} placeholder="db.company.local" autoFocus />
                  </Field>
                  <Field label={t("data.db.port")}>
                    <Input value={port} onChange={(e) => setPort(e.target.value)} placeholder={way === "sql_mysql" ? "3306" : "5432"} inputMode="numeric" />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label={t("data.db.database")}>
                    <Input value={database} onChange={(e) => setDatabase(e.target.value)} />
                  </Field>
                  <Field label={t("data.db.username")}>
                    <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
                  </Field>
                  <Field label={t("data.db.password")}>
                    <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
                  </Field>
                </div>
                <div className="flex flex-wrap items-center gap-4">
                  <label className="flex cursor-pointer items-center gap-2 text-[13px]">
                    <input type="checkbox" checked={ssl} onChange={(e) => setSsl(e.target.checked)} className="size-4 accent-[var(--accent)]" />
                    {t("data.db.ssl")}
                  </label>
                  <span className="text-[12px] text-faint">{t("data.db.login.hint")}</span>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="ghost" onClick={test} busy={busy} disabled={!loginReady}>
                    {t("data.db.test")}
                  </Button>
                  {tested !== null && (
                    <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-good">
                      <Check className="size-4" /> {t("data.db.test.ok", { n: tested })}
                    </span>
                  )}
                </div>
              </div>
            )}

            <Field label={t("data.db.name")}>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("data.db.name.ph")} />
            </Field>

            <Button onClick={read} busy={busy} disabled={!loginReady} className="w-fit">
              {busy ? t("data.db.reading") : t("data.db.read")} <ArrowRight className="size-4" />
            </Button>
          </div>
        </Step>

        <Step index={1} title={t("data.db.step.review")} done={false}>
          {result && (
            <div className="flex flex-col gap-5">
              <div className="flex flex-wrap items-center gap-2 text-[13px] text-mut">
                <span className="rounded-md bg-surface-2 px-2 py-1 font-semibold text-ink">
                  {t(`data.tables.${plural(locale, result.schema.table_count)}`, { n: result.schema.table_count })}
                </span>
                <span className="font-mono text-[12px]">{result.schema.backend}</span>
                {imp && (
                  <span className="text-[12px]">
                    {t("data.db.import.ok", { t: imp.tables.length, r: imp.rows })}
                    {imp.failed_count > 0 && ` · ${t("data.db.import.failed", { n: imp.failed_count })}`}
                  </span>
                )}
              </div>

              <div className="rounded-2xl border border-accent/25 bg-accent-soft/40 p-4">
                <p className="flex items-center gap-2 text-[13px] font-semibold text-accent-strong">
                  <Sparkles className="size-4" /> {t("data.db.ai")}
                </p>
                <p className="mt-2 whitespace-pre-wrap text-[14px] leading-relaxed">{result.report.summary}</p>
                {result.report.concerns.length > 0 && (
                  <ul className="mt-2 list-disc pl-5 text-[13px] text-mut">
                    {result.report.concerns.map((c, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" /> {c}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <Field label={t("data.db.tables")}>
                <ul className="divide-y divide-line rounded-xl border border-line">
                  {result.schema.tables.map((tb) => (
                    <li key={`${tb.schema}.${tb.name}`} className="px-3.5 py-2.5">
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                        <span className="font-mono text-[13px] font-semibold">{tb.name}</span>
                        <span className="text-[12px] text-faint">
                          {t("data.db.columns", { n: tb.columns.length })}
                          {tb.row_estimate !== null && ` · ${t("data.db.rows", { n: tb.row_estimate })}`}
                        </span>
                      </div>
                      {meanings.get(tb.name) && (
                        <p className="mt-0.5 text-[13px] text-mut">{meanings.get(tb.name)}</p>
                      )}
                      <p className="mt-1 truncate font-mono text-[11.5px] text-faint">
                        {tb.columns.map((c) => c.name).join(", ")}
                      </p>
                    </li>
                  ))}
                </ul>
              </Field>

              <Field label={t("data.db.comment")}>
                <Textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={2}
                  placeholder={t("data.db.comment.ph")}
                  className="min-h-16"
                />
              </Field>
              <Button variant="ghost" onClick={refine} busy={busy} disabled={!comment.trim()} className="w-fit">
                <Sparkles className="size-4" /> {t("data.api.refine")}
              </Button>

              <div className="grid gap-3 sm:grid-cols-2">
                <ToggleCard on={freeQuery} onChange={setFreeQuery} title={t("data.db.allow.query")} hint={t("data.db.allow.query.hint")} />
                <ToggleCard on={knowledge} onChange={setKnowledge} title={t("data.db.allow.knowledge")} hint={t("data.db.allow.knowledge.hint")} />
              </div>

              <Field label={t("data.db.who")}>
                <AccessBlock
                  audience={audience}
                  onAudience={setAudience}
                  roleValues={roleValues}
                  onRoles={setRoleValues}
                  shared={false}
                  onShared={() => {}}
                />
              </Field>
            </div>
          )}
        </Step>
      </Steps>

      {err && <Notice tone="bad">{err}</Notice>}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
        <Button variant="cta" onClick={finish} busy={busy} disabled={!result || !audience}>
          {t("data.db.done")}
        </Button>
        <Button variant="ghost" onClick={cancel} disabled={busy}>
          {t("common.cancel")}
        </Button>
      </div>
    </div>
  );
}

function ToggleCard({
  on,
  onChange,
  title,
  hint,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  title: string;
  hint: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-line bg-surface p-4">
      <div>
        <p className="text-[13.5px] font-semibold">{title}</p>
        <p className="mt-1 text-[12px] leading-relaxed text-mut">{hint}</p>
      </div>
      <Switch on={on} onChange={onChange} label={title} />
    </div>
  );
}
