"use client";

/* Data — where a non-engineer connects an API or a database.
 *
 * Two buttons, two wizards. Underneath, everything already connected, each
 * with the switches that matter: is it fetched live, is a copy kept in
 * knowledge, may the assistant query it. The assistant does the reading and
 * the explaining; the person confirms. */

import { DatabaseZap, Globe, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useState } from "react";
import { api, type ApiError, type Connector, type DataSource } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { useLocale, useT, type Locale } from "@/i18n";
import { errorWords, roleLabel, whenWords } from "@/lib/words";
import { AudienceBadge } from "@/components/audience";
import { ApiWizard } from "@/components/data/api-wizard";
import { DbWizard } from "@/components/data/db-wizard";
import { Switch } from "@/components/skills/bits";
import { ConfirmAction, EASE, Empty, Notice, PageHero, Restricted, Stagger, StaggerItem } from "@/components/pro";
import { Button } from "@/components/ui";

type View = { mode: "list" } | { mode: "api" } | { mode: "db" };

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

/* How often a copy is refreshed. Rounding straight to hours turns anything
   under half an hour into "every 0 h" — the API's floor is 5 minutes, so the
   short intervals have to read in minutes. */
function syncWords(t: ReturnType<typeof useT>, seconds: number): string {
  return seconds < 3600
    ? t("data.sync.on.min", { m: Math.max(1, Math.round(seconds / 60)) })
    : t("data.sync.on", { h: Math.round(seconds / 3600) });
}

/* ---------- an API source ---------- */

