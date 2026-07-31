"use client";

/* Audit trail (admin-only): every ingest / retrieval / skill run / ask, with
   its allow-or-deny decision and the device + identity it came from. Deny rows
   prove fail-closed RBAC. Search, decision filter, and expandable detail. */

import {
  CheckCircle2,
  Globe,
  MonitorSmartphone,
  RefreshCw,
  ScrollText,
  Search,
  ShieldCheck,
  UserRound,
  XCircle,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, type ApiError, type AuditEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Card, CardHeader, EmptyState, Rise } from "@/components/ui";
import { AuditSkeleton } from "@/components/skeleton";

/* ---------- helpers ---------- */

/** Parse a User-Agent into a friendly "Browser · OS" label. */
function parseUA(ua?: string): { browser: string; os: string } {
  if (!ua) return { browser: "Unknown", os: "" };
  let browser = "Unknown";
  if (/Edg\//.test(ua)) browser = "Edge";
  else if (/OPR\/|Opera/.test(ua)) browser = "Opera";
  else if (/Firefox\//.test(ua)) browser = "Firefox";
  else if (/Chrome\//.test(ua)) browser = "Chrome";
  else if (/Safari\//.test(ua)) browser = "Safari";
  else if (/curl\//.test(ua)) browser = "curl";
  else if (/python|httpx|requests/i.test(ua)) browser = "Script";

  let os = "";
  if (/Windows NT 10/.test(ua)) os = "Windows";
  else if (/Windows/.test(ua)) os = "Windows";
  else if (/Android/.test(ua)) os = "Android";
  else if (/iPhone|iPad|iOS/.test(ua)) os = "iOS";
  else if (/Mac OS X/.test(ua)) os = "macOS";
  else if (/Linux/.test(ua)) os = "Linux";
  return { browser, os };
}

function relTime(ts?: number): string {
  if (!ts) return "";
  const secs = Math.max(0, Date.now() / 1000 - ts);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function absTime(ts?: number): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

function DecisionPill({ decision }: { decision: AuditEvent["decision"] }) {
  return decision === "allow" ? (
    <span className="inline-flex items-center gap-1 rounded-md bg-good-soft px-2 py-0.5 text-[11.5px] font-semibold text-good">
      <CheckCircle2 className="size-3" /> allow
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-md bg-bad-soft px-2 py-0.5 text-[11.5px] font-semibold text-bad">
      <XCircle className="size-3" /> deny
    </span>
  );
}

/* ---------- stat strip ---------- */

function Stat({
  icon,
  label,
  value,
  tone = "accent",
}: {
  icon: ReactNode;
  label: string;
  value: number | string;
  tone?: "accent" | "good" | "bad";
}) {
  const toneCls = {
    accent: "bg-accent-soft text-accent",
    good: "bg-good-soft text-good",
    bad: "bg-bad-soft text-bad",
  }[tone];
  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
      <span className={`grid size-9 place-items-center rounded-lg ${toneCls}`}>
        {icon}
      </span>
      <div>
        <p className="font-display text-[20px] font-bold leading-none tabular-nums">
          {value}
        </p>
        <p className="mt-1 text-[11.5px] text-mut">{label}</p>
      </div>
    </div>
  );
}

type DecisionFilter = "all" | "allow" | "deny";

/* ---------- row ---------- */

function EventRow({ e, i }: { e: AuditEvent; i: number }) {
  const [open, setOpen] = useState(false);
  const ua = parseUA(e.user_agent);
  const hasDetail = e.detail && Object.keys(e.detail).length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(i * 0.02, 0.25), duration: 0.3 }}
      className="rounded-xl border border-line bg-surface transition-colors hover:border-line-strong"
    >
      <button
        onClick={() => hasDetail && setOpen((o) => !o)}
        className={`flex w-full items-center gap-4 px-4 py-3 text-left ${
          hasDetail ? "cursor-pointer" : "cursor-default"
        }`}
      >
        {/* action + decision */}
        <div className="flex w-40 shrink-0 items-center gap-2.5">
          <DecisionPill decision={e.decision} />
          <span className="truncate text-[13px] font-semibold">{e.action}</span>
        </div>

        {/* identity */}
        <div className="hidden w-40 shrink-0 items-center gap-1.5 sm:flex">
          <UserRound className="size-3.5 shrink-0 text-faint" />
          <span className="truncate font-mono text-[12px]">{e.user_id}</span>
          {e.roles && e.roles.length > 0 && (
            <span className="truncate rounded bg-accent-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-accent-strong">
              {e.roles.join(" · ")}
            </span>
          )}
        </div>

        {/* device */}
        <div className="hidden min-w-0 flex-1 items-center gap-4 md:flex">
          <span
            className="inline-flex items-center gap-1.5 text-[12px] text-mut"
            title={e.ip || "unknown"}
          >
            <Globe className="size-3.5 shrink-0 text-faint" />
            {e.ip || "—"}
          </span>
          <span
            className="inline-flex items-center gap-1.5 text-[12px] text-mut"
            title={e.user_agent || "unknown"}
          >
            <MonitorSmartphone className="size-3.5 shrink-0 text-faint" />
            {ua.browser}
            {ua.os ? ` · ${ua.os}` : ""}
          </span>
        </div>

        {/* time */}
        <span
          className="ml-auto shrink-0 text-[12px] tabular-nums text-faint"
          title={absTime(e.ts)}
        >
          {relTime(e.ts)}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && hasDetail && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="border-t border-line px-4 py-3">
              <div className="mb-2 flex flex-wrap gap-x-6 gap-y-1 text-[12px] text-mut sm:hidden">
                <span>User: {e.user_id}</span>
                {e.ip && <span>IP: {e.ip}</span>}
              </div>
              <pre className="overflow-x-auto rounded-lg border border-line bg-bg-deep p-3 font-mono text-[11.5px] leading-relaxed text-mut">
                {JSON.stringify({ resource: e.resource, ...e.detail }, null, 2)}
              </pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/* ---------- page ---------- */

export default function AuditPage() {
  const { token } = useAuth();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");
  const [decision, setDecision] = useState<DecisionFilter>("all");

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const d = await api.audit(token);
      setEvents([...d.events].reverse().slice(0, 300));
    } catch (e) {
      setError((e as ApiError).message);
      setEvents(null);
    } finally {
      setBusy(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    const allow = events?.filter((e) => e.decision === "allow").length ?? 0;
    const deny = events?.filter((e) => e.decision === "deny").length ?? 0;
    return { total: events?.length ?? 0, allow, deny };
  }, [events]);

  const filtered = useMemo(() => {
    if (!events) return null;
    const q = filter.trim().toLowerCase();
    return events.filter((e) => {
      if (decision !== "all" && e.decision !== decision) return false;
      if (!q) return true;
      return [
        e.action,
        e.decision,
        e.user_id,
        e.resource,
        e.ip,
        e.user_agent,
        (e.roles ?? []).join(" "),
        JSON.stringify(e.detail),
      ]
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
  }, [events, filter, decision]);

  if (!events && !error) {
    return (
      <Rise>
        <AuditSkeleton />
      </Rise>
    );
  }

  const DECISIONS: { key: DecisionFilter; label: string }[] = [
    { key: "all", label: "All" },
    { key: "allow", label: "Allow" },
    { key: "deny", label: "Deny" },
  ];

  return (
    <Rise className="flex flex-col gap-6">
      {!error && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat
            icon={<ScrollText className="size-4" />}
            label="Total events"
            value={counts.total}
          />
          <Stat
            icon={<CheckCircle2 className="size-4" />}
            label="Allowed"
            value={counts.allow}
            tone="good"
          />
          <Stat
            icon={<XCircle className="size-4" />}
            label="Denied (fail-closed)"
            value={counts.deny}
            tone="bad"
          />
        </div>
      )}

      <Card>
        <CardHeader
          icon={<ScrollText className="size-4" />}
          title="Audit trail"
          sub="Newest first · last 300 events · IP, device & role captured · admin only."
          right={
            <div className="flex items-center gap-2">
              <div className="hidden items-center gap-1 rounded-xl border border-line bg-surface-2 p-1 md:flex">
                {DECISIONS.map((d) => {
                  const active = d.key === decision;
                  return (
                    <button
                      key={d.key}
                      onClick={() => setDecision(d.key)}
                      className={`relative rounded-lg px-2.5 py-1 text-[12px] font-semibold transition-colors ${
                        active ? "text-white" : "text-mut hover:text-ink"
                      }`}
                    >
                      {active && (
                        <motion.span
                          layoutId="audit-decision-pill"
                          className="absolute inset-0 rounded-lg bg-accent"
                          transition={{ type: "spring", stiffness: 420, damping: 34 }}
                        />
                      )}
                      <span className="relative z-10">{d.label}</span>
                    </button>
                  );
                })}
              </div>
              <div className="relative hidden sm:block">
                <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
                <input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Filter…"
                  className="h-9 w-44 rounded-xl border border-line bg-surface pl-8.5 pr-3 text-[13px] transition-colors placeholder:text-faint hover:border-line-strong focus:border-accent"
                />
              </div>
              <Button variant="soft" size="sm" onClick={load} busy={busy}>
                <RefreshCw className="size-3.5" /> Refresh
              </Button>
            </div>
          }
        />

        <div className="p-6 pt-4">
          {error && (
            <EmptyState
              icon={<ScrollText className="size-6" />}
              title="Not available"
              hint={error}
            />
          )}

          {filtered && filtered.length === 0 && (
            <EmptyState
              icon={<ScrollText className="size-6" />}
              title={filter || decision !== "all" ? "No matches" : "No events yet"}
              hint={
                filter || decision !== "all"
                  ? "Try a different filter."
                  : "Ask a question or ingest a document — every action lands here."
              }
            />
          )}

          {filtered && filtered.length > 0 && (
            <div className="flex flex-col gap-2">
              {filtered.map((e, i) => (
                <EventRow key={`${e.ts}-${i}`} e={e} i={i} />
              ))}
            </div>
          )}
        </div>
      </Card>

      {!error && (
        <p className="flex items-center justify-center gap-1.5 text-center text-[12px] text-faint">
          <ShieldCheck className="size-3.5" />
          IP, browser/OS and role are captured from each request. A device&apos;s
          MAC / hardware ID isn&apos;t transmitted over the web, so it can&apos;t
          be recorded here.
        </p>
      )}
    </Rise>
  );
}
