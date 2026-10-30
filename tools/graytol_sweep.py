#!/usr/bin/env python3
"""Classify many probe pixels as BRGray=OFF replaced / not replaced.

For each family of probe colours it runs the oracle once with --gray ON and
once with --gray OFF, recovers the ink of every plane and bar, and decides for
each bar whether the OFF output matches the profile grid or the cmyk grid
better (L1 distance over the four planes).  The result is a per-pixel truth
table with the input chroma and brightness alongside, which is what the
tolerance rule has to be read off from.

Usage: graytol_sweep.py <name> <probefile>
"""
from __future__ import annotations

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
from plane_all import rows  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW, HEIGHT = 5100, 6564
PLANES = ("K", "C", "M", "Y")


def build_ppm(colors):
    step = SW // len(colors)
    row = bytearray()
    for c in colors:
        row += bytes(c) * step
    row += bytes(colors[-1]) * (SW - len(row) // 3)
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def ink_of(colors, table):
    row = np.array(colors, dtype=np.uint8).reshape(-1)
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(row, len(colors), table)
    return 255 - np.stack([k, c, m, y], axis=1)


def main() -> int:
    name = sys.argv[1]
    colors = []
    for line in Path(sys.argv[2]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    step = SW // len(colors)
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    prof = color_lut.ColorTable("rgb", improve_gray=True, gray_replace=False)
    cmykg = color_lut.ColorTable("cmyk")
    P = ink_of(colors, prof)
    G = ink_of(colors, cmykg)

    ppm = Path(f"/tmp/{name}.ppm")
    ppm.write_bytes(build_ppm(colors))
    meas = {}
    for g in ("ON", "OFF"):
        dst = Path(f"/tmp/{name}_{g}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", "Normal", "--gray", g], check=True, capture_output=True)
        (FIX / f"{name}_{g}.xl2hb").write_bytes(dst.read_bytes())
        m = {}
        for p in PLANES:
            obs = rows(f"{name}_{g}", p)
            if obs is None:
                continue
            mid = len(colors) // 2
            ph = find_phase(obs, tables[p], mid * step, (mid + 1) * step)
            m[p] = np.array([solve_window(obs, tables[p], bi * step, (bi + 1) * step, ph)[0]
                             for bi in range(len(colors))])
        meas[g] = m

    print(f"# {name}  bars={len(colors)}")
    print(f"{'idx':>3} {'pixel':>16} {'d':>3} {'min':>3} {'max':>3} | "
          f"{'OFFink':>18} | {'prof':>18} {'cmyk':>18} | dP dG  -> grid")
    for bi, c in enumerate(colors):
        off = np.array([int(meas['OFF'][p][bi]) for p in PLANES])
        dP = int(np.abs(off - P[bi]).sum())
        dG = int(np.abs(off - G[bi]).sum())
        grid = "cmyk" if dG < dP else ("prof" if dP < dG else "=")
        print(f"{bi:3d} {str(c):>16} {max(c)-min(c):3d} {min(c):3d} {max(c):3d} | "
              f"{str(off.tolist()):>18} | {str(P[bi].tolist()):>18} {str(G[bi].tolist()):>18} | {dP:3d} {dG:3d}  {grid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
