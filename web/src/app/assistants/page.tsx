"use client";

/* Assistants — a helper you set up once for a team.
 *
 * The old page asked for a "persona", an "instruction" and a "skill
 * allow-list". Someone in HR has no way in to that. This one asks three
 * questions in plain words — who is it for, how should it behave, what may it
 * do — and starts from a template so the page is never a blank box.
 *
 * The signature is the preview rail: the assistant's card assembles itself as
 * you type, and directly under it is a real conversation with the saved
 * assistant. You are always looking at the thing you are making. */

import {
  Bot,
  Check,
  Headphones,
  Plus,
  Save,
  Sparkles,
  Wallet,
  Users,
  Wrench,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  LANGUAGE_LABELS,
  type ApiError,
  type Assistant,
  type Language,
  type SkillInfo,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { errorWords } from "@/lib/words";
import { Button, Input, Picker, Textarea } from "@/components/ui";
import {
  EASE,
  Empty,
  Notice,
  PageHero,
  Stagger,
  StaggerItem,
} from "@/components/pro";
import { AssistantsSkeleton } from "@/components/skeleton";
import { PreviewThread } from "@/components/chat-thread";

/* Deterministic gradient + initials, so an assistant looks the same everywhere. */
const AVATARS = [
  "linear-gradient(135deg,#ec2336,#7a1220)",
  "linear-gradient(135deg,#3e3b4e,#1a1822)",
  "linear-gradient(135deg,#c0392b,#8e44ad)",
  "linear-gradient(135deg,#2c3e50,#4ca1af)",
  "linear-gradient(135deg,#603813,#b29f94)",
  "linear-gradient(135deg,#16222a,#3a6073)",
];
function avatarFor(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return AVATARS[h % AVATARS.length];
}
function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/* A blank instruction box is the hardest part of this page for someone who
   hasn't written one before. These are starting points, not presets — every
   field stays editable afterwards. */
const TEMPLATES = [
  {
    key: "helpdesk",
    icon: Headphones,
    name: "Helpdesk",
    forWho: "Front desk and support",
    instruction:
      "Answer staff questions about our policies and procedures. Quote the exact rule and say which document it came from. If the answer isn't in what you've read, say so and suggest who to ask.",
  },
  {
    key: "finance",
    icon: Wallet,
    name: "Finance analyst",
    forWho: "Finance team",
    instruction:
      "Report figures exactly as the data returns them — never estimate or round without saying so. Always show the period the number covers. If a figure looks unusual, point it out rather than explaining it away.",
  },
  {
    key: "hr",
    icon: Users,
    name: "HR assistant",
    forWho: "People team",
    instruction:
      "Help with leave, onboarding and workplace policy questions. Be warm and concrete. Never speculate about an individual's records, and direct anything sensitive to a person rather than answering it yourself.",
  },
];

export default function AssistantsPage() {
  const { token } = useAuth();
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loaded, setLoaded] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [instruction, setInstruction] = useState("");
  const [language, setLanguage] = useState<Language>("auto");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [limitSkills, setLimitSkills] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const refresh = useCallback(
    () =>
      api.assistants
        .list(token)
        .then((d) => setAssistants(d.assistants))
        .catch(() => setAssistants([])),
    [token],
  );

  useEffect(() => {
    Promise.all([
      refresh(),
      api
        .skills(token)
        .then((d) => setSkills(d.skills))
        .catch(() => setSkills([])),
    ]).finally(() => setLoaded(true));
  }, [token, refresh]);

  function reset() {
    setProblem(null);
    setSaved(null);
  }

  function startNew(template?: (typeof TEMPLATES)[number]) {
    setEditingId(null);
    setCreating(true);
    setName(template?.name ?? "");
    setInstruction(template?.instruction ?? "");
    setLanguage("auto");
    setChecked(new Set());
    setLimitSkills(false);
    reset();
  }

  function edit(a: Assistant) {
    setEditingId(a.id);
    setCreating(false);
    setName(a.name);
    setInstruction(a.instruction);
    setLanguage(a.language ?? "auto");
    setChecked(new Set(a.allowed_skill_names ?? []));
    setLimitSkills(Boolean(a.allowed_skill_names?.length));
    reset();
  }

  async function save() {
    if (!name.trim()) {
      setProblem("Give it a name first — that's how people will pick it.");
      return;
    }
    setBusy(true);
    reset();
    const body = {
      name: name.trim(),
      instruction,
      allowed_skill_names: limitSkills && checked.size ? [...checked] : null,
      language,
    };
    try {
      const a = editingId
        ? await api.assistants.update(token, editingId, body)
        : await api.assistants.create(token, body);
      setEditingId(a.id);
      setCreating(false);
      setSaved(
        editingId
          ? "Saved. Everyone using it sees the change straight away."
          : `${a.name} is ready — try it below.`,
      );
      await refresh();
    } catch (e) {
      setProblem(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  const open = creating || editingId !== null;

  const dirty = useMemo(() => {
    if (creating) return Boolean(name.trim() || instruction.trim());
    const a = assistants.find((x) => x.id === editingId);
    if (!a) return false;
    const was = new Set(a.allowed_skill_names ?? []);
    const sameSkills =
      limitSkills === Boolean(a.allowed_skill_names?.length) &&
      was.size === checked.size &&
      [...checked].every((s) => was.has(s));
    return (
      a.name !== name ||
      a.instruction !== instruction ||
      (a.language ?? "auto") !== language ||
      !sameSkills
    );
  }, [creating, editingId, assistants, name, instruction, language, checked, limitSkills]);

  if (!loaded) return <AssistantsSkeleton />;

  return (
    <Stagger className="flex flex-col gap-6">
      <PageHero
        eyebrow="Assistants"
        title="Set up a helper for a team"
        lead="An assistant is the same AI with a job description: how to answer, in which language, and which company data it may touch. Everyone in the team gets the same behaviour."
        actions={
          <Button variant="cta" onClick={() => startNew()}>
            <Plus className="size-4" />
            New assistant
          </Button>
        }
      />

      {assistants.length === 0 && !open ? (
        <StaggerItem>
          <section className="rounded-3xl border border-line bg-surface p-8 [box-shadow:var(--shadow)]">
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="font-display text-[19px] font-semibold">
                Start from one of these
              </h2>
              <p className="mx-auto mt-2 max-w-lg text-[13.5px] leading-relaxed text-mut">
                Each one comes with wording that works. Change anything you like
                afterwards — nothing here is fixed.
              </p>
            </div>
            <div className="mt-7 grid gap-3 md:grid-cols-3">
              {TEMPLATES.map((t, i) => (
                <motion.button
                  key={t.key}
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 + i * 0.08, duration: 0.45, ease: EASE }}
                  onClick={() => startNew(t)}
                  className="group cursor-pointer rounded-2xl border border-line bg-surface p-5 text-left transition-[border-color,transform,box-shadow] duration-300 hover:-translate-y-1 hover:border-accent/50 card-ring"
                >
                  <span className="grid size-10 place-items-center rounded-xl bg-accent-soft text-accent transition-colors group-hover:bg-accent group-hover:text-accent-ink">
                    <t.icon className="size-5" />
                  </span>
                  <span className="font-display mt-4 block text-[15px] font-semibold">
                    {t.name}
                  </span>
                  <span className="mt-0.5 block text-[12px] text-faint">
                    For {t.forWho.toLowerCase()}
                  </span>
                  <span className="mt-3 block text-[12.5px] leading-relaxed text-mut">
                    &ldquo;{t.instruction.slice(0, 92)}…&rdquo;
                  </span>
                </motion.button>
              ))}
            </div>
            <p className="mt-7 text-center">
              <button
                onClick={() => startNew()}
                className="cursor-pointer text-[13px] font-semibold text-accent transition-colors hover:text-accent-hover"
              >
                Or start from scratch
              </button>
            </p>
          </section>
        </StaggerItem>
      ) : (
        <StaggerItem>
          <div className="grid items-start gap-5 xl:grid-cols-12">
            {/* ---- rail: the assistants that exist ---- */}
            <aside className="flex flex-col gap-2 xl:col-span-3">
              <p className="px-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-mut">
                Your assistants
              </p>
              <AnimatePresence initial={false}>
                {assistants.map((a) => {
                  const active = a.id === editingId;
                  return (
                    <motion.button
                      key={a.id}
                      layout
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.25, ease: EASE }}
                      onClick={() => edit(a)}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 text-left transition-colors ${
                        active
                          ? "border-accent bg-accent-soft"
                          : "border-line bg-surface hover:border-line-strong"
                      }`}
                    >
                      <span
                        className="grid size-9 shrink-0 place-items-center rounded-lg text-[12px] font-bold text-white"
                        style={{ background: avatarFor(a.id) }}
                      >
                        {initials(a.name)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13.5px] font-semibold">
                          {a.name}
                        </span>
                        <span className="block truncate text-[11.5px] text-mut">
                          {a.allowed_skill_names?.length
                            ? `${a.allowed_skill_names.length} of ${skills.length} tasks`
                            : "Everything it's allowed"}
                        </span>
                      </span>
                    </motion.button>
                  );
                })}
              </AnimatePresence>
              <button
                onClick={() => startNew()}
                className="flex cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-dashed border-line-strong py-3 text-[13px] font-semibold text-mut transition-colors hover:border-accent hover:text-accent"
              >
                <Plus className="size-4" />
                New assistant
              </button>
            </aside>

            {/* ---- the three questions ---- */}
            <section className="rounded-2xl border border-line bg-surface [box-shadow:var(--shadow)] xl:col-span-5">
              <header className="border-b border-line px-6 py-4">
                <h2 className="font-display text-[16px] font-semibold">
                  {creating ? "New assistant" : name || "Assistant"}
                </h2>
                <p className="mt-0.5 text-[13px] text-mut">
                  {creating
                    ? "Three questions and it's live."
                    : "Changes apply the moment you save."}
                </p>
              </header>

              <div className="flex flex-col gap-6 p-6">
                <Field
                  n={1}
                  label="What should people call it?"
                  hint="This is the name in the assistant list when someone starts a chat."
                >
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Helpdesk"
                  />
                </Field>

                <Field
                  n={2}
                  label="How should it behave?"
                  hint="Write it the way you'd brief a new colleague on their first day."
                >
                  <Textarea
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    placeholder="Answer briefly. Always say which document an answer came from. If you don't know, say so."
                    className="min-h-36"
                  />
                  {!instruction.trim() && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {TEMPLATES.map((t) => (
                        <button
                          key={t.key}
                          onClick={() => setInstruction(t.instruction)}
                          className="cursor-pointer rounded-full border border-line px-2.5 py-1 text-[11.5px] font-medium text-mut transition-colors hover:border-accent hover:text-accent"
                        >
                          Use {t.name.toLowerCase()} wording
                        </button>
                      ))}
                    </div>
                  )}
                </Field>

                <Field
                  n={3}
                  label="What is it allowed to do?"
                  hint="This can only narrow what a person already has. It can never hand out access they don't have."
                >
                  <div className="flex flex-col gap-2">
                    <Choice
                      selected={!limitSkills}
                      onSelect={() => setLimitSkills(false)}
                      title="Everything the person already can"
                      body="Whatever the person chatting is allowed to see, this assistant can use. Right for most teams."
                    />
                    <Choice
                      selected={limitSkills}
                      onSelect={() => setLimitSkills(true)}
                      title="Only certain tasks"
                      body="Keep it to a short list — useful for a narrow, single-purpose helper."
                    />
                  </div>

                  <AnimatePresence initial={false}>
                    {limitSkills && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.26, ease: EASE }}
                        className="overflow-hidden"
                      >
                        <div className="mt-3 max-h-64 overflow-y-auto rounded-xl border border-line p-2">
                          {skills.length === 0 ? (
                            <p className="px-2 py-3 text-[12.5px] text-faint">
                              Nothing to choose from yet.
                            </p>
                          ) : (
                            skills.map((s) => {
                              const on = checked.has(s.name);
                              return (
                                <button
                                  key={s.name}
                                  onClick={() =>
                                    setChecked((prev) => {
                                      const next = new Set(prev);
                                      if (next.has(s.name)) next.delete(s.name);
                                      else next.add(s.name);
                                      return next;
                                    })
                                  }
                                  className={`flex w-full cursor-pointer items-start gap-2.5 rounded-lg p-2.5 text-left transition-colors ${
                                    on ? "bg-accent-soft" : "hover:bg-surface-2"
                                  }`}
                                >
                                  <span
                                    className={`mt-0.5 grid size-4.5 shrink-0 place-items-center rounded-[5px] border transition-colors ${
                                      on
                                        ? "border-accent bg-accent text-accent-ink"
                                        : "border-line-strong"
                                    }`}
                                  >
                                    {on && <Check className="size-3" />}
                                  </span>
                                  <span className="min-w-0">
                                    <span className="block text-[13px] font-medium">
                                      {s.description}
                                    </span>
                                    <span className="mt-0.5 block truncate font-mono text-[10.5px] text-faint">
                                      {s.name}
                                    </span>
                                  </span>
                                </button>
                              );
                            })
                          )}
                        </div>
                        {limitSkills && checked.size === 0 && (
                          <p className="mt-2 text-[12px] text-warn">
                            Nothing ticked — pick at least one, or switch back above.
                          </p>
                        )}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </Field>

                <div>
                  <p className="mb-1.5 text-[13px] font-semibold">
                    Which language should it answer in?
                  </p>
                  <Picker
                    value={language}
                    onChange={(v) => setLanguage(v as Language)}
                    ariaLabel="Answer language"
                    options={Object.entries(LANGUAGE_LABELS).map(([v, l]) => ({
                      value: v,
                      label: v === "auto" ? "Match the question" : l,
                    }))}
                  />
                </div>

                <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
                  <Button variant="cta" onClick={save} busy={busy} disabled={!dirty && !creating}>
                    <Save className="size-4" />
                    {creating ? "Create assistant" : "Save changes"}
                  </Button>
                  {dirty && !busy && (
                    <span className="text-[12.5px] text-warn">Not saved yet</span>
                  )}
                  {!dirty && !creating && editingId && (
                    <span className="text-[12.5px] text-faint">
                      Everything saved
                    </span>
                  )}
                </div>

                <AnimatePresence mode="wait">
                  {problem && <Notice key="bad" tone="bad">{problem}</Notice>}
                  {saved && !problem && (
                    <Notice key="ok" tone="good">{saved}</Notice>
                  )}
                </AnimatePresence>
              </div>
            </section>

            {/* ---- the thing you're making ---- */}
            <aside className="flex flex-col gap-4 xl:col-span-4 xl:sticky xl:top-4">
              <PreviewCard
                name={name}
                instruction={instruction}
                language={language}
                limited={limitSkills ? checked.size : null}
                totalSkills={skills.length}
                id={editingId}
              />
              <section className="rounded-2xl border border-line bg-surface [box-shadow:var(--shadow)]">
                <header className="flex items-center gap-2.5 border-b border-line px-5 py-3.5">
                  <span className="grid size-7 place-items-center rounded-lg bg-accent-soft text-accent">
                    <Bot className="size-3.5" />
                  </span>
                  <div>
                    <h3 className="font-display text-[14px] font-semibold">
                      Try it out
                    </h3>
                    <p className="text-[12px] text-mut">
                      {editingId
                        ? "A real answer, using this assistant."
                        : "Save it first, then talk to it here."}
                    </p>
                  </div>
                </header>
                <div className="p-5">
                  {editingId ? (
                    <PreviewThread
                      key={editingId}
                      assistantId={editingId}
                      placeholder="Ask it something…"
                    />
                  ) : (
                    <Empty
                      icon={<Sparkles className="size-6" />}
                      title="Nothing to talk to yet"
                      hint="Fill in the name and behaviour, press Create, and a real conversation appears here."
                    />
                  )}
                </div>
              </section>
            </aside>
          </div>
        </StaggerItem>
      )}
    </Stagger>
  );
}

/* ---------- pieces ---------- */

function Field({
  n,
  label,
  hint,
  children,
}: {
  n: number;
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline gap-2.5">
        <span className="font-display text-[13px] font-bold text-accent">
          {n}
        </span>
        <div className="min-w-0">
          <p className="text-[13.5px] font-semibold">{label}</p>
          <p className="mt-0.5 text-[12px] leading-relaxed text-mut">{hint}</p>
        </div>
      </div>
      <div className="pl-[26px]">{children}</div>
    </div>
  );
}

function Choice({
  selected,
  onSelect,
  title,
  body,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  body: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 text-left transition-colors ${
        selected
          ? "border-accent bg-accent-soft/50"
          : "border-line hover:border-line-strong hover:bg-surface-2"
      }`}
    >
      <span
        className={`mt-0.5 grid size-4.5 shrink-0 place-items-center rounded-full border-2 transition-colors ${
          selected ? "border-accent" : "border-line-strong"
        }`}
      >
        {selected && <span className="size-2 rounded-full bg-accent" />}
      </span>
      <span className="min-w-0">
        <span className="block text-[13.5px] font-semibold">{title}</span>
        <span className="mt-0.5 block text-[12px] leading-relaxed text-mut">
          {body}
        </span>
      </span>
    </button>
  );
}

/* The card assembles as you type — the page's signature. It shows exactly what
   a colleague will meet: the name, the first line of the briefing, and what it
   may reach. */
function PreviewCard({
  name,
  instruction,
  language,
  limited,
  totalSkills,
  id,
}: {
  name: string;
  instruction: string;
  language: Language;
  limited: number | null;
  totalSkills: number;
  id: string | null;
}) {
  const shown = name.trim() || "Untitled assistant";
  return (
    <div className="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 [box-shadow:var(--shadow)]">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(320px 140px at 100% 0%, color-mix(in oklab, var(--accent) 12%, transparent), transparent 70%)",
        }}
      />
      <div className="flex items-center gap-3.5">
        <motion.span
          key={shown}
          initial={{ scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 320, damping: 22 }}
          className="grid size-12 shrink-0 place-items-center rounded-xl text-[15px] font-bold text-white"
          style={{ background: avatarFor(id ?? shown) }}
        >
          {initials(shown)}
        </motion.span>
        <div className="min-w-0">
          <p className="font-display truncate text-[16px] font-semibold">
            {shown}
          </p>
          <p className="text-[12px] text-mut">
            {language === "auto"
              ? "Answers in the language you ask in"
              : `Always answers in ${LANGUAGE_LABELS[language]}`}
          </p>
        </div>
      </div>

      <p className="mt-4 min-h-[3.5rem] rounded-xl border border-line bg-surface-2 p-3 text-[12.5px] leading-relaxed text-mut">
        {instruction.trim() ? (
          <>&ldquo;{instruction.trim().slice(0, 180)}
          {instruction.trim().length > 180 ? "…" : ""}&rdquo;</>
        ) : (
          <span className="text-faint">
            However it behaves will show up here as you write it.
          </span>
        )}
      </p>

      <p className="mt-3 flex items-center gap-1.5 text-[12px] text-mut">
        <Wrench className="size-3.5 text-accent" />
        {limited === null
          ? "Can use anything the person is allowed to"
          : limited === 0
            ? "No tasks picked yet"
            : `Limited to ${limited} of ${totalSkills} tasks`}
      </p>
    </div>
  );
}
