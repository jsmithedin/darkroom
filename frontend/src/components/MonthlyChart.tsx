import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from "chart.js";
import { useEffect, useRef, useState } from "react";
import type { MonthPoint } from "../api/stats";

// Register only what is used, so the bundle stays small.
Chart.register(
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Legend,
  Tooltip,
);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function css(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export interface Series {
  label: string;
  points: MonthPoint[];
}

export function MonthlyChart({
  current,
  previous,
  label,
}: {
  current: Series;
  previous: Series;
  label: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [cumulative, setCumulative] = useState(false);

  useEffect(() => {
    if (!canvas.current) return;
    const fg = css("--fg", "#1c1917");
    const border = css("--border", "#d6d3d1");
    const accent = css("--accent", "#b45309");
    const muted = css("--muted", "#6b6560");
    const chart = new Chart(canvas.current, {
      type: "bar",
      data: {
        labels: MONTHS,
        datasets: [current, previous].map((series, index) => ({
          type: cumulative ? "line" : "bar",
          label: series.label,
          data: series.points.map((point) => cumulative ? point.cumulative : point.count),
          backgroundColor: index === 0 ? accent : muted,
          borderColor: index === 0 ? accent : muted,
          borderDash: index === 1 ? [5, 4] : [],
          borderRadius: 2,
          maxBarThickness: 22,
          pointRadius: 3,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { color: fg, boxWidth: 12, padding: 16 } } },
        scales: {
          x: { ticks: { color: fg }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: fg, precision: 0 }, grid: { color: border } },
        },
      },
    });
    return () => chart.destroy();
  }, [current, previous, cumulative]);

  return (
    <>
      <div className="chart-modes" role="group" aria-label="Chart view">
        <button type="button" aria-pressed={!cumulative} onClick={() => setCumulative(false)}>Monthly</button>
        <button type="button" aria-pressed={cumulative} onClick={() => setCumulative(true)}>Running total</button>
      </div>
      <div className="chart">
      <canvas ref={canvas} role="img" aria-label={cumulative ? `Running totals for ${current.label} and ${previous.label}` : label} />
      </div>
    </>
  );
}
