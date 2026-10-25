#!/usr/bin/env python3
"""Run the port's pipeline over a ramp PPM and store its XL2HB output.

Gives a native fixture for the same ramp the oracle ran, so `ramp_measure.py`
can measure both sides with one method.

Usage: ramp_port.py <axis> [--nodes | --bars N]
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import ramp_build  # noqa: E402
from pipeline import filter_page  # noqa: E402
from ppm import read_ppm  # noqa: E402
from settings import PrintSettings  # noqa: E402


def main() -> int:
    """Build the ramp, run the port filter, store the output."""
    axis = sys.argv[1] if len(sys.argv) > 1 else "r"
    nodes = "--nodes" in sys.argv
    bars = 60
    if "--bars" in sys.argv:
        bars = int(sys.argv[sys.argv.index("--bars") + 1])
    ppm = ramp_build.build_nodes_ppm(axis) if nodes else ramp_build.build_ppm(axis, bars)
    tag = "nodes" if nodes else str(bars)
    parsed = read_ppm(io.BytesIO(ppm))
    w, h, _mx, px = parsed
    settings = PrintSettings()
    settings.page_size = "Letter"
    buf = io.BytesIO()
    filter_page(w, h, px, settings, buf)
    out = HERE.parent.parent / ".." / "mnt" / "ssd" / "bprobe" / f"ramp_{axis}{tag}_port.xl2hb"
    target = Path("/mnt/ssd/bprobe") / f"ramp_{axis}{tag}_port.xl2hb"
    target.write_bytes(buf.getvalue())
    print(f"port ramp axis={axis} tag={tag} -> {target} ({len(buf.getvalue())} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
