#!/usr/bin/env python3
"""Per-pixel BRGray=OFF replacement truth table, by direct bitmap comparison.

A pixel is "replaced" exactly when the oracle's output for it differs between
BRGray=ON and BRGray=OFF.  Many probe pixels are laid out as bars on one page
and the oracle is run twice (ON, OFF); the decoded plane bitmaps of the two runs
are compared bar by bar.  The comparison is on identical page structure, so it
needs no ink model and is exact.

Usage: graytol_truth.py <colorlist> [--matching Normal|Vivid|None] [--bars N]
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
    matching = sys.argv[sys.argv.index("--matching") + 1] if "--matching" in sys.argv else "Normal"
    bars = int(sys.argv[sys.argv.index("--bars") + 1]) if "--bars" in sys.argv else 100
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    print(f"# matching={matching} bars={bars} colors={len(colors)}")
    for page0 in range(0, len(colors), bars):
        chunk = colors[page0:page0 + bars]
        step = SW // len(chunk)
        name = f"tt{page0 // bars}"
        ppm = FIX / f"{name}.ppm"
        ppm.write_bytes(build_ppm(chunk))
        for tag in ("ON", "OFF"):
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm),
                            f"/tmp/{name}_{tag}.xl2hb", "--matching", matching, "--gray", tag],
                           check=True, capture_output=True)
            (FIX / f"{name}_{tag}.xl2hb").write_bytes(Path(f"/tmp/{name}_{tag}.xl2hb").read_bytes())
        a = {p: plane_bitmap(f"{name}_ON", p) for p in PLANES}
        b = {p: plane_bitmap(f"{name}_OFF", p) for p in PLANES}
        for i, c in enumerate(chunk):
            x0, x1 = i * step, (i + 1) * step
            diff = 0
            for p in PLANES:
                if a[p] is None or b[p] is None:
                    continue
                hh = min(a[p].shape[0], b[p].shape[0])
                diff += int(np.count_nonzero(a[p][:hh, x0:x1] ^ b[p][:hh, x0:x1]))
            print(f"{str(c):>16} d={max(c)-min(c):3d} replaced={'JA' if diff else 'nein'} diff={diff}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
