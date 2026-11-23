import type { BreakdownRow } from "../api/stats";

/** Horizontal bars in CSS; the longest bar is full width and the rest scale to it. */
export function Breakdown({ title, rows }: { title: string; rows: BreakdownRow[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <section className="panel" aria-label={title}>
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p className="muted">No rolls.</p>
      ) : (
        <ul className="bars">
          {rows.map((r) => (
            <li key={r.id ?? r.name}>
              <span className="bar-label">{r.name}</span>
              <span className="bar-track">
                <span
                  className="bar-fill"
                  role="presentation"
                  data-testid="bar"
                  style={{ width: `${(r.count / max) * 100}%` }}
                />
              </span>
              <span className="bar-count">{r.count}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
