"use client";

/* Session state: the bearer token (localStorage-persisted), backend health,
   and the theme toggle. One provider wraps the whole app.

   There is no "answer language" here any more — the assistant always answers
   in the language of the question. The *interface* language lives in
   `@/i18n` and is a browser preference, not an account one. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { ApiError, UNAUTHORIZED_EVENT, api, type Me } from "./api";

/** Why the sign-in screen is showing, when it is not simply the first visit. */
export type SignInProblem = "invalid" | "offline" | "expired" | null;

interface AuthState {
  token: string;
  ready: boolean; // localStorage has been read
  model: string | null; // backend model name once health-checked
  /** checks the token with the server before keeping it */
  connect: (token: string) => Promise<SignInProblem>;
  disconnect: () => void;
  /** set when a stored token stopped working */
  problem: SignInProblem;
  theme: "light" | "dark";
  toggleTheme: () => void;
  /** who this token is, once resolved — drives role-gated navigation */
  me: Me | null;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState("");
  const [ready, setReady] = useState(false);
  const [model, setModel] = useState<string | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [me, setMe] = useState<Me | null>(null);
  const [problem, setProblem] = useState<SignInProblem>(null);

  /* localStorage does not exist while this renders on the server, so the token
     and theme cannot be seeded from it — the first client render has to match
     the server's or hydration breaks. Reading it here and correcting state is
     the intended pattern, and `ready` exists precisely to let the shell wait
     for it; the one extra render is the point, not an accident. */
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(localStorage.getItem("karag_token") ?? "");
    const stored = localStorage.getItem("karag_theme");
    const system = window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
    setTheme(stored === "dark" || stored === "light" ? stored : system);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("karag_theme", theme);
  }, [theme, ready]);

  useEffect(() => {
    api
      .health()
      .then((h) => setModel(h.model))
      .catch(() => setModel(null));
  }, []);

  // Identity drives which admin surfaces appear.
  useEffect(() => {
    // Signing out has to clear `me` too, but going through the promise keeps
    // that off the effect's synchronous path — and the guard below stops a
    // slow lookup for the previous token from overwriting the current one.
    let live = true;
    const lookup = token
      ? api.me(token).catch((e) => {
          // a token that no longer works is signed out (see the 401 listener)
          if (e instanceof ApiError && e.status === 401) return null;
          return null;
        })
      : Promise.resolve(null);
    void lookup.then((m) => {
      if (live) setMe(m);
    });
    return () => {
      live = false;
    };
  }, [token]);

  const disconnect = useCallback(() => {
    localStorage.removeItem("karag_token");
    setToken("");
    setMe(null);
  }, []);

  /* Any 401 — on load or mid-session — ends the session with a reason. */
  useEffect(() => {
    const onUnauthorized = () => {
      if (!localStorage.getItem("karag_token")) return;
      disconnect();
      setProblem("expired");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [disconnect]);

  const connect = useCallback(async (t: string): Promise<SignInProblem> => {
    try {
      const who = await api.me(t);
      localStorage.setItem("karag_token", t);
      setProblem(null);
      setMe(who);
      setToken(t);
      return null;
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      const why: SignInProblem = status === 401 || status === 403 ? "invalid" : "offline";
      setProblem(why);
      return why;
    }
  }, []);

  const toggleTheme = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return (
    <AuthContext.Provider
      value={{ token, ready, model, connect, disconnect, theme, toggleTheme, me, problem }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
