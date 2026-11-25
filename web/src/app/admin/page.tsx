"use client";

/* Admin — the people, the companies, and the messages that send themselves.
 *
 * Three jobs that used to sit in one long column of forms, now separated so
 * you're only ever looking at one of them. Roles are named after what someone
 * does rather than what the matrix calls them, and every role card says what
 * that person will be able to see.
 *
 * The signature is the handover panel: a new access key exists exactly once,
 * and the screen treats that as the important moment it is — big, copyable,
 * and honest that it will not be shown again.
 *
 * There is no language setting anywhere here on purpose: the assistant always
 * answers in the language of the question. */

import {
  AlarmClock,
  Building2,
  Check,
  Copy,
  KeyRound,
  Plus,
  RefreshCw,
  Trash2,
  UserPlus,
  Users,
  Wallet,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useState } from "react";
import {
  api,
  type Account,
  type AlertRule,
  type ApiError,
  type SkillInfo,
  type Tenant,
} from "@/lib/api";
import { humanise } from "@/components/assistants/helpers";
import { humanTitle } from "@/lib/skills";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { errorWords, roleLabel, roles, whenWords } from "@/lib/words";
import { useT } from "@/i18n";
import { Button, Input, Picker } from "@/components/ui";
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
} from "@/components/pro";
import { AssistantsSkeleton } from "@/components/skeleton";

/* Roles someone can be given here. Platform-level roles are deliberately
   absent — they are granted by a platform operator, never from this screen.
   Read inside a component so the labels follow the interface language. */
const PLATFORM_ROLES = ["platform_admin", "karag_engineer"];
function grantable() {
  return roles().filter((r) => !PLATFORM_ROLES.includes(r.value));
}

/* Check intervals the picker offers; the words live in the dictionary. */
const HOW_OFTEN = [
  { value: "900", key: "admin.every.15m" },
  { value: "3600", key: "admin.every.1h" },
  { value: "21600", key: "admin.every.6h" },
  { value: "86400", key: "admin.every.1d" },
];

type Tab = "people" | "alerts" | "companies";

