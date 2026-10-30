#!/usr/bin/env python3
"""Find what the oracle's gray=OFF replacement maps each colour to.

For a test colour the oracle's gray=OFF page is captured, then compared byte for
byte against candidate port renders: the colour itself (profile grid), the
colour forced through the cmyk grid, and grey pages of several levels rendered
at gray=OFF (which the port routes through the cmyk grid).  The candidate that
matches names the effective per-pixel colour the oracle substituted.

Usage: graytol_replace.py <colorlist> [--matching Normal|Vivid|None]
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
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_pipeline_compare import session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT = 5100, 6564
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID, "None": ColorMatching.NONE}
PROF = {"Normal": "rgb", "Vivid": "srgb", "None": "cmyk"}


def ppm_of(c):
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(c) * SW * HEIGHT


def render(ppm, settings, grid=None):
    orig_ct = pipeline.color_table
    if grid is not None:
        pipeline.color_table = lambda _s, _g=grid: _g
    try:
        w, h, _m, px = read_ppm(io.BytesIO(ppm))
        out = io.BytesIO()
        filter_page(w, h, px, settings, out)
        return session(out.getvalue())
    finally:
        pipeline.color_table = orig_ct


def main() -> int:
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH[matching]
    st.improve_gray = False
    cmykg = color_lut.ColorTable("cmyk")
    print(f"# matching={matching}")
    for ci, c in enumerate(colors):
        ppm = Path(f"{FIX}/rp{ci}.ppm")
        ppm.write_bytes(ppm_of(c))
        dst = Path(f"/tmp/rp{ci}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
        want = session(dst.read_bytes())
        cands = {"profile": render(ppm.read_bytes(), st),
                 "cmyk": render(ppm.read_bytes(), st, cmykg)}
        for v in (max(c), min(c), (c[0] + c[1] + c[2]) // 3, (max(c) + min(c)) // 2):
            cands[f"gray{v}"] = render(ppm_of((v, v, v)), st)
        hits = [k for k, val in cands.items() if val == want]
        print(f"{str(c):>16} d={max(c)-min(c):3d} -> {hits or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
