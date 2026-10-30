#!/usr/bin/env python3
"""Test whether the oracle's gray=OFF replacement neutralises the pixel first.

For each colour the oracle's gray=OFF page is captured, then compared byte for
byte against the port rendering a candidate neutralised pixel either through the
profile grid (matching Normal, gray OFF) or the cmyk grid (matching None).  A
hit names the pixel value and grid the oracle substituted.

Usage: graytol_neutral.py <colorlist> [--matching Normal|Vivid]
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

from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_pipeline_compare import session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT = 5100, 6564
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID}


def ppm_of(c):
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(c) * SW * HEIGHT


def render(ppm, matching, gray):
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH.get(matching, ColorMatching.NONE)
    st.improve_gray = gray == "ON"
    w, h, _m, px = read_ppm(io.BytesIO(ppm))
    out = io.BytesIO()
    filter_page(w, h, px, st, out)
    return session(out.getvalue())


def main() -> int:
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    print(f"# matching={matching}")
    for ci, c in enumerate(colors):
        ppm = Path(f"{FIX}/nt{ci}.ppm")
        ppm.write_bytes(ppm_of(c))
        dst = Path(f"/tmp/nt{ci}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
        want = session(dst.read_bytes())
        r, g, b = c
        neutrals = {
            "min": (min(c),) * 3,
            "max": (max(c),) * 3,
            "avg": ((r + g + b) // 3,) * 3,
            "g": (g, g, g),
            "mid": ((max(c) + min(c)) // 2,) * 3,
        }
        hits = []
        for name, q in neutrals.items():
            for grid, mm in (("prof", matching), ("cmyk", "None")):
                if render(ppm_of(q), mm, "OFF") == want:
                    hits.append(f"{name}->{grid}")
        print(f"{str(c):>16} d={max(c)-min(c):3d} -> {hits or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
