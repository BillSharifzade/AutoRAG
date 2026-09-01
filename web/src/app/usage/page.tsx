"use client";

/* Usage dashboard — the billing basis, visualized: count-up stat tiles, a
   token-budget speedometer, an input/output donut, per-request averages and
   a stacked activity timeline. All charts are hand-built SVG/CSS + Motion. */

import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Coins,
  Gauge as GaugeIcon,
  ChartColumn,
  ChartPie,
  MessageSquareText,
  RefreshCw,
  Scale,
  Wallet,
} from "lucide-react";
import {
  animate,
  motion,
  useMotionValue,
  useTransform,
  type MotionValue,
} from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ApiError, type UsageEvent, type UsageTotals } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { Button, Card, CardHeader, EmptyState, Rise } from "@/components/ui";
import { UsageSkeleton } from "@/components/skeleton";

/* Demo billing envelope the speedometer measures against. */
const TOKEN_BUDGET = 1_000_000;

const SLATE = "var(--accent-2)";
const RED = "var(--accent)";

const TILES = [
  { key: "requests", label: "Requests", icon: MessageSquareText },
  { key: "input_tokens", label: "Input tokens", icon: ArrowDownToLine },
  { key: "output_tokens", label: "Output tokens", icon: ArrowUpFromLine },
  { key: "total_tokens", label: "Total tokens", icon: Coins },
] as const;

/* ---------- time range ---------- */

type RangeKey = "all" | "today" | "7d" | "30d";

const RANGES: { key: RangeKey; label: string; days: number | null }[] = [
  { key: "all", label: "Overall", days: null },
  { key: "today", label: "Today", days: 0 },
  { key: "7d", label: "7 days", days: 7 },
  { key: "30d", label: "30 days", days: 30 },
];

/** Unix-seconds cutoff for a range, or null for "all". "today" is local midnight. */
function rangeCutoff(key: RangeKey): number | null {
  if (key === "all") return null;
  if (key === "today") {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.getTime() / 1000;
  }
  const days = RANGES.find((r) => r.key === key)?.days ?? 0;
  return Date.now() / 1000 - days * 86400;
}

/** Overall uses the backend's true cumulative totals; a bounded range is
    recomputed from the (timestamped) event stream. */
function deriveView(usage: UsageTotals, key: RangeKey): UsageTotals {
  const cutoff = rangeCutoff(key);
  if (cutoff === null) return usage;
  const events = usage.events.filter((e) => e.ts >= cutoff);
  let input = 0;
  let output = 0;
  for (const e of events) {
    input += e.input_tokens;
    output += e.output_tokens;
  }
  // Cost is priced per model on the server; scale the all-time figure by this
  // range's share of tokens rather than inventing a second price list here.
  const share = usage.total_tokens > 0 ? (input + output) / usage.total_tokens : 0;
  return {
    tenant_id: usage.tenant_id,
    requests: events.length,
    input_tokens: input,
    output_tokens: output,
    total_tokens: input + output,
    cost_usd: usage.cost_usd * share,
    unpriced_models: usage.unpriced_models,
    by_model: usage.by_model,
    events,
  };
}

/** USD with enough precision to be useful at low volume. */
function money(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function useAnimatedNumber(value: number): MotionValue<string> {
  const mv = useMotionValue(0);
  const rounded = useTransform(mv, (v) => Math.round(v).toLocaleString("en-US"));
  useEffect(() => {
    const controls = animate(mv, value, {
      duration: 0.9,
      ease: [0.2, 0.8, 0.2, 1],
    });
    return controls.stop;
  }, [value, mv]);
  return rounded;
}

function CountUp({ value, className }: { value: number; className: string }) {
  const rounded = useAnimatedNumber(value);
  return <motion.p className={className}>{rounded}</motion.p>;
}

/* ---------- speedometer ---------- */

const GAUGE_START = -120; // degrees from 12 o'clock, sweeping 240° clockwise
const GAUGE_SWEEP = 240;

function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = (deg * Math.PI) / 180;
  return { x: cx + r * Math.sin(rad), y: cy - r * Math.cos(rad) };
}

