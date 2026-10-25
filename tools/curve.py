#!/usr/bin/env python3
"""Compare the oracle's measured ink levels with the port's colour table.

Uses the measured oracle levels (bit-exact, error 0-16 bits per 5120) and the
port's own LUT output for the same six primaries, to see whether the
difference is a per-channel curve, a table-selection error, or a stage that is
missing entirely.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
from color_lut import ColorTable  # noqa: E402

# Measured from the oracle, first scanline, bit-exact match (error <= 16/5120).
ORACLE = {
    "red": {"M": 219, "Y": 190},
    "grn": {"Y": 225},
    "blu": {"M": 96},
    "cyn": {"Y": 13},
    "mag": {"M": 219},
    "yel": {"Y": 225},
}
RGB = {
    "red": (255, 0, 0),
    "grn": (0, 255, 0),
    "blu": (0, 0, 255),
    "cyn": (0, 255, 255),
    "mag": (255, 0, 255),
    "yel": (255, 255, 0),
}


def port_ink(table: ColorTable, rgb: tuple[int, int, int]) -> dict[str, int]:
    """The port's ink amount per channel for a solid colour."""
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(bytes(rgb) * 16, 16, table)
    return {"K": 255 - int(k[0]), "C": 255 - int(c[0]), "M": 255 - int(m[0]), "Y": 255 - int(y[0])}


def main() -> int:
    """Print oracle vs port ink for each primary and each table."""
    for label, table in (
        ("rgb_default", ColorTable("rgb")),
        ("srgb_default", ColorTable("srgb")),
        ("cmyk_default", ColorTable("cmyk")),
        ("rgb_ig", ColorTable("rgb", improve_gray=True)),
    ):
        print(f"=== {label} ===")
        print(f"{'farbe':6s} {'ebene':5s} {'oracle':>6s} {'port':>5s} {'diff':>5s}")
        for name, planes in ORACLE.items():
            inks = port_ink(table, RGB[name])
            for plane, oracle in planes.items():
                p = inks[plane]
                print(f"{name:6s} {plane:5s} {oracle:6d} {p:5d} {p - oracle:+5d}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
