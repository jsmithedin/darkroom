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
import { useEffect, useRef } from "react";
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

/** Rolls per month as bars with the running total as a line; follows the light/dark theme. */
export function MonthlyChart({ data, label }: { data: MonthPoint[]; label: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvas.current) return;
    const fg = css("--fg", "#1c1917");
    const border = css("--border", "#d6d3d1");
    const accent = css("--accent", "#b45309");
    const chart = new Chart(canvas.current, {
      type: "bar",
      data: {
        labels: MONTHS,
        datasets: [
          {
            type: "bar",
            label: "Rolls",
            data: data.map((p) => p.count),
            backgroundColor: accent,
          },
          {
            type: "line",
            label: "Running total",
            data: data.map((p) => p.cumulative),
            borderColor: fg,
            backgroundColor: fg,
            spanGaps: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: fg } } },
        scales: {
          x: { ticks: { color: fg }, grid: { color: border } },
          y: { beginAtZero: true, ticks: { color: fg, precision: 0 }, grid: { color: border } },
        },
      },
    });
    return () => chart.destroy();
  }, [data]);

  return (
    <div className="chart">
      <canvas ref={canvas} role="img" aria-label={label} />
    </div>
  );
}
