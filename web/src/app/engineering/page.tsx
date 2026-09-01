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

export default function EngineeringPage() {
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
            what="Reviewing KARAG's own code is restricted"
            who="This screen decides whether a change reaches the running platform. It's limited to platform engineers, and only a platform operator can grant that."
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
        eyebrow="Engineering"
        title="Changes waiting for a human"
        lead="KARAG can write a change to its own source, but it can never ship one. Each proposal lands on its own branch with the full test suite already run against it, and stays there until someone here applies it."
        actions={
          <Button variant="ghost" onClick={refresh}>
            <RefreshCw className="size-4" />
            Refresh
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
          {[
            {
              icon: ShieldCheck,
              t: "Role-gated",
              d: "Only a platform engineer can ask for a change, and only an operator can grant that role.",
            },
            {
              icon: X,
              t: "Off-limits files",
              d: "Access control, the tenant directory and the guard itself can never be edited — by any role.",
            },
            {
              icon: FileDiff,
              t: "Untrusted input refused",
              d: "A conversation carrying an uploaded or retrieved document cannot produce a change at all.",
            },
            {
              icon: Check,
              t: "You apply it",
              d: "The running system is untouched until someone presses Apply on this page.",
            },
          ].map((g, i) => (
            <motion.div
              key={g.t}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.08 + i * 0.06, duration: 0.45, ease: EASE }}
              className="rounded-2xl border border-line bg-surface p-4"
            >
              <span className="grid size-8 place-items-center rounded-lg bg-accent-soft text-accent">
                <g.icon className="size-4" />
              </span>
              <p className="mt-3 text-[13px] font-semibold">{g.t}</p>
              <p className="mt-1 text-[12px] leading-relaxed text-mut">{g.d}</p>
            </motion.div>
          ))}
        </section>
      </StaggerItem>

      <StaggerItem>
        <section className="overflow-hidden rounded-3xl border border-line bg-surface [box-shadow:var(--shadow)]">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
            <div>
              <h2 className="font-display text-[16px] font-semibold">
                Suggested changes
              </h2>
              <p className="mt-0.5 text-[13px] text-mut">
                Read the diff before you apply. Nothing here has run yet.
              </p>
            </div>
            <Segmented
              value={lens}
              onChange={setLens}
              ariaLabel="Which proposals"
              options={[
                { value: "pending", label: "Waiting", count: pending.length },
                { value: "settled", label: "Decided", count: settled.length },
              ]}
            />
          </header>

          <div className="flex flex-col gap-2 p-6 pt-4">
            {shown.length === 0 ? (
              <Empty
                icon={<GitBranch className="size-6" />}
                title={
                  lens === "pending"
                    ? "Nothing waiting"
                    : "Nothing decided yet"
                }
                hint={
                  lens === "pending"
                    ? "Ask KARAG in chat to change something about itself. The proposal appears here with its test results, and nothing moves until you say so."
                    : "Once you apply or discard a proposal it moves here, with who decided and when."
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
  const decided = p.status !== "pending";
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
                  All tests passed
                </>
              ) : (
                <>
                  <X className="size-3.5 text-bad" />
                  Tests failed
                </>
              )}
            </span>
            <span className="flex items-center gap-1.5 tabular-nums">
              <span className="flex items-center text-good">
                <Plus className="size-3" />
                {p.insertions}
              </span>
              <span className="flex items-center text-bad">
                <Minus className="size-3" />
                {p.deletions}
              </span>
            </span>
            <span>
              {p.files_changed.length}{" "}
              {p.files_changed.length === 1 ? "file" : "files"}
            </span>
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
                {p.status}
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
                  <Notice tone="bad">
                    The test suite failed against this change. Applying it would
                    put failing code on the running platform.
                  </Notice>
                </div>
              )}

              <p className="text-[12.5px] font-semibold">Files it touches</p>
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
                    What the tests said
                  </p>
                  <pre className="mt-1.5 overflow-x-auto rounded-lg bg-bg-deep p-3 font-mono text-[11.5px] leading-relaxed text-mut">
                    {p.tests_summary}
                  </pre>
                </>
              )}

              <p className="mt-4 text-[12.5px] font-semibold">The change</p>
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
                <p className="mt-1.5 text-[12.5px] text-faint">Loading the diff…</p>
              )}

              {!decided && (
                <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-line pt-4">
                  <ConfirmAction
                    question="Put this on the running platform?"
                    confirmLabel="Yes, apply it"
                    onConfirm={onApply}
                  >
                    {(start) => (
                      <Button
                        variant={p.tests_passed ? "cta" : "ghost"}
                        onClick={start}
                        disabled={busy}
                      >
                        <Check className="size-4" />
                        Apply this change
                      </Button>
                    )}
                  </ConfirmAction>
                  <Button variant="ghost" onClick={onDiscard} disabled={busy}>
                    Discard
                  </Button>
                  <p className="text-[12px] text-faint">
                    Written by {p.model} · asked for by {p.author}
                  </p>
                </div>
              )}

              {decided && (
                <p className="mt-4 border-t border-line pt-4 text-[12.5px] text-mut">
                  {p.status === "applied" ? "Applied" : "Discarded"} by{" "}
                  {p.resolved_by} {whenWords(p.resolved_at)}.
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
