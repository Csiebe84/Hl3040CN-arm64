#!/usr/bin/env python3
"""Test whether the oracle's primary edges are a per-channel curve of the port.

Ground truth: the R/G/B node ramps measured bit-exactly (error 0) by
`ramp_measure.py --nodes`.  For each output plane the oracle ink is compared
against the port's own LUT ink for the same input, using the port's real
output convention (rgb_to_cmyk_lut_arr returns brightness, ink = 255 - v).

If every (port_ink, oracle_ink) pair for a plane falls on one monotone curve,
the missing stage is a per-channel tone curve after the LUT.  If not, the
stage is not a per-channel function and the separation is 3D.

Usage: edge_curve.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
from color_lut import ColorTable  # noqa: E402

# Oracle ink per grid node 0..16 (input 0,16,...,240,255), bit-exact.
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
NODE_VALUES = [i * 16 for i in range(16)] + [255]


def port_ink(table: ColorTable, rgb: tuple[int, int, int]) -> dict[str, int]:
    """Port's ink per plane for one colour, using the port's own output order."""
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(bytes(rgb) * 1, 1, table)
    return {"K": 255 - int(k[0]), "C": 255 - int(c[0]), "M": 255 - int(m[0]), "Y": 255 - int(y[0])}


def main() -> int:
    """Print port-vs-oracle ink per plane for each edge."""
    table = ColorTable("rgb")
    for axis, coord in (("R", 0), ("G", 1), ("B", 2)):
        print(f"=== {axis} edge, table={table.name} ===")
        for plane, want in ORACLE[axis].items():
            pairs = []
            for node, val in enumerate(NODE_VALUES):
                rgb = [0, 0, 0]
                rgb[coord] = val
                p = port_ink(table, tuple(rgb))[plane]
                pairs.append((p, want[node]))
            # A per-channel curve means port_ink is monotone in node; report the
            # port sequence so a non-monotone or mismatched shape is visible.
            port_seq = [p for p, _ in pairs]
            print(f"  {plane}: port  " + " ".join(f"{v:3d}" for v in port_seq))
            print(f"  {plane}: oracle" + " ".join(f"{v:3d}" for v in want))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
