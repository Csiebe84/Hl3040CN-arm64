#!/usr/bin/env python3
"""Search every grid in the 3040 binary for the oracle's red ink pair.

The oracle's red page carries only M and Y planes, measured bit-exactly at
ink 219 (brightness 36) and 190 (brightness 65).  Red is exactly a grid node,
so a matching grid must hold that pair at its red cell in the Y and M fields.
All three axis assignments are tried, because the packed layout puts the R
axis on either end and assuming wrong would hide the answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import find_luts  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "ref" / "brhl3040cnfilter.bin"
WANT_Y = 65  # 255 - 190
WANT_M = 36  # 255 - 219
# Raw field order in the file is (K, Y, M, C).
F_Y, F_M = 1, 2
AXES = {"r_slow": 16 * 289, "r_mid": 16 * 17, "r_fast": 16}


def main() -> int:
    """Report grids whose red cell matches the oracle's (Y, M) pair."""
    raw = RAW.read_bytes()
    cands = find_luts.scan(raw)
    print(f"Kandidaten: {len(cands)}   Ziel: Y={WANT_Y} M={WANT_M} (Tinte 190/219)")
    print(f"{'offset':>9s} {'achse':7s} | {'K':>4s} {'Y':>4s} {'M':>4s} {'C':>4s} |")
    print("-" * 44)
    hits = 0
    for off in cands:
        grid = find_luts.unpack(raw, off)
        for name, idx in AXES.items():
            v = grid[idx]
            if int(v[F_Y]) == WANT_Y and int(v[F_M]) == WANT_M:
                hits += 1
                print(f"0x{off:07x} {name:7s} | {v[0]:4d} {v[1]:4d} {v[2]:4d} {v[3]:4d} | <== TREFFER")
    print()
    print(f"Treffer: {hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
