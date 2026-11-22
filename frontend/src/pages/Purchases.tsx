import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { formatMetres, formatPounds, parsePounds } from "../lib/format";
import {
  type Movement,
  type NewMovement,
  useBulkRolls,
  useCreateMovement,
  useDeleteMovement,
  useMovements,
  useSettings,
  useUpdateMovement,
} from "../api/stock";
import { BulkMeter } from "../components/BulkMeter";
import { ErrorNote } from "../components/ErrorNote";
import { RefSelect } from "../components/RefSelect";
import { todayLocal } from "../components/RollForm";

type Mode = "bought" | "bulk" | "given";

const MODES: { mode: Mode; label: string }[] = [
  { mode: "bought", label: "Bought" },
  { mode: "bulk", label: "Loaded from bulk" },
  { mode: "given", label: "Given away" },
];

const KIND_LABEL: Record<Movement["kind"], string> = {
  purchase: "Bought",
  bulk_load: "Loaded from bulk",
  given_away: "Given away",
  adjustment: "Recount",
  opening: "Opening stock",
};

const orNull = (s: string) => (s.trim() === "" ? null : s.trim());
const isCount = (s: string) => /^\d{1,5}$/.test(s) && Number(s) > 0;

function useSubmit() {
  const create = useCreateMovement();
  const [done, setDone] = useState(false);
  return {
    create,
    done,
    send(body: NewMovement, reset: () => void) {
      setDone(false);
      create.mutate(body, {
        onSuccess: () => {
          reset();
          setDone(true);
        },
      });
    },
    clear: () => setDone(false),
  };
}

function Result({ s }: { s: ReturnType<typeof useSubmit> }) {
  return (
    <>
      {s.done && <p role="status">Recorded.</p>}
      <ErrorNote error={s.create.error} />
    </>
  );
}

function BoughtForm({ film, format }: { film: string; format: string }) {
  const s = useSubmit();
  const [date, setDate] = useState(todayLocal());
  const [filmId, setFilmId] = useState(film);
  const [formatId, setFormatId] = useState(format);
  const [rolls, setRolls] = useState("");
  const [cost, setCost] = useState("");
  const [supplier, setSupplier] = useState("");
  const [notes, setNotes] = useState("");
  const pence = parsePounds(cost);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (pence === null) return;
    s.send(
      {
        kind: "purchase",
        film_id: filmId,
        format_id: formatId,
        occurred_on: date,
        rolls: Number(rolls),
        cost_pence: pence,
        supplier: orNull(supplier),
        notes: orNull(notes),
      },
      () => {
        setRolls("");
        setCost("");
        setNotes("");
      },
    );
  }

  return (
    <form onSubmit={submit} className="stack" aria-label="Bought film">
      <label>
        Date
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
      </label>
      <RefSelect kind="films" label="Film" value={filmId} onChange={setFilmId} required />
      <RefSelect kind="formats" label="Format" value={formatId} onChange={setFormatId} required />
      <label>
        Number of rolls
        <input inputMode="numeric" value={rolls} onChange={(e) => setRolls(e.target.value)} required />
      </label>
      <label>
        Total cost (£)
        <input
          inputMode="decimal"
          value={cost}
          onChange={(e) => setCost(e.target.value)}
          placeholder="the receipt total, e.g. 25.50"
          required
        />
      </label>
      <label>
        Supplier
        <input value={supplier} onChange={(e) => setSupplier(e.target.value)} />
      </label>
      <label>
        Notes
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <button
        type="submit"
        className="button primary"
        disabled={s.create.isPending || !isCount(rolls) || pence === null || !filmId || !formatId}
      >
        Record purchase
      </button>
      <Result s={s} />
    </form>
  );
}

