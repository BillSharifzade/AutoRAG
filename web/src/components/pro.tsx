"use client";

/* The layer the refactored pages are built from.
 *
 * `ui.tsx` holds the original primitives (still used by the sign-in screen and
 * the usage dashboard, which are staying as they are). This file adds the
 * pieces those pages didn't need: an orchestrated page-load, a page hero that
 * carries a signature visual, count-up tiles, a segmented control, two-step
 * confirms, and states for empty / restricted / failed.
 *
 * Every animation here is opt-out: `useCalm()` reads prefers-reduced-motion and
 * collapses motion to a plain fade, so nothing moves for someone who asked for
 * stillness. */

import { AlertTriangle, ArrowRight, Check, Info, Lock, X } from "lucide-react";
import {
  AnimatePresence,
  animate,
  motion,
  useMotionValue,
  useTransform,
  type Variants,
} from "motion/react";
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

/* ---------- motion foundation ---------- */

/** The app's one easing curve — every page-load and reveal uses it. */
export const EASE = [0.2, 0.8, 0.2, 1] as const;

/* prefers-reduced-motion is an external store, so it's read through
   useSyncExternalStore — no effect, no cascading render, and the server render
   is `false` so nothing animates before hydration decides. */
const CALM_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeCalm(onChange: () => void) {
  const mq = window.matchMedia(CALM_QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

/** True when the visitor asked for reduced motion. */
export function useCalm(): boolean {
  return useSyncExternalStore(
    subscribeCalm,
    () => window.matchMedia(CALM_QUERY).matches,
    () => false,
  );
}

/* One page-load choreography, shared by every page: children rise in sequence
   rather than all at once, which is what makes a screen feel composed instead
   of merely animated. */
export function Stagger({
  children,
  className = "",
  gap = 0.06,
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  gap?: number;
  delay?: number;
}) {
  const calm = useCalm();
  const variants: Variants = {
    hidden: {},
    shown: {
      transition: { staggerChildren: calm ? 0 : gap, delayChildren: delay },
    },
  };
  return (
    <motion.div
      variants={variants}
      initial="hidden"
      animate="shown"
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className = "",
  /** how far it travels in; 0 for things that shouldn't move at all */
  rise = 16,
}: {
  children: ReactNode;
  className?: string;
  rise?: number;
}) {
  const calm = useCalm();
  const variants: Variants = {
    hidden: { opacity: 0, y: calm ? 0 : rise },
    shown: {
      opacity: 1,
      y: 0,
      transition: { duration: calm ? 0.2 : 0.5, ease: EASE },
    },
  };
  return (
    <motion.div variants={variants} className={className}>
      {children}
    </motion.div>
  );
}

/* ---------- numbers that arrive ---------- */

/** Counts up to `value`. Formatting stays with the caller. */
export function CountUp({
  value,
  format = (n) => Math.round(n).toLocaleString("en-US"),
  className = "",
  duration = 0.9,
}: {
  value: number;
  format?: (n: number) => string;
  className?: string;
  duration?: number;
}) {
  const calm = useCalm();
  const mv = useMotionValue(calm ? value : 0);
  const text = useTransform(mv, format);
  useEffect(() => {
    if (calm) {
      mv.set(value);
      return;
    }
    const controls = animate(mv, value, { duration, ease: EASE });
    return controls.stop;
  }, [value, mv, calm, duration]);
  return <motion.span className={className}>{text}</motion.span>;
}

/* ---------- page hero ---------- */

/* Every page opens the same way: a small eyebrow naming where you are, a
   display-face title, one sentence saying what the page is for in the reader's
   terms, and the page's primary action. `art` is the per-page signature — the
   one thing that page is remembered by. */
export function PageHero({
  eyebrow,
  title,
  lead,
  actions,
  art,
}: {
  eyebrow: string;
  title: string;
  lead: string;
  actions?: ReactNode;
  art?: ReactNode;
}) {
  return (
    <StaggerItem rise={10}>
      <header className="relative isolate overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
        {/* brand wash — sits behind everything, never intercepts a click */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              "radial-gradient(760px 300px at 88% -30%, color-mix(in oklab, var(--accent) 13%, transparent), transparent 70%), radial-gradient(560px 260px at 8% 130%, color-mix(in oklab, var(--accent-2) 16%, transparent), transparent 70%)",
          }}
        />
        <div className="flex flex-col gap-6 p-7 sm:p-9 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0 max-w-2xl">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">
              {eyebrow}
            </p>
            <h1 className="font-display mt-2 text-[clamp(1.65rem,3.4vw,2.35rem)] font-bold leading-[1.1]">
              {title}
            </h1>
            <p className="mt-3 text-[14.5px] leading-relaxed text-mut">{lead}</p>
            {actions && (
              <div className="mt-6 flex flex-wrap items-center gap-3">{actions}</div>
            )}
          </div>
          {art && <div className="shrink-0">{art}</div>}
        </div>
      </header>
    </StaggerItem>
  );
}

/* ---------- stat tile ---------- */

export function StatTile({
  label,
  value,
  icon,
  hint,
  format,
  tone = "accent",
}: {
  label: string;
  value: number;
  icon?: ReactNode;
  hint?: string;
  format?: (n: number) => string;
  tone?: "accent" | "good" | "warn" | "bad" | "neutral";
}) {
  const tones = {
    accent: "bg-accent-soft text-accent",
    good: "bg-good-soft text-good",
    warn: "bg-warn-soft text-warn",
    bad: "bg-bad-soft text-bad",
    neutral: "bg-surface-2 text-mut",
  }[tone];
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-line bg-surface p-5 transition-[box-shadow,transform] duration-300 hover:-translate-y-0.5 card-ring">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-mut">
          {label}
        </p>
        {icon && (
          <span className={`grid size-8 shrink-0 place-items-center rounded-lg ${tones}`}>
            {icon}
          </span>
        )}
      </div>
      <CountUp
        value={value}
        format={format}
        className="font-display mt-3 block text-[30px] font-bold leading-none tracking-tight tabular-nums"
      />
      {hint && <p className="mt-2 text-[12px] text-faint">{hint}</p>}
    </div>
  );
}

