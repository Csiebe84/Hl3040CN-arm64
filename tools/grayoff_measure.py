#!/usr/bin/env python3
"""Measure the oracle's four ink planes for gray=ON and gray=OFF, per bar.

Earlier work compared fixtures that `grid_identify.py` had overwritten for each
setting, so the gray=ON and gray=OFF fixtures were not from the same setting.
This tool generates a fresh, uniquely named fixture per setting and measures
every plane (C via the 20-bit decoder, M/Y/K via the 12/10-bit decoders), then
compares ON against OFF and against the grid the port uses.

Usage: grayoff_measure.py [--out DIR]
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
from grid_pin_all import COL, ORDER  # noqa: E402
from plane_all import rows  # noqa: E402
from ramp_measure import find_phase, solve_window  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
FIX = Path("/mnt/ssd/bprobe")
SW, HEIGHT, BARS = 5100, 6564, 60
STEP = SW // BARS
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
RAMPS = {"r": lambda v: (v, 0, 0), "g": lambda v: (0, v, 0), "b": lambda v: (0, 0, v),
         "gray": lambda v: (v, v, v)}
PLANES = ["C", "M", "Y", "K"]


def build_ppm(ramp: str) -> bytes:
    row = bytearray()
    for v in VALUES:
        row += bytes(RAMPS[ramp](v)) * STEP
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def measure(name: str, tables) -> dict[str, np.ndarray]:
    out = {}
    for plane in PLANES:
        r = rows(name, plane)
        if r is None:
            continue
        table = tables[plane]
        phase = find_phase(r, table, 30 * STEP, 31 * STEP)
        out[plane] = np.array([solve_window(r, table, bi * STEP, (bi + 1) * STEP, phase)[0]
                               for bi in range(BARS)])
    return out


def main() -> int:
    outdir = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path("/tmp/grayoff")
    outdir.mkdir(parents=True, exist_ok=True)
    raw = RAW.read_bytes()
    weights = load_weights()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"),
                                        fine=False, toner_save=False)
    log = open(outdir / "grayoff_measure.log", "w")

    def say(line: str) -> None:
        print(line)
        log.write(line + "\n")

    for ramp in RAMPS:
        ppm = Path(f"/tmp/gom_{ramp}.ppm")
        ppm.write_bytes(build_ppm(ramp))
        meas = {}
        for g in ("ON", "OFF"):
            name = f"gom_{ramp}_{g}"
            dst = Path(f"/tmp/{name}.xl2hb")
            subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(ppm), str(dst),
                            "--matching", "Normal", "--gray", g], check=True, capture_output=True)
            (FIX / f"{name}.xl2hb").write_bytes(dst.read_bytes())
            meas[g] = measure(name, tables)
        grid = interp_exact(unpack(raw, 0xA7C5E), weights,
                            np.array([list(RAMPS[ramp](v)) for v in VALUES]), ORDER)
        say(f"=== ramp {ramp} ===")
        for plane in PLANES:
            on = meas["ON"].get(plane)
            off = meas["OFF"].get(plane)
            gm = grid[:, COL[plane]]

            def fmt(a):
                return "absent" if a is None else f"n={np.count_nonzero(a):2d} max={a.max():3d}"

            if on is None and off is None:
                say(f"  {plane}: both absent")
                continue
            if on is None or off is None:
                say(f"  {plane}: ON {fmt(on)} | OFF {fmt(off)}  <-- presence differs")
            else:
                d = int(np.abs(on - off).max())
                say(f"  {plane}: ON {fmt(on)} | OFF {fmt(off)} | max|ON-OFF|={d}")
            nz = [(bi, VALUES[bi], (int(on[bi]) if on is not None else None),
                   (int(off[bi]) if off is not None else None), int(gm[bi]))
                  for bi in range(BARS)
                  if (on is not None and on[bi]) or (off is not None and off[bi]) or gm[bi]]
            for bi, v, a, b, gval in nz[:14]:
                say(f"      bar {bi:2d} v={v:3d}  ON={a} OFF={b} grid0xa7c5e={gval}")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
