import { describe, expect, it } from "vitest";

import { cfDecode, indexOf, type TimeAxis } from "./data";

describe("cfDecode", () => {
  it("applies scale_factor/add_offset and masks _FillValue (PRISM cf-uint packing)", () => {
    const attrs = { scale_factor: 0.0001, add_offset: -70, _FillValue: 4294967295 };
    const raw = Uint32Array.from([0, 700000, 4294967295, 922903]);
    const out = cfDecode(raw, attrs);
    expect(out[0]).toBeCloseTo(-70, 6);
    expect(out[1]).toBeCloseTo(0, 6);
    expect(Number.isNaN(out[2])).toBe(true);
    expect(out[3]).toBeCloseTo(22.2903, 4);
  });
  it("passes float data through, keeping NaN", () => {
    const out = cfDecode(Float32Array.from([1.5, NaN]), {});
    expect(out[0]).toBe(1.5);
    expect(Number.isNaN(out[1])).toBe(true);
  });
});

describe("indexOf", () => {
  const daily: TimeAxis = { originMs: Date.parse("1900-01-01T00:00Z"), unitMs: 86400000, first: 14609, step: 1, length: 100000 };
  it("finds days on a 'days since' axis", () => {
    // 1940-01-01 is 14609 days after 1900-01-01 (1900 is not a leap year)
    expect(indexOf(daily, "1940-01-01")).toBe(0);
    expect(indexOf(daily, "2021-07-01")).toBe(29767);
  });
  it("finds hours on an 'hours since' axis (Earthmover ERA5)", () => {
    const hourly: TimeAxis = { originMs: Date.parse("1940-01-01T00:00Z"), unitMs: 3600000, first: 0, step: 1, length: 1e6 };
    expect(indexOf(hourly, "2021-07-01T12:00Z")).toBe(714420);
  });
  it("handles 'seconds since' with daily steps (dynamical CHIRPS)", () => {
    const secs: TimeAxis = { originMs: 0, unitMs: 1000, first: 347155200, step: 86400, length: 20000 };
    expect(indexOf(secs, "1981-01-02")).toBe(1);
  });
});
