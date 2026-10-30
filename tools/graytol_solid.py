#!/usr/bin/env python3
"""Unambiguous replacement signal: one full-page solid per colour.

Runs a page filled with a single colour through the oracle at gray=ON and
gray=OFF and compares the four planes bit for bit.  ON and OFF share the
colour grid, so the only difference is the per-pixel achromatic replacement:
non-zero means the pixel was replaced.  A whole-page solid has no bar edges,
so the dither phase cannot alias the signal (unlike narrow-bar probes).

Usage: graytol_solid.py <colorlist> [--matching Normal|Vivid|None]
   colorlist: lines "R G B"
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


def build_ppm(c):
    row = bytes(c) * SW
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + row * HEIGHT


def main() -> int:
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    print(f"# matching={matching} solids={len(colors)}")
    for ci, c in enumerate(colors):
        name = f"sol{ci}"
        ppm = Path(f"/tmp/{name}.ppm")
        ppm.write_bytes(build_ppm(c))
        for g in ("ON", "OFF"):
            dst = Path(f"/tmp/{name}_{g}.xl2hb")
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                            "--matching", matching, "--gray", g], check=True, capture_output=True)
            (FIX / f"{name}_{g}.xl2hb").write_bytes(dst.read_bytes())
        on = {p: plane_bitmap(f"{name}_ON", p) for p in PLANES}
        off = {p: plane_bitmap(f"{name}_OFF", p) for p in PLANES}
        diffs = {}
        for p in PLANES:
            if on[p] is None or off[p] is None:
                diffs[p] = "missing"
                continue
            h = min(on[p].shape[0], off[p].shape[0])
            diffs[p] = int(np.count_nonzero(on[p][:h] ^ off[p][:h]))
        total = sum(v for v in diffs.values() if isinstance(v, int))
        print(f"{str(c):>16} d={max(c)-min(c):3d} diffs={diffs} total={total} "
              f"{'REPLACED' if total > 0 else 'not'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
