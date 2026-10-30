#!/usr/bin/env python3
"""Test whether oracle gray=OFF maps a colour to a pure grey value.

Renders every grey level 0..255 with the port at gray=OFF (which uses the cmyk
replacement grid, byte-identical to the oracle's grey ramp), hashes each page,
then for every test colour captures the oracle's gray=OFF page and looks its
hash up.  A hit names the grey level the colour was replaced by; no hit means
the replacement is not a pure grey.

Usage: graytol_mapg.py <colorlist> [--matching Normal|Vivid|None]
"""
from __future__ import annotations

import hashlib
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

SW, HEIGHT = 5100, 6564
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID, "None": ColorMatching.NONE}


def ppm_of(c):
    row = bytes(c) * SW
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + row * HEIGHT


def port(ppm, settings):
    w, h, _m, px = read_ppm(io.BytesIO(ppm))
    out = io.BytesIO()
    filter_page(w, h, px, settings, out)
    return session(out.getvalue())


def h(b):
    return hashlib.sha256(b).hexdigest()


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
    gray_hash = {}
    for g in range(256):
        gray_hash.setdefault(h(port(ppm_of((g, g, g)), st)), g)
    print(f"# matching={matching} grey levels hashed={len(gray_hash)}")
    for ci, c in enumerate(colors):
        ppm = Path(f"/tmp/mg{ci}.ppm")
        ppm.write_bytes(ppm_of(c))
        dst = Path(f"/tmp/mg{ci}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
        g = gray_hash.get(h(session(dst.read_bytes())))
        print(f"{str(c):>16} d={max(c)-min(c):3d} -> grey {g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
