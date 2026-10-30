#!/usr/bin/env python3
"""Characterise the remaining Stage-2 (pattern encoder) divergence.

Stage 1 is byte-identical on every fixture.  On the gradient ramps only the
Stage-2 tokenisation differs: the oracle picks a longer stride-3/4 pattern
where the port emits mode-3 plus literals (see logs/fine_transition.md).

This tool does not guess a fix.  It answers, over the *whole* ramp:

  * how many lines differ, and by how many bytes;
  * whether the oracle's entry is a valid re-encoding of the same Stage-1
    bytes (i.e. the divergence is purely "shorter encoding exists");
  * which token sequence the oracle starts with where the port starts
    differently, so the rule can be derived from data rather than folklore.

Usage: .venv312/bin/python tools/stage2_diag.py [fixture]
"""
from __future__ import annotations

import io
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT / "src"), str(ROOT / "hl3040cn" / "src"), str(ROOT / "tools")):
    sys.path.insert(0, p)

import band  # noqa: E402
import pclxl  # noqa: E402
from fine_decode import decode_stage2  # noqa: E402
from fine_encoder import compress_pattern_encode  # noqa: E402
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import ColorMatching, PrintSettings, Resolution  # noqa: E402

FIX = Path("/mnt/ssd/finecmp")
SW, HEIGHT, BARS = 5100, 6564, 60


def session(data: bytes) -> bytes:
    a = data.find(b") BROTHER XL2HB;1;0\n")
    return data[a:] if a >= 0 else data


def entries(data: bytes) -> dict[str, dict[int, bytes]]:
    out: dict[str, dict[int, bytes]] = {}
    for b in band.decode_blocks(pclxl.parse(data)):
        for k, e in enumerate(b.entries):
            out.setdefault(b.plane_name, {})[b.start_line + k] = bytes(e)
    return out


def build_gray_ramp() -> bytes:
    values = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
    step = SW // BARS
    row = bytearray()
    for v in values:
        row += bytes((v, v, v)) * step
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    fixture = sys.argv[1] if len(sys.argv) > 1 else "gray"
    ppm = build_gray_ramp()
    (FIX / f"{fixture}.ppm").write_bytes(ppm)

    st = PrintSettings()
    st.page_size = "Letter"
    st.color_matching = ColorMatching.NORMAL
    st.resolution = Resolution.FINE
    st.improve_gray = False

    w, h, _m, px = read_ppm(io.BytesIO(ppm))
    out = io.BytesIO()
    filter_page(w, h, px, st, out)

    oracle = entries(session((FIX / f"{fixture}_or.xl2hb").read_bytes()))
    port = entries(session(out.getvalue()))

    print(f"fixture={fixture}  planes={sorted(oracle)}")
    for plane in sorted(oracle):
        o, p = oracle[plane], port.get(plane, {})
        bad = [r for r in sorted(o) if o[r] != p.get(r)]
        if not bad:
            print(f"  {plane}: IDENTICAL ({len(o)} lines)")
            continue
        d_bytes = sum(len(o[r]) - len(p.get(r, b"")) for r in bad)
        # Is the oracle entry a valid re-encoding of the same Stage-1 stream?
        same_s1 = 0
        oracle_is_reencode = 0
        for r in bad:
            s1 = decode_stage2(o[r])
            if decode_stage2(p.get(r, b"")) == s1:
                same_s1 += 1
            if compress_pattern_encode(s1) == o[r]:
                oracle_is_reencode += 1
        print(f"  {plane}: {len(bad)}/{len(o)} lines differ, "
              f"oracle is {d_bytes} B smaller; "
              f"same Stage-1 on {same_s1}/{len(bad)}; "
              f"oracle == re-encode(s1) on {oracle_is_reencode}/{len(bad)}")

        # Where do they first diverge?  Collect the token at that point.
        first_tokens: Counter[tuple[int, int]] = Counter()
        for r in bad[:200]:
            a, b = o[r], p.get(r, b"")
            n = min(len(a), len(b))
            i = next((k for k in range(n) if a[k] != b[k]), n)
            if i < n:
                first_tokens[(a[i], b[i])] += 1
        top = ", ".join(f"or={a:#04x}/port={b:#04x}x{c}" for (a, b), c in first_tokens.most_common(6))
        print(f"    first differing token: {top or '(length only)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
