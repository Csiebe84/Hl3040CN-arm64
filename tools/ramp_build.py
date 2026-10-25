#!/usr/bin/env python3
"""Build a column-bar tone ramp and run it through the oracle filter.

The six solid primaries give only six data points; a ramp gives hundreds and
is what the colour transformation must reproduce.  One page carries N vertical
bars of equal width, each a constant RGB value along a chosen axis.  The page
is exactly the filter's own pixel size (5120x6564 Letter), so nothing is
scaled and what the colour separation sees is what we put in.

Usage: ramp_build.py <axis> [--bars N]
  axis: r | g | b | gray  (gray walks R=G=B together)
Output fixture: /mnt/ssd/bprobe/ramp_<axis>.xl2hb
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTAINER = "brother-cups"
PRINTER = "/opt/brother/Printers/hl3040cn"
FILTER = f"{PRINTER}/lpd/brhl3040cnfilter"
PAPER_INF = f"{PRINTER}/inf/paperinfij2"
RC = f"{PRINTER}/inf/brhl3040cnrc"
FIX = Path("/mnt/ssd/bprobe")
# Feed the paper's real width (Letter = 5100 px), not the rounded image width
# 5120: the filter pads to 5120 itself, and a wrong stride shears any image
# with horizontal structure.
SRC_WIDTH = 5100
HEIGHT = 6564


def axis_colour(axis: str, value: int) -> tuple[int, int, int]:
    """RGB triple for a step of the ramp."""
    if axis == "r":
        return (value, 0, 0)
    if axis == "g":
        return (0, value, 0)
    if axis == "b":
        return (0, 0, value)
    if axis == "gray":
        return (value, value, value)
    raise ValueError(f"unknown axis {axis!r}")


def build_ppm(axis: str, bars: int) -> bytes:
    """Assemble the column-bar PPM at the paper's real width.

    `bars` must divide SRC_WIDTH so every bar is a whole number of pixels and
    the measured windows line up with what was fed in.
    """
    if SRC_WIDTH % bars:
        raise ValueError(f"bars={bars} does not divide {SRC_WIDTH}")
    values = [round(i * 255 / (bars - 1)) for i in range(bars)]
    row = bytearray()
    for v in values:
        row += bytes(axis_colour(axis, v)) * (SRC_WIDTH // bars)
    return b"P6\n%d %d\n255\n" % (SRC_WIDTH, HEIGHT) + bytes(row) * HEIGHT


def build_nodes_ppm(axis: str) -> bytes:
    """Column-bar PPM whose 17 bars sit exactly on the LUT's grid nodes.

    0, 16, ..., 240, 255 — the values the 3D LUT samples directly.  5100/17
    is a whole 300 px, so each bar is one grid node with no interpolation
    blend at its centre.
    """
    values = [i * 16 for i in range(16)] + [255]
    step = SRC_WIDTH // len(values)
    row = bytearray()
    for v in values:
        row += bytes(axis_colour(axis, v)) * step
    return b"P6\n%d %d\n255\n" % (SRC_WIDTH, HEIGHT) + bytes(row) * HEIGHT


def run_filter(ppm: bytes) -> bytes:
    """Push a PPM through Brother's filter."""
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"{FILTER} -pi {PAPER_INF} -rc {RC}"],
        input=ppm, capture_output=True, check=False,
    ).stdout


def main() -> int:
    """Build the ramp for one axis and store the oracle output."""
    axis = sys.argv[1] if len(sys.argv) > 1 else "r"
    bars = 60
    if "--bars" in sys.argv:
        bars = int(sys.argv[sys.argv.index("--bars") + 1])
    if "--nodes" in sys.argv:
        ppm = build_nodes_ppm(axis)
        tag = "nodes"
    else:
        ppm = build_ppm(axis, bars)
        tag = str(bars)
    print(f"ramp axis={axis} tag={tag} ppm={len(ppm)} bytes")
    data = run_filter(ppm)
    out = FIX / f"ramp_{axis}{tag}.xl2hb"
    out.write_bytes(data)
    print(f"oracle output {len(data)} bytes -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
