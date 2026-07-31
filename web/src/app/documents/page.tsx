"use client";

/* Knowledge-plane ingestion: paste text or upload Office/PDF files.
   Every document carries a data class enforced at retrieval time. A session
   log shows what you've just added, with the class it landed in. */

import {
  CheckCircle2,
  FileText,
  FileUp,
  Layers,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
} from "react";
import {
  api,
  type ApiError,
  type Classification,
  type DocumentSummary,
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
import { SkeletonText } from "@/components/skeleton";

const DATA_CLASSES = [
  { value: "public", hint: "anyone in the tenant", dot: "var(--good)" },
  { value: "operational", hint: "employees and above", dot: "var(--accent-2)" },
  { value: "hr", hint: "HR-cleared roles only", dot: "var(--warn)" },
  { value: "financial", hint: "finance-cleared roles only", dot: "var(--accent)" },
  { value: "regulated", hint: "the most restricted class", dot: "var(--bad)" },
];

function classMeta(v: string) {
  return DATA_CLASSES.find((c) => c.value === v) ?? DATA_CLASSES[1];
}

function DataClassSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const current = classMeta(value);
  return (
    <div>
      <Picker
        value={value}
        onChange={onChange}
        ariaLabel="Data class"
        options={DATA_CLASSES.map((c) => ({
          value: c.value,
          label: c.value,
          hint: `Visible to ${c.hint}`,
        }))}
      />
      <p className="mt-1.5 flex items-center gap-1.5 text-[12px] text-faint">
        <span
          className="size-2 rounded-full"
          style={{ background: current.dot }}
        />
        Visible to {current.hint} — enforced at retrieval time.
      </p>
    </div>
  );
}

interface Ingested {
  id: string;
  docId: string;
  label: string;
  kind: "text" | "file";
  dataClass: string;
  at: number;
}

