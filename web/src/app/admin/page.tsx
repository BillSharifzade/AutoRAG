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
 * and honest that it will not be shown again. */

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
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useState } from "react";
import {
  api,
  LANGUAGE_LABELS,
  type Account,
  type AlertRule,
  type ApiError,
  type Language,
  type SkillInfo,
  type Tenant,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { ROLES, errorWords, roleLabel, whenWords } from "@/lib/words";
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
   absent — they are granted by a platform operator, never from this screen. */
const GRANTABLE = ROLES.filter(
  (r) => !["platform_admin", "karag_engineer"].includes(r.value),
);

const HOW_OFTEN = [
  { value: "900", label: "Every 15 minutes" },
  { value: "3600", label: "Every hour" },
  { value: "21600", label: "Every 6 hours" },
  { value: "86400", label: "Once a day" },
];

type Tab = "people" | "alerts" | "companies";

export default function AdminPage() {
  const { token, me } = useAuth();

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
      setLookups(sk.skills);
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
            what="Only administrators manage people"
            who="Adding colleagues, changing what they can see and setting up alerts is limited to administrators and leadership at your company."
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
        eyebrow="Administration"
        title="Who's here, and what they can see"
        lead="Everyone gets their own access key and their own view of the company's knowledge. Change someone's role and it takes effect on their very next question — no waiting, no re-sync."
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
                    {handover.who}&rsquo;s access key
                  </h2>
                  <p className="mt-1 text-[13.5px] leading-relaxed text-mut">
                    Copy it now and give it to them directly. It exists only in
                    this box — close it and nobody, including you, can read it
                    again. If it goes missing, make a new one.
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
                          <Check className="size-4" /> Copied
                        </>
                      ) : (
                        <>
                          <Copy className="size-4" /> Copy
                        </>
                      )}
                    </Button>
                  </div>
                  <button
                    onClick={() => setHandover(null)}
                    className="mt-4 cursor-pointer text-[13px] font-semibold text-mut transition-colors hover:text-ink"
                  >
                    I&rsquo;ve saved it — close this
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
          ariaLabel="What to manage"
          options={[
            { value: "people", label: "People", count: people.length },
            { value: "alerts", label: "Alerts", count: alerts.length },
            ...(isOperator
              ? ([{ value: "companies", label: "Companies", count: companies.length }] as const)
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
  const [adding, setAdding] = useState(false);
  const [userId, setUserId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [roles, setRoles] = useState<string[]>(["employee"]);
  const [busy, setBusy] = useState(false);

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
            People at your company
          </h2>
          <p className="mt-0.5 text-[13px] text-mut">
            Each person sees only what their role covers — enforced every time
            they ask, not just at sign-in.
          </p>
        </div>
        {!adding && (
          <Button variant="cta" onClick={() => setAdding(true)}>
            <UserPlus className="size-4" /> Add someone
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
                    Their name
                  </label>
                  <Input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Nilufar Rahimova"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-[13px] font-semibold">
                    Sign-in ID
                  </label>
                  <Input
                    value={userId}
                    onChange={(e) => setUserId(e.target.value)}
                    placeholder="nilufar"
                    className="font-mono text-[13px]"
                  />
                  <p className="mt-1.5 text-[12px] text-faint">
                    Short, no spaces. Appears in the activity log.
                  </p>
                </div>
              </div>

              <p className="mb-2 mt-5 text-[13px] font-semibold">
                What should they be able to see?
              </p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {GRANTABLE.map((r) => {
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
                  Create their access key
                </Button>
                <Button variant="ghost" onClick={() => setAdding(false)}>
                  Cancel
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
            title="Nobody added yet"
            hint="Add your colleagues one at a time. Each gets their own key and only sees what their role allows."
            action={
              <Button variant="cta" onClick={() => setAdding(true)}>
                <UserPlus className="size-4" /> Add the first person
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
                        you
                      </span>
                    )}
                    {!p.active && (
                      <span className="rounded-md bg-warn-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-warn">
                        suspended
                      </span>
                    )}
                  </p>
                  <p className="truncate text-[12px] text-mut">
                    {p.roles.map(roleLabel).join(" · ")}
                  </p>
                </div>

                <button
                  onClick={async () => {
                    try {
                      const r = await api.accounts.rotate(token, p.id);
                      onKey(p.display_name || p.id, r.token);
                    } catch (e) {
                      onProblem(errorWords((e as ApiError).message));
                    }
                  }}
                  title="Give them a new key — the old one stops working"
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                >
                  <RefreshCw className="size-3.5" />
                  New key
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
                  {p.active ? "Suspend" : "Restore"}
                </button>

                <ConfirmAction
                  question={`Remove ${p.display_name || p.id}?`}
                  confirmLabel="Yes, remove"
                  onConfirm={async () => {
                    await api.accounts.remove(token, p.id).catch(() => {});
                    await onRefresh();
                  }}
                >
                  {(start) => (
                    <button
                      onClick={start}
                      aria-label={`Remove ${p.display_name || p.id}`}
                      className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </ConfirmAction>
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
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [lookup, setLookup] = useState("");
  const [every, setEvery] = useState("3600");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 className="font-display text-[16px] font-semibold">
            Messages that send themselves
          </h2>
          <p className="mt-0.5 text-[13px] text-mut">
            Instead of someone remembering to check, KARAG checks on a schedule
            and only speaks up when there&rsquo;s something to say.
          </p>
        </div>
        {!adding && lookups.length > 0 && (
          <Button variant="cta" onClick={() => setAdding(true)}>
            <Plus className="size-4" /> New alert
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
                  What should we call it?
                </label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Stock running low"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  What should it check?
                </label>
                <Picker
                  value={lookup}
                  onChange={setLookup}
                  placeholder="Choose a lookup…"
                  ariaLabel="Which lookup"
                  options={lookups.map((s) => ({
                    value: s.name,
                    label: s.description || s.name,
                  }))}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  How often?
                </label>
                <Picker
                  value={every}
                  onChange={setEvery}
                  ariaLabel="How often"
                  options={HOW_OFTEN}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  What should it say?
                </label>
                <Input
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Some items are running low"
                />
              </div>
              <div className="flex items-center gap-3 md:col-span-2">
                <Button
                  variant="cta"
                  busy={busy}
                  disabled={!name.trim() || !lookup}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api.alerts.create(token, {
                        name: name.trim(),
                        skill_name: lookup,
                        interval_s: Number(every),
                        condition: "rows_returned",
                        message_template: message.trim() || name.trim(),
                      });
                      setAdding(false);
                      setName("");
                      setLookup("");
                      setMessage("");
                      await onRefresh();
                    } catch (e) {
                      onProblem(errorWords((e as ApiError).message));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Create alert
                </Button>
                <Button variant="ghost" onClick={() => setAdding(false)}>
                  Cancel
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
            title="No alerts set up"
            hint={
              lookups.length === 0
                ? "Alerts run a live lookup on a schedule, so you'll need at least one lookup first."
                : "Pick something worth watching — stock levels, expiring batches, an overdue figure — and KARAG will keep an eye on it for you."
            }
            action={
              lookups.length > 0 ? (
                <Button variant="cta" onClick={() => setAdding(true)}>
                  <Plus className="size-4" /> Create one
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
                    {HOW_OFTEN.find((h) => h.value === String(a.interval_s))
                      ?.label ?? `Every ${Math.round(a.interval_s / 60)} min`}
                    {a.last_run_at
                      ? ` · last checked ${whenWords(a.last_run_at)}`
                      : " · not run yet"}
                    {a.last_error ? " · last check failed" : ""}
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
                  {a.enabled ? "Pause" : "Resume"}
                </button>
                <button
                  onClick={async () => {
                    await api.alerts.run(token, a.id).catch(() => {});
                    await onRefresh();
                  }}
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                >
                  <RefreshCw className="size-3.5" /> Check now
                </button>
                <ConfirmAction
                  question="Delete this alert?"
                  confirmLabel="Yes, delete"
                  onConfirm={async () => {
                    await api.alerts.remove(token, a.id).catch(() => {});
                    await onRefresh();
                  }}
                >
                  {(start) => (
                    <button
                      onClick={start}
                      aria-label={`Delete ${a.name}`}
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
  const [adding, setAdding] = useState(false);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [lang, setLang] = useState<Language>("auto");
  const [busy, setBusy] = useState(false);

  return (
    <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 className="font-display text-[16px] font-semibold">
            Companies on the platform
          </h2>
          <p className="mt-0.5 text-[13px] text-mut">
            Each one is sealed off from the others. No question asked in one can
            ever reach another&rsquo;s data.
          </p>
        </div>
        {!adding && (
          <Button variant="cta" onClick={() => setAdding(true)}>
            <Plus className="size-4" /> Add a company
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
            <div className="grid gap-4 border-b border-line bg-surface-2 p-6 md:grid-cols-3">
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  Company name
                </label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Dusti Pharma"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  Short code
                </label>
                <Input
                  value={id}
                  onChange={(e) => setId(e.target.value)}
                  placeholder="dusti"
                  className="font-mono text-[13px]"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold">
                  Default language
                </label>
                <Picker
                  value={lang}
                  onChange={(v) => setLang(v as Language)}
                  ariaLabel="Default language"
                  options={Object.entries(LANGUAGE_LABELS).map(([v, l]) => ({
                    value: v,
                    label: v === "auto" ? "Match the question" : l,
                  }))}
                />
              </div>
              <div className="flex items-center gap-3 md:col-span-3">
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
                        default_language: lang,
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
                  Add company
                </Button>
                <Button variant="ghost" onClick={() => setAdding(false)}>
                  Cancel
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
            title="No companies yet"
            hint="Each company gets its own sealed space for knowledge, people and data."
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
                        suspended
                      </span>
                    )}
                  </p>
                  <p className="truncate text-[12px] text-mut">
                    Added {whenWords(c.created_at)} · answers in{" "}
                    {c.default_language === "auto"
                      ? "whichever language is asked"
                      : LANGUAGE_LABELS[c.default_language]}
                  </p>
                </div>
                <button
                  onClick={async () => {
                    await api.tenants
                      .setActive(token, c.id, !c.active)
                      .catch(() => {});
                    await onRefresh();
                  }}
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                >
                  {c.active ? "Suspend" : "Restore"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
