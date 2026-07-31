"use client";

/* Administration — §12's "accounts, tenants" and §15's proactive alerts.
   Tenants are the platform operator's (KIT's) view; accounts and alerts belong
   to each company's own admin. */

import {
  AlertTriangle,
  BellRing,
  Building2,
  Copy,
  KeyRound,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  LANGUAGE_LABELS,
  type Account,
  type AlertRule,
  type Language,
  type SkillInfo,
  type Tenant,
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
} from "@/components/ui";
import { AssistantsSkeleton } from "@/components/skeleton";

const ROLES = [
  "employee", "hr", "finance", "legal", "qa", "skill_author", "admin", "ceo",
];

const LANGUAGE_OPTIONS = (Object.keys(LANGUAGE_LABELS) as Language[]).map((v) => ({
  value: v,
  label: LANGUAGE_LABELS[v],
}));

const INTERVALS = [
  { value: "300", label: "Every 5 minutes" },
  { value: "3600", label: "Hourly" },
  { value: "21600", label: "Every 6 hours" },
  { value: "86400", label: "Daily" },
];

function relative(ts: number): string {
  if (!ts) return "never";
  const secs = Math.round(Date.now() / 1000 - ts);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export default function AdminPage() {
  const { token, me } = useAuth();
  const [loading, setLoading] = useState(true);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [error, setError] = useState("");
  /** A minted token is shown exactly once — only its hash is stored. */
  const [issued, setIssued] = useState<{ user: string; token: string } | null>(null);

  const isOperator = me?.roles.includes("platform_admin") ?? false;
  const isAdmin =
    isOperator || (me?.roles ?? []).some((r) => r === "admin" || r === "ceo");

  const refresh = useCallback(async () => {
    if (!token) return;
    const [a, al, sk] = await Promise.all([
      api.accounts.list(token).catch(() => ({ accounts: [] })),
      api.alerts.list(token).catch(() => ({ alerts: [] })),
      api.skills(token).catch(() => ({ skills: [] })),
    ]);
    setAccounts(a.accounts);
    setAlerts(al.alerts);
    setSkills(sk.skills);
    if (isOperator) {
      const t = await api.tenants.list(token).catch(() => ({ tenants: [] }));
      setTenants(t.tenants);
    }
    setLoading(false);
  }, [token, isOperator]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (me && !isAdmin) {
    return (
      <EmptyState
        icon={<ShieldCheck className="size-6" />}
        title="Administration is restricted"
        hint="Managing accounts and alerts needs an admin role in your company."
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
        {issued && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="rounded-xl border border-accent/30 bg-accent-soft px-4 py-3.5"
          >
            <p className="flex items-center gap-2 text-[13.5px] font-semibold text-accent-strong">
              <KeyRound className="size-4" /> Access token for {issued.user}
            </p>
            <p className="mt-1 text-[12.5px] text-mut">
              Copy it now — only its hash is stored, so it cannot be shown again.
            </p>
            <div className="mt-2.5 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-lg bg-surface px-3 py-2 font-mono text-[12.5px]">
                {issued.token}
              </code>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigator.clipboard?.writeText(issued.token)}
              >
                <Copy className="size-3.5" /> Copy
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setIssued(null)}>
                Done
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="grid gap-6 xl:grid-cols-2">
        {isOperator && (
          <TenantsCard
            tenants={tenants}
            onError={setError}
            onChanged={refresh}
          />
        )}

        <AccountsCard
          accounts={accounts}
          onError={setError}
          onChanged={refresh}
          onIssued={setIssued}
        />

        <AlertsCard
          alerts={alerts}
          skills={skills}
          onError={setError}
          onChanged={refresh}
        />
      </div>
    </div>
  );
}

/* ---------------- tenants ---------------- */

function TenantsCard({
  tenants,
  onError,
  onChanged,
}: {
  tenants: Tenant[];
  onError: (m: string) => void;
  onChanged: () => void;
}) {
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [language, setLanguage] = useState<Language>("auto");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      await api.tenants.create(token, { id, name, default_language: language });
      setId("");
      setName("");
      setOpen(false);
      onChanged();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "Could not create the tenant");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Tenants"
        sub="Companies on the platform"
        icon={<Building2 className="size-4" />}
        right={
          <Button size="sm" variant="soft" onClick={() => setOpen((o) => !o)}>
            <Plus className="size-3.5" /> Onboard
          </Button>
        }
      />
      <div className="flex flex-col gap-2 p-5 pt-0">
        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mb-2 rounded-xl border border-line p-3.5">
                <Label>Slug</Label>
                <Input
                  value={id}
                  onChange={(e) => setId(e.target.value)}
                  placeholder="dusti"
                  className="font-mono"
                />
                <Label>Company name</Label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Dusti Pharma"
                />
                <Label>Default answer language</Label>
                <Picker
                  value={language}
                  onChange={(v) => setLanguage(v as Language)}
                  options={LANGUAGE_OPTIONS}
                  ariaLabel="Default language"
                />
                <div className="mt-3.5 flex gap-2">
                  <Button size="sm" onClick={create} busy={busy} disabled={!id || !name}>
                    Create
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {tenants.map((t, i) => (
          <Rise key={t.id} delay={i * 0.04}>
            <div className="flex items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-3">
              <div className="min-w-0">
                <p className="truncate text-[14px] font-semibold">{t.name}</p>
                <p className="font-mono text-[11.5px] text-mut">
                  {t.id} · {LANGUAGE_LABELS[t.default_language]}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Chip tone={t.active ? "good" : "neutral"}>
                  {t.active ? "active" : "suspended"}
                </Chip>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    api.tenants
                      .setActive(token, t.id, !t.active)
                      .then(onChanged)
                      .catch(() => onError("Could not update the tenant"))
                  }
                >
                  {t.active ? "Suspend" : "Resume"}
                </Button>
              </div>
            </div>
          </Rise>
        ))}
        {!tenants.length && (
          <p className="text-[13px] text-mut">
            No tenants yet. The rollout order is Koinoti → Evar → Dusti Pharma.
          </p>
        )}
      </div>
    </Card>
  );
}

