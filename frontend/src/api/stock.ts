import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiFetch } from "./client";

export type FilmType = "bw" | "colour" | "slide";
export type MovementKind = "purchase" | "bulk_load" | "given_away" | "adjustment" | "opening";

export interface FilmRef {
  id: string;
  name: string;
  type: FilmType;
}

export interface FormatRef {
  id: string;
  name: string;
}

export interface StockRow {
  film: FilmRef;
  format: FormatRef;
  rolls: number;
}

export interface Movement {
  id: string;
  kind: MovementKind;
  film: FilmRef;
  format: FormatRef;
  occurred_on: string;
  rolls: number;
  notes: string | null;
  cost_pence: number | null;
  supplier: string | null;
  bulk_roll_id: string | null;
  exposures_per_cassette: number | null;
  metres_mm: number | null;
  counted_to: number | null;
}

export interface BulkRoll {
  id: string;
  label: string;
  film: FilmRef;
  length_mm: number;
  cost_pence: number | null;
  supplier: string | null;
  bought_on: string | null;
  used_before_mm: number;
  finished: boolean;
  notes: string | null;
  cassettes_loaded: number;
  used_mm: number;
  left_mm: number;
  exposures_left: number;
  cost_per_36_pence: number | null;
}

export interface BulkRollInput {
  label: string;
  film_id: string;
  length_mm: number;
  cost_pence: number | null;
  supplier: string | null;
  bought_on: string | null;
  used_before_mm: number;
  finished: boolean;
  notes: string | null;
}

export interface AppSettings {
  leader_mm: number;
  frame_pitch_mm: number;
  timezone: string;
}

export type NewMovement =
  | {
      kind: "purchase";
      film_id: string;
      format_id: string;
      occurred_on: string;
      rolls: number;
      cost_pence: number;
      supplier: string | null;
      notes: string | null;
    }
  | {
      kind: "bulk_load";
      bulk_roll_id: string;
      occurred_on: string;
      rolls: number;
      exposures_per_cassette: number;
      notes: string | null;
    }
  | {
      kind: "given_away";
      film_id: string;
      format_id: string;
      occurred_on: string;
      rolls: number; // negative
      notes: string | null;
    };

export interface NewAdjustment {
  film_id: string;
  format_id: string;
  counted: number;
  occurred_on: string;
  notes?: string | null;
}

/** Details of a 409 "not enough stock", so the UI can offer a purchase or a recount. */
export interface InsufficientStock {
  film_id: string;
  format_id: string;
  film: string;
  format: string;
}

export function insufficientStock(error: unknown): InsufficientStock | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const body = error.body as Partial<InsufficientStock> & { code?: string };
  if (body?.code !== "insufficient_stock" || !body.film_id || !body.format_id) return null;
  return {
    film_id: body.film_id,
    format_id: body.format_id,
    film: body.film ?? "",
    format: body.format ?? "",
  };
}

export function useStock(includeZero: boolean) {
  return useQuery({
    queryKey: ["stock", { includeZero }],
    queryFn: () => apiFetch<StockRow[]>(`/api/stock${includeZero ? "?include_zero=true" : ""}`),
  });
}

export function useMovements(limit: number) {
  return useQuery({
    queryKey: ["movements", { limit }],
    queryFn: () =>
      apiFetch<{ items: Movement[]; total: number }>(`/api/stock-movements?limit=${limit}`),
  });
}

export function useBulkRolls(opts: { includeFinished: boolean }) {
  return useQuery({
    queryKey: ["bulk", { includeFinished: opts.includeFinished }],
    queryFn: () =>
      apiFetch<BulkRoll[]>(`/api/bulk-rolls?include_finished=${opts.includeFinished}`),
  });
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => apiFetch<AppSettings>("/api/settings") });
}

/** Anything that changes stock or bulk figures refreshes everything that shows them. */
function useInvalidateStock() {
  const qc = useQueryClient();
  return () =>
    Promise.all(
      ["stock", "movements", "bulk"].map((key) => qc.invalidateQueries({ queryKey: [key] })),
    );
}

export function useCreateMovement() {
  const invalidate = useInvalidateStock();
  return useMutation({
    mutationFn: (body: NewMovement) =>
      apiFetch<Movement>("/api/stock-movements", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useCreateAdjustment() {
  const invalidate = useInvalidateStock();
  return useMutation({
    mutationFn: (body: NewAdjustment) =>
      apiFetch<Movement>("/api/stock-adjustments", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useUpdateMovement() {
  const invalidate = useInvalidateStock();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
      apiFetch<Movement>(`/api/stock-movements/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteMovement() {
  const invalidate = useInvalidateStock();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/api/stock-movements/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useSaveBulkRoll(id?: string) {
  const invalidate = useInvalidateStock();
  return useMutation({
    mutationFn: (body: BulkRollInput) =>
      apiFetch<BulkRoll>(id ? `/api/bulk-rolls/${id}` : "/api/bulk-rolls", {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteBulkRoll() {
  const invalidate = useInvalidateStock();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/api/bulk-rolls/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<AppSettings>) =>
      apiFetch<AppSettings>("/api/settings", { method: "PATCH", body: JSON.stringify(body) }),
    // leader and pitch change the live exposure counts
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: ["settings"] }),
      qc.invalidateQueries({ queryKey: ["bulk"] }),
    ]),
  });
}
