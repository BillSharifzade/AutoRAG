"use client";

/* The conversation, held above the router.
 *
 * The chat used to live inside the chat page, so walking over to Documents and
 * back threw the thread away and you had to find your conversation again. This
 * provider is mounted in the app shell, which Next keeps alive across route
 * changes, so the open conversation and everything in it simply survives.
 *
 * It also owns what the composer needs and a plain fetch cannot give it: an
 * abort handle, so *stop* really stops (on the server too), and the answer as
 * it is being written — the server streams status, tool calls and text, and
 * the thread shows each the moment it arrives.
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
  ApiError,
  api,
  type Answer,
  type ChatAskResult,
  type ChatAttachment,
  type ChatStreamEvent,
  type ChatSummary,
  type StoredChatMessage,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { errorWords } from "@/lib/words";

/* ---------- turns ---------- */

export interface Att extends ChatAttachment {
  id: string;
  /** object URL for an image thumbnail */
  preview?: string;
  /** pretty label, e.g. a voice note's length */
  label?: string;
}

/** What the model is doing right now, while nothing has been written yet. */
export interface TurnStatus {
  stage?: "retrieving" | "thinking";
  tool?: string;
}

export interface Turn {
  role: "you" | "karag";
  text: string;
  answer?: Answer;
  error?: boolean;
  attachments?: Att[];
  /** the answer is still arriving */
  streaming?: boolean;
  status?: TurnStatus;
  /** the reader stopped it; whatever text arrived is kept */
  stopped?: boolean;
  /** the chat's assistant was deleted; this turn ran with the default one */
  assistantMissing?: boolean;
}

/** Map persisted chat messages back into renderable turns. */
export function historyToTurns(messages: StoredChatMessage[]): Turn[] {
  return messages.map((m) => {
    if (m.role === "user") {
      return {
        role: "you" as const,
        text: m.text,
        attachments: (m.attachments ?? []).map((a, i) => ({
          id: `${i}`,
          kind: a.kind,
          filename: a.filename,
          media_type: "",
          data_b64: "",
          label: a.kind === "audio" ? "voice" : undefined,
        })),
      };
    }
    const plane = m.answer?.plane;
    if (plane === "error") {
      return { role: "karag" as const, text: m.text, error: true };
    }
    if (plane === "stopped") {
      return { role: "karag" as const, text: "", stopped: true };
    }
    return {
      role: "karag" as const,
      text: m.text,
      answer: m.answer ?? undefined,
    };
  });
}

/* ---------- the engine one thread runs on ---------- */

/** Events a run may report while the answer is on its way. */
export type EngineEvent = Exclude<ChatStreamEvent, { type: "done" } | { type: "error" }>;

export interface RunResult {
  answer: Answer;
  assistantMissing?: boolean;
}

export type Runner = (
  query: string,
  attachments: ChatAttachment[],
  signal: AbortSignal,
  emit: (event: EngineEvent) => void,
) => Promise<RunResult>;

export interface ChatEngine {
  turns: Turn[];
  /** waiting on the model, or still receiving the answer */
  busy: boolean;
  /** true only while answer text is arriving */
  writing: boolean;
  send: (text: string, attachments: Att[]) => void;
  /** abandon an answer that hasn't finished — the server stops too */
  stop: () => void;
  reset: (turns?: Turn[]) => void;
}

