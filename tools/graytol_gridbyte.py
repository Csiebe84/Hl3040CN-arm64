#!/usr/bin/env python3
"""Which embedded grid reproduces the oracle's gray=OFF solid page, byte for byte?

Renders a solid-colour page under every one of the 18 embedded grids and compares
it to the oracle's gray=OFF capture.  A match names the grid the oracle used.

Usage: graytol_gridbyte.py <colorlist> [--matching Normal|Vivid|None]
"""
from __future__ import annotations

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

FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT = 5100, 6564
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID, "None": ColorMatching.NONE}
GRIDS = [color_lut.ColorTable(p, ig, v)
         for p in ("rgb", "srgb", "cmyk") for ig in (False, True)
         for v in ("default", "density2", "glossy")]


def ppm_of(c):
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(c) * SW * HEIGHT


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
    matching = sys.argv[sys.argv.index("--matching") + 1] if "--matching" in sys.argv else "Normal"
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH[matching]
    st.improve_gray = False
    print(f"# matching={matching}")
    for ci, c in enumerate(colors):
        ppm = ppm_of(c)
        p = FIX / f"gb{ci}.ppm"
        p.write_bytes(ppm)
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(p), f"/tmp/gb{ci}.xl2hb",
                        "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
        want = session(Path(f"/tmp/gb{ci}.xl2hb").read_bytes())
        hits = [g.name for g in GRIDS if render(ppm, st, g) == want]
        print(f"{str(c):>16} d={max(c)-min(c):3d} -> {hits or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
