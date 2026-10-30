#!/usr/bin/env python3
"""Phase-independent ink estimate for uniform pages, oracle ON vs OFF.

For a uniform page each plane is the dither of one constant level, so the
fraction of set bits over a wide window estimates that level (scaled to 0..255)
without needing the dither phase.  Printed next to the port's profile-grid and
cmyk-grid separation for the same colour, this shows which grid the oracle's
gray=OFF replacement produces.

Usage: graytol_mean.py <colorlist> [--matching Normal|Vivid|None]
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

import color_lut  # noqa: E402
from graytol_fullink import plane_bitmap  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT = 5100, 6564
PLANES = ("K", "C", "M", "Y")
PROF = {"Normal": "rgb", "Vivid": "srgb", "None": "cmyk"}


def build_ppm(c):
    row = bytes(c) * SW
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + row * HEIGHT


def ink(c, table):
    a = np.array(c, dtype=np.uint8).reshape(-1)
    k, cc, mm, y = color_lut.rgb_to_cmyk_lut_arr(a, 1, table)
    return [255 - int(k[0]), 255 - int(cc[0]), 255 - int(mm[0]), 255 - int(y[0])]


def mean_ink(name):
    out = []
    for p in PLANES:
        bm = plane_bitmap(name, p)
        if bm is None:
            out.append(None)
            continue
        out.append(int(round(bm[:, 1000:4000].mean() * 255)))
    return out


def main() -> int:
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    prof = color_lut.ColorTable(PROF[matching], improve_gray=True, gray_replace=False)
    cmykg = color_lut.ColorTable("cmyk")
    print(f"# matching={matching}  planes=K,C,M,Y")
    for ci, c in enumerate(colors):
        name = f"mn{ci}"
        ppm = Path(f"/tmp/{name}.ppm")
        ppm.write_bytes(build_ppm(c))
        res = {}
        for g in ("ON", "OFF"):
            dst = Path(f"/tmp/{name}_{g}.xl2hb")
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                            "--matching", matching, "--gray", g], check=True, capture_output=True)
            (FIX / f"{name}_{g}.xl2hb").write_bytes(dst.read_bytes())
            res[g] = mean_ink(f"{name}_{g}")
        print(f"{str(c):>16} d={max(c)-min(c):3d} ON={res['ON']} OFF={res['OFF']}")
        print(f"{'':>16}           prof={ink(c, prof)} cmyk={ink(c, cmykg)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
