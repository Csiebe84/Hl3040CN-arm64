#!/usr/bin/env python3
"""Print profile/cmyk separations for the known replace/keep truth table."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402

logging.disable(logging.WARNING)

prof = color_lut.ColorTable("rgb", improve_gray=True, gray_replace=False)
cmyk = color_lut.ColorTable("cmyk")

REPLACED = [(1, 0, 0), (4, 0, 0), (5, 5, 5), (8, 8, 8), (15, 0, 0), (15, 15, 15), (16, 16, 16),
            (20, 20, 20), (100, 84, 84), (100, 85, 85), (112, 97, 97), (128, 113, 113),
            (128, 128, 128), (150, 135, 135), (200, 184, 190), (200, 185, 185), (200, 185, 190),
            (0, 0, 4), (0, 0, 9)]
KEPT = [(0, 0, 0), (16, 0, 0), (17, 0, 0), (240, 240, 255), (255, 240, 240), (255, 240, 255),
        (255, 255, 240), (255, 255, 255), (0, 0, 16)]


def sep(c, t):
    a = np.array(c, dtype=np.uint8).reshape(-1)
    k, cc, mm, y = color_lut.rgb_to_cmyk_lut_arr(a, 1, t)
    return [int(255 - k[0]), int(255 - cc[0]), int(255 - mm[0]), int(255 - y[0])]


def main() -> int:
    print(f"{'color':>16} {'d':>3} {'rep':>4} | {'prof KCMY':>20} | {'cmyk KCMY':>20}")
    for rep, group in (("JA", REPLACED), ("nein", KEPT)):
        for c in group:
            p = sep(c, prof)
            g = sep(c, cmyk)
            print(f"{str(c):>16} {max(c)-min(c):3d} {rep:>4} | {str(p):>20} | {str(g):>20}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
