"use client";

/* Shared primitives — KARAG tokens + Motion micro-interactions. */

import { Check, ChevronDown, Loader2 } from "lucide-react";
import { AnimatePresence, motion, type HTMLMotionProps } from "motion/react";
import {
  useEffect,
  useRef,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { useT } from "@/i18n";

/* ---------- brand ---------- */

/* Theme-aware logo: light artwork by default, white artwork in dark mode. */
export function BrandLogo({
  mark = false,
  className = "",
}: {
  mark?: boolean;
  className?: string;
}) {
  const light = mark ? "/logo-mark.png" : "/logo.png";
  const dark = mark ? "/logo-mark-dark.png" : "/logo-dark.png";
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={light} alt="KARAG" className={`${className} dark:hidden`} />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={dark} alt="KARAG" className={`${className} hidden dark:block`} />
    </>
  );
}

/* ---------- layout ---------- */

export function Card({
  children,
  className = "",
  flat = false,
}: {
  children: ReactNode;
  className?: string;
  flat?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border border-line bg-surface transition-shadow duration-300 ${
        flat ? "[box-shadow:var(--shadow-sm)]" : "card-ring"
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  sub,
  icon,
  right,
}: {
  title: ReactNode;
  sub?: string;
  icon?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
      <div className="flex items-start gap-3">
        {icon && (
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
            {icon}
          </span>
        )}
        <div>
          <h3 className="font-display text-[16px] font-semibold">{title}</h3>
          {sub && <p className="mt-0.5 text-[13px] text-mut">{sub}</p>}
        </div>
      </div>
      {right}
    </div>
  );
}

/* ---------- controls ---------- */

type ButtonProps = Omit<HTMLMotionProps<"button">, "children"> & {
  children?: ReactNode;
  variant?: "primary" | "cta" | "soft" | "ghost" | "danger";
  busy?: boolean;
  size?: "md" | "sm" | "icon";
};

export function Button({
  variant = "primary",
  busy = false,
  size = "md",
  className = "",
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const styles = {
    primary:
      "brand-gradient text-accent-ink shadow-[0_2px_12px_-2px_rgb(62_59_78/0.55)] hover:shadow-[0_4px_20px_-2px_rgb(62_59_78/0.65)] hover:brightness-110",
    /* The single strongest action on a page — the red gradient, spent once. */
    cta: "red-gradient text-accent-ink shadow-[0_2px_14px_-2px_rgb(236_35_54/0.5)] hover:shadow-[0_6px_22px_-2px_rgb(236_35_54/0.6)] hover:brightness-110",
    soft: "bg-accent-soft text-accent-strong hover:bg-accent-soft-2",
    ghost:
      "border border-line bg-surface text-mut hover:border-line-strong hover:text-ink",
    danger: "bg-bad-soft text-bad hover:brightness-95 dark:hover:brightness-125",
  }[variant];
  const sizes = {
    md: "h-10 px-4.5 text-[14px] gap-2",
    sm: "h-8.5 px-3 text-[13px] gap-1.5",
    icon: "size-10 p-0",
  }[size];
  return (
    <motion.button
      whileTap={{ scale: 0.96 }}
      transition={{ duration: 0.1 }}
      className={`inline-flex cursor-pointer items-center justify-center rounded-xl font-semibold transition-[background,box-shadow,color,filter] duration-200 disabled:pointer-events-none disabled:opacity-45 ${styles} ${sizes} ${className}`}
      disabled={disabled || busy}
      {...rest}
    >
      {busy && <Loader2 className="size-4 animate-spin" />}
      {children}
    </motion.button>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`h-10 w-full rounded-xl border border-line bg-surface px-3.5 text-[14px] transition-colors placeholder:text-faint hover:border-line-strong focus:border-accent ${props.className ?? ""}`}
    />
  );
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`min-h-24 w-full resize-y rounded-xl border border-line bg-surface p-3.5 text-[14px] leading-relaxed transition-colors placeholder:text-faint hover:border-line-strong focus:border-accent ${props.className ?? ""}`}
    />
  );
}

