#!/usr/bin/env python3
"""Find every (level, table row) that reproduces an oracle scanline exactly.

The oracle plane is compared against the threshold matrix tiled to the full
page width.  Reporting all exact matches settles whether the model
"solid page = threshold matrix at one ink level" holds at all, and if so
which level it implies.
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


def tiled(table, row: int) -> np.ndarray:
    """Threshold row `row` tiled to the full page width, as bits."""
    t = table.threshold_matrix[row % table.height]
    reps = WIDTH // table.width + 1
    return np.tile(t, reps)[:WIDTH]


def main() -> int:
    """Report exact (level, row) matches for the first oracle rows."""
    name = sys.argv[1] if len(sys.argv) > 1 else "red"
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    for plane in (sys.argv[2:] or ["M", "Y"]):
        rows = oracle_rows(name, plane)
        table = tables[plane]
        print(f"=== {name} / {plane} (Tabelle {table.width}x{table.height}) ===")
        for y in range(3):
            want = np.unpackbits(np.frombuffer(rows[y], np.uint8))[:WIDTH]
            hits: list[tuple[int, int, str]] = []
            for row in range(table.height):
                th = tiled(table, row)
                for level in range(256):
                    for pol, ink in (("ink", 255 - level), ("direct", level)):
                        if np.array_equal(ink > th, want.astype(bool)):
                            hits.append((level, row, pol))
            if hits:
                lv = sorted({h[0] for h in hits})
                rw = sorted({h[1] for h in hits})
                print(f"  Zeile {y}: {len(hits)} Treffer  Stufen={lv[:8]}  TabZeilen={rw[:8]}  Pol={sorted({h[2] for h in hits})}")
            else:
                print(f"  Zeile {y}: KEINE exakte Kombination")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
