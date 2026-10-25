#!/usr/bin/env python3
"""Determine how an oracle scanline relates to the threshold matrix.

Decoding gave a horizontal period of 10 for both planes, which no 80- or
24-wide threshold row reproduces.  This compares the oracle line against the
tiled matrix directly: which table row is closest, at which level, and by how
many bits it differs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import dither  # noqa: E402
import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
WIDTH = 5120
LINE_BYTES = WIDTH // 8


def oracle_rows(name: str, plane: str) -> list[bytes]:
    """All decoded scanlines of one plane, in stream order."""
    blocks = decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes()))
    out: list[bytes] = []
    for b in blocks:
        if b.plane_name != plane:
            continue
        dec = rle_decode.decode_10bit if b.header.comp_size == 10 else rle_decode.decode_12bit
        out.extend(dec(e, LINE_BYTES) for e in b.entries)
    return out


def main() -> int:
    """Compare the first oracle row against every table row and level."""
    name = sys.argv[1] if len(sys.argv) > 1 else "red"
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    for plane in (sys.argv[2:] or ["M", "Y"]):
        rows = oracle_rows(name, plane)
        table = tables[plane]
        want = np.unpackbits(np.frombuffer(rows[0], np.uint8))[:WIDTH].astype(bool)
        want_density = want.mean()
        print(f"=== {name} / {plane}: Dichte={want_density:.4f} ===")
        best = None
        for row in range(table.height):
            t = table.threshold_matrix[row % table.height]
            reps = WIDTH // len(t) + 1
            th = np.tile(t, reps)[:WIDTH]
            for level in range(256):
                diff = int(np.count_nonzero((level > th) ^ want))
                if best is None or diff < best[0]:
                    best = (diff, row, level)
        diff, row, level = best
        print(f"  bester Treffer: Zeile {row}, Stufe {level}, {diff} abweichende Bit von {WIDTH}")
        print(f"  Dichte der besten Schwelle: {(level > np.tile(table.threshold_matrix[row], WIDTH//table.width+1)[:WIDTH]).mean():.4f}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
