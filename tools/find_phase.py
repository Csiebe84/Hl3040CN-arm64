#!/usr/bin/env python3
"""Recover the oracle's ink level and dither phase for a solid-colour page.

For a solid page every scanline is the same ink level, so the plane is just
the threshold matrix tiled vertically.  A per-row level search therefore
reports a different level on each row whenever the phase is non-zero, which
is exactly what was observed.  This searches level and phase jointly and
requires the match to hold across the whole table cycle.

Because `dither` compares a scalar against a threshold row, all rows for a
given level are computed at once with numpy.
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


def oracle_rows(name: str) -> dict[str, list[bytes]]:
    """Decoded scanline bitmaps per plane, in stream order."""
    blocks = decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes()))
    out: dict[str, list[bytes]] = {}
    for b in blocks:
        dec = rle_decode.decode_10bit if b.header.comp_size == 10 else rle_decode.decode_12bit
        for e in b.entries:
            out.setdefault(b.plane_name, []).append(dec(e, LINE_BYTES))
    return out


def packed_rows(table, level: int) -> list[bytes]:
    """The dithered output of every table row for one ink level."""
    thresholds = table.threshold_matrix
    dots = (255 - level) > thresholds  # (H, W) bool
    return [np.packbits(row)[: LINE_BYTES].tobytes() for row in dots]


def solve(rows: list[bytes], table) -> tuple[int, int, int] | None:
    """Find (level, phase, matched_rows) reproducing `rows`.

    Returns:
        The level, the phase offset, and how many of the table's rows were
        reproduced exactly, or None when nothing matched.
    """
    height = table.height
    cycle = [rows[y] for y in range(min(height, len(rows)))]
    for level in range(256):
        cand = packed_rows(table, level)
        index = {r: t for t, r in enumerate(cand)}
        votes: dict[int, int] = {}
        for y, want in enumerate(cycle):
            t = index.get(want)
            if t is None:
                continue
            phase = (t - y) % height
            votes[phase] = votes.get(phase, 0) + 1
        if not votes:
            continue
        phase, hits = max(votes.items(), key=lambda kv: kv[1])
        if hits == height:
            return level, phase, hits
    return None


def main() -> int:
    """Report the level and phase per plane for each fixture."""
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    for name in sys.argv[1:] or ["red"]:
        print(f"=== {name} ===")
        rows = oracle_rows(name)
        for plane in sorted(rows):
            table = tables[plane]
            got = solve(rows[plane], table)
            if got is None:
                print(f"  {plane}: keine Stufe reproduziert den ganzen Zyklus")
            else:
                level, phase, hits = got
                print(
                    f"  {plane}: Tintenstufe = {level:3d}  Phase = {phase:2d}"
                    f"  ({hits}/{table.height} Zeilen bit-genau)"
                )
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