/* ---------------- accounts ---------------- */

function AccountsCard({
  accounts,
  onError,
  onChanged,
  onIssued,
}: {
  accounts: Account[];
  onError: (m: string) => void;
  onChanged: () => void;
  onIssued: (v: { user: string; token: string }) => void;
}) {
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [userId, setUserId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [roles, setRoles] = useState<string[]>(["employee"]);
  const [language, setLanguage] = useState<Language>("auto");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const res = await api.accounts.create(token, {
        user_id: userId,
        display_name: displayName,
        roles,
        language,
      });
      onIssued({ user: res.account.id, token: res.token });
      setUserId("");
      setDisplayName("");
      setRoles(["employee"]);
      setOpen(false);
      onChanged();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "Could not create the account");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="People"
        sub={`${accounts.length} account(s)`}
        icon={<Users className="size-4" />}
        right={
          <Button size="sm" variant="soft" onClick={() => setOpen((o) => !o)}>
            <UserPlus className="size-3.5" /> Add
          </Button>
        }
      />
      <div className="flex flex-col gap-2 p-5 pt-0">
        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mb-2 rounded-xl border border-line p-3.5">
                <Label>User id</Label>
                <Input
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  placeholder="qa1"
                  className="font-mono"
                />
                <Label>Display name</Label>
                <Input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="QA lead"
                />
                <Label>Roles</Label>
                <div className="flex flex-wrap gap-2">
                  {ROLES.map((role) => {
                    const on = roles.includes(role);
                    return (
                      <button
                        key={role}
                        onClick={() =>
                          setRoles(
                            on ? roles.filter((r) => r !== role) : [...roles, role],
                          )
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
                <Label>Answer language</Label>
                <Picker
                  value={language}
                  onChange={(v) => setLanguage(v as Language)}
                  options={LANGUAGE_OPTIONS}
                  ariaLabel="Account language"
                />
                <div className="mt-3.5 flex gap-2">
                  <Button size="sm" onClick={create} busy={busy} disabled={!userId}>
                    Create &amp; issue token
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {accounts.map((a, i) => (
          <Rise key={a.id} delay={i * 0.04}>
            <div className="flex items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-3">
              <div className="min-w-0">
                <p className="truncate text-[14px] font-semibold">
                  {a.display_name || a.id}
                </p>
                <p className="truncate text-[11.5px] text-mut">
                  <span className="font-mono">{a.id}</span> · {a.roles.join(", ")}
                  {a.language !== "auto" && ` · ${LANGUAGE_LABELS[a.language]}`}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {!a.active && <Chip tone="neutral">suspended</Chip>}
                <button
                  title="Rotate token"
                  onClick={() =>
                    api.accounts
                      .rotate(token, a.id)
                      .then((r) => onIssued({ user: a.id, token: r.token }))
                      .catch(() => onError("Could not rotate the token"))
                  }
                  className="grid size-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-ink"
                >
                  <RefreshCw className="size-3.5" />
                </button>
                <button
                  title={a.active ? "Suspend" : "Reactivate"}
                  onClick={() =>
                    api.accounts
                      .setActive(token, a.id, !a.active)
                      .then(onChanged)
                      .catch(() => onError("Could not update the account"))
                  }
                  className="grid size-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-ink"
                >
                  <ShieldCheck className="size-3.5" />
                </button>
                <button
                  title="Delete"
                  onClick={() =>
                    api.accounts.remove(token, a.id).then(onChanged).catch(() => {})
                  }
                  className="grid size-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            </div>
          </Rise>
        ))}
        {!accounts.length && (
          <p className="text-[13px] text-mut">
            No accounts yet. Each person gets their own token and role set.
          </p>
        )}
      </div>
    </Card>
  );
}

/* ---------------- alerts ---------------- */

function AlertsCard({
  alerts,
  skills,
  onError,
  onChanged,
}: {
  alerts: AlertRule[];
  skills: SkillInfo[];
  onError: (m: string) => void;
  onChanged: () => void;
}) {
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [skill, setSkill] = useState("");
  const [interval, setInterval] = useState("3600");
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [ran, setRan] = useState<Record<string, string>>({});

  const create = async () => {
    setBusy(true);
    try {
      await api.alerts.create(token, {
        name,
        skill_name: skill,
        interval_s: Number(interval),
        condition: "rows_returned",
        message_template: template,
      });
      setName("");
      setTemplate("");
      setOpen(false);
      onChanged();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "Could not create the alert");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="xl:col-span-2">
      <CardHeader
        title="Proactive alerts"
        sub="The system writes to you — no one has to ask"
        icon={<BellRing className="size-4" />}
        right={
          <Button
            size="sm"
            variant="soft"
            onClick={() => setOpen((o) => !o)}
            disabled={!skills.length}
          >
            <Plus className="size-3.5" /> New rule
          </Button>
        }
      />
      <div className="flex flex-col gap-2 p-5 pt-0">
        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mb-2 grid gap-4 rounded-xl border border-line p-3.5 sm:grid-cols-2">
                <div>
                  <Label>Rule name</Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Batch expiring"
                  />
                </div>
                <div>
                  <Label>Watches skill</Label>
                  <Picker
                    value={skill}
                    onChange={setSkill}
                    options={skills.map((s) => ({
                      value: s.name,
                      label: s.name,
                      hint: s.description,
                    }))}
                    placeholder="Choose a skill…"
                    ariaLabel="Skill"
                  />
                </div>
                <div>
                  <Label>Check every</Label>
                  <Picker
                    value={interval}
                    onChange={setInterval}
                    options={INTERVALS}
                    ariaLabel="Interval"
                  />
                </div>
                <div>
                  <Label>Message</Label>
                  <Input
                    value={template}
                    onChange={(e) => setTemplate(e.target.value)}
                    placeholder="{count} batch(es) expiring"
                  />
                </div>
                <div className="sm:col-span-2">
                  <p className="mb-3 text-[11.5px] text-faint">
                    Fires when the skill returns any rows. The rule runs with your
                    own roles — it can never read more than you can.
                  </p>
                  <div className="flex gap-2">
                    <Button size="sm" onClick={create} busy={busy} disabled={!name || !skill}>
                      Create rule
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {alerts.map((a, i) => (
          <Rise key={a.id} delay={i * 0.04}>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-3">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-[14px] font-semibold">
                  {a.name}
                  {!a.enabled && <Chip tone="neutral">paused</Chip>}
                  {a.last_error && (
                    <Chip tone="bad">
                      <AlertTriangle className="size-3" /> failing
                    </Chip>
                  )}
                </p>
                <p className="truncate text-[11.5px] text-mut">
                  <span className="font-mono">{a.skill_name}</span> · every{" "}
                  {Math.round(a.interval_s / 60)}m · last run {relative(a.last_run_at)}
                  {a.last_fired_at ? ` · last fired ${relative(a.last_fired_at)}` : ""}
                </p>
                {ran[a.id] && (
                  <p className="mt-1 text-[11.5px] text-accent-strong">{ran[a.id]}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    api.alerts
                      .run(token, a.id)
                      .then((r) =>
                        setRan({
                          ...ran,
                          [a.id]: r.error
                            ? `Error: ${r.error}`
                            : r.fired
                              ? `Fired — ${r.message}`
                              : "Ran; condition not met",
                        }),
                      )
                      .catch(() => onError("Could not run the rule"))
                  }
                >
                  <Play className="size-3.5" /> Test
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    api.alerts
                      .setEnabled(token, a.id, !a.enabled)
                      .then(onChanged)
                      .catch(() => onError("Could not update the rule"))
                  }
                >
                  {a.enabled ? "Pause" : "Resume"}
                </Button>
                <button
                  title="Delete"
                  onClick={() =>
                    api.alerts.remove(token, a.id).then(onChanged).catch(() => {})
                  }
                  className="grid size-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            </div>
          </Rise>
        ))}
        {!alerts.length && (
          <p className="text-[13px] text-mut">
            {skills.length
              ? "No rules yet. A rule watches a verified skill and messages you when it returns something."
              : "Define a skill first — an alert watches a verified query."}
          </p>
        )}
      </div>
    </Card>
  );
}
