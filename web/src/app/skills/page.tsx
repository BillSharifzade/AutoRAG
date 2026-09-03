"use client";

/* Skills — one list, one button.
 *
 * A skill is either a procedure (how the company does something) or a lookup
 * (a live figure from a connected system). The page opens on the list; "New
 * skill" asks one question — which kind — and then shows one form. Connections
 * and the shared library sit at the bottom as small sections, because they are
 * things you touch once, not every day. */

import { ArrowLeft, BookOpenCheck, Database, Globe, Plus, Search, Share2, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { api, type ApiError, type Connector, type SkillDefinition, type SkillKind } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { useLocale, useT, type Locale } from "@/i18n";
import { errorWords, roleLabel } from "@/lib/words";
import { humanTitle, isProcedure, matches, summarise, toInput } from "@/lib/skills";
import { AudienceBadge } from "@/components/audience";
import {
  ConfirmAction,
  EASE,
  Empty,
  Notice,
  PageHero,
  Restricted,
  Stagger,
  StaggerItem,
} from "@/components/pro";
import { Button, Input, Picker } from "@/components/ui";
import { KindIcon, Switch, useKindLabel } from "@/components/skills/bits";
import { useConnectorKindLabel } from "@/components/skills/connection-form";
import { LookupForm } from "@/components/skills/lookup-form";
import { ProcedureForm } from "@/components/skills/procedure-form";

type View =
  | { mode: "list" }
  | { mode: "choose" }
  | { mode: "edit"; kind: SkillKind; skill?: SkillDefinition };

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

/* ---------- a skill, as a card ---------- */

function SkillCard({
  s,
  onOpen,
  onToggle,
}: {
  s: SkillDefinition;
  onOpen: () => void;
  onToggle: (on: boolean) => Promise<void>;
}) {
  const t = useT();
  const { locale } = useLocale();
  const kindLabel = useKindLabel();
  const [busy, setBusy] = useState(false);
  // A div, not a button: the on/off switch inside is itself a button, and a
  // button may not contain another. Keyboard users still get Enter/Space.
  return (
    <motion.div
      role="button"
      tabIndex={0}
      layout
      whileHover={{ y: -2 }}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={`group flex h-full cursor-pointer flex-col rounded-2xl border border-line bg-surface p-5 text-left transition-[box-shadow,opacity] card-ring ${
        s.enabled ? "" : "opacity-60"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
          <KindIcon kind={s.kind} className="size-4.5" />
        </span>
        <Switch
          on={s.enabled}
          busy={busy}
          label={t("skills.toggle")}
          onChange={async (on) => {
            setBusy(true);
            try {
              await onToggle(on);
            } finally {
              setBusy(false);
            }
          }}
        />
      </div>
      <p className="font-display mt-3 text-[15.5px] font-semibold leading-snug">{humanTitle(s.name)}</p>
      <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-mut">{summarise(s)}</p>
      <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-4 text-[11.5px] text-faint">
        <span className="rounded-md border border-line bg-surface-2 px-2 py-1 font-medium">
          {kindLabel(s.kind)}
        </span>
        <AudienceBadge value={s.required_data_class} />
        {isProcedure(s) && s.resources.length > 0 && (
          <span>· {t(`skills.files.${plural(locale, s.resources.length)}`, { n: s.resources.length })}</span>
        )}
        {s.required_roles.length > 0 && <span>· {s.required_roles.map(roleLabel).join(", ")}</span>}
      </div>
    </motion.div>
  );
}

/* ---------- the type chooser ---------- */

function Choose({ onPick, onBack }: { onPick: (kind: SkillKind) => void; onBack: () => void }) {
  const t = useT();
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: EASE }}
      className="mx-auto max-w-3xl"
    >
      <button
        type="button"
        onClick={onBack}
        className="mb-5 inline-flex cursor-pointer items-center gap-1.5 text-[13px] font-semibold text-mut transition-colors hover:text-ink"
      >
        <ArrowLeft className="size-3.5" /> {t("common.back")}
      </button>
      <h2 className="font-display text-[22px] font-bold">{t("skills.choose.title")}</h2>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <button
          type="button"
          onClick={() => onPick("agent")}
          className="group flex cursor-pointer flex-col rounded-3xl border border-line bg-surface p-7 text-left transition-[border-color,box-shadow] hover:border-accent/50 card-ring"
        >
          <span className="grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
            <BookOpenCheck className="size-6" />
          </span>
          <span className="font-display mt-5 text-[19px] font-semibold">{t("skills.choose.procedure")}</span>
          <span className="mt-1.5 text-[13.5px] leading-relaxed text-mut">{t("skills.choose.procedure.hint")}</span>
        </button>
        <div className="flex flex-col rounded-3xl border border-line bg-surface p-7 card-ring">
          <span className="grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
            <Database className="size-6" />
          </span>
          <span className="font-display mt-5 text-[19px] font-semibold">{t("skills.choose.lookup")}</span>
          <span className="mt-1.5 text-[13.5px] leading-relaxed text-mut">{t("skills.choose.lookup.hint")}</span>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button variant="soft" size="sm" onClick={() => onPick("sql")}>
              <Database className="size-3.5" /> {t("skills.choose.fromDb")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onPick("rest")}>
              <Globe className="size-3.5" /> {t("skills.choose.fromApi")}
            </Button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

/* ---------- the page ---------- */

export default function SkillsPage() {
  const t = useT();
  const { locale } = useLocale();
  const { token, me } = useAuth();
  const kindLabel = useKindLabel();
  const connectorKindLabel = useConnectorKindLabel();

  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [library, setLibrary] = useState<SkillDefinition[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [view, setView] = useState<View>({ mode: "list" });
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const [importConn, setImportConn] = useState<Record<string, string>>({});

  const canAuthor = me?.can_author_skills ?? false;

  const load = useCallback(async () => {
    if (!token || !canAuthor) return;
    try {
      const [s, c, l] = await Promise.all([
        api.skillDefs.list(token),
        api.connectors.list(token),
        api.skillDefs.library(token).catch(() => ({ skills: [] })),
      ]);
      setSkills(s.skills);
      setConnectors(c.connectors);
      setLibrary(l.skills);
    } catch (e) {
      setNotice({ tone: "bad", text: errorWords((e as ApiError).message) });
    } finally {
      setLoaded(true);
    }
  }, [token, canAuthor]);
  useLoad(load);

  const say = useCallback((tone: "good" | "bad", text: string) => {
    setNotice({ tone, text });
    setTimeout(() => setNotice(null), 4500);
  }, []);

  const visible = useMemo(() => skills.filter((s) => matches(s, query)), [skills, query]);

  if (!me) return null;
  if (!canAuthor) {
    return (
      <Restricted
        what={t("skills.restricted.what")}
        who={t("skills.restricted.who")}
        yourRole={me.roles.map(roleLabel).join(", ")}
      />
    );
  }

  async function toggle(s: SkillDefinition, on: boolean) {
    try {
      const saved = await api.skillDefs.update(token, s.id, { ...toInput(s), enabled: on });
      setSkills((all) => all.map((x) => (x.id === saved.id ? saved : x)));
    } catch (e) {
      say("bad", errorWords((e as ApiError).message));
    }
  }

  function onSaved(saved: SkillDefinition, wasNew: boolean) {
    setSkills((all) => {
      const others = all.filter((x) => x.id !== saved.id);
      return [...others, saved].sort((a, b) => a.created_at - b.created_at);
    });
    say("good", t("skills.saved"));
    // a new lookup stays open so it can be tried; anything else returns to the list
    if (wasNew && saved.kind !== "agent") setView({ mode: "edit", kind: saved.kind, skill: saved });
    else setView({ mode: "list" });
  }

  function onDeleted(id: string) {
    setSkills((all) => all.filter((x) => x.id !== id));
    say("good", t("skills.deleted"));
    setView({ mode: "list" });
  }

  async function importFromLibrary(s: SkillDefinition) {
    try {
      const saved = await api.skillDefs.import(token, s.id, isProcedure(s) ? "" : importConn[s.id] ?? "");
      setSkills((all) => [...all, saved]);
      say("good", t("skills.library.imported"));
    } catch (e) {
      say("bad", errorWords((e as ApiError).message));
    }
  }

  /* ----- editing ----- */
  if (view.mode === "choose") {
    return <Choose onPick={(kind) => setView({ mode: "edit", kind })} onBack={() => setView({ mode: "list" })} />;
  }
  if (view.mode === "edit") {
    const { kind, skill } = view;
    const title = skill ? humanTitle(skill.name) : t("skills.new");
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE }}
        className="mx-auto max-w-3xl"
      >
        <button
          type="button"
          onClick={() => setView({ mode: "list" })}
          className="mb-5 inline-flex cursor-pointer items-center gap-1.5 text-[13px] font-semibold text-mut transition-colors hover:text-ink"
        >
          <ArrowLeft className="size-3.5" /> {t("common.back")}
        </button>
        <div className="mb-6 flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-accent-soft text-accent">
            <KindIcon kind={kind} className="size-5" />
          </span>
          <div>
            <h2 className="font-display text-[22px] font-bold leading-tight">{title}</h2>
            <p className="text-[12.5px] text-mut">{kindLabel(kind)}</p>
          </div>
        </div>
        {notice && (
          <div className="mb-5">
            <Notice tone={notice.tone}>{notice.text}</Notice>
          </div>
        )}
        <div className="rounded-3xl border border-line bg-surface p-6 [box-shadow:var(--shadow)] sm:p-8">
          {kind === "agent" ? (
            <ProcedureForm
              existing={skill}
              onSaved={(s) => onSaved(s, !skill)}
              onDeleted={onDeleted}
              onCancel={() => setView({ mode: "list" })}
            />
          ) : (
            <LookupForm
              kind={kind}
              existing={skill}
              connectors={connectors}
              onConnectorAdded={(c) => setConnectors((cs) => [...cs, c])}
              onSaved={(s) => onSaved(s, !skill)}
              onDeleted={onDeleted}
              onCancel={() => setView({ mode: "list" })}
            />
          )}
        </div>
      </motion.div>
    );
  }

  /* ----- the list ----- */
  return (
    <Stagger className="flex flex-col gap-6">
      <PageHero
        eyebrow={t("skills.eyebrow")}
        title={t("skills.title")}
        lead={t("skills.lead")}
        actions={
          <Button variant="cta" onClick={() => setView({ mode: "choose" })}>
            <Plus className="size-4" /> {t("skills.new")}
          </Button>
        }
      />

      <AnimatePresence>
        {notice && (
          <StaggerItem rise={0}>
            <Notice tone={notice.tone}>{notice.text}</Notice>
          </StaggerItem>
        )}
      </AnimatePresence>

      <StaggerItem>
        {loaded && skills.length === 0 ? (
          <div className="rounded-3xl border border-line bg-surface">
            <Empty
              icon={<BookOpenCheck className="size-6" />}
              title={t("skills.empty.title")}
              hint={t("skills.empty.hint")}
              action={
                <Button onClick={() => setView({ mode: "choose" })}>
                  <Plus className="size-4" /> {t("skills.new")}
                </Button>
              }
            />
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[13px] text-mut">
                {t(`skills.count.${plural(locale, skills.length)}`, { n: skills.length })}
              </p>
              {skills.length > 6 && (
                <div className="relative w-64">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={t("skills.search")}
                    className="pl-9"
                  />
                </div>
              )}
            </div>
            {visible.length === 0 ? (
              <p className="py-8 text-center text-[13px] text-faint">{t("skills.noMatch")}</p>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <AnimatePresence initial={false}>
                  {visible.map((s) => (
                    <motion.div key={s.id} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                      <SkillCard
                        s={s}
                        onOpen={() => setView({ mode: "edit", kind: s.kind, skill: s })}
                        onToggle={(on) => toggle(s, on)}
                      />
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            )}
          </div>
        )}
      </StaggerItem>

      {/* connections — a small section, touched rarely */}
      {connectors.length > 0 && (
        <StaggerItem>
          <section className="rounded-2xl border border-line bg-surface p-5">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-display text-[15px] font-semibold">{t("skills.connections.title")}</h3>
              <Link href="/data" className="text-[12.5px] font-semibold text-accent-strong hover:underline">
                {t("nav.data")} →
              </Link>
            </div>
            <ul className="mt-3 divide-y divide-line">
              {connectors.map((c) => (
                <li key={c.id} className="flex items-center gap-3 py-2.5">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-accent">
                    <KindIcon kind={c.kind === "rest" ? "rest" : "sql"} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] font-semibold">{c.name}</span>
                    <span className="block text-[12px] text-mut">{connectorKindLabel(c.kind)}</span>
                  </span>
                  <ConfirmAction
                    question={t("skills.connections.remove.q")}
                    onConfirm={async () => {
                      try {
                        await api.connectors.remove(token, c.id);
                        setConnectors((cs) => cs.filter((x) => x.id !== c.id));
                      } catch (e) {
                        say("bad", errorWords((e as ApiError).message));
                      }
                    }}
                  >
                    {(start) => (
                      <button
                        type="button"
                        onClick={start}
                        aria-label={t("common.delete")}
                        className="grid size-8 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-bad-soft hover:text-bad"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    )}
                  </ConfirmAction>
                </li>
              ))}
            </ul>
          </section>
        </StaggerItem>
      )}

      {/* library — other companies' shared definitions */}
      {library.length > 0 && (
        <StaggerItem>
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h3 className="font-display flex items-center gap-2 text-[15px] font-semibold">
              <Share2 className="size-4 text-accent" /> {t("skills.library.title")}
            </h3>
            <ul className="mt-3 divide-y divide-line">
              {library.map((s) => {
                const fitting = connectors.filter((c) =>
                  s.kind === "rest" ? c.kind === "rest" : c.kind !== "rest",
                );
                const needsConn = !isProcedure(s);
                return (
                  <li key={s.id} className="flex flex-wrap items-center gap-3 py-2.5">
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-accent">
                      <KindIcon kind={s.kind} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-semibold">{humanTitle(s.name)}</span>
                      <span className="block truncate text-[12px] text-mut">{s.description}</span>
                    </span>
                    {needsConn && (
                      <Picker
                        value={importConn[s.id] ?? ""}
                        onChange={(v) => setImportConn((m) => ({ ...m, [s.id]: v }))}
                        options={fitting.map((c) => ({ value: c.id, label: c.name }))}
                        placeholder={t("skills.library.needConn")}
                        className="w-56"
                      />
                    )}
                    <Button
                      size="sm"
                      variant="soft"
                      disabled={needsConn && !importConn[s.id]}
                      onClick={() => importFromLibrary(s)}
                    >
                      {t("skills.library.import")}
                    </Button>
                  </li>
                );
              })}
            </ul>
          </section>
        </StaggerItem>
      )}
    </Stagger>
  );
}
