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

/** Bumps whenever the system light/dark preference changes, so the canvas colours can follow. */
function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query) return;
    const bump = () => setVersion((v) => v + 1);
    query.addEventListener("change", bump);
    return () => query.removeEventListener("change", bump);
  }, []);
  return version;
}

/**
 * Rolls per month as bars with the running total as a line, for the chosen year and the one
 * before it; follows the light/dark theme.
 */
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
  const theme = useThemeVersion();

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
        datasets: [
          {
            type: "bar",
            label: `${previous.label} rolls`,
            data: previous.points.map((p) => p.count),
            backgroundColor: muted,
          },
          {
            type: "bar",
            label: `${current.label} rolls`,
            data: current.points.map((p) => p.count),
            backgroundColor: accent,
          },
          {
            type: "line",
            label: `${previous.label} running total`,
            data: previous.points.map((p) => p.cumulative),
            borderColor: muted,
            backgroundColor: muted,
            borderDash: [6, 4],
            spanGaps: false,
          },
          {
            type: "line",
            label: `${current.label} running total`,
            data: current.points.map((p) => p.cumulative),
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
  }, [current, previous, theme]);

  return (
    <div className="chart">
      <canvas ref={canvas} role="img" aria-label={label} />
    </div>
  );
}
