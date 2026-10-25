#!/usr/bin/env python3
"""Identify the HL-3040CN colour grids by comparing against the print oracle.

Feeding the proprietary filter a solid colour page gives, for each plane, the
fraction of dots it lays down; for a flat area that fraction is the ink level
the colour grid produced, divided by 255.  So each grid can be scored by how
well its predicted inks match the measured dot densities, which also pins the
exact byte alignment of each grid (a one-byte shift scrambles the values).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

LUT_DIM = 17
LUT_ENTRIES = LUT_DIM**3
LUT_BYTES = LUT_ENTRIES * 8
PLANES = ("C", "M", "Y", "K")

# Approximate grid starts found by structural scan; the exact offset is
# resolved per cluster by the ink match below.
CLUSTERS = [0x2A541, 0x33EBE, 0x3D8BF, 0x47340, 0x50CBD, 0x5A6BE, 0x646BB,
            0x6E0BD, 0x77ABD, 0x814B3, 0x8AE95, 0x94875, 0x9E25C, 0xA7C5E,
            0xB165E, 0xBB054, 0xC4A36, 0xCE416]

# Dot fraction per plane measured from the 3040 filter for each solid colour.
MEASURED = {
    "red":   {"M": 0.833, "Y": 0.581},
    "green": {"Y": 0.664},
    "blue":  {"C": 0.263, "M": 0.451},
    "black": {"K": 0.996},
    "cyan":  {"C": 0.112, "Y": 0.042},
    "magenta": {"C": 0.007, "M": 0.833},
    "yellow": {"Y": 0.664},
}
RGB = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "black": (0, 0, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "yellow": (255, 255, 0),
}


def unpack(raw: bytes, offset: int) -> np.ndarray:
    """Unpack one packed CMYK grid into (4913, 4)."""
    packed = np.frombuffer(raw[offset : offset + LUT_BYTES], dtype=np.int32).reshape(-1, 2)
    out = np.empty((LUT_ENTRIES, 4), dtype=np.int32)
    out[:, 0] = packed[:, 0] & 0xFFFF
    out[:, 1] = packed[:, 0] >> 16
    out[:, 2] = packed[:, 1] & 0xFFFF
    out[:, 3] = packed[:, 1] >> 16
    return out


def index(rgb: tuple[int, int, int]) -> int:
    """Grid index for an RGB triple, using the driver's b*289 + g*17 + r order."""
    r, g, b = (c // 16 for c in rgb)
    return b * 289 + g * 17 + r


def score(grid: np.ndarray) -> float:
    """Root-mean-square error between predicted ink and measured dot fraction."""
    errors = []
    for name, planes in MEASURED.items():
        idx = index(RGB[name])
        for plane, measured in planes.items():
            predicted = grid[idx][PLANES.index(plane)] / 255.0
            errors.append(predicted - measured)
    return float(np.sqrt(np.mean(np.square(errors))))


def main() -> None:
    """Report the best alignment and match score for every grid cluster."""
    raw = (Path(__file__).resolve().parent.parent / "ref" / "brhl3040cnfilter.bin").read_bytes()
    print(f"{'cluster':>9s} {'offset':>9s} {'rmse':>7s}  black")
    for cluster in CLUSTERS:
        best = None
        for offset in range(max(0, cluster - 400), min(len(raw) - LUT_BYTES, cluster + 400)):
            grid = unpack(raw, offset)
            if grid.max() > 255 or grid.min() < 0:
                continue
            err = score(grid)
            if best is None or err < best[1]:
                best = (offset, err, grid)
        if best is None:
            print(f"0x{cluster:07x} {'-':>9s} {'-':>7s}  no valid alignment")
            continue
        offset, err, grid = best
        print(f"0x{cluster:07x} 0x{offset:07x} {err:7.4f}  {grid[0].tolist()}")


if __name__ == "__main__":
    main()
