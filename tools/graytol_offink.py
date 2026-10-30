#!/usr/bin/env python3
"""Oracle gray=OFF ink per solid colour, with a wide-window exact fit.

Runs one oracle capture per colour at gray=OFF, decodes each plane and recovers
its constant ink with the bit-exact fit over a 400-column window.  Prints the
recovered ink next to the port's profile-grid and cmyk-grid separation.

Usage: graytol_offink.py <colorlist> [--matching Normal|Vivid|None] [--height N]
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
import dither  # noqa: E402
from graytol_fullink import plane_bitmap  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
SW = 5100
PLANES = ("K", "C", "M", "Y")
PROF = {"Normal": "rgb", "Vivid": "srgb", "None": "cmyk"}


def main() -> int:
    matching = "Normal"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    height = 6564
    if "--height" in sys.argv:
        height = int(sys.argv[sys.argv.index("--height") + 1])
    colors = []
    for line in Path(sys.argv[1]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    prof = color_lut.ColorTable(PROF[matching], improve_gray=True, gray_replace=False)
    cmykg = color_lut.ColorTable("cmyk")

    def ink(c, t):
        a = np.array(c, dtype=np.uint8).reshape(-1)
        k, cc, mm, y = color_lut.rgb_to_cmyk_lut_arr(a, 1, t)
        return [255 - int(k[0]), 255 - int(cc[0]), 255 - int(mm[0]), 255 - int(y[0])]

    print(f"# matching={matching} height={height}")
    for ci, c in enumerate(colors):
        name = f"oi{ci}"
        row = bytes(c) * SW
        ppm = Path(f"/tmp/{name}.ppm")
        ppm.write_bytes(b"P6\n%d %d\n255\n" % (SW, height) + row * height)
        dst = Path(f"/tmp/{name}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", matching, "--gray", "OFF"], check=True, capture_output=True)
        (FIX / f"{name}.xl2hb").write_bytes(dst.read_bytes())
        obs = {}
        for p in PLANES:
            bm = plane_bitmap(name, p)
            if bm is None:
                continue
            ph = find_phase(bm, tables[p], 2000, 2400)
            obs[p] = solve_window(bm, tables[p], 2000, 2400, ph)[0]
        o = [obs[p] for p in PLANES if p in obs]
        print(f"{str(c):>16} d={max(c)-min(c):3d} OFF={o} prof={ink(c, prof)} cmyk={ink(c, cmykg)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
