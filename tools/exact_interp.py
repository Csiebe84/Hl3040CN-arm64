#!/usr/bin/env python3
"""Reproduce the oracle ink with the driver's own 8-corner weight table.

The port interpolates tetrahedrally, but the driver ships 17 weight tables of
17*17*9 bytes in the binary: per (fractional triple) it stores a total and 8
corner weights.  Using those exact weights (instead of a tetrahedral
approximation) should close the last +/-2.

The 17 sub-tables live at 0x1dce0 in the 3040 filter, stride 0xa40, 2601 bytes
each, byte-identical to the HL-4150CDN's.  Corner order is
[0, 17, 1, 18, 289, 306, 290, 307] over the grid base index.

Usage: exact_interp.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
INTERP_BASE = 0x1DCE0
SUB_SIZE = 2601
SUB_STRIDE = 0xA40
CORNERS = np.array([0, 17, 1, 18, 289, 306, 290, 307], dtype=np.int64)
GRID_OFF = 0xA7C5E
LUT_BYTES = 39304
VALUES = [round(i * 255 / 59) for i in range(60)]


def load_weights() -> np.ndarray:
    """The 17 (17*17*9) weight sub-tables from the binary."""
    raw = RAW.read_bytes()
    subs = [raw[INTERP_BASE + i * SUB_STRIDE : INTERP_BASE + i * SUB_STRIDE + SUB_SIZE] for i in range(17)]
    return np.frombuffer(b"".join(subs), dtype=np.uint8).reshape(17, 289, 9)


def load_grid() -> np.ndarray:
    """The colour grid at 0xA7C5E, (4913, 4) int32 in stored field order."""
    raw = RAW.read_bytes()
    p = np.frombuffer(raw[GRID_OFF : GRID_OFF + LUT_BYTES], dtype=np.int32).reshape(-1, 2)
    o = np.empty((4913, 4), dtype=np.int64)
    o[:, 0] = p[:, 0] & 0xFFFF
    o[:, 1] = p[:, 0] >> 16
    o[:, 2] = p[:, 1] & 0xFFFF
    o[:, 3] = p[:, 1] >> 16
    return o


def interp_exact(grid: np.ndarray, weights: np.ndarray, rgb: np.ndarray, order: tuple[int, int, int]) -> np.ndarray:
    """8-corner weighted interpolation; `order` maps (r,g,b) frac to (sub,row,col)."""
    out = np.empty((len(rgb), 4), dtype=np.int64)
    for i, (r, g, b) in enumerate(rgb):
        fr = [16 if v == 255 else v & 15 for v in (r, g, b)]
        hi = [15 if v == 255 else v >> 4 for v in (r, g, b)]
        if r == 255 and g == 255 and b == 255:
            out[i] = [0, 0, 0, 0]
            continue
        if r == 0 and g == 0 and b == 0:
            out[i] = [0, 0, 0, 255]  # C,M,Y,K ink (rich black off)
            continue
        sub, row, col = fr[order[0]], fr[order[1]], fr[order[2]]
        w = weights[sub, row * 17 + col]
        total = int(w[0]) or 1
        base = hi[0] * 289 + hi[1] * 17 + hi[2]
        acc = np.zeros(4, dtype=np.int64)
        for k in range(8):
            acc += int(w[k + 1]) * grid[min(base + CORNERS[k], 4912)]
        out[i] = (acc + (total >> 1)) // total
    return out


def parse_ramp(path: Path, planes: list[str]) -> dict[str, list[int]]:
    """Read a ramp_measure log into {plane: ink over bars}."""
    out = {p: [] for p in planes}
    for line in path.read_text().splitlines():
        f = line.split()
        if len(f) >= 3 + len(planes) and f[0].isdigit() and int(f[0]) < 60:
            for j, p in enumerate(planes):
                out[p].append(int(f[2 + j]))
    return out


def main() -> int:
    """Try every weight-table axis order and report ramp error."""
    weights = load_weights()
    grid = load_grid()
    logs = HERE.parent / "logs"
    ramps = {
        "R": parse_ramp(logs / "ramp_measure_r60.log", ["K", "M", "Y"]),
        "G": parse_ramp(logs / "ramp_measure_g60.log", ["K", "Y"]),
        "B": parse_ramp(logs / "ramp_measure_b60.log", ["K", "M", "Y"]),
    }
    coord = {"R": 0, "G": 1, "B": 2}
    results = []
    for order in itertools.permutations(range(3)):
        total = 0
        for axis, c in coord.items():
            rgb = np.array([[v if j == c else 0 for j in range(3)] for v in VALUES])
            ink = interp_exact(grid, weights, rgb, order)  # C,M,Y,K
            for plane, want in ramps[axis].items():
                col = ("C", "M", "Y", "K").index(plane)
                total += int(np.abs(ink[:, col] - np.array(want)).sum())
        results.append((total, order))
    results.sort()
    for total, order in results:
        print(f"  order={order}  sum|err|={total}")
    print(f"best order={results[0][1]} err={results[0][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
