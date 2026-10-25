#!/usr/bin/env python3
"""Match every extracted colour table against the oracle edges under both
index conventions.

The port's `color_lut.py` indexes the grid blue-major (`b*289 + g*17 + r`).
The oracle's measured edges match a grid in the binary only when it is read
red-major (`r*289 + g*17 + b`).  This tool scores each extracted table file
under both conventions and every channel assignment, so the transposition is
either confirmed or rejected on the full 17-node edge (bit-exact target).

Oracle ink per node 0..16 (input 0,16,...,240,255), measured error 0 by
`ramp_measure.py --nodes`.  Node 0 (black) is excluded: the driver
special-cases it to K only.

Usage: table_edge_search.py
"""
from __future__ import annotations

import glob
import itertools
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

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
    },
}
COORD = {"R": 0, "G": 1, "B": 2}


def load_file(path: str) -> np.ndarray:
    """Unpack a table file into (4913, 4) int32, stored field order."""
    packed = np.frombuffer(Path(path).read_bytes(), dtype=np.int32).reshape(-1, 2)
    out = np.empty((4913, 4), dtype=np.int64)
    out[:, 0] = packed[:, 0] & 0xFFFF
    out[:, 1] = packed[:, 0] >> 16
    out[:, 2] = packed[:, 1] & 0xFFFF
    out[:, 3] = packed[:, 1] >> 16
    return out


def edge_index(convention: str, node: int, coord: int) -> int:
    """Flat grid index of an edge node under r-major or b-major ordering."""
    n = [0, 0, 0]
    n[coord] = node
    if convention == "r_major":
        return n[0] * 289 + n[1] * 17 + n[2]
    return n[2] * 289 + n[1] * 17 + n[0]


def main() -> int:
    """Score every table file under both conventions and all channel maps."""
    names = sorted(glob.glob(str(HERE.parent / "hl3040cn/src/color_data/*_lut.bin")))
    results = []
    for path in names:
        grid = load_file(path)
        for conv in ("r_major", "b_major"):
            edges = {}
            for axis, coord in COORD.items():
                idx = [edge_index(conv, n, coord) for n in range(17)]
                edges[axis] = grid[idx]
            for perm in itertools.permutations(range(4)):
                total = 0
                for axis, planes in ORACLE.items():
                    for plane, want in planes.items():
                        field = perm[("K", "C", "M", "Y").index(plane)]
                        got = edges[axis][1:, field]
                        total += int(np.abs(got - np.array(want[1:])).sum())
                results.append((total, os.path.basename(path), conv, perm))
    results.sort(key=lambda t: t[0])
    print(f"{'fehler':>7s}  {'datei':28s} {'konvention':9s} kanal(C,M,Y,K)->feld")
    print("-" * 68)
    for total, name, conv, perm in results[:15]:
        print(f"{total:7d}  {name:28s} {conv:9s} {perm}")
    b = results[0]
    print(f"\nbester: fehler={b[0]} datei={b[1]} konvention={b[2]} perm={b[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
