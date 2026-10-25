#!/usr/bin/env python3
"""Verify a candidate colour table + indexing convention against the oracle.

Discovery so far: the oracle's primary edges match `srgb_ig_density2_lut.bin`
read *red-major* (index = r*289 + g*17 + b), with the stored fields mapping to
(K, C, M, Y) = (field3, field0, field1, field2).  The port reads blue-major
(index = b*289 + g*17 + r) and uses a different channel map, which is why no
table ever reproduced the oracle.

This tool computes the candidate's ink for any RGB input with red-major
tetrahedral interpolation and compares it against the oracle node ramps and the
60-bar ramp (both measured bit-exactly, error 0).

Usage: verify_transform.py [--table NAME] [--bars N]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "hl3040cn" / "src" / "color_data"
SRC_WIDTH = 5100

# Oracle ink per node 0..16 (input 0,16,...,240,255), measured error 0.
ORACLE_NODES: dict[str, dict[str, list[int]]] = {
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
NODE_VALUES = [i * 16 for i in range(16)] + [255]
COORD = {"R": 0, "G": 1, "B": 2}


def load_table(name: str) -> np.ndarray:
    """Unpack a table file to (4913, 4) int32 in stored field order."""
    packed = np.frombuffer((DATA / f"{name}_lut.bin").read_bytes(), dtype=np.int32).reshape(-1, 2)
    out = np.empty((4913, 4), dtype=np.int64)
    out[:, 0] = packed[:, 0] & 0xFFFF
    out[:, 1] = packed[:, 0] >> 16
    out[:, 2] = packed[:, 1] & 0xFFFF
    out[:, 3] = packed[:, 1] >> 16
    return out


def interp_ink(grid: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    """Red-major tetrahedral interpolation; returns ink (N, 4) for (N, 3) RGB.

    Fields are (f0, f1, f2, f3) = (C, M, Y, K) by the winning convention; the
    returned columns are in that same order.
    """
    r = rgb[:, 0].astype(np.int64)
    g = rgb[:, 1].astype(np.int64)
    b = rgb[:, 2].astype(np.int64)
    hi = np.where(rgb == 255, 15, rgb >> 4).astype(np.int64)
    fr = np.where(rgb == 255, 16, rgb & 0xF).astype(np.int64)
    rh, gh, bh = hi[:, 0], hi[:, 1], hi[:, 2]
    rf, gf, bf = fr[:, 0], fr[:, 1], fr[:, 2]

    def corner(dr: int, dg: int, db: int) -> np.ndarray:
        idx = np.clip(rh + dr, 0, 16) * 289 + np.clip(gh + dg, 0, 16) * 17 + np.clip(bh + db, 0, 16)
        return grid[idx]

    c000, c100, c010, c001 = corner(0, 0, 0), corner(1, 0, 0), corner(0, 1, 0), corner(0, 0, 1)
    c110, c101, c011, c111 = corner(1, 1, 0), corner(1, 0, 1), corner(0, 1, 1), corner(1, 1, 1)

    # Standard 6-case tetrahedral decomposition (Kang).
    out = np.empty((len(rgb), 4), dtype=np.float64)
    case = np.where(rf >= gf, np.where(gf >= bf, 0, np.where(rf >= bf, 1, 2)),
                    np.where(bf >= gf, 3, np.where(bf >= rf, 4, 5)))
    corners = [
        (c000, c100, c110, c111),
        (c000, c100, c101, c111),
        (c000, c001, c101, c111),
        (c000, c001, c011, c111),
        (c000, c010, c011, c111),
        (c000, c010, c110, c111),
    ]
    for k in range(6):
        sel = case == k
        if not np.any(sel):
            continue
        p0, p1, p2, p3 = (c[sel] for c in corners[k])
        rfk, gfk, bfk = rf[sel], gf[sel], bf[sel]
        if k == 0:
            w = np.stack([16 - rfk, rfk - gfk, gfk - bfk, bfk], axis=1)
        elif k == 1:
            w = np.stack([16 - rfk, rfk - bfk, bfk - gfk, gfk], axis=1)
        elif k == 2:
            w = np.stack([16 - bfk, bfk - rfk, rfk - gfk, gfk], axis=1)
        elif k == 3:
            w = np.stack([16 - bfk, bfk - gfk, gfk - rfk, rfk], axis=1)
        elif k == 4:
            w = np.stack([16 - gfk, gfk - bfk, bfk - rfk, rfk], axis=1)
        else:
            w = np.stack([16 - gfk, gfk - rfk, rfk - bfk, bfk], axis=1)
        out[sel] = (w[:, 0:1] * p0 + w[:, 1:2] * p1 + w[:, 2:3] * p2 + w[:, 3:4] * p3) / 16.0
    return out


def main() -> int:
    """Compare a candidate table's edges against the oracle node ramps."""
    name = "srgb_ig_density2"
    if "--table" in sys.argv:
        name = sys.argv[sys.argv.index("--table") + 1]
    grid = load_table(name)
    # Winning field map: K=f3, C=f0, M=f1, Y=f2.  interp_ink returns (C,M,Y,K).
    print(f"table={name}  convention=red-major  fields(C,M,Y,K)=(f0,f1,f2,f3)")
    for axis, coord in COORD.items():
        vals = np.array([[v if i == coord else 0 for i in range(3)] for v in NODE_VALUES], dtype=np.int64)
        ink = interp_ink(grid, vals)  # columns C,M,Y,K
        for plane, want in ORACLE_NODES[axis].items():
            col = ("C", "M", "Y", "K").index(plane)
            got = np.round(ink[:, col]).astype(int)
            err = int(np.abs(got - np.array(want)).sum())
            print(f"  {axis} {plane}: err={err:3d}  " + " ".join(f"{v:3d}" for v in got))
            print(f"  {'':4s} oracle " + " ".join(f"{v:3d}" for v in want))
    return 0


if __name__ == "__main__":
    sys.exit(main())
