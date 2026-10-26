#!/usr/bin/env python3
"""Byte comparison of the port's Fine mode against Brother's filter.

`ramp_pipeline_compare.py` only exercises Normal (600 dpi).  Fine selects the
`capt` dither tables and the two-stage encoder, so it needs its own check.

Renders the same ramp page through the oracle with BRResolution=Fine and
through the port with Resolution.FINE, then reports byte equality.

Usage: fine_compare.py [--matching Normal|Vivid] [--bars N]
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from ramp_pipeline_compare import session  # noqa: E402
from settings import ColorMatching, PrintSettings, Resolution  # noqa: E402

SW, HEIGHT, BARS = 5100, 6564, 60
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
RAMPS = {"r": lambda v: (v, 0, 0), "g": lambda v: (0, v, 0),
         "b": lambda v: (0, 0, v), "gray": lambda v: (v, v, v)}
MATCH = {"Normal": ColorMatching.NORMAL, "Vivid": ColorMatching.VIVID}


def build_ppm(axis: str) -> bytes:
    fn = RAMPS[axis]
    step = SW // BARS
    row = bytearray()
    for v in VALUES:
        row += bytes(fn(v)) * step
    return b"P6\n%d %d\n255\n" % (SW, HEIGHT) + bytes(row) * HEIGHT


def main() -> int:
    matching = sys.argv[sys.argv.index("--matching") + 1] if "--matching" in sys.argv else "Normal"
    tmp = Path("/mnt/ssd/finecmp")
    tmp.mkdir(exist_ok=True)
    ok = total = 0
    for axis in ("r", "g", "b", "gray"):
        ppm = build_ppm(axis)
        p = tmp / f"{axis}.ppm"
        p.write_bytes(ppm)
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(p),
                        str(tmp / f"{axis}_or.xl2hb"), "--matching", matching,
                        "--gray", "OFF", "--resolution", "Fine"],
                       check=True, capture_output=True)
        oracle = session((tmp / f"{axis}_or.xl2hb").read_bytes())
        st = PrintSettings()
        st.page_size = "Letter"
        st.color_matching = MATCH[matching]
        st.resolution = Resolution.FINE
        st.improve_gray = False
        w, h, _m, px = read_ppm(io.BytesIO(ppm))
        o = io.BytesIO()
        filter_page(w, h, px, st, o)
        port = session(o.getvalue())
        total += 1
        if oracle == port:
            ok += 1
            print(f"{matching} Fine {axis:4s} OK ({len(port)} bytes)")
        else:
            n = min(len(oracle), len(port))
            d = next((i for i in range(n) if oracle[i] != port[i]), n)
            print(f"{matching} Fine {axis:4s} DIFF @{d} oracle={len(oracle)} port={len(port)}")
    print(f"\n{ok}/{total} Fine ramps byte-identical")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
