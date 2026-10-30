#!/usr/bin/env python3
"""Per-pixel: is the oracle's gray=OFF render the profile grid or the cmyk grid?

Probe colours are laid out as bars on one page.  The oracle is run once with
--gray OFF; the port renders the same page twice, forcing the profile grid and
the cmyk grid.  Each bar is then classified:
  P  = oracle equals the profile render (pixel NOT replaced)
  G  = oracle equals the cmyk render (pixel replaced)
  =  = both equal (the two grids agree)
  x  = neither (needs inspection)

Usage: graytol_probe.py <colorlist> [--matching Normal|Vivid] [--bars N]
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
from ramp_pipeline_compare import session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

pipeline.HAS_BAND_KERNEL = False
FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT = 5100, 6564
PLANES = ("K", "C", "M", "Y")
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID}


def bars_ppm(colors):
    step = SW // len(colors)
    row = bytearray()
    for c in colors:
        row += bytes(c) * step
    row += bytes(colors[-1]) * (SW - len(row) // 3)
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


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
    bars = int(sys.argv[sys.argv.index("--bars") + 1]) if "--bars" in sys.argv else 150
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH[matching]
    st.improve_gray = False
    prof = color_lut.ColorTable("rgb" if matching == "Normal" else "srgb", improve_gray=True, gray_replace=False)
    cmyk = color_lut.ColorTable("cmyk")
    print(f"# matching={matching} bars={bars} colors={len(colors)}")
    for page0 in range(0, len(colors), bars):
        chunk = colors[page0:page0 + bars]
        step = SW // len(chunk)
        name = f"pb{page0 // bars}"
        ppm = bars_ppm(chunk)
        p = FIX / f"{name}.ppm"
        p.write_bytes(ppm)
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(p), f"/tmp/{name}.xl2hb",
                        "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
        (FIX / f"{name}_OR.xl2hb").write_bytes(session(Path(f"/tmp/{name}.xl2hb").read_bytes()))
        (FIX / f"{name}_P.xl2hb").write_bytes(render(ppm, st, prof))
        (FIX / f"{name}_C.xl2hb").write_bytes(render(ppm, st, cmyk))
        orr = {pl: plane_bitmap(f"{name}_OR", pl) for pl in PLANES}
        pr = {pl: plane_bitmap(f"{name}_P", pl) for pl in PLANES}
        cy = {pl: plane_bitmap(f"{name}_C", pl) for pl in PLANES}
        for i, c in enumerate(chunk):
            x0, x1 = i * step, (i + 1) * step
            dp = dc = 0
            for pl in PLANES:
                a = orr[pl]
                if a is None:
                    continue
                for other, acc in ((pr[pl], "p"), (cy[pl], "c")):
                    if other is None:
                        continue
                    hh = min(a.shape[0], other.shape[0])
                    d = int(np.count_nonzero(a[:hh, x0:x1] ^ other[:hh, x0:x1]))
                    if acc == "p":
                        dp += d
                    else:
                        dc += d
            tag = "=" if dp == 0 and dc == 0 else ("P" if dp == 0 else ("G" if dc == 0 else "x"))
            print(f"{str(c):>16} d={max(c)-min(c):3d} mx={max(c):3d} {tag} dp={dp} dc={dc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
