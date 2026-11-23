import { useState } from "react";
import { type ChangedRow, changedRows, useStock, useStocktake } from "../api/stock";
import { ErrorNote } from "./ErrorNote";
import { RefSelect } from "./RefSelect";
import { todayLocal } from "./RollForm";

interface Line {
  film_id: string;
  film: string;
  format_id: string;
  format: string;
  recorded: number;
  counted: number;
  flagged: ChangedRow | null;
}

const MAX_COUNT = 100_000;
const validCount = (v: string) => /^\d+$/.test(v.trim()) && Number(v.trim()) <= MAX_COUNT;
const key = (film_id: string, format_id: string) => `${film_id}:${format_id}`;

/**
 * Count many films in one go (the freezer stocktake). Leave a row blank to skip it; 0 means
 * "counted, none found". Differences are reviewed before anything is saved, and only they are
 * recorded. If stock moved since the review, those rows are flagged and nothing is applied.
 */
export function Stocktake({ onDone }: { onDone: () => void }) {
  const stock = useStock(true);
  const save = useStocktake();
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [extra, setExtra] = useState<{ film_id: string; film: string; format_id: string; format: string }[]>([]);
  const [pickFilm, setPickFilm] = useState<{ id: string; name: string }>({ id: "", name: "" });
  const [pickFormat, setPickFormat] = useState<{ id: string; name: string }>({ id: "", name: "" });
  const [review, setReview] = useState<Line[] | null>(null);
  const [batchId, setBatchId] = useState(() => crypto.randomUUID());
  const [stale, setStale] = useState(false);

  const known = (stock.data ?? []).map((r) => ({
    film_id: r.film.id,
    film: r.film.name,
    format_id: r.format.id,
    format: r.format.name,
    recorded: r.rolls,
  }));
  const rows = [
    ...known,
    ...extra
      .filter((e) => !known.some((k) => key(k.film_id, k.format_id) === key(e.film_id, e.format_id)))
      .map((e) => ({ ...e, recorded: 0 })),
  ].sort((a, b) => a.film.localeCompare(b.film) || a.format.localeCompare(b.format));

  function addRow() {
    if (!pickFilm.id || !pickFormat.id) return;
    const id = key(pickFilm.id, pickFormat.id);
    const already = [...known, ...extra].some((r) => key(r.film_id, r.format_id) === id);
    if (already) {
      setPickFilm({ id: "", name: "" });
      setPickFormat({ id: "", name: "" });
      return;
    }
    setExtra([
      ...extra,
      { film_id: pickFilm.id, film: pickFilm.name, format_id: pickFormat.id, format: pickFormat.name },
    ]);
    setPickFilm({ id: "", name: "" });
    setPickFormat({ id: "", name: "" });
  }

  const invalid = rows.some((r) => {
    const v = typed[key(r.film_id, r.format_id)];
    return v !== undefined && v.trim() !== "" && !validCount(v);
  });
  const entered = rows.filter((r) => (typed[key(r.film_id, r.format_id)] ?? "").trim() !== "");

  function startReview() {
    // One id per reviewed set: pressing Apply again on the same review is a safe retry, but an
    // edited set must not be mistaken for an earlier one.
    setBatchId(crypto.randomUUID());
    setReview(
      entered.map((r) => ({
        ...r,
        counted: Number(typed[key(r.film_id, r.format_id)].trim()),
        flagged: null,
      })),
    );
    setStale(false);
    save.reset();
  }

  function confirm() {
    if (!review) return;
    save.mutate(
      {
        batch_id: batchId,
        occurred_on: todayLocal(),
        counts: review.map((l) => ({
          film_id: l.film_id,
          format_id: l.format_id,
          counted: l.counted,
          expected: l.recorded,
        })),
      },
      {
        onSuccess: onDone,
        onError: (error) => {
          const changed = changedRows(error);
          if (!changed) return;
          // Show the new recorded figure and ask for another look before applying anything.
          setReview(
            review.map((l) => {
              const hit = changed.find((c) => c.film_id === l.film_id && c.format_id === l.format_id);
              return hit ? { ...l, recorded: hit.current, flagged: hit } : l;
            }),
          );
          setStale(true);
        },
      },
    );
  }

  if (review) {
    const differences = review.filter((l) => l.counted !== l.recorded);
    // A flagged row whose figure now matches the count stays visible so the alert makes sense.
    const shown = review.filter((l) => l.counted !== l.recorded || l.flagged);
    const matching = review.length - shown.length;
    return (
      <section className="stack panel" aria-label="Review stocktake">
        <h3>Review differences</h3>
        {stale && (
          <p role="alert" className="error">
            Stock changed since you counted. The flagged rows now show the current figure; check
            them and confirm again. Nothing has been saved.
          </p>
        )}
        {shown.length === 0 ? (
          <p>Every count matches the recorded stock. Nothing to change.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Film</th>
                <th>Recorded</th>
                <th>Counted</th>
                <th>Difference</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((l) => (
                <tr key={key(l.film_id, l.format_id)} className={l.flagged ? "flagged" : ""}>
                  <td>
                    {l.film} ({l.format})
                    {l.flagged && (
                      <span className="small"> — changed from {l.flagged.expected} to {l.flagged.current}</span>
                    )}
                  </td>
                  <td>{l.recorded}</td>
                  <td>{l.counted}</td>
                  <td>
                    {l.counted === l.recorded
                      ? "now matches"
                      : `${l.counted - l.recorded > 0 ? "+" : ""}${l.counted - l.recorded}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {matching > 0 && <p className="small">{matching} counted row{matching === 1 ? "" : "s"} matched.</p>}
        <div className="row">
          <button
            type="button"
            className="button primary"
            onClick={confirm}
            disabled={save.isPending || differences.length === 0}
          >
            Apply {differences.length} change{differences.length === 1 ? "" : "s"}
          </button>
          <button type="button" className="button" onClick={() => setReview(null)}>
            Back to counting
          </button>
          <button type="button" className="button" onClick={onDone}>
            Cancel
          </button>
        </div>
        {!changedRows(save.error) && <ErrorNote error={save.error} />}
      </section>
    );
  }

  return (
    <form
      className="stack panel"
      aria-label="Stocktake"
      onSubmit={(e) => {
        e.preventDefault();
        startReview();
      }}
    >
      <h3>Stocktake</h3>
      <p className="small">Enter what you actually have. Leave a row blank to skip it; 0 means none found.</p>
      {stock.isPending && <p>Loading…</p>}
      {stock.isError && <p role="alert" className="error">{stock.error.message}</p>}
      <ul className="cards">
        {rows.map((r) => {
          const id = key(r.film_id, r.format_id);
          return (
            <li key={id}>
              <div className="row spread">
                <label htmlFor={`count-${id}`}>
                  <strong>{r.film}</strong> <span className="small">{r.format}</span>
                </label>
                <span className="small">recorded {r.recorded}</span>
              </div>
              <input
                id={`count-${id}`}
                aria-label={`Counted ${r.film} ${r.format}`}
                aria-invalid={(typed[id] ?? "").trim() !== "" && !validCount(typed[id])}
                inputMode="numeric"
                pattern="[0-9]*"
                value={typed[id] ?? ""}
                onChange={(e) => setTyped({ ...typed, [id]: e.target.value })}
              />
            </li>
          );
        })}
      </ul>
      <div className="row">
        <RefSelect
          kind="films"
          label="Another film"
          value={pickFilm.id}
          onChange={(id, item) => setPickFilm({ id, name: item?.name ?? "" })}
        />
        <RefSelect
          kind="formats"
          label="Format"
          value={pickFormat.id}
          onChange={(id, item) => setPickFormat({ id, name: item?.name ?? "" })}
        />
        <button type="button" className="button" onClick={addRow} disabled={!pickFilm.id || !pickFormat.id}>
          Add row
        </button>
      </div>
      <div className="row">
        <button type="submit" className="button primary" disabled={entered.length === 0 || invalid}>
          Review differences
        </button>
        <button type="button" className="button" onClick={onDone}>
          Cancel
        </button>
      </div>
      {invalid && <p role="alert" className="error">Counts must be whole numbers from 0 to 100,000.</p>}
    </form>
  );
}
