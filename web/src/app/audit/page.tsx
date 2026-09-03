"use client";

/* Activity — who did what, and whether it was allowed.
 *
 * The wire format is `noun.verb` plus a decision flag, which reads as machine
 * output. Here every event becomes a sentence, and the log is drawn as a
 * timeline so a run of events reads as a sequence of things that happened
 * rather than rows in a table.
 *
 * The signature is the blocked lane: refusals sit on the same spine as
 * everything else but in the refusal colour, so scanning the left edge tells
 * you instantly whether the day was quiet. That is the whole point of an audit
 * trail and it should be visible without reading a word. */

import {
  Activity,
  Ban,
  Search,
  RefreshCw,
  ShieldCheck,
  User,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useMemo, useState } from "react";
import { useT } from "@/i18n";
import { api, type ApiError, type AuditEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { actionWords, errorWords, roleLabel, whenWords } from "@/lib/words";
import { Button, Input } from "@/components/ui";
import {
  CountUp,
  EASE,
  Empty,
  Notice,
  PageHero,
  Restricted,
  Segmented,
  Stagger,
  StaggerItem,
} from "@/components/pro";
import { SkeletonText } from "@/components/skeleton";

type Lens = "all" | "allow" | "deny";

/** Events shown before the list asks to go further back. */
const PAGE = 40;

/** Who may read the log — mirrors the navigation gate in the shell. */
const READERS = new Set(["admin", "ceo"]);

export default function AuditPage() {
  const t = useT();
  const { token, me } = useAuth();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [lens, setLens] = useState<Lens>("all");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const r = await api.audit(token);
      setEvents(r.events);
      setProblem("");
    } catch (e) {
      setProblem(errorWords((e as ApiError).message));
      setEvents([]);
    } finally {
      setBusy(false);
    }
  }, [token]);

  /* The spinner belongs to the refresh button. The first load is covered by the
     skeleton, and raising the flag there would mean a setState inside the mount
     effect for a state nothing is showing yet. */
  const refresh = useCallback(() => {
    setBusy(true);
    void load();
  }, [load]);

  useLoad(load);

  const blocked = useMemo(
    () => (events ?? []).filter((e) => e.decision === "deny").length,
    [events],
  );

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (events ?? []).filter((e) => {
      if (lens !== "all" && e.decision !== lens) return false;
      if (!q) return true;
      return (
        e.user_id.toLowerCase().includes(q) ||
        actionWords(e.action).toLowerCase().includes(q) ||
        (e.resource ?? "").toLowerCase().includes(q)
      );
    });
  }, [events, lens, query]);

  /* Administrators and leadership may read the log. Anyone else meets the
     wall — as does a refusal from the server while `me` is still resolving,
     because a refusal is the interesting case and is never hidden without
     saying who can see it. */
  const mayRead = me ? me.roles.some((r) => READERS.has(r)) : undefined;
  const refused = problem !== "" && (events?.length ?? 0) === 0;
  if (mayRead === false || (mayRead === undefined && refused)) {
    return (
      <Stagger>
        <StaggerItem>
          <Restricted
            what={t("audit.restricted.what")}
            who={t("audit.restricted.who")}
            yourRole={me?.roles.map(roleLabel).join(", ")}
          />
        </StaggerItem>
      </Stagger>
    );
  }

  return (
    <Stagger className="flex flex-col gap-6">
      <PageHero
        eyebrow={t("audit.eyebrow")}
        title={t("audit.title")}
        lead={t("audit.lead")}
        art={
          events && events.length > 0 ? (
            <div className="flex gap-3">
              <Tally
                label={t("audit.tally.recorded")}
                value={events.length}
                tone="neutral"
                icon={<Activity className="size-4" />}
              />
              <Tally
                label={t("audit.tally.blocked")}
                value={blocked}
                tone={blocked > 0 ? "bad" : "good"}
                icon={
                  blocked > 0 ? (
                    <Ban className="size-4" />
                  ) : (
                    <ShieldCheck className="size-4" />
                  )
                }
              />
            </div>
          ) : undefined
        }
      />

      <StaggerItem>
        <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
            <Segmented
              value={lens}
              onChange={(l) => {
                setLens(l);
                setLimit(PAGE);
              }}
              ariaLabel={t("audit.lens.aria")}
              options={[
                { value: "all", label: t("audit.lens.all") },
                { value: "allow", label: t("audit.lens.allow") },
                { value: "deny", label: t("audit.lens.deny"), count: blocked },
              ]}
            />
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("audit.search")}
                  aria-label={t("audit.search.aria")}
                  className="w-60 pl-9"
                />
              </div>
              <Button variant="ghost" size="icon" onClick={refresh} busy={busy}>
                <RefreshCw className="size-4" />
              </Button>
            </div>
          </header>

          <div className="p-6 pt-5">
            {problem && (
              <div className="mb-4">
                <Notice tone="warn">{problem}</Notice>
              </div>
            )}

            {events === null ? (
              <SkeletonText lines={6} />
            ) : shown.length === 0 ? (
              <Empty
                icon={<Activity className="size-6" />}
                title={
                  events.length === 0
                    ? t("audit.empty.title")
                    : t("audit.noMatch.title")
                }
                hint={
                  events.length === 0
                    ? t("audit.empty.hint")
                    : t("audit.noMatch.hint")
                }
              />
            ) : (
              <>
                <ol className="relative flex flex-col">
                  {/* the spine */}
                  <span
                    aria-hidden
                    className="absolute bottom-3 left-[15.5px] top-3 w-0.5 rounded-full bg-line-strong/60"
                  />
                  <AnimatePresence initial={false}>
                    {shown.slice(0, limit).map((e, i) => (
                      <Event key={`${e.ts}-${i}`} e={e} i={i} />
                    ))}
                  </AnimatePresence>
                </ol>
                {shown.length > limit && (
                  <button
                    onClick={() => setLimit((l) => l + PAGE)}
                    className="mt-4 w-full cursor-pointer rounded-xl border border-line py-2.5 text-[13px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                  >
                    {t("audit.more", { n: shown.length - limit })}
                  </button>
                )}
              </>
            )}
          </div>
        </section>
      </StaggerItem>
    </Stagger>
  );
}

