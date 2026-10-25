#!/usr/bin/env python3
"""Check the port's encoders against Brother's by re-encoding oracle planes.

Decode an oracle plane to its bitmap, re-encode it with the port's encoder for
that plane's word width, and compare with the oracle's original bytes.  A
mismatch means the encoder differs from Brother's; a match means the encoder is
faithful and any size difference comes from the bitmap, i.e. from colour
separation.  This separates an encoder defect from a colour defect.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402
from plane_encoders import encode_m_plane_10, encode_plane  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LINE_BYTES = 640


def check(name: str, plane: str, limit: int) -> None:
    """Re-encode the first `limit` lines of one oracle plane and compare."""
    blocks = decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes()))
    sel = [b for b in blocks if b.plane_name == plane]
    if not sel:
        print(f"  {plane}: keine Bloecke")
        return
    is_m = sel[0].header.comp_size == 10
    dec = rle_decode.decode_10bit if is_m else rle_decode.decode_12bit
    enc = encode_m_plane_10 if is_m else (lambda d: encode_plane(d, plane))
    same = diff = 0
    shown = 0
    for b in sel[:2]:
        for e in b.entries[:limit]:
            bitmap = dec(e, LINE_BYTES)
            mine = enc(bitmap)
            if mine == e:
                same += 1
            else:
                diff += 1
                if shown < 3:
                    shown += 1
                    print(f"    ABWEICHUNG: oracle={len(e)}B {e.hex()[:48]}")
                    print(f"                port  ={len(mine)}B {mine.hex()[:48]}")
    width = sel[0].header.comp_size
    print(f"  {plane} (cs={width}): {same} identisch, {diff} abweichend")


def main() -> int:
    """Re-encode oracle planes for every fixture given."""
    for name in sys.argv[1:] or ["red"]:
        print(f"=== {name} ===")
        check(name, "Y", 40)
        check(name, "M", 40)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