function SourceCard({
  s,
  onChange,
  onRemove,
  onError,
}: {
  s: DataSource;
  onChange: (s: DataSource) => void;
  onRemove: () => Promise<void>;
  onError: (m: string) => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const { token } = useAuth();
  const [busy, setBusy] = useState(false);

  async function patch(body: Parameters<typeof api.sources.update>[2]) {
    setBusy(true);
    try {
      onChange(await api.sources.update(token, s.id, body));
    } catch (e) {
      onError(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  async function syncNow() {
    setBusy(true);
    try {
      const r = await api.sources.sync(token, s.id);
      onChange(r.source);
      if (r.status === "error") onError(r.error);
    } catch (e) {
      onError(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  const status =
    s.last_status === "ok"
      ? t("data.status.ok", { when: whenWords(s.last_synced_at) })
      : s.last_status === "unchanged"
        ? t("data.status.unchanged", { when: whenWords(s.last_checked_at) })
        : s.last_status === "error"
          ? t("data.status.error", { error: s.last_error })
          : t("data.status.never");

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5 card-ring">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
          <Globe className="size-4.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-display truncate text-[15.5px] font-semibold">{s.name}</p>
          <p className="truncate font-mono text-[11.5px] text-faint">{s.url}</p>
          <p className="mt-1 line-clamp-2 text-[13px] text-mut">{s.description}</p>
        </div>
        <ConfirmAction question={t("data.source.remove.q")} onConfirm={onRemove}>
          {(start) => (
            <button
              type="button"
              onClick={start}
              aria-label={t("common.delete")}
              className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
            >
              <Trash2 className="size-4" />
            </button>
          )}
        </ConfirmAction>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px]">
        <label className="flex items-center gap-2">
          <Switch on={s.skill_enabled} busy={busy} label={t("data.toggle.skill")} onChange={(on) => void patch({ skill_enabled: on })} />
          <span className={s.skill_enabled ? "" : "text-faint"}>{s.skill_enabled ? t("data.skill.on") : t("data.skill.off")}</span>
        </label>
        <label className="flex items-center gap-2">
          <Switch on={s.sync_enabled} busy={busy} label={t("data.toggle.sync")} onChange={(on) => void patch({ sync_enabled: on })} />
          <span className={s.sync_enabled ? "" : "text-faint"}>
            {s.sync_enabled ? syncWords(t, s.sync_interval_s) : t("data.sync.off")}
          </span>
        </label>
        <AudienceBadge value={s.data_class} />
        {s.required_roles.length > 0 && <span className="text-faint">{s.required_roles.map(roleLabel).join(", ")}</span>}
      </div>
      {s.sync_enabled && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-[12.5px]">
          <span className={s.last_status === "error" ? "text-bad" : "text-mut"}>
            {status}
            {s.last_records > 0 && ` · ${t(`data.records.${plural(locale, s.last_records)}`, { n: s.last_records })}`}
          </span>
          <Button size="sm" variant="ghost" onClick={syncNow} busy={busy}>
            <RefreshCw className="size-3.5" /> {t("data.syncNow")}
          </Button>
        </div>
      )}
    </div>
  );
}

/* ---------- a database ---------- */

function DbCard({
  c,
  onChange,
  onRemove,
  onError,
}: {
  c: Connector;
  onChange: (c: Connector) => void;
  onRemove: () => Promise<void>;
  onError: (m: string) => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const { token } = useAuth();
  const [busy, setBusy] = useState(false);
  const m = c.metadata;

  async function patch(body: Parameters<typeof api.databases.update>[2]) {
    setBusy(true);
    try {
      onChange(await api.databases.update(token, c.id, body));
    } catch (e) {
      onError(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  const kind = c.kind === "sql_mysql" ? "MySQL" : c.kind === "sql_postgres" ? "PostgreSQL" : "SQLite";
  const where = m.source === "upload" ? t("data.uploaded") : m.host ? `${m.host}/${m.database ?? ""}` : "";

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5 card-ring">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
          {m.source === "upload" ? <Upload className="size-4.5" /> : <DatabaseZap className="size-4.5" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-display truncate text-[15.5px] font-semibold">{c.name}</p>
          <p className="truncate text-[11.5px] text-faint">
            {kind}
            {where && ` · ${where}`}
            {m.table_count !== undefined && ` · ${t(`data.tables.${plural(locale, m.table_count)}`, { n: m.table_count })}`}
          </p>
          {m.summary && <p className="mt-1 line-clamp-2 text-[13px] text-mut">{m.summary}</p>}
        </div>
        <ConfirmAction question={t("data.db.remove.q")} onConfirm={onRemove}>
          {(start) => (
            <button
              type="button"
              onClick={start}
              aria-label={t("common.delete")}
              className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
            >
              <Trash2 className="size-4" />
            </button>
          )}
        </ConfirmAction>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px]">
        <label className="flex items-center gap-2">
          <Switch on={Boolean(m.free_query)} busy={busy} label={t("data.toggle.freeQuery")} onChange={(on) => void patch({ free_query: on })} />
          <span className={m.free_query ? "" : "text-faint"}>{m.free_query ? t("data.freeQuery.on") : t("data.freeQuery.off")}</span>
        </label>
        <label className="flex items-center gap-2">
          <Switch on={Boolean(m.knowledge)} busy={busy} label={t("data.toggle.knowledge")} onChange={(on) => void patch({ knowledge: on })} />
          <span className={m.knowledge ? "" : "text-faint"}>{t("data.knowledge.on")}</span>
        </label>
        {m.data_class && <AudienceBadge value={m.data_class} />}
        {(m.required_roles ?? []).length > 0 && <span className="text-faint">{m.required_roles!.map(roleLabel).join(", ")}</span>}
      </div>
    </div>
  );
}

/* ---------- the page ---------- */

export default function DataPage() {
  const t = useT();
  const { token, me } = useAuth();
  const [sources, setSources] = useState<DataSource[]>([]);
  const [databases, setDatabases] = useState<Connector[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [view, setView] = useState<View>({ mode: "list" });
  const [notice, setNotice] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const canAuthor = me?.can_author_skills ?? false;

  const load = useCallback(async () => {
    if (!token || !canAuthor) return;
    try {
      const [s, c] = await Promise.all([api.sources.list(token), api.connectors.list(token)]);
      setSources(s.sources);
      // only databases that came through the guided flow carry metadata
      setDatabases(c.connectors.filter((x) => x.kind !== "rest" && x.metadata && Object.keys(x.metadata).length > 0));
    } catch (e) {
      setNotice({ tone: "bad", text: errorWords((e as ApiError).message) });
    } finally {
      setLoaded(true);
    }
  }, [token, canAuthor]);
  useLoad(load);

  const say = useCallback((tone: "good" | "bad", text: string) => {
    setNotice({ tone, text });
    setTimeout(() => setNotice(null), 5000);
  }, []);

  if (!me) return null;
  if (!canAuthor) {
    return (
      <Restricted
        what={t("data.restricted.what")}
        who={t("data.restricted.who")}
        yourRole={me.roles.map(roleLabel).join(", ")}
      />
    );
  }

  if (view.mode !== "list") {
    const isApi = view.mode === "api";
    return (
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: EASE }} className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-accent-soft text-accent">
            {isApi ? <Globe className="size-5" /> : <DatabaseZap className="size-5" />}
          </span>
          <h2 className="font-display text-[22px] font-bold leading-tight">{isApi ? t("data.api.title") : t("data.db.title")}</h2>
        </div>
        <div className="rounded-3xl border border-line bg-surface p-6 [box-shadow:var(--shadow)] sm:p-8">
          {isApi ? (
            <ApiWizard
              onDone={(s) => {
                setSources((all) => [...all, s]);
                say("good", t("data.saved.api"));
                setView({ mode: "list" });
              }}
              onCancel={() => setView({ mode: "list" })}
            />
          ) : (
            <DbWizard
              onDone={(c) => {
                setDatabases((all) => [...all.filter((x) => x.id !== c.id), c]);
                say("good", t("data.saved.db"));
                setView({ mode: "list" });
              }}
              onCancel={() => setView({ mode: "list" })}
            />
          )}
        </div>
      </motion.div>
    );
  }

  const nothing = loaded && sources.length === 0 && databases.length === 0;

  return (
    <Stagger className="flex flex-col gap-6">
      <PageHero
        eyebrow={t("data.eyebrow")}
        title={t("data.title")}
        lead={t("data.lead")}
        actions={
          <>
            <Button variant="cta" onClick={() => setView({ mode: "api" })}>
              <Globe className="size-4" /> {t("data.api.cta")}
            </Button>
            <Button onClick={() => setView({ mode: "db" })}>
              <DatabaseZap className="size-4" /> {t("data.db.cta")}
            </Button>
          </>
        }
      />

      <AnimatePresence>
        {notice && (
          <StaggerItem rise={0}>
            <Notice tone={notice.tone}>{notice.text}</Notice>
          </StaggerItem>
        )}
      </AnimatePresence>

      {nothing && (
        <StaggerItem>
          <div className="rounded-3xl border border-line bg-surface">
            <Empty
              icon={<Plus className="size-6" />}
              title={t("data.empty")}
              action={
                <div className="flex flex-wrap gap-2">
                  <Button variant="soft" onClick={() => setView({ mode: "api" })}>{t("data.api.cta")}</Button>
                  <Button variant="soft" onClick={() => setView({ mode: "db" })}>{t("data.db.cta")}</Button>
                </div>
              }
            />
          </div>
        </StaggerItem>
      )}

      {sources.length > 0 && (
        <StaggerItem>
          <h3 className="font-display mb-3 text-[15px] font-semibold">{t("data.sources.title")}</h3>
          <div className="grid gap-4 lg:grid-cols-2">
            {sources.map((s) => (
              <SourceCard
                key={s.id}
                s={s}
                onChange={(n) => setSources((all) => all.map((x) => (x.id === n.id ? n : x)))}
                onRemove={async () => {
                  await api.sources.remove(token, s.id);
                  setSources((all) => all.filter((x) => x.id !== s.id));
                  say("good", t("data.removed"));
                }}
                onError={(m) => say("bad", m)}
              />
            ))}
          </div>
        </StaggerItem>
      )}

      {databases.length > 0 && (
        <StaggerItem>
          <h3 className="font-display mb-3 text-[15px] font-semibold">{t("data.dbs.title")}</h3>
          <div className="grid gap-4 lg:grid-cols-2">
            {databases.map((c) => (
              <DbCard
                key={c.id}
                c={c}
                onChange={(n) => setDatabases((all) => all.map((x) => (x.id === n.id ? n : x)))}
                onRemove={async () => {
                  await api.databases.remove(token, c.id);
                  setDatabases((all) => all.filter((x) => x.id !== c.id));
                  say("good", t("data.removed"));
                }}
                onError={(m) => say("bad", m)}
              />
            ))}
          </div>
        </StaggerItem>
      )}
    </Stagger>
  );
}