/* ---------- segmented control ---------- */

/* The moving pill is a shared layout animation, so switching tabs slides one
   element rather than cross-fading two. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; count?: number }[];
  ariaLabel?: string;
}) {
  /* stable id so the sliding pill's layoutId can't collide with another
     segmented control on the same page */
  const id = useId();
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="inline-flex items-center gap-1 rounded-full border border-line bg-surface-2 p-1"
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            /* `isolate` matters: the pill is painted behind the label inside
               this button's own stacking context. Without it the pill drops
               behind the track's background and the active label goes
               invisible against it. */
            className={`relative isolate cursor-pointer rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${
              active ? "text-accent-ink" : "text-mut hover:text-ink"
            }`}
          >
            {active && (
              <motion.span
                layoutId={id}
                aria-hidden
                transition={{ type: "spring", stiffness: 380, damping: 32 }}
                className="red-gradient absolute inset-0 -z-10 rounded-full"
              />
            )}
            <span className="relative">{o.label}</span>
            {o.count !== undefined && (
              <span
                className={`relative ml-1.5 ${active ? "opacity-80" : "text-faint"}`}
              >
                {o.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- two-step confirm ---------- */

/* Deliberately not a browser confirm() and not a modal: the question appears
   where the action is, and answering it never moves the reader elsewhere. */
export function ConfirmAction({
  onConfirm,
  question,
  confirmLabel = "Yes, remove",
  children,
}: {
  onConfirm: () => void | Promise<void>;
  question: string;
  confirmLabel?: string;
  children: (start: () => void) => ReactNode;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <AnimatePresence mode="wait" initial={false}>
      {asking ? (
        <motion.span
          key="ask"
          initial={{ opacity: 0, x: 8 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 8 }}
          transition={{ duration: 0.16, ease: EASE }}
          className="flex flex-wrap items-center justify-end gap-2"
        >
          <span className="text-[12.5px] text-mut">{question}</span>
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
              } finally {
                setBusy(false);
                setAsking(false);
              }
            }}
            className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg bg-bad-soft px-2.5 text-[12.5px] font-semibold text-bad transition-[filter] hover:brightness-95 disabled:opacity-50 dark:hover:brightness-125"
          >
            <Check className="size-3.5" />
            {confirmLabel}
          </button>
          <button
            onClick={() => setAsking(false)}
            className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:text-ink"
          >
            <X className="size-3.5" />
            Keep
          </button>
        </motion.span>
      ) : (
        <motion.span
          key="idle"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
        >
          {children(() => setAsking(true))}
        </motion.span>
      )}
    </AnimatePresence>
  );
}

/* ---------- states ---------- */

/* An empty screen is an invitation, so it always carries the action that fills
   it rather than only reporting that nothing is there. */
export function Empty({
  icon,
  title,
  hint,
  action,
}: {
  icon: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: EASE }}
      className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center"
    >
      <div className="relative">
        <div
          aria-hidden
          className="absolute inset-0 -z-10 rounded-full blur-2xl"
          style={{ background: "color-mix(in oklab, var(--accent) 22%, transparent)" }}
        />
        <div className="grid size-14 place-items-center rounded-2xl border border-line bg-surface text-accent">
          {icon}
        </div>
      </div>
      <p className="font-display mt-1 text-[16px] font-semibold">{title}</p>
      {hint && (
        <p className="max-w-md text-[13.5px] leading-relaxed text-mut">{hint}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </motion.div>
  );
}

