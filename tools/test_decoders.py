#!/usr/bin/env python3
"""Validate the RLE decoders against the port's encoders by round-trip.

A decoder is only trustworthy if re-encoding what it produced yields the
original bytes.  This pins both word widths (12-bit K/Y, 10-bit M) and the
oracle's real payloads, so a later colour measurement cannot rest on a
mis-decoded plane.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from plane_encoders import encode_m_plane_10, encode_plane  # noqa: E402
from band import decode_blocks  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LINE_BYTES = 640  # 5120 px / 8


def roundtrip_12bit() -> bool:
    """Decode and re-encode a synthetic 12-bit plane."""
    pat = bytes(range(80)) * 8
    enc = encode_plane(pat, "Y")
    if not enc:
        print("  12-bit: encoder produced empty output")
        return False
    dec = rle_decode.decode_12bit(enc, len(pat))
    re = encode_plane(dec, "Y")
    ok = re == enc
    print(f"  12-bit round-trip: {'OK' if ok else 'FAIL'}  ({len(enc)} B)")
    return ok


def roundtrip_10bit() -> bool:
    """Decode and re-encode a synthetic 10-bit M plane."""
    pat = bytes((0b10111101, 0b11) * 80)[:160]
    enc = encode_m_plane_10(pat)
    if not enc:
        print("  10-bit: encoder produced empty output")
        return False
    dec = rle_decode.decode_10bit(enc, len(pat))
    re = encode_m_plane_10(dec)
    ok = re == enc
    print(f"  10-bit round-trip: {'OK' if ok else 'FAIL'}  ({len(enc)} B)")
    return ok


def oracle_m_lines() -> bool:
    """Decode the oracle's real M-plane payloads without raising."""
    blocks = decode_blocks(pclxl.parse((FIX / "red.xl2hb").read_bytes()))
    m_blocks = [b for b in blocks if b.plane_name == "M"]
    ok = 0
    bad = 0
    for b in m_blocks[:3]:
        for e in b.entries[:40]:
            try:
                out = rle_decode.decode_10bit(e, LINE_BYTES)
                if len(out) != LINE_BYTES:
                    bad += 1
                else:
                    ok += 1
            except rle_decode.RleError:
                bad += 1
    print(f"  oracle M-Zeilen dekodiert: {ok} ok, {bad} fehlerhaft")
    return bad == 0


def main() -> int:
    """Run all decoder checks and report a summary."""
    print("Decoder-Validierung:")
    results = [roundtrip_12bit(), roundtrip_10bit(), oracle_m_lines()]
    print()
    print("GESAMT:", "OK" if all(results) else "FEHLER")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
