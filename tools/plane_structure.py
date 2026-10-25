#!/usr/bin/env python3
"""Describe the raw structure of an oracle plane: period, density, pattern.

Before trusting any level/phase model, establish what the plane actually
looks like: how many distinct scanlines it has, whether they repeat with the
dither table's period, and what the horizontal pattern of one line is.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
WIDTH = 5120
LINE_BYTES = WIDTH // 8


def rows_for(name: str, plane: str) -> list[bytes]:
    """All decoded scanlines of one plane, in stream order."""
    blocks = decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes()))
    out: list[bytes] = []
    for b in blocks:
        if b.plane_name != plane:
            continue
        dec = rle_decode.decode_10bit if b.header.comp_size == 10 else rle_decode.decode_12bit
        out.extend(dec(e, LINE_BYTES) for e in b.entries)
    return out


def density(line: bytes) -> float:
    """Fraction of set bits in a packed 1bpp line."""
    return float(np.unpackbits(np.frombuffer(line, np.uint8)).mean())


def main() -> int:
    """Report period, distinct rows and first-line pattern per plane."""
    name = sys.argv[1] if len(sys.argv) > 1 else "red"
    for plane in (sys.argv[2:] or ["M", "Y"]):
        rows = rows_for(name, plane)
        if not rows:
            print(f"{plane}: keine Zeilen")
            continue
        uniq = Counter(rows)
        print(f"=== {name} / {plane}: {len(rows)} Zeilen, {len(uniq)} verschiedene ===")
        print(f"  Dichte Zeile 0..4: " + " ".join(f"{density(r):.3f}" for r in rows[:5]))

        # Look for the smallest period p where rows repeat, up to 120.
        period = None
        for p in range(1, 121):
            if len(rows) > 2 * p and all(rows[i] == rows[i % p] for i in range(0, min(len(rows), 8 * p))):
                period = p
                break
        print(f"  kleinste Periode: {period if period else 'keine <= 120'}")

        # Horizontal pattern of line 0: first 96 bits.
        bits = np.unpackbits(np.frombuffer(rows[0], np.uint8))[:96]
        print(f"  Zeile 0, Bit 0..95: {''.join(str(b) for b in bits)}")

        # Smallest horizontal period of line 0 over the full width.
        hper = None
        b0 = np.unpackbits(np.frombuffer(rows[0], np.uint8))
        for p in range(1, 200):
            if np.array_equal(b0, np.tile(b0[:p], len(b0) // p + 1)[: len(b0)]):
                hper = p
                break
        print(f"  horizontale Periode Zeile 0: {hper if hper else 'keine <= 199'}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
