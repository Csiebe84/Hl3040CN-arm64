#!/usr/bin/env python3
"""Match each probe's OFF ink against all 14 embedded grids (exact L1).

Uses the robust all-block measurement (`graytol_probe`) so the OFF ink is the
oracle's real ink, then interpolates every embedded grid at the probe colour
with the driver's own weight tables and reports the exact matches.

Usage: graytol_gridsearch.py <name> <probefile>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

from exact_interp import interp_exact, load_weights  # noqa: E402
from find_luts import unpack  # noqa: E402
from graytol_probe import FIX, MATCHING, PLANES, SW, build_ppm, measure  # noqa: E402
from grid_pin_all import COL, GRIDS, ORDER  # noqa: E402
import dither  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"


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
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    ppm = Path(f"/tmp/{name}.ppm")
    ppm.write_bytes(build_ppm(colors))
    import subprocess
    res = {}
    for g in ("ON", "OFF"):
        dst = Path(f"/tmp/{name}_{g}.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                        "--matching", matching, "--gray", g], check=True, capture_output=True)
        (FIX / f"{name}_{g}.xl2hb").write_bytes(dst.read_bytes())
        res[g] = measure(f"{name}_{g}", colors, tables)

    weights = load_weights()
    raw = RAW.read_bytes()
    rgb = np.array(colors)
    grids = {off: interp_exact(unpack(raw, off), weights, rgb, ORDER) for off in GRIDS}
    for bi, c in enumerate(colors):
        common = [p for p in PLANES if p in res["OFF"]]
        idx = [PLANES.index(p) for p in common]
        off = np.array([int(res["OFF"][p][bi]) for p in common])
        on = np.array([int(res["ON"][p][bi]) for p in common if p in res["ON"]]) if all(p in res["ON"] for p in common) else np.array([])
        matches = []
        best = (10**9, None)
        for off_off, gi in grids.items():
            ink = gi[bi][idx]
            dd = int(np.abs(ink - off).sum())
            if dd < best[0]:
                best = (dd, off_off)
            if dd == 0:
                matches.append(GRIDS[off_off])
        tag = ",".join(matches) if matches else f"none(best {GRIDS[best[1]]} d={best[0]})"
        print(f"{str(c):>16} OFF={off.tolist()} ON={on.tolist()} -> {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
