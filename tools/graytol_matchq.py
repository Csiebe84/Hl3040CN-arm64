#!/usr/bin/env python3
"""Find which pixel value reproduces the oracle's gray=OFF output for a colour.

Renders one bar per candidate pixel with the port (grid selectable) and compares
the decoded plane bitmaps bar by bar against the oracle's gray=OFF solid page.
The dither phase is a page property and both pages share the same bar layout, so
a zero-difference bar names the pixel the oracle substituted.

Usage: graytol_matchq.py <r> <g> <b> <candidatefile> [--matching Normal|Vivid] [--grid cmyk|prof]
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


def solid_ppm(c):
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(c) * SW * HEIGHT


def main() -> int:
    r, g, b = (int(x) for x in sys.argv[1:4])
    matching = sys.argv[sys.argv.index("--matching") + 1] if "--matching" in sys.argv else "Normal"
    grid = sys.argv[sys.argv.index("--grid") + 1] if "--grid" in sys.argv else "cmyk"
    cands = []
    for line in Path(sys.argv[4]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cands.append(tuple(int(x) for x in line.split()))
    step = SW // len(cands)
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH[matching]
    st.improve_gray = False

    orp = FIX / "mq_or.ppm"
    orp.write_bytes(solid_ppm((r, g, b)))
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(orp), "/tmp/mq_or.xl2hb",
                    "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
    (FIX / "mq_OR.xl2hb").write_bytes(session(Path("/tmp/mq_or.xl2hb").read_bytes()))

    tbl = color_lut.ColorTable("cmyk") if grid == "cmyk" else color_lut.ColorTable(
        "rgb" if matching == "Normal" else "srgb", improve_gray=True, gray_replace=False)
    orig = pipeline.color_table
    pipeline.color_table = lambda _s, _t=tbl: _t
    pp = FIX / "mq_port.ppm"
    pp.write_bytes(bars_ppm(cands))
    w, h, _m, px = read_ppm(io.BytesIO(pp.read_bytes()))
    o = io.BytesIO()
    filter_page(w, h, px, st, o)
    pipeline.color_table = orig
    (FIX / "mq_PORT.xl2hb").write_bytes(session(o.getvalue()))

    oa = {p: plane_bitmap("mq_OR", p) for p in PLANES}
    pa = {p: plane_bitmap("mq_PORT", p) for p in PLANES}
    print(f"# target {(r, g, b)} matching={matching} grid={grid} cands={len(cands)} step={step}")
    for i, q in enumerate(cands):
        x0, x1 = i * step, (i + 1) * step
        tot = 0
        for p in PLANES:
            a, bb = oa[p], pa[p]
            if a is None or bb is None:
                continue
            hh = min(a.shape[0], bb.shape[0])
            tot += int(np.count_nonzero(a[:hh, x0:x1] ^ bb[:hh, x0:x1]))
        if tot == 0:
            print(f"  MATCH {q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
