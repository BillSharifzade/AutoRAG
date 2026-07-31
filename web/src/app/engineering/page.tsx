"use client";

/* Code-change review — the human gate on KARAG modifying itself.

   The assistant can only ever propose: each entry is a git branch with a diff
   and the test suite's verdict. Nothing here is live until someone presses
   Apply. */

import {
  AlertTriangle,
  Check,
  CircleSlash,
  Code2,
  FlaskConical,
  GitBranch,
  ShieldCheck,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type CodeProposal } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Button,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  Rise,
} from "@/components/ui";
import { AssistantsSkeleton } from "@/components/skeleton";

function relative(ts: number): string {
  if (!ts) return "";
  const secs = Math.round(Date.now() / 1000 - ts);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

/* Minimal unified-diff colouring — enough to read a patch, no dependency. */
function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="max-h-[520px] overflow-auto rounded-xl bg-surface-2 p-4 font-mono text-[11.5px] leading-[1.6]">
      {diff.split("\n").map((line, i) => {
        let tone = "text-mut";
        if (line.startsWith("+++") || line.startsWith("---")) tone = "text-faint font-semibold";
        else if (line.startsWith("@@")) tone = "text-accent";
        else if (line.startsWith("+")) tone = "text-good bg-good-soft";
        else if (line.startsWith("-")) tone = "text-bad bg-bad-soft";
        else if (line.startsWith("diff ")) tone = "text-ink font-semibold";
        return (
          <div key={i} className={`${tone} whitespace-pre-wrap break-all px-1`}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

export default function EngineeringPage() {
  const { token, me } = useAuth();
  const [loading, setLoading] = useState(true);
  const [proposals, setProposals] = useState<CodeProposal[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CodeProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      setProposals((await api.code.list(token)).proposals);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load proposals");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const open = async (id: string) => {
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
      setError(e instanceof ApiError ? e.message : "Could not load the diff");
    }
  };

  const act = async (id: string, action: "apply" | "discard") => {
    setBusy(true);
    setError("");
    try {
      await (action === "apply" ? api.code.apply(token, id) : api.code.discard(token, id));
      setOpenId(null);
      setDetail(null);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `Could not ${action}`);
    } finally {
      setBusy(false);
    }
  };

  if (me && !me.can_edit_code) {
    return (
      <EmptyState
        icon={<ShieldCheck className="size-6" />}
        title="Engineering is restricted"
        hint="Reviewing changes to KARAG's own source requires the karag_engineer role, which only a platform operator can grant."
      />
    );
  }

  if (loading) return <AssistantsSkeleton />;

  const pending = proposals.filter((p) => p.status === "pending");

  return (
    <div className="flex flex-col gap-6">
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="flex items-start gap-2.5 rounded-xl border border-bad/30 bg-bad-soft px-4 py-3 text-[13.5px] text-bad"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <Card flat>
        <div className="flex items-start gap-3 p-5">
          <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
            <ShieldCheck className="size-4" />
          </span>
          <p className="text-[13px] leading-relaxed text-mut">
            The assistant can only <span className="font-semibold text-ink">propose</span>.
            Each change is committed to its own git branch and the full test suite runs
            against it — nothing reaches the running platform until you apply it here.
            Access-control, identity and guard files are permanently off-limits, and a
            conversation containing uploaded or retrieved content cannot produce a change
            at all.
          </p>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Proposed changes"
          sub={`${pending.length} awaiting review`}
          icon={<Code2 className="size-4" />}
        />
        <div className="flex flex-col gap-2 p-5 pt-0">
          {proposals.length === 0 && (
            <EmptyState
              icon={<GitBranch className="size-6" />}
              title="No proposals yet"
              hint="Ask the assistant for a change in chat — for example “add a rate limit to /v1/ask”. It will write the code, run the tests, and the diff will appear here."
            />
          )}

          {proposals.map((p, i) => (
            <Rise key={p.id} delay={i * 0.04}>
              <div className="rounded-xl border border-line">
                <button
                  onClick={() => open(p.id)}
                  className="flex w-full cursor-pointer items-start justify-between gap-3 px-4 py-3.5 text-left"
                >
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 text-[14px] font-semibold">
                      {p.summary}
                      {p.status === "pending" ? (
                        p.tests_passed ? (
                          <Chip tone="good">
                            <FlaskConical className="size-3" /> tests pass
                          </Chip>
                        ) : (
                          <Chip tone="bad">
                            <FlaskConical className="size-3" /> tests fail
                          </Chip>
                        )
                      ) : (
                        <Chip tone={p.status === "applied" ? "accent" : "neutral"}>
                          {p.status}
                        </Chip>
                      )}
                    </p>
                    <p className="mt-1 truncate font-mono text-[11.5px] text-mut">
                      {p.branch}
                    </p>
                    <p className="mt-1 text-[11.5px] text-faint">
                      {p.files_changed.length} file
                      {p.files_changed.length === 1 ? "" : "s"} ·{" "}
                      <span className="text-good">+{p.insertions}</span>{" "}
                      <span className="text-bad">−{p.deletions}</span> · by {p.author}
                      {p.model && ` via ${p.model}`} · {relative(p.created_at)}
                    </p>
                  </div>
                </button>

                <AnimatePresence>
                  {openId === p.id && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      className="overflow-hidden border-t border-line"
                    >
                      <div className="p-4">
                        <p className="mb-2 text-[12px] text-mut">
                          <span className="font-semibold">Tests:</span>{" "}
                          {p.tests_summary || "not run"}
                        </p>
                        <p className="mb-3 flex flex-wrap gap-1.5">
                          {p.files_changed.map((f) => (
                            <span
                              key={f}
                              className="rounded-md border border-line bg-surface-2 px-2 py-0.5 font-mono text-[11px]"
                            >
                              {f}
                            </span>
                          ))}
                        </p>

                        {detail?.diff ? (
                          <DiffView diff={detail.diff} />
                        ) : (
                          <p className="text-[13px] text-mut">Loading diff…</p>
                        )}

                        {p.status === "pending" && (
                          <div className="mt-4 flex flex-wrap items-center gap-2">
                            <Button
                              onClick={() => act(p.id, "apply")}
                              busy={busy}
                              disabled={!detail}
                            >
                              <Check className="size-4" /> Apply &amp; merge
                            </Button>
                            <Button
                              variant="danger"
                              onClick={() => act(p.id, "discard")}
                              busy={busy}
                            >
                              <X className="size-4" /> Discard
                            </Button>
                            {!p.tests_passed && (
                              <span className="flex items-center gap-1.5 text-[12px] text-bad">
                                <CircleSlash className="size-3.5" />
                                The suite did not pass — read the diff carefully.
                              </span>
                            )}
                          </div>
                        )}
                        {p.status !== "pending" && (
                          <p className="mt-4 text-[12px] text-faint">
                            {p.status} by {p.resolved_by} {relative(p.resolved_at)}
                          </p>
                        )}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </Rise>
          ))}
        </div>
      </Card>
    </div>
  );
}
