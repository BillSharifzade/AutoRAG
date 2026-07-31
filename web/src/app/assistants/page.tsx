"use client";

/* No-code assistant builder: list · editor with skill toggles · live preview.
   The allow-list can only narrow what the caller's RBAC already permits. */

import {
  Bot,
  Check,
  CheckCheck,
  Plus,
  Sparkles,
  Wrench,
  X,
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
  Textarea,
} from "@/components/ui";
import { AssistantsSkeleton } from "@/components/skeleton";
import { ChatThread } from "@/components/chat-thread";

/* Deterministic pastel gradient + initials for an assistant avatar. */
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
  if (parts.length === 0) return "A";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function scopeLabel(a: Assistant, totalSkills: number) {
  if (!a.allowed_skill_names || a.allowed_skill_names.length === 0)
    return `All ${totalSkills} skills`;
  return `${a.allowed_skill_names.length} of ${totalSkills} skills`;
}

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
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ text: string; bad?: boolean } | null>(
    null,
  );

  const refresh = useCallback(() => {
    return api.assistants
      .list(token)
      .then((d) => setAssistants(d.assistants))
      .catch(() => setAssistants([]));
  }, [token]);

  useEffect(() => {
    Promise.all([
      refresh(),
      api
        .skills(token)
        .then((d) => setSkills(d.skills))
        .catch(() => setSkills([])),
    ]).finally(() => setLoaded(true));
  }, [token, refresh]);

  function startNew() {
    setEditingId(null);
    setCreating(true);
    setName("");
    setInstruction("");
    setChecked(new Set());
    setStatus(null);
  }

  function edit(a: Assistant) {
    setEditingId(a.id);
    setCreating(false);
    setName(a.name);
    setInstruction(a.instruction);
    setLanguage(a.language ?? "auto");
    setChecked(new Set(a.allowed_skill_names ?? []));
    setStatus(null);
  }

  async function save() {
    if (!name.trim()) {
      setStatus({ text: "Name is required", bad: true });
      return;
    }
    setBusy(true);
    const body = {
      name: name.trim(),
      instruction,
      allowed_skill_names: checked.size ? [...checked] : null,
      language,
    };
    try {
      const saved = editingId
        ? await api.assistants.update(token, editingId, body)
        : await api.assistants.create(token, body);
      setEditingId(saved.id);
      setCreating(false);
      setStatus({ text: editingId ? "Saved" : "Created" });
      await refresh();
    } catch (e) {
      setStatus({ text: (e as ApiError).message, bad: true });
    } finally {
      setBusy(false);
    }
  }

  function toggleSkill(n: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });
  }

  const editorOpen = creating || editingId !== null;
  const allSelected = skills.length > 0 && checked.size === skills.length;

  const dirty = useMemo(() => {
    if (creating) return name.trim() !== "" || instruction !== "" || checked.size > 0;
    const a = assistants.find((x) => x.id === editingId);
    if (!a) return false;
    const cur = new Set(a.allowed_skill_names ?? []);
    const sameSkills =
      cur.size === checked.size && [...checked].every((s) => cur.has(s));
    return (
      a.name !== name ||
      a.instruction !== instruction ||
      (a.language ?? "auto") !== language ||
      !sameSkills
    );
  }, [creating, editingId, assistants, name, instruction, language, checked]);

  if (!loaded) {
    return (
      <Rise>
        <AssistantsSkeleton />
      </Rise>
    );
  }

  return (
    <Rise className="grid items-start gap-6 xl:grid-cols-12">
      {/* List */}
      <div className="flex flex-col gap-2.5 xl:col-span-3">
        <Button
          variant={editorOpen && creating ? "primary" : "soft"}
          onClick={startNew}
          className="justify-start"
        >
          <Plus className="size-4" /> New assistant
        </Button>

        <AnimatePresence initial={false}>
          {assistants.map((a, i) => {
            const active = a.id === editingId;
            return (
              <motion.button
                key={a.id}
                layout
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.04, 0.3) }}
                onClick={() => edit(a)}
                className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 text-left transition-all ${
                  active
                    ? "border-accent bg-accent-soft [box-shadow:var(--glow)]"
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
                    {scopeLabel(a, skills.length)}
                  </span>
                </span>
              </motion.button>
            );
          })}
        </AnimatePresence>

        {assistants.length === 0 && (
          <div className="rounded-xl border border-dashed border-line-strong p-5 text-center">
            <p className="text-[12.5px] text-faint">
              No assistants yet — create your first one.
            </p>
          </div>
        )}
      </div>

      {/* Editor */}
      <Card className="xl:col-span-5">
        <CardHeader
          icon={<Sparkles className="size-4" />}
          title={
            editorOpen
              ? creating
                ? "New assistant"
                : `Editing · ${name || "assistant"}`
              : "Assistant builder"
          }
          sub="A persona plus an optional skill allow-list — it can only narrow what the user already may use."
          right={dirty ? <Chip tone="warn">Unsaved</Chip> : undefined}
        />
        {editorOpen ? (
          <div className="p-6">
            <Label>Name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Helpdesk"
            />

            <Label>Instruction</Label>
            <Textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Answer concisely, cite sources, never guess a number."
            />

            <Label>Answer language</Label>
            <Picker
              value={language}
              onChange={(v) => setLanguage(v as Language)}
              options={(Object.keys(LANGUAGE_LABELS) as Language[]).map((v) => ({
                value: v,
                label: LANGUAGE_LABELS[v],
              }))}
              ariaLabel="Answer language"
            />
            <p className="mt-1.5 text-[12px] text-faint">
              Pinning a language overrides the reader&apos;s own choice — useful
              for a customer-facing assistant.
            </p>

            <div className="mb-1.5 mt-4 flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-mut">
                Skills{" "}
                {checked.size > 0 && (
                  <span className="text-accent-strong">· {checked.size} on</span>
                )}
              </span>
              {skills.length > 0 && (
                <button
                  onClick={() =>
                    setChecked(
                      allSelected
                        ? new Set()
                        : new Set(skills.map((s) => s.name)),
                    )
                  }
                  className="inline-flex cursor-pointer items-center gap-1 text-[11.5px] font-semibold text-mut transition-colors hover:text-accent"
                >
                  {allSelected ? (
                    <>
                      <X className="size-3" /> Clear all
                    </>
                  ) : (
                    <>
                      <CheckCheck className="size-3" /> Select all
                    </>
                  )}
                </button>
              )}
            </div>

            <p className="mb-2.5 text-[12px] text-faint">
              {checked.size === 0
                ? "Empty = every skill your role can use."
                : "Only the checked skills will be offered to this assistant."}
            </p>

            <div className="flex flex-col gap-2">
              {skills.map((s) => {
                const on = checked.has(s.name);
                return (
                  <button
                    key={s.name}
                    onClick={() => toggleSkill(s.name)}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-left transition-all ${
                      on
                        ? "border-accent bg-accent-soft"
                        : "border-line hover:border-line-strong"
                    }`}
                  >
                    <span
                      className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border transition-colors ${
                        on
                          ? "border-accent bg-accent text-accent-ink"
                          : "border-line-strong"
                      }`}
                    >
                      {on && <Check className="size-3.5" />}
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5 font-mono text-[12.5px] font-semibold">
                        <Wrench className="size-3.5 shrink-0 text-mut" /> {s.name}
                      </span>
                      <span className="mt-0.5 block text-[12.5px] leading-relaxed text-mut">
                        {s.description}
                      </span>
                    </span>
                  </button>
                );
              })}
              {skills.length === 0 && (
                <p className="text-[12.5px] text-faint">
                  No skills are visible to your role.
                </p>
              )}
            </div>

            <div className="mt-5 flex items-center gap-3">
              <Button onClick={save} busy={busy} disabled={!dirty && !creating}>
                {editingId ? "Save changes" : "Create assistant"}
              </Button>
              <AnimatePresence mode="wait">
                {status && (
                  <motion.div
                    key={status.text}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0 }}
                  >
                    <Chip tone={status.bad ? "bad" : "good"}>
                      {!status.bad && <Check className="size-3" />}
                      {status.text}
                    </Chip>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        ) : (
          <div className="p-6">
            <EmptyState
              icon={<Sparkles className="size-6" />}
              title="Build or pick an assistant"
              hint="Create a new persona, or select one on the left to edit it."
            >
              <Button variant="soft" onClick={startNew} className="mt-2">
                <Plus className="size-4" /> New assistant
              </Button>
            </EmptyState>
          </div>
        )}
      </Card>

      {/* Live preview */}
      <Card className="xl:col-span-4">
        <CardHeader
          icon={<Bot className="size-4" />}
          title="Live preview"
          sub={
            editingId
              ? "Chatting through this saved assistant."
              : "Save the assistant to try it here."
          }
        />
        <div className="p-6">
          {editingId ? (
            <ChatThread
              key={editingId}
              assistantId={editingId}
              compact
              placeholder="Try your assistant…"
            />
          ) : (
            <EmptyState
              icon={<Bot className="size-6" />}
              title="No assistant selected"
              hint={
                creating
                  ? "Create the assistant first — then test it live right here."
                  : "Create or pick one — then test it live right here."
              }
            />
          )}
        </div>
      </Card>
    </Rise>
  );
}
