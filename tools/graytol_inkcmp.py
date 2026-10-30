#!/usr/bin/env python3
"""Per solid colour: oracle gray=OFF ink vs profile-grid and cmyk-grid ink.

Renders each colour as a full-page solid through the oracle at gray=OFF,
recovers its four ink planes with the bit-exact window fit, and prints them
next to the port's profile-grid and cmyk-grid separation for the same colour.
The grid whose ink matches the oracle's is the one the oracle used.

Usage: graytol_inkcmp.py <colorlist> [--matching Normal|Vivid|None]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import os

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
import dither  # noqa: E402
from graytol_fullink import plane_bitmap  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW = 5100
HEIGHT = int(__import__("os").environ.get("ICH", "6564"))
PLANES = ("K", "C", "M", "Y")
PROF = {"Normal": "rgb", "Vivid": "srgb", "None": "cmyk"}


def build_ppm(c):
    row = bytes(c) * SW
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + row * HEIGHT


def ink(c, table):
    a = np.array(c, dtype=np.uint8).reshape(-1)
    k, cc, mm, y = color_lut.rgb_to_cmyk_lut_arr(a, 1, table)
    return [255 - int(k[0]), 255 - int(cc[0]), 255 - int(mm[0]), 255 - int(y[0])]


CAND = [color_lut.ColorTable(p, ig, v)
        for p in ("rgb", "srgb", "cmyk") for ig in (False, True)
        for v in ("default", "density2", "glossy")]


def main() -> int:
    matching = "Normal"
    gray = "OFF"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    if "--gray" in sys.argv:
        gray = sys.argv[sys.argv.index("--gray") + 1]
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    print(f"# matching={matching} gray={gray}")
    for ci, c in enumerate(colors):
        name = f"ic{ci}"
        ppm = Path(f"/tmp/{name}.ppm")
        ppm.write_bytes(build_ppm(c))
        dst = Path(f"/tmp/{name}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", matching, "--gray", gray], check=True, capture_output=True)
        (FIX / f"{name}.xl2hb").write_bytes(dst.read_bytes())
        obs = {}
        for p in PLANES:
            bm = plane_bitmap(name, p)
            if bm is None:
                continue
            ph = find_phase(bm, tables[p], 1500, 3500)
            obs[p] = solve_window(bm, tables[p], 1500, 3500, ph)[0]
        o = [obs[p] for p in PLANES if p in obs]
        scored = sorted((sum(abs(ink(c, t)[i] - o[i]) for i in range(len(o))), t.name) for t in CAND)
        print(f"{str(c):>16} d={max(c)-min(c):3d} oracle={o} best={scored[0][1]}({scored[0][0]})"
              f" next={scored[1][1]}({scored[1][0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
