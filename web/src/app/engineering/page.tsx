"use client";

/* Suggested changes — KARAG proposing edits to its own source.
 *
 * This is the highest-consequence screen in the product, so it is built to
 * slow the reader down rather than speed them up. The four things that decide
 * whether a change is safe to apply — did the tests pass, what does it touch,
 * how big is it, what does the diff actually say — are all visible before the
 * Apply button is reachable, and Apply is a two-step confirm.
 *
 * The signature is the gate strip: the four independent barriers this change
 * had to clear, stated as facts about this proposal rather than reassurance. */

import {
  Check,
  Code2,
  FileDiff,
  GitBranch,
  Minus,
  Plus,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useState } from "react";
import { useLocale } from "@/i18n";
import { api, ApiError, type CodeProposal } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLoad } from "@/lib/use-load";
import { errorWords, roleLabel, whenWords } from "@/lib/words";
import { Button } from "@/components/ui";
import {
  ConfirmAction,
  EASE,
  Empty,
  Notice,
  PageHero,
  Restricted,
  Segmented,
  Stagger,
  StaggerItem,
} from "@/components/pro";
import { AssistantsSkeleton } from "@/components/skeleton";

type Lens = "pending" | "settled";

/* The four gates, as dictionary keys — the text lives in `@/i18n/engineering`. */
const GATES = [
  { icon: ShieldCheck, key: "role" },
  { icon: X, key: "files" },
  { icon: FileDiff, key: "untrusted" },
  { icon: Check, key: "you" },
] as const;

export default function EngineeringPage() {
  const { t } = useLocale();
  const { token, me } = useAuth();
  const [proposals, setProposals] = useState<CodeProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [lens, setLens] = useState<Lens>("pending");
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CodeProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      setProposals((await api.code.list(token)).proposals);
      setProblem("");
    } catch (e) {
      setProblem(errorWords(e instanceof ApiError ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useLoad(refresh);

  async function openOne(id: string) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    try {
      setDetail(await api.code.get(token, id));
    } catch (e) {
      setProblem(errorWords(e instanceof ApiError ? e.message : String(e)));
    }
  }

  async function act(id: string, action: "apply" | "discard") {
    setBusy(true);
    setProblem("");
    try {
      await (action === "apply"
        ? api.code.apply(token, id)
        : api.code.discard(token, id));
      setOpenId(null);
      setDetail(null);
      await refresh();
    } catch (e) {
      setProblem(errorWords(e instanceof ApiError ? e.message : String(e)));
    } finally {
      setBusy(false);
    }
  }

  if (me && !me.can_edit_code) {
    return (
      <Stagger>
        <StaggerItem>
          <Restricted
            what={t("engineering.restricted.what")}
            who={t("engineering.restricted.who")}
            yourRole={me.roles.map(roleLabel).join(", ")}
          />
        </StaggerItem>
      </Stagger>
    );
  }

  if (loading) return <AssistantsSkeleton />;

  const pending = proposals.filter((p) => p.status === "pending");
  const settled = proposals.filter((p) => p.status !== "pending");
  const shown = lens === "pending" ? pending : settled;

  return (
    <Stagger className="flex flex-col gap-6">
      <PageHero
        eyebrow={t("engineering.eyebrow")}
        title={t("engineering.title")}
        lead={t("engineering.lead")}
        actions={
          <Button variant="ghost" onClick={refresh}>
            <RefreshCw className="size-4" />
            {t("common.refresh")}
          </Button>
        }
      />

      {problem && (
        <StaggerItem>
          <Notice tone="bad">{problem}</Notice>
        </StaggerItem>
      )}

      {/* the four gates — facts about the mechanism, stated once */}
      <StaggerItem>
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {GATES.map((g, i) => (
            <motion.div
              key={g.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.08 + i * 0.06, duration: 0.45, ease: EASE }}
              className="rounded-2xl border border-line bg-surface p-4"
            >
              <span className="grid size-8 place-items-center rounded-lg bg-accent-soft text-accent">
                <g.icon className="size-4" />
              </span>
              <p className="mt-3 text-[13px] font-semibold">
                {t(`engineering.gate.${g.key}`)}
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-mut">
                {t(`engineering.gate.${g.key}.d`)}
              </p>
            </motion.div>
          ))}
        </section>
      </StaggerItem>

      <StaggerItem>
        <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
            <div>
              <h2 className="font-display text-[16px] font-semibold">
                {t("engineering.suggested")}
              </h2>
              <p className="mt-0.5 text-[13px] text-mut">
                {t("engineering.suggested.sub")}
              </p>
            </div>
            <Segmented
              value={lens}
              onChange={setLens}
              ariaLabel={t("engineering.lens.aria")}
              options={[
                { value: "pending", label: t("engineering.lens.pending"), count: pending.length },
                { value: "settled", label: t("engineering.lens.settled"), count: settled.length },
              ]}
            />
          </header>

          <div className="flex flex-col gap-2 p-6 pt-4">
            {shown.length === 0 ? (
              <Empty
                icon={<GitBranch className="size-6" />}
                title={
                  lens === "pending"
                    ? t("engineering.empty.pending")
                    : t("engineering.empty.settled")
                }
                hint={
                  lens === "pending"
                    ? t("engineering.empty.pending.hint")
                    : t("engineering.empty.settled.hint")
                }
              />
            ) : (
              shown.map((p) => (
                <Proposal
                  key={p.id}
                  p={p}
                  open={openId === p.id}
                  detail={openId === p.id ? detail : null}
                  busy={busy}
                  onToggle={() => openOne(p.id)}
                  onApply={() => act(p.id, "apply")}
                  onDiscard={() => act(p.id, "discard")}
                />
              ))
            )}
          </div>
        </section>
      </StaggerItem>
    </Stagger>
  );
}

