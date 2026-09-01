"use client";

/* The conversation, held above the router.
 *
 * The chat used to live inside the chat page, so walking over to Documents and
 * back threw the thread away and you had to find your conversation again. This
 * provider is mounted in the app shell, which Next keeps alive across route
 * changes, so the open conversation and everything in it simply survives.
 *
 * It also owns the two things the composer needs and a plain fetch cannot give
 * it: an abort handle, so *stop* really stops, and a reveal cursor, so an answer
 * arrives as writing rather than as a wall of text.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  type Answer,
  type ApiError,
  type ChatAttachment,
  type ChatSummary,
  type StoredChatMessage,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { errorWords } from "@/lib/words";
import { useCalm } from "@/components/pro";

/* ---------- turns ---------- */

export interface Att extends ChatAttachment {
  id: string;
  /** object URL for an image thumbnail */
  preview?: string;
  /** pretty label, e.g. a voice note's length */
  label?: string;
}

export interface Turn {
  role: "you" | "karag";
  text: string;
  answer?: Answer;
  error?: boolean;
  attachments?: Att[];
  /** how much of `text` has been revealed; undefined means all of it */
  shown?: number;
}

/** Map persisted chat messages back into renderable turns. */
export function historyToTurns(messages: StoredChatMessage[]): Turn[] {
  return messages.map((m) =>
    m.role === "user"
      ? {
          role: "you" as const,
          text: m.text,
          attachments: (m.attachments ?? []).map((a, i) => ({
            id: `${i}`,
            kind: a.kind,
            filename: a.filename,
            media_type: "",
            data_b64: "",
            label: a.kind === "audio" ? "Voice note" : undefined,
          })),
        }
      : {
          role: "karag" as const,
          text: m.text || "(no answer)",
          answer: m.answer ?? undefined,
        },
  );
}

/* ---------- how fast an answer writes itself ---------- */

/* A fixed characters-per-second rate would make a one-line answer feel snappy
   and a long one feel broken. Instead the whole reveal is budgeted: short
   answers take about half a second, the longest about three, and everything in
   between scales. It reads as typing without ever making anyone wait. */
const MIN_REVEAL_MS = 450;
const MAX_REVEAL_MS = 3000;
const CHARS_PER_MS = 0.22;

function revealDuration(length: number): number {
  return Math.min(MAX_REVEAL_MS, Math.max(MIN_REVEAL_MS, length / CHARS_PER_MS));
}

/* ---------- the engine one thread runs on ---------- */

export interface ChatEngine {
  turns: Turn[];
  /** waiting on the model, or still writing the answer out */
  busy: boolean;
  /** true only while the answer is being written out */
  writing: boolean;
  send: (text: string, attachments: Att[]) => void;
  /** abandon an answer that hasn't arrived, or finish one that is writing */
  stop: () => void;
  reset: (turns?: Turn[]) => void;
}

/** A thread that sends through `ask` and keeps its state locally. */
export function useChatEngine(
  send: (
    query: string,
    attachments: ChatAttachment[],
    signal: AbortSignal,
  ) => Promise<Answer>,
  initial: Turn[] = [],
): ChatEngine {
  const [turns, setTurns] = useState<Turn[]>(initial);
  const [pending, setPending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const revealRef = useRef<number | null>(null);
  const calm = useCalm();

  const cancelReveal = useCallback(() => {
    if (revealRef.current !== null) {
      cancelAnimationFrame(revealRef.current);
      revealRef.current = null;
    }
  }, []);

  // Nothing may keep animating or fetching once the thread is gone.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (revealRef.current !== null) cancelAnimationFrame(revealRef.current);
    },
    [],
  );

  /** Walk the reveal cursor of the final turn up to the full length. */
  const startReveal = useCallback(
    (length: number) => {
      if (calm || length === 0) {
        setTurns((t) => withShown(t, undefined));
        return;
      }
      const started = performance.now();
      const duration = revealDuration(length);
      const step = (now: number) => {
        const progress = Math.min(1, (now - started) / duration);
        // ease-out: fast at the start, settling at the end, like a person
        // typing a sentence they already know
        const eased = 1 - (1 - progress) ** 2;
        const shown = Math.ceil(eased * length);
        setTurns((t) => withShown(t, progress >= 1 ? undefined : shown));
        if (progress < 1) {
          revealRef.current = requestAnimationFrame(step);
        } else {
          revealRef.current = null;
        }
      };
      revealRef.current = requestAnimationFrame(step);
    },
    [calm],
  );

  const doSend = useCallback(
    (text: string, attachments: Att[]) => {
      const query = text.trim();
      if ((!query && attachments.length === 0) || pending) return;

      setTurns((t) => [
        ...t,
        {
          role: "you",
          text: query,
          attachments: attachments.length ? attachments : undefined,
        },
      ]);
      setPending(true);

      const controller = new AbortController();
      abortRef.current = controller;
      const payload: ChatAttachment[] = attachments.map(
        ({ kind, filename, media_type, data_b64 }) => ({
          kind,
          filename,
          media_type,
          data_b64,
        }),
      );

      void (async () => {
        try {
          const answer = await send(query, payload, controller.signal);
          if (controller.signal.aborted) return;
          const body = answer.text || "(no answer)";
          setTurns((t) => [
            ...t,
            { role: "karag", text: body, answer, shown: 0 },
          ]);
          startReveal(body.length);
        } catch (e) {
          if (controller.signal.aborted) return;
          setTurns((t) => [
            ...t,
            {
              role: "karag",
              text: errorWords((e as ApiError).message),
              error: true,
            },
          ]);
        } finally {
          if (abortRef.current === controller) abortRef.current = null;
          setPending(false);
        }
      })();
    },
    [pending, send, startReveal],
  );

  const stop = useCallback(() => {
    // Mid-write, the words are already here — show them all rather than
    // throwing away an answer that has been paid for.
    if (revealRef.current !== null) {
      cancelReveal();
      setTurns((t) => withShown(t, undefined));
      return;
    }
    abortRef.current?.abort();
    abortRef.current = null;
    setPending(false);
  }, [cancelReveal]);

  const reset = useCallback(
    (next: Turn[] = []) => {
      abortRef.current?.abort();
      abortRef.current = null;
      cancelReveal();
      setPending(false);
      setTurns(next);
    },
    [cancelReveal],
  );

  const writing = turns.at(-1)?.shown !== undefined;

  return {
    turns,
    busy: pending || writing,
    writing,
    send: doSend,
    stop,
    reset,
  };
}

