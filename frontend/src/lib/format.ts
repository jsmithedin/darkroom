/** Millimetres as metres for display: 7300 -> "7.3 m", 17000 -> "17 m". */
export function formatMetres(mm: number): string {
  const metres = mm / 1000;
  return `${Number(metres.toFixed(2))} m`;
}

/** Pence as pounds: 2500 -> "£25.00". */
export function formatPounds(pence: number): string {
  return `£${(pence / 100).toFixed(2)}`;
}

/** "25", "25.5" or "25.50" -> pence, or null if it is not a sum of money. Exact, no floats. */
export function parsePounds(text: string): number | null {
  const m = text.trim().replace(/^£/, "").match(/^(\d{1,7})(?:\.(\d{1,2}))?$/);
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
}

/** "17", "7.3" or "0.25" -> millimetres, or null if it is not a length. Exact, no floats. */
export function parseMetres(text: string): number | null {
  const m = text.trim().match(/^(\d{1,4})(?:\.(\d{1,3}))?$/);
  if (!m) return null;
  return Number(m[1]) * 1000 + Number((m[2] ?? "").padEnd(3, "0"));
}

/** Millimetres as an editable metres string: 17000 -> "17", 7300 -> "7.3". */
export function metresInput(mm: number): string {
  return String(Number((mm / 1000).toFixed(3)));
}

/** Pence as an editable pounds string: 2500 -> "25.00". */
export function poundsInput(pence: number): string {
  return (pence / 100).toFixed(2);
}