function Speedometer({ fraction }: { fraction: number }) {
  const pct = Math.min(Math.max(fraction, 0), 1);
  const cx = 130;
  const cy = 120;
  const r = 92;
  const a = polar(cx, cy, r, GAUGE_START);
  const b = polar(cx, cy, r, GAUGE_START + GAUGE_SWEEP);
  const track = `M ${a.x} ${a.y} A ${r} ${r} 0 1 1 ${b.x} ${b.y}`;

  /* One motion value drives everything — needle, arc fill and the percent
     readout all track the same sweep. */
  const angle = useMotionValue(GAUGE_START);
  const progress = useTransform(angle, (d) => (d - GAUGE_START) / GAUGE_SWEEP);
  const dash = useTransform(progress, (p) => `${Math.max(p, 0.001)} 1`);
  const pctText = useTransform(progress, (p) => `${(p * 100).toFixed(1)}%`);

  useEffect(() => {
    let active = true;
    const target = GAUGE_START + GAUGE_SWEEP * pct;
    const run = async () => {
      // startup sweep: peg the needle to the end of the dial…
      await animate(angle, GAUGE_START + GAUGE_SWEEP, {
        duration: 0.7,
        ease: [0.45, 0, 0.55, 1],
      });
      if (!active) return;
      // …then spring back down to the real value.
      animate(angle, target, {
        type: "spring",
        stiffness: 50,
        damping: 13,
        mass: 1.1,
      });
    };
    void run();
    return () => {
      active = false;
      angle.stop();
    };
  }, [pct, angle]);

  const nx = useTransform(angle, (d) => polar(cx, cy, 66, d).x);
  const ny = useTransform(angle, (d) => polar(cx, cy, 66, d).y);
  const tailX = useTransform(angle, (d) => polar(cx, cy, -14, d).x);
  const tailY = useTransform(angle, (d) => polar(cx, cy, -14, d).y);

  const ticks = Array.from({ length: 13 }, (_, i) => {
    const deg = GAUGE_START + (GAUGE_SWEEP / 12) * i;
    const p1 = polar(cx, cy, r - 12, deg);
    const p2 = polar(cx, cy, r - (i % 3 === 0 ? 22 : 17), deg);
    return { p1, p2, major: i % 3 === 0 };
  });

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 260 180" className="w-full max-w-[300px]">
        <defs>
          <linearGradient id="gauge-grad" x1="0%" y1="100%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={SLATE} />
            <stop offset="70%" stopColor={RED} />
            <stop offset="100%" stopColor={RED} />
          </linearGradient>
        </defs>

        <path
          d={track}
          fill="none"
          stroke="var(--line)"
          strokeWidth="13"
          strokeLinecap="round"
        />
        <motion.path
          d={track}
          fill="none"
          stroke="url(#gauge-grad)"
          strokeWidth="13"
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray={dash}
        />

        {ticks.map(({ p1, p2, major }, i) => (
          <line
            key={i}
            x1={p1.x}
            y1={p1.y}
            x2={p2.x}
            y2={p2.y}
            stroke={major ? "var(--mut)" : "var(--line-strong)"}
            strokeWidth={major ? 2 : 1.2}
            strokeLinecap="round"
          />
        ))}

        {/* needle */}
        <motion.line
          x1={tailX}
          y1={tailY}
          x2={nx}
          y2={ny}
          stroke={RED}
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r="7" fill={RED} />
        <circle cx={cx} cy={cy} r="3" fill="var(--surface)" />
      </svg>
      <motion.p className="font-display -mt-8 text-[30px] font-bold leading-none tracking-tight tabular-nums">
        {pctText}
      </motion.p>
      <p className="mt-1.5 text-[12.5px] text-mut">
        of a {TOKEN_BUDGET.toLocaleString("en-US")} token budget
      </p>
    </div>
  );
}

