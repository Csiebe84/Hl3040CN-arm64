#!/usr/bin/env python3
"""End-to-end ramp comparison: oracle vs port, byte for byte.

`compare.py` covers solids and bars; this tool covers the tone ramps that the
colour transformation must reproduce.  For each setting it builds R, G, B and
grey ramps, runs both filters, and reports byte equality (and, on a mismatch,
the first differing offset).  This is the reference test for the colour path.

Usage: ramp_pipeline_compare.py [--settings label]
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
from settings import ColorMatching, MediaType, PrintSettings  # noqa: E402

SRC_WIDTH = 5100
HEIGHT = 6564
BARS = 60
STEP = SRC_WIDTH // BARS
VALUES = [round(i * 255 / (BARS - 1)) for i in range(BARS)]
RAMPS = {
    "r": lambda v: (v, 0, 0), "g": lambda v: (0, v, 0), "b": lambda v: (0, 0, v),
    "gray": lambda v: (v, v, v),
}
SESSION_MARKER = b") BROTHER XL2HB;1;0\n"

SETTINGS = [
    ("Normal gray=ON ", dict(color_matching=ColorMatching.NORMAL, improve_gray=True)),
    ("Normal gray=OFF", dict(color_matching=ColorMatching.NORMAL, improve_gray=False)),
    ("Vivid  gray=ON ", dict(color_matching=ColorMatching.VIVID, improve_gray=True)),
    ("Vivid  gray=OFF", dict(color_matching=ColorMatching.VIVID, improve_gray=False)),
    ("None   gray=ON ", dict(color_matching=ColorMatching.NONE, improve_gray=True)),
    ("None   gray=OFF", dict(color_matching=ColorMatching.NONE, improve_gray=False)),
]


def build_ppm(ramp: str) -> bytes:
    """A 60-bar ramp at the paper's real width."""
    row = bytearray()
    for v in VALUES:
        row += bytes(RAMPS[ramp](v)) * STEP
    return b"P6\n%d %d\n255\n" % (SRC_WIDTH, HEIGHT) + bytes(row) * HEIGHT


def session(stream: bytes) -> bytes:
    """Bytes from the XL2HB session marker onwards."""
    at = stream.find(SESSION_MARKER)
    return stream[at:] if at >= 0 else stream


def oracle_run(ppm: bytes, flags: list[str]) -> bytes:
    """Run Brother's filter over a PPM."""
    tmp = Path("/tmp/rpc_in.ppm")
    tmp.write_bytes(ppm)
    out = Path("/tmp/rpc_out.xl2hb")
    subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(tmp), str(out), *flags],
                   check=True, capture_output=True)
    return out.read_bytes()


def native_run(ppm: bytes, settings: PrintSettings) -> bytes:
    """Run the native pipeline over a PPM."""
    parsed = read_ppm(io.BytesIO(ppm))
    if parsed is None:
        return b""
    w, h, _mx, pixels = parsed
    out = io.BytesIO()
    filter_page(w, h, pixels, settings, out)
    return out.getvalue()


def main() -> int:
    """Run every ramp under every setting and report byte equality."""
    want_label = None
    if "--settings" in sys.argv:
        want_label = sys.argv[sys.argv.index("--settings") + 1]
    total = 0
    passed = 0
    for label, kwargs in SETTINGS:
        if want_label and want_label not in label:
            continue
        settings = PrintSettings()
        settings.page_size = "Letter"
        for k, v in kwargs.items():
            setattr(settings, k, v)
        flags = ["--matching", {"NORMAL": "Normal", "VIVID": "Vivid", "NONE": "None"}[kwargs["color_matching"].name],
                 "--gray", "ON" if kwargs["improve_gray"] else "OFF"]
        for ramp in RAMPS:
            ppm = build_ppm(ramp)
            want = session(oracle_run(ppm, flags))
            got = session(native_run(ppm, settings))
            total += 1
            if want == got:
                passed += 1
                print(f"  {label} {ramp:4s} OK      {len(got):7d} bytes identical")
            else:
                limit = min(len(want), len(got))
                at = next((i for i in range(limit) if want[i] != got[i]), limit)
                print(f"  {label} {ramp:4s} DIFF    oracle={len(want)} native={len(got)} first diff @{at}")
    print(f"\n{passed}/{total} ramps byte-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
