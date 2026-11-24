import { readFileSync } from "node:fs";
import { screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Purchases } from "../pages/Purchases";
import { Stock } from "../pages/Stock";
import { LogRoll } from "../pages/LogRoll";
import { installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";

// Vitest is configured with css: false, so read the real stylesheet from disk.
const css = readFileSync(`${process.cwd()}/src/styles/global.css`, "utf8");

// jsdom does no layout, but it does cascade the real stylesheet, so declared sizes can be checked.
let style: HTMLStyleElement;
beforeEach(() => {
  style = document.createElement("style");
  style.textContent = css;
  document.head.append(style);
  installMockApi({
    refs: {
      films: [{ id: "f1", name: "Tri-X", archived_at: null, type: "bw", box_iso: 400 }],
      formats: [{ id: "m35", name: "35mm", archived_at: null }],
      cameras: [{ id: "c1", name: "FM2", archived_at: null, fixed_lens: false }],
      lenses: [{ id: "l1", name: "50mm", archived_at: null }],
      developers: [{ id: "d1", name: "HC-110", archived_at: null }],
    },
    handler: (url) => {
      if (url.startsWith("/api/stock-movements")) {
        return reply({ items: [], total: 0, limit: 20, offset: 0 });
      }
      if (url.startsWith("/api/stock")) {
        return reply([{ film: { id: "f1", name: "Tri-X", type: "bw" }, format: { id: "m35", name: "35mm" }, rolls: 3 }]);
      }
      if (url.startsWith("/api/bulk-rolls") || url === "/api/stats/low-stock") return reply([]);
      if (url.startsWith("/api/rolls")) return reply({ items: [], total: 0, limit: 20, offset: 0 });
      return undefined;
    },
  });
});
afterEach(() => {
  style.remove();
  vi.unstubAllGlobals();
});

const TARGETS = "button, a[href], input, select, textarea, summary";
const px = (value: string) => {
  if (value === "auto" || value === "") return 0; // no rule sets a size
  const n = Number.parseFloat(value);
  if (Number.isNaN(n)) throw new Error(`computed size "${value}" is not a number`);
  return n;
};

function controls(root: HTMLElement) {
  return [...root.querySelectorAll<HTMLElement>(TARGETS)].filter((el) => {
    if (el instanceof HTMLInputElement && (el.type === "hidden")) return false;
    return true;
  });
}

/** A checkbox or radio is small, but its label row is the touch target. */
function target(el: HTMLElement): HTMLElement {
  if (el instanceof HTMLInputElement && ["checkbox", "radio"].includes(el.type)) {
    return el.closest("label") ?? el;
  }
  return el;
}

const screens = [
  ["log", <LogRoll key="log" />, "/"],
  ["purchases", <Purchases key="p" />, "/purchases"],
  ["stock", <Stock key="s" />, "/stock"],
] as const;

for (const [name, ui, route] of screens) {
  it(`all interactive elements on ${name} are at least 44px tall`, async () => {
    const { container } = renderApp(ui, route);
    await screen.findAllByRole("heading");
    await new Promise((r) => setTimeout(r, 50)); // let the queries settle
    const small = controls(container)
      .filter((el) => px(getComputedStyle(target(el)).minHeight) < 44)
      .map((el) => `${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute("aria-label") || el.getAttribute("name") || "").trim().slice(0, 30)}"`);
    expect(small).toEqual([]);
  });

  it(`text inputs on ${name} compute to 16px so iOS does not zoom`, async () => {
    const { container } = renderApp(ui, route);
    await screen.findAllByRole("heading");
    await new Promise((r) => setTimeout(r, 50));
    const fields = [...container.querySelectorAll<HTMLElement>("input, select, textarea")].filter(
      (el) => !(el instanceof HTMLInputElement && ["hidden", "checkbox", "radio"].includes(el.type)),
    );
    expect(fields.length).toBeGreaterThan(0);
    const wrong = fields
      .filter((el) => px(getComputedStyle(el).fontSize) < 16)
      .map((el) => el.getAttribute("name") || el.getAttribute("aria-label") || el.tagName);
    expect(wrong).toEqual([]);
  });
}
