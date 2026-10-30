#!/usr/bin/env python3
"""Compare the oracle's BRGray=OFF ink to the profile and cmyk grids' ink.

Runs the oracle with --gray ON and --gray OFF over a bar probe, recovers the
ink of every plane and bar, and prints it next to the port's profile-grid ink
and cmyk-grid ink, so it is visible which grid (if either) the oracle used.

Usage: graytol_compare.py <probefile>
"""
from __future__ import annotations

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

LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW = 5100
PLANES = ("K", "C", "M", "Y")


def ink_of(colors, table):
    row = np.array(colors, dtype=np.uint8).reshape(-1)
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(row, len(colors), table)
    return 255 - np.stack([k, c, m, y], axis=1)


def main() -> int:
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    step = SW // len(colors)
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    prof = color_lut.ColorTable("rgb", improve_gray=True, gray_replace=False)
    cmykg = color_lut.ColorTable("cmyk")
    P = ink_of(colors, prof)
    G = ink_of(colors, cmykg)

    meas = {}
    for g in ("ON", "OFF"):
        m = {}
        for p in PLANES:
            obs = rows(f"graytol_{g}", p)
            if obs is None:
                continue
            mid = len(colors) // 2
            ph = find_phase(obs, tables[p], mid * step, (mid + 1) * step)
            m[p] = np.array([solve_window(obs, tables[p], bi * step, (bi + 1) * step, ph)[0]
                             for bi in range(len(colors))])
        meas[g] = m

    for bi, c in enumerate(colors):
        on = [int(meas["ON"][p][bi]) for p in PLANES]
        off = [int(meas["OFF"][p][bi]) for p in PLANES]
        prof = [int(P[bi, i]) for i in range(4)]
        cmyk = [int(G[bi, i]) for i in range(4)]
        diff_p = [off[i] - prof[i] for i in range(4)]
        diff_g = [off[i] - cmyk[i] for i in range(4)]
        print(f"{str(c):>16} d={max(c)-min(c):3d} | ON {on} | OFF {off}")
        print(f"{'':>16}            | prof {prof} dP={diff_p}")
        print(f"{'':>16}            | cmyk {cmyk} dG={diff_g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
