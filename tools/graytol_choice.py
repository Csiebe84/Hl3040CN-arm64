#!/usr/bin/env python3
"""Decide the oracle's grid choice per colour, by byte comparison.

For a solid page of one colour, render it with the port twice: once forcing the
profile grid for every pixel (no replacement) and once forcing the cmyk grid for
every pixel (full replacement).  Byte-compare each against the oracle's gray=OFF
capture.  A match identifies the grid the oracle used for that colour, with no
dither-phase or ink-fit ambiguity.

Usage: graytol_choice.py <colorlist> [--matching Normal|Vivid|None]
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_pipeline_compare import session  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

SW, HEIGHT = 5100, 6564
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID, "None": ColorMatching.NONE}


def build_ppm(c):
    row = bytes(c) * SW
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + row * HEIGHT


def render(ppm, settings, mode):
    """Render `ppm` with replacement forced to `mode` (None/profile/cmyk)."""
    orig = color_lut.gray_replace_table

    def patched(table=color_lut.DEFAULT_TABLE):
        if mode == "cmyk":
            return color_lut._GRAY_REPLACE_TABLE
        return None

    color_lut.gray_replace_table = patched
    try:
        w, h, _mx, pixels = read_ppm(io.BytesIO(ppm))
        out = io.BytesIO()
        filter_page(w, h, pixels, settings, out)
        return session(out.getvalue())
    finally:
        color_lut.gray_replace_table = orig


def main() -> int:
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    settings = PrintSettings()
    settings.page_size = "Letter"
    settings.color_matching = MATCH[matching]
    settings.improve_gray = False
    print(f"# matching={matching} solids={len(colors)}")
    for c in colors:
        ppm = build_ppm(c)
        tmp = Path("/tmp/gc_in.ppm")
        tmp.write_bytes(ppm)
        out = Path("/tmp/gc_out.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(tmp), str(out),
                        "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
        want = session(out.read_bytes())
        prof = render(ppm, settings, "profile")
        cmyk = render(ppm, settings, "cmyk")
        pm = prof == want
        cm = cmyk == want
        pick = "profile" if pm else ("cmyk" if cm else "NEITHER")
        if pm and cm:
            pick = "both"
        print(f"{str(c):>16} d={max(c)-min(c):3d} lenO={len(want)} prof={'OK' if pm else 'x'} "
              f"cmyk={'OK' if cm else 'x'} -> {pick}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
