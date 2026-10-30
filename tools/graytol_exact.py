#!/usr/bin/env python3
"""Exact ink of a solid-colour full page, from the oracle, gray ON vs OFF.

A full page of one colour gives thousands of dither periods, so the recovered
ink is exact (fit error 0).  This is the high-precision companion to
`graytol_sweep.py`: it says precisely which integer ink the oracle used for
each plane, which is what tells a real grid switch from a small tint.

Usage: graytol_exact.py <probefile>   (lines of "r g b")
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


def solve_full(obs: np.ndarray, table) -> tuple[int, int, int]:
    """Best (ink, error, phase) over the whole width and every phase."""
    period = table.width
    w = (SW // period) * period
    reps = w // period + 2
    tiled = np.tile(table.threshold_matrix, (1, reps))[:, :w]
    h = min(obs.shape[0], table.height)
    # One phase fit on a mid window, reused: the phase is a page property.
    ph = find_phase(obs, table, w // 2, w // 2 + period * 3)
    ink, err = solve_window(obs, table, 0, w, ph)
    return ink, err, ph


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
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    prof = color_lut.ColorTable("rgb", improve_gray=True, gray_replace=False)
    cmykg = color_lut.ColorTable("cmyk")
    P = ink_of(colors, prof)
    G = ink_of(colors, cmykg)

    for bi, c in enumerate(colors):
        ppm = b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(c) * SW * HEIGHT
        vals = {}
        for g in ("ON", "OFF"):
            dst = Path(f"/tmp/gte_{g}.xl2hb")
            p = Path(f"/tmp/gte_{g}.ppm")
            p.write_bytes(ppm)
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(p), str(dst),
                            "--matching", "Normal", "--gray", g], check=True, capture_output=True)
            (FIX / f"gte_{g}.xl2hb").write_bytes(dst.read_bytes())
            row = []
            for pl in PLANES:
                obs = rows(f"gte_{g}", pl)
                if obs is None:
                    row.append(None)
                    continue
                ink, err, ph = solve_full(obs, tables[pl])
                row.append((ink, err, ph))
            vals[g] = row
        on = [None if v is None else v[0] for v in vals["ON"]]
        off = [None if v is None else v[0] for v in vals["OFF"]]
        errs = [0 if v is None else v[1] for v in vals["OFF"]]
        print(f"{str(c):>16} d={max(c)-min(c):3d} | ON {on} | OFF {off} err={errs}")
        print(f"{'':>16}            | prof {P[bi].tolist()}  cmyk {G[bi].tolist()}")
        dP = [off[i] - int(P[bi, i]) for i in range(4)]
        dG = [off[i] - int(G[bi, i]) for i in range(4)]
        print(f"{'':>16}            | OFF-prof={dP} OFF-cmyk={dG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
