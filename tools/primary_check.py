#!/usr/bin/env python3
"""Verify the six solid primaries dot-exactly against the oracle fixtures.

The single-axis ramps cover R, G and B.  The compound primaries cyan, magenta
and yellow (two channels at 255) exercise a different grid region, so they are
the second half of the reference cases.  For each fixture this tool lists the
levels whose rendered pattern matches the oracle exactly and checks whether the
model's level is among them.

Usage: primary_check.py
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
from dot_check import zero_levels  # noqa: E402
from exact_interp import interp_exact, load_grid, load_weights  # noqa: E402
from ramp_measure import find_phase, plane_cycle  # noqa: E402

WIDTH = 5120
SRC_WIDTH = 5100
COL = {"K": 3, "C": 0, "M": 1, "Y": 2}
ORDER = (2, 1, 0)
CASES = {
    "red": ([255, 0, 0], ["M", "Y"]),
    "grn": ([0, 255, 0], ["Y"]),
    "blu": ([0, 0, 255], ["M"]),
    "cyn": ([0, 255, 255], ["Y"]),
    "mag": ([255, 0, 255], ["M"]),
    "yel": ([255, 255, 0], ["Y"]),
}


def main() -> int:
    """Check every primary plane: is the model's level pattern-exact?"""
    grid = load_grid()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"), fine=False, toner_save=False)
    bad = 0
    for name, (rgb, planes) in CASES.items():
        ink = interp_exact(grid, weights, np.array([rgb]), ORDER)[0]
        for plane in planes:
            obs = plane_cycle(name, plane, 10**6)
            table = tables[plane]
            phase = find_phase(obs, table, 0, SRC_WIDTH // 4)
            w = (SRC_WIDTH // table.width) * table.width
            zs = zero_levels(obs, table, 0, w, phase)
            model = int(ink[COL[plane]])
            ok = model in zs
            if not ok:
                bad += 1
            print(f"{name:4s} {plane} model={model:3d} "
                  f"exact-range={(min(zs), max(zs)) if zs else None} -> {'OK' if ok else 'MISS'}")
    print(f"\nGESAMT primary-plane misses: {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
