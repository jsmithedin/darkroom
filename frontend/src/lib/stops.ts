/** Mirrors the backend: stops of over (+) or under (-) exposure relative to box speed. */
export function stopsVsBox(ei: number, boxIso: number): number | null {
  if (!(ei > 0) || !(boxIso > 0)) return null;
  const raw = Math.log2(ei / boxIso);
  const rounded = Math.sign(raw) * Math.round(Math.abs(raw) * 10) / 10; // halves away from zero
  return rounded === 0 ? 0 : rounded;
}

/** "+1", "-2", "0", "-0.7": a sign, and a decimal only when there is a fractional part. */
export function formatStops(stops: number): string {
  if (stops === 0) return "0";
  const text = Number.isInteger(stops) ? String(Math.abs(stops)) : Math.abs(stops).toFixed(1);
  return (stops > 0 ? "+" : "-") + text;
}
