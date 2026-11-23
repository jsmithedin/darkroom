import { useState } from "react";
import { Link } from "react-router-dom";
import { type Stats, useCameraIdle, useSpend, useStats } from "../api/stats";
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

// The stats endpoint accepts these years; the spend list is not bounded the same way.
const MIN_YEAR = 1900;
const MAX_YEAR = 2200;

function Failed({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <p role="alert" className="error">
      Could not load {what}.{" "}
      <button type="button" className="link" onClick={onRetry}>
        Try again
      </button>
    </p>
  );
}

function IdlePanel() {
  const idle = useCameraIdle();
  return (
    <section className="panel" aria-label="Cameras not used lately">
      <h3>Longest since last used</h3>
      {idle.isPending && <p>Loading…</p>}
      {idle.isError && <Failed what="the cameras" onRetry={() => void idle.refetch()} />}
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
  );
}

function SpendPanel({ spend }: { spend: ReturnType<typeof useSpend> }) {
  return (
    <section className="panel" aria-label="Spend">
      <h3>Spend</h3>
      {spend.isPending && <p>Loading…</p>}
      {spend.isError && <Failed what="the spend figures" onRetry={() => void spend.refetch()} />}
      {spend.data && (
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
            {spend.data.map((y) => (
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
      )}
      <p className="small">
        Per roll is spend divided by rolls developed that year. Prices come from{" "}
        <Link to="/purchases">purchases</Link> and priced bulk spools.
      </p>
    </section>
  );
}

export function Dashboard() {
  // undefined means "the current year", as the server sees it in the configured timezone.
  const [chosen, setChosen] = useState<number | undefined>(undefined);
  const stats = useStats(chosen);
  const spend = useSpend();
  const s = stats.data;

  // The selector stays put whatever happens to the stats request, so a bad year can be left.
  const years = new Set<number>((spend.data ?? []).map((y) => y.year));
  if (s) years.add(s.year);
  if (chosen !== undefined) years.add(chosen);
  const options = [...years].filter((y) => y >= MIN_YEAR && y <= MAX_YEAR).sort((a, b) => b - a);
  const shown = chosen ?? s?.year;

  return (
    <div className="stack">
      <h2>Dashboard</h2>
      <label>
        Year
        <select
          value={shown ?? ""}
          onChange={(e) => setChosen(Number(e.target.value))}
          disabled={options.length === 0}
        >
          {options.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </label>

      {stats.isPending && <p>Loading…</p>}
      {stats.isError && <Failed what="the statistics" onRetry={() => void stats.refetch()} />}
      {s && <YearResults s={s} />}

      <IdlePanel />
      <SpendPanel spend={spend} />
    </div>
  );
}

function YearResults({ s }: { s: Stats }) {
  const diff = s.ytd.this_year - s.ytd.last_year_to_date;
  const total = s.monthly.reduce((n, m) => n + m.count, 0);
  return (
    <>
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
        <MonthlyChart
          current={{ label: String(s.year), points: s.monthly }}
          previous={{ label: String(s.year - 1), points: s.previous_monthly }}
          label={`Rolls per month in ${s.year}, compared with ${s.year - 1}`}
        />
      </section>

      {BREAKDOWNS.map(({ key, title }) => (
        <Breakdown key={key} title={title} rows={s.breakdowns[key] ?? []} />
      ))}
    </>
  );
}
