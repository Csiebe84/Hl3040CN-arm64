#!/usr/bin/env python3
"""Which grid does the oracle's BRGray=OFF output match, pixel by pixel?

For a solid-colour page the rendered plane is fully determined by the ink value
and the dither threshold matrix, so the oracle's dot pattern can be compared
bit for bit against the pattern predicted by the profile grid and by the cmyk
grid.  A plane whose mismatch count is zero is reproduced exactly by that grid;
anything else means neither grid alone explains the output.

Usage: graytol_grid.py <probefile>
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

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW = 5100
PLANES = ("K", "C", "M", "Y")
COL = {"K": 0, "C": 1, "M": 2, "Y": 3}


def oracle_ink(color: tuple[int, int, int], table: color_lut.ColorTable) -> np.ndarray:
    """(K,C,M,Y) ink the port's `table` gives one solid colour."""
    row = np.array(color, dtype=np.uint8).reshape(-1)
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(row, 1, table)
    return np.array([int(k[0]), int(c[0]), int(m[0]), int(y[0])])


def mismatch(obs: np.ndarray, table, ink: int, phase: int, x0: int, x1: int) -> int:
    """Differing bits between the oracle window and the dither of `ink`."""
    period = table.width
    w = ((x1 - x0) // period) * period or (x1 - x0)
    reps = w // period + 2
    tiled = np.tile(table.threshold_matrix, (1, reps))[:, x0 % period : x0 % period + w]
    h = min(obs.shape[0], table.height)
    th = np.roll(tiled, -phase, axis=0)[:h]
    obs_w = obs[:h, x0 : x0 + w]
    dots = (255 - ink) > th
    return int(np.count_nonzero(dots ^ obs_w))


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

    prof_ink = np.array([oracle_ink(c, prof) for c in colors])
    cmyk_ink = np.array([oracle_ink(c, cmykg) for c in colors])

    obs_on = {p: rows("graytol_ON", p) for p in PLANES}
    obs_off = {p: rows("graytol_OFF", p) for p in PLANES}
    phase = {}
    for p in PLANES:
        if obs_on[p] is None:
            continue
        best = None
        for ph in range(tables[p].height):
            e = sum(mismatch(obs_on[p], tables[p], int(prof_ink[bi, COL[p]]), ph, bi * step, (bi + 1) * step)
                    for bi in range(len(colors)))
            if best is None or e < best[0]:
                best = (e, ph)
        phase[p] = best[1]
    print(f"phases={phase}")

    print(f"{'idx':>3} {'pixel':>16} {'repl':>4} | "
          + " ".join(f"{p}:{'prof':>4}/{'cmyk':>4}" for p in PLANES))
    for bi, c in enumerate(colors):
        replaced = False
        cells = []
        for p in PLANES:
            if obs_off[p] is None:
                cells.append(f"{p}:  -- /  --")
                continue
            mp = mismatch(obs_off[p], tables[p], int(prof_ink[bi, COL[p]]), phase[p], bi * step, (bi + 1) * step)
            mc = mismatch(obs_off[p], tables[p], int(cmyk_ink[bi, COL[p]]), phase[p], bi * step, (bi + 1) * step)
            if mp or mc:
                replaced = replaced or (mp != mc)
            tag = ""
            if mp == 0 and mc == 0:
                tag = "="
            elif mp == 0:
                tag = "P"
            elif mc == 0:
                tag = "G"
            cells.append(f"{p}:{mp:4d}/{mc:4d}{tag}")
        print(f"{bi:3d} {str(c):>16} {'JA ' if replaced else 'no '} | " + " ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