/* Being told "restricted" and nothing else is a dead end. Say who does have
   this, and what to ask for. */
export function Restricted({
  what,
  who,
  yourRole,
}: {
  what: string;
  who: string;
  yourRole?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE }}
      className="mx-auto max-w-lg rounded-3xl border border-line bg-surface p-9 text-center [box-shadow:var(--shadow)]"
    >
      <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-surface-2 text-mut">
        <Lock className="size-6" />
      </div>
      <h2 className="font-display mt-5 text-[19px] font-semibold">{what}</h2>
      <p className="mt-2.5 text-[14px] leading-relaxed text-mut">{who}</p>
      {yourRole && (
        <p className="mt-5 inline-flex items-center gap-2 rounded-full border border-line bg-surface-2 px-3.5 py-1.5 text-[12.5px] text-mut">
          You are signed in as
          <strong className="font-semibold text-ink">{yourRole}</strong>
        </p>
      )}
      <p className="mt-5 text-[12.5px] text-faint">
        Ask an administrator at your company if you need this.
      </p>
    </motion.div>
  );
}

/* ---------- inline feedback ---------- */

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "good" | "warn" | "bad";
  children: ReactNode;
}) {
  const map = {
    info: { cls: "border-line bg-surface-2 text-mut", Icon: Info },
    good: { cls: "border-transparent bg-good-soft text-good", Icon: Check },
    warn: { cls: "border-transparent bg-warn-soft text-warn", Icon: AlertTriangle },
    bad: { cls: "border-transparent bg-bad-soft text-bad", Icon: AlertTriangle },
  }[tone];
  const { Icon } = map;
  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2, ease: EASE }}
      className={`flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-[13px] leading-relaxed ${map.cls}`}
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <span className="min-w-0">{children}</span>
    </motion.div>
  );
}

/* A definition on demand, for the few platform words that have no plain
   synonym. Hover or focus — never a click, never a modal. */
export function Explain({ term, children }: { term: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={`What is ${term}?`}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="inline-grid size-4 cursor-help place-items-center rounded-full border border-line text-[9px] font-bold text-mut transition-colors hover:border-accent hover:text-accent"
      >
        ?
      </button>
      <AnimatePresence>
        {open && (
          <motion.span
            role="tooltip"
            initial={{ opacity: 0, y: 4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.97 }}
            transition={{ duration: 0.14, ease: EASE }}
            className="absolute bottom-full left-1/2 z-40 mb-2 w-60 -translate-x-1/2 rounded-xl border border-line bg-surface p-3 text-left text-[12.5px] font-normal leading-relaxed text-mut [box-shadow:var(--shadow-lg)]"
          >
            <strong className="mb-1 block font-semibold text-ink">{term}</strong>
            {children}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

/* ---------- guided flow ---------- */

interface StepCtx {
  current: number;
  go: (n: number) => void;
}
const StepContext = createContext<StepCtx>({ current: 0, go: () => {} });

/** Numbered because these really are a sequence — each step needs the one before. */
export function Steps({
  current,
  onGo,
  children,
}: {
  current: number;
  onGo: (n: number) => void;
  children: ReactNode;
}) {
  return (
    <StepContext.Provider value={{ current, go: onGo }}>
      <ol className="flex flex-col gap-3">{children}</ol>
    </StepContext.Provider>
  );
}

export function Step({
  index,
  title,
  summary,
  done = false,
  children,
}: {
  index: number;
  title: string;
  /** what the reader chose, shown once the step is behind them */
  summary?: string;
  done?: boolean;
  children: ReactNode;
}) {
  const { current, go } = useContext(StepContext);
  const open = current === index;
  const reachable = done || index <= current;
  return (
    <li
      className={`overflow-hidden rounded-2xl border transition-colors ${
        open ? "border-accent/40 bg-surface" : "border-line bg-surface"
      }`}
    >
      <button
        type="button"
        disabled={!reachable}
        onClick={() => reachable && go(index)}
        className={`flex w-full items-center gap-3.5 px-5 py-4 text-left transition-colors ${
          reachable ? "cursor-pointer hover:bg-surface-2" : "cursor-not-allowed opacity-55"
        }`}
      >
        <span
          className={`grid size-8 shrink-0 place-items-center rounded-full text-[13px] font-bold transition-colors ${
            done
              ? "bg-good-soft text-good"
              : open
                ? "red-gradient text-accent-ink"
                : "bg-surface-2 text-mut"
          }`}
        >
          {done ? <Check className="size-4" /> : index + 1}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-display text-[15px] font-semibold">{title}</span>
          {!open && summary && (
            <span className="mt-0.5 block truncate text-[12.5px] text-mut">{summary}</span>
          )}
        </span>
        {!open && reachable && (
          <ArrowRight className="size-4 shrink-0 text-faint" />
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="border-t border-line px-5 py-5">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}
