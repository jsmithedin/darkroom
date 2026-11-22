import { describe, expect, it } from "vitest";
import {
  formatMetres,
  formatPounds,
  metresInput,
  parseMetres,
  parsePounds,
  poundsInput,
} from "./format";

describe("money", () => {
  it.each([
    ["25", 2500],
    ["25.5", 2550],
    ["25.50", 2550],
    ["£25.99", 2599],
    ["0.05", 5],
    ["0", 0],
    [" 12 ", 1200],
  ])("parses %s", (text, pence) => expect(parsePounds(text)).toBe(pence));

  it.each(["", "abc", "1.234", "-5", "1,5", "£", "1e3"])("rejects %j", (text) => {
    expect(parsePounds(text)).toBeNull();
  });

  it("formats", () => {
    expect(formatPounds(2500)).toBe("£25.00");
    expect(formatPounds(5)).toBe("£0.05");
    expect(poundsInput(2550)).toBe("25.50");
  });
});

describe("lengths", () => {
  it.each([
    ["17", 17000],
    ["7.3", 7300],
    ["0.25", 250],
    ["0.001", 1],
    ["30.48", 30480],
  ])("parses %s m", (text, mm) => expect(parseMetres(text)).toBe(mm));

  it.each(["", "m", "1.2345", "-1", "1,5"])("rejects %j", (text) => {
    expect(parseMetres(text)).toBeNull();
  });

  it("formats", () => {
    expect(formatMetres(7300)).toBe("7.3 m");
    expect(formatMetres(17000)).toBe("17 m");
    expect(formatMetres(790)).toBe("0.79 m");
    expect(metresInput(17000)).toBe("17");
    expect(metresInput(7300)).toBe("7.3");
  });
});