export default function DocumentsPage() {
  const { token } = useAuth();

  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [textClass, setTextClass] = useState("operational");
  const [textBusy, setTextBusy] = useState(false);
  const [textStatus, setTextStatus] = useState<{
    text: string;
    bad?: boolean;
  } | null>(null);

  const [fileClass, setFileClass] = useState("operational");
  const [fileBusy, setFileBusy] = useState(false);
  const [fileStatus, setFileStatus] = useState<{
    text: string;
    bad?: boolean;
  } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  /* A picked file is *staged*, not ingested: §7 allows auto-classification
     "only as a suggestion", so the uploader confirms the class first. */
  const [staged, setStaged] = useState<File | null>(null);
  const [suggestion, setSuggestion] = useState<Classification | null>(null);
  const [classifying, setClassifying] = useState(false);

  const [log, setLog] = useState<Ingested[]>([]);
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const loadDocs = useCallback(async () => {
    if (!token) return;
    try {
      setDocs((await api.documents.list(token)).documents);
    } catch {
      setDocs([]);
    }
  }, [token]);

  useEffect(() => {
    void loadDocs();
  }, [loadDocs]);

  function logIngest(entry: Omit<Ingested, "id" | "at">) {
    setLog((l) => [
      { ...entry, id: crypto.randomUUID(), at: Date.now() },
      ...l,
    ]);
  }

  /** Stage a file and ask the backend what class it looks like. */
  async function stageFile(file: File) {
    setStaged(file);
    setSuggestion(null);
    setFileStatus(null);
    setClassifying(true);
    try {
      const c = await api.documents.classify(token, file);
      setSuggestion(c);
      setFileClass(c.suggested); // pre-selected, still the uploader's call
    } catch {
      // A classifier failure must never block an upload — the manual
      // selection is the authority anyway.
      setSuggestion(null);
    } finally {
      setClassifying(false);
    }
  }

  async function ingestText() {
    setTextBusy(true);
    setTextStatus(null);
    try {
      const r = await api.ingestText(token, {
        title,
        text,
        data_class: textClass,
      });
      setTextStatus({ text: "Ingested, chunked & embedded" });
      logIngest({
        docId: r.document_id,
        label: title.trim() || "Untitled",
        kind: "text",
        dataClass: r.data_class,
      });
      setTitle("");
      setText("");
      void loadDocs();
    } catch (e) {
      setTextStatus({ text: (e as ApiError).message, bad: true });
    } finally {
      setTextBusy(false);
    }
  }

  async function ingestStaged() {
    if (!staged) return;
    setFileBusy(true);
    setFileStatus(null);
    try {
      const r = await api.ingestFile(token, staged, fileClass);
      setFileStatus({ text: `${staged.name} ingested` });
      logIngest({
        docId: r.document_id,
        label: staged.name,
        kind: "file",
        dataClass: r.data_class,
      });
      setStaged(null);
      setSuggestion(null);
      void loadDocs();
    } catch (e) {
      setFileStatus({ text: (e as ApiError).message, bad: true });
    } finally {
      setFileBusy(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) void stageFile(file);
  }

  const cards = [
    // Add text
    <Card key="text">
      <CardHeader
        icon={<FileText className="size-4" />}
        title="Add text"
        sub="Paste a policy, SOP, or any knowledge into the platform."
      />
      <div className="p-6">
        <Label>Title</Label>
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Returns Policy"
        />
        <Label>Text</Label>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Customers may return unopened goods within 14 days…"
          className="min-h-44"
        />
        <Label>Data class</Label>
        <DataClassSelect value={textClass} onChange={setTextClass} />
        <div className="mt-5 flex min-h-9 items-center gap-3">
          <Button
            onClick={ingestText}
            busy={textBusy}
            disabled={!title.trim() || !text.trim()}
          >
            Ingest text
          </Button>
          <AnimatePresence mode="wait">
            {textStatus && (
              <motion.div
                key={textStatus.text}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
              >
                <Chip tone={textStatus.bad ? "bad" : "good"}>
                  {!textStatus.bad && <CheckCircle2 className="size-3" />}
                  {textStatus.text}
                </Chip>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </Card>,

    // Upload a file
    <Card key="file">
      <CardHeader
        icon={<FileUp className="size-4" />}
        title="Upload a file"
        sub=".docx · .xlsx · .pptx · .pdf · .csv · .txt · .md"
      />
      <div className="p-6">
        <motion.button
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          animate={dragOver ? { scale: 1.015 } : { scale: 1 }}
          className={`flex min-h-44 w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed transition-colors ${
            dragOver
              ? "border-accent bg-accent-soft"
              : "border-line-strong hover:border-accent/60 hover:bg-accent-soft/30"
          }`}
        >
          <motion.span
            animate={dragOver ? { y: -4 } : { y: 0 }}
            className={`grid size-12 place-items-center rounded-2xl transition-colors ${
              dragOver
                ? "brand-gradient text-accent-ink"
                : "bg-accent-soft text-accent"
            }`}
          >
            <UploadCloud className="size-6" />
          </motion.span>
          <span className="text-center">
            <span className="block text-[14px] font-semibold">
              {staged ? staged.name : "Drop a file here or click to browse"}
            </span>
            <span className="mt-0.5 block text-[12.5px] text-mut">
              {staged
                ? "Confirm the data class below, then ingest."
                : "Text is extracted, chunked and embedded — you set the class."}
            </span>
          </span>
        </motion.button>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept=".docx,.xlsx,.pptx,.pdf,.csv,.txt,.md"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void stageFile(f);
            e.target.value = "";
          }}
        />

        <AnimatePresence>
          {(classifying || suggestion) && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mt-4 rounded-xl border border-line bg-surface-2 p-3.5">
                {classifying ? (
                  <p className="text-[12.5px] text-mut">Reading the document…</p>
                ) : suggestion ? (
                  <>
                    <p className="flex items-center gap-2 text-[12.5px] font-semibold">
                      <Sparkles className="size-3.5 text-accent" />
                      Suggested: <span className="capitalize">{suggestion.suggested}</span>
                      <Chip tone="neutral">
                        {Math.round(suggestion.confidence * 100)}% confidence
                      </Chip>
                    </p>
                    <p className="mt-1.5 text-[11.5px] leading-relaxed text-mut">
                      {suggestion.rationale}
                    </p>
                  </>
                ) : null}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <Label>Data class</Label>
        <DataClassSelect value={fileClass} onChange={setFileClass} />
        <div className="mt-5 flex min-h-9 flex-wrap items-center gap-3">
          <Button onClick={ingestStaged} busy={fileBusy} disabled={!staged}>
            Ingest file
          </Button>
          {staged && !fileBusy && (
            <Button
              variant="ghost"
              onClick={() => {
                setStaged(null);
                setSuggestion(null);
              }}
            >
              Clear
            </Button>
          )}
          <AnimatePresence mode="wait">
            {fileStatus && (
              <motion.div
                key={fileStatus.text}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
              >
                <Chip tone={fileStatus.bad ? "bad" : "good"}>
                  {!fileStatus.bad && <CheckCircle2 className="size-3" />}
                  {fileStatus.text}
                </Chip>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </Card>,
  ];

  return (
    <Rise className="flex flex-col gap-6">
      <div className="grid items-start gap-6 lg:grid-cols-2">
        {cards.map((c, i) => (
          <motion.div
            key={c.key}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
          >
            {c}
          </motion.div>
        ))}
      </div>

      {/* Session ingest log */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.16, duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
      >
        <Card>
          <CardHeader
            icon={<Layers className="size-4" />}
            title="Knowledge base"
            sub="Everything you're cleared to see — the list obeys the same filter as retrieval."
            right={
              docs && docs.length > 0 ? (
                <Chip tone="neutral">
                  {docs.length} {docs.length === 1 ? "document" : "documents"}
                </Chip>
              ) : undefined
            }
          />
          <div className="p-6 pt-4">
            {docs === null ? (
              <SkeletonText lines={4} />
            ) : docs.length === 0 ? (
              <EmptyState
                icon={<Layers className="size-6" />}
                title="Nothing here yet"
                hint="Paste text or drop a file above. Documents in classes you aren't cleared for never appear — not even their titles."
              />
            ) : (
              <div className="flex flex-col gap-2">
                <AnimatePresence initial={false}>
                  {docs.map((d) => {
                    const meta = classMeta(d.data_class);
                    const justAdded = log.some((l) => l.docId === d.document_id);
                    return (
                      <motion.div
                        key={d.document_id}
                        layout
                        initial={{ opacity: 0, y: -8, height: 0 }}
                        animate={{ opacity: 1, y: 0, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3"
                      >
                        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                          {d.source_uri ? (
                            <FileUp className="size-4" />
                          ) : (
                            <FileText className="size-4" />
                          )}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="flex items-center gap-2 truncate text-[13.5px] font-semibold">
                            {d.title}
                            {justAdded && <Chip tone="good">new</Chip>}
                          </p>
                          <p className="truncate font-mono text-[11px] text-faint">
                            {d.document_id} · {d.chunks}{" "}
                            {d.chunks === 1 ? "chunk" : "chunks"}
                          </p>
                        </div>
                        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-1 text-[11.5px] font-medium capitalize">
                          <span
                            className="size-2 rounded-full"
                            style={{ background: meta.dot }}
                          />
                          {d.data_class}
                        </span>
                        {pendingDelete === d.document_id ? (
                          <span className="flex shrink-0 items-center gap-1.5">
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={async () => {
                                await api.documents
                                  .remove(token, d.document_id)
                                  .catch(() => {});
                                setPendingDelete(null);
                                void loadDocs();
                              }}
                            >
                              Confirm
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setPendingDelete(null)}
                            >
                              Cancel
                            </Button>
                          </span>
                        ) : (
                          <button
                            title="Remove from the knowledge base"
                            onClick={() => setPendingDelete(d.document_id)}
                            className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        )}
                      </motion.div>
                    );
                  })}
                </AnimatePresence>
              </div>
            )}
          </div>
        </Card>
      </motion.div>

      <p className="flex items-center justify-center gap-1.5 text-center text-[12px] text-faint">
        <ShieldCheck className="size-3.5 text-good" />
        Data class is bound at ingest time and enforced on every retrieval —
        forbidden classes never reach the model.
      </p>
    </Rise>
  );
}
