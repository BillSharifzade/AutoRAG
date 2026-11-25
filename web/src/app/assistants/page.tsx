"use client";

/* Assistants — a list of cards and one focused form.
 *
 * An assistant is the plain chat with a job description: a name, how it should
 * behave, and what it may use. Creating one is three fields on one panel;
 * nothing about languages, nothing technical. Everyone in the company may use
 * any assistant; only the person who made it (or an administrator) can change
 * it. */

import {
  ArrowLeft,
  Bot,
  ExternalLink,
  Pencil,
  Plus,
  Send,
  Trash2,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import {
  api,
  type Answer,
  type ApiError,
  type Assistant,
  type SkillInfo,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { useLocale, useT } from "@/i18n";
import { errorWords } from "@/lib/words";
import {
  accessOf,
  humanise,
  initials,
  pluralKey,
  sameAccess,
  toneFor,
  type AccessMode,
} from "@/components/assistants/helpers";
import { TEMPLATES } from "@/components/assistants/templates";
import { Markdown } from "@/components/chat-thread";
import {
  ConfirmAction,
  EASE,
  Empty,
  Notice,
  PageHero,
  Stagger,
  StaggerItem,
} from "@/components/pro";
import { Button, Input, Textarea } from "@/components/ui";

type View =
  | { mode: "list" }
  | { mode: "new" }
  | { mode: "edit"; a: Assistant }
  | { mode: "detail"; a: Assistant };

/* ---------- small pieces ---------- */

function Avatar({ name, size = "size-11" }: { name: string; size?: string }) {
  return (
    <span
      className={`grid ${size} shrink-0 place-items-center rounded-2xl font-display text-[14px] font-bold ${toneFor(name)}`}
    >
      {initials(name)}
    </span>
  );
}

function AccessLine({ a }: { a: Assistant }) {
  const t = useT();
  const { locale } = useLocale();
  const mode = accessOf(a.allowed_skill_names);
  if (mode === "all") return <>{t("assistants.access.all")}</>;
  if (mode === "docs") return <>{t("assistants.access.docs")}</>;
  const n = a.allowed_skill_names?.length ?? 0;
  return <>{t(`assistants.skillsCount.${pluralKey(locale, n)}`, { n })}</>;
}

function Owner({ a }: { a: Assistant }) {
  const t = useT();
  const { me } = useAuth();
  return (
    <>{a.created_by && a.created_by === me?.user_id ? t("assistants.byYou") : t("assistants.by", { who: a.created_by || "—" })}</>
  );
}

/* ---------- a card ---------- */

function AssistantCard({ a, onOpen, onEdit }: { a: Assistant; onOpen: () => void; onEdit: () => void }) {
  const t = useT();
  return (
    <motion.div
      layout
      whileHover={{ y: -2 }}
      className="group flex h-full flex-col rounded-2xl border border-line bg-surface p-5 transition-shadow card-ring"
    >
      <button type="button" onClick={onOpen} className="flex cursor-pointer items-start gap-3.5 text-left">
        <Avatar name={a.name} />
        <span className="min-w-0">
          <span className="font-display block truncate text-[15.5px] font-semibold">{a.name}</span>
          <span className="mt-0.5 line-clamp-2 block text-[13px] leading-relaxed text-mut">
            {a.instruction || t("assistants.detail.noInstruction")}
          </span>
        </span>
      </button>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4 text-[12px] text-faint">
        <span>
          <AccessLine a={a} /> · <Owner a={a} />
        </span>
        <span className="flex items-center gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
          <Link
            href={`/?assistant=${a.id}`}
            title={t("assistants.card.open")}
            className="grid size-8 place-items-center rounded-lg text-mut transition-colors hover:bg-accent-soft hover:text-accent-strong"
          >
            <ExternalLink className="size-4" />
          </Link>
          {a.can_edit && (
            <button
              type="button"
              onClick={onEdit}
              title={t("common.edit")}
              aria-label={t("common.edit")}
              className="grid size-8 cursor-pointer place-items-center rounded-lg text-mut transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <Pencil className="size-4" />
            </button>
          )}
        </span>
      </div>
    </motion.div>
  );
}

/* ---------- the form ---------- */

function AssistantForm({
  existing,
  skills,
  onSaved,
  onDeleted,
  onCancel,
}: {
  existing?: Assistant;
  skills: SkillInfo[];
  onSaved: (a: Assistant, created: boolean) => void;
  onDeleted?: (id: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const { token } = useAuth();
  const [name, setName] = useState(existing?.name ?? "");
  const [instruction, setInstruction] = useState(existing?.instruction ?? "");
  const [mode, setMode] = useState<AccessMode>(existing ? accessOf(existing.allowed_skill_names) : "all");
  const [picked, setPicked] = useState<string[]>(existing?.allowed_skill_names ?? []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const allowed: string[] | null = mode === "all" ? null : mode === "docs" ? [] : picked;
  const ready = name.trim().length > 0 && (mode !== "some" || picked.length > 0);
  const dirty =
    !existing ||
    existing.name !== name.trim() ||
    existing.instruction !== instruction ||
    !sameAccess(existing.allowed_skill_names, allowed);

  async function save() {
    if (!name.trim()) {
      setErr(t("assistants.error.name"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const saved = existing
        ? await api.assistants.update(token, existing.id, {
            name: name.trim(),
            instruction,
            allowed_skill_names: allowed,
          })
        : await api.assistants.create(token, {
            name: name.trim(),
            instruction,
            allowed_skill_names: allowed,
          });
      onSaved(saved, !existing);
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  const modes: { value: AccessMode; label: string; hint: string }[] = [
    { value: "all", label: t("assistants.access.all"), hint: t("assistants.access.all.hint") },
    { value: "docs", label: t("assistants.access.docs"), hint: t("assistants.access.docs.hint") },
    { value: "some", label: t("assistants.access.some"), hint: t("assistants.access.some.hint") },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <label htmlFor="asst-name" className="mb-1.5 block text-[13px] font-semibold">
          {t("common.name")}
        </label>
        <Input
          id="asst-name"
          autoFocus={!existing}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("assistants.field.name.placeholder")}
          className="h-11 text-[15px]"
        />
      </div>

      <div>
        <label htmlFor="asst-instruction" className="mb-1.5 block text-[13px] font-semibold">
          {t("assistants.field.behaviour")}
        </label>
        <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[12px] text-faint">
          <span>{t("assistants.templates")}</span>
          {TEMPLATES.map(({ key, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setInstruction(t(`assistants.template.${key}.text`))}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-[12px] font-medium text-mut transition-colors hover:border-accent/50 hover:text-ink"
            >
              <Icon className="size-3.5 text-accent" /> {t(`assistants.template.${key}`)}
            </button>
          ))}
        </div>
        <Textarea
          id="asst-instruction"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={5}
          placeholder={t("assistants.field.behaviour.placeholder")}
          className="min-h-32"
        />
      </div>

      <div>
        <p className="mb-2 text-[13px] font-semibold">{t("assistants.field.access")}</p>
        <div role="radiogroup" aria-label={t("assistants.field.access")} className="grid gap-2 sm:grid-cols-3">
          {modes.map((m) => {
            const active = mode === m.value;
            return (
              <button
                key={m.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setMode(m.value)}
                className={`cursor-pointer rounded-xl border p-3.5 text-left transition-colors ${
                  active
                    ? "border-accent bg-accent-soft/50"
                    : "border-line bg-surface hover:border-line-strong hover:bg-surface-2"
                }`}
              >
                <span className="block text-[13.5px] font-semibold">{m.label}</span>
                <span className="mt-1 block text-[12px] leading-relaxed text-mut">{m.hint}</span>
              </button>
            );
          })}
        </div>
        <AnimatePresence initial={false}>
          {mode === "some" && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.24, ease: EASE }}
              className="overflow-hidden"
            >
              <div className="mt-3 rounded-xl border border-line bg-surface-2 p-3.5">
                {skills.length === 0 ? (
                  <p className="text-[13px] text-mut">{t("assistants.skills.none")}</p>
                ) : (
                  <>
                    <div className="mb-2 flex items-center justify-between text-[12px] text-faint">
                      <span>{t("assistants.skills.picked", { n: picked.length, total: skills.length })}</span>
                      <span className="flex gap-3">
                        <button type="button" className="cursor-pointer font-semibold hover:text-ink" onClick={() => setPicked(skills.map((s) => s.name))}>
                          {t("assistants.skills.selectAll")}
                        </button>
                        <button type="button" className="cursor-pointer font-semibold hover:text-ink" onClick={() => setPicked([])}>
                          {t("assistants.skills.clear")}
                        </button>
                      </span>
                    </div>
                    <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto">
                      {skills.map((s) => {
                        const on = picked.includes(s.name);
                        return (
                          <li key={s.name}>
                            <label className="flex cursor-pointer items-start gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-surface">
                              <input
                                type="checkbox"
                                checked={on}
                                onChange={() =>
                                  setPicked((p) => (on ? p.filter((x) => x !== s.name) : [...p, s.name]))
                                }
                                className="mt-1 size-4 accent-[var(--accent)]"
                              />
                              <span className="min-w-0">
                                <span className="block text-[13px] font-medium">{s.description || humanise(s.name)}</span>
                                <span className="block font-mono text-[11px] text-faint">{humanise(s.name)}</span>
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                    {picked.length === 0 && (
                      <p className="mt-2 text-[12px] text-bad">{t("assistants.skills.pickOne")}</p>
                    )}
                  </>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {err && <Notice tone="bad">{err}</Notice>}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
        <Button variant="cta" onClick={save} busy={busy} disabled={!ready || !dirty}>
          {existing ? t("common.save") : t("common.create")}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        {existing && onDeleted && existing.can_edit && (
          <span className="ml-auto">
            <ConfirmAction
              question={t("assistants.delete.question")}
              onConfirm={async () => {
                await api.assistants.remove(token, existing.id);
                onDeleted(existing.id);
              }}
            >
              {(start) => (
                <Button variant="danger" size="sm" onClick={start}>
                  <Trash2 className="size-3.5" /> {t("common.delete")}
                </Button>
              )}
            </ConfirmAction>
          </span>
        )}
      </div>
    </div>
  );
}

/* ---------- try a question ---------- */

function TryBox({ a }: { a: Assistant }) {
  const t = useT();
  const { locale } = useLocale();
  const { token } = useAuth();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [err, setErr] = useState("");

  async function ask() {
    if (!q.trim()) return;
    setBusy(true);
    setErr("");
    setAnswer(null);
    try {
      setAnswer(await api.ask(token, q.trim(), a.id));
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <p className="font-display text-[15px] font-semibold">{t("assistants.try.title")}</p>
      <p className="mt-0.5 text-[12.5px] text-faint">{t("assistants.try.caption")}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void ask();
        }}
        className="mt-3 flex gap-2"
      >
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("assistants.try.placeholder")} />
        <Button type="submit" busy={busy} disabled={!q.trim()}>
          <Send className="size-4" /> {t("assistants.try.ask")}
        </Button>
      </form>
      {err && (
        <div className="mt-3">
          <Notice tone="bad">{err}</Notice>
        </div>
      )}
      {answer && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mt-4">
          {answer.text ? (
            <Markdown text={answer.text} />
          ) : (
            <p className="text-[14px] leading-relaxed">{t("assistants.try.empty")}</p>
          )}
          <p className="mt-2 flex flex-wrap gap-3 text-[12px] text-faint">
            {answer.skills_used.length > 0 && (
              <span>{t("assistants.try.used", { skills: answer.skills_used.map(humanise).join(", ") })}</span>
            )}
            {answer.citations.length > 0 && (
              <span>
                {t(`assistants.try.sources.${pluralKey(locale, answer.citations.length)}`, { n: answer.citations.length })}
              </span>
            )}
          </p>
          <Link
            href={`/?assistant=${a.id}`}
            className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent-strong hover:underline"
          >
            {t("assistants.try.continue")} <ExternalLink className="size-3.5" />
          </Link>
        </motion.div>
      )}
    </div>
  );
}

/* ---------- the page ---------- */

export default function AssistantsPage() {
  const t = useT();
  const { token } = useAuth();
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [view, setView] = useState<View>({ mode: "list" });
  const [notice, setNotice] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [a, s] = await Promise.all([api.assistants.list(token), api.skills(token)]);
      setAssistants(a.assistants);
      setSkills(s.skills);
    } catch (e) {
      setNotice({ tone: "bad", text: errorWords((e as ApiError).message) });
    } finally {
      setLoaded(true);
    }
  }, [token]);
  useLoad(load);

  const say = useCallback((tone: "good" | "bad", text: string) => {
    setNotice({ tone, text });
    setTimeout(() => setNotice(null), 4500);
  }, []);

  const sorted = useMemo(() => [...assistants].sort((a, b) => a.name.localeCompare(b.name)), [assistants]);

  function onSaved(a: Assistant, created: boolean) {
    setAssistants((all) => [...all.filter((x) => x.id !== a.id), a]);
    say("good", created ? t("assistants.ready") : t("assistants.saved"));
    setHighlight(a.id);
    setTimeout(() => setHighlight(null), 2500);
    setView(created ? { mode: "detail", a } : { mode: "list" });
  }

  function onDeleted(id: string) {
    setAssistants((all) => all.filter((x) => x.id !== id));
    say("good", t("assistants.deleted"));
    setView({ mode: "list" });
  }

  const back = (
    <button
      type="button"
      onClick={() => setView({ mode: "list" })}
      className="mb-5 inline-flex cursor-pointer items-center gap-1.5 text-[13px] font-semibold text-mut transition-colors hover:text-ink"
    >
      <ArrowLeft className="size-3.5" /> {t("assistants.back")}
    </button>
  );

  if (view.mode === "new" || view.mode === "edit") {
    const existing = view.mode === "edit" ? view.a : undefined;
    return (
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: EASE }} className="mx-auto max-w-2xl">
        {back}
        <div className="mb-6 flex items-center gap-3">
          {existing ? <Avatar name={existing.name} /> : (
            <span className="grid size-11 place-items-center rounded-2xl bg-accent-soft text-accent">
              <Bot className="size-5" />
            </span>
          )}
          <h2 className="font-display text-[22px] font-bold">{existing ? existing.name : t("assistants.new")}</h2>
        </div>
        <div className="rounded-3xl border border-line bg-surface p-6 [box-shadow:var(--shadow)] sm:p-8">
          <AssistantForm
            existing={existing}
            skills={skills}
            onSaved={onSaved}
            onDeleted={onDeleted}
            onCancel={() => setView(existing ? { mode: "detail", a: existing } : { mode: "list" })}
          />
        </div>
      </motion.div>
    );
  }

  if (view.mode === "detail") {
    const a = assistants.find((x) => x.id === view.a.id) ?? view.a;
    return (
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: EASE }} className="mx-auto flex max-w-2xl flex-col gap-5">
        <div>{back}</div>
        {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
        <div className="rounded-3xl border border-line bg-surface p-6 [box-shadow:var(--shadow)] sm:p-8">
          <div className="flex flex-wrap items-start gap-4">
            <Avatar name={a.name} size="size-14" />
            <div className="min-w-0 flex-1">
              <h2 className="font-display text-[24px] font-bold leading-tight">{a.name}</h2>
              <p className="mt-1 text-[12.5px] text-faint">
                <AccessLine a={a} /> · <Owner a={a} />
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Link href={`/?assistant=${a.id}`}>
                <Button variant="cta">
                  <ExternalLink className="size-4" /> {t("assistants.card.open")}
                </Button>
              </Link>
              {a.can_edit && (
                <Button variant="ghost" onClick={() => setView({ mode: "edit", a })}>
                  <Pencil className="size-4" /> {t("common.edit")}
                </Button>
              )}
            </div>
          </div>
          <p className="mt-5 whitespace-pre-wrap text-[14px] leading-relaxed text-mut">
            {a.instruction || t("assistants.detail.noInstruction")}
          </p>
        </div>
        <TryBox a={a} />
      </motion.div>
    );
  }

  return (
    <Stagger className="flex flex-col gap-6">
      <PageHero
        eyebrow={t("assistants.eyebrow")}
        title={t("assistants.title")}
        lead={t("assistants.lead")}
        actions={
          <Button variant="cta" onClick={() => setView({ mode: "new" })}>
            <Plus className="size-4" /> {t("assistants.new")}
          </Button>
        }
      />
      <AnimatePresence>
        {notice && (
          <StaggerItem rise={0}>
            <Notice tone={notice.tone}>{notice.text}</Notice>
          </StaggerItem>
        )}
      </AnimatePresence>
      <StaggerItem>
        {loaded && sorted.length === 0 ? (
          <div className="rounded-3xl border border-line bg-surface">
            <Empty
              icon={<Bot className="size-6" />}
              title={t("assistants.empty.title")}
              hint={t("assistants.empty.hint")}
              action={
                <Button onClick={() => setView({ mode: "new" })}>
                  <Plus className="size-4" /> {t("assistants.new")}
                </Button>
              }
            />
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <AnimatePresence initial={false}>
              {sorted.map((a) => (
                <motion.div
                  key={a.id}
                  layout
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1, boxShadow: highlight === a.id ? "var(--glow)" : "none" }}
                  exit={{ opacity: 0 }}
                  className="rounded-2xl"
                >
                  <AssistantCard
                    a={a}
                    onOpen={() => setView({ mode: "detail", a })}
                    onEdit={() => setView({ mode: "edit", a })}
                  />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </StaggerItem>
    </Stagger>
  );
}
