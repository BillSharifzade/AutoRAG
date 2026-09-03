"use client";

/* Chat — the primary surface, and now the only thing on it.
 *
 * The history rail moved into the app sidebar, so the conversation sits in the
 * middle of the screen where a conversation belongs. The thread's state lives
 * in the shell's ChatProvider, which means walking to Documents and back leaves
 * you exactly where you were. This page is only the frame.
 *
 * `/?assistant=<id>` opens a fresh conversation with that assistant already
 * chosen — the link the Assistants page hands out. */

import { PanelLeft, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api, type Assistant } from "@/lib/api";
import { useT } from "@/i18n";
import { useAuth } from "@/lib/auth";
import { useChat } from "@/lib/chat-store";
import { Rise } from "@/components/ui";
import { ChatHistory } from "@/components/chat-history";
import { ChatThread } from "@/components/chat-thread";

/* Reads the query string, which Next only allows inside a Suspense boundary
   on a statically rendered page. Applies the assistant once, then clears the
   parameter so a reload does not re-apply it over a conversation. */
function AssistantFromQuery() {
  const params = useSearchParams();
  const router = useRouter();
  const { activeId, newChat, setAssistantId, turns } = useChat();
  const wanted = params.get("assistant");

  useEffect(() => {
    if (!wanted) return;
    if (!activeId && turns.length === 0) {
      setAssistantId(wanted);
    } else {
      newChat();
      setAssistantId(wanted);
    }
    router.replace("/");
    // only when the parameter itself changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted]);

  return null;
}

export default function ChatPage() {
  const t = useT();
  const { token } = useAuth();
  const chat = useChat();
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    api.assistants
      .list(token)
      .then((d) => setAssistants(d.assistants))
      .catch(() => setAssistants([]));
  }, [token]);

  const { activeId, setAssistantId } = chat;
  const changeAssistant = useCallback(
    (id: string) => {
      // switching persona only matters before a chat has any history
      if (!activeId) setAssistantId(id);
    },
    [activeId, setAssistantId],
  );

  return (
    <Rise className="mx-auto h-[calc(100dvh-8.5rem)] w-full max-w-4xl">
      <Suspense fallback={null}>
        <AssistantFromQuery />
      </Suspense>
      <div className="flex h-full flex-col">
        {/* history is in the sidebar on a wide screen; a drawer below that */}
        <button
          onClick={() => setDrawerOpen(true)}
          className="mb-2 flex w-fit items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[12.5px] font-medium text-mut transition-colors hover:text-ink lg:hidden"
        >
          <PanelLeft className="size-3.5" /> {t("chat.drawer")}
        </button>

        <div className="min-h-0 flex-1">
          <ChatThread
            engine={chat}
            assistantId={chat.assistantId || undefined}
            assistants={assistants}
            onAssistantChange={changeAssistant}
          />
        </div>
      </div>

      <AnimatePresence>
        {drawerOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 lg:hidden"
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
                <span className="text-[14px] font-semibold">{t("chat.drawer")}</span>
                <button
                  onClick={() => setDrawerOpen(false)}
                  aria-label={t("common.close")}
                  className="grid size-8 place-items-center rounded-lg text-mut hover:bg-surface-2"
                >
                  <X className="size-4" />
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <ChatHistory
                  sessions={chat.sessions}
                  loading={chat.loadingSessions}
                  activeId={chat.activeId}
                  onNew={() => {
                    chat.newChat();
                    setDrawerOpen(false);
                  }}
                  onOpen={(id) => {
                    void chat.openChat(id);
                    setDrawerOpen(false);
                  }}
                  onRename={(id, title) => void chat.renameChat(id, title)}
                  onDelete={(id) => void chat.deleteChat(id)}
                />
              </div>
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>
    </Rise>
  );
}
