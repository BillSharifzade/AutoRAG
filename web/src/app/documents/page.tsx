"use client";

/* Knowledge — what the assistant has read.
 *
 * Rebuilt for someone who has never heard the words "ingest", "chunk" or
 * "data class". The page answers three questions in order: what does it
 * already know, how do I add to it, and who can see what I add. The signature
 * is the library ribbon in the hero — the collection's own sensitivity mix,
 * drawn from the real documents, doubling as the filter for the list below. */

import {
  BookOpen,
  FileText,
  Search,
  Sparkles,
  Trash2,
  Type,
  UploadCloud,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type DragEvent,
} from "react";
import {
  api,
  type ApiError,
  type Classification,
  type DocumentSummary,
  type IngestResult,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { audience, audiences, errorWords, sizeWords } from "@/lib/words";
import { useLocale, useT, type Locale } from "@/i18n";
import { Button, Input, Textarea } from "@/components/ui";
import {
  ConfirmAction,
  CountUp,
  EASE,
  Empty,
  Notice,
  PageHero,
  Segmented,
  Stagger,
  StaggerItem,
} from "@/components/pro";
import { AudienceBadge, AudiencePicker } from "@/components/audience";
import { SkeletonText } from "@/components/skeleton";

type Mode = "write" | "upload";

/** What happened to a document added in this session — drives its chip. */
type Added = "new" | "replaced";

/** How many documents the library shows before asking to expand. */
const PAGE = 8;

/** Russian counts take three forms, English two. Returns the key suffix. */
function plural(locale: Locale, n: number): "one" | "few" | "many" {
  if (locale !== "ru") return n === 1 ? "one" : "many";
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "one";
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "few";
  return "many";
}

export default function DocumentsPage() {
  const { token, me } = useAuth();
  // Adding and removing needs an ingest role; everyone else reads only. The
  // API refuses either way — this keeps people from filling in a form that
  // can only fail.
  const canIngest = me?.can_ingest ?? false;
  const t = useT();
  const { locale } = useLocale();

  const [mode, setMode] = useState<Mode>("write");
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [justAdded, setJustAdded] = useState<Record<string, Added>>({});

  /* one shared audience choice — the reader picks who can see it once,
     whichever way they're adding it */
  const [who, setWho] = useState("operational");

  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [staged, setStaged] = useState<File | null>(null);
  const [suggestion, setSuggestion] = useState<Classification | null>(null);
  const [reading, setReading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setDocs((await api.documents.list(token)).documents);
    } catch {
      setDocs([]);
    }
  }, [token]);

  useLoad(load);

  /* the collection's sensitivity mix — real counts, not decoration */
  const mix = useMemo(() => {
    const counts = new Map<string, number>();
    for (const d of docs ?? [])
      counts.set(d.data_class, (counts.get(d.data_class) ?? 0) + 1);
    return audiences(locale).map((a) => ({ ...a, count: counts.get(a.value) ?? 0 }));
  }, [docs, locale]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (docs ?? []).filter(
      (d) =>
        (!filter || d.data_class === filter) &&
        (!q || d.title.toLowerCase().includes(q)),
    );
  }, [docs, query, filter]);

  async function stage(file: File) {
    setStaged(file);
    setSuggestion(null);
    setProblem(null);
    setDone(null);
    setReading(true);
    try {
      const c = await api.documents.classify(token, file);
      setSuggestion(c);
      // Pre-select only a guess with evidence behind it. With none, the
      // server's fail-closed "regulated" is not a suggestion — the reader
      // chooses, and the current choice is left alone.
      if (c.confidence > 0) setWho(c.suggested);
    } catch {
      // A failed guess must never block an upload — the choice below is
      // the authority regardless.
      setSuggestion(null);
    } finally {
      setReading(false);
    }
  }

  async function add() {
    setBusy(true);
    setProblem(null);
    setDone(null);
    try {
      let r: IngestResult;
      let name: string;
      if (mode === "write") {
        name = title.trim();
        r = await api.ingestText(token, { title, text, data_class: who });
        setTitle("");
        setText("");
      } else {
        if (!staged) return;
        name = staged.name;
        r = await api.ingestFile(token, staged, who);
        setStaged(null);
        setSuggestion(null);
      }
      /* same title as an existing document → the old copy is gone now */
      const replaced = r.replaced.length > 0;
      setJustAdded((j) => ({ ...j, [r.document_id]: replaced ? "replaced" : "new" }));
      setDone(
        replaced
          ? `${t("documents.done", { name })} ${t("documents.replaced")}`
          : t("documents.done", { name }),
      );
      void load();
    } catch (e) {
      setProblem(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  const canAdd =
    mode === "write" ? Boolean(title.trim() && text.trim()) : Boolean(staged);
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;

  return (
    <Stagger className="flex flex-col gap-6">
      <PageHero
        eyebrow={t("documents.eyebrow")}
        title={t("documents.title")}
        lead={t("documents.lead")}
        art={
          docs && docs.length > 0 ? (
            <LibraryRibbon mix={mix} total={docs.length} onPick={setFilter} active={filter} />
          ) : undefined
        }
      />

      {/* ---------- add ---------- */}
      {canIngest && (
      <StaggerItem>
        <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-6 py-4">
            <div>
              <h2 className="font-display text-[16px] font-semibold">
                {t("documents.add.title")}
              </h2>
              <p className="mt-0.5 text-[13px] text-mut">{t("documents.add.sub")}</p>
            </div>
            <Segmented
              value={mode}
              onChange={(m) => {
                setMode(m);
                setDone(null);
                setProblem(null);
              }}
              ariaLabel={t("documents.add.how")}
              options={[
                { value: "write", label: t("documents.mode.write") },
                { value: "upload", label: t("documents.mode.upload") },
              ]}
            />
          </div>

          <div className="grid gap-7 p-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            {/* left: the content itself */}
            <div>
              <AnimatePresence mode="wait" initial={false}>
                {mode === "write" ? (
                  <motion.div
                    key="write"
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -10 }}
                    transition={{ duration: 0.22, ease: EASE }}
                  >
                    <FieldLabel htmlFor="doc-title">{t("documents.field.title")}</FieldLabel>
                    <Input
                      id="doc-title"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder={t("documents.field.titlePh")}
                    />
                    <p className="mt-1.5 text-[12px] text-faint">
                      {t("documents.field.titleHint")}
                    </p>

                    <FieldLabel htmlFor="doc-text">{t("documents.field.text")}</FieldLabel>
                    <Textarea
                      id="doc-text"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      placeholder={t("documents.field.textPh")}
                      className="min-h-52"
                    />
                    <p className="mt-1.5 text-[12px] text-faint">
                      {words > 0
                        ? t(`documents.words.${plural(locale, words)}`, { n: words })
                        : t("documents.field.textHint")}
                    </p>
                  </motion.div>
                ) : (
                  <motion.div
                    key="upload"
                    initial={{ opacity: 0, x: 10 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 10 }}
                    transition={{ duration: 0.22, ease: EASE }}
                  >
                    <DropZone
                      staged={staged}
                      dragOver={dragOver}
                      onBrowse={() => fileInput.current?.click()}
                      onDragOver={(e: DragEvent) => {
                        e.preventDefault();
                        setDragOver(true);
                      }}
                      onDragLeave={() => setDragOver(false)}
                      onDrop={(e: DragEvent) => {
                        e.preventDefault();
                        setDragOver(false);
                        const f = e.dataTransfer.files[0];
                        if (f) void stage(f);
                      }}
                      onClear={() => {
                        setStaged(null);
                        setSuggestion(null);
                      }}
                    />
                    <input
                      ref={fileInput}
                      type="file"
                      hidden
                      accept=".docx,.xlsx,.pptx,.pdf,.csv,.txt,.md"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void stage(f);
                        e.target.value = "";
                      }}
                    />
                    <AnimatePresence>
                      {(reading || suggestion) && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.25, ease: EASE }}
                          className="overflow-hidden"
                        >
                          <div className="mt-4">
                            {reading ? (
                              <Notice tone="info">{t("documents.reading")}</Notice>
                            ) : suggestion && suggestion.confidence <= 0 ? (
                              <Notice tone="info">{t("documents.guess.none")}</Notice>
                            ) : suggestion ? (
                              <div className="rounded-xl border border-line bg-surface-2 p-3.5">
                                <p className="flex items-center gap-2 text-[13px] font-semibold">
                                  <Sparkles className="size-3.5 text-accent" />
                                  {t("documents.guess.title", {
                                    kind: audience(suggestion.suggested).label,
                                  })}
                                </p>
                                <p className="mt-1.5 text-[12px] leading-relaxed text-mut">
                                  {t("documents.guess.why", {
                                    words: (suggestion.matched[suggestion.suggested] ?? [])
                                      .slice(0, 4)
                                      .map((w) => `«${w}…»`)
                                      .join(", "),
                                  })}{" "}
                                  {t("documents.guess.note")}
                                </p>
                              </div>
                            ) : null}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* right: who can see it */}
            <div className="lg:border-l lg:border-line lg:pl-7">
              <FieldLabel>{t("documents.who.title")}</FieldLabel>
              <p className="mb-3 text-[12.5px] leading-relaxed text-mut">
                {t("documents.who.sub")}
              </p>
              <AudiencePicker
                value={who}
                onChange={setWho}
                suggested={suggestion?.suggested ?? null}
              />

              <div className="mt-7 flex flex-wrap items-center gap-3 border-t border-line pt-5">
                <Button variant="cta" onClick={add} busy={busy} disabled={!canAdd}>
                  {mode === "write"
                    ? t("documents.submit.write")
                    : t("documents.submit.upload")}
                </Button>
                {!canAdd && (
                  <p className="text-[12.5px] text-faint">
                    {mode === "write"
                      ? t("documents.need.write")
                      : t("documents.need.upload")}
                  </p>
                )}
              </div>

              <div className="mt-3 empty:mt-0">
                <AnimatePresence mode="wait">
                  {problem && (
                    <Notice key="bad" tone="bad">
                      {problem}
                    </Notice>
                  )}
                  {done && !problem && (
                    <Notice key="good" tone="good">
                      {done}
                    </Notice>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>
        </section>
      </StaggerItem>
      )}

      {/* ---------- library ---------- */}
      <StaggerItem>
        <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-6 py-4">
            <div>
              <h2 className="font-display text-[16px] font-semibold">
                {t("documents.library.title")}
              </h2>
              <p className="mt-0.5 text-[13px] text-mut">{t("documents.library.sub")}</p>
            </div>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("documents.library.searchPh")}
                aria-label={t("documents.library.search")}
                className="w-56 pl-9"
              />
            </div>
          </div>

          {filter && (
            <div className="flex items-center gap-2 border-b border-line bg-surface-2 px-6 py-2.5">
              <span className="text-[12.5px] text-mut">
                {t("documents.filter.before")}{" "}
                <strong className="font-semibold text-ink">
                  {audience(filter).label}
                </strong>{" "}
                {t("documents.filter.after")}
              </span>
              <button
                onClick={() => setFilter(null)}
                className="inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] font-semibold text-accent transition-colors hover:bg-accent-soft"
              >
                <X className="size-3" />
                {t("documents.filter.clear")}
              </button>
            </div>
          )}

          <div className="p-6 pt-4">
            {docs === null ? (
              <SkeletonText lines={4} />
            ) : visible.length === 0 ? (
              <Empty
                icon={<BookOpen className="size-6" />}
                title={
                  docs.length === 0
                    ? t("documents.empty.title")
                    : t("documents.empty.noMatch")
                }
                hint={
                  docs.length === 0
                    ? t("documents.empty.hint")
                    : t("documents.empty.noMatchHint")
                }
              />
            ) : (
              <ul className="flex flex-col gap-2">
                <AnimatePresence initial={false}>
                  {visible.slice(0, showAll ? undefined : PAGE).map((d) => (
                    <motion.li
                      key={d.document_id}
                      layout
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                      transition={{ duration: 0.24, ease: EASE }}
                      className="group flex items-center gap-3.5 rounded-xl border border-line bg-surface px-4 py-3 transition-colors hover:border-line-strong"
                    >
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                        {d.source_uri ? (
                          <UploadCloud className="size-4" />
                        ) : (
                          <Type className="size-4" />
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-2 truncate text-[14px] font-semibold">
                          {d.title}
                          {justAdded[d.document_id] && (
                            <span className="rounded-md bg-good-soft px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide text-good">
                              {t(`documents.chip.${justAdded[d.document_id]}`)}
                            </span>
                          )}
                        </p>
                        <p className="mt-0.5 truncate text-[12px] text-faint">
                          {d.source_uri
                            ? t("documents.kind.file")
                            : t("documents.kind.text")}
                        </p>
                      </div>
                      <AudienceBadge value={d.data_class} />
                      {canIngest && (
                      <ConfirmAction
                        question={t("documents.remove.q")}
                        onConfirm={async () => {
                          await api.documents
                            .remove(token, d.document_id)
                            .catch(() => {});
                          void load();
                        }}
                      >
                        {(start) => (
                          <button
                            onClick={start}
                            aria-label={t("documents.remove.aria", { name: d.title })}
                            title={t("documents.remove.aria", { name: d.title })}
                            className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        )}
                      </ConfirmAction>
                      )}
                    </motion.li>
                  ))}
                </AnimatePresence>
                {visible.length > PAGE && (
                  <button
                    onClick={() => setShowAll((s) => !s)}
                    className="mt-1 cursor-pointer rounded-xl border border-line py-2.5 text-[13px] font-semibold text-mut transition-colors hover:border-line-strong hover:text-ink"
                  >
                    {showAll
                      ? t("documents.showFewer")
                      : t("documents.showAll", { n: visible.length })}
                  </button>
                )}
              </ul>
            )}
          </div>
        </section>
      </StaggerItem>
    </Stagger>
  );
}

/* ---------- pieces ---------- */

function FieldLabel({
  children,
  htmlFor,
}: {
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="mb-1.5 mt-5 block text-[13px] font-semibold first:mt-0"
    >
      {children}
    </label>
  );
}

/* The hero's signature: the library's own sensitivity mix as a single ribbon.
   Width is share of the collection, so it reads as a fact about the content
   rather than a chart for its own sake — and each band filters the list. */
function LibraryRibbon({
  mix,
  total,
  onPick,
  active,
}: {
  mix: { value: string; label: string; dot: string; count: number }[];
  total: number;
  onPick: (v: string | null) => void;
  active: string | null;
}) {
  const t = useT();
  const { locale } = useLocale();
  const present = mix.filter((m) => m.count > 0);
  return (
    <div className="w-full md:w-72">
      <p className="font-display flex items-baseline gap-1.5 text-[13px] font-semibold text-mut">
        <CountUp value={total} className="text-[26px] font-bold leading-none text-ink" />
        {t(`documents.count.${plural(locale, total)}`)}
      </p>
      <div className="mt-3 flex h-3 w-full gap-1 overflow-hidden rounded-full">
        {present.map((m, i) => (
          <motion.button
            key={m.value}
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ delay: 0.25 + i * 0.07, duration: 0.55, ease: EASE }}
            onClick={() => onPick(active === m.value ? null : m.value)}
            aria-label={t("documents.ribbon.aria", { n: m.count, who: m.label })}
            title={`${m.count} · ${m.label}`}
            style={{
              flexGrow: m.count,
              background: m.dot,
              transformOrigin: "left",
              opacity: active && active !== m.value ? 0.35 : 1,
            }}
            className="h-full cursor-pointer rounded-full transition-opacity"
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-3.5 gap-y-1.5">
        {present.map((m) => (
          <button
            key={m.value}
            onClick={() => onPick(active === m.value ? null : m.value)}
            className={`flex cursor-pointer items-center gap-1.5 text-[11.5px] transition-colors ${
              active === m.value ? "font-semibold text-ink" : "text-mut hover:text-ink"
            }`}
          >
            <span className="size-2 rounded-full" style={{ background: m.dot }} />
            {m.label} {m.count}
          </button>
        ))}
      </div>
    </div>
  );
}

function DropZone({
  staged,
  dragOver,
  onBrowse,
  onDragOver,
  onDragLeave,
  onDrop,
  onClear,
}: {
  staged: File | null;
  dragOver: boolean;
  onBrowse: () => void;
  onDragOver: (e: DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: DragEvent) => void;
  onClear: () => void;
}) {
  const t = useT();
  if (staged) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.25, ease: EASE }}
        className="flex min-h-52 flex-col items-center justify-center gap-3 rounded-2xl border border-line bg-surface-2 p-6 text-center"
      >
        <span className="grid size-14 place-items-center rounded-2xl bg-accent-soft text-accent">
          <FileText className="size-7" />
        </span>
        <span>
          <span className="block text-[14.5px] font-semibold">{staged.name}</span>
          <span className="mt-0.5 block text-[12.5px] text-mut">
            {sizeWords(staged.size)} · {t("documents.drop.ready")}
          </span>
        </span>
        <button
          onClick={onClear}
          className="cursor-pointer text-[12.5px] font-semibold text-accent transition-colors hover:text-accent-hover"
        >
          {t("documents.drop.change")}
        </button>
      </motion.div>
    );
  }
  return (
    <motion.button
      type="button"
      onClick={onBrowse}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      animate={dragOver ? { scale: 1.015 } : { scale: 1 }}
      transition={{ duration: 0.18, ease: EASE }}
      className={`flex min-h-52 w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed p-6 transition-colors ${
        dragOver
          ? "border-accent bg-accent-soft"
          : "border-line-strong hover:border-accent/60 hover:bg-accent-soft/25"
      }`}
    >
      <motion.span
        animate={dragOver ? { y: -5 } : { y: 0 }}
        transition={{ type: "spring", stiffness: 300, damping: 20 }}
        className={`grid size-14 place-items-center rounded-2xl transition-colors ${
          dragOver ? "brand-gradient text-accent-ink" : "bg-accent-soft text-accent"
        }`}
      >
        <UploadCloud className="size-7" />
      </motion.span>
      <span className="text-center">
        <span className="block text-[14.5px] font-semibold">
          {dragOver ? t("documents.drop.release") : t("documents.drop.title")}
        </span>
        <span className="mt-1 block text-[12.5px] text-mut">
          {t("documents.drop.sub")}
        </span>
      </span>
    </motion.button>
  );
}
