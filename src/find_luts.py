#!/usr/bin/env python3
"""Locate and name the HL-3040CN colour LUT blobs inside its filter binary.

The filter keeps a set of 17x17x17 RGB-to-CMYK grids, one per colour-matching
profile / grey-handling / toner-save combination.  They are plain arrays in
the binary with no symbol table, so they are found by structure: every value
is a byte-wide ink amount, the white corner is all zeros, and a real grid
varies smoothly from entry to entry while code does not.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np

LUT_DIM = 17
LUT_ENTRIES = LUT_DIM**3
LUT_BYTES = LUT_ENTRIES * 8

# The HL-4150CDN driver's grid offsets, used as a cross-check: two of its
# grids (colour-matching None, with and without grey handling) are byte-equal
# to grids in the 3040 binary.
HL4150_LUTS = {
    "rgb_default": 0x92D58, "rgb_density2": 0xAFB18, "rgb_glossy": 0xA6138,
    "rgb_ig_default": 0xF3057, "rgb_ig_density2": 0x10FE17, "rgb_ig_glossy": 0x106437,
    "srgb_default": 0xC2ED7, "srgb_density2": 0xDFC77, "srgb_glossy": 0xD6297,
    "srgb_ig_default": 0x1231D6, "srgb_ig_density2": 0x13FF76, "srgb_ig_glossy": 0x136596,
    "cmyk_default": 0x32543, "cmyk_density2": 0x4F343, "cmyk_glossy": 0x45943,
    "cmyk_ig_default": 0x62742, "cmyk_ig_density2": 0x7F542, "cmyk_ig_glossy": 0x75B42,
}


def unpack(raw: bytes, offset: int) -> np.ndarray:
    """Unpack a packed LUT blob into (4913, 4) int32 CMYK."""
    packed = np.frombuffer(raw[offset : offset + LUT_BYTES], dtype=np.int32).reshape(-1, 2)
    out = np.empty((LUT_ENTRIES, 4), dtype=np.int32)
    out[:, 0] = packed[:, 0] & 0xFFFF
    out[:, 1] = packed[:, 0] >> 16
    out[:, 2] = packed[:, 1] & 0xFFFF
    out[:, 3] = packed[:, 1] >> 16
    return out


def smoothness(grid: np.ndarray) -> float:
    """Mean absolute difference between neighbouring grid entries.

    A colour grid changes slowly across the cube, so this stays small; a
    block of machine code jumps around and scores high.
    """
    flat = grid.astype(np.int64).ravel()
    return float(np.abs(np.diff(flat)).mean())


def scan(raw: bytes) -> list[int]:
    """Find candidate LUT offsets at either byte parity.

    A window qualifies when every byte-wide value fits in a byte and the
    white corner (last entry) is zero; sliding windows are then collapsed
    to their leftmost start.
    """
    hits: list[int] = []
    for parity in (0, 1):
        body = raw[parity : len(raw) - ((len(raw) - parity) % 2)]
        u16 = np.frombuffer(body, dtype="<u2")
        n = len(u16)
        need = LUT_ENTRIES * 4
        if n < need:
            continue
        span = n - need + 1
        fits = np.ones(span, dtype=bool)
        for k in range(4):
            fits &= u16[k : k + span] <= 255
        white_zero = np.ones(span, dtype=bool)
        for k in range(4):
            white_zero &= u16[need - 4 + k : need - 4 + k + span] == 0
        for index in np.nonzero(fits & white_zero)[0]:
            hits.append(2 * int(index) + parity)
    hits.sort()
    # Collapse overlapping windows: keep the first start of each cluster.
    kept: list[int] = []
    for hit in hits:
        if kept and hit - kept[-1] < LUT_BYTES:
            continue
        kept.append(hit)
    return kept


def main() -> None:
    """Report every plausible grid, its smoothness and any exact 4150 match."""
    root = Path(__file__).resolve().parent.parent
    raw = (root / "ref" / "brhl3040cnfilter.bin").read_bytes()
    ref = (root / "ref" / "brhl4150cdnfilter.bin").read_bytes()

    ref_by_hash: dict[str, list[str]] = {}
    for name, off in HL4150_LUTS.items():
        digest = hashlib.sha256(ref[off : off + LUT_BYTES]).hexdigest()[:16]
        ref_by_hash.setdefault(digest, []).append(name)

    print(f"{'offset':>10s} {'smooth':>8s}  black       white    match")
    for off in scan(raw):
        grid = unpack(raw, off)
        digest = hashlib.sha256(raw[off : off + LUT_BYTES]).hexdigest()[:16]
        black = grid[0].tolist()
        white = grid[LUT_ENTRIES - 1].tolist()
        match = ",".join(ref_by_hash.get(digest, []))
        print(
            f"0x{off:08x} {smoothness(grid):8.1f}  {str(black):11s} {str(white):8s} {match}"
        )


if __name__ == "__main__":
    main()
