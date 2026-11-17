import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  applyConfiguration,
  cancelConfiguration,
  uploadConfiguration,
} from "../api";
import type { Comparison, Origin, Period, RecordChange, Report, TableComparison } from "../api";
import { texts } from "../texts";

const t = texts.import;

type Step = "file" | "comparison" | "selection" | "report";
const STEPS: Step[] = ["file", "comparison", "selection", "report"];

interface Props {
  /** Retour à la grille. */
  onFinish: () => void;
}

function changeCount(table: TableComparison): number {
  return table.inserts.length + table.updates.length + table.deletes.length;
}

/** Clés des cases à cocher d'une table, par action. */
function keysOf(table: TableComparison) {
  return {
    inserts: table.inserts.map((item) => item.key),
    updates: table.updates.flatMap((item) => item.fields.map((field) => field.key)),
    deletes: table.deletes.map((item) => item.key),
  };
}

/** Sélection de départ : ajouts et modifications cochés, suppressions décochées. */
function defaultSelection(tables: TableComparison[]): Set<string> {
  return new Set(tables.flatMap((table) => [...keysOf(table).inserts, ...keysOf(table).updates]));
}

/** Import en quatre étapes : fichier, comparaison, sélection, application. */
export function ConfigurationImport({ onFinish }: Props) {
  const [step, setStep] = useState<Step>("file");
  const [file, setFile] = useState<File | null>(null);
  const [period, setPeriod] = useState<Period>("active");
  const [origin, setOrigin] = useState<Origin>("resasat");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (caught) {
      setError(
        caught instanceof TypeError
          ? t.networkError
          : caught instanceof Error
            ? caught.message
            : String(caught),
      );
    } finally {
      setBusy(false);
    }
  }

  function compare(event: FormEvent) {
    event.preventDefault();
    if (file === null) {
      return;
    }
    void run(async () => {
      const result = await uploadConfiguration(file, period, origin);
      setComparison(result);
      setSelection(defaultSelection(result.tables));
      setStep("comparison");
    });
  }

  /** Abandonne l'import en attente côté serveur et revient au choix du fichier. */
  function restart() {
    const token = comparison?.token;
    setComparison(null);
    setReport(null);
    setFile(null);
    setError("");
    setStep("file");
    if (token !== undefined && step !== "report") {
      void cancelConfiguration(token).catch(() => undefined);
    }
  }

  function apply() {
    if (comparison === null) {
      return;
    }
    if (selection.size === 0) {
      setError(t.nothingSelected);
      return;
    }
    const deletes = comparison.tables
      .flatMap((table) => keysOf(table).deletes)
      .filter((key) => selection.has(key)).length;
    if (!window.confirm(t.confirm(selection.size, deletes))) {
      return;
    }
    void run(async () => {
      setReport(await applyConfiguration(comparison.token, [...selection]));
      setStep("report");
    });
  }

  return (
    <div className="import">
      <ol className="steps">
        {STEPS.map((name, index) => (
          <li key={name} className={name === step ? "current" : undefined}>
            {index + 1}. {t.steps[index]}
          </li>
        ))}
      </ol>
      {error !== "" && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      {step === "file" && (
        <form className="import-form" onSubmit={compare}>
          <label className="form-row">
            <span className="form-label">{t.file}</span>
            <input
              type="file"
              accept=".json,application/json"
              required
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <fieldset className="form-row">
            <legend className="form-label">{t.period}</legend>
            <label>
              <input
                type="radio"
                name="period"
                checked={period === "active"}
                onChange={() => setPeriod("active")}
              />
              {t.periodActive} <small>({t.periodActiveHelp})</small>
            </label>
            <label>
              <input
                type="radio"
                name="period"
                checked={period === "all"}
                onChange={() => setPeriod("all")}
              />
              {t.all}
            </label>
          </fieldset>
          <fieldset className="form-row">
            <legend className="form-label">{t.origin}</legend>
            <label>
              <input
                type="radio"
                name="origin"
                checked={origin === "resasat"}
                onChange={() => setOrigin("resasat")}
              />
              {t.originResasat} <small>({t.originResasatHelp})</small>
            </label>
            <label>
              <input
                type="radio"
                name="origin"
                checked={origin === "all"}
                onChange={() => setOrigin("all")}
              />
              {t.all}
            </label>
          </fieldset>
          <div className="buttons">
            <button type="submit" className="primary" disabled={busy || file === null}>
              {busy ? t.comparing : t.compare}
            </button>
            <button type="button" onClick={onFinish}>
              {t.close}
            </button>
          </div>
        </form>
      )}

      {step === "comparison" && comparison !== null && (
        <>
          <Summary comparison={comparison} />
          {comparison.total === 0 && <p className="notice">{t.noDifference}</p>}
          <div className="buttons">
            {comparison.total > 0 && (
              <button type="button" className="primary" onClick={() => setStep("selection")}>
                {t.select}
              </button>
            )}
            <button type="button" onClick={restart}>
              {comparison.total > 0 ? t.cancel : t.otherFile}
            </button>
            {comparison.total === 0 && (
              <button type="button" onClick={onFinish}>
                {t.close}
              </button>
            )}
          </div>
        </>
      )}

      {step === "selection" && comparison !== null && (
        <SelectionStep
          comparison={comparison}
          selection={selection}
          setSelection={setSelection}
          busy={busy}
          onApply={apply}
          onBack={() => {
            setError("");
            setStep("comparison");
          }}
          onCancel={restart}
        />
      )}

      {step === "report" && report !== null && (
        <>
          <p className="notice">{report.tables.length > 0 ? t.done : t.nothingApplied}</p>
          {report.tables.length > 0 && (
            <table className="data">
              <thead>
                <tr>
                  <th>{t.table}</th>
                  <th>{t.inserts}</th>
                  <th>{t.updates}</th>
                  <th>{t.deletes}</th>
                </tr>
              </thead>
              <tbody>
                {report.tables.map((table) => (
                  <tr key={table.name}>
                    <td>{table.label}</td>
                    <td className="number">{table.insert}</td>
                    <td className="number">{table.update}</td>
                    <td className="number">{table.delete}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {report.ignored > 0 && <p className="note">{t.ignoredKeys(report.ignored)}</p>}
          <div className="buttons">
            <button type="button" className="primary" onClick={onFinish}>
              {t.finish}
            </button>
            <button type="button" onClick={restart}>
              {t.newImport}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/** Étape 2 : ce que la comparaison a trouvé, table par table. */
function Summary({ comparison }: { comparison: Comparison }) {
  const period = comparison.period === "active" ? t.periodActive : t.all;
  const origin = comparison.origin === "resasat" ? t.originResasat : t.all;
  const invalid = comparison.tables.filter((table) => table.invalid.length > 0);
  return (
    <>
      <p className="note">
        {t.filters} : {t.period.toLowerCase()} « {period} », {t.origin.toLowerCase()} « {origin} ».
      </p>
      <table className="data">
        <thead>
          <tr>
            <th>{t.table}</th>
            <th>{t.inserts}</th>
            <th>{t.updates}</th>
            <th>{t.deletes}</th>
            <th>{t.discarded}</th>
          </tr>
        </thead>
        <tbody>
          {comparison.tables.map((table) =>
            table.in_file ? (
              <tr key={table.name}>
                <td>{table.label}</td>
                <td className="number">{table.inserts.length}</td>
                <td className="number">{table.updates.length}</td>
                <td className="number">{table.deletes.length}</td>
                <td className="number">{table.discarded}</td>
              </tr>
            ) : (
              <tr key={table.name}>
                <td>{table.label}</td>
                <td colSpan={4}>
                  <i>{t.notInFile}</i>
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
      {comparison.tables
        .filter((table) => table.ignored_columns.length > 0)
        .map((table) => (
          <p className="note" key={table.name}>
            {table.label} : {t.ignoredColumns} {table.ignored_columns.join(", ")}
          </p>
        ))}
      {comparison.ignored_tables.length > 0 && (
        <div className="note">
          {t.ignoredTables} :
          <ul>
            {comparison.ignored_tables.map((table) => (
              <li key={table.name}>
                <code>{table.name}</code> — {table.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {invalid.length > 0 && (
        <div className="note warning">
          {t.invalidRecords} :
          <ul>
            {invalid.flatMap((table) =>
              table.invalid.map((record) => (
                <li key={`${table.name}-${record.id}`}>
                  {table.label} #{record.id} — {record.reason}
                </li>
              )),
            )}
          </ul>
        </div>
      )}
    </>
  );
}

interface SelectionProps {
  comparison: Comparison;
  selection: Set<string>;
  setSelection: (selection: Set<string>) => void;
  busy: boolean;
  onApply: () => void;
  onBack: () => void;
  onCancel: () => void;
}

/** Étape 3 : une case par champ modifié, une case par enregistrement ajouté ou supprimé. */
function SelectionStep(props: SelectionProps) {
  const { comparison, selection, setSelection, busy } = props;
  const tables = useMemo(
    () => comparison.tables.filter((table) => changeCount(table) > 0),
    [comparison],
  );
  const allKeys = useMemo(
    () => tables.flatMap((table) => Object.values(keysOf(table)).flat()),
    [tables],
  );

  /** Coche ou décoche un ensemble de cases sans toucher aux autres. */
  function set(keys: string[], checked: boolean) {
    const next = new Set(selection);
    for (const key of keys) {
      if (checked) {
        next.add(key);
      } else {
        next.delete(key);
      }
    }
    setSelection(next);
  }

  return (
    <>
      <p className="note">{t.help}</p>
      <div className="tools">
        <button type="button" className="link" onClick={() => setSelection(new Set(allKeys))}>
          {t.selectAll}
        </button>
        <button type="button" className="link" onClick={() => setSelection(new Set())}>
          {t.selectNone}
        </button>
        <button
          type="button"
          className="link"
          onClick={() => setSelection(defaultSelection(tables))}
        >
          {t.selectAllButDeletes}
        </button>
        <span className="counter">{t.selected(selection.size, allKeys.length)}</span>
      </div>
      {tables.map((table) => (
        <TableSelection key={table.name} table={table} selection={selection} set={set} />
      ))}
      <div className="buttons sticky">
        <button type="button" className="primary" disabled={busy} onClick={props.onApply}>
          {busy ? t.applying : t.apply}
        </button>
        <button type="button" disabled={busy} onClick={props.onBack}>
          {t.back}
        </button>
        <button type="button" disabled={busy} onClick={props.onCancel}>
          {t.cancel}
        </button>
        <span className="counter">{t.selected(selection.size, allKeys.length)}</span>
      </div>
    </>
  );
}

interface TableProps {
  table: TableComparison;
  selection: Set<string>;
  set: (keys: string[], checked: boolean) => void;
}

/** Au-delà de ce nombre de lignes, une table s'affiche repliée. */
const OPEN_LIMIT = 200;

function TableSelection({ table, selection, set }: TableProps) {
  const keys = useMemo(() => Object.values(keysOf(table)).flat(), [table]);
  const [open, setOpen] = useState(keys.length <= OPEN_LIMIT);
  const selected = keys.filter((key) => selection.has(key)).length;

  return (
    <details
      className="table-section"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span className="table-name">{table.label}</span>
        <span className="counter">{t.selected(selected, keys.length)}</span>
      </summary>
      {/* Les lignes d'une table repliée ne sont pas construites. */}
      {open && (
        <>
          <div className="tools">
            <button type="button" className="link" onClick={() => set(keys, true)}>
              {t.selectAll}
            </button>
            <button type="button" className="link" onClick={() => set(keys, false)}>
              {t.selectNone}
            </button>
          </div>
          <table className="data changes">
            <thead>
              <tr>
                <th />
                <th>{t.action}</th>
                <th>{t.record}</th>
                <th>{t.field}</th>
                <th>{t.currentValue}</th>
                <th>{t.importedValue}</th>
              </tr>
            </thead>
            <tbody>
              {table.updates.flatMap((update) =>
                update.fields.map((field, index) => (
                  <tr key={field.key} className="update">
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${t.update} ${update.label} : ${field.label}`}
                        checked={selection.has(field.key)}
                        onChange={(event) => set([field.key], event.target.checked)}
                      />
                    </td>
                    {index === 0 && (
                      <>
                        <td rowSpan={update.fields.length}>{t.update}</td>
                        <td rowSpan={update.fields.length}>
                          <RecordName label={update.label} id={update.id} />
                        </td>
                      </>
                    )}
                    <td>{field.label}</td>
                    <td className="old">{field.old}</td>
                    <td className="new">{field.new}</td>
                  </tr>
                )),
              )}
              {table.inserts.map((record) => (
                <RecordRow
                  key={record.key}
                  record={record}
                  action="insert"
                  checked={selection.has(record.key)}
                  onChange={(checked) => set([record.key], checked)}
                />
              ))}
              {table.deletes.map((record) => (
                <RecordRow
                  key={record.key}
                  record={record}
                  action="delete"
                  checked={selection.has(record.key)}
                  onChange={(checked) => set([record.key], checked)}
                />
              ))}
            </tbody>
          </table>
        </>
      )}
    </details>
  );
}

function RecordName({ label, id }: { label: string; id: number }) {
  return (
    <>
      {label} <small>(#{id})</small>
    </>
  );
}

interface RecordRowProps {
  record: RecordChange;
  action: "insert" | "delete";
  checked: boolean;
  onChange: (checked: boolean) => void;
}

/** Ajout ou suppression : une ligne par enregistrement, ses champs à la demande. */
function RecordRow({ record, action, checked, onChange }: RecordRowProps) {
  const title = action === "insert" ? t.insert : t.delete;
  return (
    <tr className={action}>
      <td>
        <input
          type="checkbox"
          aria-label={`${title} ${record.label}`}
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
        />
      </td>
      <td>{title}</td>
      <td>
        <RecordName label={record.label} id={record.id} />
      </td>
      <td colSpan={3}>
        {record.fields.length > 0 && (
          <details>
            <summary>{t.details}</summary>
            <dl className={action === "insert" ? "fields new" : "fields old"}>
              {record.fields.map((field) => (
                <div key={field.label}>
                  <dt>{field.label}</dt>
                  <dd>{field.value}</dd>
                </div>
              ))}
            </dl>
          </details>
        )}
      </td>
    </tr>
  );
}
