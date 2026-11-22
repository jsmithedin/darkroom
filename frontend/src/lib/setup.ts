import type { Roll, RollDraft } from "../api/rolls";

/** The gear a person keeps using between rolls; remembered on this device. */
export interface Setup {
  camera_id: string;
  lens_id: string;
  format_id: string;
  developer_id: string;
}

const KEY = "darkroom.setup";

export function loadSetup(): Setup | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw);
    if (s && typeof s === "object") {
      return {
        camera_id: String(s.camera_id ?? ""),
        lens_id: String(s.lens_id ?? ""),
        format_id: String(s.format_id ?? ""),
        developer_id: String(s.developer_id ?? ""),
      };
    }
  } catch {
    // unreadable or storage blocked: behave as if nothing was saved
  }
  return null;
}

export function saveSetup(s: Setup): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // private mode etc.; remembering is a convenience only
  }
}

/**
 * When a camera is picked, take lens and format from its most recent roll.
 * A fixed-lens camera's last roll has no lens, which clears the lens (N/A).
 * With no previous roll the draft is left alone.
 */
export function applyCameraDefaults(draft: Partial<RollDraft>, last: Roll | null): Partial<RollDraft> {
  if (!last) return draft;
  return { ...draft, lens_id: last.lens?.id ?? "", format_id: last.format.id };
}
