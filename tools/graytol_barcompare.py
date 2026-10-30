#!/usr/bin/env python3
"""Per-bar: does the oracle's gray=OFF ramp match the profile or the cmyk grid?

Decodes the oracle's gray=OFF ramp and the port's ramp rendered under each forced
grid, then reports per bar and per plane the differing-bit counts against the
profile grid and against the cmyk grid.  Zero means that grid reproduces the bar
exactly.

Usage: graytol_barcompare.py <ramp r|g|b> [--matching Normal|Vivid]
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
import pipeline  # noqa: E402
from graytol_fullink import plane_bitmap  # noqa: E402
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_pipeline_compare import build_ppm, session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

pipeline.HAS_BAND_KERNEL = False
FIX = Path("/mnt/ssd/bprobe")
SW = 5100
STEP = SW // 60
PLANES = ("K", "C", "M", "Y")
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID}
RAMPS = {"r": lambda v: (v, 0, 0), "g": lambda v: (0, v, 0), "b": lambda v: (0, 0, v)}


def render(ppm, st, grid):
    orig = pipeline.color_table
    pipeline.color_table = lambda _s, _g=grid: _g
    try:
        w, h, _m, px = read_ppm(io.BytesIO(ppm))
        o = io.BytesIO()
        filter_page(w, h, px, st, o)
        return session(o.getvalue())
    finally:
        pipeline.color_table = orig


def main() -> int:
    ramp = sys.argv[1]
    matching = sys.argv[sys.argv.index("--matching") + 1] if "--matching" in sys.argv else "Normal"
    ppm = build_ppm(ramp)
    p = FIX / "bc.ppm"
    p.write_bytes(ppm)
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(p), "/tmp/bc.xl2hb",
                    "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
    (FIX / "bc_OR.xl2hb").write_bytes(session(Path("/tmp/bc.xl2hb").read_bytes()))
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH[matching]
    st.improve_gray = False
    prof = color_lut.ColorTable("rgb" if matching == "Normal" else "srgb", improve_gray=True, gray_replace=False)
    cmyk = color_lut.ColorTable("cmyk")
    (FIX / "bc_PROF.xl2hb").write_bytes(render(ppm, st, prof))
    (FIX / "bc_CMYK.xl2hb").write_bytes(render(ppm, st, cmyk))
    orr = {pl: plane_bitmap("bc_OR", pl) for pl in PLANES}
    pr = {pl: plane_bitmap("bc_PROF", pl) for pl in PLANES}
    cy = {pl: plane_bitmap("bc_CMYK", pl) for pl in PLANES}
    print(f"# ramp={ramp} matching={matching} gray=OFF")
    for bi in range(60):
        v = round(bi * 255 / 59)
        c = RAMPS[ramp](v)
        cells = []
        for pl in PLANES:
            a = orr[pl]
            if a is None:
                continue
            x0, x1 = bi * STEP, (bi + 1) * STEP
            dp = dc = None
            if pr[pl] is not None:
                hh = min(a.shape[0], pr[pl].shape[0])
                dp = int(np.count_nonzero(a[:hh, x0:x1] ^ pr[pl][:hh, x0:x1]))
            if cy[pl] is not None:
                hh = min(a.shape[0], cy[pl].shape[0])
                dc = int(np.count_nonzero(a[:hh, x0:x1] ^ cy[pl][:hh, x0:x1]))
            tag = "=" if dp == 0 and dc == 0 else ("P" if dp == 0 else ("G" if dc == 0 else "x"))
            cells.append(f"{pl}:{dp}/{dc}{tag}")
        print(f"bar{bi:2d} {str(c):>16} " + " ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
