#!/usr/bin/env python3
"""Measure the oracle's real ink level per plane, using the validated decoders.

For each plane the oracle emits, decode a scanline and search the dither table
for the ink level whose dithered output reproduces that bitmap bit for bit.
That yields the ink level the original filter actually used, which is the
number the colour separation must produce.
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


def oracle_lines(name: str) -> dict[str, list[bytes]]:
    """Decoded bitmaps per plane, keyed by plane letter."""
    blocks = decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes()))
    out: dict[str, list[bytes]] = {}
    for b in blocks:
        dec = rle_decode.decode_10bit if b.header.comp_size == 10 else rle_decode.decode_12bit
        for e in b.entries:
            out.setdefault(b.plane_name, []).append(dec(e, LINE_BYTES))
    return out


def match_level(bitmap: bytes, table, row: int) -> tuple[int | None, int]:
    """Find the ink level whose dithered row equals `bitmap`.

    Returns:
        (level or None, best differing-bit count).
    """
    arr = np.frombuffer(bitmap, dtype=np.uint8)
    best = (None, WIDTH + 1)
    for level in range(256):
        ink = np.full(WIDTH, level, dtype=np.uint8)
        got = dither.dither_channel_1bpp_arr(ink, row, WIDTH, table)
        if got == bitmap:
            return level, 0
        diff = int(np.unpackbits(np.frombuffer(got, np.uint8) ^ arr).sum())
        if diff < best[1]:
            best = (level, diff)
    return best


def main() -> int:
    """Report the oracle ink level per plane for each fixture."""
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    for name in sys.argv[1:] or ["red"]:
        print(f"=== {name} ===")
        for plane, lines in sorted(oracle_lines(name).items()):
            table = tables[plane]
            print(f"  {plane}: {len(lines)} Zeilen, Tabelle {table.width}x{table.height}")
            for row in (0, 1, 2):
                if row >= len(lines):
                    break
                level, diff = match_level(lines[row], table, row)
                if level is None:
                    print(f"     Zeile {row}: keine exakte Stufe, beste {diff} abweichende Bit")
                else:
                    print(f"     Zeile {row}: Tintenstufe = {level}   (bit-genau)")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
