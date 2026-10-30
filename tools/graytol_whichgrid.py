#!/usr/bin/env python3
"""Which embedded colour grid does the oracle's gray=OFF path use per pixel?

Runs one solid-bar page through the oracle at gray=OFF, recovers each bar's
exact ink, and compares it against all 14 embedded grids (driver weight tables).
Reports the grid(s) matching exactly, so the replacement decision can be read
off directly instead of inferred from an ON/OFF difference.

Usage: graytol_whichgrid.py <name> <probefile> [--matching Normal|Vivid|None] [--gray OFF]
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

import dither  # noqa: E402
from exact_interp import interp_exact, load_weights  # noqa: E402
from find_luts import unpack  # noqa: E402
from graytol_probe import FIX, PLANES, SW, build_ppm, measure  # noqa: E402
from grid_pin_all import GRIDS, ORDER  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"


def main() -> int:
    name = sys.argv[1]
    matching = "Normal"
    gray = "OFF"
    if "--matching" in sys.argv:
        matching = sys.argv[sys.argv.index("--matching") + 1]
    if "--gray" in sys.argv:
        gray = sys.argv[sys.argv.index("--gray") + 1]
    colors = []
    for line in Path(sys.argv[2]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            colors.append(tuple(int(x) for x in line.split()))
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    ppm = Path(f"/tmp/{name}.ppm")
    ppm.write_bytes(build_ppm(colors))
    dst = Path(f"/tmp/{name}_{gray}.xl2hb")
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                    "--matching", matching, "--gray", gray], check=True, capture_output=True)
    (FIX / f"{name}_{gray}.xl2hb").write_bytes(dst.read_bytes())
    res = measure(f"{name}_{gray}", colors, tables)

    weights = load_weights()
    raw = RAW.read_bytes()
    rgb = np.array(colors)
    grids = {off: interp_exact(unpack(raw, off), weights, rgb, ORDER) for off in GRIDS}
    print(f"# {name} matching={matching} gray={gray} bars={len(colors)}")
    for bi, c in enumerate(colors):
        common = [p for p in PLANES if p in res]
        idx = [PLANES.index(p) for p in common]
        off = np.array([int(res[p][bi]) for p in common])
        scored = sorted((int(np.abs(gi[bi][idx] - off).sum()), GRIDS[o]) for o, gi in grids.items())
        best = [n for d, n in scored if d == scored[0][0]]
        print(f"{str(c):>16} d={max(c)-min(c):3d} OFF={off.tolist()} -> {best[0]}({scored[0][0]})"
              f"{'  tie:'+','.join(best[1:]) if len(best) > 1 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
