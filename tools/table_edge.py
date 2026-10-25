#!/usr/bin/env python3
"""Score each port colour table against the oracle's bit-exact primary edges.

Uses the R/G/B node ramps (measured error 0) as the target.  For every table
the port's LUT ink along each edge is compared with the oracle, and the table's
per-edge channel reach is reported: if a table's maximum ink on an edge is
below the oracle's, no input remap can ever reach it and the table is out.

Usage: table_edge.py
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
from color_lut import ColorTable  # noqa: E402

# Oracle ink per node 0..16 (input 0,16,...,240,255), bit-exact.
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
NODE_VALUES = [i * 16 for i in range(16)] + [255]
COORD = {"R": 0, "G": 1, "B": 2}


def port_ink(table: ColorTable, rgb: tuple[int, int, int]) -> dict[str, int]:
    """Port's ink per plane for one colour."""
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(bytes(rgb) * 1, 1, table)
    return {"K": 255 - int(k[0]), "C": 255 - int(c[0]), "M": 255 - int(m[0]), "Y": 255 - int(y[0])}


def main() -> int:
    """Print per-table edge error and channel reach."""
    names = [os.path.basename(p).replace("_lut.bin", "") for p in sorted(glob.glob(str(HERE.parent / "hl3040cn/src/color_data/*_lut.bin")))]
    print(f"{'table':22s} {'fehler':>7s}  oracle-max / port-max per edge-channel")
    for nm in names:
        t = ColorTable(
            profile=nm.split("_")[0],
            improve_gray="_ig" in nm,
            variant=("density2" if "density2" in nm else ("glossy" if "glossy" in nm else "default")),
        )
        total = 0
        reach = []
        for axis, planes in ORACLE.items():
            for plane, want in planes.items():
                seq = []
                for val in NODE_VALUES:
                    rgb = [0, 0, 0]
                    rgb[COORD[axis]] = val
                    seq.append(port_ink(t, tuple(rgb))[plane])
                total += int(np.abs(np.array(seq) - np.array(want)).sum())
                reach.append(f"{axis}{plane} {max(want):3d}/{max(seq):3d}")
        print(f"{nm:22s} {total:7d}  " + "  ".join(reach))
    return 0


if __name__ == "__main__":
    sys.exit(main())
