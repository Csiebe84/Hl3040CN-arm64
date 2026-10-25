#!/usr/bin/env python3
"""Measure ink level per plane in both streams with one method.

Decoding both the oracle fixture and the native output with the same decoder
and the same level solver removes any doubt about which side a difference
comes from.  A plane is described by its word width, its first-row density and
the (table row, ink level) that reproduces that row.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import dither  # noqa: E402
import pclxl  # noqa: E402
import pipeline  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import PrintSettings  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
WIDTH = 5120
LINE_BYTES = WIDTH // 8
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit}


def first_rows(blob: bytes) -> dict[tuple[str, int], np.ndarray]:
    """First decoded scanline per (plane, word width), as bool arrays."""
    out: dict[tuple[str, int], np.ndarray] = {}
    for b in decode_blocks(pclxl.parse(blob)):
        key = (b.plane_name, b.header.comp_size)
        if key in out or not b.entries:
            continue
        dec = DECODERS.get(b.header.comp_size)
        if dec is None:
            continue
        try:
            raw = dec(b.entries[0], LINE_BYTES)
        except rle_decode.RleError:
            continue
        out[key] = np.unpackbits(np.frombuffer(raw, np.uint8))[:WIDTH].astype(bool)
    return out


def solve(obs: np.ndarray, table) -> tuple[int, int, int]:
    """Best (table row, ink level, differing bits) for one scanline."""
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


def report(label: str, blob: bytes, tables) -> None:
    """Print one line per plane for one stream."""
    for (plane, cs), obs in sorted(first_rows(blob).items()):
        row, level, err = solve(obs, tables[plane])
        print(
            f"  {label:7s} {plane}(cs={cs:2d})  TabZeile={row:3d}  Stufe={level:3d}"
            f"  Tinte={255 - level:3d}  Fehler={err:5d}  Dichte={obs.mean():.4f}"
        )


def main() -> int:
    """Compare oracle and native plane levels for each fixture."""
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    for name in sys.argv[1:] or ["red"]:
        print(f"=== {name} ===")
        report("ORACLE", (FIX / f"{name}.xl2hb").read_bytes(), tables)
        w, h, _mx, px = read_ppm(io.BytesIO((FIX / f"{name}.ppm").read_bytes()))
        s = PrintSettings()
        s.page_size = "Letter"
        buf = io.BytesIO()
        pipeline.filter_page(w, h, px, s, buf)
        report("NATIVE", buf.getvalue(), tables)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
