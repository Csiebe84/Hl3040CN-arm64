#!/usr/bin/env python3
"""Per-bar oracle-vs-port ink on a ramp at gray=OFF (the failing ramps).

Decodes the oracle's gray=OFF capture and the port's output for the same ramp
and prints, bar by bar, the recovered ink of both and their difference.  This
is the ground truth for the six diverging ramps: it shows exactly which input
values the port separates through the wrong grid.

Usage: graytol_offramp.py r|g|b|gray [--matching Normal|Vivid|None]
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
from settings import ColorMatching, PrintSettings  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW, HEIGHT, BARS = 5100, 6564, 60
STEP = SW // BARS
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
RAMPS = {"r": lambda v: (v, 0, 0), "g": lambda v: (0, v, 0), "b": lambda v: (0, 0, v),
         "gray": lambda v: (v, v, v)}
PLANES = ("K", "C", "M", "Y")
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID, "None": ColorMatching.NONE}


def build_ppm(ramp):
    row = bytearray()
    for v in VALUES:
        row += bytes(RAMPS[ramp](v)) * STEP
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def decode(name, tables):
    out = {}
    for p in PLANES:
        obs = plane_bitmap(name, p)
        if obs is None:
            continue
        ph = find_phase(obs, tables[p], (BARS // 2) * STEP, (BARS // 2 + 1) * STEP)
        out[p] = np.array([solve_window(obs, tables[p], bi * STEP, (bi + 1) * STEP, ph)[0]
                           for bi in range(BARS)])
    return out


def main() -> int:
    ramp = sys.argv[1]
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    ppm = build_ppm(ramp)
    Path(f"/tmp/of_{ramp}.ppm").write_bytes(ppm)
    dst = Path(f"/tmp/of_{ramp}_oracle.xl2hb")
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(Path(f"/tmp/of_{ramp}.ppm")),
                    str(dst), "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
    (FIX / f"of_{ramp}_oracle.xl2hb").write_bytes(dst.read_bytes())

    parsed = read_ppm(io.BytesIO(ppm))
    w, h, _mx, pixels = parsed
    s = PrintSettings()
    s.page_size = "Letter"
    s.color_matching = MATCH[matching]
    s.improve_gray = False
    buf = io.BytesIO()
    filter_page(w, h, pixels, s, buf)
    (FIX / f"of_{ramp}_port.xl2hb").write_bytes(buf.getvalue())

    o = decode(f"of_{ramp}_oracle", tables)
    p = decode(f"of_{ramp}_port", tables)
    print(f"# ramp={ramp} matching={matching} gray=OFF")
    ndiff = 0
    for bi in range(BARS):
        common = [q for q in PLANES if q in o and q in p]
        oi = [int(o[q][bi]) for q in common]
        pi = [int(p[q][bi]) for q in common]
        if oi != pi:
            ndiff += 1
            print(f"bar {bi:2d} {str(RAMPS[ramp](VALUES[bi])):>14} d={VALUES[bi]:3d} "
                  f"oracle{oi} port{pi} DIFF")
    print(f"{ndiff} differing bars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
