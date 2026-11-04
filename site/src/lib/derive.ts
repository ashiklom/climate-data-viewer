// Canonical variables computed from several native arrays (Daymet), mirroring climate_mirror.daymet.canonical.
export type VarSpec = { name?: string; inputs?: string[]; op?: string };

/** Native array names a canonical variable reads. */
export function inputsOf(spec: VarSpec): string[] {
  return spec.inputs ?? [spec.name!];
}

const OPS: Record<string, (...x: number[]) => number> = {
  mean: (a, b) => (a! + b!) / 2,
  // daylight-mean W m-2 x daylength s -> MJ m-2 day-1
  daylight_energy: (srad, dayl) => (srad! * dayl!) / 1e6,
  // dew point (degC) from vapour pressure (Pa), inverting the Tetens/Murray formula Daymet uses
  dewpoint_tetens: (vp) => { const x = Math.log(vp! / 610.78); return (237.3 * x) / (17.269 - x); },
};

/** Elementwise combination of decoded input arrays (NaN propagates). */
export function combine(spec: VarSpec, inputs: ArrayLike<number>[]): Float32Array {
  const f = spec.op ? OPS[spec.op] : undefined;
  if (!f) {
    if (inputs.length !== 1) throw new Error(`no op for ${inputs.length} inputs`);
    return Float32Array.from(inputs[0]!);
  }
  const out = new Float32Array(inputs[0]!.length);
  for (let i = 0; i < out.length; i++) out[i] = f(...inputs.map((a) => a[i]!));
  return out;
}
