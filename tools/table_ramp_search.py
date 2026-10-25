#!/usr/bin/env python3
"""Find the exact colour table + indexing convention that reproduces the oracle.

Scores every extracted table, under both grid index conventions (red-major
`r*289+g*17+b` and blue-major `b*289+g*17+r`) and every channel assignment,
against the *60-bar oracle ramp* — hundreds of non-node points, so it
discriminates far better than the 17-node edges.

The oracle ramp ink was measured bit-exactly (fit error 0) by
`ramp_measure.py`; see logs/ramp_measure_r60.log.

Usage: table_ramp_search.py
"""
from __future__ import annotations

import glob
import itertools
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

from verify_transform import interp_ink, load_table  # noqa: E402

# 60-bar R ramp: values and bit-exact oracle ink (K, M, Y).
VALUES = [round(i * 255 / 59) for i in range(60)]
ORACLE_K = [255, 246, 236, 228, 219, 209, 200, 192, 182, 173, 165, 156, 149, 140, 131, 123, 116, 109, 100, 95, 90, 84, 79, 75, 70, 65, 61, 56, 54, 49, 45, 42, 38, 35, 32, 30, 27, 24, 22, 20, 18, 16, 13, 12, 10, 9, 7, 6, 5, 4, 4, 3, 2, 1, 1, 0, 0, 0, 0, 0]
ORACLE_M = [0, 26, 58, 84, 105, 113, 121, 128, 135, 141, 147, 154, 159, 164, 170, 175, 178, 182, 188, 191, 194, 198, 201, 204, 209, 211, 213, 217, 219, 221, 225, 226, 230, 231, 233, 233, 233, 233, 233, 233, 233, 233, 233, 231, 231, 231, 230, 230, 228, 228, 226, 225, 223, 221, 221, 219, 217, 217, 215, 213]
ORACLE_Y = [0, 21, 47, 67, 85, 91, 98, 103, 110, 116, 121, 127, 134, 138, 145, 150, 156, 162, 168, 173, 175, 179, 180, 183, 187, 189, 192, 195, 198, 200, 203, 206, 209, 212, 213, 213, 214, 214, 215, 215, 216, 216, 216, 217, 217, 217, 216, 215, 213, 212, 210, 208, 207, 205, 204, 202, 200, 198, 196, 194]
ORACLE = np.array([ORACLE_K, ORACLE_M, ORACLE_Y])  # (3, 60) in K,M,Y order


def main() -> int:
    """Rank table x convention x channel map by 60-bar ramp error."""
    names = [os.path.basename(p).replace("_lut.bin", "") for p in sorted(glob.glob(str(HERE.parent / "hl3040cn/src/color_data/*_lut.bin")))]
    rgb = np.array([[v, 0, 0] for v in VALUES], dtype=np.int64)
    results = []
    for name in names:
        grid = load_table(name)  # fields f0..f3
        # interp_ink assumes red-major index; emulate blue-major by swapping
        # the r and b axes of the input, which is equivalent.
        for conv in ("r_major", "b_major"):
            inp = rgb[:, ::-1].copy() if conv == "b_major" else rgb
            ink = interp_ink(grid, inp)  # columns (C, M, Y, K) in field order
            for perm in itertools.permutations(range(4)):
                # perm maps physical (K, C, M, Y) -> field column index
                pred = np.array([ink[:, perm[i]] for i in range(4)])
                # K, M, Y are rows 0, 2, 3 of pred (K, C, M, Y).
                err = int(np.abs(np.round(pred[[0, 2, 3]]) - ORACLE).sum())
                results.append((err, name, conv, perm))
    results.sort(key=lambda t: t[0])
    print(f"{'fehler':>7s}  {'datei':28s} {'konvention':9s} kanal(K,C,M,Y)->feld")
    print("-" * 70)
    for err, name, conv, perm in results[:12]:
        print(f"{err:7d}  {name:28s} {conv:9s} {perm}")
    b = results[0]
    print(f"\nbester: fehler={b[0]} datei={b[1]} konvention={b[2]} perm={b[3]}")
    print("(sum|err| over 3 planes x 60 bars; port baseline is ~8000+)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
