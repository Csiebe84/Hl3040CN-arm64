#!/usr/bin/env python3
"""Compare every candidate colour grid's primary edges with the oracle ramps.

The six solid primaries are single grid nodes; the R/G/B node ramps are the
whole edge of the cube and therefore hundreds of bits of evidence instead of
six.  Each grid is indexed by (r, g, b) in 0..16; the R edge is the cell at
(g=b=0) for r = 0..16, and likewise for G and B.  All six axis assignments of
the stored (K, Y, M, C) fields are tried because the packing does not say
which end of the triple is R.

Measured oracle ink at the nodes comes from `ramp_measure.py --nodes`
(fit error 0 for every bar).

Usage: grid_edge.py [--csv out.csv]
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
FIELD = {"K": 0, "Y": 1, "M": 2, "C": 3}  # stored order in the blob
NODES = list(range(16))  # input 0,16,...,240 -> grid node 0..15

# Oracle ink at each node, measured bit-exactly (tools/ramp_measure.py --nodes).
# Rows are the input node index 0..15; values are ink 0..255 per plane.
ORACLE = {
    "R": {
        "K": [255, 221, 187, 156, 125, 97, 78, 61, 46, 34, 24, 16, 9, 5, 2, 0],
        "M": [0, 103, 131, 154, 173, 190, 203, 213, 223, 233, 233, 233, 231, 228, 223, 219],
        "Y": [0, 83, 105, 127, 150, 171, 181, 192, 202, 213, 214, 216, 217, 211, 205, 198],
    },
    "G": {
        "K": [255, 238, 209, 182, 156, 131, 105, 88, 69, 55, 40, 28, 20, 12, 6, 2],
        "Y": [0, 137, 153, 168, 184, 199, 215, 225, 235, 242, 238, 235, 232, 228, 225, 222],
    },
    "B": {
        "K": [255, 222, 172, 126, 92, 65, 46, 31, 20, 12, 7, 4, 2, 1, 0, 0],
        "M": [0, 42, 68, 95, 105, 115, 117, 119, 117, 114, 112, 109, 107, 104, 101, 99],
        "Y": [11, 11, 11, 11, 11, 11, 14, 13, 11, 11, 11, 11, 11, 11, 11, 11],
    },
}


def grid_index(axes: tuple[int, int, int], r: int, g: int, b: int) -> int:
    """Flat index for an RGB node under one axis assignment.

    axes maps (which axis is slowest, middle, fastest) onto (r, g, b).
    """
    v = (r, g, b)
    return v[axes[0]] * 289 + v[axes[1]] * 17 + v[axes[2]]


def edge_errors(grid: np.ndarray, axes: tuple[int, int, int]) -> dict[str, int]:
    """Total |predicted - measured| ink over all three edges and their planes."""
    totals: dict[str, int] = {}
    for axis, planes in ORACLE.items():
        coord = {"R": 0, "G": 1, "B": 2}[axis]
        for plane, want in planes.items():
            field = FIELD[plane]
            err = 0
            for node in NODES:
                rgb = [0, 0, 0]
                rgb[coord] = node
                idx = grid_index(axes, rgb[0], rgb[1], rgb[2])
                got = 255 - int(grid[idx][field])
                err += abs(got - want[node])
            totals[f"{axis}{plane}"] = err
    return totals


def main() -> int:
    """Score every grid x axis order against the full measured edges."""
    raw = RAW.read_bytes()
    cands = find_luts.scan(raw)
    print(f"Kandidaten: {len(cands)}   Knoten je Achse: {len(NODES)}")
    results = []
    for axes in itertools.permutations(range(3)):
        for off in cands:
            grid = find_luts.unpack(raw, off)
            errs = edge_errors(grid, axes)
            results.append((sum(errs.values()), axes, off, errs))
    results.sort()
    print(f"{'summe':>7s} {'achsen':10s} {'offset':>10s}  R:KYM  G:KY  B:KMY")
    print("-" * 62)
    for total, axes, off, errs in results[:12]:
        detail = (
            f"{errs['RK']:4d}/{errs['RM']:4d}/{errs['RY']:4d} "
            f"{errs['GK']:4d}/{errs['GY']:4d} "
            f"{errs['BK']:4d}/{errs['BM']:4d}/{errs['BY']:4d}"
        )
        print(f"{total:7d} {str(axes):10s} 0x{off:07x}  {detail}")
    best = results[0]
    print(f"\nbester: summe={best[0]} achsen={best[1]} offset=0x{best[2]:x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
