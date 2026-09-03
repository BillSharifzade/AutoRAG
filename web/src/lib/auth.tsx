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
import { api, type Me } from "./api";

interface AuthState {
  token: string;
  ready: boolean; // localStorage has been read
  model: string | null; // backend model name once health-checked
  connect: (token: string) => void;
  disconnect: () => void;
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
    const lookup = token ? api.me(token).catch(() => null) : Promise.resolve(null);
    void lookup.then((m) => {
      if (live) setMe(m);
    });
    return () => {
      live = false;
    };
  }, [token]);

  const connect = useCallback((t: string) => {
    localStorage.setItem("karag_token", t);
    setToken(t);
  }, []);

  const disconnect = useCallback(() => {
    localStorage.removeItem("karag_token");
    setToken("");
    setMe(null);
  }, []);

  const toggleTheme = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return (
    <AuthContext.Provider
      value={{ token, ready, model, connect, disconnect, theme, toggleTheme, me }}
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
