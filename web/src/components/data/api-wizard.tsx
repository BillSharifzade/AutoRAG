"use client";

/* Connecting an API in three steps: the address, what came back (with the
   assistant's reading of it and room to correct it), and how to use it. */

import { AlertTriangle, ArrowRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { api, type ApiError, type DataSource, type ProbeResult } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLocale, useT } from "@/i18n";
import { errorWords } from "@/lib/words";
import { Button, Input, Picker, Textarea } from "@/components/ui";
import { Notice, Step, Steps } from "@/components/pro";
import { AccessBlock, Field } from "@/components/skills/bits";

const HOURS = [1, 2, 6, 12, 24];

export function ApiWizard({
  onDone,
  onCancel,
}: {
  onDone: (s: DataSource) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const { token } = useAuth();
  const [step, setStep] = useState(0);
  const [url, setUrl] = useState("");
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [comment, setComment] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [audience, setAudience] = useState("operational");
  const [roleValues, setRoleValues] = useState<string[]>([]);
  const [useSkill, setUseSkill] = useState(true);
  const [useSync, setUseSync] = useState(false);
  const [hours, setHours] = useState(1);

  async function fetchIt(refine = false) {
    setBusy(true);
    setErr("");
    try {
      const res = await api.sources.probe(token, {
        url: url.trim(),
        language: locale,
        comment: refine ? comment : "",
        previous: refine ? probe?.analysis ?? null : null,
      });
      setProbe(res);
      if (!refine || !name) setName(res.analysis.suggested_name);
      if (!refine || !description) setDescription(res.analysis.suggested_description);
      const merged: Record<string, string> = {};
      for (const f of res.analysis.fields) merged[f.name] = f.meaning;
      setNotes((prev) => (refine ? { ...merged, ...prev, ...merged } : merged));
      setStep(1);
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setErr("");
    try {
      const created = await api.sources.create(token, {
        name: name.trim(),
        url: url.trim(),
        description: description.trim(),
        field_notes: notes,
        data_class: audience as DataSource["data_class"],
        required_roles: roleValues,
        skill_enabled: useSkill,
        sync_enabled: useSync,
        sync_interval_s: hours * 3600,
      });
      onDone(created);
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  const profile = probe?.profile;
  const got = !profile
    ? ""
    : profile.kind === "records"
      ? t("data.api.got.records", { n: profile.record_count, f: profile.fields.length })
      : profile.kind === "object"
        ? t("data.api.got.object", { f: profile.fields.length })
        : t("data.api.got.text", { n: profile.text_preview.length });
  const ready = name.trim() && description.trim() && (useSkill || useSync);

  return (
    <div className="flex flex-col gap-6">
      <Steps current={step} onGo={setStep}>
        <Step index={0} title={t("data.api.step.url")} summary={url.trim() || undefined} done={Boolean(probe)}>
          <div className="flex flex-col gap-4">
            <Field label={t("data.api.url")} hint={t("data.api.url.hint")}>
              <Input
                value={url}
                autoFocus
                onChange={(e) => setUrl(e.target.value)}
                placeholder={t("data.api.url.ph")}
                spellCheck={false}
                className="font-mono text-[13px]"
                onKeyDown={(e) => e.key === "Enter" && url.trim() && void fetchIt()}
              />
            </Field>
            <Button onClick={() => void fetchIt()} busy={busy} disabled={!url.trim()} className="w-fit">
              {busy ? t("data.api.fetching") : t("data.api.fetch")} <ArrowRight className="size-4" />
            </Button>
          </div>
        </Step>

        <Step index={1} title={t("data.api.step.review")} summary={got || undefined} done={step > 1}>
          {probe && profile && (
            <div className="flex flex-col gap-5">
              <div className="flex flex-wrap items-center gap-2 text-[13px] text-mut">
                <span className="rounded-md bg-surface-2 px-2 py-1 font-semibold text-ink">{got}</span>
                <span className="font-mono text-[12px]">{probe.kind} · {(probe.bytes / 1024).toFixed(0)} KB</span>
              </div>
              {probe.truncated && <Notice tone="warn">{t("data.api.truncated")}</Notice>}

              {/* what the assistant understood */}
              <div className="rounded-2xl border border-accent/25 bg-accent-soft/40 p-4">
                <p className="flex items-center gap-2 text-[13px] font-semibold text-accent-strong">
                  <Sparkles className="size-4" /> {t("data.api.ai")}
                </p>
                <p className="mt-2 whitespace-pre-wrap text-[14px] leading-relaxed">{probe.analysis.summary}</p>
                {probe.analysis.source === "heuristic" && (
                  <p className="mt-1.5 text-[12px] text-faint">{t("data.api.heuristic")}</p>
                )}
                {probe.analysis.concerns.length > 0 && (
                  <div className="mt-3">
                    <p className="flex items-center gap-1.5 text-[12px] font-semibold text-warn">
                      <AlertTriangle className="size-3.5" /> {t("data.api.concerns")}
                    </p>
                    <ul className="mt-1 list-disc pl-5 text-[13px] text-mut">
                      {probe.analysis.concerns.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* fields, with the meaning editable in place */}
              {profile.fields.length > 0 && (
                <div className="overflow-x-auto rounded-xl border border-line">
                  <table className="w-full text-[12.5px]">
                    <thead className="bg-surface-2 text-left text-[11px] uppercase tracking-wide text-mut">
                      <tr>
                        <th className="px-3 py-2 font-semibold">{t("data.api.field")}</th>
                        <th className="px-3 py-2 font-semibold">{t("data.api.type")}</th>
                        <th className="px-3 py-2 font-semibold">{t("data.api.sample")}</th>
                        <th className="px-3 py-2 font-semibold">{t("data.api.meaning")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {profile.fields.map((f) => (
                        <tr key={f.name} className="border-t border-line align-top">
                          <td className="px-3 py-2 font-mono">{f.name}</td>
                          <td className="px-3 py-2 text-mut">{f.types.join(" / ") || "—"}</td>
                          <td className="max-w-[16rem] truncate px-3 py-2 font-mono text-mut">
                            {f.samples.length ? String(f.samples[0]) : "—"}
                          </td>
                          <td className="px-3 py-1.5">
                            <input
                              value={notes[f.name] ?? ""}
                              onChange={(e) => setNotes((n) => ({ ...n, [f.name]: e.target.value }))}
                              className="h-8 w-full min-w-40 rounded-lg border border-transparent bg-transparent px-2 transition-colors hover:border-line focus:border-accent focus:bg-surface"
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <Field label={t("data.api.comment")}>
                <Textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={2}
                  placeholder={t("data.api.comment.ph")}
                  className="min-h-16"
                />
              </Field>
              <div className="flex flex-wrap gap-3">
                <Button variant="ghost" onClick={() => void fetchIt(true)} busy={busy} disabled={!comment.trim()}>
                  <Sparkles className="size-4" /> {t("data.api.refine")}
                </Button>
                <Button variant="soft" onClick={() => setStep(2)}>
                  {t("common.next")} <ArrowRight className="size-4" />
                </Button>
              </div>
            </div>
          )}
        </Step>

        <Step index={2} title={t("data.api.step.save")} done={false}>
          <div className="flex flex-col gap-5">
            <Field label={t("data.api.name")}>
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label={t("data.api.desc")}>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300} />
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              <UseCard
                on={useSkill}
                onChange={setUseSkill}
                title={t("data.api.use.skill")}
                hint={t("data.api.use.skill.hint")}
              />
              <UseCard
                on={useSync}
                onChange={setUseSync}
                title={t("data.api.use.sync")}
                hint={t("data.api.use.sync.hint")}
              >
                {useSync && (
                  <div className="mt-3 flex items-center gap-2 text-[13px]" onClick={(e) => e.stopPropagation()}>
                    <span className="text-mut">{t("data.api.every")}</span>
                    <Picker
                      value={String(hours)}
                      onChange={(v) => setHours(Number(v))}
                      options={HOURS.map((h) => ({
                        value: String(h),
                        label: h === 1 ? t("data.api.hours.1") : h === 24 ? t("data.api.day") : t("data.api.hours.n", { n: h }),
                      }))}
                      className="w-36"
                    />
                  </div>
                )}
              </UseCard>
            </div>

            <Field label={t("data.api.who")}>
              <AccessBlock
                audience={audience}
                onAudience={setAudience}
                roleValues={roleValues}
                onRoles={setRoleValues}
                shared={false}
                onShared={() => {}}
              />
            </Field>
          </div>
        </Step>
      </Steps>

      {err && <Notice tone="bad">{err}</Notice>}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
        <Button variant="cta" onClick={save} busy={busy} disabled={!ready || step < 2}>
          {t("common.save")}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        {step === 2 && !ready && <span className="text-[12.5px] text-faint">{t("data.api.need")}</span>}
      </div>
    </div>
  );
}

function UseCard({
  on,
  onChange,
  title,
  hint,
  children,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  title: string;
  hint: string;
  children?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={`cursor-pointer rounded-xl border p-4 text-left transition-colors ${
        on ? "border-accent bg-accent-soft/50" : "border-line bg-surface hover:border-line-strong"
      }`}
    >
      <span className="flex items-center gap-2.5">
        <span
          className={`grid size-5 shrink-0 place-items-center rounded-md border ${
            on ? "border-accent bg-accent text-white" : "border-line-strong"
          }`}
        >
          {on && <span className="text-[11px] font-bold">✓</span>}
        </span>
        <span className="text-[13.5px] font-semibold">{title}</span>
      </span>
      <span className="mt-1.5 block text-[12px] leading-relaxed text-mut">{hint}</span>
      {children}
    </button>
  );
}
