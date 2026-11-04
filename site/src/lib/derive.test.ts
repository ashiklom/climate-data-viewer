import { describe, expect, it } from "vitest";

import { combine, inputsOf } from "./derive";

describe("derived variables", () => {
  it("dew point inverts the Tetens formula", () => {
    const es = (t: number) => 610.78 * Math.exp((17.269 * t) / (237.3 + t));
    const td = combine({ inputs: ["vp"], op: "dewpoint_tetens" }, [[es(-10), es(0), es(15.5), es(25)]]);
    expect(Array.from(td).map((v) => +v.toFixed(4))).toEqual([-10, 0, 15.5, 25]);
  });
  it("daylight energy and mean; NaN propagates", () => {
    const e = combine({ inputs: ["srad", "dayl"], op: "daylight_energy" }, [[400, NaN], [43200, 1]]);
    expect(e[0]).toBeCloseTo(17.28, 5);
    expect(e[1]).toBeNaN();
    expect(Array.from(combine({ inputs: ["tmax", "tmin"], op: "mean" }, [[30], [10]]))).toEqual([20]);
  });
  it("single native variable passes through", () => {
    expect(inputsOf({ name: "prcp" })).toEqual(["prcp"]);
    expect(Array.from(combine({ name: "prcp" }, [[1.5, 2]]))).toEqual([1.5, 2]);
  });
});