/* ---------- pieces ---------- */

function Tally({
  label,
  value,
  tone,
  icon,
}: {
  label: string;
  value: number;
  tone: "neutral" | "good" | "bad";
  icon: React.ReactNode;
}) {
  const cls = {
    neutral: "bg-surface-2 text-mut",
    good: "bg-good-soft text-good",
    bad: "bg-bad-soft text-bad",
  }[tone];
  return (
    <div className="rounded-2xl border border-line bg-surface px-4 py-3">
      <span className="flex items-center gap-2">
        <span className={`grid size-7 place-items-center rounded-lg ${cls}`}>
          {icon}
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-[0.09em] text-mut">
          {label}
        </span>
      </span>
      <CountUp
        value={value}
        className="font-display mt-1.5 block text-[24px] font-bold leading-none tabular-nums"
      />
    </div>
  );
}

/* Opaque handles (conn_cc1047a2…, skl_1cb3056b…) and internal component names
   tell a reader nothing. They stay available in the expanded detail, but the
   line itself only carries a resource when it's something a person recognises. */
const OPAQUE = /^[a-z]+_[0-9a-f]{8,}$/;
const INTERNAL = new Set(["knowledge", "orchestrator", "assistant"]);

function readableResource(r: string | undefined): string | null {
  if (!r || OPAQUE.test(r) || INTERNAL.has(r)) return null;
  return r;
}

function Event({ e, i }: { e: AuditEvent; i: number }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const denied = e.decision === "deny";
  const detail = Object.entries(e.detail ?? {}).filter(
    ([, v]) => v !== null && v !== "",
  );
  const resource = readableResource(e.resource);
  const hasMore = detail.length > 0 || e.ip || e.user_agent || e.resource;

  return (
    <motion.li
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3, delay: Math.min(i * 0.015, 0.3), ease: EASE }}
      className="relative flex gap-3.5 py-2"
    >
      {/* node on the spine — colour carries allow/deny at a glance */}
      <span
        className={`relative z-10 mt-1 grid size-8 shrink-0 place-items-center rounded-full border-2 border-surface ${
          denied ? "bg-bad-soft text-bad" : "bg-surface-2 text-mut"
        }`}
      >
        {denied ? <Ban className="size-3.5" /> : <User className="size-3.5" />}
      </span>

      <div className="min-w-0 flex-1 rounded-xl border border-transparent px-2 py-1 transition-colors hover:border-line hover:bg-surface-2">
        <button
          onClick={() => hasMore && setOpen((o) => !o)}
          className={`flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 text-left ${
            hasMore ? "cursor-pointer" : "cursor-default"
          }`}
        >
          <span className="text-[13.5px] font-semibold">{e.user_id}</span>
          <span className="text-[13.5px] text-mut">{actionWords(e.action)}</span>
          {denied && (
            <span className="rounded-md bg-bad-soft px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide text-bad">
              {t("audit.pill.blocked")}
            </span>
          )}
          <span className="ml-auto shrink-0 text-[12px] tabular-nums text-faint">
            {e.ts ? whenWords(e.ts) : ""}
          </span>
        </button>

        {resource && (
          <p className="truncate text-[12px] text-faint">{resource}</p>
        )}

        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: EASE }}
              className="overflow-hidden"
            >
              <dl className="mt-2 grid gap-x-6 gap-y-1 rounded-lg bg-bg-deep p-3 text-[12px] sm:grid-cols-2">
                {e.roles && e.roles.length > 0 && (
                  <Row
                    k={t("audit.row.signedAs")}
                    v={e.roles.map(roleLabel).join(", ")}
                  />
                )}
                {e.resource && <Row k={t("audit.row.appliedTo")} v={e.resource} />}
                {e.ip && <Row k={t("audit.row.from")} v={e.ip} />}
                {e.user_agent && <Row k={t("audit.row.device")} v={e.user_agent} />}
                {detail.map(([k, v]) => (
                  <Row key={k} k={k.replace(/_/g, " ")} v={String(v)} />
                ))}
              </dl>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.li>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex min-w-0 gap-2">
      <dt className="shrink-0 capitalize text-faint">{k}</dt>
      <dd className="min-w-0 truncate text-mut">{v}</dd>
    </div>
  );
}
