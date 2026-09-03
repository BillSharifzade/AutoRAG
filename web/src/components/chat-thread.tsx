"use client";

/* The conversation surface: centered hero + composer when empty, plain
   markdown answers with a hover action row, user bubbles on the right, an
   auto-growing composer with assistant picker, image/file/voice attachments,
   and full provenance rendering.

   The thread holds no conversation state of its own — it renders a ChatEngine
   and calls back into it. That is what lets the main chat's engine live in the
   app shell and survive navigation, while the assistants page spins up a
   throwaway one for its preview. */

import {
  ArrowUp,
  AudioLines,
  BookOpenText,
  Check,
  Compass,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  Globe,
  Mic,
  Paperclip,
  ShieldAlert,
  Sparkles,
  Square,
  TrendingUp,
  Wrench,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  downloadArtifact,
  toBase64,
  type Answer,
  type Assistant,
  type Citation,
} from "@/lib/api";
import { useLocale, useT, type Locale } from "@/i18n";
import { useAuth } from "@/lib/auth";
import {
  useChatEngine,
  type Att,
  type ChatEngine,
  type Runner,
  type Turn,
  type TurnStatus,
} from "@/lib/chat-store";
import { roleLabel } from "@/lib/words";
import { Notice } from "@/components/pro";
import { BrandLogo, Button, Chip, Picker, TypingDots } from "@/components/ui";

const PLANE_ICON = {
  knowledge: BookOpenText,
  data: Database,
  mixed: Sparkles,
  refusal: ShieldAlert,
  error: ShieldAlert,
  stopped: Square,
} as const;

/* Four openers, one per thing the assistant can actually do — look something
   up in a document, fetch a live figure, build a file, and answer from a
   restricted class. Written as the question a person would say out loud; the
   words live in the dictionary so the opener is in the reader's language. */
const SUGGESTIONS = [
  { icon: BookOpenText, key: "rule" },
  { icon: TrendingUp, key: "number" },
  { icon: FileSpreadsheet, key: "sheet" },
  { icon: Database, key: "figure" },
];

/** Which plural form a count takes: Russian has three, English two. */
function plural(locale: Locale, n: number): "one" | "few" | "many" {
  if (locale === "ru") {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return "one";
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "few";
    return "many";
  }
  return n === 1 ? "one" : "many";
}

/** `store_sales` → "store sales", for a status line a person reads. */
function humanise(name: string): string {
  return name.replace(/[_-]+/g, " ");
}

const ACCEPT =
  "image/png,image/jpeg,image/webp,image/gif,.pdf,.docx,.xlsx,.pptx,.csv,.txt,.md";
const MAX_ATTACHMENT_MB = 20;

