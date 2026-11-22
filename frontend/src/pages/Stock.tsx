import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  type FilmType,
  type StockRow,
  useBulkRolls,
  useCreateAdjustment,
  useStock,
} from "../api/stock";
import { BulkMeter } from "../components/BulkMeter";
import { ErrorNote } from "../components/ErrorNote";
import { RefSelect } from "../components/RefSelect";
import { todayLocal } from "../components/RollForm";

const TYPE_ORDER: FilmType[] = ["bw", "colour", "slide"];
const TYPE_LABEL: Record<FilmType, string> = {
  bw: "Black and white",
  colour: "Colour",
  slide: "Slide",
};

interface Target {
  film_id: string;
  format_id: string;
}

function RecountForm({ initial, onDone }: { initial: Target; onDone: () => void }) {
  const [filmId, setFilmId] = useState(initial.film_id);
  const [formatId, setFormatId] = useState(initial.format_id);
  const [counted, setCounted] = useState("");
  const adjust = useCreateAdjustment();

  function submit(e: FormEvent) {
    e.preventDefault();
    adjust.mutate(
      {
        film_id: filmId,
        format_id: formatId,
        counted: Number(counted),
        occurred_on: todayLocal(),
      },
      { onSuccess: onDone },
    );
  }

  return (
    <form onSubmit={submit} className="stack panel" aria-label="Recount stock">
      <h3>Recount</h3>
      <RefSelect kind="films" label="Film" value={filmId} onChange={setFilmId} required />
      <RefSelect kind="formats" label="Format" value={formatId} onChange={setFormatId} required />
      <label>
        Rolls you actually have
        <input
          inputMode="numeric"
          pattern="[0-9]*"
          value={counted}
          onChange={(e) => setCounted(e.target.value)}
          required
        />
      </label>
      <div className="row">
        <button
          type="submit"
          className="button primary"
          disabled={adjust.isPending || !/^\d+$/.test(counted)}
        >
          Save recount
        </button>
        <button type="button" className="button" onClick={onDone}>
          Cancel
        </button>
      </div>
      <ErrorNote error={adjust.error} />
    </form>
  );
}

function groupByType(rows: StockRow[]): [FilmType, StockRow[]][] {
  return TYPE_ORDER.map((t) => [t, rows.filter((r) => r.film.type === t)] as [FilmType, StockRow[]]).filter(
    ([, list]) => list.length > 0,
  );
}

export function Stock() {
  const [params, setParams] = useSearchParams();
  const [showEmpty, setShowEmpty] = useState(false);
  const stock = useStock(showEmpty);
  const spools = useBulkRolls({ includeFinished: false });

  // ?recount=film:format opens the recount form (the link on a refused write)
  const fromLink = params.get("recount")?.split(":");
  const [target, setTarget] = useState<Target | null>(
    fromLink && fromLink.length === 2 ? { film_id: fromLink[0], format_id: fromLink[1] } : null,
  );
  function closeRecount() {
    setTarget(null);
    if (params.has("recount")) {
      params.delete("recount");
      setParams(params, { replace: true });
    }
  }

  return (
    <>
      <h1>Stock</h1>
      <div className="row spread">
        <label className="check">
          <input
            type="checkbox"
            checked={showEmpty}
            onChange={(e) => setShowEmpty(e.target.checked)}
          />
          Show empty
        </label>
        {!target && (
          <button
            type="button"
            className="button"
            onClick={() => setTarget({ film_id: "", format_id: "" })}
          >
            Recount…
          </button>
        )}
      </div>

      {target && <RecountForm key={`${target.film_id}:${target.format_id}`} initial={target} onDone={closeRecount} />}

      {stock.isPending && <p>Loading…</p>}
      {stock.isError && (
        <p role="alert" className="error">
          {stock.error.message}
        </p>
      )}
      {stock.data && stock.data.length === 0 && <p>No film in stock.</p>}
      {stock.data &&
        groupByType(stock.data).map(([type, rows]) => (
          <section key={type} aria-label={TYPE_LABEL[type]}>
            <h2>{TYPE_LABEL[type]}</h2>
            <ul className="cards">
              {rows.map((r) => (
                <li key={`${r.film.id}:${r.format.id}`} className={r.rolls === 0 ? "muted" : ""}>
                  <div className="row spread">
                    <strong>{r.film.name}</strong>
                    <span className="count">{r.rolls}</span>
                  </div>
                  <div className="row spread">
                    <span className="small">{r.format.name}</span>
                    <button
                      type="button"
                      className="button"
                      onClick={() => setTarget({ film_id: r.film.id, format_id: r.format.id })}
                    >
                      Recount
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}

      {spools.data && spools.data.length > 0 && (
        <section aria-label="Bulk film">
          <h2>Bulk film</h2>
          <ul className="cards">
            {spools.data.map((b) => (
              <li key={b.id}>
                <div className="row spread">
                  <strong>{b.label}</strong>
                  <span className="small">{b.film.name}</span>
                </div>
                <BulkMeter
                  left_mm={b.left_mm}
                  length_mm={b.length_mm}
                  exposures_left={b.exposures_left}
                />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
