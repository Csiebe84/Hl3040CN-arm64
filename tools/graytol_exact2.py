#!/usr/bin/env python3
"""Robust per-plane ink of a uniform page (oracle and port), with validation.

Decodes every row of every block, finds the dither phase over a wide window and
recovers the single constant ink of each plane with the bit-exact fit.  The same
recovery is run on the port's own render, whose grid is known, so a mismatch
there flags a broken measurement rather than a real difference.

Usage: graytol_exact2.py <colorlist> [--matching Normal|Vivid|None]
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
import dither  # noqa: E402
from graytol_fullink import plane_bitmap  # noqa: E402
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402
from ramp_pipeline_compare import session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW, HEIGHT = 5100, 6564
PLANES = ("K", "C", "M", "Y")
PROF = {"Normal": "rgb", "Vivid": "srgb", "None": "cmyk"}
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID, "None": ColorMatching.NONE}


def build_ppm(c):
    row = bytes(c) * SW
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + row * HEIGHT


def ink(c, table):
    a = np.array(c, dtype=np.uint8).reshape(-1)
    k, cc, mm, y = color_lut.rgb_to_cmyk_lut_arr(a, 1, table)
    return [255 - int(k[0]), 255 - int(cc[0]), 255 - int(mm[0]), 255 - int(y[0])]


def recover(name, tables):
    out = {}
    for p in PLANES:
        bm = plane_bitmap(name, p)
        if bm is None:
            continue
        ph = find_phase(bm, tables[p], 1200, 3900)
        out[p] = solve_window(bm, tables[p], 1200, 3900, ph)[0]
    return [out[p] for p in PLANES if p in out]


def main() -> int:
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    prof = color_lut.ColorTable(PROF[matching], improve_gray=True, gray_replace=False)
    cmykg = color_lut.ColorTable("cmyk")
    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = MATCH[matching]
    st.improve_gray = False
    print(f"# matching={matching}")
    for ci, c in enumerate(colors):
        name = f"x2_{ci}"
        ppm = Path(f"/mnt/ssd/bprobe/{name}.ppm")
        ppm.write_bytes(build_ppm(c))
        for tag in ("ON", "OFF"):
            dst = Path(f"/tmp/{name}_{tag}.xl2hb")
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                            "--matching", matching, "--gray", tag], check=True, capture_output=True)
            (FIX / f"{name}_{tag}.xl2hb").write_bytes(dst.read_bytes())
        st.improve_gray = True
        w, h, _m, px = read_ppm(io.BytesIO(ppm.read_bytes()))
        o = io.BytesIO()
        filter_page(w, h, px, st, o)
        (FIX / f"{name}_PORT.xl2hb").write_bytes(session(o.getvalue()))
        st.improve_gray = False
        o = io.BytesIO()
        filter_page(w, h, px, st, o)
        (FIX / f"{name}_PORTF.xl2hb").write_bytes(session(o.getvalue()))
        on = recover(f"{name}_ON", tables)
        off = recover(f"{name}_OFF", tables)
        port = recover(f"{name}_PORT", tables)
        print(f"{str(c):>16} d={max(c)-min(c):3d}")
        print(f"    oracleON ={on}")
        print(f"    oracleOFF={off}   prof={ink(c, prof)} cmyk={ink(c, cmykg)}")
        print(f"    portON   ={port}  (validation: should equal prof)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