/** A thread that sends through `run` and keeps its state locally. */
export function useChatEngine(run: Runner, initial: Turn[] = []): ChatEngine {
  const [turns, setTurns] = useState<Turn[]>(initial);
  const [pending, setPending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Nothing may keep fetching once the thread is gone.
  useEffect(() => () => abortRef.current?.abort(), []);

  const patchLast = useCallback((patch: (last: Turn) => Turn) => {
    setTurns((t) => {
      if (t.length === 0) return t;
      const last = t[t.length - 1];
      if (last.role !== "karag") return t;
      return [...t.slice(0, -1), patch(last)];
    });
  }, []);

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
        // the answer's place, filled in as events arrive
        { role: "karag", text: "", streaming: true, status: { stage: "thinking" } },
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

      const emit = (event: EngineEvent) => {
        if (controller.signal.aborted) return;
        if (event.type === "status") {
          patchLast((l) => ({ ...l, status: { stage: event.stage } }));
        } else if (event.type === "tool") {
          patchLast((l) => ({
            ...l,
            status: event.status === "start" ? { tool: event.name } : { stage: "thinking" },
          }));
        } else if (event.type === "delta") {
          patchLast((l) => ({ ...l, text: l.text + event.text, status: undefined }));
        } else if (event.type === "reset") {
          // the model in use failed mid-answer; the fallback starts over
          patchLast((l) => ({ ...l, text: "", status: { stage: "thinking" } }));
        }
      };

      void (async () => {
        try {
          const { answer, assistantMissing } = await run(
            query, payload, controller.signal, emit,
          );
          if (controller.signal.aborted) return;
          patchLast((l) => ({
            ...l,
            text: answer.text || l.text,
            answer,
            streaming: false,
            status: undefined,
            assistantMissing,
          }));
        } catch (e) {
          if (controller.signal.aborted) return;
          const message = errorWords((e as ApiError).message ?? String(e));
          patchLast((l) =>
            l.text
              ? { ...l, streaming: false, status: undefined, stopped: true }
              : { ...l, text: message, error: true, streaming: false, status: undefined },
          );
        } finally {
          if (abortRef.current === controller) abortRef.current = null;
          setPending(false);
        }
      })();
    },
    [pending, run, patchLast],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    // Keep whatever arrived: it has been paid for and may already be useful.
    patchLast((l) => ({ ...l, streaming: false, status: undefined, stopped: true }));
    setPending(false);
  }, [patchLast]);

  const reset = useCallback((next: Turn[] = []) => {
    abortRef.current?.abort();
    abortRef.current = null;
    setPending(false);
    setTurns(next);
  }, []);

  const last = turns.at(-1);
  const writing = Boolean(last?.role === "karag" && last.streaming && last.text);

  return {
    turns,
    busy: pending,
    writing,
    send: doSend,
    stop,
    reset,
  };
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
  const { token } = useAuth();
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
     never used never appears in anyone's history. The answer streams; if the
     stream cannot even be opened, the plain endpoint answers instead. */
  const run = useCallback<Runner>(
    async (query, attachments, signal, emit) => {
      let id = activeRef.current;
      if (!id) {
        const created = await api.chats.create(token, {
          assistant_id: assistantId || null,
        });
        id = created.id;
        setActive(id);
      }
      const chatId = id;

      let result: ChatAskResult | null = null;
      let sawEvent = false;
      try {
        for await (const ev of api.chats.stream(token, chatId, query, attachments, signal)) {
          sawEvent = true;
          if (ev.type === "done") {
            result = ev;
            break;
          }
          if (ev.type === "error") throw new ApiError(ev.detail, ev.status);
          emit(ev);
        }
      } catch (e) {
        if (signal.aborted || sawEvent || e instanceof ApiError) throw e;
        // transport failure before anything arrived — answer without streaming
        result = await api.chats.ask(token, chatId, query, attachments, undefined, signal);
      }
      if (!result) throw new ApiError("no answer", 502);

      const res = result;
      setSessions((prev) => {
        const existing = prev.find((s) => s.id === chatId);
        const updated: ChatSummary = {
          id: chatId,
          title: res.title,
          assistant_id: existing?.assistant_id ?? (assistantId || null),
          created_at: existing?.created_at ?? Date.now() / 1000,
          updated_at: res.updated_at ?? Date.now() / 1000,
          message_count: (existing?.message_count ?? 0) + 2,
          preview: res.title,
        };
        return [updated, ...prev.filter((s) => s.id !== chatId)];
      });
      return { answer: res.answer, assistantMissing: res.assistant_missing };
    },
    [token, assistantId, setActive],
  );

  const engine = useChatEngine(run);
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
