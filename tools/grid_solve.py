#!/usr/bin/env python3
"""Find the colour grid and axis order that reproduce all measured oracle inks.

Measured bit-exactly from the oracle bitmaps (fit error <= 16 bits in 5120):

    red   M=219 Y=190     grn  Y=225     blu  M=96
    cyn   Y=13            mag  M=219     yel  Y=225

Each primary is a grid node, so no interpolation is involved and the required
ink can be read straight from a candidate grid's cell.  All six axis orders are
tried, because the packed layout fixes the storage order but not which corner
is red.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import find_luts  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "ref" / "brhl3040cnfilter.bin"
# Raw field order in the file is (K, Y, M, C); a candidate must give these inks.
WANT = {
    "red": (16, 0, 0, {"M": 219, "Y": 190}),
    "grn": (0, 16, 0, {"Y": 225}),
    "blu": (0, 0, 16, {"M": 96}),
    "cyn": (0, 16, 16, {"Y": 13}),
    "mag": (16, 0, 16, {"M": 219}),
    "yel": (16, 16, 0, {"Y": 225}),
}
FIELD = {"K": 0, "Y": 1, "M": 2, "C": 3}


def main() -> int:
    """Score every grid and axis order against all measured oracle inks."""
    raw = RAW.read_bytes()
    cands = find_luts.scan(raw)
    print(f"Kandidaten: {len(cands)}")
    results = []
    for axes in itertools.permutations(range(3)):
        for off in cands:
            grid = find_luts.unpack(raw, off)
            total = 0
            ok = True
            for _name, (r, g, b, want) in WANT.items():
                v = [r, g, b]
                idx = v[axes[0]] * 289 + v[axes[1]] * 17 + v[axes[2]]
                cell = grid[idx]
                for field, target in want.items():
                    got = 255 - int(cell[FIELD[field]])
                    total += abs(got - target)
            results.append((total, axes, off, ok))
    results.sort()
    print(f"{'fehler':>7s} {'achsen':10s} {'offset':>10s}")
    print("-" * 32)
    for total, axes, off, _ok in results[:10]:
        print(f"{total:7d} {str(axes):10s} 0x{off:07x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
