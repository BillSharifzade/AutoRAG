"use client";

/* Chat — the primary surface. A saved-history rail (grouped by date, rename &
   delete) sits beside the thread; conversations persist and carry multi-turn
   memory. New chats are created lazily on the first message. */

import {
  Check,
  MessageSquarePlus,
  MessageSquareText,
  PanelLeft,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type Answer,
  type Assistant,
  type ChatAttachment,
  type ChatSummary,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Rise } from "@/components/ui";
import { ChatListSkeleton } from "@/components/skeleton";
import { ChatThread, historyToTurns, type Turn } from "@/components/chat-thread";

/* ---------- date grouping ---------- */

const GROUP_ORDER = ["Today", "Yesterday", "Previous 7 days", "Older"] as const;
type GroupName = (typeof GROUP_ORDER)[number];

function groupSessions(sessions: ChatSummary[]): Record<GroupName, ChatSummary[]> {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const t0 = start.getTime();
  const day = 86400000;
  const out: Record<GroupName, ChatSummary[]> = {
    Today: [],
    Yesterday: [],
    "Previous 7 days": [],
    Older: [],
  };
  for (const s of sessions) {
    const d = s.updated_at * 1000;
    if (d >= t0) out.Today.push(s);
    else if (d >= t0 - day) out.Yesterday.push(s);
    else if (d >= t0 - 7 * day) out["Previous 7 days"].push(s);
    else out.Older.push(s);
  }
  return out;
}

/* ---------- rail item ---------- */

