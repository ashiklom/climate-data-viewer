"""Map overlays for the website: coastlines, national borders and US state borders from Natural Earth 1:10m.

Source GeoJSON (public domain) is cached under cache/raw.githubusercontent.com/...; the output is simplified to
`--tolerance` degrees (`--fine-tolerance` over CONUS and its neighbours, where the finest datasets are) and rounded to 4
decimals there (about 10 m) and 3 elsewhere, written to site/public/overlays/<name>.geojson.

    uv run python scripts/web/make_overlays.py
"""

from __future__ import annotations

import argparse
import json

import httpx
from shapely.geometry import box, mapping, shape

from climate_mirror.paths import REPO_ROOT, cache_path

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
OVERLAYS = {
    # output name: (Natural Earth layer, feature filter)
    "coastline": ("ne_10m_coastline", None),
    "countries": ("ne_10m_admin_0_boundary_lines_land", None),
    "states": ("ne_10m_admin_1_states_provinces_lines", lambda p: p.get("ADM0_A3") == "USA"),
}
FINE_BOX = box(-128, 14, -50, 53)  # CONUS, Mexico, southern Canada
OUT = REPO_ROOT / "site" / "public" / "overlays"


def source(layer: str) -> dict:
    url = f"{BASE}{layer}.geojson"
    path = cache_path(url)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(url, follow_redirects=True, timeout=120)
        r.raise_for_status()
        path.write_bytes(r.content)
    return json.loads(path.read_text())


def rounded(coords, nd: int):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], nd), round(coords[1], nd)]
    return [rounded(c, nd) for c in coords]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tolerance", type=float, default=0.01, help="simplification tolerance, degrees")
    ap.add_argument("--fine-tolerance", type=float, default=0.002, help="tolerance over CONUS and its neighbours, degrees")
    ap.add_argument("--min-length", type=float, default=0.1, help="drop lines shorter than this, degrees (tiny islets)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (layer, keep) in OVERLAYS.items():
        features = []
        for f in source(layer)["features"]:
            if keep and not keep(f["properties"]):
                continue
            full = shape(f["geometry"])
            if full.length < args.min_length:
                continue
            parts = [full] if not full.intersects(FINE_BOX) else [
                full.intersection(FINE_BOX).simplify(args.fine_tolerance, preserve_topology=False),
                full.difference(FINE_BOX).simplify(args.tolerance, preserve_topology=False)]
            lines = []
            for i, geom in enumerate(parts):
                fine = len(parts) == 2 and i == 0
                nd = 4 if fine else 3  # about 10 m / 100 m
                if geom is full:
                    geom = full.simplify(args.tolerance, preserve_topology=False)
                for g in getattr(geom, "geoms", [geom]):
                    if g.geom_type == "LineString" and not g.is_empty:
                        lines.append(rounded(mapping(g)["coordinates"], nd))
                    elif g.geom_type == "MultiLineString":
                        lines += [rounded(mapping(x)["coordinates"], nd) for x in g.geoms if not x.is_empty]
            if lines:
                features.append({"type": "Feature", "properties": {},
                                 "geometry": {"type": "MultiLineString", "coordinates": lines}})
        out = OUT / f"{name}.geojson"
        out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")))
        print(f"{name}: {len(features)} features, {out.stat().st_size / 1e6:.2f} MB -> {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