export default function AdminPage() {
  const { token, me } = useAuth();
  const t = useT();

  const isAdmin = Boolean(
    me?.roles.some((r) => ["admin", "ceo", "platform_admin"].includes(r)),
  );
  const isOperator = Boolean(me?.roles.includes("platform_admin"));

  const [tab, setTab] = useState<Tab>("people");
  const [loading, setLoading] = useState(true);
  const [people, setPeople] = useState<Account[]>([]);
  const [companies, setCompanies] = useState<Tenant[]>([]);
  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [lookups, setLookups] = useState<SkillInfo[]>([]);
  const [problem, setProblem] = useState("");

  /* the one-time key handover */
  const [handover, setHandover] = useState<{ who: string; key: string } | null>(
    null,
  );
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      const [a, al, sk] = await Promise.all([
        api.accounts.list(token),
        api.alerts.list(token).catch(() => ({ alerts: [] })),
        api.skills(token).catch(() => ({ skills: [] })),
      ]);
      setPeople(a.accounts);
      setAlerts(al.alerts);
      // alerts run lookups on company data — not file makers, admin or
      // platform tools
      setLookups(sk.skills.filter((x) => (x.category ?? "data") === "data"));
      if (isOperator) {
        const t = await api.tenants.list(token).catch(() => ({ tenants: [] }));
        setCompanies(t.tenants);
      }
      setProblem("");
    } catch (e) {
      setProblem(errorWords((e as ApiError).message));
    } finally {
      setLoading(false);
    }
  }, [token, isOperator]);

  useLoad(refresh);

  if (me && !isAdmin) {
    return (
      <Stagger>
        <StaggerItem>
          <Restricted
            what={t("admin.restricted.what")}
            who={t("admin.restricted.who")}
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
        eyebrow={t("admin.eyebrow")}
        title={t("admin.title")}
        lead={t("admin.lead")}
      />

      {problem && (
        <StaggerItem>
          <Notice tone="bad">{problem}</Notice>
        </StaggerItem>
      )}

      {/* the one-time key — the most consequential thing on this page */}
      <AnimatePresence>
        {handover && (
          <motion.div
            initial={{ opacity: 0, y: -12, height: 0 }}
            animate={{ opacity: 1, y: 0, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.35, ease: EASE }}
            className="overflow-hidden"
          >
            <section className="relative overflow-hidden rounded-3xl border border-accent/40 bg-surface p-7 [box-shadow:var(--glow)]">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0 -z-10"
                style={{
                  background:
                    "radial-gradient(600px 220px at 20% -20%, color-mix(in oklab, var(--accent) 18%, transparent), transparent 70%)",
                }}
              />
              <div className="flex items-start gap-4">
                <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                  <KeyRound className="size-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="font-display text-[18px] font-semibold">
                    {t("admin.key.title", { who: handover.who })}
                  </h2>
                  <p className="mt-1 text-[13.5px] leading-relaxed text-mut">
                    {t("admin.key.sub")}
                  </p>
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    <code className="min-w-0 flex-1 overflow-x-auto rounded-xl border border-line bg-bg-deep px-4 py-3 font-mono text-[14px] tracking-tight">
                      {handover.key}
                    </code>
                    <Button
                      variant="cta"
                      onClick={async () => {
                        await navigator.clipboard
                          .writeText(handover.key)
                          .catch(() => {});
                        setCopied(true);
                        setTimeout(() => setCopied(false), 2000);
                      }}
                    >
                      {copied ? (
                        <>
                          <Check className="size-4" /> {t("common.copied")}
                        </>
                      ) : (
                        <>
                          <Copy className="size-4" /> {t("common.copy")}
                        </>
                      )}
                    </Button>
                  </div>
                  <button
                    onClick={() => setHandover(null)}
                    className="mt-4 cursor-pointer text-[13px] font-semibold text-mut transition-colors hover:text-ink"
                  >
                    {t("admin.key.close")}
                  </button>
                </div>
              </div>
            </section>
          </motion.div>
        )}
      </AnimatePresence>

      <StaggerItem>
        <Segmented
          value={tab}
          onChange={setTab}
          ariaLabel={t("admin.tabs")}
          options={[
            { value: "people", label: t("admin.tab.people"), count: people.length },
            { value: "alerts", label: t("admin.tab.alerts"), count: alerts.length },
            ...(isOperator
              ? ([
                  {
                    value: "companies",
                    label: t("admin.tab.companies"),
                    count: companies.length,
                  },
                ] as const)
              : []),
          ]}
        />
      </StaggerItem>

      {tab === "people" && (
        <StaggerItem>
          <People
            people={people}
            onRefresh={refresh}
            onKey={(who, key) => {
              setHandover({ who, key });
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            onProblem={setProblem}
            meId={me?.user_id}
          />
        </StaggerItem>
      )}

      {tab === "alerts" && (
        <StaggerItem>
          <Alerts
            alerts={alerts}
            lookups={lookups}
            onRefresh={refresh}
            onProblem={setProblem}
          />
        </StaggerItem>
      )}

      {tab === "companies" && isOperator && (
        <StaggerItem>
          <Companies
            companies={companies}
            onRefresh={refresh}
            onProblem={setProblem}
          />
        </StaggerItem>
      )}
    </Stagger>
  );
}

/* ---------------- people ---------------- */

function People({
  people,
  onRefresh,
  onKey,
  onProblem,
  meId,
}: {
  people: Account[];
  onRefresh: () => Promise<void>;
  onKey: (who: string, key: string) => void;
  onProblem: (s: string) => void;
  meId?: string;
}) {
  const { token } = useAuth();
  const t = useT();
  const [adding, setAdding] = useState(false);
  const [userId, setUserId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [roles, setRoles] = useState<string[]>(["employee"]);
  const [busy, setBusy] = useState(false);
  const offered = grantable();

  async function add() {
    setBusy(true);
    try {
      const r = await api.accounts.create(token, {
        user_id: userId.trim(),
        display_name: displayName.trim(),
        roles,
      });
      onKey(displayName.trim() || userId.trim(), r.token);
      setAdding(false);
      setUserId("");
      setDisplayName("");
      setRoles(["employee"]);
      await onRefresh();
    } catch (e) {
      onProblem(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 className="font-display text-[16px] font-semibold">
            {t("admin.people.title")}
          </h2>
          <p className="mt-0.5 text-[13px] text-mut">{t("admin.people.sub")}</p>
        </div>
        {!adding && (
          <Button variant="cta" onClick={() => setAdding(true)}>
            <UserPlus className="size-4" /> {t("admin.people.add")}
          </Button>
        )}
      </header>

      <AnimatePresence initial={false}>
        {adding && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="border-b border-line bg-surface-2 p-6">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-[13px] font-semibold">
                    {t("admin.people.name")}
                  </label>
                  <Input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder={t("admin.people.namePh")}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-[13px] font-semibold">
                    {t("admin.people.id")}
                  </label>
                  <Input
                    value={userId}
                    onChange={(e) => setUserId(e.target.value)}
                    placeholder={t("admin.people.idPh")}
                    className="font-mono text-[13px]"
                  />
                  <p className="mt-1.5 text-[12px] text-faint">
                    {t("admin.people.idHint")}
                  </p>
                </div>
              </div>

              <p className="mb-2 mt-5 text-[13px] font-semibold">
                {t("admin.people.roles")}
              </p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {offered.map((r) => {
                  const on = roles.includes(r.value);
                  return (
                    <button
                      key={r.value}
                      onClick={() =>
                        setRoles((prev) =>
                          prev.includes(r.value)
                            ? prev.filter((x) => x !== r.value)
                            : [...prev, r.value],
                        )
                      }
                      className={`cursor-pointer rounded-xl border p-3 text-left transition-colors ${
                        on
                          ? "border-accent bg-accent-soft/50"
                          : "border-line hover:border-line-strong"
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <span
                          className={`grid size-4 shrink-0 place-items-center rounded-[5px] border transition-colors ${
                            on
                              ? "border-accent bg-accent text-accent-ink"
                              : "border-line-strong"
                          }`}
                        >
                          {on && <Check className="size-2.5" />}
                        </span>
                        <span className="text-[13px] font-semibold">
                          {r.label}
                        </span>
                      </span>
                      <span className="mt-1 block text-[11.5px] leading-relaxed text-mut">
                        {r.who}
                      </span>
                    </button>
                  );
                })}
              </div>

              <div className="mt-5 flex items-center gap-3">
                <Button
                  variant="cta"
                  onClick={add}
                  busy={busy}
                  disabled={!userId.trim() || roles.length === 0}
                >
                  {t("admin.people.create")}
                </Button>
                <Button variant="ghost" onClick={() => setAdding(false)}>
                  {t("common.cancel")}
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="p-6 pt-4">
        {people.length === 0 ? (
          <Empty
            icon={<Users className="size-6" />}
            title={t("admin.people.empty")}
            hint={t("admin.people.emptyHint")}
            action={
              <Button variant="cta" onClick={() => setAdding(true)}>
                <UserPlus className="size-4" /> {t("admin.people.addFirst")}
              </Button>
            }
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {people.map((p) => (
              <motion.li
                key={p.id}
                layout
                className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-4 py-3"
              >
                <span
                  className={`grid size-9 shrink-0 place-items-center rounded-lg text-[12px] font-bold ${
                    p.active
                      ? "bg-accent-soft text-accent"
                      : "bg-surface-2 text-faint"
                  }`}
                >
                  {(p.display_name || p.id).slice(0, 2).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 truncate text-[14px] font-semibold">
                    {p.display_name || p.id}
                    {p.id === meId && (
                      <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10.5px] font-semibold text-mut">
                        {t("admin.people.you")}
                      </span>
                    )}
                    {!p.active && (
                      <span className="rounded-md bg-warn-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-warn">
                        {t("admin.people.suspended")}
                      </span>
                    )}
                    {p.source === "config" && (
                      <span
                        title={t("admin.people.configHint")}
                        className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10.5px] font-semibold text-mut"
                      >
                        {t("admin.people.config")}
                      </span>
                    )}
                  </p>
                  <p className="truncate text-[12px] text-mut">
                    {p.roles.map(roleLabel).join(" · ")}
                  </p>
                </div>

                {/* A config-token person is managed in the server's
                    configuration; nothing here could change their access. */}
                {p.source !== "config" && (<>
                <button
                  onClick={async () => {
                    try {
                      const r = await api.accounts.rotate(token, p.id);
                      onKey(p.display_name || p.id, r.token);
                    } catch (e) {
                      onProblem(errorWords((e as ApiError).message));
                    }
                  }}
                  title={t("admin.people.rotateHint")}
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                >
                  <RefreshCw className="size-3.5" />
                  {t("admin.people.rotate")}
                </button>

                <button
                  onClick={async () => {
                    await api.accounts
                      .setActive(token, p.id, !p.active)
                      .catch(() => {});
                    await onRefresh();
                  }}
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                >
                  {p.active ? t("admin.suspend") : t("admin.restore")}
                </button>

                <ConfirmAction
                  question={t("admin.people.removeQ", { name: p.display_name || p.id })}
                  onConfirm={async () => {
                    await api.accounts.remove(token, p.id).catch(() => {});
                    await onRefresh();
                  }}
                >
                  {(start) => (
                    <button
                      onClick={start}
                      aria-label={t("admin.people.removeAria", {
                        name: p.display_name || p.id,
                      })}
                      className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </ConfirmAction>
                </>)}
              </motion.li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

/* ---------------- alerts ---------------- */

function Alerts({
  alerts,
  lookups,
  onRefresh,
  onProblem,
}: {
  alerts: AlertRule[];
  lookups: SkillInfo[];
  onRefresh: () => Promise<void>;
  onProblem: (s: string) => void;
}) {
  const { token } = useAuth();
  const t = useT();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [lookup, setLookup] = useState("");
  const [every, setEvery] = useState("3600");
  const [message, setMessage] = useState("");
  const [args, setArgs] = useState<Record<string, string>>({});
  const [condition, setCondition] = useState<AlertRule["condition"]>("rows_returned");
  const [field, setField] = useState("");
  const [op, setOp] = useState("<");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const howOften = HOW_OFTEN.map((h) => ({ value: h.value, label: t(h.key) }));
  const chosen = lookups.find((s) => s.name === lookup);
  // `purpose` is the lookup's note for the activity log — filled from the
  // alert's name rather than asked for
  const params = Object.entries(chosen?.input_schema?.properties ?? {}).filter(
    ([k]) => k !== "purpose",
  );
  const wantsPurpose = Boolean(chosen?.input_schema?.properties?.purpose);
  const required = new Set(chosen?.input_schema?.required ?? []);
  const argsOk = params.every(([k]) => !required.has(k) || (args[k] ?? "").trim());
  const conditionOk = condition !== "field_compare" || (field.trim() && target.trim());

  function reset() {
    setAdding(false);
    setName("");
    setLookup("");
    setMessage("");
    setArgs({});
    setCondition("rows_returned");
    setField("");
    setTarget("");
  }

  /** typed as the lookup's schema declares, so "10" reaches it as 10 */
  function typedArgs(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const [k, spec] of params) {
      const raw = (args[k] ?? "").trim();
      if (!raw) continue;
      if (spec.type === "integer" || spec.type === "number") out[k] = Number(raw);
      else if (spec.type === "boolean") out[k] = raw === "true";
      else out[k] = raw;
    }
    if (wantsPurpose) out.purpose = `alert: ${name.trim()}`;
    return out;
  }

  return (
    <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 className="font-display text-[16px] font-semibold">
            {t("admin.alerts.title")}
          </h2>
          <p className="mt-0.5 text-[13px] text-mut">{t("admin.alerts.sub")}</p>
        </div>
        {!adding && lookups.length > 0 && (
          <Button variant="cta" onClick={() => setAdding(true)}>
            <Plus className="size-4" /> {t("admin.alerts.new")}
          </Button>
        )}
      </header>

      <AnimatePresence initial={false}>
        {adding && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="grid gap-4 border-b border-line bg-surface-2 p-6 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  {t("admin.alerts.name")}
                </label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("admin.alerts.namePh")}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  {t("admin.alerts.lookup")}
                </label>
                <Picker
                  value={lookup}
                  onChange={setLookup}
                  placeholder={t("admin.alerts.lookupPh")}
                  ariaLabel={t("admin.alerts.lookupAria")}
                  options={lookups.map((s) => ({
                    value: s.name,
                    label: s.label || humanTitle(s.name),
                  }))}
                />
                {/* an authored lookup's description is the author's own words;
                    a connection's is written for the model — not shown */}
                {chosen?.description && !chosen.label && (
                  <p className="mt-1.5 line-clamp-2 text-[12px] text-mut">{chosen.description}</p>
                )}
              </div>
              {params.length > 0 && (
                <div className="grid gap-3 md:col-span-2 md:grid-cols-2">
                  {params.map(([key, spec]) => (
                    <div key={key} className={key === "sql" ? "md:col-span-2" : undefined}>
                      <label className="mb-1.5 block text-[13px] font-semibold">
                        {key === "sql" ? t("admin.alerts.sql") : humanise(key)}
                        {required.has(key) ? " *" : ""}
                      </label>
                      <Input
                        value={args[key] ?? ""}
                        onChange={(e) => setArgs((a) => ({ ...a, [key]: e.target.value }))}
                        placeholder={key === "sql" ? "SELECT COUNT(*) AS n FROM …" : spec.description ?? ""}
                        inputMode={spec.type === "integer" || spec.type === "number" ? "decimal" : undefined}
                        className={key === "sql" ? "font-mono text-[12.5px]" : undefined}
                      />
                    </div>
                  ))}
                </div>
              )}
              <div className="md:col-span-2">
                <label className="mb-1.5 block text-[13px] font-semibold">
                  {t("admin.alerts.when")}
                </label>
                <div className="grid gap-3 md:grid-cols-[minmax(0,1.3fr)_repeat(3,minmax(0,1fr))]">
                  <Picker
                    value={condition}
                    onChange={(v) => setCondition(v as AlertRule["condition"])}
                    ariaLabel={t("admin.alerts.when")}
                    options={[
                      { value: "rows_returned", label: t("admin.alerts.when.rows") },
                      { value: "field_compare", label: t("admin.alerts.when.field") },
                      { value: "always", label: t("admin.alerts.when.always") },
                    ]}
                  />
                  {condition === "field_compare" && (
                    <>
                      <Input
                        value={field}
                        onChange={(e) => setField(e.target.value)}
                        placeholder={t("admin.alerts.fieldPh")}
                        aria-label={t("admin.alerts.fieldPh")}
                      />
                      <Picker
                        value={op}
                        onChange={setOp}
                        ariaLabel={t("admin.alerts.op")}
                        options={["<", "<=", ">", ">=", "==", "!="].map((o) => ({
                          value: o,
                          label: t(`admin.alerts.op.${o}`),
                        }))}
                      />
                      <Input
                        value={target}
                        onChange={(e) => setTarget(e.target.value)}
                        placeholder={t("admin.alerts.valuePh")}
                        aria-label={t("admin.alerts.valuePh")}
                      />
                    </>
                  )}
                </div>
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  {t("admin.alerts.every")}
                </label>
                <Picker
                  value={every}
                  onChange={setEvery}
                  ariaLabel={t("admin.alerts.everyAria")}
                  options={howOften}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  {t("admin.alerts.message")}
                </label>
                <Input
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder={t("admin.alerts.messagePh")}
                />
                <p className="mt-1.5 text-[12px] text-faint">{t("admin.alerts.messageHint")}</p>
              </div>
              <div className="flex items-center gap-3 md:col-span-2">
                <Button
                  variant="cta"
                  busy={busy}
                  disabled={!name.trim() || !lookup || !argsOk || !conditionOk}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const raw = target.trim();
                      await api.alerts.create(token, {
                        name: name.trim(),
                        skill_name: lookup,
                        arguments: typedArgs(),
                        interval_s: Number(every),
                        condition,
                        condition_config:
                          condition === "field_compare"
                            ? {
                                field: field.trim(),
                                op,
                                value: raw !== "" && !Number.isNaN(Number(raw)) ? Number(raw) : raw,
                              }
                            : {},
                        message_template: message.trim() || name.trim(),
                      });
                      reset();
                      await onRefresh();
                    } catch (e) {
                      onProblem(errorWords((e as ApiError).message));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {t("admin.alerts.create")}
                </Button>
                <Button variant="ghost" onClick={reset}>
                  {t("common.cancel")}
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="p-6 pt-4">
        {alerts.length === 0 ? (
          <Empty
            icon={<AlarmClock className="size-6" />}
            title={t("admin.alerts.empty")}
            hint={
              lookups.length === 0
                ? t("admin.alerts.emptyNoLookup")
                : t("admin.alerts.emptyHint")
            }
            action={
              lookups.length > 0 ? (
                <Button variant="cta" onClick={() => setAdding(true)}>
                  <Plus className="size-4" /> {t("admin.alerts.createOne")}
                </Button>
              ) : undefined
            }
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {alerts.map((a) => (
              <li
                key={a.id}
                className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-4 py-3"
              >
                <span
                  className={`grid size-9 shrink-0 place-items-center rounded-lg ${
                    a.enabled
                      ? "bg-accent-soft text-accent"
                      : "bg-surface-2 text-faint"
                  }`}
                >
                  <AlarmClock className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-semibold">{a.name}</p>
                  <p className="truncate text-[12px] text-mut">
                    {howOften.find((h) => h.value === String(a.interval_s))
                      ?.label ??
                      t("admin.every.min", { n: Math.round(a.interval_s / 60) })}
                    {" · "}
                    {a.last_run_at
                      ? t("admin.alerts.lastChecked", { when: whenWords(a.last_run_at) })
                      : t("admin.alerts.notRun")}
                    {a.last_error ? ` · ${t("admin.alerts.failed")}` : ""}
                  </p>
                </div>
                <button
                  onClick={async () => {
                    await api.alerts
                      .setEnabled(token, a.id, !a.enabled)
                      .catch(() => {});
                    await onRefresh();
                  }}
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                >
                  {a.enabled ? t("admin.alerts.pause") : t("admin.alerts.resume")}
                </button>
                <button
                  onClick={async () => {
                    await api.alerts.run(token, a.id).catch(() => {});
                    await onRefresh();
                  }}
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                >
                  <RefreshCw className="size-3.5" /> {t("admin.alerts.runNow")}
                </button>
                <ConfirmAction
                  question={t("admin.alerts.deleteQ")}
                  confirmLabel={t("admin.alerts.deleteYes")}
                  onConfirm={async () => {
                    await api.alerts.remove(token, a.id).catch(() => {});
                    await onRefresh();
                  }}
                >
                  {(start) => (
                    <button
                      onClick={start}
                      aria-label={t("admin.alerts.deleteAria", { name: a.name })}
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
  );
}

/* ---------------- companies (platform operator only) ---------------- */

/* A company's monthly AI budget: this month's spend against the cap, and a
   small inline editor. An empty field removes the cap. Only a platform
   operator sees this list at all, and the API enforces the same. */
function BudgetEditor({
  company,
  onSaved,
  onProblem,
}: {
  company: Tenant;
  onSaved: () => Promise<void>;
  onProblem: (s: string) => void;
}) {
  const { token } = useAuth();
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const b = company.budget;
  const usd = (n: number) =>
    n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

  if (editing) {
    return (
      <form
        className="flex shrink-0 items-center gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          const raw = value.trim().replace(",", ".");
          const next = raw === "" ? null : Number(raw);
          if (next !== null && (!Number.isFinite(next) || next < 0)) {
            onProblem(t("admin.budget.invalid"));
            return;
          }
          setSaving(true);
          try {
            await api.tenants.setBudget(token, company.id, next);
            setEditing(false);
            await onSaved();
          } catch (err) {
            onProblem(errorWords((err as ApiError).message));
          } finally {
            setSaving(false);
          }
        }}
      >
        <Input
          autoFocus
          inputMode="decimal"
          aria-label={t("admin.budget.label")}
          placeholder={t("admin.budget.none")}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="h-8 w-32"
        />
        <Button type="submit" disabled={saving}>
          {t("common.save")}
        </Button>
        <Button variant="ghost" type="button" onClick={() => setEditing(false)}>
          {t("common.cancel")}
        </Button>
      </form>
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        setValue(b?.budget_usd != null ? String(b.budget_usd) : "");
        setEditing(true);
      }}
      title={t("admin.budget.label")}
      className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12.5px] text-mut transition-colors hover:border-line-strong hover:text-ink"
    >
      <Wallet className="size-3.5" />
      {b?.budget_usd != null
        ? t("admin.budget.of", { spent: usd(b.spent_usd), budget: usd(b.budget_usd) })
        : t("admin.budget.unlimited", { spent: usd(b?.spent_usd ?? 0) })}
    </button>
  );
}

function Companies({
  companies,
  onRefresh,
  onProblem,
}: {
  companies: Tenant[];
  onRefresh: () => Promise<void>;
  onProblem: (s: string) => void;
}) {
  const { token } = useAuth();
  const t = useT();
  const [adding, setAdding] = useState(false);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 className="font-display text-[16px] font-semibold">
            {t("admin.companies.title")}
          </h2>
          <p className="mt-0.5 text-[13px] text-mut">{t("admin.companies.sub")}</p>
        </div>
        {!adding && (
          <Button variant="cta" onClick={() => setAdding(true)}>
            <Plus className="size-4" /> {t("admin.companies.add")}
          </Button>
        )}
      </header>

      <AnimatePresence initial={false}>
        {adding && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="grid gap-4 border-b border-line bg-surface-2 p-6 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  {t("admin.companies.name")}
                </label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("admin.companies.namePh")}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  {t("admin.companies.code")}
                </label>
                <Input
                  value={id}
                  onChange={(e) => setId(e.target.value)}
                  placeholder={t("admin.companies.codePh")}
                  className="font-mono text-[13px]"
                />
              </div>
              <div className="flex items-center gap-3 md:col-span-2">
                <Button
                  variant="cta"
                  busy={busy}
                  disabled={!id.trim() || !name.trim()}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api.tenants.create(token, {
                        id: id.trim(),
                        name: name.trim(),
                      });
                      setAdding(false);
                      setId("");
                      setName("");
                      await onRefresh();
                    } catch (e) {
                      onProblem(errorWords((e as ApiError).message));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {t("admin.companies.add")}
                </Button>
                <Button variant="ghost" onClick={() => setAdding(false)}>
                  {t("common.cancel")}
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="p-6 pt-4">
        {companies.length === 0 ? (
          <Empty
            icon={<Building2 className="size-6" />}
            title={t("admin.companies.empty")}
            hint={t("admin.companies.emptyHint")}
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {companies.map((c) => (
              <li
                key={c.id}
                className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-4 py-3"
              >
                <span
                  className={`grid size-9 shrink-0 place-items-center rounded-lg ${
                    c.active
                      ? "bg-accent-soft text-accent"
                      : "bg-surface-2 text-faint"
                  }`}
                >
                  <Building2 className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 truncate text-[14px] font-semibold">
                    {c.name}
                    {!c.active && (
                      <span className="rounded-md bg-warn-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-warn">
                        {t("admin.companies.suspended")}
                      </span>
                    )}
                  </p>
                  <p className="truncate text-[12px] text-mut">
                    {t("admin.companies.added", { when: whenWords(c.created_at) })}
                  </p>
                </div>
                <BudgetEditor company={c} onSaved={onRefresh} onProblem={onProblem} />
                <button
                  onClick={async () => {
                    await api.tenants
                      .setActive(token, c.id, !c.active)
                      .catch(() => {});
                    await onRefresh();
                  }}
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                >
                  {c.active ? t("admin.suspend") : t("admin.restore")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
