import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import {
  type Roll,
  type RollDraft,
  fetchLastRoll,
  rollToDraft,
  useCreateRoll,
  useDeleteRoll,
  useUpdateRoll,
} from "../api/rolls";
import { formatStops, stopsVsBox } from "../lib/stops";
import { applyCameraDefaults, loadSetup, saveSetup } from "../lib/setup";
import { ErrorNote } from "./ErrorNote";
import { RefSelect } from "./RefSelect";

const EI_PATTERN = /^\d{1,5}(\.\d{1,2})?$/;
const TIME_PATTERN = /^\d{1,3}(\.\d{1,2})?$/;

export function todayLocal(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function emptyDraft(): RollDraft {
  const setup = loadSetup();
  return {
    dev_date: todayLocal(),
    camera_id: setup?.camera_id ?? "",
    lens_id: setup?.lens_id ?? "",
    format_id: setup?.format_id ?? "",
    film_id: "",
    ei: "",
    developer_id: setup?.developer_id ?? "",
    dev_time_min: "",
    filter_id: "",
    subject: "",
    notes: "",
    source: "factory",
    counts_against_stock: true,
  };
}

/** After saving a new roll: keep the setup (and date), clear everything specific to that roll. */
function afterSave(d: RollDraft): RollDraft {
  return {
    ...emptyDraft(),
    dev_date: d.dev_date,
    camera_id: d.camera_id,
    lens_id: d.lens_id,
    format_id: d.format_id,
    developer_id: d.developer_id,
    source: d.source,
  };
}

interface Props {
  /** Present when editing an existing roll. */
  roll?: Roll;
  onDone?: () => void;
}

export function RollForm({ roll, onDone }: Props) {
  const editing = roll !== undefined;
  const qc = useQueryClient();
  const [draft, setDraft] = useState<RollDraft>(() => (roll ? rollToDraft(roll) : emptyDraft()));
  const [boxIso, setBoxIso] = useState<number | null>(roll ? roll.film.box_iso : null);
  const [saved, setSaved] = useState(false);
  const [localError, setLocalError] = useState("");
  const create = useCreateRoll();
  const update = useUpdateRoll(roll?.id ?? "");
  const remove = useDeleteRoll();
  const mutation = editing ? update : create;

  function set<K extends keyof RollDraft>(key: K, value: RollDraft[K]) {
    setSaved(false);
    setDraft((d) => ({ ...d, [key]: value }));
  }

  async function pickCamera(id: string) {
    set("camera_id", id);
    if (editing || !id) return;
    const last = await qc.fetchQuery({
      queryKey: ["rolls", "last", id],
      queryFn: () => fetchLastRoll(id),
      staleTime: 0,
    });
    // only apply if the camera is still the chosen one when the answer arrives
    setDraft((d) => (d.camera_id === id ? ({ ...d, ...applyCameraDefaults(d, last) } as RollDraft) : d));
  }

  function pickFilm(id: string, item?: { box_iso?: number }) {
    set("film_id", id);
    const box = item?.box_iso ?? null;
    setBoxIso(box);
    if (box) set("ei", String(box)); // EI starts at the box speed
  }

  const eiNumber = EI_PATTERN.test(draft.ei) ? Number(draft.ei) : NaN;
  const stops = boxIso && eiNumber > 0 ? stopsVsBox(eiNumber, boxIso) : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    setLocalError("");
    if (!(eiNumber > 0)) return setLocalError("EI must be a positive number, such as 400 or 12.5.");
    if (draft.dev_time_min && !TIME_PATTERN.test(draft.dev_time_min)) {
      return setLocalError("Development time must be a number of minutes, such as 9.5.");
    }
    mutation.mutate(draft, {
      onSuccess: () => {
        if (editing) return onDone?.();
        saveSetup({
          camera_id: draft.camera_id,
          lens_id: draft.lens_id,
          format_id: draft.format_id,
          developer_id: draft.developer_id,
        });
        setDraft(afterSave(draft));
        setBoxIso(null);
        setSaved(true);
        onDone?.();
      },
    });
  }


  return (
    <form onSubmit={submit} className="stack roll-form" aria-label={editing ? "Edit roll" : "Log a roll"}>
      <fieldset>
        <legend>Roll details</legend>
      <label>
        Developed on
        <input
          type="date"
          value={draft.dev_date}
          onChange={(e) => set("dev_date", e.target.value)}
          required
        />
      </label>
      <RefSelect kind="cameras" label="Camera" value={draft.camera_id} onChange={pickCamera} required />
      <RefSelect
        kind="lenses"
        label="Lens"
        value={draft.lens_id}
        onChange={(id) => set("lens_id", id)}
        emptyLabel="N/A"
      />
      <RefSelect
        kind="formats"
        label="Format"
        value={draft.format_id}
        onChange={(id) => set("format_id", id)}
        required
      />
      <RefSelect kind="films" label="Film" value={draft.film_id} onChange={pickFilm} required />
      <label>
        EI
        <input
          inputMode="decimal"
          value={draft.ei}
          onChange={(e) => set("ei", e.target.value)}
          placeholder="e.g. 400 or 12.5"
          required
        />
      </label>
      {stops !== null && boxIso !== null && (
        <p className="stops" aria-live="polite">
          Stops vs box: <strong>{formatStops(stops)}</strong> <span className="small">(box ISO {boxIso})</span>
        </p>
      )}
      </fieldset>
      <fieldset>
        <legend>Development</legend>
      <RefSelect
        kind="developers"
        label="Developer"
        value={draft.developer_id}
        onChange={(id) => set("developer_id", id)}
        required
      />
      <label>
        Development time (min)
        <input
          inputMode="decimal"
          value={draft.dev_time_min}
          onChange={(e) => set("dev_time_min", e.target.value)}
          placeholder="optional"
        />
      </label>
      <RefSelect
        kind="filters"
        label="Filter"
        value={draft.filter_id}
        onChange={(id) => set("filter_id", id)}
        emptyLabel="None"
      />
      <label>
        Source
        <select value={draft.source} onChange={(e) => set("source", e.target.value as RollDraft["source"])}>
          <option value="factory">Factory roll</option>
          <option value="bulk">Loaded from bulk</option>
        </select>
      </label>
      </fieldset>
      <fieldset>
        <legend>Field notes</legend>
      <label>
        Subject
        <input value={draft.subject} onChange={(e) => set("subject", e.target.value)} />
      </label>
      <label>
        Notes
        <textarea value={draft.notes} onChange={(e) => set("notes", e.target.value)} rows={3} />
      </label>

      </fieldset>
      <label className="check">
        <input
          type="checkbox"
          checked={draft.counts_against_stock}
          onChange={(e) => set("counts_against_stock", e.target.checked)}
        />
        Counts against stock
      </label>

      <div className="row">
        <button type="submit" className="button primary" disabled={mutation.isPending}>
          {editing ? "Save changes" : "Log roll"}
        </button>
        {editing && (
          <>
            <button type="button" className="button" onClick={onDone}>
              Cancel
            </button>
            <button
              type="button"
              className="button danger"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm("Delete this roll? This cannot be undone.")) {
                  remove.mutate(roll.id, { onSuccess: () => onDone?.() });
                }
              }}
            >
              Delete
            </button>
          </>
        )}
      </div>
      {saved && <p role="status">Roll logged.</p>}
      {localError && (
        <p role="alert" className="error">
          {localError}
        </p>
      )}
      <ErrorNote error={mutation.error} />
      {remove.isError && (
        <p role="alert" className="error">
          {remove.error.message}
        </p>
      )}
    </form>
  );
}
