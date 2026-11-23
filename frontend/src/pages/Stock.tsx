import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  type FilmRef,
  type FilmType,
  type FormatRef,
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

function rollSections(rows: StockRow[], sort: string) {
  if (sort === "type") {
    return TYPE_ORDER.map((type) => ({
      title: TYPE_LABEL[type],
      rows: rows.filter((row) => row.film.type === type),
    })).filter((section) => section.rows.length > 0);
  }

  rows.sort((a, b) => {
    if (sort === "fewest" && a.rolls !== b.rolls) return a.rolls - b.rolls;
    if (sort === "most" && a.rolls !== b.rolls) return b.rolls - a.rolls;
    return a.film.name.localeCompare(b.film.name) || a.format.name.localeCompare(b.format.name);
  });
  return rows.length ? [{ title: "Individual rolls", rows }] : [];
}

export function Stock() {
  const [params, setParams] = useSearchParams();
  const [showEmpty, setShowEmpty] = useState(false);
  const stock = useStock(showEmpty);
  const spools = useBulkRolls({ includeFinished: false });

  const [search, setSearch] = useState("");
  const [filmType, setFilmType] = useState("");
  const [format, setFormat] = useState<FormatRef | null>(null);
  const [rollSort, setRollSort] = useState("type");
  const [bulkSort, setBulkSort] = useState("default");
  const query = search.trim().toLowerCase();

  function matchesFilm(film: FilmRef) {
    return (!filmType || film.type === filmType) && film.name.toLowerCase().includes(query);
  }

  const formats = new Map(stock.data?.map(({ format }) => [format.id, format.name]));
  if (format) formats.set(format.id, format.name);
  const rolls = (stock.data ?? []).filter((row) =>
    matchesFilm(row.film) && (!format || row.format.id === format.id)
  );
  const visibleSpools = (spools.data ?? []).filter((spool) => matchesFilm(spool.film));
  if (bulkSort === "remaining") visibleSpools.sort((a, b) => a.left_mm - b.left_mm);

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
      <div className="row">
        <label>
          Film name
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <label>
          Film type
          <select value={filmType} onChange={(e) => setFilmType(e.target.value)}>
            <option value="">All types</option>
            {TYPE_ORDER.map((type) => <option key={type} value={type}>{TYPE_LABEL[type]}</option>)}
          </select>
        </label>
        <label>
          Roll format
          <select value={format?.id ?? ""} onChange={(e) => {
            const id = e.target.value;
            setFormat(id ? { id, name: e.target.selectedOptions[0].text } : null);
          }}>
            <option value="">All formats</option>
            {Array.from(formats).sort((a, b) => a[1].localeCompare(b[1])).map(([id, name]) =>
              <option key={id} value={id}>{name}</option>
            )}
          </select>
        </label>
        <label>
          Sort rolls
          <select value={rollSort} onChange={(e) => setRollSort(e.target.value)}>
            <option value="type">Group by film type</option>
            <option value="name">Name A–Z</option>
            <option value="fewest">Fewest rolls first</option>
            <option value="most">Most rolls first</option>
          </select>
        </label>
      </div>
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
      {stock.data && stock.data.length === 0 && <p>No individual rolls in stock.</p>}
      {!!stock.data?.length && rolls.length === 0 && <p>No individual rolls match your filters.</p>}
      {rollSections(rolls, rollSort).map(({ title, rows }) => (
        <section key={title} aria-label={title}>
          <h2>{title}</h2>
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
        <section aria-labelledby="bulk-film-heading">
          <h2 id="bulk-film-heading">Bulk film (35mm)</h2>
          {spools.data.length > 1 && (
            <label>
              Sort bulk film
              <select value={bulkSort} onChange={(e) => setBulkSort(e.target.value)}>
                <option value="default">Default order</option>
                <option value="remaining">Least film remaining</option>
              </select>
            </label>
          )}
          {visibleSpools.length === 0 && <p>No bulk film matches your filters.</p>}
          <ul className="cards">
            {visibleSpools.map((b) => (
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
