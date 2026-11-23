import { type FormEvent, useState } from "react";
import {
  type DevTimeGroup,
  useCreateDevTimeRef,
  useDeleteDevTimeRef,
  useDevTimes,
  useUpdateDevTimeRef,
} from "../api/devtimes";
import { ErrorNote } from "../components/ErrorNote";
import { RefSelect } from "../components/RefSelect";

function RefForm({ onDone }: { onDone: () => void }) {
  const create = useCreateDevTimeRef();
  const [filmId, setFilmId] = useState("");
  const [developerId, setDeveloperId] = useState("");
  const [ei, setEi] = useState("");
  const [minutes, setMinutes] = useState("");
  const [notes, setNotes] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        film_id: filmId,
        developer_id: developerId,
        ei: Number(ei),
        minutes: Number(minutes),
        notes: notes.trim() || null,
      },
      { onSuccess: onDone },
    );
  }

  return (
    <form onSubmit={submit} className="stack panel" aria-label="Add reference time">
      <h3>Add a reference time</h3>
      <RefSelect kind="films" label="Film" value={filmId} onChange={setFilmId} required />
      <label>
        EI
        <input inputMode="decimal" value={ei} onChange={(e) => setEi(e.target.value)} required />
      </label>
      <RefSelect
        kind="developers"
        label="Developer"
        value={developerId}
        onChange={setDeveloperId}
        required
      />
      <label>
        Minutes
        <input
          inputMode="decimal"
          value={minutes}
          onChange={(e) => setMinutes(e.target.value)}
          required
        />
      </label>
      <label>
        Notes
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <ErrorNote error={create.error} />
      <button type="submit" disabled={create.isPending}>
        Save reference
      </button>
    </form>
  );
}

function Reference({ group }: { group: DevTimeGroup }) {
  const update = useUpdateDevTimeRef();
  const remove = useDeleteDevTimeRef();
  const [editing, setEditing] = useState(false);
  const [minutes, setMinutes] = useState("");
  const ref = group.reference;
  if (!ref) return <p className="muted">No reference time.</p>;

  if (editing) {
    return (
      <form
        className="row"
        aria-label="Edit reference time"
        onSubmit={(e) => {
          e.preventDefault();
          update.mutate(
            { id: ref.id, minutes: Number(minutes) },
            { onSuccess: () => setEditing(false) },
          );
        }}
      >
        <label>
          Minutes
          <input
            inputMode="decimal"
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
            required
          />
        </label>
        <button type="submit">Save</button>
        <button type="button" className="link" onClick={() => setEditing(false)}>
          Cancel
        </button>
        <ErrorNote error={update.error} />
      </form>
    );
  }

  return (
    <p className="row">
      <span>
        Reference: <strong>{ref.minutes} min</strong>
        {ref.notes ? ` (${ref.notes})` : ""}
      </span>
      <button
        type="button"
        className="link"
        onClick={() => {
          setMinutes(String(ref.minutes));
          setEditing(true);
        }}
      >
        Edit
      </button>
      <button
        type="button"
        className="link"
        onClick={() => {
          if (window.confirm("Delete this reference time?")) remove.mutate(ref.id);
        }}
      >
        Delete
      </button>
    </p>
  );
}

export function DevTimes() {
  const [film, setFilm] = useState("");
  const [developer, setDeveloper] = useState("");
  const [ei, setEi] = useState("");
  const [adding, setAdding] = useState(false);
  const times = useDevTimes({ film, developer, ei: ei.trim() });

  return (
    <div className="stack">
      <h2>Dev times</h2>
      <form className="row" aria-label="Filter dev times" onSubmit={(e) => e.preventDefault()}>
        <RefSelect kind="films" label="Film" value={film} onChange={setFilm} emptyLabel="Any" />
        <label>
          EI
          <input inputMode="decimal" value={ei} onChange={(e) => setEi(e.target.value)} />
        </label>
        <RefSelect
          kind="developers"
          label="Developer"
          value={developer}
          onChange={setDeveloper}
          emptyLabel="Any"
        />
      </form>

      {adding ? (
        <RefForm onDone={() => setAdding(false)} />
      ) : (
        <button type="button" onClick={() => setAdding(true)}>
          Add a reference time
        </button>
      )}

      {times.isPending && <p>Loading…</p>}
      {times.isError && <p role="alert">Could not load dev times.</p>}
      {times.data?.length === 0 && <p>No dev times yet.</p>}
      {times.data?.map((g) => (
        <section
          key={`${g.film.id}:${g.ei}:${g.developer.id}`}
          className="panel"
          aria-label={`${g.film.name} at EI ${g.ei} in ${g.developer.name}`}
        >
          <h3>
            {g.film.name} · EI {g.ei} · {g.developer.name}
          </h3>
          <Reference group={g} />
          {g.entries.length === 0 ? (
            <p className="muted">No logged times.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Minutes</th>
                </tr>
              </thead>
              <tbody>
                {g.entries.map((e) => (
                  <tr key={e.roll_id}>
                    <td>{new Date(e.dev_date).toLocaleDateString()}</td>
                    <td>{e.minutes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ))}
    </div>
  );
}