/* ---------- donut ---------- */

function Donut({ input, output }: { input: number; output: number }) {
  const total = input + output;
  const inFrac = total > 0 ? input / total : 0.5;
  const outFrac = total > 0 ? output / total : 0.5;
  const r = 70;
  const totalText = useAnimatedNumber(total);

  return (
    <div className="flex flex-col items-center gap-5">
      <div className="relative">
        <svg viewBox="0 0 180 180" className="w-full max-w-[210px]">
          <circle
            cx="90"
            cy="90"
            r={r}
            fill="none"
            stroke="var(--line)"
            strokeWidth="16"
          />
          <motion.circle
            cx="90"
            cy="90"
            r={r}
            fill="none"
            stroke={SLATE}
            strokeWidth="16"
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray="1 1"
            transform="rotate(-90 90 90)"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: Math.max(inFrac - 0.004, 0.001) }}
            transition={{ duration: 1, ease: [0.2, 0.8, 0.2, 1] }}
          />
          <motion.circle
            cx="90"
            cy="90"
            r={r}
            fill="none"
            stroke={RED}
            strokeWidth="16"
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray="1 1"
            transform={`rotate(${-90 + inFrac * 360} 90 90)`}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: Math.max(outFrac - 0.004, 0.001) }}
            transition={{ duration: 1, delay: 0.15, ease: [0.2, 0.8, 0.2, 1] }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <motion.p className="font-display text-[24px] font-bold leading-none tracking-tight tabular-nums">
            {totalText}
          </motion.p>
          <p className="mt-1 text-[11.5px] text-mut">tokens</p>
        </div>
      </div>
      <div className="flex items-center gap-5 text-[12.5px]">
        <span className="flex items-center gap-2">
          <span className="size-2.5 rounded-full" style={{ background: SLATE }} />
          <span className="text-mut">Input</span>
          <span className="font-semibold tabular-nums">
            {total > 0 ? `${Math.round(inFrac * 100)}%` : "—"}
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span className="size-2.5 rounded-full" style={{ background: RED }} />
          <span className="text-mut">Output</span>
          <span className="font-semibold tabular-nums">
            {total > 0 ? `${Math.round(outFrac * 100)}%` : "—"}
          </span>
        </span>
      </div>
    </div>
  );
}

/* ---------- per-request averages ---------- */

