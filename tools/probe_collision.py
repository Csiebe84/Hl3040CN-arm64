#!/usr/bin/env python3
"""Probe suspected size collisions found by fuzz_filter.py.

mid_gray RGB(128,128,128) and mixed_128_128_130 RGB(128,128,130) produced the
same payload size.  Either the 2-unit blue difference is legitimately below the
separation's resolution, or the colour is being dropped.  Diff the bytes to
decide, and look at the ink levels the separation actually produced.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FILTER = "/usr/lib/cups/filter/brhl3040cn-filter"
WORK = Path("/mnt/ssd/fuzz")
sys.path.insert(0, "/usr/local/lib/brhl3040cn")

CASES = {
    "mid_gray": (128, 128, 128),
    "mixed_128_128_130": (128, 128, 130),
    "mixed_128_128_160": (128, 128, 160),
    "gray_vs_blue_tint": (120, 128, 136),
}


def render(rgb: tuple[int, int, int]) -> bytes:
    r, g, b = (c / 255 for c in rgb)
    ps = (
        "%!PS-Adobe-3.0\n%%Pages: 1\n"
        f"{r} {g} {b} setrgbcolor 0 0 595 842 rectfill\nshowpage\n%%EOF\n"
    )
    src = WORK / "probe.ps"
    src.write_bytes(ps.encode())
    p = subprocess.run(
        [FILTER, "1", "probe", "probe", "1", "BRResolution=600x2400dpi BRGray=OFF", str(src)],
        capture_output=True,
        timeout=180,
    )
    return p.stdout


def main() -> int:
    out = {}
    for name, rgb in CASES.items():
        data = render(rgb)
        out[name] = data
        print(f"  {name:22s} rgb{rgb}  {len(data):>9} B")

    print()
    base = out["mid_gray"]
    for name, data in out.items():
        if name == "mid_gray":
            continue
        same = data == base
        print(f"  mid_gray vs {name:22s} byte-identical: {same}")
        if not same:
            n = min(len(base), len(data))
            first = next((i for i in range(n) if base[i] != data[i]), None)
            print(f"      first diff @ {first}  (len {len(base)} vs {len(data)})")

    # What ink does the separation assign?  Read it straight from the LUT.
    print("\n  separation (ink 0..255):")
    try:
        from transforms.color_lut import rgb_to_cmyk_ink  # type: ignore

        for name, rgb in CASES.items():
            print(f"    {name:22s} {rgb} -> C,M,Y,K = {rgb_to_cmyk_ink(*rgb)}")
    except Exception as exc:  # noqa: BLE001
        print(f"    could not import separation: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
