import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface Me {
  email: string;
  name: string;
  csrf_token: string;
}

export type Scope = "films:read" | "films:write";

export interface Token {
  id: string;
  name: string;
  prefix: string;
  scopes: Scope[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface CreatedToken extends Token {
  token: string;
}

export interface NewToken {
  name: string;
  scopes: Scope[];
  expires_at: string | null;
}

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => apiFetch<Me>("/api/me"), retry: false });
}

export function useTokens() {
  return useQuery({ queryKey: ["tokens"], queryFn: () => apiFetch<Token[]>("/api/tokens") });
}

export function useCreateToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewToken) =>
      apiFetch<CreatedToken>("/api/tokens", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }),
  });
}

export function useRevokeToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/api/tokens/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      qc.clear();
      window.location.assign("/login");
    },
  });
}
