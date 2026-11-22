import { type FormEvent, useState } from "react";
import {
  FILM_TYPE_LABELS,
  type FilmType,
  type RefInput,
  type RefItem,
  type RefKind,
  useArchiveRef,
  useCreateRef,
  useRefItems,
  useUpdateRef,
} from "../api/reference";

function RefForm({
  kind,
  initial,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  kind: RefKind;
  initial?: RefItem;
  submitLabel: string;
  pending: boolean;
  error?: string;
  onSubmit: (values: RefInput) => void;
  onCancel?: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [fixedLens, setFixedLens] = useState(initial?.fixed_lens ?? false);
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [type, setType] = useState<FilmType>(initial?.type ?? "bw");
  const [boxIso, setBoxIso] = useState(initial?.box_iso ? String(initial.box_iso) : "");

  function submit(e: FormEvent) {
    e.preventDefault();
    const values: RefInput = { name: name.trim() };
    if (kind === "cameras") {
      values.fixed_lens = fixedLens;
      values.notes = notes.trim() || null;
    }
    if (kind === "films") {
      values.type = type;
      values.box_iso = Number(boxIso);
    }
    onSubmit(values);
  }

  return (
    <form onSubmit={submit} className="stack">
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} />
      </label>
      {kind === "cameras" && (
        <>
          <label className="check">
            <input
              type="checkbox"
              checked={fixedLens}
              onChange={(e) => setFixedLens(e.target.checked)}
            />
            Fixed lens
          </label>
          <label>
            Notes
            <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} />
          </label>
        </>
      )}
      {kind === "films" && (
        <>
          <label>
            Type
            <select value={type} onChange={(e) => setType(e.target.value as FilmType)}>
              {(Object.keys(FILM_TYPE_LABELS) as FilmType[]).map((t) => (
                <option key={t} value={t}>
                  {FILM_TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Box ISO
            <input
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={boxIso}
              onChange={(e) => setBoxIso(e.target.value)}
              required
            />
          </label>
        </>
      )}
      <div className="row">
        <button type="submit" className="button primary" disabled={pending || !name.trim()}>
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </form>
  );
}

function describe(kind: RefKind, item: RefItem): string {
  if (kind === "cameras") {
    return [item.fixed_lens ? "Fixed lens" : "", item.notes ?? ""].filter(Boolean).join(" · ");
  }
  if (kind === "films" && item.type) {
    return `${FILM_TYPE_LABELS[item.type]} · ISO ${item.box_iso}`;
  }
  return "";
}

function Row({ kind, item }: { kind: RefKind; item: RefItem }) {
  const [editing, setEditing] = useState(false);
  const update = useUpdateRef(kind);
  const archive = useArchiveRef(kind);
  const extra = describe(kind, item);

  if (editing) {
    return (
      <li>
        <RefForm
          kind={kind}
          initial={item}
          submitLabel="Save"
          pending={update.isPending}
          error={update.error?.message}
          onCancel={() => setEditing(false)}
          onSubmit={(values) =>
            update.mutate({ id: item.id, ...values }, { onSuccess: () => setEditing(false) })
          }
        />
      </li>
    );
  }

  return (
    <li className={item.archived_at ? "muted" : ""}>
      <div className="row spread">
        <strong>{item.name}</strong>
        {item.archived_at && <span className="badge">archived</span>}
      </div>
      {extra && <div className="small">{extra}</div>}
      <div className="row">
        <button type="button" className="button" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button
          type="button"
          className="button"
          disabled={archive.isPending}
          onClick={() => archive.mutate({ id: item.id, archive: !item.archived_at })}
        >
          {item.archived_at ? "Unarchive" : "Archive"}
        </button>
      </div>
      {archive.isError && (
        <p role="alert" className="error">
          {archive.error.message}
        </p>
      )}
    </li>
  );
}

export function RefList({ kind, singular }: { kind: RefKind; singular: string }) {
  const [showArchived, setShowArchived] = useState(false);
  const [adding, setAdding] = useState(false);
  const items = useRefItems(kind, { includeArchived: showArchived });
  const create = useCreateRef(kind);

  return (
    <section>
      <div className="row spread">
        <label className="check">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          Show archived
        </label>
        {!adding && (
          <button type="button" className="button primary" onClick={() => setAdding(true)}>
            Add {singular}
          </button>
        )}
      </div>

      {adding && (
        <RefForm
          key={kind}
          kind={kind}
          submitLabel={`Add ${singular}`}
          pending={create.isPending}
          error={create.error?.message}
          onCancel={() => {
            create.reset();
            setAdding(false);
          }}
          onSubmit={(values) => create.mutate(values, { onSuccess: () => setAdding(false) })}
        />
      )}

      {items.isPending && <p>Loading…</p>}
      {items.isError && (
        <p role="alert" className="error">
          {items.error.message}
        </p>
      )}
      {items.data && items.data.length === 0 && <p>Nothing here yet.</p>}
      <ul className="cards">
        {items.data?.map((item) => <Row key={item.id} kind={kind} item={item} />)}
      </ul>
    </section>
  );
}
