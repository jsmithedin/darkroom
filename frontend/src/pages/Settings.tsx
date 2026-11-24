import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { apiFetch } from "../api/client";
import {
  type CreatedToken,
  type Scope,
  type Token,
  useCreateToken,
  useRevokeToken,
  useTokens,
} from "../api/hooks";

const EXPIRY_OPTIONS = [
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "1 year", days: 365 },
  { label: "Never", days: 0 },
];

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : "never";
}

function status(t: Token): string {
  if (t.revoked_at) return "revoked";
  if (t.expires_at && new Date(t.expires_at) <= new Date()) return "expired";
  return "active";
}

function NewTokenForm({ onCreated }: { onCreated: (t: CreatedToken) => void }) {
  const create = useCreateToken();
  const [name, setName] = useState("");
  const [write, setWrite] = useState(false);
  const [days, setDays] = useState(90);

  function submit(e: FormEvent) {
    e.preventDefault();
    const scopes: Scope[] = write ? ["films:write"] : ["films:read"];
    const expires_at = days ? new Date(Date.now() + days * 86_400_000).toISOString() : null;
    create.mutate(
      { name: name.trim(), scopes, expires_at },
      {
        onSuccess: (t) => {
          setName("");
          onCreated(t);
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="stack">
      <label>
        Name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Claude Code"
          required
          maxLength={100}
        />
      </label>
      <label className="check">
        <input type="checkbox" checked={write} onChange={(e) => setWrite(e.target.checked)} />
        Allow changes (otherwise read-only)
      </label>
      <label>
        Expires
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {EXPIRY_OPTIONS.map((o) => (
            <option key={o.label} value={o.days}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className="button primary" disabled={create.isPending || !name.trim()}>
        Create token
      </button>
      {create.isError && <p role="alert" className="error">{create.error.message}</p>}
    </form>
  );
}

function RevealedToken({ token, onDismiss }: { token: CreatedToken; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <section className="reveal" aria-label="New token">
      <p>
        <strong>Copy this token now.</strong> It will not be shown again.
      </p>
      <code className="secret">{token.token}</code>
      <div className="row">
        <button
          type="button"
          className="button"
          onClick={async () => {
            await navigator.clipboard?.writeText(token.token);
            setCopied(true);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" className="button" onClick={onDismiss}>
          I have saved it
        </button>
      </div>
    </section>
  );
}

function TokenList() {
  const tokens = useTokens();
  const revoke = useRevokeToken();

  if (tokens.isPending) return <p>Loading…</p>;
  if (tokens.isError) return <p role="alert" className="error">{tokens.error.message}</p>;
  if (tokens.data.length === 0) return <p>No tokens yet.</p>;

  return (
    <ul className="cards">
      {tokens.data.map((t) => (
        <li key={t.id} className={status(t) === "active" ? "" : "muted"}>
          <div className="row spread">
            <strong>{t.name}</strong>
            <span className="badge">{status(t)}</span>
          </div>
          <div>
            <code>{t.prefix}…</code> · {t.scopes.includes("films:write") ? "read and write" : "read only"}
          </div>
          <div className="small">
            Created {formatDate(t.created_at)} · Expires {formatDate(t.expires_at)} · Last used{" "}
            {formatDate(t.last_used_at)}
          </div>
          {status(t) === "active" && (
            <button
              type="button"
              className="button danger"
              disabled={revoke.isPending}
              onClick={() => {
                if (window.confirm(`Revoke "${t.name}"? Anything using it will stop working.`)) {
                  revoke.mutate(t.id);
                }
              }}
            >
              Revoke
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

function ExportSection() {
  const tables = useQuery({
    queryKey: ["export", "tables"],
    queryFn: () => apiFetch<string[]>("/api/export"),
  });
  return (
    <section aria-labelledby="export-heading">
      <h2 id="export-heading">Export</h2>
      <p>
        Download any table as a CSV file. It is your whole log in plain text, for spreadsheets or
        a backup you can read.
      </p>
      {tables.isPending && <p>Loading…</p>}
      {tables.isError && (
        <p role="alert" className="error">
          {tables.error.message}
        </p>
      )}
      {tables.data && (
        <ul className="cards">
          {tables.data.map((table) => (
            <li key={table}>
              <a className="button" href={`/api/export/${table}.csv`} download>
                {table.replaceAll("_", " ")}.csv
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Settings() {
  const [revealed, setRevealed] = useState<CreatedToken | null>(null);
  return (
    <>
      <h1>Settings</h1>
      <h2>Access tokens</h2>
      <p>
        Tokens let scripts and AI clients use your data. Treat them like passwords.
      </p>
      {revealed && <RevealedToken token={revealed} onDismiss={() => setRevealed(null)} />}
      <NewTokenForm onCreated={setRevealed} />
      <TokenList />
      <ExportSection />
    </>
  );
}
