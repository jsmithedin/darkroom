import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  type BulkRoll,
  useBulkRolls,
  useDeleteBulkRoll,
  useSettings,
  useUpdateSettings,
} from "../api/stock";
import { BulkMeter } from "../components/BulkMeter";
import { ErrorNote } from "../components/ErrorNote";
import { SpoolForm } from "../components/SpoolForm";
import { formatPounds } from "../lib/format";

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

function SpoolCard({ spool }: { spool: BulkRoll }) {
  const [editing, setEditing] = useState(false);
  const remove = useDeleteBulkRoll();
  if (editing) {
    return (
      <li>
        <SpoolForm
          spool={spool}
          onSaved={() => setEditing(false)}
          onCancel={() => setEditing(false)}
        />
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
  return (
    <>
      <h1>Bulk film</h1>
      <BulkMathsForm />
      <section aria-label="Bulk spools">
        <h2>Spools</h2>
        <p className="small">
          Buying a new spool is recorded on the <Link to="/purchases">Purchases</Link> screen.
          Edit or delete existing ones here.
        </p>
        {spools.isPending && <p>Loading…</p>}
        {spools.data && spools.data.length === 0 && <p>No bulk spools yet.</p>}
        <ul className="cards">
          {spools.data?.map((b) => <SpoolCard key={b.id} spool={b} />)}
        </ul>
      </section>
    </>
  );
}
