import { type FormEvent, useEffect, useState } from "react";
import {
  type BulkRoll,
  type BulkRollInput,
  useBulkRolls,
  useDeleteBulkRoll,
  useSaveBulkRoll,
  useSettings,
  useUpdateSettings,
} from "../api/stock";
import { BulkMeter } from "../components/BulkMeter";
import { ErrorNote } from "../components/ErrorNote";
import { RefSelect } from "../components/RefSelect";
import { formatPounds, metresInput, parseMetres, parsePounds, poundsInput } from "../lib/format";

const isWhole = (s: string) => /^\d{1,5}$/.test(s) && Number(s) > 0;

function BulkMathsForm() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [leader, setLeader] = useState("");
  const [pitch, setPitch] = useState("");
  const [timezone, setTimezone] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings.data) {
      setLeader(String(settings.data.leader_mm));
      setPitch(String(settings.data.frame_pitch_mm));
      setTimezone(settings.data.timezone);
    }
  }, [settings.data]);

  function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    update.mutate(
      { leader_mm: Number(leader), frame_pitch_mm: Number(pitch), timezone: timezone.trim() },
      { onSuccess: () => setSaved(true) },
    );
  }

  return (
    <form onSubmit={submit} className="stack" aria-label="Bulk film maths">
      <h2>Bulk film maths</h2>
      <p className="small">
        A 36-exposure cassette uses the leader plus 36 frames. Changing these never alters loads
        already recorded; it only changes the live estimates.
      </p>
      <label>
        Leader per cassette (mm)
        <input inputMode="numeric" value={leader} onChange={(e) => setLeader(e.target.value)} />
      </label>
      <label>
        Frame pitch (mm per exposure)
        <input inputMode="numeric" value={pitch} onChange={(e) => setPitch(e.target.value)} />
      </label>
      <label>
        Timezone
        <input value={timezone} onChange={(e) => setTimezone(e.target.value)} />
      </label>
      <button
        type="submit"
        className="button primary"
        disabled={update.isPending || !isWhole(leader) || !isWhole(pitch) || !timezone.trim()}
      >
        Save
      </button>
      {saved && <p role="status">Saved.</p>}
      <ErrorNote error={update.error} />
    </form>
  );
}

function SpoolForm({ spool, onDone }: { spool?: BulkRoll; onDone: () => void }) {
  const save = useSaveBulkRoll(spool?.id);
  const [label, setLabel] = useState(spool?.label ?? "");
  const [filmId, setFilmId] = useState(spool?.film.id ?? "");
  const [length, setLength] = useState(spool ? metresInput(spool.length_mm) : "");
  const [cost, setCost] = useState(
    spool?.cost_pence != null ? poundsInput(spool.cost_pence) : "",
  );
  const [supplier, setSupplier] = useState(spool?.supplier ?? "");
  const [boughtOn, setBoughtOn] = useState(spool?.bought_on ?? "");
  const [usedBefore, setUsedBefore] = useState(spool ? metresInput(spool.used_before_mm) : "0");
  const [finished, setFinished] = useState(spool?.finished ?? false);
  const [notes, setNotes] = useState(spool?.notes ?? "");

  const lengthMm = parseMetres(length);
  const usedMm = parseMetres(usedBefore);
  const costPence = cost.trim() === "" ? null : parsePounds(cost);
  const valid =
    label.trim() !== "" &&
    filmId !== "" &&
    lengthMm !== null &&
    lengthMm > 0 &&
    usedMm !== null &&
    (cost.trim() === "" || costPence !== null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid || lengthMm === null || usedMm === null) return;
    const body: BulkRollInput = {
      label: label.trim(),
      film_id: filmId,
      length_mm: lengthMm,
      cost_pence: costPence,
      supplier: supplier.trim() || null,
      bought_on: boughtOn || null,
      used_before_mm: usedMm,
      finished,
      notes: notes.trim() || null,
    };
    save.mutate(body, { onSuccess: onDone });
  }

  return (
    <form onSubmit={submit} className="stack panel" aria-label={spool ? "Edit spool" : "Add spool"}>
      <label>
        Label
        <input value={label} onChange={(e) => setLabel(e.target.value)} required maxLength={100} />
      </label>
      <RefSelect kind="films" label="Film" value={filmId} onChange={setFilmId} required />
      <label>
        Length (m)
        <input inputMode="decimal" value={length} onChange={(e) => setLength(e.target.value)} required />
      </label>
      <label>
        Used before tracking (m)
        <input
          inputMode="decimal"
          value={usedBefore}
          onChange={(e) => setUsedBefore(e.target.value)}
        />
      </label>
      <label>
        Price (£, optional)
        <input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
      </label>
      <label>
        Supplier (optional)
        <input value={supplier} onChange={(e) => setSupplier(e.target.value)} />
      </label>
      <label>
        Bought on (optional)
        <input type="date" value={boughtOn} onChange={(e) => setBoughtOn(e.target.value)} />
      </label>
      <label className="check">
        <input type="checkbox" checked={finished} onChange={(e) => setFinished(e.target.checked)} />
        Finished
      </label>
      <label>
        Notes
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="row">
        <button type="submit" className="button primary" disabled={!valid || save.isPending}>
          {spool ? "Save spool" : "Add spool"}
        </button>
        <button type="button" className="button" onClick={onDone}>
          Cancel
        </button>
      </div>
      <ErrorNote error={save.error} />
    </form>
  );
}

function SpoolCard({ spool }: { spool: BulkRoll }) {
  const [editing, setEditing] = useState(false);
  const remove = useDeleteBulkRoll();
  if (editing) {
    return (
      <li>
        <SpoolForm spool={spool} onDone={() => setEditing(false)} />
      </li>
    );
  }
  return (
    <li className={spool.finished ? "muted" : ""}>
      <div className="row spread">
        <strong>{spool.label}</strong>
        {spool.finished && <span className="badge">finished</span>}
      </div>
      <div className="small">
        {spool.film.name} · {spool.cassettes_loaded} cassettes loaded
        {spool.cost_per_36_pence !== null
          ? ` · ${formatPounds(spool.cost_per_36_pence)} per 36`
          : " · unpriced"}
      </div>
      <BulkMeter
        left_mm={spool.left_mm}
        length_mm={spool.length_mm}
        exposures_left={spool.exposures_left}
      />
      <div className="row">
        <button type="button" className="button" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button
          type="button"
          className="button danger"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(`Delete "${spool.label}"?`)) remove.mutate(spool.id);
          }}
        >
          Delete
        </button>
      </div>
      <ErrorNote error={remove.error} />
    </li>
  );
}

export function SettingsBulk() {
  const spools = useBulkRolls({ includeFinished: true });
  const [adding, setAdding] = useState(false);
  return (
    <>
      <h1>Bulk film</h1>
      <BulkMathsForm />
      <section aria-label="Bulk spools">
        <div className="row spread">
          <h2>Spools</h2>
          {!adding && (
            <button type="button" className="button primary" onClick={() => setAdding(true)}>
              Add spool
            </button>
          )}
        </div>
        {adding && <SpoolForm onDone={() => setAdding(false)} />}
        {spools.isPending && <p>Loading…</p>}
        {spools.data && spools.data.length === 0 && <p>No bulk spools yet.</p>}
        <ul className="cards">
          {spools.data?.map((b) => <SpoolCard key={b.id} spool={b} />)}
        </ul>
      </section>
    </>
  );
}
