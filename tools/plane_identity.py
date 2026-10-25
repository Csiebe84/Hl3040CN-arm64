#!/usr/bin/env python3
"""Test whether CommentData identifies the plane, by comparing bitmaps.

If two fixtures carry the same physical plane, its bitmap must be identical
regardless of how the block is labelled.  Decoding the cs=10 plane of red and
of magenta and hashing the first rows settles whether the labels can be
trusted, which every colour measurement so far depends on.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LINE_BYTES = 640
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit}


def first_bitmaps(name: str) -> dict[tuple[int, int], str]:
    """Hash of the first scanline per (CommentData, comp_size)."""
    out: dict[tuple[int, int], str] = {}
    for b in decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes())):
        key = (b.plane, b.header.comp_size)
        if key in out or not b.entries:
            continue
        dec = DECODERS.get(b.header.comp_size)
        if dec is None:
            out[key] = "(kein Decoder)"
            continue
        try:
            raw = dec(b.entries[0], LINE_BYTES)
        except rle_decode.RleError:
            out[key] = "(Fehler)"
            continue
        bits = np.unpackbits(np.frombuffer(raw, np.uint8))[:5120]
        out[key] = f"{hashlib.sha256(bits.tobytes()).hexdigest()[:16]} d={bits.mean():.4f}"
    return out


def main() -> int:
    """Print the (CommentData, cs) -> bitmap hash map per fixture."""
    for name in sys.argv[1:] or ["red", "mag", "grn", "blu", "cyn", "yel"]:
        m = first_bitmaps(name)
        parts = "  ".join(f"cd={k[0]},cs={k[1]}: {v}" for k, v in sorted(m.items()))
        print(f"{name:5s} {parts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
