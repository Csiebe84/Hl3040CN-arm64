#!/usr/bin/env python3
"""Decode the stage-2 (pattern) layer of the Fine-mode encoder.

`fine_encoder.compress_pattern_encode` is the second of Fine mode's two
compression stages.  This is its inverse: it expands an entry payload back to
the stage-1 byte stream, which is what makes it possible to see *why* the
port's Fine output is larger than Brother's — stage 1 emits one token per
input byte for a constant scanline, and stage 2 then cannot compress the run.

The inverse of stage 1 is deliberately **not** provided: its opcode space
overlaps (a byte can be a white/black run head *and* a mixed-byte token), so a
hand-written inverse desynchronises.  `compress_pattern_encode(decode(e)) == e`
is the round-trip check that keeps this decoder honest; run it with
`--check` against real streams.

Usage: fine_decode.py <stream.xl2hb> [--check]
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))


def _ext(data: bytes, i: int) -> tuple[int, int]:
    """Read a 0xFF-terminated count extension."""
    total = 0
    while i < len(data) and data[i] == 0xFF:
        total += 0xFF
        i += 1
    if i >= len(data):
        msg = "count extension runs off the end"
        raise ValueError(msg)
    total += data[i]
    return total, i + 1


# Pattern header byte -> (mode, match_count).  Extended headers (0x03, 0x07,
# 0x09, 0x0B, 0x0D, 0x0F) read a count extension and are handled inline.
_SIMPLE = {
    0x00: (0, 3), 0x01: (0, 4), 0x02: (0, 5),
    0x04: (2, 2), 0x05: (2, 3), 0x06: (2, 4),
    0x08: (1, 3),
    0x0A: (3, 3),
    0x0C: (4, 2),
    0x0E: (5, 2),
}
_EXT = {0x03: (0, 6), 0x07: (2, 5), 0x09: (1, 4), 0x0B: (3, 4), 0x0D: (4, 3), 0x0F: (5, 3)}


def decode_stage2(data: bytes) -> bytes:
    """Expand a stage-2 entry payload back to the stage-1 byte stream."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        i += 1
        if b >= 0x10:  # literal pass-through from stage 1
            out.append(b)
            continue
        if b in _SIMPLE:
            mode, mc = _SIMPLE[b]
        elif b in _EXT:
            base_mode, base_mc = _EXT[b]
            extra, i = _ext(data, i)
            mode, mc = base_mode, base_mc + extra
        else:
            msg = f"unknown stage-2 header {b:#04x} at {i - 1}"
            raise ValueError(msg)

        if mode == 0:  # stride-1 repeat: p0 * mc
            p0 = data[i]
            i += 1
            out.extend([p0] * mc)
        elif mode == 1:  # stride-2 half: (p0, x) * mc
            p0 = data[i]
            i += 1
            for _ in range(mc):
                out.append(p0)
                out.append(data[i])
                i += 1
        elif mode == 2:  # stride-2 full: (p0, p1) * mc
            p0, p1 = data[i], data[i + 1]
            i += 2
            for _ in range(mc):
                out.append(p0)
                out.append(p1)
        elif mode == 3:  # stride-3 third: (p0, x, y) * mc
            p0 = data[i]
            i += 1
            for _ in range(mc):
                out.append(p0)
                out.append(data[i])
                out.append(data[i + 1])
                i += 2
        elif mode == 4:  # stride-3 two-thirds: (p0, p1, x) * mc
            p0, p1 = data[i], data[i + 1]
            i += 2
            for _ in range(mc):
                out.append(p0)
                out.append(p1)
                out.append(data[i])
                i += 1
        else:  # mode 5: stride-3 full: (p0, p1, p2) * mc
            p0, p1, p2 = data[i], data[i + 1], data[i + 2]
            i += 3
            for _ in range(mc):
                out.append(p0)
                out.append(p1)
                out.append(p2)
    return bytes(out)


def main() -> int:
    """Decode every Fine entry in a stream, or round-trip-check them."""
    import band
    import pclxl
    from fine_encoder import compress_pattern_encode
    from ramp_pipeline_compare import session

    args = sys.argv[1:]
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    if not args:
        print(__doc__)
        return 2
    blob = session(Path(args[0]).read_bytes())
    blocks = band.decode_blocks(pclxl.parse(blob))

    # Stage 2 only exists in Fine mode; a Normal (600 dpi) capture stores its
    # planes as 10/12/20-bit RLE and would desynchronise the decoder.  Refuse
    # it up front instead of failing with a confusing IndexError mid-stream.
    normal = [b for b in blocks if b.header.comp_size != 0]
    if normal:
        sizes = sorted({b.header.comp_size for b in normal})
        print(
            f"not a Fine-mode stream: {len(normal)}/{len(blocks)} blocks carry "
            f"comp_size={sizes} (Normal 600 dpi RLE), which stage 2 cannot decode",
        )
        return 2

    total = checked = ok = 0
    for block in blocks:
        for entry in block.entries:
            total += 1
            try:
                stage1 = decode_stage2(entry)
            except (ValueError, IndexError) as exc:
                print(f"plane {block.plane} start {block.start_line}: {type(exc).__name__}: {exc}")
                continue
            if check:
                checked += 1
                if compress_pattern_encode(stage1) == entry:
                    ok += 1
                else:
                    print(f"ROUND-TRIP FAIL plane {block.plane} start {block.start_line}")
    if check:
        print(f"{ok}/{checked} entries round-trip (of {total} decoded)")
        return 0 if ok == checked else 1
    print(f"decoded {total} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
