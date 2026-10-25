#!/usr/bin/env python3
"""Search every candidate grid against ALL THREE 60-bar oracle ramps at once.

The R ramp alone leaves a small residual (Y~11 on blue) that a single-axis
match cannot attribute.  Scoring R, G and B together, over every grid in the
binary, both index conventions and every channel map, either finds a grid with
error 0 or proves the residual is not any single embedded grid.

Usage: combined_search.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from find_luts import scan  # noqa: E402
from verify_transform import interp_ink  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
LUT_BYTES = 39304
VALUES = [round(i * 255 / 59) for i in range(60)]


def parse_ramp(path: Path, planes: list[str]) -> dict[str, np.ndarray]:
    """Read a ramp_measure log into {plane: ink array over bars}."""
    out = {p: [] for p in planes}
    for line in path.read_text().splitlines():
        f = line.split()
        if len(f) >= 3 + len(planes) and f[0].isdigit() and int(f[0]) < 60:
            for j, p in enumerate(planes):
                out[p].append(int(f[2 + j]))
    return {p: np.array(v) for p, v in out.items()}


def unpack(raw: bytes, off: int) -> np.ndarray:
    """Unpack a grid blob to (4913, 4) int32 in stored field order."""
    p = np.frombuffer(raw[off : off + LUT_BYTES], dtype=np.int32).reshape(-1, 2)
    o = np.empty((4913, 4), dtype=np.int64)
    o[:, 0] = p[:, 0] & 0xFFFF
    o[:, 1] = p[:, 0] >> 16
    o[:, 2] = p[:, 1] & 0xFFFF
    o[:, 3] = p[:, 1] >> 16
    return o


def main() -> int:
    """Rank grids by combined R+G+B ramp error over all channels."""
    ramps = {
        "R": parse_ramp(HERE.parent / "logs" / "ramp_measure_r60.log", ["K", "M", "Y"]),
        "G": parse_ramp(HERE.parent / "logs" / "ramp_measure_g60.log", ["K", "Y"]),
        "B": parse_ramp(HERE.parent / "logs" / "ramp_measure_b60.log", ["K", "M", "Y"]),
    }
    coord = {"R": 0, "G": 1, "B": 2}
    raw = RAW.read_bytes()
    cands = sorted(set(c + d for c in scan(raw) for d in (-2, 0, 2) if 0 <= c + d <= len(raw) - LUT_BYTES))
    results = []
    for off in cands:
        grid = unpack(raw, off)
        if not np.all(grid[4912] == 0):
            continue
        for conv in ("r_major", "b_major"):
            rgb = {}
            for axis, c in coord.items():
                arr = np.array([[v if i == c else 0 for i in range(3)] for v in VALUES], dtype=np.int64)
                rgb[axis] = arr[:, ::-1].copy() if conv == "b_major" else arr
            inks = {axis: interp_ink(grid, rgb[axis]) for axis in coord}  # columns (f0,f1,f2,f3)
            for perm in itertools.permutations(range(4)):
                total = 0
                for axis, planes in ramps.items():
                    pred = np.round(inks[axis][:, perm]).astype(np.int64)
                    for plane, want in planes.items():
                        col = ("K", "C", "M", "Y").index(plane)
                        total += int(np.abs(pred[:, col] - want).sum())
                results.append((total, off, conv, perm))
    results.sort(key=lambda t: t[0])
    print(f"{'fehler':>7s} {'offset':>10s} {'konvention':9s} kanal(K,C,M,Y)->feld")
    print("-" * 60)
    for err, off, conv, perm in results[:12]:
        print(f"{err:7d} 0x{off:07x} {conv:9s} {perm}")
    b = results[0]
    print(f"\nbester: fehler={b[0]} offset=0x{b[1]:x} {b[2]} perm={b[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
