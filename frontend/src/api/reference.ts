import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type RefKind = "cameras" | "lenses" | "developers" | "filters" | "films" | "formats";
export type FilmType = "bw" | "colour" | "slide";

export const REF_KINDS: { kind: RefKind; label: string; singular: string }[] = [
  { kind: "cameras", label: "Cameras", singular: "camera" },
  { kind: "lenses", label: "Lenses", singular: "lens" },
  { kind: "films", label: "Films", singular: "film" },
  { kind: "developers", label: "Developers", singular: "developer" },
  { kind: "filters", label: "Filters", singular: "filter" },
  { kind: "formats", label: "Formats", singular: "format" },
];

export const FILM_TYPE_LABELS: Record<FilmType, string> = {
  bw: "Black and white",
  colour: "Colour",
  slide: "Slide",
};

export interface RefItem {
  id: string;
  name: string;
  archived_at: string | null;
  // cameras
  fixed_lens?: boolean;
  notes?: string | null;
  // films
  type?: FilmType;
  box_iso?: number;
}

/** Fields accepted when creating or editing an item (extras apply to cameras and films only). */
export interface RefInput {
  name?: string;
  fixed_lens?: boolean;
  notes?: string | null;
  type?: FilmType;
  box_iso?: number;
}

export function useRefItems(kind: RefKind, opts: { includeArchived?: boolean } = {}) {
  const includeArchived = opts.includeArchived ?? false;
  return useQuery({
    queryKey: ["ref", kind, includeArchived],
    queryFn: () =>
      apiFetch<RefItem[]>(`/api/${kind}${includeArchived ? "?include_archived=true" : ""}`),
  });
}

function useInvalidate(kind: RefKind) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["ref", kind] });
}

export function useCreateRef(kind: RefKind) {
  const invalidate = useInvalidate(kind);
  return useMutation({
    mutationFn: (body: RefInput) =>
      apiFetch<RefItem>(`/api/${kind}`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useUpdateRef(kind: RefKind) {
  const invalidate = useInvalidate(kind);
  return useMutation({
    mutationFn: ({ id, ...body }: RefInput & { id: string }) =>
      apiFetch<RefItem>(`/api/${kind}/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useArchiveRef(kind: RefKind) {
  const invalidate = useInvalidate(kind);
  return useMutation({
    mutationFn: ({ id, archive }: { id: string; archive: boolean }) =>
      apiFetch<RefItem>(`/api/${kind}/${id}/${archive ? "archive" : "unarchive"}`, {
        method: "POST",
      }),
    onSuccess: invalidate,
  });
}
