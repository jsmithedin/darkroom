import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiFetch } from "./client";

export interface Ref {
  id: string;
  name: string;
}

export interface Roll {
  id: string;
  dev_date: string;
  camera: Ref;
  lens: Ref | null;
  format: Ref;
  film: Ref & { type: string; box_iso: number };
  ei: number;
  developer: Ref;
  dev_time_min: number | null;
  filter: Ref | null;
  subject: string | null;
  notes: string | null;
  source: "factory" | "bulk";
  counts_against_stock: boolean;
  year: number;
  month: number;
  film_type: string;
  box_iso: number;
  stops_vs_box: string;
}

/** What the form edits: every value is a string so inputs stay controlled while typing. */
export interface RollDraft {
  dev_date: string;
  camera_id: string;
  lens_id: string;
  format_id: string;
  film_id: string;
  ei: string;
  developer_id: string;
  dev_time_min: string;
  filter_id: string;
  subject: string;
  notes: string;
  source: "factory" | "bulk";
  counts_against_stock: boolean;
}

export interface RollPage {
  items: Roll[];
  total: number;
  limit: number;
  offset: number;
}

/** The request body for create and update. */
export function draftToBody(d: RollDraft) {
  const orNull = (s: string) => (s.trim() === "" ? null : s.trim());
  return {
    dev_date: d.dev_date,
    camera_id: d.camera_id,
    lens_id: d.lens_id || null,
    format_id: d.format_id,
    film_id: d.film_id,
    ei: Number(d.ei),
    developer_id: d.developer_id,
    dev_time_min: d.dev_time_min.trim() === "" ? null : Number(d.dev_time_min),
    filter_id: d.filter_id || null,
    subject: orNull(d.subject),
    notes: orNull(d.notes),
    source: d.source,
    counts_against_stock: d.counts_against_stock,
  };
}

export function rollToDraft(r: Roll): RollDraft {
  return {
    dev_date: r.dev_date,
    camera_id: r.camera.id,
    lens_id: r.lens?.id ?? "",
    format_id: r.format.id,
    film_id: r.film.id,
    ei: String(r.ei),
    developer_id: r.developer.id,
    dev_time_min: r.dev_time_min === null ? "" : String(r.dev_time_min),
    filter_id: r.filter?.id ?? "",
    subject: r.subject ?? "",
    notes: r.notes ?? "",
    source: r.source,
    counts_against_stock: r.counts_against_stock,
  };
}

export function useRolls(limit: number) {
  return useQuery({
    queryKey: ["rolls", { limit }],
    queryFn: () => apiFetch<RollPage>(`/api/rolls?limit=${limit}`),
  });
}

/** The camera's most recent roll, or null when it has none yet. */
export async function fetchLastRoll(cameraId: string): Promise<Roll | null> {
  try {
    return await apiFetch<Roll>(`/api/cameras/${cameraId}/last-roll`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

function useInvalidateRolls() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["rolls"] });
}

export function useCreateRoll() {
  const invalidate = useInvalidateRolls();
  return useMutation({
    mutationFn: (d: RollDraft) =>
      apiFetch<Roll>("/api/rolls", { method: "POST", body: JSON.stringify(draftToBody(d)) }),
    onSuccess: invalidate,
  });
}

export function useUpdateRoll(id: string) {
  const invalidate = useInvalidateRolls();
  return useMutation({
    mutationFn: (d: RollDraft) =>
      apiFetch<Roll>(`/api/rolls/${id}`, { method: "PATCH", body: JSON.stringify(draftToBody(d)) }),
    onSuccess: invalidate,
  });
}

export function useDeleteRoll() {
  const invalidate = useInvalidateRolls();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/api/rolls/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}
