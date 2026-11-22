import { beforeEach, describe, expect, it } from "vitest";
import type { Roll } from "../api/rolls";
import { applyCameraDefaults, loadSetup, saveSetup } from "./setup";
import { formatStops, stopsVsBox } from "./stops";

describe("stops", () => {
  it.each([
    [400, 400, "0"],
    [800, 400, "+1"],
    [100, 400, "-2"],
    [3200, 400, "+3"],
    [250, 400, "-0.7"],
    [402, 400, "0"],
    [398, 400, "0"],
  ])("EI %d on box %d is %s", (ei, box, shown) => {
    expect(formatStops(stopsVsBox(ei, box)!)).toBe(shown);
  });

  it("is null for unusable input", () => {
    expect(stopsVsBox(0, 400)).toBeNull();
    expect(stopsVsBox(400, 0)).toBeNull();
    expect(stopsVsBox(Number.NaN, 400)).toBeNull();
  });
});

describe("setup", () => {
  beforeEach(() => localStorage.clear());

  it("round-trips and tolerates junk", () => {
    expect(loadSetup()).toBeNull();
    const s = { camera_id: "a", lens_id: "b", format_id: "c", developer_id: "d" };
    saveSetup(s);
    expect(loadSetup()).toEqual(s);
    localStorage.setItem("darkroom.setup", "{not json");
    expect(loadSetup()).toBeNull();
  });

  it("applyCameraDefaults uses the last roll, and leaves the draft when there is none", () => {
    const last = { lens: null, format: { id: "f35", name: "35mm" } } as unknown as Roll;
    expect(applyCameraDefaults({ lens_id: "x", format_id: "y" }, last)).toMatchObject({
      lens_id: "",
      format_id: "f35",
    });
    const draft = { lens_id: "x", format_id: "y" };
    expect(applyCameraDefaults(draft, null)).toBe(draft);
  });
});
