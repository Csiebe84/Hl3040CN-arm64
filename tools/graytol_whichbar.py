#!/usr/bin/env python3
"""Per-bar: which grid (of 18) reproduces the oracle's gray=OFF bar?"""
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
    ppm = bars_ppm(colors)
    (FIX / "wb.ppm").write_bytes(ppm)
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(FIX / "wb.ppm"),
                    "/tmp/wb.xl2hb", "--matching", matching, "--gray", "OFF"],
                   check=True, capture_output=True)
    (FIX / "wb_OR.xl2hb").write_bytes(session(Path("/tmp/wb.xl2hb").read_bytes()))
    orr = {p: plane_bitmap("wb_OR", p) for p in PLANES}
    step = SW // len(colors)
    gridnames = [(p, ig, v) for p in ("rgb", "srgb", "cmyk")
                 for ig in (False, True) for v in ("default", "density2", "glossy")]
    print("# " + " ".join(f"{c}" for c in colors))
    results = {c: [] for c in colors}
    w, h, _m, px = read_ppm(io.BytesIO(ppm))
    for (p, ig, v) in gridnames:
        g = color_lut.ColorTable(p, ig, v)
        orig = pipeline.color_table
        pipeline.color_table = lambda _s, _g=g: _g
        try:
            o = io.BytesIO()
            filter_page(w, h, px, st, o)
            out = session(o.getvalue())
        finally:
            pipeline.color_table = orig
        (FIX / "wb_G.xl2hb").write_bytes(out)
        for i, c in enumerate(colors):
            x0, x1 = i * step, (i + 1) * step
            d = 0
            for pl in PLANES:
                a = orr[pl]
                b = plane_bitmap("wb_G", pl)
                if a is None or b is None:
                    continue
                hh = min(a.shape[0], b.shape[0])
                d += int(np.count_nonzero(a[:hh, x0:x1] ^ b[:hh, x0:x1]))
            results[c].append((d, g.name))
    for c in colors:
        results[c].sort()
        best = results[c][0]
        print(f"{str(c):>16} best={best[1]:20s} d={best[0]}  next={results[c][1][1]} d={results[c][1][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