function withShown(turns: Turn[], shown: number | undefined): Turn[] {
  if (turns.length === 0) return turns;
  const last = turns[turns.length - 1];
  if (last.role !== "karag" || last.shown === shown) return turns;
  return [...turns.slice(0, -1), { ...last, shown }];
}

/* ---------- the shared, navigation-surviving conversation ---------- */

interface ChatStore extends ChatEngine {
  sessions: ChatSummary[];
  loadingSessions: boolean;
  activeId: string | null;
  assistantId: string;
  setAssistantId: (id: string) => void;
  newChat: () => void;
  openChat: (id: string) => Promise<void>;
  renameChat: (id: string, title: string) => Promise<void>;
  deleteChat: (id: string) => Promise<void>;
}

const Ctx = createContext<ChatStore | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const { token, language } = useAuth();
  const [sessions, setSessions] = useState<ChatSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [assistantId, setAssistantId] = useState("");
  /* The id is read inside an in-flight send, which must not be torn down and
     rebuilt just because the list around it changed. */
  const activeRef = useRef<string | null>(null);

  const setActive = useCallback((id: string | null) => {
    activeRef.current = id;
    setActiveId(id);
  }, []);

  const refreshSessions = useCallback(async () => {
    if (!token) return;
    try {
      const d = await api.chats.list(token);
      setSessions(d.chats);
    } catch {
      setSessions([]);
    } finally {
      setLoadingSessions(false);
    }
  }, [token]);

  useLoad(refreshSessions);

  /* The session is created lazily on the first message, so a new chat that is
     never used never appears in anyone's history. */
  const send = useCallback(
    async (query: string, attachments: ChatAttachment[], signal: AbortSignal) => {
      let id = activeRef.current;
      if (!id) {
        const created = await api.chats.create(token, {
          assistant_id: assistantId || null,
        });
        id = created.id;
        setActive(id);
      }
      const res = await api.chats.ask(
        token,
        id,
        query,
        attachments,
        language,
        signal,
      );
      const chatId = id;
      setSessions((prev) => {
        const existing = prev.find((s) => s.id === chatId);
        const updated: ChatSummary = {
          id: chatId,
          title: res.title,
          assistant_id: assistantId || null,
          created_at: existing?.created_at ?? Date.now() / 1000,
          updated_at: res.updated_at ?? Date.now() / 1000,
          message_count: (existing?.message_count ?? 0) + 2,
          preview: res.title,
        };
        return [updated, ...prev.filter((s) => s.id !== chatId)];
      });
      return res.answer;
    },
    [token, language, assistantId, setActive],
  );

  const engine = useChatEngine(send);
  const { reset } = engine;

  const newChat = useCallback(() => {
    setActive(null);
    setAssistantId("");
    reset([]);
  }, [reset, setActive]);

  const openChat = useCallback(
    async (id: string) => {
      try {
        const detail = await api.chats.get(token, id);
        setAssistantId(detail.assistant_id ?? "");
        setActive(id);
        reset(historyToTurns(detail.messages));
      } catch {
        /* deleted elsewhere — leave the current thread alone */
      }
    },
    [token, reset, setActive],
  );

  const renameChat = useCallback(
    async (id: string, title: string) => {
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
      try {
        await api.chats.rename(token, id, title);
      } catch {
        void refreshSessions();
      }
    },
    [token, refreshSessions],
  );

  const deleteChat = useCallback(
    async (id: string) => {
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeRef.current === id) newChat();
      try {
        await api.chats.remove(token, id);
      } catch {
        void refreshSessions();
      }
    },
    [token, newChat, refreshSessions],
  );

  const value = useMemo<ChatStore>(
    () => ({
      ...engine,
      sessions,
      loadingSessions,
      activeId,
      assistantId,
      setAssistantId,
      newChat,
      openChat,
      renameChat,
      deleteChat,
    }),
    [
      engine,
      sessions,
      loadingSessions,
      activeId,
      assistantId,
      newChat,
      openChat,
      renameChat,
      deleteChat,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChat(): ChatStore {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useChat must be used inside <ChatProvider>");
  return ctx;
}
