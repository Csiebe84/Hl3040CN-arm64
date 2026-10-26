#!/usr/bin/env python3
"""Decode the 20-bit sliding-window RLE used by the cyan plane.

The C plane is stored as ``comp_size=20`` blocks (``encode_c_plane`` packs to
20-bit words); the existing decoders only cover the 12-bit (K/Y) and 10-bit
(M) planes, so the cyan channel of an oracle capture could not be read.  This
decoder mirrors ``decode_12bit`` with the 20-bit opcodes from
``hl3040cn/src/rle.py`` (``emit_run``/``emit_literal_block`` with
``value_bits=20``): 0xF0 long run, 0x80 short run, 0x40 literal, else context
skip repeating the word two positions back.

Usage: decode20.py <name> [plane]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import pclxl  # noqa: E402
from band import decode_blocks  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
WIDTH = 5120
LINE_BYTES = WIDTH // 8
WORD_BITS = 20


def decode_20bit(data: bytes, line_bytes: int) -> bytes:
    """Expand one 20-bit-word RLE entry back to packed 1bpp bytes (MSB first)."""
    total_words = (line_bytes * 8) // WORD_BITS
    out: list[int] = []
    pos = 0

    def count_ext() -> int:
        nonlocal pos
        total = 0
        while pos < len(data) and data[pos] == 0xFF:
            total += 255
            pos += 1
        if pos >= len(data):
            raise ValueError("count extension runs off the end")
        total += data[pos]
        pos += 1
        return total

    while pos < len(data) and len(out) < total_words:
        byte = data[pos]
        if byte >= 0xF0:  # long run, count >= 8, 20-bit value in 3 bytes
            v_hi = byte & 0x0F
            pos += 1
            if pos + 2 > len(data):
                raise ValueError("long run truncated")
            value = (v_hi << 16) | (data[pos] << 8) | data[pos + 1]
            pos += 2
            out.extend([value] * (8 + count_ext()))
        elif byte >= 0x80:  # short run, count 1..7
            count = ((byte >> 4) & 0x07) + 1
            v_hi = byte & 0x0F
            pos += 1
            if pos + 2 > len(data):
                raise ValueError("short run truncated")
            value = (v_hi << 16) | (data[pos] << 8) | data[pos + 1]
            pos += 2
            out.extend([value] * count)
        elif byte >= 0x40:  # literal block, 20-bit groups
            pos += 1
            count = (0x41 + count_ext()) if byte == 0x7F else (byte & 0x3F) + 2
            bits = 0
            for _ in range(count):
                if pos + (bits + 20 + 7) // 8 > len(data):
                    raise ValueError("literal runs off the end")
                value = 0
                for _ in range(20):
                    b = data[pos + (bits >> 3)]
                    value = (value << 1) | ((b >> (7 - (bits & 7))) & 1)
                    bits += 1
                out.append(value)
            pos += (bits + 7) // 8
        else:  # context skip: repeat the word two positions back
            pos += 1
            count = (64 + count_ext()) if byte == 0x3F else byte + 1
            for _ in range(count):
                i = len(out)
                out.append(out[i - 2] if i >= 2 else 0)
                if len(out) >= total_words:
                    break

    packed = bytearray(line_bytes)
    bitpos = 0
    for value in out:
        for k in range(WORD_BITS - 1, -1, -1):
            if bitpos >= line_bytes * 8:
                break
            if (value >> k) & 1:
                packed[bitpos >> 3] |= 1 << (7 - (bitpos & 7))
            bitpos += 1
    return bytes(packed)


def plane_rows(name: str, plane: str, want: int) -> np.ndarray | None:
    """First `want` decoded scanlines of the plane's first block as bool rows."""
    for b in decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes())):
        if b.plane_name != plane or not b.entries:
            continue
        if b.header.comp_size != WORD_BITS:
            return None
        rows = [np.unpackbits(np.frombuffer(decode_20bit(e, LINE_BYTES), np.uint8))[:WIDTH].astype(bool)
                for e in b.entries]
        return np.stack(rows)
    return None


def main() -> int:
    name = sys.argv[1]
    plane = sys.argv[2] if len(sys.argv) > 2 else "C"
    rows = plane_rows(name, plane, 10**6)
    if rows is None:
        print(f"{name}: no {plane} (20-bit) block")
        return 0
    print(f"{name}: {plane} rows={rows.shape[0]} density={rows.mean():.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
