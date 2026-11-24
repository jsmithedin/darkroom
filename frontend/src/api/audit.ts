import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface AuditEvent {
  id: string;
  occurred_at: string;
  tool: string;
  entity_type: string;
  entity_id: string | null;
  summary: Record<string, unknown>;
  via: "pat" | "oauth";
  token_id: string | null;
  client_id: string | null;
  actor: string | null;
}

export interface AuditPage {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
}

export function useAuditEvents(offset: number, limit = 50) {
  return useQuery({
    queryKey: ["audit", offset, limit],
    queryFn: () => apiFetch<AuditPage>(`/api/audit-events?limit=${limit}&offset=${offset}`),
  });
}