function Proposal({
  p,
  open,
  detail,
  busy,
  onToggle,
  onApply,
  onDiscard,
}: {
  p: CodeProposal;
  open: boolean;
  detail: CodeProposal | null;
  busy: boolean;
  onToggle: () => void;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const { t, locale } = useLocale();
  const decided = p.status !== "pending";
  const lang = locale === "ru" ? "ru-RU" : "en-US";
  const fileCount = t(
    `engineering.file.${new Intl.PluralRules(lang).select(p.files_changed.length)}`,
    { n: p.files_changed.length.toLocaleString(lang) },
  );
  return (
    <motion.div
      layout
      className={`overflow-hidden rounded-2xl border transition-colors ${
        open ? "border-accent/40" : "border-line"
      }`}
    >
      <button
        onClick={onToggle}
        className="flex w-full cursor-pointer items-start gap-3.5 p-4 text-left transition-colors hover:bg-surface-2"
      >
        <span
          className={`mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg ${
            p.tests_passed
              ? "bg-good-soft text-good"
              : "bg-bad-soft text-bad"
          }`}
        >
          <Code2 className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-semibold">{p.summary}</span>
          <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-mut">
            <span className="flex items-center gap-1">
              {p.tests_passed ? (
                <>
                  <Check className="size-3.5 text-good" />
                  {t("engineering.testsPassed")}
                </>
              ) : (
                <>
                  <X className="size-3.5 text-bad" />
                  {t("engineering.testsFailed")}
                </>
              )}
            </span>
            <span className="flex items-center gap-1.5 tabular-nums">
              <span className="flex items-center text-good">
                <Plus className="size-3" />
                {p.insertions.toLocaleString(lang)}
              </span>
              <span className="flex items-center text-bad">
                <Minus className="size-3" />
                {p.deletions.toLocaleString(lang)}
              </span>
            </span>
            <span>{fileCount}</span>
            <span className="text-faint">·</span>
            <span>{whenWords(p.created_at)}</span>
            {decided && (
              <span
                className={`rounded-md px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide ${
                  p.status === "applied"
                    ? "bg-good-soft text-good"
                    : "bg-surface-2 text-mut"
                }`}
              >
                {t(`engineering.status.${p.status}`)}
              </span>
            )}
          </span>
        </span>
        <span className="shrink-0 font-mono text-[11px] text-faint">
          {p.branch}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="border-t border-line p-4">
              {!p.tests_passed && (
                <div className="mb-4">
                  <Notice tone="bad">{t("engineering.testsFailed.notice")}</Notice>
                </div>
              )}

              <p className="text-[12.5px] font-semibold">{t("engineering.files")}</p>
              <ul className="mt-1.5 flex flex-wrap gap-1.5">
                {p.files_changed.map((f) => (
                  <li
                    key={f}
                    className="rounded-md border border-line bg-surface-2 px-2 py-1 font-mono text-[11px] text-mut"
                  >
                    {f}
                  </li>
                ))}
              </ul>

              {p.tests_summary && (
                <>
                  <p className="mt-4 text-[12.5px] font-semibold">
                    {t("engineering.testsSaid")}
                  </p>
                  <pre className="mt-1.5 overflow-x-auto rounded-lg bg-bg-deep p-3 font-mono text-[11.5px] leading-relaxed text-mut">
                    {p.tests_summary}
                  </pre>
                </>
              )}

              <p className="mt-4 text-[12.5px] font-semibold">
                {t("engineering.theChange")}
              </p>
              {detail?.diff ? (
                <pre className="mt-1.5 max-h-96 overflow-auto rounded-lg bg-bg-deep p-3 font-mono text-[11.5px] leading-relaxed">
                  {detail.diff.split("\n").map((line, i) => (
                    <div
                      key={i}
                      className={
                        line.startsWith("+") && !line.startsWith("+++")
                          ? "text-good"
                          : line.startsWith("-") && !line.startsWith("---")
                            ? "text-bad"
                            : line.startsWith("@@")
                              ? "text-accent"
                              : "text-mut"
                      }
                    >
                      {line || " "}
                    </div>
                  ))}
                </pre>
              ) : (
                <p className="mt-1.5 text-[12.5px] text-faint">
                  {t("engineering.loadingDiff")}
                </p>
              )}

              {!decided && (
                <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-line pt-4">
                  <ConfirmAction
                    question={t("engineering.confirm.q")}
                    confirmLabel={t("engineering.confirm.yes")}
                    onConfirm={onApply}
                  >
                    {(start) => (
                      <Button
                        variant={p.tests_passed ? "cta" : "ghost"}
                        onClick={start}
                        disabled={busy}
                      >
                        <Check className="size-4" />
                        {t("engineering.apply")}
                      </Button>
                    )}
                  </ConfirmAction>
                  <Button variant="ghost" onClick={onDiscard} disabled={busy}>
                    {t("engineering.discard")}
                  </Button>
                  <p className="text-[12px] text-faint">
                    {t("engineering.byline", { model: p.model, author: p.author })}
                  </p>
                </div>
              )}

              {decided && (
                <p className="mt-4 border-t border-line pt-4 text-[12.5px] text-mut">
                  {t(`engineering.decided.${p.status}`, {
                    who: p.resolved_by,
                    when: whenWords(p.resolved_at),
                  })}
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
