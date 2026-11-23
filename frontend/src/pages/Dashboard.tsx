import { useState } from "react";
import { Link } from "react-router-dom";
import { useCameraIdle, useSpend, useStats } from "../api/stats";
import { Breakdown } from "../components/Breakdown";
import { MonthlyChart } from "../components/MonthlyChart";
import { formatPounds } from "../lib/format";

const BREAKDOWNS: { key: string; title: string }[] = [
  { key: "camera", title: "Cameras" },
  { key: "film", title: "Films" },
  { key: "developer", title: "Developers" },
  { key: "format", title: "Formats" },
  { key: "type", title: "Film type" },
  { key: "source", title: "Source" },
];

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function Dashboard() {
  // undefined means "the current year", as the server sees it in the configured timezone.
  const [chosen, setChosen] = useState<number | undefined>(undefined);
  const stats = useStats(chosen);
  const spend = useSpend();
  const idle = useCameraIdle();

  if (stats.isPending) return <p>Loading…</p>;
  if (stats.isError) return <p role="alert">Could not load the statistics.</p>;
  const s = stats.data;

  const years = new Set<number>([s.year, ...(spend.data ?? []).map((y) => y.year)]);
  const options = [...years].sort((a, b) => b - a);
  const diff = s.ytd.this_year - s.ytd.last_year_to_date;
  const total = s.monthly.reduce((n, m) => n + m.count, 0);

  return (
    <div className="stack">
      <h2>Dashboard</h2>
      <label>
        Year
        <select value={s.year} onChange={(e) => setChosen(Number(e.target.value))}>
          {options.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </label>

      <section className="panel" aria-label="Year to date">
        <h3>
          {plural(s.ytd.this_year, "roll")} in {s.year}
        </h3>
        <p>
          {plural(s.ytd.last_year_to_date, "roll")} by the same date in {s.year - 1}
          {diff !== 0 && ` (${diff > 0 ? "+" : ""}${diff})`}.
        </p>
        <p className="muted">{plural(total, "roll")} over the whole year.</p>
      </section>

      <section className="panel" aria-label="Rolls per month">
        <h3>Rolls per month</h3>
        <MonthlyChart data={s.monthly} label={`Rolls per month in ${s.year}`} />
      </section>

      {BREAKDOWNS.map(({ key, title }) => (
        <Breakdown key={key} title={title} rows={s.breakdowns[key] ?? []} />
      ))}

      <section className="panel" aria-label="Cameras not used lately">
        <h3>Longest since last used</h3>
        {idle.data?.length === 0 && <p className="muted">No cameras yet.</p>}
        <ul className="plain">
          {idle.data?.slice(0, 5).map((c) => (
            <li key={c.camera_id}>
              {c.name}{" "}
              <span className="muted">
                {c.last_used
                  ? new Date(c.last_used).toLocaleDateString(undefined, { timeZone: "UTC" })
                  : "never used"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-label="Spend">
        <h3>Spend</h3>
        <table>
          <thead>
            <tr>
              <th>Year</th>
              <th>Film bought</th>
              <th>Bulk</th>
              <th>Rolls</th>
              <th>Per roll</th>
            </tr>
          </thead>
          <tbody>
            {spend.data?.map((y) => (
              <tr key={y.year}>
                <td>{y.year}</td>
                <td>{formatPounds(y.purchases_pence)}</td>
                <td>{formatPounds(y.bulk_pence)}</td>
                <td>{y.rolls}</td>
                <td>{y.cost_per_roll_pence === null ? "–" : formatPounds(y.cost_per_roll_pence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small">
          Per roll is spend divided by rolls developed that year. Prices come from{" "}
          <Link to="/purchases">purchases</Link> and priced bulk spools.
        </p>
      </section>
    </div>
  );
}
