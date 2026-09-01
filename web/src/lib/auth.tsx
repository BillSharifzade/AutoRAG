"use client";

/* Session state: the bearer token (localStorage-persisted), backend health,
   and the theme toggle. One provider wraps the whole app. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, type Language, type Me } from "./api";

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
  /** effective answer language; "auto" mirrors the question */
  language: Language;
  setLanguage: (l: Language) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState("");
  const [ready, setReady] = useState(false);
  const [model, setModel] = useState<string | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [me, setMe] = useState<Me | null>(null);
  const [language, setLanguageState] = useState<Language>("auto");

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

  // Identity drives which admin surfaces appear and which language is used.
  useEffect(() => {
    // Signing out has to clear `me` too, but going through the promise keeps
    // that off the effect's synchronous path — and the guard below stops a
    // slow lookup for the previous token from overwriting the current one.
    let live = true;
    const lookup = token ? api.me(token).catch(() => null) : Promise.resolve(null);
    void lookup.then((m) => {
      if (!live) return;
      setMe(m);
      if (m) setLanguageState(m.language);
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

  const setLanguage = useCallback(
    (l: Language) => {
      setLanguageState(l); // optimistic: chat keeps working either way
      if (!token) return;
      // env-token sessions have no account row to persist to; the choice then
      // simply travels with each request instead of being stored.
      api.setLanguage(token, l).catch(() => {});
    },
    [token],
  );

  const toggleTheme = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return (
    <AuthContext.Provider
      value={{
        token, ready, model, connect, disconnect, theme, toggleTheme,
        me, language, setLanguage,
      }}
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
