import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface MonthPoint {
  month: number;
  count: number;
  cumulative: number | null;
}

export interface BreakdownRow {
  id: string | null;
  name: string;
  count: number;
}

export interface Stats {
  year: number;
  monthly: MonthPoint[];
  previous_monthly: MonthPoint[];
  ytd: { this_year: number; last_year_to_date: number };
  breakdowns: Record<string, BreakdownRow[]>;
}

export interface CameraIdle {
  camera_id: string;
  name: string;
  last_used: string | null;
}

export interface SpendYear {
  year: number;
  purchases_pence: number;
  bulk_pence: number;
  rolls: number;
  cost_per_roll_pence: number | null;
}

/** `year` undefined asks the server for the current year in the configured timezone. */
export function useStats(year: number | undefined) {
  return useQuery({
    queryKey: ["stats", year ?? "current"],
    queryFn: () => apiFetch<Stats>(`/api/stats${year ? `?year=${year}` : ""}`),
  });
}

export function useCameraIdle() {
  return useQuery({
    queryKey: ["stats", "camera-idle"],
    queryFn: () => apiFetch<CameraIdle[]>("/api/stats/camera-idle"),
  });
}

export function useSpend() {
  return useQuery({
    queryKey: ["stats", "spend"],
    queryFn: () => apiFetch<SpendYear[]>("/api/stats/spend"),
  });
}
