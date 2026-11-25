"use client";

/* "Who can see this?" — the control that used to be a `data_class` dropdown.
 *
 * This is the one choice on the Documents page a non-technical person can get
 * meaningfully wrong, and getting it wrong means either hiding something
 * useful or exposing something sensitive. So it is not a dropdown: every
 * option is visible at once with the consequence spelled out, the choice is
 * one click, and a meter shows how restricted the selection is relative to the
 * others. Unclassified still fails closed on the server — this only makes the
 * decision legible. */

import { motion } from "motion/react";
import { useT } from "@/i18n";
import { audience, audiences } from "@/lib/words";
import { EASE } from "@/components/pro";

export function AudiencePicker({
  value,
  onChange,
  /** the server's advisory guess, shown as a hint — never auto-applied */
  suggested,
}: {
  value: string;
  onChange: (v: string) => void;
  suggested?: string | null;
}) {
  const t = useT();
  const AUDIENCES = audiences();
  const current = audience(value);
  // nothing chosen yet: the meter stays empty instead of implying a default
  const chosen = AUDIENCES.some((a) => a.value === value);
  const level = chosen ? current.level : -1;
  return (
    <div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {AUDIENCES.map((a) => {
          const active = a.value === value;
          const isSuggested = suggested === a.value;
          return (
            <button
              key={a.value}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(a.value)}
              className={`relative isolate cursor-pointer overflow-hidden rounded-xl border p-3.5 text-left transition-[border-color,background] duration-200 ${
                active
                  ? "border-accent bg-accent-soft/50"
                  : "border-line bg-surface hover:border-line-strong hover:bg-surface-2"
              }`}
            >
              {active && (
                <motion.span
                  layoutId="audience-glow"
                  transition={{ type: "spring", stiffness: 400, damping: 34 }}
                  aria-hidden
                  className="pointer-events-none absolute inset-0 -z-10"
                  style={{
                    background:
                      "radial-gradient(220px 90px at 12% 0%, color-mix(in oklab, var(--accent) 16%, transparent), transparent 70%)",
                  }}
                />
              )}
              <span className="flex items-center gap-2">
                <span
                  className="size-2.5 shrink-0 rounded-full"
                  style={{ background: a.dot }}
                />
                <span className="text-[13.5px] font-semibold">{a.label}</span>
                {isSuggested && !active && (
                  <span className="ml-auto rounded-md bg-surface-2 px-1.5 py-0.5 text-[10.5px] font-semibold text-mut">
                    {t("audience.suggested")}
                  </span>
                )}
              </span>
              <span className="mt-1.5 block text-[12px] leading-relaxed text-mut">
                {a.who}
              </span>
            </button>
          );
        })}
      </div>

      {/* sensitivity meter — the five levels as segments, filled to the choice */}
      <div className="mt-4 flex items-center gap-3">
        <span className="flex gap-1" aria-hidden>
          {AUDIENCES.map((a) => (
            <motion.span
              key={a.value}
              animate={{
                backgroundColor:
                  a.level <= level ? current.dot : "var(--line)",
                scaleY: a.level <= level ? 1 : 0.55,
              }}
              transition={{ duration: 0.3, ease: EASE }}
              className="h-2 w-7 origin-center rounded-full"
            />
          ))}
        </span>
        {chosen ? (
          <p className="text-[12.5px] text-mut">
            <strong className="font-semibold text-ink">{current.label}</strong> —{" "}
            {current.who}
          </p>
        ) : (
          <p className="text-[12.5px] font-semibold text-warn">{t("audience.choose")}</p>
        )}
      </div>
    </div>
  );
}

/** The read-only badge form, for lists. */
export function AudienceBadge({ value }: { value: string }) {
  const a = audience(value);
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-1 text-[11.5px] font-medium">
      <span className="size-2 rounded-full" style={{ background: a.dot }} />
      {a.label}
    </span>
  );
}
