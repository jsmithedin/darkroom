import { formatMetres } from "../lib/format";

interface Props {
  left_mm: number;
  length_mm: number;
  exposures_left: number;
}

/** How much of a bulk spool is left. An overdrawn spool shows the shortfall instead. */
export function BulkMeter({ left_mm, length_mm, exposures_left }: Props) {
  const fraction = length_mm > 0 ? Math.min(1, Math.max(0, left_mm / length_mm)) : 0;
  const overdrawn = left_mm < 0;
  return (
    <div className="bulk-meter">
      <div
        className="meter"
        role="meter"
        aria-label="Film left on spool"
        aria-valuemin={0}
        aria-valuemax={length_mm}
        aria-valuenow={Math.max(0, left_mm)}
      >
        <div className="meter-fill" style={{ width: `${Math.round(fraction * 100)}%` }} />
      </div>
      <div className="small">
        {overdrawn
          ? `Overdrawn by ${formatMetres(-left_mm)}`
          : `${formatMetres(left_mm)} left of ${formatMetres(length_mm)}`}
        {" · "}
        {exposures_left} exposures left
      </div>
    </div>
  );
}
