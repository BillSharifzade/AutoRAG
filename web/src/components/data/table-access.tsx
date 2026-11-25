"use client";

/* Who may query each table of a connected database.
 *
 * The connection's own audience decides who is offered the database at all;
 * here a single table can be narrowed further — salaries to HR, say — or
 * hidden from the assistant altogether. Narrowing only: a table cannot be
 * opened wider than the database it lives in, and the server enforces that
 * on every query, so this screen is a convenience, not the guard. */

import { ChevronDown, EyeOff, Table2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { api, type ApiError, type Connector, type DataClass, type DbTable } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useT } from "@/i18n";
import { audiences, errorWords } from "@/lib/words";
import { EASE } from "@/components/pro";

const SAME = "";
const HIDDEN = "__hidden";

export function TableAccess({
  c,
  onChange,
  onError,
}: {
  c: Connector;
  onChange: (c: Connector) => void;
  onError: (m: string) => void;
}) {
  const t = useT();
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [tables, setTables] = useState<DbTable[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const classes = c.metadata.table_classes ?? {};
  const hidden = new Set(c.metadata.hidden_tables ?? []);
  const narrowed = Object.keys(classes).length + hidden.size;

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && tables === null) {
      try {
        setTables((await api.databases.schema(token, c.id)).tables);
      } catch (e) {
        onError(errorWords((e as ApiError).message));
        setOpen(false);
      }
    }
  }

  async function choose(table: string, value: string) {
    const key = table.toLowerCase();
    const nextHidden = new Set(hidden);
    const nextClasses: Record<string, DataClass | null> = { ...classes };
    nextHidden.delete(key);
    nextClasses[key] = null;
    if (value === HIDDEN) nextHidden.add(key);
    else if (value !== SAME) nextClasses[key] = value as DataClass;
    setBusy(table);
    try {
      onChange(await api.databases.update(token, c.id, {
        table_classes: nextClasses,
        hidden_tables: [...nextHidden],
      }));
    } catch (e) {
      onError(errorWords((e as ApiError).message));
    } finally {
      setBusy(null);
    }
  }

  const options = audiences();

  return (
    <div className="rounded-xl border border-line">
      <button
        type="button"
        onClick={() => void toggle()}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-[12.5px] text-mut transition-colors hover:text-ink"
      >
        <Table2 className="size-3.5" />
        <span className="flex-1">
          {narrowed
            ? t("data.tables.access.narrowed", { n: narrowed })
            : t("data.tables.access")}
        </span>
        <ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="overflow-hidden"
          >
            <p className="px-3 pb-2 text-[12px] text-faint">{t("data.tables.access.hint")}</p>
            {tables === null ? (
              <p className="px-3 pb-3 text-[12.5px] text-faint">{t("data.tables.loading")}</p>
            ) : (
              <ul className="flex flex-col divide-y divide-line border-t border-line">
                {tables.map((tb) => {
                  const key = tb.name.toLowerCase();
                  const value = hidden.has(key) ? HIDDEN : classes[key] ?? SAME;
                  return (
                    <li key={tb.name} className="flex items-center gap-3 px-3 py-2">
                      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">
                        {value === HIDDEN && <EyeOff className="mr-1.5 inline size-3.5 text-faint" />}
                        {tb.name}
                      </span>
                      <select
                        value={value}
                        disabled={busy === tb.name}
                        aria-label={t("data.tables.access.for", { table: tb.name })}
                        onChange={(e) => void choose(tb.name, e.target.value)}
                        className="h-8 max-w-[55%] cursor-pointer rounded-lg border border-line bg-surface px-2 text-[12.5px] text-ink disabled:opacity-60"
                      >
                        <option value={SAME}>{t("data.tables.access.same")}</option>
                        {options.map((a) => (
                          <option key={a.value} value={a.value}>
                            {a.label}
                          </option>
                        ))}
                        <option value={HIDDEN}>{t("data.tables.access.hidden")}</option>
                      </select>
                    </li>
                  );
                })}
              </ul>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
