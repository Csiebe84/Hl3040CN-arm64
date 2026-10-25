#!/usr/bin/env python3
"""Exhaustive search for the colour grid + indexing + channel map + convention.

Scores every candidate grid in the 3040 filter binary (find_luts.scan), under
both grid index conventions (red-major r*289+g*17+b, blue-major b*289+g*17+r),
every channel assignment, and both rounding modes, against the *60-bar oracle
ramp* (bit-exact target, error 0 fit).

A hit at error 0 identifies the colour transformation exactly.  Anything
larger quantifies how far the best model still is.

Usage: full_search.py
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
ORACLE = np.array([
    [255, 246, 236, 228, 219, 209, 200, 192, 182, 173, 165, 156, 149, 140, 131, 123, 116, 109, 100, 95, 90, 84, 79, 75, 70, 65, 61, 56, 54, 49, 45, 42, 38, 35, 32, 30, 27, 24, 22, 20, 18, 16, 13, 12, 10, 9, 7, 6, 5, 4, 4, 3, 2, 1, 1, 0, 0, 0, 0, 0],
    [0, 26, 58, 84, 105, 113, 121, 128, 135, 141, 147, 154, 159, 164, 170, 175, 178, 182, 188, 191, 194, 198, 201, 204, 209, 211, 213, 217, 219, 221, 225, 226, 230, 231, 233, 233, 233, 233, 233, 233, 233, 233, 233, 231, 231, 231, 230, 230, 228, 228, 226, 225, 223, 221, 221, 219, 217, 217, 215, 213],
    [0, 21, 47, 67, 85, 91, 98, 103, 110, 116, 121, 127, 134, 138, 145, 150, 156, 162, 168, 173, 175, 179, 180, 183, 187, 189, 192, 195, 198, 200, 203, 206, 209, 212, 213, 213, 214, 214, 215, 215, 216, 216, 216, 217, 217, 217, 216, 215, 213, 212, 210, 208, 207, 205, 204, 202, 200, 198, 196, 194],
], dtype=np.int64)  # K, M, Y


def unpack(raw: bytes, off: int) -> np.ndarray:
    """Unpack a grid blob to (4913, 4) int32, stored field order."""
    p = np.frombuffer(raw[off : off + LUT_BYTES], dtype=np.int32).reshape(-1, 2)
    o = np.empty((4913, 4), dtype=np.int64)
    o[:, 0] = p[:, 0] & 0xFFFF
    o[:, 1] = p[:, 0] >> 16
    o[:, 2] = p[:, 1] & 0xFFFF
    o[:, 3] = p[:, 1] >> 16
    return o


def main() -> int:
    """Search every grid x convention x channel map x rounding."""
    raw = RAW.read_bytes()
    cands = sorted(set(c + d for c in scan(raw) for d in (-2, 0, 2) if 0 <= c + d <= len(raw) - LUT_BYTES))
    rgb = np.array([[v, 0, 0] for v in VALUES], dtype=np.int64)
    results = []
    for off in cands:
        grid = unpack(raw, off)
        if not np.all(grid[4912] == 0):
            continue
        for conv in ("r_major", "b_major"):
            inp = rgb[:, ::-1].copy() if conv == "b_major" else rgb
            ink = interp_ink(grid, inp)  # columns (f0,f1,f2,f3)
            for perm in itertools.permutations(range(4)):
                pred = np.array([ink[:, perm[i]] for i in range(4)])
                for rnd in ("round", "floor"):
                    vals = np.round(pred[[0, 2, 3]]) if rnd == "round" else np.floor(pred[[0, 2, 3]])
                    err = int(np.abs(vals.astype(np.int64) - ORACLE).sum())
                    results.append((err, off, conv, perm, rnd))
    results.sort(key=lambda t: t[0])
    print(f"{'fehler':>7s} {'offset':>10s} {'konvention':9s} kanal(K,C,M,Y)->feld rnd")
    print("-" * 62)
    for err, off, conv, perm, rnd in results[:15]:
        print(f"{err:7d} 0x{off:07x} {conv:9s} {perm} {rnd}")
    b = results[0]
    print(f"\nbester: fehler={b[0]} offset=0x{b[1]:x} {b[2]} perm={b[3]} rnd={b[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
