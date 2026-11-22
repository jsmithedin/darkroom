import { type RefItem, type RefKind, useRefItems } from "../api/reference";

interface Props {
  kind: RefKind;
  value: string;
  /** Called with the chosen id and, when one was chosen, the full item. */
  onChange: (id: string, item?: RefItem) => void;
  label: string;
  /** Text for the empty choice; leave out to require a value. */
  emptyLabel?: string;
  required?: boolean;
}

/**
 * Pick a reference item. Archived items are hidden, except the one currently selected,
 * so old records still display (and can be saved) with their archived camera or film.
 */
export function RefSelect({ kind, value, onChange, label, emptyLabel, required }: Props) {
  const { data = [], isPending, isError } = useRefItems(kind, { includeArchived: true });
  const visible = data.filter((i: RefItem) => !i.archived_at || i.id === value);

  return (
    <label>
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value, data.find((i) => i.id === e.target.value))}
        required={required}
        disabled={isPending || isError}
      >
        {(emptyLabel !== undefined || !value) && <option value="">{emptyLabel ?? "Choose…"}</option>}
        {visible.map((i) => (
          <option key={i.id} value={i.id}>
            {i.name}
            {i.archived_at ? " (archived)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