function BulkForm() {
  const s = useSubmit();
  const spools = useBulkRolls({ includeFinished: false });
  const settings = useSettings();
  const [date, setDate] = useState(todayLocal());
  const [spoolId, setSpoolId] = useState("");
  const [rolls, setRolls] = useState("");
  const [exposures, setExposures] = useState("36");
  const [notes, setNotes] = useState("");
  const spool = spools.data?.find((b) => b.id === spoolId);
  const uses =
    settings.data && isCount(rolls) && isCount(exposures)
      ? Number(rolls) *
        (settings.data.leader_mm + Number(exposures) * settings.data.frame_pitch_mm)
      : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    s.send(
      {
        kind: "bulk_load",
        bulk_roll_id: spoolId,
        occurred_on: date,
        rolls: Number(rolls),
        exposures_per_cassette: Number(exposures),
        notes: orNull(notes),
      },
      () => {
        setRolls("");
        setNotes("");
      },
    );
  }

  return (
    <form onSubmit={submit} className="stack" aria-label="Loaded from bulk">
      <label>
        Date
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
      </label>
      <label>
        Bulk spool
        <select value={spoolId} onChange={(e) => setSpoolId(e.target.value)} required>
          <option value="">Choose…</option>
          {spools.data?.map((b) => (
            <option key={b.id} value={b.id}>
              {b.label} ({b.film.name})
            </option>
          ))}
        </select>
      </label>
      {spool && (
        <BulkMeter
          left_mm={spool.left_mm}
          length_mm={spool.length_mm}
          exposures_left={spool.exposures_left}
        />
      )}
      <label>
        Cassettes loaded
        <input inputMode="numeric" value={rolls} onChange={(e) => setRolls(e.target.value)} required />
      </label>
      <label>
        Exposures per cassette
        <input
          inputMode="numeric"
          value={exposures}
          onChange={(e) => setExposures(e.target.value)}
          required
        />
      </label>
      {uses !== null && (
        <p className="small">
          Uses about {formatMetres(uses)}
          {spool && uses > spool.left_mm ? ", more than is left on the spool." : "."}
        </p>
      )}
      <label>
        Notes
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <button
        type="submit"
        className="button primary"
        disabled={s.create.isPending || !spoolId || !isCount(rolls) || !isCount(exposures)}
      >
        Record load
      </button>
      <Result s={s} />
    </form>
  );
}

function GivenForm({ film, format }: { film: string; format: string }) {
  const s = useSubmit();
  const [date, setDate] = useState(todayLocal());
  const [filmId, setFilmId] = useState(film);
  const [formatId, setFormatId] = useState(format);
  const [rolls, setRolls] = useState("");
  const [notes, setNotes] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    s.send(
      {
        kind: "given_away",
        film_id: filmId,
        format_id: formatId,
        occurred_on: date,
        rolls: -Number(rolls), // stock goes down
        notes: orNull(notes),
      },
      () => {
        setRolls("");
        setNotes("");
      },
    );
  }

  return (
    <form onSubmit={submit} className="stack" aria-label="Given away">
      <label>
        Date
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
      </label>
      <RefSelect kind="films" label="Film" value={filmId} onChange={setFilmId} required />
      <RefSelect kind="formats" label="Format" value={formatId} onChange={setFormatId} required />
      <label>
        Number of rolls given away
        <input inputMode="numeric" value={rolls} onChange={(e) => setRolls(e.target.value)} required />
      </label>
      <label>
        Notes
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <button
        type="submit"
        className="button primary"
        disabled={s.create.isPending || !isCount(rolls) || !filmId || !formatId}
      >
        Record given away
      </button>
      <Result s={s} />
    </form>
  );
}

