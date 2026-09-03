"use client";

/* Saved conversations, grouped by date, with rename and delete.
 *
 * This used to be a rail beside the thread, which pushed the conversation
 * off-centre and vanished the moment you left the page. It now hangs under
 * Chat in the app sidebar — the same place every other destination lives — so
 * the thread itself gets the middle of the screen. */

import { Bot, Check, MessageSquarePlus, MessageSquareText, Pencil, Trash2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { ChatSummary } from "@/lib/api";
import { useT } from "@/i18n";
import { ChatListSkeleton } from "@/components/skeleton";

const GROUP_ORDER = ["today", "yesterday", "week", "older"] as const;
type GroupName = (typeof GROUP_ORDER)[number];

function groupSessions(sessions: ChatSummary[]): Record<GroupName, ChatSummary[]> {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const t0 = start.getTime();
  const day = 86400000;
  const out: Record<GroupName, ChatSummary[]> = {
    today: [],
    yesterday: [],
    week: [],
    older: [],
  };
  for (const s of sessions) {
    const d = s.updated_at * 1000;
    if (d >= t0) out.today.push(s);
    else if (d >= t0 - day) out.yesterday.push(s);
    else if (d >= t0 - 7 * day) out.week.push(s);
    else out.older.push(s);
  }
  return out;
}

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
  const t = useT();
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
          className="w-full rounded-lg border border-accent bg-surface px-2.5 py-1.5 text-[12.5px] outline-none"
        />
      ) : (
        <button
          onClick={onOpen}
          className="min-w-0 flex-1 cursor-pointer px-2.5 py-1.5 text-left"
          title={s.title}
        >
          <span
            className={`flex items-center gap-1.5 text-[12.5px] ${
              active ? "font-semibold text-accent-strong" : "text-mut"
            }`}
          >
            {s.assistant_id && (
              <Bot className="size-3 shrink-0 text-faint" aria-label={t("chat.usesAssistant")} />
            )}
            <span className="truncate">{s.title}</span>
          </span>
        </button>
      )}

      {!editing && (
        <div className="absolute right-0.5 flex items-center">
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
                  title={t("chat.confirmDelete")}
                  onClick={onDelete}
                  className="grid size-6 cursor-pointer place-items-center rounded text-bad hover:bg-bad-soft"
                >
                  <Check className="size-3" />
                </button>
                <button
                  title={t("common.cancel")}
                  onClick={() => setConfirming(false)}
                  className="grid size-6 cursor-pointer place-items-center rounded text-mut hover:bg-surface-2"
                >
                  <X className="size-3" />
                </button>
              </motion.div>
            ) : (
              <div className="hidden items-center gap-0.5 pr-0.5 group-hover:flex">
                <button
                  title={t("chat.rename")}
                  onClick={() => {
                    setDraft(s.title);
                    setEditing(true);
                  }}
                  className="grid size-6 cursor-pointer place-items-center rounded text-faint hover:bg-surface hover:text-ink"
                >
                  <Pencil className="size-3" />
                </button>
                <button
                  title={t("common.delete")}
                  onClick={() => setConfirming(true)}
                  className="grid size-6 cursor-pointer place-items-center rounded text-faint hover:bg-surface hover:text-bad"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

export function ChatHistory({
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
  const t = useT();
  const groups = groupSessions(sessions);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <button
        onClick={onNew}
        className="mb-2 flex items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] font-semibold transition-colors hover:border-accent/50 hover:text-accent-strong"
      >
        <MessageSquarePlus className="size-3.5 text-accent" /> {t("chat.new")}
      </button>

      {/* The list scrolls inside its own box — the New button above stays put
          and the rest of the sidebar never moves, however long the history. */}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-0.5">
        {loading ? (
          <ChatListSkeleton rows={4} />
        ) : sessions.length === 0 ? (
          <p className="px-2.5 py-3 text-[11.5px] leading-relaxed text-faint">
            <MessageSquareText className="mb-1 size-3.5" />
            {t("chat.empty")}
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            {GROUP_ORDER.filter((g) => groups[g].length > 0).map((g) => (
              <div key={g}>
                <p className="px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
                  {t(`chat.group.${g}`)}
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
