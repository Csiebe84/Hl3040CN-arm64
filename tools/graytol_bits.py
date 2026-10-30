#!/usr/bin/env python3
"""Exact per-pixel BRGray=OFF replacement signal from raw bitmaps.

For a non-replaced pixel the gray=ON and gray=OFF paths use the same colour
grid, so the four planes are bit-identical.  For a replaced pixel the OFF path
goes through the cmyk grid and the bits differ.  Comparing the raw plane bits
per bar is therefore an exact, noise-free "replaced?" signal -- unlike
comparing fitted ink values, which carries a +/-2 dither-phase error.

Usage: graytol_bits.py <name> <probefile> [--matching Normal|Vivid|None]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

from graytol_fullink import plane_bitmap  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT = 5100, 6564
PLANES = ("K", "C", "M", "Y")


def build_ppm(colors):
    step = SW // len(colors)
    row = bytearray()
    for c in colors:
        row += bytes(c) * step
    row += bytes(colors[-1]) * (SW - len(row) // 3)
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    name = sys.argv[1]
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    colors = []
    for line in Path(sys.argv[2]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    step = SW // len(colors)
    ppm = Path(f"/tmp/{name}.ppm")
    ppm.write_bytes(build_ppm(colors))
    for g in ("ON", "OFF"):
        dst = Path(f"/tmp/{name}_{g}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", matching, "--gray", g], check=True, capture_output=True)
        (FIX / f"{name}_{g}.xl2hb").write_bytes(dst.read_bytes())

    on = {p: plane_bitmap(f"{name}_ON", p) for p in PLANES}
    off = {p: plane_bitmap(f"{name}_OFF", p) for p in PLANES}
    print(f"# {name} matching={matching} bars={len(colors)}")
    for bi, c in enumerate(colors):
        a = bi * step
        b = (bi + 1) * step
        diffs = {}
        for p in PLANES:
            o1, o2 = on[p], off[p]
            if o1 is None and o2 is None:
                continue
            if o1 is None or o2 is None:
                diffs[p] = "missing"
                continue
            h = min(o1.shape[0], o2.shape[0])
            diffs[p] = int(np.count_nonzero(o1[:h, a:b] ^ o2[:h, a:b]))
        total = sum(v for v in diffs.values() if isinstance(v, int))
        repl = total > 0
        print(f"{str(c):>16} d={max(c)-min(c):3d} diffs={diffs} total={total} "
              f"{'REPLACED' if repl else 'not'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