function MovementEdit({ m, onDone }: { m: Movement; onDone: () => void }) {
  const update = useUpdateMovement();
  const [date, setDate] = useState(m.occurred_on);
  const [rolls, setRolls] = useState(String(Math.abs(m.rolls)));
  const [cost, setCost] = useState(m.cost_pence === null ? "" : (m.cost_pence / 100).toFixed(2));
  const [supplier, setSupplier] = useState(m.supplier ?? "");
  const [exposures, setExposures] = useState(String(m.exposures_per_cassette ?? ""));
  const [notes, setNotes] = useState(m.notes ?? "");
  const hasRolls = m.kind !== "adjustment";

  function submit(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = { id: m.id, occurred_on: date, notes: orNull(notes) };
    if (hasRolls) body.rolls = (m.kind === "given_away" ? -1 : 1) * Number(rolls);
    if (m.kind === "purchase") {
      const pence = parsePounds(cost);
      if (pence !== null) body.cost_pence = pence;
      body.supplier = orNull(supplier);
    }
    if (m.kind === "bulk_load") body.exposures_per_cassette = Number(exposures);
    update.mutate(body as { id: string } & Record<string, unknown>, { onSuccess: onDone });
  }

  return (
    <form onSubmit={submit} className="stack" aria-label="Edit movement">
      <label>
        Date
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
      </label>
      {hasRolls && (
        <label>
          Rolls
          <input inputMode="numeric" value={rolls} onChange={(e) => setRolls(e.target.value)} />
        </label>
      )}
      {m.kind === "purchase" && (
        <>
          <label>
            Total cost (£)
            <input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
          </label>
          <label>
            Supplier
            <input value={supplier} onChange={(e) => setSupplier(e.target.value)} />
          </label>
        </>
      )}
      {m.kind === "bulk_load" && (
        <label>
          Exposures per cassette
          <input
            inputMode="numeric"
            value={exposures}
            onChange={(e) => setExposures(e.target.value)}
          />
        </label>
      )}
      <label>
        Notes
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="row">
        <button type="submit" className="button primary" disabled={update.isPending}>
          Save changes
        </button>
        <button type="button" className="button" onClick={onDone}>
          Cancel
        </button>
      </div>
      <ErrorNote error={update.error} />
    </form>
  );
}

function MovementCard({ m }: { m: Movement }) {
  const [editing, setEditing] = useState(false);
  const remove = useDeleteMovement();
  if (editing) {
    return (
      <li>
        <MovementEdit m={m} onDone={() => setEditing(false)} />
      </li>
    );
  }
  return (
    <li>
      <div className="row spread">
        <strong>{KIND_LABEL[m.kind]}</strong>
        <span className="small">{m.occurred_on}</span>
      </div>
      <div>
        {m.film.name} · {m.format.name} ·{" "}
        <strong>
          {m.rolls > 0 ? "+" : ""}
          {m.rolls}
        </strong>{" "}
        {Math.abs(m.rolls) === 1 ? "roll" : "rolls"}
        {m.kind === "adjustment" && m.counted_to !== null ? ` (counted ${m.counted_to})` : ""}
      </div>
      <div className="small">
        {[
          m.cost_pence !== null ? formatPounds(m.cost_pence) : "",
          m.supplier ?? "",
          m.metres_mm !== null ? `${formatMetres(m.metres_mm)} of film` : "",
          m.notes ?? "",
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>
      <div className="row">
        <button type="button" className="button" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button
          type="button"
          className="button danger"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm("Delete this entry? The stock figure will change.")) {
              remove.mutate(m.id);
            }
          }}
        >
          Delete
        </button>
      </div>
      <ErrorNote error={remove.error} />
    </li>
  );
}

function RecentMovements() {
  const movements = useMovements(20);
  return (
    <section aria-label="Recent entries">
      <h2>Recent entries</h2>
      {movements.isPending && <p>Loading…</p>}
      {movements.data && movements.data.items.length === 0 && <p>Nothing recorded yet.</p>}
      <ul className="cards">
        {movements.data?.items.map((m) => <MovementCard key={m.id} m={m} />)}
      </ul>
    </section>
  );
}

export function Purchases() {
  const [params] = useSearchParams();
  const [mode, setMode] = useState<Mode>("bought");
  const film = params.get("film") ?? "";
  const format = params.get("format") ?? "";

  return (
    <>
      <h1>Purchases</h1>
      <div className="tabs" role="tablist" aria-label="What happened">
        {MODES.map((m) => (
          <button
            key={m.mode}
            type="button"
            role="tab"
            aria-selected={mode === m.mode}
            className={mode === m.mode ? "tab active" : "tab"}
            onClick={() => setMode(m.mode)}
          >
            {m.label}
          </button>
        ))}
      </div>
      {mode === "bought" && <BoughtForm film={film} format={format} />}
      {mode === "bulk" && <BulkForm />}
      {mode === "given" && <GivenForm film={film} format={format} />}
      <RecentMovements />
    </>
  );
}
