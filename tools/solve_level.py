#!/usr/bin/env python3
"""Solve the oracle's ink level and phase per plane, over the whole cycle.

For a solid-colour page every scanline carries the same ink level, so the
plane is the threshold matrix tiled vertically.  This searches the level and
the vertical phase jointly against the whole table cycle and reports the total
number of differing bits, which is the honest error of the model.  Both ink
polarities are tried because the comparison direction is not yet pinned.
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


def oracle_rows(name: str, plane: str) -> list[np.ndarray]:
    """Decoded scanlines of one plane as bool arrays."""
    blocks = decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes()))
    out: list[np.ndarray] = []
    for b in blocks:
        if b.plane_name != plane:
            continue
        dec = rle_decode.decode_10bit if b.header.comp_size == 10 else rle_decode.decode_12bit
        for e in b.entries:
            out.append(np.unpackbits(np.frombuffer(dec(e, LINE_BYTES), np.uint8))[:WIDTH].astype(bool))
    return out


def tiled_rows(table) -> np.ndarray:
    """The threshold matrix tiled horizontally to the page width."""
    reps = WIDTH // table.width + 1
    return np.tile(table.threshold_matrix, (1, reps))[:, :WIDTH]


def solve(rows: list[np.ndarray], table) -> tuple[int, int, int, str]:
    """Best (level, phase, differing bits, polarity) over the whole cycle."""
    th = tiled_rows(table)
    h = table.height
    obs = np.stack(rows[:h]) if len(rows) >= h else np.stack(rows)
    levels = np.arange(256, dtype=np.int32)[:, None, None]
    best = (10**9, -1, -1, "")
    for pol in ("ink", "direct"):
        cmp = th[None, :, :] if pol == "ink" else th[None, :, :]
        vals = levels if pol == "direct" else 255 - levels
        dots = vals > cmp  # (256, h, W)
        for phase in range(h):
            rolled = np.roll(obs, -phase, axis=0)
            err = np.count_nonzero(dots ^ rolled[None, :, :], axis=(1, 2))
            i = int(np.argmin(err))
            if err[i] < best[0]:
                best = (int(err[i]), i, phase, pol)
    return best[1], best[2], best[0], best[3]


def main() -> int:
    """Report the solved level/phase per plane for each fixture."""
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    for name in sys.argv[1:] or ["red"]:
        print(f"=== {name} ===")
        for plane in ("M", "Y"):
            rows = oracle_rows(name, plane)
            table = tables[plane]
            level, phase, err, pol = solve(rows, table)
            total = WIDTH * min(len(rows), table.height)
            print(
                f"  {plane}: Stufe={level:3d}  Phase={phase:2d}  Polaritaet={pol:6s}"
                f"  Fehler={err}/{total} Bit ({100 * err / total:.3f}%)"
            )
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