function Markdown({ text }: { text: string }) {
  return (
    <div className="prose prose-sm max-w-none text-[15px] leading-[1.75]">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

/* Half-written markdown renders badly for one frame — an unclosed fence turns
   the rest of the answer into a code block that then snaps back. Closing it as
   we go keeps the reveal steady. */
function balanceFences(text: string): string {
  const fences = (text.match(/^```/gm) ?? []).length;
  return fences % 2 === 1 ? `${text}\n\`\`\`` : text;
}

function PlaneBadge({ plane }: { plane: Answer["plane"] }) {
  const t = useT();
  const Icon = PLANE_ICON[plane] ?? PLANE_ICON.knowledge;
  return (
    <Chip tone={plane === "refusal" || plane === "error" ? "bad" : "accent"}>
      <Icon className="size-3" /> {t(`chat.plane.${plane}`)}
    </Chip>
  );
}

function CopyButton({ text }: { text: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  return (
    <button
      title={t("common.copy")}
      onClick={() => {
        void navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="grid size-7 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-ink"
    >
      {copied ? (
        <Check className="size-3.5 text-good" />
      ) : (
        <Copy className="size-3.5" />
      )}
    </button>
  );
}

function AttachmentChips({
  atts,
  onRemove,
}: {
  atts: Att[];
  onRemove?: (id: string) => void;
}) {
  const t = useT();
  if (atts.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {atts.map((a) => (
        <span key={a.id} className="group/att relative">
          {a.kind === "image" && a.preview ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={a.preview}
              alt={a.filename}
              className="h-16 w-16 rounded-xl border border-line object-cover"
            />
          ) : (
            <span className="flex items-center gap-2 rounded-xl border border-line bg-surface-2 px-3 py-2 text-[12.5px] font-medium">
              {a.kind === "audio" ? (
                <AudioLines className="size-4 text-accent" />
              ) : (
                <FileText className="size-4 text-accent" />
              )}
              {a.kind === "audio" ? `${t("chat.voiceNote")}${a.label && a.label !== "voice" ? ` · ${a.label}` : ""}` : a.filename}
            </span>
          )}
          {onRemove && (
            <button
              type="button"
              aria-label={t("chat.removeAttachment", { name: a.filename })}
              onClick={() => onRemove(a.id)}
              className="absolute -right-1.5 -top-1.5 grid size-5 cursor-pointer place-items-center rounded-full bg-ink text-bg opacity-0 transition-opacity group-hover/att:opacity-100"
            >
              <X className="size-3" />
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

/* A source the assistant read on the internet. It is a link on purpose: the
   whole promise of citing the web is that the reader can go and check it, and
   a page can change after it was quoted. The domain is shown because that is
   what tells someone whether to believe it. */
function WebSource({ c }: { c: Citation }) {
  let host = "";
  try {
    host = new URL(c.source_uri ?? "").hostname.replace(/^www\./, "");
  } catch {
    host = "";
  }
  return (
    <a
      href={c.source_uri ?? "#"}
      target="_blank"
      rel="noreferrer noopener"
      title={c.snippet}
      className="inline-flex max-w-[22rem] items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-0.5 text-[11.5px] font-medium text-mut transition-colors hover:border-accent/50 hover:text-accent-strong"
    >
      <Globe className="size-3 shrink-0 text-accent" />
      <span className="truncate">{c.title}</span>
      {host && <span className="shrink-0 text-faint">{host}</span>}
      <ExternalLink className="size-2.5 shrink-0 text-faint" />
    </a>
  );
}

function AnswerExtras({ answer }: { answer: Answer }) {
  const t = useT();
  const { locale } = useLocale();
  const hasMeta =
    answer.citations.length > 0 ||
    answer.skills_used.length > 0 ||
    answer.queries_shown.length > 0 ||
    answer.artifacts.length > 0;
  if (!hasMeta) return null;

  /* Documents and web pages are both sources, but they are not equally
     trustworthy and the screen should not imply they are. */
  const docs = answer.citations.filter((c) => c.document_id !== "web");
  const web = answer.citations.filter((c) => c.document_id === "web");

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mt-3 flex flex-col gap-2.5"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <PlaneBadge plane={answer.plane} />
        {answer.skills_used.map((s) => (
          <Chip key={s} tone="neutral">
            <Wrench className="size-3" /> {s}
          </Chip>
        ))}
        {[...new Map(docs.map((c) => [c.title, c])).values()].map((c) => (
          <span
            key={c.chunk_id}
            title={c.snippet}
            className="inline-flex cursor-help items-center gap-1 rounded-md border border-line bg-surface px-2 py-0.5 text-[11.5px] font-medium text-mut"
          >
            <BookOpenText className="size-3" /> {c.title}
          </span>
        ))}
      </div>

      {web.length > 0 && (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.07em] text-faint">
            <Globe className="size-3" />
            {t("chat.web.title")}
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            {[...new Map(web.map((c) => [c.source_uri, c])).values()].map((c) => (
              <WebSource key={c.chunk_id} c={c} />
            ))}
          </div>
        </div>
      )}

      {answer.queries_shown.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none text-[12px] font-semibold text-mut transition-colors hover:text-accent">
            ▸{" "}
            {t("chat.provenance", {
              n: answer.queries_shown.length,
              noun: t(`chat.query.${plural(locale, answer.queries_shown.length)}`),
            })}
          </summary>
          <div className="mt-1.5 flex flex-col gap-1.5">
            {answer.queries_shown.map((q, i) => (
              <code
                key={i}
                className="block overflow-x-auto rounded-lg border border-line bg-bg-deep p-2.5 font-mono text-[11.5px] leading-relaxed text-mut"
              >
                {q}
              </code>
            ))}
          </div>
        </details>
      )}

      {answer.artifacts.map((a) => {
        const ready = Boolean(a.content_base64);
        return (
          <motion.button
            key={a.filename}
            whileHover={ready ? { y: -1 } : undefined}
            whileTap={ready ? { scale: 0.97 } : undefined}
            onClick={() => ready && downloadArtifact(a)}
            disabled={!ready}
            className={`flex w-fit items-center gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13px] font-semibold transition-colors ${
              ready
                ? "cursor-pointer hover:border-accent hover:text-accent-strong"
                : "cursor-default opacity-70"
            }`}
          >
            <span className="grid size-8 place-items-center rounded-lg bg-accent-soft text-accent">
              {ready ? (
                <Download className="size-4" />
              ) : (
                <FileText className="size-4" />
              )}
            </span>
            <span className="text-left">
              {a.filename}
              <span className="block text-[11px] font-normal text-mut">
                {(a.size_bytes / 1024).toFixed(1)} KB ·{" "}
                {ready ? t("chat.artifact.ready") : t("chat.artifact.regen")}
              </span>
            </span>
          </motion.button>
        );
      })}
    </motion.div>
  );
}

/* ---------- composer ---------- */

function fmtSecs(s: number) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function greetingKey() {
  const h = new Date().getHours();
  if (h < 5) return "chat.greeting.late";
  if (h < 12) return "chat.greeting.morning";
  if (h < 18) return "chat.greeting.afternoon";
  return "chat.greeting.evening";
}

function Composer({
  input,
  setInput,
  onSend,
  onStop,
  busy,
  placeholder,
  picker,
  autoFocus = false,
  atts,
  onAddFiles,
  onRemoveAtt,
  recording,
  recSecs,
  onToggleRec,
  notice,
}: {
  input: string;
  setInput: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  placeholder: string;
  picker?: ReactNode;
  autoFocus?: boolean;
  atts: Att[];
  onAddFiles: (files: FileList | null) => void;
  onRemoveAtt: (id: string) => void;
  recording: boolean;
  recSecs: number;
  onToggleRec: () => void;
  notice: string | null;
}) {
  const t = useT();
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // auto-grow up to a cap, shrink back when cleared
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 192)}px`;
  }, [input]);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!busy) onSend();
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) onStop();
    else onSend();
  }

  const canSend =
    (input.trim().length > 0 || atts.length > 0) && !busy && !recording;

  return (
    <form onSubmit={onSubmit}>
      <div className="rounded-[26px] border border-line bg-surface p-3 transition-[border-color,box-shadow] [box-shadow:var(--shadow)] focus-within:border-line-strong focus-within:[box-shadow:var(--shadow-lg)]">
        {atts.length > 0 && (
          <div className="px-2 pb-2.5 pt-1">
            <AttachmentChips atts={atts} onRemove={onRemoveAtt} />
          </div>
        )}
        <textarea
          ref={ref}
          rows={1}
          autoFocus={autoFocus}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label={t("chat.message")}
          className="max-h-48 w-full resize-none bg-transparent px-2 pt-1 text-[15px] leading-relaxed outline-none placeholder:text-faint"
        />
        <div className="flex items-center justify-between pt-1.5">
          <div className="flex items-center gap-0.5">
            <input
              ref={fileRef}
              type="file"
              hidden
              multiple
              accept={ACCEPT}
              onChange={(e) => {
                onAddFiles(e.target.files);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              title={t("chat.attach")}
              onClick={() => fileRef.current?.click()}
              className="grid size-9 cursor-pointer place-items-center rounded-full text-mut transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <Paperclip className="size-[18px]" />
            </button>
            {recording ? (
              <button
                type="button"
                title={t("chat.recordStop")}
                onClick={onToggleRec}
                className="flex h-9 cursor-pointer items-center gap-2 rounded-full bg-accent-soft px-3 text-[13px] font-semibold text-accent"
              >
                <span className="relative flex size-2.5">
                  <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-60" />
                  <span className="relative inline-flex size-2.5 rounded-full bg-accent" />
                </span>
                {fmtSecs(recSecs)}
                <Square className="size-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                title={t("chat.record")}
                onClick={onToggleRec}
                className="grid size-9 cursor-pointer place-items-center rounded-full text-mut transition-colors hover:bg-surface-2 hover:text-ink"
              >
                <Mic className="size-[18px]" />
              </button>
            )}
            {picker}
          </div>

          {/* One control, two jobs: send, or stop what is already running. */}
          <motion.button
            type="submit"
            whileTap={{ scale: 0.88 }}
            disabled={!busy && !canSend}
            aria-label={busy ? t("chat.stopGenerating") : t("chat.send")}
            title={busy ? t("chat.stop") : t("chat.send")}
            className={`grid size-9 shrink-0 cursor-pointer place-items-center rounded-full transition-[opacity,background] disabled:opacity-35 ${
              busy
                ? "bg-ink text-bg"
                : "red-gradient text-white shadow-[0_2px_12px_-2px_rgb(236_35_54/0.5)]"
            }`}
          >
            <AnimatePresence mode="wait" initial={false}>
              {busy ? (
                <motion.span
                  key="stop"
                  initial={{ scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.6, opacity: 0 }}
                  transition={{ duration: 0.12 }}
                >
                  <Square className="size-3 fill-current" />
                </motion.span>
              ) : (
                <motion.span
                  key="send"
                  initial={{ scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.6, opacity: 0 }}
                  transition={{ duration: 0.12 }}
                >
                  <ArrowUp className="size-4.5" />
                </motion.span>
              )}
            </AnimatePresence>
          </motion.button>
        </div>
      </div>
      {notice && (
        <p className="pt-1.5 text-center text-[12px] text-bad">{notice}</p>
      )}
    </form>
  );
}

/* ---------- first-visit tip ---------- */

/* KARAG knows what it is and what this user's roles allow, so a new user gets
   one offer to be shown around rather than a static tour. Dismissal is
   remembered per user so it appears once, not every time the thread empties. */
function OnboardingTip({ onAsk }: { onAsk: (query: string) => void }) {
  const t = useT();
  const { token, me } = useAuth();
  const [dismissed, setDismissed] = useState(true);
  const [prompt, setPrompt] = useState("");

  const storageKey = me ? `karag_tour_seen:${me.tenant_id}:${me.user_id}` : "";

  useEffect(() => {
    if (!token || !storageKey) return;
    if (localStorage.getItem(storageKey) === "1") return;
    api
      .onboarding(token)
      .then((o) => {
        setPrompt(o.prompt);
        setDismissed(false);
      })
      .catch(() => setDismissed(true));
  }, [token, storageKey]);

  const close = () => {
    setDismissed(true);
    if (storageKey) localStorage.setItem(storageKey, "1");
  };

  if (dismissed || !prompt) return null;

  const roleNames = (me?.roles ?? []).map(roleLabel).join(", ");

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -8, height: 0 }}
        animate={{ opacity: 1, y: 0, height: "auto" }}
        exit={{ opacity: 0, height: 0 }}
        className="mb-5 overflow-hidden"
      >
        <div className="flex items-start gap-3 rounded-2xl border border-accent/25 bg-accent-soft px-4 py-3.5">
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-surface text-accent">
            <Compass className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[13.5px] font-semibold text-accent-strong">
              {t("chat.tip.title")}
            </p>
            <p className="mt-0.5 text-[12.5px] leading-relaxed text-mut">
              {roleNames
                ? t("chat.tip.body", { role: roleNames })
                : t("chat.tip.bodyNoRole")}
            </p>
            <div className="mt-2.5 flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() => {
                  close();
                  onAsk(prompt);
                }}
              >
                {t("chat.tip.go")}
              </Button>
              <Button size="sm" variant="ghost" onClick={close}>
                {t("chat.tip.later")}
              </Button>
            </div>
          </div>
          <button
            onClick={close}
            aria-label={t("chat.tip.dismiss")}
            className="grid size-7 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface hover:text-ink"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

/* ---------- one answer, as it arrives ---------- */

function StatusLine({ status }: { status: TurnStatus }) {
  const t = useT();
  const text = status.tool
    ? t("chat.status.tool", { skill: humanise(status.tool) })
    : status.stage === "retrieving"
      ? t("chat.status.retrieving")
      : t("chat.status.thinking");
  return (
    <motion.div
      key={text}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-3 text-[13px] text-mut"
    >
      <BrandLogo mark className="size-6" />
      <span className="flex items-center gap-2">
        {status.tool ? <Wrench className="size-3.5 text-accent" /> : <TypingDots />}
        {text}
      </span>
    </motion.div>
  );
}

function AssistantTurn({ turn }: { turn: Turn }) {
  const t = useT();
  const streaming = Boolean(turn.streaming);
  // nothing written yet: say what is happening instead of showing dots alone
  if (streaming && !turn.text) {
    return <StatusLine status={turn.status ?? { stage: "thinking" }} />;
  }
  const body = streaming ? balanceFences(turn.text) : turn.text;
  return (
    <div className="group">
      {turn.assistantMissing && (
        <div className="mb-2">
          <Notice tone="warn">{t("chat.assistantMissing")}</Notice>
        </div>
      )}
      {turn.text ? (
        <Markdown text={body} />
      ) : (
        turn.stopped && (
          <p className="text-[13.5px] italic text-faint">{t("chat.stoppedEarly")}</p>
        )
      )}
      {streaming && (
        <span
          aria-hidden
          className="caret -mt-4 ml-0.5 inline-block h-4 w-[2px] translate-y-[3px] rounded-full bg-accent align-middle"
        />
      )}
      {turn.stopped && turn.text && (
        <p className="mt-1 text-[12px] text-faint">{t("chat.stopped")}</p>
      )}
      {/* Citations and downloads land once the words have finished, so the
          answer doesn't jump around while it is being read. */}
      {!streaming && turn.answer && <AnswerExtras answer={turn.answer} />}
      {!streaming && turn.text && (
        <div className="mt-1.5 flex items-center gap-0.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
          <CopyButton text={turn.text} />
        </div>
      )}
    </div>
  );
}

/* ---------- thread ---------- */

export function ChatThread({
  engine,
  assistantId,
  assistants,
  onAssistantChange,
  placeholder,
  compact = false,
}: {
  engine: ChatEngine;
  assistantId?: string;
  /** when provided (with onAssistantChange), an assistant picker is shown */
  assistants?: Assistant[];
  onAssistantChange?: (id: string) => void;
  placeholder?: string;
  compact?: boolean;
}) {
  const t = useT();
  const { turns, busy, send, stop } = engine;
  const [input, setInput] = useState("");
  const [atts, setAtts] = useState<Att[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [recSecs, setRecSecs] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recSecsRef = useRef(0);

  // `turns` changes on every reveal frame, so this keeps the newest line in
  // view as the answer grows rather than only when it finishes.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns, busy]);

  useEffect(
    () => () => {
      if (timerRef.current) clearInterval(timerRef.current);
      recorderRef.current?.stream.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  const flash = useCallback((msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(null), 4000);
  }, []);

  const submit = useCallback(
    (text?: string) => {
      const query = text ?? input;
      if (!query.trim() && atts.length === 0) return;
      send(query, atts);
      setInput("");
      setAtts([]);
    },
    [input, atts, send],
  );

  async function addFiles(files: FileList | null) {
    if (!files) return;
    for (const f of Array.from(files)) {
      if (f.size > MAX_ATTACHMENT_MB * 1024 * 1024) {
        flash(t("chat.tooBig", { name: f.name, mb: MAX_ATTACHMENT_MB }));
        continue;
      }
      const isImage = /^image\/(png|jpeg|webp|gif)$/.test(f.type);
      try {
        const data_b64 = await toBase64(f);
        setAtts((a) => [
          ...a,
          {
            id: crypto.randomUUID(),
            kind: isImage ? "image" : "file",
            filename: f.name,
            media_type: f.type || "application/octet-stream",
            data_b64,
            preview: isImage ? URL.createObjectURL(f) : undefined,
          },
        ]);
      } catch {
        flash(t("chat.cantRead", { name: f.name }));
      }
    }
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : undefined;
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      rec.ondataavailable = (e) => chunksRef.current.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (timerRef.current) clearInterval(timerRef.current);
        setRecording(false);
        const blob = new Blob(chunksRef.current, {
          type: rec.mimeType || "audio/webm",
        });
        const secs = recSecsRef.current;
        setRecSecs(0);
        if (blob.size === 0) return;
        // name the file by its real container — the transcriber infers the
        // codec from the extension (Firefox records ogg, Safari mp4)
        const ext = blob.type.includes("ogg")
          ? "ogg"
          : blob.type.includes("mp4")
            ? "mp4"
            : "webm";
        try {
          const data_b64 = await toBase64(blob);
          setAtts((a) => [
            ...a,
            {
              id: crypto.randomUUID(),
              kind: "audio",
              filename: `voice-note.${ext}`,
              media_type: blob.type,
              data_b64,
              label: fmtSecs(secs),
            },
          ]);
        } catch {
          flash(t("chat.cantReadRecording"));
        }
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
      setRecSecs(0);
      recSecsRef.current = 0;
      timerRef.current = setInterval(() => {
        recSecsRef.current += 1;
        setRecSecs(recSecsRef.current);
      }, 1000);
    } catch {
      flash(t("chat.micDenied"));
    }
  }

  /* The persona is fixed once the conversation has started: the server keeps
     one assistant per chat, so the picker locks after the first message. */
  const locked = turns.length > 0;
  const picker =
    assistants && onAssistantChange ? (
      <span title={locked ? t("chat.assistantLocked") : undefined}>
        <Picker
          compact
          dropUp
          disabled={locked}
          value={assistantId ?? ""}
          onChange={onAssistantChange}
          ariaLabel={t("chat.assistant")}
          options={[
            { value: "", label: t("chat.defaultAssistant") },
            ...assistants.map((a) => ({ value: a.id, label: a.name })),
          ]}
        />
      </span>
    ) : undefined;

  const composerProps = {
    input,
    setInput,
    onSend: () => submit(),
    onStop: stop,
    busy,
    placeholder: placeholder ?? t("chat.placeholder"),
    picker,
    atts,
    onAddFiles: (f: FileList | null) => void addFiles(f),
    onRemoveAtt: (id: string) => setAtts((a) => a.filter((x) => x.id !== id)),
    recording,
    recSecs,
    onToggleRec: () => void toggleRecording(),
    notice,
  };

  const empty = turns.length === 0 && !busy;

  /* -- empty: centered hero with the composer in the middle (Claude-style) -- */
  if (empty && !compact) {
    return (
      <div className="flex h-full min-h-0 flex-col items-center justify-center px-4">
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: [0.2, 0.8, 0.2, 1] }}
          className="w-full max-w-2xl"
        >
          <div className="mb-8 flex flex-col items-center gap-4 text-center">
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
            >
              <BrandLogo mark className="size-14" />
            </motion.div>
            <div>
              <h1 className="font-display text-[32px] font-bold tracking-tight">
                {t(greetingKey())}
              </h1>
              <p className="mt-1.5 text-[15px] text-mut">{t("chat.howHelp")}</p>
            </div>
          </div>

          <OnboardingTip onAsk={(q) => submit(q)} />

          <Composer {...composerProps} autoFocus />

          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            {SUGGESTIONS.map(({ icon: Icon, key }, i) => (
              <motion.button
                key={key}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 + i * 0.06, duration: 0.4 }}
                whileHover={{ y: -1 }}
                whileTap={{ scale: 0.96 }}
                onClick={() => submit(t(`chat.sug.${key}.query`))}
                className="flex cursor-pointer items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-2 text-[13px] font-medium text-mut transition-colors hover:border-accent/50 hover:text-ink"
              >
                <Icon className="size-3.5 text-accent" /> {t(`chat.sug.${key}.label`)}
              </motion.button>
            ))}
          </div>
        </motion.div>
      </div>
    );
  }

  /* -- active conversation: scrolling thread + docked composer -- */
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div
          className={`mx-auto flex w-full flex-col gap-6 px-1 py-4 ${
            compact ? "" : "max-w-3xl"
          }`}
        >
          {compact && turns.length === 0 && (
            <p className="py-6 text-center text-[13px] text-faint">{t("chat.tryAssistant")}</p>
          )}
          <AnimatePresence initial={false}>
            {turns.map((t, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: [0.2, 0.8, 0.2, 1] }}
                className={t.role === "you" ? "flex justify-end" : ""}
              >
                {t.role === "you" ? (
                  <div className="flex max-w-[85%] flex-col items-end gap-2">
                    {t.attachments && <AttachmentChips atts={t.attachments} />}
                    {t.text && (
                      <div className="whitespace-pre-wrap rounded-3xl rounded-br-lg bg-surface-2 px-4.5 py-2.5 text-[15px] leading-relaxed">
                        {t.text}
                      </div>
                    )}
                  </div>
                ) : t.error ? (
                  <div className="rounded-2xl border border-bad/30 bg-bad-soft px-4 py-3 text-[14px] text-bad">
                    {t.text}
                  </div>
                ) : (
                  <AssistantTurn turn={t} />
                )}
              </motion.div>
            ))}
          </AnimatePresence>
          <div ref={bottomRef} />
        </div>
      </div>

      <div className={`mx-auto w-full pt-2 ${compact ? "" : "max-w-3xl"}`}>
        <Composer {...composerProps} />
        {!compact && (
          <p className="pb-1 pt-2 text-center text-[11.5px] text-faint">{t("chat.footer")}</p>
        )}
      </div>
    </div>
  );
}

/* A thread that owns its own short-lived engine — the assistants page's
   preview, which is deliberately not part of anyone's saved history. */
export function PreviewThread({
  assistantId,
  placeholder,
}: {
  assistantId: string;
  placeholder?: string;
}) {
  const { token } = useAuth();
  const run = useCallback<Runner>(
    async (query, attachments, signal) => ({
      answer: await api.ask(token, query, assistantId, attachments, undefined, signal),
    }),
    [token, assistantId],
  );
  const engine = useChatEngine(run);
  return <ChatThread engine={engine} compact placeholder={placeholder} />;
}
