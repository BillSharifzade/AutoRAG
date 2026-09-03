"use client";

/* The small pieces the two skill forms share. Each one is a single decision
   made once: how a field is labelled, how "more" unfolds, how a machine name
   is shown without being asked for. */

import { BookOpenCheck, ChevronDown, Database, Globe, Pencil } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useId, useState, type ReactNode } from "react";
import type { SkillKind } from "@/lib/api";
import { useT } from "@/i18n";
import { roles } from "@/lib/words";
import { nameProblem } from "@/lib/skills";
import { AudiencePicker } from "@/components/audience";
import { EASE } from "@/components/pro";
import { Input } from "@/components/ui";

/* ---------- kind ---------- */

export function KindIcon({ kind, className = "size-4" }: { kind: SkillKind; className?: string }) {
  if (kind === "agent") return <BookOpenCheck className={className} />;
  if (kind === "rest") return <Globe className={className} />;
  return <Database className={className} />;
}

export function useKindLabel(): (kind: SkillKind) => string {
  const t = useT();
  return (kind) =>
    kind === "agent"
      ? t("skills.kind.procedure")
      : kind === "rest"
        ? t("skills.kind.lookupApi")
        : t("skills.kind.lookupDb");
}

/* ---------- switch ---------- */

/** On / off, in one glance. Stops the click so a card underneath doesn't open. */
export function Switch({
  on,
  onChange,
  label,
  busy = false,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  label: string;
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      title={label}
      disabled={busy}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!on);
      }}
      className={`relative inline-flex h-6 w-10 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-50 ${
        on ? "bg-good" : "bg-line-strong"
      }`}
    >
      <motion.span
        aria-hidden
        animate={{ x: on ? 18 : 2 }}
        transition={{ type: "spring", stiffness: 500, damping: 34 }}
        className="absolute size-5 rounded-full bg-white shadow-sm"
      />
    </button>
  );
}

/* ---------- field ---------- */

/** A label, at most one quiet line under it, then the control. */
export function Field({
  label,
  hint,
  right,
  children,
}: {
  label: string;
  hint?: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="text-[13px] font-semibold">{label}</span>
        {right && <span className="text-[11.5px] text-faint">{right}</span>}
      </div>
      {children}
      {hint && <p className="mt-1.5 text-[12px] text-faint">{hint}</p>}
    </div>
  );
}

/* ---------- more ---------- */

/** Rarely needed choices stay folded under one word. */
export function More({
  label,
  open: openInitially = false,
  children,
}: {
  label: string;
  open?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(openInitially);
  const id = useId();
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-mut transition-colors hover:text-ink"
      >
        <ChevronDown
          className={`size-3.5 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
        {label}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={id}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="pt-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ---------- title + machine name ---------- */

/* The person types a title; the name the assistant calls the skill by is
   derived and shown small. It can be corrected, but nobody is asked to invent
   it. */
export function TitleField({
  title,
  name,
  kind,
  onTitle,
  onName,
  autoFocus = false,
}: {
  title: string;
  name: string;
  kind: SkillKind;
  onTitle: (v: string) => void;
  onName: (v: string) => void;
  autoFocus?: boolean;
}) {
  const t = useT();
  const [editingName, setEditingName] = useState(false);
  const problem = title || name ? nameProblem(name, kind) : "";
  return (
    <Field label={t("skills.field.title")}>
      <Input
        value={title}
        autoFocus={autoFocus}
        onChange={(e) => onTitle(e.target.value)}
        placeholder={
          kind === "agent" ? t("skills.field.title.phProc") : t("skills.field.title.phLookup")
        }
      />
      <div className="mt-1.5 flex min-h-5 flex-wrap items-center gap-2 text-[12px] text-faint">
        {editingName ? (
          <input
            autoFocus
            value={name}
            onChange={(e) => onName(e.target.value)}
            onBlur={() => setEditingName(false)}
            onKeyDown={(e) => e.key === "Enter" && setEditingName(false)}
            aria-label={t("skills.field.name")}
            className="h-6 rounded-md border border-line bg-surface px-1.5 font-mono text-[12px] text-ink focus:border-accent"
          />
        ) : (
          name && (
            <>
              <span>{t("skills.field.name")}:</span>
              <code className="font-mono text-[12px] text-mut">{name}</code>
              <button
                type="button"
                onClick={() => setEditingName(true)}
                aria-label={t("common.edit")}
                className="inline-grid size-5 cursor-pointer place-items-center rounded-md text-faint transition-colors hover:bg-surface-2 hover:text-ink"
              >
                <Pencil className="size-3" />
              </button>
            </>
          )
        )}
        {problem && <span className="text-bad">{t(problem)}</span>}
      </div>
    </Field>
  );
}

/* ---------- one-line description ---------- */

export function WhenField({
  value,
  onChange,
  max,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  max: number;
  placeholder: string;
}) {
  const t = useT();
  return (
    <Field
      label={t("skills.field.when")}
      hint={t("skills.field.when.hint")}
      right={value.length > max * 0.7 ? `${value.length}/${max}` : undefined}
    >
      <Input
        value={value}
        maxLength={max}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </Field>
  );
}

/* ---------- who can use it ---------- */

export function AccessBlock({
  audience,
  onAudience,
  roleValues,
  onRoles,
  shared,
  onShared,
}: {
  audience: string;
  onAudience: (v: string) => void;
  roleValues: string[];
  onRoles: (v: string[]) => void;
  shared: boolean;
  onShared: (v: boolean) => void;
}) {
  const t = useT();
  const all = roles().filter((r) => !["platform_admin", "karag_engineer"].includes(r.value));
  return (
    <div className="flex flex-col gap-4">
      <AudiencePicker value={audience} onChange={onAudience} />
      <More label={t("skills.access.more")} open={roleValues.length > 0 || shared}>
        <div className="flex flex-col gap-4">
          <Field label={t("skills.access.roles")} hint={t("skills.access.roles.hint")}>
            <div className="flex flex-wrap gap-1.5">
              {all.map((r) => {
                const active = roleValues.includes(r.value);
                return (
                  <button
                    key={r.value}
                    type="button"
                    aria-pressed={active}
                    onClick={() =>
                      onRoles(
                        active
                          ? roleValues.filter((v) => v !== r.value)
                          : [...roleValues, r.value],
                      )
                    }
                    className={`cursor-pointer rounded-lg border px-2.5 py-1 text-[12.5px] font-medium transition-colors ${
                      active
                        ? "border-accent bg-accent-soft text-accent-strong"
                        : "border-line bg-surface text-mut hover:border-line-strong hover:text-ink"
                    }`}
                  >
                    {r.label}
                  </button>
                );
              })}
            </div>
          </Field>
          <label className="flex cursor-pointer items-start gap-2.5 text-[13px]">
            <input
              type="checkbox"
              checked={shared}
              onChange={(e) => onShared(e.target.checked)}
              className="mt-0.5 size-4 accent-[var(--accent)]"
            />
            <span>
              <span className="font-semibold">{t("skills.access.share")}</span>
              <span className="block text-[12px] text-faint">{t("skills.access.share.hint")}</span>
            </span>
          </label>
        </div>
      </More>
    </div>
  );
}

/* ---------- reference files ---------- */

export function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
