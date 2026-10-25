#!/usr/bin/env python3
"""Exhaustively match every binary grid against the oracle's primary edges.

The R/G/B node ramps (tools/ramp_build.py --nodes, measured by
tools/ramp_measure.py --nodes) give the oracle's ink at all 17 grid nodes of
each primary axis with a bit-exact fit (error 0).  That is the whole edge of
the colour cube, not just the six corners, so it discriminates grids far
better than the six solid primaries.

The stored blob is 17x17x17 packed int32 pairs.  Two things are unknown and
both are searched here:

* the axis order (which of r/g/b is slowest in the flat index), and
* the channel order (which of the four fields is C, M, Y, K).

Node 0 (pure black) is excluded: the driver special-cases it to K-only.

Usage: grid_edge_search.py [--top N]
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import find_luts  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"

# Oracle ink per grid node (0..16), measured bit-exactly from the node ramps.
# Nodes 0 is omitted from scoring (black is special-cased by the driver).
ORACLE: dict[str, dict[str, list[int]]] = {
    "R": {
        "K": [255, 221, 187, 156, 125, 97, 78, 61, 46, 34, 24, 16, 9, 5, 2, 0, 0],
        "M": [0, 103, 131, 154, 173, 190, 203, 213, 223, 233, 233, 233, 231, 228, 223, 219, 213],
        "Y": [0, 83, 105, 127, 150, 171, 181, 192, 202, 213, 214, 216, 217, 211, 205, 198, 190],
    },
    "G": {
        "K": [255, 238, 209, 182, 156, 131, 105, 88, 69, 55, 40, 28, 20, 12, 6, 2, 0],
        "Y": [0, 137, 153, 168, 184, 199, 215, 225, 235, 242, 238, 235, 232, 228, 225, 222, 218],
    },
    "B": {
        "K": [255, 222, 172, 126, 92, 65, 46, 31, 20, 12, 7, 4, 2, 1, 0, 0, 0],
        "M": [0, 42, 68, 95, 105, 115, 117, 119, 117, 114, 112, 109, 107, 104, 101, 99, 96],
        "Y": [11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11],
    },
}


def cell_index(axes: tuple[int, int, int], r: int, g: int, b: int) -> int:
    """Flat index for an RGB node under one axis order."""
    v = (r, g, b)
    return v[axes[0]] * 289 + v[axes[1]] * 17 + v[axes[2]]


def main() -> int:
    """Rank grid x axis x channel-order x value-convention combinations."""
    top = 15
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
    raw = RAW.read_bytes()
    cands = find_luts.scan(raw)
    print(f"Kandidaten: {len(cands)}, Achsen: 6, Kanaltupel: 24, Konvention: 2")

    results = []
    for axes in itertools.permutations(range(3)):
        for off in cands:
            grid = find_luts.unpack(raw, off)
            edges: dict[str, np.ndarray] = {}
            for axis, coord in (("R", 0), ("G", 1), ("B", 2)):
                idx = np.array([cell_index(axes, *[n if i == coord else 0 for i in range(3)]) for n in range(17)])
                edges[axis] = grid[idx]  # (17, 4), stored field order
            for perm in itertools.permutations(range(4)):
                for invert in (False, True):
                    total = 0
                    for axis, planes in ORACLE.items():
                        for plane, want in planes.items():
                            field = perm[("K", "C", "M", "Y").index(plane)]
                            raw_vals = edges[axis][1:, field].astype(np.int64)
                            got = (255 - raw_vals) if invert else raw_vals
                            total += int(np.abs(got - np.array(want[1:])).sum())
                    results.append((total, axes, off, perm, invert))
    results.sort(key=lambda t: t[0])
    print(f"{'fehler':>7s} {'achsen':10s} {'offset':>10s}  kanaltupel(C,M,Y,K)->feld  invert")
    print("-" * 70)
    for total, axes, off, perm, invert in results[:top]:
        print(f"{total:7d} {str(axes):10s} 0x{off:07x}  {perm}  {invert}")
    b = results[0]
    print(f"\nbester: fehler={b[0]} achsen={b[1]} offset=0x{b[2]:x} perm={b[3]} invert={b[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