function AvgBars({ usage }: { usage: UsageTotals }) {
  const avgIn = usage.requests ? usage.input_tokens / usage.requests : 0;
  const avgOut = usage.requests ? usage.output_tokens / usage.requests : 0;
  const max = Math.max(avgIn, avgOut, 1);
  const rows = [
    { label: "Avg input / request", value: avgIn, color: SLATE },
    { label: "Avg output / request", value: avgOut, color: RED },
  ];
  const perReq = useAnimatedNumber(
    usage.requests ? usage.total_tokens / usage.requests : 0,
  );

  return (
    <div className="flex h-full flex-col justify-center gap-6">
      <div className="text-center">
        <motion.p className="font-display text-[30px] font-bold leading-none tracking-tight tabular-nums">
          {perReq}
        </motion.p>
        <p className="mt-1.5 text-[12.5px] text-mut">avg tokens per request</p>
      </div>
      <div className="flex flex-col gap-4">
        {rows.map(({ label, value, color }, i) => (
          <div key={label}>
            <div className="mb-1.5 flex items-center justify-between text-[12px]">
              <span className="text-mut">{label}</span>
              <span className="font-semibold tabular-nums">
                {Math.round(value).toLocaleString("en-US")}
              </span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-surface-2">
              <motion.div
                className="h-full rounded-full"
                style={{ background: color }}
                initial={{ width: 0 }}
                animate={{ width: `${(value / max) * 100}%` }}
                transition={{
                  duration: 0.9,
                  delay: 0.15 + i * 0.12,
                  ease: [0.2, 0.8, 0.2, 1],
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- activity timeline ---------- */

interface Bucket {
  start: number;
  input: number;
  output: number;
  requests: number;
}

const BUCKET_SIZES = [60, 300, 900, 3600, 21600, 86400]; // s

function bucketize(
  events: UsageEvent[],
  since?: number | null,
): { buckets: Bucket[]; size: number } {
  const now = Date.now() / 1000;
  const first = since ?? (events.length ? events[0].ts : now - 1);
  const span = Math.max(now - first, 60);
  const size =
    BUCKET_SIZES.find((s) => span / s <= 30) ??
    BUCKET_SIZES[BUCKET_SIZES.length - 1];
  const end = Math.ceil(now / size) * size;
  const count = Math.min(Math.ceil(span / size) + 1, 30);
  const start = end - count * size;
  const buckets: Bucket[] = Array.from({ length: count }, (_, i) => ({
    start: start + i * size,
    input: 0,
    output: 0,
    requests: 0,
  }));
  for (const e of events) {
    const idx = Math.floor((e.ts - start) / size);
    if (idx >= 0 && idx < count) {
      buckets[idx].input += e.input_tokens;
      buckets[idx].output += e.output_tokens;
      buckets[idx].requests += 1;
    }
  }
  return { buckets, size };
}

function fmtBucketTime(ts: number, size: number): string {
  const d = new Date(ts * 1000);
  if (size >= 86400)
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function ActivityChart({
  events,
  since,
}: {
  events: UsageEvent[];
  since?: number | null;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const { buckets, size } = useMemo(
    () => bucketize(events, since),
    [events, since],
  );
  const max = Math.max(...buckets.map((b) => b.input + b.output), 1);
  const labelEvery = Math.max(1, Math.ceil(buckets.length / 6));

  return (
    <div>
      <div className="flex h-56 items-end gap-[5px]">
        {buckets.map((b, i) => {
          const total = b.input + b.output;
          const inH = (b.input / max) * 100;
          const outH = (b.output / max) * 100;
          return (
            <div
              key={b.start}
              className="group relative flex h-full flex-1 cursor-default flex-col items-stretch justify-end"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              {/* hover halo */}
              <div
                className={`absolute inset-x-[-2px] inset-y-0 rounded-lg transition-colors ${
                  hover === i ? "bg-surface-2" : ""
                }`}
              />
              {total === 0 ? (
                <div className="relative z-10 h-[3px] rounded-full bg-line" />
              ) : (
                <>
                  <motion.div
                    className="relative z-10 rounded-t-[4px]"
                    style={{ background: RED, opacity: 0.92 }}
                    initial={{ height: 0 }}
                    animate={{ height: `${outH}%` }}
                    transition={{
                      duration: 0.6,
                      delay: 0.1 + i * 0.02,
                      ease: [0.2, 0.8, 0.2, 1],
                    }}
                  />
                  <motion.div
                    className="relative z-10 rounded-b-[4px]"
                    style={{ background: SLATE }}
                    initial={{ height: 0 }}
                    animate={{ height: `${inH}%` }}
                    transition={{
                      duration: 0.6,
                      delay: 0.1 + i * 0.02,
                      ease: [0.2, 0.8, 0.2, 1],
                    }}
                  />
                </>
              )}
              {/* tooltip */}
              {hover === i && total > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="absolute bottom-full left-1/2 z-20 mb-2 w-max -translate-x-1/2 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[12px] [box-shadow:var(--shadow-lg)]"
                >
                  <p className="font-semibold">{fmtBucketTime(b.start, size)}</p>
                  <p className="mt-1 text-mut">
                    {b.requests} {b.requests === 1 ? "request" : "requests"}
                  </p>
                  <p className="text-mut">
                    <span style={{ color: SLATE }}>●</span>{" "}
                    {b.input.toLocaleString("en-US")} in ·{" "}
                    <span style={{ color: RED }}>●</span>{" "}
                    {b.output.toLocaleString("en-US")} out
                  </p>
                </motion.div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex border-t border-line pt-2">
        {buckets.map((b, i) => (
          <span
            key={b.start}
            className="flex-1 text-center text-[10.5px] text-faint"
          >
            {i % labelEvery === 0 ? fmtBucketTime(b.start, size) : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ---------- range tabs ---------- */

function RangeTabs({
  value,
  onChange,
}: {
  value: RangeKey;
  onChange: (k: RangeKey) => void;
}) {
  return (
    <div className="inline-flex items-center gap-1 rounded-xl border border-line bg-surface-2 p-1">
      {RANGES.map((r) => {
        const active = r.key === value;
        return (
          <button
            key={r.key}
            onClick={() => onChange(r.key)}
            className={`relative rounded-lg px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors ${
              active ? "text-white" : "text-mut hover:text-ink"
            }`}
          >
            {active && (
              <motion.span
                layoutId="range-pill"
                className="absolute inset-0 rounded-lg"
                style={{ background: RED }}
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            )}
            <span className="relative z-10">{r.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/* ---------- page ---------- */

export default function UsagePage() {
  const { token } = useAuth();
  const [usage, setUsage] = useState<UsageTotals | null>(null);
  const [range, setRange] = useState<RangeKey>("all");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // bumped on every successful load — remounts the charts so they re-animate
  const [tick, setTick] = useState(0);

  const view = useMemo(
    () => (usage ? deriveView(usage, range) : null),
    [usage, range],
  );
  const rangeLabel = RANGES.find((r) => r.key === range)?.label ?? "";

  const load = useCallback(async () => {
    try {
      // minimum spinner time so a fast fetch doesn't flicker
      const [u] = await Promise.all([
        api.usage(token),
        new Promise((r) => setTimeout(r, 450)),
      ]);
      setUsage(u);
      setError(null);
      setTick((t) => t + 1);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }, [token]);

  /* The spinner belongs to the refresh button. The first load is covered by the
     full-page skeleton, and raising the flag there would mean a setState inside
     the mount effect for a state nothing is showing yet. */
  const refresh = useCallback(() => {
    setBusy(true);
    void load();
  }, [load]);

  useLoad(load);

  // first paint before any data lands → full-page skeleton
  if (!usage && !error) {
    return (
      <Rise>
        <UsageSkeleton />
      </Rise>
    );
  }

  return (
    <Rise className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h3 className="font-display text-[18px] font-bold tracking-tight">
            Tenant usage
          </h3>
          <p className="mt-0.5 text-[13.5px] text-mut">
            {usage
              ? range === "all"
                ? `All-time totals for ${usage.tenant_id}.`
                : `${rangeLabel} · ${usage.tenant_id}.`
              : "Token and request accounting."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <RangeTabs value={range} onChange={setRange} />
          <Button variant="soft" onClick={refresh} busy={busy}>
            <RefreshCw className="size-4" /> Refresh
          </Button>
        </div>
      </div>

      {error && (
        <Card>
          <EmptyState
            icon={<Coins className="size-6" />}
            title="Not available"
            hint={error}
          />
        </Card>
      )}

      {view && (
        <div key={`${tick}:${range}`} className="contents">
          {/* stat tiles */}
          <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
            {TILES.map(({ key, label, icon: Icon }, i) => (
              <motion.div
                key={key}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.07, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
              >
                <Card className="p-6">
                  <div className="flex items-center justify-between">
                    <span className="text-[11.5px] font-semibold uppercase tracking-[0.08em] text-mut">
                      {label}
                    </span>
                    <span className="grid size-9 place-items-center rounded-lg bg-accent-soft text-accent">
                      <Icon className="size-4" />
                    </span>
                  </div>
                  <CountUp
                    value={view[key]}
                    className="font-display mt-4 text-[36px] font-bold leading-none tracking-tight tabular-nums"
                  />
                </Card>
              </motion.div>
            ))}
          </div>

          {/* cost — §15's dashboard is "usage *and cost*", §17 bills on it */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <Card>
              <CardHeader
                icon={<Wallet className="size-4" />}
                title="Cost"
                sub="Priced per model — local inference is free."
                right={
                  <span className="font-display text-[26px] font-bold leading-none tracking-tight tabular-nums">
                    {money(view.cost_usd)}
                  </span>
                }
              />
              <div className="p-6 pt-2">
                {view.by_model.length ? (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[520px] text-left text-[13px]">
                      <thead>
                        <tr className="text-[11px] uppercase tracking-[0.08em] text-mut">
                          <th className="pb-2 font-semibold">Model</th>
                          <th className="pb-2 text-right font-semibold">Requests</th>
                          <th className="pb-2 text-right font-semibold">Input</th>
                          <th className="pb-2 text-right font-semibold">Output</th>
                          <th className="pb-2 text-right font-semibold">Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {view.by_model.map((m) => (
                          <tr key={m.model} className="border-t border-line">
                            <td className="py-2.5 font-mono text-[12.5px]">
                              {m.model}
                            </td>
                            <td className="py-2.5 text-right tabular-nums">
                              {m.requests.toLocaleString("en-US")}
                            </td>
                            <td className="py-2.5 text-right tabular-nums text-mut">
                              {m.input_tokens.toLocaleString("en-US")}
                            </td>
                            <td className="py-2.5 text-right tabular-nums text-mut">
                              {m.output_tokens.toLocaleString("en-US")}
                            </td>
                            <td className="py-2.5 text-right tabular-nums font-semibold">
                              {m.cost.priced ? (
                                money(m.cost.total_usd)
                              ) : (
                                <span className="text-warn">no rate</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-[13px] text-mut">
                    No metered requests in this range.
                  </p>
                )}
                {view.unpriced_models.length > 0 && (
                  <p className="mt-4 text-[12px] text-warn">
                    No price configured for {view.unpriced_models.join(", ")} —
                    set KARAG_PRICING rather than letting a wrong number reach an
                    invoice.
                  </p>
                )}
              </div>
            </Card>
          </motion.div>

          {/* gauges row */}
          <div className="grid gap-6 xl:grid-cols-3">
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
            >
              <Card className="h-full">
                <CardHeader
                  icon={<GaugeIcon className="size-4" />}
                  title="Budget meter"
                  sub="Share of the token budget consumed."
                />
                <div className="p-6 pt-4">
                  <Speedometer fraction={view.total_tokens / TOKEN_BUDGET} />
                </div>
              </Card>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.32, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
            >
              <Card className="h-full">
                <CardHeader
                  icon={<ChartPie className="size-4" />}
                  title="Token split"
                  sub="Prompt tokens in, generated tokens out."
                />
                <div className="p-6 pt-4">
                  <Donut input={view.input_tokens} output={view.output_tokens} />
                </div>
              </Card>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.39, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
            >
              <Card className="h-full">
                <CardHeader
                  icon={<Scale className="size-4" />}
                  title="Per request"
                  sub="Average cost of a single question."
                />
                <div className="h-[calc(100%-73px)] p-6 pt-4">
                  <AvgBars usage={view} />
                </div>
              </Card>
            </motion.div>
          </div>

          {/* activity timeline */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.46, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <Card>
              <CardHeader
                icon={<ChartColumn className="size-4" />}
                title="Activity"
                sub="Tokens per interval — stacked input and output."
              />
              <div className="p-6">
                {view.events.length === 0 ? (
                  <EmptyState
                    icon={<ChartColumn className="size-6" />}
                    title={range === "all" ? "No activity yet" : "Nothing in this window"}
                    hint={
                      range === "all"
                        ? "Ask a question in Chat — every request lands on this timeline."
                        : "No requests fell in the selected range. Try a wider window."
                    }
                  />
                ) : (
                  <ActivityChart
                    events={view.events}
                    since={rangeCutoff(range)}
                  />
                )}
              </div>
            </Card>
          </motion.div>
        </div>
      )}
    </Rise>
  );
}
