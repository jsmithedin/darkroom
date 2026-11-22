import { type FormEvent, useState } from "react";
import { type BulkRoll, type BulkRollInput, useSaveBulkRoll } from "../api/stock";
import { metresInput, parseMetres, parsePounds, poundsInput } from "../lib/format";
import { ErrorNote } from "./ErrorNote";
import { RefSelect } from "./RefSelect";
import { todayLocal } from "./RollForm";

interface Props {
  /** Present when editing an existing spool. */
  spool?: BulkRoll;
  /** A new purchase: hides "used before tracking" and "finished", and defaults the date to today. */
  simple?: boolean;
  onSaved: () => void;
  /** When given, a Cancel button is shown. */
  onCancel?: () => void;
}

/** Add or edit a bulk spool. Lengths are entered in metres and prices in pounds. */
export function SpoolForm({ spool, simple = false, onSaved, onCancel }: Props) {
  const save = useSaveBulkRoll(spool?.id);
  const [label, setLabel] = useState(spool?.label ?? "");
  const [filmId, setFilmId] = useState(spool?.film.id ?? "");
  const [length, setLength] = useState(spool ? metresInput(spool.length_mm) : "");
  const [cost, setCost] = useState(
    spool?.cost_pence != null ? poundsInput(spool.cost_pence) : "",
  );
  const [supplier, setSupplier] = useState(spool?.supplier ?? "");
  const [boughtOn, setBoughtOn] = useState(spool?.bought_on ?? (simple ? todayLocal() : ""));
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
    save.mutate(body, { onSuccess: onSaved });
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
      {!simple && (
        <label>
          Used before tracking (m)
          <input
            inputMode="decimal"
            value={usedBefore}
            onChange={(e) => setUsedBefore(e.target.value)}
          />
        </label>
      )}
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
      {!simple && (
        <label className="check">
          <input
            type="checkbox"
            checked={finished}
            onChange={(e) => setFinished(e.target.checked)}
          />
          Finished
        </label>
      )}
      <label>
        Notes
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="row">
        <button type="submit" className="button primary" disabled={!valid || save.isPending}>
          {spool ? "Save spool" : simple ? "Record spool" : "Add spool"}
        </button>
        {onCancel && (
          <button type="button" className="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      <ErrorNote error={save.error} />
    </form>
  );
}
