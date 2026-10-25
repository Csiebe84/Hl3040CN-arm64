#!/usr/bin/env python3
"""Inspect the BRCD threshold matrices and their internal periodicity.

The oracle's solid-colour planes show a horizontal period of 10, which a
table tiled from 80 (or 24) columns can only produce if its rows are
themselves periodic.  This prints the raw threshold rows so the geometry is
read from the data instead of assumed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import dither  # noqa: E402

LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"


def period_of(row: np.ndarray) -> int | None:
    """Smallest horizontal period of a 1-D row, or None."""
    n = len(row)
    for p in range(1, n // 2 + 1):
        if all(row[i] == row[i % p] for i in range(n)):
            return p
    return None


def main() -> int:
    """Print threshold rows and their periods for each channel."""
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    for ch in "KCMY":
        t = tables[ch]
        m = t.threshold_matrix
        print(f"=== {ch}: {t.width}x{t.height}, dtype {m.dtype} ===")
        print(f"  global: min={m.min()} max={m.max()} mean={m.mean():.1f} distinct={len(np.unique(m))}")
        for r in range(min(3, t.height)):
            row = m[r]
            print(f"  Zeile {r} (Periode {period_of(row)}):")
            print(f"    {row.tolist()}")
        print(f"  vertikale Periode: {period_of(m[:, 0])}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
