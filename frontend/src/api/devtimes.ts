import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { FilmRef } from "./stock";

export interface NameRef {
  id: string;
  name: string;
}

export interface DevTimeRef {
  id: string;
  film: FilmRef;
  ei: number;
  developer: NameRef;
  minutes: number;
  notes: string | null;
}

export interface DevTimeGroup {
  film: FilmRef;
  ei: number;
  developer: NameRef;
  entries: { roll_id: string; dev_date: string; minutes: number }[];
  reference: DevTimeRef | null;
}

export interface DevTimeFilters {
  film?: string;
  developer?: string;
  ei?: string;
}

export interface DevTimeRefInput {
  film_id: string;
  ei: number;
  developer_id: string;
  minutes: number;
  notes: string | null;
}

export function useDevTimes(filters: DevTimeFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return useQuery({
    queryKey: ["dev-times", filters],
    queryFn: () => apiFetch<DevTimeGroup[]>(`/api/dev-times${query ? `?${query}` : ""}`),
  });
}

function useRefWrite<V>(call: (v: V) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: () => client.invalidateQueries({ queryKey: ["dev-times"] }),
  });
}

export const useCreateDevTimeRef = () =>
  useRefWrite((body: DevTimeRefInput) =>
    apiFetch("/api/dev-time-refs", { method: "POST", body: JSON.stringify(body) }),
  );

export const useUpdateDevTimeRef = () =>
  useRefWrite(({ id, ...body }: { id: string } & Partial<DevTimeRefInput>) =>
    apiFetch(`/api/dev-time-refs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  );

export const useDeleteDevTimeRef = () =>
  useRefWrite((id: string) => apiFetch(`/api/dev-time-refs/${id}`, { method: "DELETE" }));
