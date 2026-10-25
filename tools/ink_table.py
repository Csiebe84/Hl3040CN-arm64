#!/usr/bin/env python3
"""Measure the oracle's ink level for every solid-colour fixture.

For a solid page each scanline carries one ink level, so the plane is the
threshold matrix tiled.  The cheapest exact way to recover that level is to
match the plane's first scanline against every table row and level.  Doing
this across all six primaries gives the curve the colour separation must
reproduce, which is the measurement the port's table lookup can be checked
against.
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


def plane_first_rows(name: str) -> dict[str, np.ndarray]:
    """First decoded scanline per plane, as bool arrays."""
    try:
        blob = (FIX / f"{name}.xl2hb").read_bytes()
    except FileNotFoundError:
        return {}
    out: dict[str, np.ndarray] = {}
    for b in decode_blocks(pclxl.parse(blob)):
        if b.plane_name in out or not b.entries:
            continue
        if b.header.comp_size == 10:
            dec = rle_decode.decode_10bit
        elif b.header.comp_size == 12:
            dec = rle_decode.decode_12bit
        else:
            continue  # 20-bit C plane needs its own decoder
        raw = dec(b.entries[0], LINE_BYTES)
        out[b.plane_name] = np.unpackbits(np.frombuffer(raw, np.uint8))[:WIDTH].astype(bool)
    return out


def solve(obs: np.ndarray, table) -> tuple[int, int, int]:
    """Best (table row, level, differing bits) for one scanline."""
    reps = WIDTH // table.width + 1
    levels = np.arange(256, dtype=np.int32)[:, None]
    best = (10**9, -1, -1)
    for r in range(table.height):
        th = np.tile(table.threshold_matrix[r], reps)[:WIDTH][None, :]
        err = np.count_nonzero(((255 - levels) > th) ^ obs[None, :], axis=1)
        i = int(np.argmin(err))
        if err[i] < best[0]:
            best = (int(err[i]), r, i)
    return best[1], best[2], best[0]


def main() -> int:
    """Print the measured ink level per plane for each fixture."""
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    print(f"{'fixture':8s} {'ebene':5s} {'TabZeile':>8s} {'Stufe':>5s} {'Tinte':>5s} {'Fehler':>7s} {'Dichte':>7s}")
    print("-" * 56)
    for name in sys.argv[1:] or ["red", "grn", "blu", "cyn", "mag", "yel", "blk"]:
        for plane, obs in sorted(plane_first_rows(name).items()):
            row, level, err = solve(obs, tables[plane])
            print(
                f"{name:8s} {plane:5s} {row:8d} {level:5d} {255 - level:5d} {err:7d} {obs.mean():7.4f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
