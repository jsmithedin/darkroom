import { useState } from "react";
import { type AuditEvent, useAuditEvents } from "../api/audit";

const PAGE = 50;

function source(event: AuditEvent): string {
  if (event.via === "oauth") return `Connector: ${event.actor ?? event.client_id ?? "unknown"}`;
  return `Token: ${event.actor ?? "deleted token"}`;
}

function describe(event: AuditEvent): string {
  const s = event.summary as Record<string, unknown>;
  const name = (v: unknown) => (v && typeof v === "object" ? (v as { name?: string }).name : v);
  const parts = [name(s.film), name(s.format), name(s.camera), s.label, s.name, s.dev_date, s.occurred_on]
    .filter((p) => typeof p === "string" && p)
    .join(" · ");
  return parts || event.entity_type;
}

export function Audit() {
  const [offset, setOffset] = useState(0);
  const query = useAuditEvents(offset, PAGE);

  return (
    <section className="stack" aria-label="Activity">
      <h2>Activity</h2>
      <p>Changes made through the MCP connector or a token, newest first.</p>
      {query.isPending && <p>Loading…</p>}
      {query.isError && (
        <div role="alert" className="error">
          <p>Could not load activity.</p>
          <button type="button" onClick={() => query.refetch()}>
            Retry
          </button>
        </div>
      )}
      {query.data && query.data.items.length === 0 && <p>Nothing has been changed this way yet.</p>}
      {query.data && query.data.items.length > 0 && (
        <>
          <div className="panel" style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Action</th>
                  <th>Record</th>
                  <th>Made by</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((event) => (
                  <tr key={event.id}>
                    <td>{new Date(event.occurred_at).toLocaleString()}</td>
                    <td>{event.tool}</td>
                    <td>{describe(event)}</td>
                    <td>{source(event)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
            >
              Newer
            </button>
            <button
              type="button"
              disabled={offset + PAGE >= query.data.total}
              onClick={() => setOffset(offset + PAGE)}
            >
              Older
            </button>
          </div>
        </>
      )}
    </section>
  );
}