function RailItem({
  s,
  active,
  onOpen,
  onRename,
  onDelete,
}: {
  s: ChatSummary;
  active: boolean;
  onOpen: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [draft, setDraft] = useState(s.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  function commit() {
    const t = draft.trim();
    if (t && t !== s.title) onRename(t);
    setEditing(false);
  }

  return (
    <div
      className={`group relative flex items-center rounded-lg transition-colors ${
        active ? "bg-accent-soft" : "hover:bg-surface-2"
      }`}
    >
      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              setDraft(s.title);
              setEditing(false);
            }
          }}
          className="w-full rounded-lg border border-accent bg-surface px-3 py-2 text-[13px] outline-none"
        />
      ) : (
        <button
          onClick={onOpen}
          className="min-w-0 flex-1 cursor-pointer px-3 py-2 text-left"
          title={s.title}
        >
          <span
            className={`block truncate text-[13px] ${
              active ? "font-semibold text-accent-strong" : "text-ink"
            }`}
          >
            {s.title}
          </span>
        </button>
      )}

      {!editing && (
        <div className="absolute right-1 flex items-center">
          <AnimatePresence mode="wait" initial={false}>
            {confirming ? (
              <motion.div
                key="confirm"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-0.5 rounded-md bg-surface px-0.5 shadow-[var(--shadow-sm)]"
              >
                <button
                  title="Confirm delete"
                  onClick={onDelete}
                  className="grid size-6 cursor-pointer place-items-center rounded text-bad hover:bg-bad-soft"
                >
                  <Check className="size-3.5" />
                </button>
                <button
                  title="Cancel"
                  onClick={() => setConfirming(false)}
                  className="grid size-6 cursor-pointer place-items-center rounded text-mut hover:bg-surface-2"
                >
                  <X className="size-3.5" />
                </button>
              </motion.div>
            ) : (
              <div className="hidden items-center gap-0.5 pr-1 group-hover:flex">
                <button
                  title="Rename"
                  onClick={() => {
                    setDraft(s.title);
                    setEditing(true);
                  }}
                  className="grid size-6 cursor-pointer place-items-center rounded text-faint hover:bg-surface hover:text-ink"
                >
                  <Pencil className="size-3.5" />
                </button>
                <button
                  title="Delete"
                  onClick={() => setConfirming(true)}
                  className="grid size-6 cursor-pointer place-items-center rounded text-faint hover:bg-surface hover:text-bad"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

/* ---------- rail ---------- */

function HistoryRail({
  sessions,
  loading,
  activeId,
  onNew,
  onOpen,
  onRename,
  onDelete,
}: {
  sessions: ChatSummary[];
  loading: boolean;
  activeId: string | null;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}) {
  const groups = groupSessions(sessions);
  return (
    <div className="flex h-full flex-col">
      <button
        onClick={onNew}
        className="mb-3 flex items-center gap-2 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px] font-semibold transition-colors hover:border-accent/50 hover:text-accent-strong"
      >
        <MessageSquarePlus className="size-4 text-accent" /> New chat
      </button>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {loading ? (
          <ChatListSkeleton />
        ) : sessions.length === 0 ? (
          <p className="px-3 py-6 text-center text-[12.5px] text-faint">
            No saved chats yet. Your conversations will appear here.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {GROUP_ORDER.filter((g) => groups[g].length > 0).map((g) => (
              <div key={g}>
                <p className="px-3 pb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-faint">
                  {g}
                </p>
                <div className="flex flex-col gap-0.5">
                  <AnimatePresence initial={false}>
                    {groups[g].map((s) => (
                      <motion.div
                        key={s.id}
                        layout
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, height: 0 }}
                      >
                        <RailItem
                          s={s}
                          active={s.id === activeId}
                          onOpen={() => onOpen(s.id)}
                          onRename={(t) => onRename(s.id, t)}
                          onDelete={() => onDelete(s.id)}
                        />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- page ---------- */

export default function ChatPage() {
  const { token, language } = useAuth();
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [assistantId, setAssistantId] = useState("");

  const [sessions, setSessions] = useState<ChatSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);

  // stable thread identity — only changes when the user opens/creates a chat,
  // NOT when a lazy id is assigned mid-conversation (so the thread never remounts)
  const [threadKey, setThreadKey] = useState(() => crypto.randomUUID());
  const [initialTurns, setInitialTurns] = useState<Turn[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const setActive = (id: string | null) => {
    activeIdRef.current = id;
    setActiveId(id);
  };

  const refreshSessions = useCallback(async () => {
    try {
      const d = await api.chats.list(token);
      setSessions(d.chats);
    } catch {
      setSessions([]);
    } finally {
      setLoadingSessions(false);
    }
  }, [token]);

  useEffect(() => {
    api.assistants
      .list(token)
      .then((d) => setAssistants(d.assistants))
      .catch(() => setAssistants([]));
    void refreshSessions();
  }, [token, refreshSessions]);

  function newChat() {
    setActive(null);
    setInitialTurns([]);
    setAssistantId("");
    setThreadKey(crypto.randomUUID());
    setDrawerOpen(false);
  }

  async function openChat(id: string) {
    setDrawerOpen(false);
    try {
      const detail = await api.chats.get(token, id);
      setInitialTurns(historyToTurns(detail.messages));
      setAssistantId(detail.assistant_id ?? "");
      setActive(id);
      setThreadKey(id);
    } catch {
      /* deleted elsewhere — ignore */
    }
  }

  async function renameChat(id: string, title: string) {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title } : s)),
    );
    try {
      await api.chats.rename(token, id, title);
    } catch {
      void refreshSessions();
    }
  }

  async function deleteChat(id: string) {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeIdRef.current === id) newChat();
    try {
      await api.chats.remove(token, id);
    } catch {
      void refreshSessions();
    }
  }

  // parent-owned send: lazily create the session, persist, keep the rail fresh
  const sendMessage = useCallback(
    async (query: string, attachments: ChatAttachment[]): Promise<Answer> => {
      let id = activeIdRef.current;
      if (!id) {
        const created = await api.chats.create(token, {
          assistant_id: assistantId || null,
        });
        id = created.id;
        setActive(id);
        setThreadKey((k) => k); // keep identity — no remount
      }
      const res = await api.chats.ask(token, id, query, attachments, language);
      setSessions((prev) => {
        const rest = prev.filter((s) => s.id !== id);
        const existing = prev.find((s) => s.id === id);
        const updated: ChatSummary = {
          id: id!,
          title: res.title,
          assistant_id: assistantId || null,
          created_at: existing?.created_at ?? Date.now() / 1000,
          updated_at: res.updated_at ?? Date.now() / 1000,
          message_count: (existing?.message_count ?? 0) + 2,
          preview: res.title,
        };
        return [updated, ...rest];
      });
      return res.answer;
    },
    [token, assistantId, language],
  );

  return (
    <Rise className="h-[calc(100dvh-8.5rem)]">
      <div className="flex h-full gap-6">
        {/* Rail — desktop */}
        <aside className="hidden w-64 shrink-0 md:block">
          <HistoryRail
            sessions={sessions}
            loading={loadingSessions}
            activeId={activeId}
            onNew={newChat}
            onOpen={openChat}
            onRename={renameChat}
            onDelete={deleteChat}
          />
        </aside>

        {/* Thread */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* mobile history toggle */}
          <button
            onClick={() => setDrawerOpen(true)}
            className="mb-2 flex w-fit items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[12.5px] font-medium text-mut transition-colors hover:text-ink md:hidden"
          >
            <PanelLeft className="size-3.5" /> History
          </button>
          <div className="min-h-0 flex-1">
            <ChatThread
              key={threadKey}
              initialTurns={initialTurns}
              onSendMessage={sendMessage}
              assistantId={assistantId || undefined}
              assistants={assistants}
              onAssistantChange={(id) => {
                // switching persona only matters for a fresh chat
                if (!activeIdRef.current) setAssistantId(id);
              }}
            />
          </div>
        </div>
      </div>

      {/* Rail — mobile drawer */}
      <AnimatePresence>
        {drawerOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 md:hidden"
          >
            <div
              className="absolute inset-0 bg-ink/40 backdrop-blur-sm"
              onClick={() => setDrawerOpen(false)}
            />
            <motion.aside
              initial={{ x: -320 }}
              animate={{ x: 0 }}
              exit={{ x: -320 }}
              transition={{ type: "spring", stiffness: 380, damping: 38 }}
              className="absolute inset-y-0 left-0 flex w-80 max-w-[85vw] flex-col border-r border-line bg-surface p-4"
            >
              <div className="mb-3 flex items-center justify-between">
                <span className="flex items-center gap-2 text-[14px] font-semibold">
                  <MessageSquareText className="size-4 text-accent" /> Chats
                </span>
                <button
                  onClick={() => setDrawerOpen(false)}
                  className="grid size-8 place-items-center rounded-lg text-mut hover:bg-surface-2"
                >
                  <X className="size-4" />
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <HistoryRail
                  sessions={sessions}
                  loading={loadingSessions}
                  activeId={activeId}
                  onNew={newChat}
                  onOpen={openChat}
                  onRename={renameChat}
                  onDelete={deleteChat}
                />
              </div>
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>
    </Rise>
  );
}
