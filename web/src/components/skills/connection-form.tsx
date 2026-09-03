"use client";

/* Connecting a data source is three plain choices and one value. The value
   is stored hidden on the server and never shown again, so it is asked for
   once, here, and nowhere else. */

import { useState } from "react";
import { api, type ApiError, type Connector, type ConnectorKind } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useT } from "@/i18n";
import { errorWords } from "@/lib/words";
import { Button, Input, Textarea } from "@/components/ui";
import { Notice, Segmented } from "@/components/pro";
import { Field, More } from "./bits";

export const ALL_CONNECTOR_KINDS: ConnectorKind[] = ["sql_sqlite", "sql_postgres", "sql_mysql", "rest"];

export function useConnectorKindLabel(): (kind: ConnectorKind) => string {
  const t = useT();
  return (kind) =>
    kind === "sql_sqlite"
      ? t("skills.conn.kind.sql_sqlite")
      : kind === "sql_postgres"
        ? t("skills.conn.kind.sql_postgres")
        : kind === "sql_mysql"
          ? t("skills.conn.kind.sql_mysql")
          : t("skills.conn.kind.rest");
}

export function ConnectionForm({
  allowed = ALL_CONNECTOR_KINDS,
  onDone,
  onCancel,
}: {
  /** which kinds make sense here — a lookup on an API can only use an API */
  allowed?: ConnectorKind[];
  onDone: (c: Connector) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const { token } = useAuth();
  const kindLabel = useConnectorKindLabel();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<ConnectorKind>(allowed[0]);
  const [value, setValue] = useState("");
  const [headers, setHeaders] = useState("");
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const field =
    kind === "sql_sqlite"
      ? { key: "path", label: t("skills.conn.path"), ph: "./sales.db" }
      : kind === "sql_postgres"
        ? { key: "dsn", label: t("skills.conn.dsn"), ph: "postgresql://reader@host/db" }
        : kind === "sql_mysql"
          ? { key: "dsn", label: t("skills.conn.dsn"), ph: "mysql://reader:pass@host:3306/db" }
        : { key: "base_url", label: t("skills.conn.url"), ph: "https://api.example.com" };

  async function create() {
    setBusy(true);
    setErr("");
    try {
      const config: Record<string, string> = { [field.key]: value.trim() };
      if (kind === "rest") {
        if (headers.trim()) {
          let parsed: unknown;
          try {
            parsed = JSON.parse(headers);
          } catch {
            parsed = null;
          }
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            setErr(t("skills.conn.err.headers"));
            return;
          }
          // The server reads a JSON object; the wire type is loose about it.
          (config as Record<string, unknown>).headers = parsed;
        }
        if (internal) config.allow_private = "true";
      }
      onDone(await api.connectors.create(token, { name: name.trim(), kind, config }));
    } catch (e) {
      setErr(errorWords((e as ApiError).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-line bg-surface-2 p-5">
      <p className="text-[13.5px] font-semibold">{t("skills.conn.new")}</p>

      {allowed.length > 1 && (
        <Segmented
          value={kind}
          onChange={setKind}
          ariaLabel={t("skills.conn.kindLabel")}
          options={allowed.map((k) => ({ value: k, label: kindLabel(k) }))}
        />
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("common.name")}>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("skills.conn.name.ph")}
          />
        </Field>
        <Field label={field.label} hint={t("skills.conn.secret.hint")}>
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={field.ph}
            spellCheck={false}
            className="font-mono text-[12.5px]"
          />
        </Field>
      </div>

      {kind === "rest" && (
        <More label={t("skills.conn.more")}>
          <div className="flex flex-col gap-4">
            <Field label={t("skills.conn.headers")} hint={t("skills.conn.headers.hint")}>
              <Textarea
                value={headers}
                onChange={(e) => setHeaders(e.target.value)}
                rows={3}
                spellCheck={false}
                placeholder={'{ "Authorization": "env:SALES_API_KEY" }'}
                className="font-mono text-[12.5px]"
              />
            </Field>
            <label className="flex cursor-pointer items-center gap-2.5 text-[13px]">
              <input
                type="checkbox"
                checked={internal}
                onChange={(e) => setInternal(e.target.checked)}
                className="size-4 accent-[var(--accent)]"
              />
              {t("skills.conn.internal")}
            </label>
          </div>
        </More>
      )}

      {err && <Notice tone="bad">{err}</Notice>}

      <div className="flex items-center gap-3">
        <Button onClick={create} busy={busy} disabled={!name.trim() || !value.trim()}>
          {t("skills.conn.connect")}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
      </div>
    </div>
  );
}
