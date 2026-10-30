#!/usr/bin/env python3
"""Recover the exact ink of an already-captured uniform (solid) page.

A solid page has one colour everywhere, so a best-fit over a wide window of the
first block recovers each plane's ink without bar-edge or phase aliasing.

Usage: graytol_solidink.py <capture_stem> [x0 x1]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import dither  # noqa: E402
from graytol_fullink import plane_bitmap  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
PLANES = ("K", "C", "M", "Y")


def main() -> int:
    stem = sys.argv[1]
    x0 = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    x1 = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    ink = {}
    for p in PLANES:
        obs = plane_bitmap(stem, p)
        if obs is None:
            continue
        ph = find_phase(obs, tables[p], x0, x1)
        ink[p] = solve_window(obs, tables[p], x0, x1, ph)[0]
    print(f"{stem}: {[ink[p] for p in PLANES if p in ink]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
