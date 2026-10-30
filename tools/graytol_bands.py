#!/usr/bin/env python3
"""Clean BRGray=OFF replacement signal: full-width row-bands, many per page.

Each test colour fills a block of full-width scanlines.  A block spans many
dither periods, so the ON/OFF XOR cannot alias on the phase (unlike narrow-bar
probes).  ON uses the profile grid for every pixel; OFF uses the profile grid
for chromatic pixels and the cmyk grid for the achromatic ones, so the XOR of
a block is ~0 exactly when the colour was not replaced.

Usage: graytol_bands.py <colorlist> [--matching Normal|Vivid|None] [--rows 64]
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


def main() -> int:
    matching = "Normal"
    rows = 64
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    if "--rows" in sys.argv:
        rows = int(sys.argv[sys.argv.index("--rows") + 1])
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    per_page = HEIGHT // rows
    print(f"# matching={matching} rows={rows} colors={len(colors)} per_page={per_page}")
    for p0 in range(0, len(colors), per_page):
        chunk = colors[p0:p0 + per_page]
        body = bytearray()
        for c in chunk:
            body += (bytes(c) * SW) * rows
        used = len(chunk) * rows
        body += (bytes(chunk[-1]) * SW) * (HEIGHT - used)
        name = f"band{p0 // per_page}"
        ppm = Path(f"/tmp/{name}.ppm")
        ppm.write_bytes(b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(body))
        for g in ("ON", "OFF"):
            dst = Path(f"/tmp/{name}_{g}.xl2hb")
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                            "--matching", matching, "--gray", g], check=True, capture_output=True)
            (FIX / f"{name}_{g}.xl2hb").write_bytes(dst.read_bytes())
        on = {p: plane_bitmap(f"{name}_ON", p) for p in PLANES}
        off = {p: plane_bitmap(f"{name}_OFF", p) for p in PLANES}
        for bi, c in enumerate(chunk):
            a, b = bi * rows, (bi + 1) * rows
            diffs = {}
            for p in PLANES:
                if on[p] is None or off[p] is None:
                    diffs[p] = "missing"
                    continue
                h = min(on[p].shape[0], off[p].shape[0])
                if b > h:
                    diffs[p] = "oob"
                    continue
                diffs[p] = int(np.count_nonzero(on[p][a:b] ^ off[p][a:b]))
            total = sum(v for v in diffs.values() if isinstance(v, int))
            area = rows * SW
            frac = total / (4 * area)
            print(f"{str(c):>16} d={max(c)-min(c):3d} total={total} frac={frac:.3f} "
                  f"{'REPLACED' if total > 0 else 'not'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
