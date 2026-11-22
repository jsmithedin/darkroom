import { useState } from "react";
import { type Roll, useRolls } from "../api/rolls";
import { RollForm } from "./RollForm";

const PAGE = 20;

function RollCard({ roll }: { roll: Roll }) {
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <li>
        <RollForm roll={roll} onDone={() => setEditing(false)} />
      </li>
    );
  }
  return (
    <li>
      <div className="row spread">
        <strong>{roll.film.name}</strong>
        <span className="small">{roll.dev_date}</span>
      </div>
      <div>
        {roll.camera.name}
        {roll.lens ? ` · ${roll.lens.name}` : ""} · {roll.format.name}
      </div>
      <div className="small">
        EI {roll.ei} ({roll.stops_vs_box} stops) · {roll.developer.name}
        {roll.dev_time_min !== null ? ` · ${roll.dev_time_min} min` : ""}
        {roll.filter ? ` · ${roll.filter.name}` : ""}
      </div>
      {roll.subject && <div>{roll.subject}</div>}
      {roll.notes && <div className="small">{roll.notes}</div>}
      <div className="row">
        <button type="button" className="button" onClick={() => setEditing(true)}>
          Edit
        </button>
      </div>
    </li>
  );
}

export function RecentRolls() {
  const [limit, setLimit] = useState(PAGE);
  const rolls = useRolls(limit);

  return (
    <section aria-label="Recent rolls">
      <h2>Recent rolls</h2>
      {rolls.isPending && <p>Loading…</p>}
      {rolls.isError && (
        <p role="alert" className="error">
          {rolls.error.message}
        </p>
      )}
      {rolls.data && rolls.data.items.length === 0 && <p>No rolls logged yet.</p>}
      <ul className="cards">
        {rolls.data?.items.map((r) => <RollCard key={r.id} roll={r} />)}
      </ul>
      {rolls.data && rolls.data.total > rolls.data.items.length && (
        <button type="button" className="button" onClick={() => setLimit((l) => l + PAGE)}>
          Show more ({rolls.data.total - rolls.data.items.length} older)
        </button>
      )}
    </section>
  );
}
