#!/usr/bin/env python3
"""Fast search: grid offset x base order x weight order x channel map on edges.

A single-axis ramp input (G=B=0) touches only the grid nodes on one axis, so
the interpolated curve is a fixed linear blend of two node values per bar.
That makes it cheap to score every (grid, base order, weight order, channel
map) combination against all three oracle ramps, using the driver's own 8-corner
weight table.  The winner is then confirmed on the full ramps by dot_check.py.

Usage: edge_search_fast.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from exact_interp import CORNERS, load_weights  # noqa: E402
from find_luts import scan  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
LUT_BYTES = 39304
VALUES = [round(i * 255 / 59) for i in range(60)]
PLANES = {"R": ["K", "M", "Y"], "G": ["K", "Y"], "B": ["K", "M", "Y"]}
COORD = {"R": 0, "G": 1, "B": 2}
COL = {"K": 3, "C": 0, "M": 1, "Y": 2}


def unpack(raw: bytes, off: int) -> np.ndarray:
    """Unpack a grid blob to (4913, 4) int32, stored field order."""
    p = np.frombuffer(raw[off : off + LUT_BYTES], dtype=np.int32).reshape(-1, 2)
    o = np.empty((4913, 4), dtype=np.int64)
    o[:, 0] = p[:, 0] & 0xFFFF
    o[:, 1] = p[:, 0] >> 16
    o[:, 2] = p[:, 1] & 0xFFFF
    o[:, 3] = p[:, 1] >> 16
    return o


def parse(fn: Path, planes: list[str]) -> dict[str, np.ndarray]:
    """Read a ramp_measure log."""
    out = {p: [] for p in planes}
    for line in fn.read_text().splitlines():
        f = line.split()
        if len(f) >= 3 + len(planes) and f[0].isdigit() and int(f[0]) < 60:
            for j, p in enumerate(planes):
                out[p].append(int(f[2 + j]))
    return {p: np.array(v) for p, v in out.items()}


def interp_axis(grid: np.ndarray, weights: np.ndarray, values: list[int], axis: int,
                bo: tuple[int, int, int], wo: tuple[int, int, int]) -> np.ndarray:
    """Interpolate a single-axis ramp, returning (len(values), 4) integer ink."""
    out = np.empty((len(values), 4), dtype=np.int64)
    for i, v in enumerate(values):
        fr = 16 if v == 255 else v & 15
        hi = 15 if v == 255 else v >> 4
        f = [0, 0, 0]
        h = [0, 0, 0]
        f[axis] = fr
        h[axis] = hi
        w = weights[f[wo[0]], f[wo[1]] * 17 + f[wo[2]]]
        total = int(w[0]) or 1
        base = h[bo[0]] * 289 + h[bo[1]] * 17 + h[bo[2]]
        acc = np.zeros(4, dtype=np.int64)
        for k in range(8):
            acc += int(w[k + 1]) * grid[min(base + CORNERS[k], 4912)]
        out[i] = (acc + (total >> 1)) // total
    return out


def main() -> int:
    """Rank grid x base order x weight order x channel map by combined ramp error."""
    W = load_weights()
    raw = RAW.read_bytes()
    cands = sorted(set(c + d for c in scan(raw) for d in (-2, 0, 2) if 0 <= c + d <= len(raw) - LUT_BYTES))
    ramps = {
        "R": parse(HERE.parent / "logs" / "ramp_measure_r60.log", PLANES["R"]),
        "G": parse(HERE.parent / "logs" / "ramp_measure_g60.log", PLANES["G"]),
        "B": parse(HERE.parent / "logs" / "ramp_measure_b60.log", PLANES["B"]),
    }
    results = []
    for off in cands:
        grid = unpack(raw, off)
        if not np.all(grid[4912] == 0):
            continue
        for bo in itertools.permutations(range(3)):
            for wo in itertools.permutations(range(3)):
                curves = {ax: interp_axis(grid, W, VALUES, COORD[ax], bo, wo) for ax in COORD}
                for perm in itertools.permutations(range(4)):
                    total = 0
                    for ax, planes in ramps.items():
                        pred = curves[ax][:, perm]
                        for plane, want in planes.items():
                            total += int(np.abs(pred[:, COL[plane]] - want).sum())
                    results.append((total, off, bo, wo, perm))
    results.sort(key=lambda t: t[0])
    print(f"{'fehler':>7s} {'offset':>10s} base_order weight_order  kanal(K,C,M,Y)->feld")
    print("-" * 72)
    for total, off, bo, wo, perm in results[:12]:
        print(f"{total:7d} 0x{off:07x} {str(bo):10s} {str(wo):11s} {perm}")
    b = results[0]
    print(f"\nbester: fehler={b[0]} offset=0x{b[1]:x} base={b[2]} weight={b[3]} perm={b[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
