#!/usr/bin/env python3
"""Find the colour grid whose red cell matches the oracle.

Red (255,0,0) is exactly grid node 16 on the R axis, so no interpolation is
needed: read the cell directly.  The oracle's Y ink for red was measured
bit-exactly as level 190, i.e. brightness 255-190 = 65.

The raw grid stores (K, Y, M, C); the R axis may be the slow, middle or fast
axis, so the red cell is one of three indices.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import find_luts  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "ref" / "brhl3040cnfilter.bin"
TARGET_Y = 65  # 255 - 190, the oracle's Y brightness for red
RED_IDX = {"r_slow": 16 * 289, "r_mid": 16 * 17, "r_fast": 16}
CH = ("K", "Y", "M", "C")


def main() -> int:
    """Scan every candidate grid for a red cell matching the oracle."""
    raw = RAW.read_bytes()
    cands = find_luts.scan(raw)
    print(f"Kandidaten im Binary: {len(cands)}   Ziel: Y-Kanal an der Rot-Zelle = {TARGET_Y}")
    print(f"{'offset':>9s} {'achse':7s} | {'K':>4s} {'Y':>4s} {'M':>4s} {'C':>4s} | Treffer")
    print("-" * 58)
    hits = 0
    for off in cands:
        grid = find_luts.unpack(raw, off)
        for name, idx in RED_IDX.items():
            vals = grid[idx]
            ok = any(int(v) == TARGET_Y for v in vals)
            if ok:
                hits += 1
                tag = " <== Y passt" if int(vals[1]) == TARGET_Y else " <== anderes Feld"
                print(f"0x{off:07x} {name:7s} | {vals[0]:4d} {vals[1]:4d} {vals[2]:4d} {vals[3]:4d} |{tag}")
    print()
    print(f"Treffer: {hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