export interface PickerOption {
  value: string;
  label: string;
  hint?: string;
}

/* Custom animated dropdown — replaces the native <select>. */
export function Picker({
  value,
  onChange,
  options,
  className = "",
  ariaLabel,
  placeholder,
  compact = false,
  dropUp = false,
  disabled = false,
}: {
  value: string;
  onChange: (v: string) => void;
  options: PickerOption[];
  className?: string;
  ariaLabel?: string;
  placeholder?: string;
  /** borderless pill trigger, e.g. inside the chat composer */
  compact?: boolean;
  /** open the list above the trigger (composer sits at screen bottom) */
  dropUp?: boolean;
  disabled?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = options.find((o) => o.value === value);

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={
          compact
            ? `flex h-9 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition-colors ${
                open ? "bg-surface-2 text-ink" : "text-mut hover:bg-surface-2 hover:text-ink"
              }`
            : `flex h-11 w-full cursor-pointer items-center justify-between gap-2 rounded-xl border bg-surface px-3.5 text-[14px] transition-colors ${
                open ? "border-accent" : "border-line hover:border-line-strong"
              }`
        }
      >
        <span className={`truncate ${current ? "" : "text-faint"}`}>
          {current?.label ?? placeholder ?? t("common.select")}
        </span>
        <ChevronDown
          className={`size-4 shrink-0 text-faint transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: dropUp ? 6 : -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: dropUp ? 6 : -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
            className={`absolute z-30 max-h-72 w-full min-w-52 overflow-y-auto rounded-xl border border-line bg-surface p-1.5 [box-shadow:var(--shadow-lg)] ${
              dropUp ? "bottom-full mb-2" : "mt-2"
            }`}
          >
            {options.map((o) => {
              const active = o.value === value;
              return (
                <li key={o.value} role="option" aria-selected={active}>
                  <button
                    type="button"
                    onClick={() => {
                      onChange(o.value);
                      setOpen(false);
                    }}
                    className={`flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-[13.5px] transition-colors ${
                      active
                        ? "bg-accent-soft font-semibold text-accent-strong"
                        : "hover:bg-surface-2"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate">{o.label}</span>
                      {o.hint && (
                        <span className="mt-0.5 block text-[11.5px] font-normal text-mut">
                          {o.hint}
                        </span>
                      )}
                    </span>
                    {active && <Check className="size-4 shrink-0 text-accent" />}
                  </button>
                </li>
              );
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return (
    <label className="mb-1.5 mt-4 block text-[11px] font-semibold uppercase tracking-[0.08em] text-mut first:mt-0">
      {children}
    </label>
  );
}

/* ---------- feedback ---------- */

export function Chip({
  children,
  tone = "accent",
  className = "",
}: {
  children: ReactNode;
  tone?: "accent" | "good" | "bad" | "warn" | "neutral";
  className?: string;
}) {
  const styles = {
    accent: "bg-accent-soft text-accent-strong",
    good: "bg-good-soft text-good",
    bad: "bg-bad-soft text-bad",
    warn: "bg-warn-soft text-warn",
    neutral: "border border-line bg-surface-2 text-mut",
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11.5px] font-semibold ${styles} ${className}`}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  children,
}: {
  icon: ReactNode;
  title: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center gap-2.5 py-10 text-center"
    >
      <div className="grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
        {icon}
      </div>
      <p className="font-display text-[14.5px] font-semibold">{title}</p>
      {hint && <p className="max-w-sm text-[13px] leading-relaxed text-mut">{hint}</p>}
      {children}
    </motion.div>
  );
}

export function TypingDots() {
  const t = useT();
  return (
    <span className="inline-flex items-center gap-1 px-1" aria-label={t("ui.thinking")}>
      <span className="typing-dot size-1.5 rounded-full bg-accent" />
      <span className="typing-dot size-1.5 rounded-full bg-accent" />
      <span className="typing-dot size-1.5 rounded-full bg-accent" />
    </span>
  );
}

/* ---------- motion helpers ---------- */

export function Rise({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.2, 0.8, 0.2, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}
