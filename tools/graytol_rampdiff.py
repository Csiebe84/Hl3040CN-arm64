#!/usr/bin/env python3
"""Per-bar, per-plane bit differences between oracle and port on a ramp.

Decodes both XL2HB outputs to plane bitmaps and reports, for each ramp bar, the
number of differing bits in each plane, so the failing colour range and the
affected plane are visible.

Usage: graytol_rampdiff.py <ramp r|g|b|gray> [--matching Normal|Vivid] [--gray ON|OFF]
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

from graytol_fullink import plane_bitmap  # noqa: E402
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_pipeline_compare import SESSION_MARKER, build_ppm, session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
SW = 5100
STEP = SW // 60
PLANES = ("K", "C", "M", "Y")
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID, "None": ColorMatching.NONE}
RAMPS = {"r": lambda v: (v, 0, 0), "g": lambda v: (0, v, 0), "b": lambda v: (0, 0, v),
         "gray": lambda v: (v, v, v)}


def main() -> int:
    ramp = sys.argv[1]
    matching = sys.argv[sys.argv.index("--matching") + 1] if "--matching" in sys.argv else "Normal"
    gray = sys.argv[sys.argv.index("--gray") + 1] if "--gray" in sys.argv else "OFF"
    ppm = build_ppm(ramp)
    p = FIX / "rdiff.ppm"
    p.write_bytes(ppm)
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(p), "/tmp/rdiff.xl2hb",
                    "--matching", matching, "--gray", gray], check=True, capture_output=True)
    (FIX / "rdiff_OR.xl2hb").write_bytes(session(Path("/tmp/rdiff.xl2hb").read_bytes()))
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH[matching]
    st.improve_gray = gray == "ON"
    w, h, _m, px = read_ppm(io.BytesIO(ppm))
    o = io.BytesIO()
    filter_page(w, h, px, st, o)
    (FIX / "rdiff_PORT.xl2hb").write_bytes(session(o.getvalue()))
    or_ = {pl: plane_bitmap("rdiff_OR", pl) for pl in PLANES}
    po = {pl: plane_bitmap("rdiff_PORT", pl) for pl in PLANES}
    print(f"# ramp={ramp} matching={matching} gray={gray}")
    for bi in range(60):
        v = round(bi * 255 / 59)
        c = RAMPS[ramp](v)
        row = []
        for pl in PLANES:
            a, b = or_[pl], po[pl]
            if a is None or b is None:
                row.append(f"{pl}:--")
                continue
            d = int(np.count_nonzero(a[:, bi * STEP:(bi + 1) * STEP] ^ b[:, bi * STEP:(bi + 1) * STEP]))
            row.append(f"{pl}:{d}")
        tot = sum(int(x.split(":")[1]) for x in row if x.split(":")[1].isdigit())
        if tot:
            print(f"bar{bi:2d} {str(c):>16} " + " ".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
