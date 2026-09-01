"use client";

/* Writing a procedure — the SKILL.md editor.
 *
 * A procedure is a document, not a sequence of settings, so this is not a
 * stepped wizard: it is the document on the left and the file the assistant
 * will actually read on the right, updating as you type.
 *
 * Two things carry the design. First, the *description coach*: a skill almost
 * never fails by being rejected, it fails by never being chosen, and the
 * description is the only thing that decides that — so it is reviewed live
 * against the published guidance instead of being a plain text box. Second,
 * the *disclosure map*: it shows what is loaded always, what is loaded when the
 * skill fires, and what is loaded only if the instructions ask — which is the
 * whole reason a company can hold fifty of these at once. */

import {
  AlertTriangle,
  Check,
  ChevronDown,
  Download,
  FileCode2,
  FilePlus2,
  Layers,
  Play,
  Plus,
  ScrollText,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import {
  api,
  type ApiError,
  type SkillDefinitionInput,
  type SkillResource,
  type SkillTestRun,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { errorWords } from "@/lib/words";
import {
  ADVISED_MAX_BODY_LINES,
  EXAMPLE_DESCRIPTION,
  MAX_DESCRIPTION,
  MAX_NAME,
  bodyLines,
  metadataWords,
  nameProblem,
  renderSkillMd,
  resourceProblem,
  reviewDescription,
  slugify,
  unreferencedResources,
} from "@/lib/skills";
import { AudiencePicker } from "@/components/audience";
import { Button, Input, Textarea } from "@/components/ui";
import { ConfirmAction, EASE, Explain, Notice } from "@/components/pro";

const PLACEHOLDER_BODY = `# Writing the weekly report

## Steps
1. Pull last week's totals for every store.
2. Compare each against the same week last year.
3. Flag any store down more than 10%.
4. Lead with the flagged stores, then the totals.

## House rules
- Money always in somoni, thousands separated.
- Never estimate a missing week — say it is missing.

Regional groupings: see reference/regions.md`;

/* ---------- a labelled block of the document ---------- */

function Section({
  n,
  title,
  hint,
  right,
  children,
}: {
  n: number;
  title: string;
  hint?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-line px-6 py-5 first:border-t-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 font-display text-[15px] font-semibold">
            <span className="grid size-5 shrink-0 place-items-center rounded-full bg-surface-2 text-[10.5px] font-bold text-mut">
              {n}
            </span>
            {title}
          </h3>
          {hint && (
            <p className="mt-1 text-[12.5px] leading-relaxed text-mut">{hint}</p>
          )}
        </div>
        {right}
      </div>
      <div className="mt-3.5">{children}</div>
    </section>
  );
}

function Counter({ used, max }: { used: number; max: number }) {
  const over = used > max;
  const near = !over && used > max * 0.85;
  return (
    <span
      className={`shrink-0 font-mono text-[11.5px] tabular-nums ${
        over ? "text-bad" : near ? "text-warn" : "text-faint"
      }`}
    >
      {used}/{max}
    </span>
  );
}

/* ---------- the description coach ---------- */

function DescriptionCoach({ text }: { text: string }) {
  const notes = reviewDescription(text);
  const failing = notes.filter((n) => !n.ok);
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface-2 p-3.5">
      <p className="flex items-center gap-1.5 text-[12px] font-semibold text-mut">
        <Sparkles className="size-3.5 text-accent" />
        How the assistant will read this
      </p>
      <ul className="mt-2.5 flex flex-col gap-2">
        {notes.map((n) => (
          <li key={n.label} className="flex items-start gap-2">
            <span
              className={`mt-px grid size-4 shrink-0 place-items-center rounded-full ${
                n.ok ? "bg-good-soft text-good" : "bg-surface text-faint"
              }`}
            >
              {n.ok ? (
                <Check className="size-2.5" />
              ) : (
                <span className="size-1.5 rounded-full bg-current" />
              )}
            </span>
            <span className="min-w-0">
              <span
                className={`block text-[12.5px] ${
                  n.ok ? "text-mut" : "font-semibold text-ink"
                }`}
              >
                {n.label}
              </span>
              {!n.ok && (
                <span className="mt-0.5 block text-[12px] leading-relaxed text-mut">
                  {n.why}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {failing.length === 0 && (
        <p className="mt-2.5 border-t border-line pt-2.5 text-[12px] text-good">
          This should get picked up reliably.
        </p>
      )}
    </div>
  );
}

/* ---------- one bundled file ---------- */

function ResourceRow({
  res,
  all,
  cited,
  onChange,
  onRemove,
}: {
  res: SkillResource;
  all: SkillResource[];
  cited: boolean;
  onChange: (r: SkillResource) => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(!res.content);
  const problem = resourceProblem(res.path, all);
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <div className="flex items-center gap-2 bg-surface-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-label={open ? "Collapse" : "Expand"}
          className="grid size-6 shrink-0 cursor-pointer place-items-center rounded text-faint transition-colors hover:text-ink"
        >
          <ChevronDown
            className={`size-3.5 transition-transform ${open ? "" : "-rotate-90"}`}
          />
        </button>
        <Input
          value={res.path}
          onChange={(e) => onChange({ ...res, path: e.target.value })}
          placeholder="reference/regions.md"
          aria-label="File name"
          className="h-8 flex-1 border-0 bg-transparent px-0 font-mono text-[12.5px] hover:border-0 focus:border-0"
        />
        {!cited && !problem && (
          <span
            title="The instructions never mention this file, so it will never be opened."
            className="hidden shrink-0 items-center gap-1 rounded-md bg-warn-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-warn sm:inline-flex"
          >
            <AlertTriangle className="size-3" /> not referenced
          </span>
        )}
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${res.path || "file"}`}
          className="grid size-7 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
      {problem && (
        <p className="border-t border-line px-3 py-1.5 text-[11.5px] text-bad">
          {problem}
        </p>
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
            <Textarea
              value={res.content}
              onChange={(e) => onChange({ ...res, content: e.target.value })}
              placeholder="Anything long the instructions can point at — a table of regions, a schema, a template."
              aria-label="File contents"
              className="min-h-28 rounded-none border-0 border-t border-line font-mono text-[12px] hover:border-line focus:border-line"
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ---------- what gets loaded, and when ---------- */

function DisclosureMap({
  draft,
  lines,
}: {
  draft: SkillDefinitionInput;
  lines: number;
}) {
  const levels = [
    {
      icon: Layers,
      when: "Always loaded",
      what: "Name and description",
      detail: `about ${metadataWords(draft.name, draft.description)} words of the assistant's memory, for every conversation`,
      tone: "accent" as const,
    },
    {
      icon: ScrollText,
      when: "Loaded when the skill fires",
      what: "These instructions",
      detail:
        lines === 0
          ? "nothing written yet"
          : `${lines} ${lines === 1 ? "line" : "lines"}${
              lines > ADVISED_MAX_BODY_LINES
                ? " — past 500, move detail into a reference file"
                : ""
            }`,
      tone: lines > ADVISED_MAX_BODY_LINES ? ("warn" as const) : ("neutral" as const),
    },
    {
      icon: FileCode2,
      when: "Loaded only if asked for",
      what: "Reference files",
      detail:
        draft.resources.length === 0
          ? "none bundled — they cost nothing until read"
          : draft.resources.map((r) => r.path).join(", "),
      tone: "neutral" as const,
    },
  ];
  return (
    <ol className="flex flex-col gap-2.5">
      {levels.map(({ icon: Icon, when, what, detail, tone }, i) => (
        <li
          key={when}
          className={`rounded-xl border p-3 ${
            tone === "accent"
              ? "border-accent/40 bg-accent-soft/40"
              : tone === "warn"
                ? "border-warn/40 bg-warn-soft/40"
                : "border-line bg-surface"
          }`}
        >
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-mut">
            <Icon className="size-3.5" />
            {i + 1} · {when}
          </p>
          <p className="mt-1 text-[13px] font-semibold">{what}</p>
          <p className="mt-0.5 text-[12px] leading-relaxed text-mut">{detail}</p>
        </li>
      ))}
    </ol>
  );
}

/* ---------- the editor ---------- */

type Preview = "file" | "loading" | "run";

export function ProcedureBuilder({
  draft,
  setDraft,
  editing,
  saving,
  saved,
  onSave,
  onDelete,
  onClose,
}: {
  draft: SkillDefinitionInput;
  setDraft: (d: SkillDefinitionInput) => void;
  editing: string | null;
  saving: boolean;
  saved: string;
  onSave: () => void;
  onDelete?: () => void;
  onClose: () => void;
}) {
  const { token } = useAuth();
  const [preview, setPreview] = useState<Preview>("file");
  const [run, setRun] = useState<SkillTestRun | null>(null);
  const [testing, setTesting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState("");

  const set = <K extends keyof SkillDefinitionInput>(
    k: K,
    v: SkillDefinitionInput[K],
  ) => setDraft({ ...draft, [k]: v });

  const lines = bodyLines(draft.instructions);
  const nameIssue = nameProblem(draft.name);
  const orphans = useMemo(
    () => unreferencedResources(draft.instructions, draft.resources),
    [draft.instructions, draft.resources],
  );
  const file = renderSkillMd(draft.name, draft.description, draft.instructions);

  const complete =
    Boolean(draft.name.trim()) &&
    !nameIssue &&
    Boolean(draft.description.trim()) &&
    draft.description.trim().length <= MAX_DESCRIPTION &&
    Boolean(draft.instructions.trim());

  async function openAsAssistant() {
    if (!editing) return;
    setTesting(true);
    setPreview("run");
    try {
      setRun(await api.skillDefs.test(token, editing, {}));
    } catch (e) {
      setRun({
        ok: false,
        query_shown: "",
        data: null,
        error: errorWords((e as ApiError).message),
        row_count: null,
      });
    } finally {
      setTesting(false);
    }
  }

  function download() {
    const url = URL.createObjectURL(
      new Blob([file], { type: "text/markdown" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${draft.name || "skill"}.SKILL.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function adopt() {
    setImportError("");
    try {
      const parsed = await api.skillDefs.parseSkillMd(token, importText);
      setDraft({
        ...draft,
        name: parsed.name,
        description: parsed.description,
        instructions: parsed.instructions,
      });
      setImporting(false);
      setImportText("");
    } catch (e) {
      setImportError(errorWords((e as ApiError).message));
    }
  }

  return (
    <div className="grid items-start gap-5 xl:grid-cols-12">
      {/* ---- the document ---- */}
      <div className="overflow-hidden rounded-2xl border border-line bg-surface [box-shadow:var(--shadow)] xl:col-span-7">
        <header className="flex items-start justify-between gap-3 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <h2 className="font-display truncate text-[16px] font-semibold">
              {editing ? draft.name || "Procedure" : "Write a procedure"}
            </h2>
            <p className="mt-0.5 text-[13px] text-mut">
              Teach it once, in your own words. Everyone gets the same answer
              after that.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => setImporting((v) => !v)}
              title="Paste a SKILL.md you already have"
              className="grid size-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <Upload className="size-4" />
            </button>
            <button
              type="button"
              onClick={download}
              title="Download as SKILL.md"
              className="grid size-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <Download className="size-4" />
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="grid size-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <X className="size-4" />
            </button>
          </div>
        </header>

        <AnimatePresence initial={false}>
          {importing && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.26, ease: EASE }}
              className="overflow-hidden border-b border-line bg-surface-2"
            >
              <div className="p-5">
                <p className="text-[13px] font-semibold">
                  Already have a SKILL.md?
                </p>
                <p className="mt-0.5 text-[12.5px] text-mut">
                  Paste the whole file — front matter and all — and it fills the
                  fields in.
                </p>
                <Textarea
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder={"---\nname: writing-weekly-reports\ndescription: …\n---\n\n# …"}
                  className="mt-3 min-h-32 font-mono text-[12px]"
                />
                {importError && (
                  <div className="mt-2.5">
                    <Notice tone="bad">{importError}</Notice>
                  </div>
                )}
                <div className="mt-3 flex items-center gap-2.5">
                  <Button size="sm" onClick={adopt} disabled={!importText.trim()}>
                    Fill the fields
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setImporting(false);
                      setImportError("");
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <Section
          n={1}
          title="What is this procedure called?"
          hint="A short handle. Nobody reads it out loud — it just has to be unique."
        >
          <Input
            value={draft.name}
            onChange={(e) => set("name", slugify(e.target.value))}
            onBlur={(e) => set("name", slugify(e.target.value))}
            placeholder="writing-weekly-reports"
            aria-label="Skill name"
            className={`font-mono text-[13px] ${nameIssue ? "border-bad" : ""}`}
          />
          <div className="mt-1.5 flex items-start justify-between gap-3">
            <p className={`text-[12px] ${nameIssue ? "text-bad" : "text-faint"}`}>
              {nameIssue ||
                "Lowercase words joined by hyphens. Naming it after the activity — writing-…, handling-… — keeps a library readable."}
            </p>
            <Counter used={draft.name.length} max={MAX_NAME} />
          </div>
        </Section>

        <Section
          n={2}
          title="When should the assistant use it?"
          hint={
            <>
              This one sentence is the whole of what the assistant knows about
              the procedure until it opens it, so it decides whether the skill is
              ever used at all. Say what it does <em>and</em> when.
            </>
          }
          right={
            <Counter used={draft.description.trim().length} max={MAX_DESCRIPTION} />
          }
        >
          <Textarea
            value={draft.description}
            onChange={(e) => set("description", e.target.value)}
            placeholder={EXAMPLE_DESCRIPTION}
            aria-label="Description"
            className="min-h-24 text-[13.5px]"
          />
          {!draft.description.trim() && (
            <button
              type="button"
              onClick={() => set("description", EXAMPLE_DESCRIPTION)}
              className="mt-2 cursor-pointer text-[12px] font-semibold text-accent hover:underline"
            >
              Start from a good example
            </button>
          )}
          <DescriptionCoach text={draft.description} />
        </Section>

        <Section
          n={3}
          title="The instructions"
          hint="What a new colleague would need to be told — the steps, the house rules, anything easy to get wrong. Assume they are already competent."
          right={
            <span
              className={`shrink-0 font-mono text-[11.5px] tabular-nums ${
                lines > ADVISED_MAX_BODY_LINES ? "text-warn" : "text-faint"
              }`}
            >
              {lines} {lines === 1 ? "line" : "lines"}
            </span>
          }
        >
          <Textarea
            value={draft.instructions}
            onChange={(e) => set("instructions", e.target.value)}
            placeholder={PLACEHOLDER_BODY}
            aria-label="Instructions"
            className="min-h-64 font-mono text-[12.5px] leading-relaxed"
          />
          {lines > ADVISED_MAX_BODY_LINES && (
            <div className="mt-3">
              <Notice tone="warn">
                Past about {ADVISED_MAX_BODY_LINES} lines this starts to crowd
                out everything else once it loads. Move the reference material
                into a file below and point at it from here.
              </Notice>
            </div>
          )}
        </Section>

        <Section
          n={4}
          title="Reference files"
          hint="Optional. Long tables, schemas, templates — anything the instructions can point at instead of carrying. They cost nothing until they are actually opened."
        >
          <div className="flex flex-col gap-2">
            {draft.resources.map((r, i) => (
              <ResourceRow
                key={i}
                res={r}
                all={draft.resources}
                cited={draft.instructions.includes(r.path.trim())}
                onChange={(next) => {
                  const list = [...draft.resources];
                  list[i] = next;
                  set("resources", list);
                }}
                onRemove={() =>
                  set(
                    "resources",
                    draft.resources.filter((_, j) => j !== i),
                  )
                }
              />
            ))}
            <button
              type="button"
              onClick={() =>
                set("resources", [...draft.resources, { path: "", content: "" }])
              }
              className="flex cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-dashed border-line-strong py-2.5 text-[12.5px] font-semibold text-mut transition-colors hover:border-accent hover:text-accent"
            >
              <FilePlus2 className="size-3.5" />
              Add a reference file
            </button>
          </div>
          {orphans.length > 0 && (
            <div className="mt-3">
              <Notice tone="warn">
                The instructions never mention {orphans.join(", ")}. A file is
                only ever read because the instructions name it — write the path
                into step 3 where it is needed.
              </Notice>
            </div>
          )}
        </Section>

        <Section
          n={5}
          title="Who can use it?"
          hint="A procedure gives nobody new access to data — but it can still describe how sensitive work is done, so it is held to the same levels as everything else."
        >
          <AudiencePicker
            value={draft.required_data_class}
            onChange={(v) =>
              set("required_data_class", v as SkillDefinitionInput["required_data_class"])
            }
          />
          <label className="mt-4 flex cursor-pointer items-start gap-2.5 rounded-xl border border-line p-3.5">
            <input
              type="checkbox"
              checked={draft.shared}
              onChange={(e) => set("shared", e.target.checked)}
              className="mt-0.5 size-4 accent-[var(--accent)]"
            />
            <span>
              <span className="block text-[13px] font-semibold">
                Let other companies copy it
              </span>
              <span className="mt-0.5 block text-[12px] leading-relaxed text-mut">
                They get the wording only. It reaches none of your data, so
                nothing of yours travels with it.
              </span>
            </span>
          </label>
        </Section>

        <div className="flex flex-wrap items-center gap-3 border-t border-line px-6 py-5">
          <Button variant="cta" onClick={onSave} busy={saving} disabled={!complete}>
            {editing ? "Save changes" : "Publish procedure"}
          </Button>
          {editing && (
            <Button variant="ghost" onClick={openAsAssistant} busy={testing}>
              <Play className="size-4" />
              Open it as the assistant would
            </Button>
          )}
          {onDelete && (
            <ConfirmAction
              question="Take it out of service?"
              confirmLabel="Yes, remove"
              onConfirm={onDelete}
            >
              {(start) => (
                <button
                  onClick={start}
                  className="ml-auto cursor-pointer text-[12.5px] font-semibold text-faint transition-colors hover:text-bad"
                >
                  Remove this procedure
                </button>
              )}
            </ConfirmAction>
          )}
        </div>

        {saved && (
          <div className="px-6 pb-5">
            <Notice tone="good">{saved}</Notice>
          </div>
        )}
      </div>

      {/* ---- what the assistant gets ---- */}
      <aside className="xl:sticky xl:top-24 xl:col-span-5">
        <div className="overflow-hidden rounded-2xl border border-line bg-surface [box-shadow:var(--shadow)]">
          <div className="flex items-center gap-1 border-b border-line p-1.5">
            {(
              [
                ["file", "SKILL.md"],
                ["loading", "What loads, when"],
                ["run", "Try it"],
              ] as [Preview, string][]
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                onClick={() => setPreview(v)}
                className={`relative cursor-pointer rounded-lg px-3 py-1.5 text-[12.5px] font-semibold transition-colors ${
                  preview === v ? "text-accent-strong" : "text-mut hover:text-ink"
                }`}
              >
                {preview === v && (
                  <motion.span
                    layoutId="procedure-preview-pill"
                    transition={{ type: "spring", bounce: 0.15, duration: 0.45 }}
                    className="absolute inset-0 rounded-lg bg-accent-soft"
                  />
                )}
                <span className="relative z-10">{label}</span>
              </button>
            ))}
          </div>

          <div className="p-4">
            {preview === "file" && (
              <>
                <p className="mb-2.5 text-[12px] leading-relaxed text-mut">
                  Exactly what gets stored — and the same bytes Claude Code or
                  claude.ai would read, so this is portable out of KARAG.
                </p>
                <pre className="max-h-[26rem] overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-line bg-bg-deep p-3.5 font-mono text-[11.5px] leading-relaxed text-mut">
                  {file}
                </pre>
              </>
            )}

            {preview === "loading" && (
              <>
                <p className="mb-3 flex items-start gap-1.5 text-[12px] leading-relaxed text-mut">
                  <span>
                    Nothing here is loaded all at once. That is what lets a
                    company keep dozens of procedures without slowing anything
                    down.
                  </span>
                  <Explain term="Progressive disclosure">
                    The assistant holds only each skill&rsquo;s name and
                    description. It reads the instructions when a request matches,
                    and a reference file only when those instructions point at it.
                  </Explain>
                </p>
                <DisclosureMap draft={draft} lines={lines} />
              </>
            )}

            {preview === "run" && (
              <>
                {!editing ? (
                  <p className="py-8 text-center text-[12.5px] text-faint">
                    Publish it first, then you can open it here exactly as the
                    assistant would.
                  </p>
                ) : !run ? (
                  <div className="py-8 text-center">
                    <p className="text-[12.5px] text-faint">
                      Nothing tried yet.
                    </p>
                    <Button
                      size="sm"
                      variant="soft"
                      className="mt-3"
                      onClick={openAsAssistant}
                      busy={testing}
                    >
                      <Play className="size-3.5" /> Open it
                    </Button>
                  </div>
                ) : run.ok ? (
                  <RunResult data={run.data} />
                ) : (
                  <Notice tone="bad">{run.error}</Notice>
                )}
              </>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}

/* What actually came back when the skill was opened — the proof that level 2
   arrived and level 3 did not. */
function RunResult({ data }: { data: unknown }) {
  const d = (data ?? {}) as {
    instructions?: string;
    bundled_files?: string[];
  };
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 rounded-lg bg-good-soft px-3 py-2 text-[12.5px] font-semibold text-good">
        <Check className="size-4 shrink-0" />
        Opened — the assistant now has the instructions.
      </div>
      <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-line bg-bg-deep p-3.5 font-mono text-[11.5px] leading-relaxed text-mut">
        {d.instructions ?? ""}
      </pre>
      <div>
        <p className="text-[12px] font-semibold text-mut">
          Files it was told about — not opened
        </p>
        {d.bundled_files && d.bundled_files.length > 0 ? (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {d.bundled_files.map((f) => (
              <li
                key={f}
                className="rounded-md border border-line bg-surface-2 px-2 py-0.5 font-mono text-[11.5px] text-mut"
              >
                {f}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[12px] text-faint">None bundled.</p>
        )}
      </div>
    </div>
  );
}

/* The button that starts a new procedure, for empty states. */
export function NewProcedureButton({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="cta" onClick={onClick}>
      <Plus className="size-4" /> Write a procedure
    </Button>
  );
}
