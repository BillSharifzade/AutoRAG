"use client";

/* A procedure on one screen: a title, one line saying when it applies, the
   instructions, and — folded away — reference files and access. Nothing has
   to be invented: the machine name comes from the title. */

import { Download, FileText, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import {
  api,
  type ApiError,
  type SkillDefinition,
  type SkillDefinitionInput,
  type SkillResource,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useT } from "@/i18n";
import { errorWords } from "@/lib/words";
import {
  MAX_DESCRIPTION,
  blankInput,
  humanTitle,
  machineName,
  nameProblem,
  renderSkillMd,
  resourceProblem,
} from "@/lib/skills";
import { Button, Input, Textarea } from "@/components/ui";
import { ConfirmAction, Notice } from "@/components/pro";
import { AccessBlock, Field, More, TitleField, WhenField, downloadText } from "./bits";

export function ProcedureForm({
  existing,
  onSaved,
  onDeleted,
  onCancel,
}: {
  existing?: SkillDefinition;
  onSaved: (s: SkillDefinition) => void;
  onDeleted?: (id: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const { token } = useAuth();
  const [title, setTitle] = useState(existing ? humanTitle(existing.name) : "");
  const [name, setName] = useState(existing?.name ?? "");
  const [nameTouched, setNameTouched] = useState(Boolean(existing));
  const [description, setDescription] = useState(existing?.description ?? "");
  const [instructions, setInstructions] = useState(existing?.instructions ?? "");
  const [resources, setResources] = useState<SkillResource[]>(existing?.resources ?? []);
  const [audience, setAudience] = useState<string>(existing?.required_data_class ?? "operational");
  const [roleValues, setRoleValues] = useState<string[]>(existing?.required_roles ?? []);
  const [shared, setShared] = useState(existing?.shared ?? false);
  const [paste, setPaste] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function changeTitle(v: string) {
    setTitle(v);
    if (!nameTouched) setName(machineName(v, "agent"));
  }

  const resourceErrors = resources.map((r) => resourceProblem(r.path, resources));
  const ready =
    !nameProblem(name, "agent") &&
    description.trim().length > 0 &&
    instructions.trim().length > 0 &&
    resourceErrors.every((e) => !e);

  async function save() {
    setBusy(true);
    setErr("");
    const body: SkillDefinitionInput = {
      ...blankInput("agent"),
      name,
      description: description.trim(),
      instructions,
      resources: resources.map((r) => ({ path: r.path.trim(), content: r.content })),
      required_data_class: audience as SkillDefinitionInput["required_data_class"],
      required_roles: roleValues,
      shared,
      enabled: existing?.enabled ?? true,
    };
    try {
      const saved = existing
        ? await api.skillDefs.update(token, existing.id, body)
        : await api.skillDefs.create(token, body);
      onSaved(saved);
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  async function usePasted() {
    setErr("");
    try {
      const parsed = await api.skillDefs.parseSkillMd(token, paste);
      setName(parsed.name);
      setNameTouched(true);
      setTitle(humanTitle(parsed.name));
      setDescription(parsed.description);
      setInstructions(parsed.instructions);
      setPaste("");
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <TitleField
        title={title}
        name={name}
        kind="agent"
        onTitle={changeTitle}
        onName={(v) => {
          setNameTouched(true);
          setName(v);
        }}
        autoFocus={!existing}
      />

      <WhenField
        value={description}
        onChange={setDescription}
        max={MAX_DESCRIPTION}
        placeholder={t("skills.field.when.phProc")}
      />

      <Field label={t("skills.field.instructions")} hint={t("skills.field.instructions.hint")}>
        <Textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={10}
          placeholder={t("skills.field.instructions.ph")}
          className="min-h-56 font-mono text-[13px]"
        />
      </Field>

      {/* reference files, folded unless there are some */}
      <More label={t("skills.res.title")} open={resources.length > 0}>
        <div className="flex flex-col gap-3">
          {resources.map((r, i) => (
            <div key={i} className="rounded-xl border border-line bg-surface-2 p-3.5">
              <div className="flex items-center gap-2">
                <FileText className="size-4 shrink-0 text-accent" />
                <Input
                  value={r.path}
                  onChange={(e) =>
                    setResources((rs) => rs.map((x, j) => (j === i ? { ...x, path: e.target.value } : x)))
                  }
                  placeholder="checklist.md"
                  aria-label={t("skills.res.path")}
                  className="h-9 font-mono text-[12.5px]"
                />
                <button
                  type="button"
                  aria-label={t("skills.res.remove")}
                  title={t("skills.res.remove")}
                  onClick={() => setResources((rs) => rs.filter((_, j) => j !== i))}
                  className="grid size-9 shrink-0 cursor-pointer place-items-center rounded-lg text-faint transition-colors hover:bg-surface hover:text-bad"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
              {resourceErrors[i] && (
                <p className="mt-1.5 text-[12px] text-bad">{t(resourceErrors[i])}</p>
              )}
              <Textarea
                value={r.content}
                onChange={(e) =>
                  setResources((rs) => rs.map((x, j) => (j === i ? { ...x, content: e.target.value } : x)))
                }
                rows={5}
                aria-label={t("skills.res.content")}
                className="mt-2 min-h-24 font-mono text-[12.5px]"
              />
            </div>
          ))}
          <p className="text-[12px] text-faint">{t("skills.res.hint")}</p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setResources((rs) => [...rs, { path: "", content: "" }])}
            className="w-fit"
          >
            <Plus className="size-3.5" /> {t("skills.res.add")}
          </Button>
        </div>
      </More>

      <Field label={t("skills.access.title")}>
        <AccessBlock
          audience={audience}
          onAudience={setAudience}
          roleValues={roleValues}
          onRoles={setRoleValues}
          shared={shared}
          onShared={setShared}
        />
      </Field>

      {!existing && (
        <More label={t("skills.md.paste")}>
          <div className="flex flex-col gap-2">
            <Textarea
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
              rows={6}
              placeholder={t("skills.md.pastePh")}
              className="font-mono text-[12.5px]"
            />
            <Button variant="ghost" size="sm" onClick={usePasted} disabled={!paste.trim()} className="w-fit">
              {t("skills.md.use")}
            </Button>
          </div>
        </More>
      )}

      {err && <Notice tone="bad">{err}</Notice>}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
        <Button variant="cta" onClick={save} busy={busy} disabled={!ready}>
          {existing ? t("common.save") : t("skills.save.new")}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        {existing && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              downloadText(`${name || "skill"}.md`, renderSkillMd(name, description, instructions))
            }
          >
            <Download className="size-3.5" /> {t("skills.md.download")}
          </Button>
        )}
        {existing && onDeleted && (
          <span className="ml-auto">
            <ConfirmAction
              question={t("skills.delete.q")}
              onConfirm={async () => {
                await api.skillDefs.remove(token, existing.id);
                onDeleted(existing.id);
              }}
            >
              {(start) => (
                <Button variant="danger" size="sm" onClick={start}>
                  <Trash2 className="size-3.5" /> {t("common.delete")}
                </Button>
              )}
            </ConfirmAction>
          </span>
        )}
      </div>
    </div>
  );
}
