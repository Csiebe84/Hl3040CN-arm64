#!/usr/bin/env python3
"""Identify the exact grid the oracle uses for a solid colour, by byte compare.

For a solid page of one colour, render it with the port while forcing *every*
pixel through one candidate grid (all 18 tables, and the profile grid as the
no-replacement reference).  Byte-compare each render against the oracle's
gray=OFF capture: the grid that matches byte for byte is the one the oracle
used for that colour.  No ink-fit or dither-phase ambiguity.

Usage: graytol_whichgrid2.py <colorlist> [--matching Normal|Vivid|None]
"""
from __future__ import annotations

import os

import io
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
import pipeline  # noqa: E402
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_pipeline_compare import session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

SW = 5100
HEIGHT = 6564
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID, "None": ColorMatching.NONE}

PROF = {"Normal": "rgb", "Vivid": "srgb", "None": "cmyk"}
GRIDS = [color_lut.ColorTable(p, ig, v)
         for p in ("rgb", "srgb", "cmyk") for ig in (False, True)
         for v in ("default", "density2", "glossy")]


def build_ppm(c):
    row = bytes(c) * SW
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + row * HEIGHT


def render_all(ppm, settings, grid):
    """Render with the whole page separated through `grid`, no replacement."""
    orig_ct = pipeline.color_table
    orig_grt = color_lut.gray_replace_table

    pipeline.color_table = lambda _s, _g=grid: _g
    color_lut.gray_replace_table = lambda _t=None: None
    try:
        w, h, _mx, pixels = read_ppm(io.BytesIO(ppm))
        out = io.BytesIO()
        filter_page(w, h, pixels, settings, out)
        return session(out.getvalue())
    finally:
        pipeline.color_table = orig_ct
        color_lut.gray_replace_table = orig_grt


def main() -> int:
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    settings = PrintSettings()
    settings.page_size = "Letter"
    settings.color_matching = MATCH[matching]
    settings.improve_gray = False
    print(f"# matching={matching} solids={len(colors)}")
    for c in colors:
        ppm = build_ppm(c)
        tmp = Path("/tmp/gw2_in.ppm")
        tmp.write_bytes(ppm)
        out = Path("/tmp/gw2_out.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(tmp), str(out),
                        "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
        want = session(out.read_bytes())
        only = os.environ.get("GWGRIDS")
        grids = [g for g in GRIDS if not only or g.name in only.split(",")]
        hits = []
        for g in grids:
            try:
                if render_all(ppm, settings, g) == want:
                    hits.append(g.name)
            except Exception as exc:  # noqa: BLE001
                hits.append(f"{g.name}!{exc}")
        print(f"{str(c):>16} d={max(c)-min(c):3d} lenO={len(want)} hits={hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
