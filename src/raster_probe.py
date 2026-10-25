#!/usr/bin/env python3
"""Probe Brother's raster filter with exact-size PPM pages.

Feeding the filter a PPM that already matches the page's pixel dimensions
removes Ghostscript and any scaling from the experiment: what goes in is
exactly what the colour separation sees.  That makes it possible to read the
compressed scanline encoding straight off controlled patterns.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CONTAINER = "brother-cups"
PRINTER = "/opt/brother/Printers/hl3040cn"
FILTER = f"{PRINTER}/lpd/brhl3040cnfilter"
PAPER_INF = f"{PRINTER}/inf/paperinfij2"
RC = f"{PRINTER}/inf/brhl3040cnrc"
OUT = Path(__file__).resolve().parent.parent / "ref" / "raster"


def page_dims(page_size: str) -> tuple[int, int]:
    """Source dimensions the filter uses for a paper size.

    Width is the paperinfij2 width rounded up to a multiple of 32 (the
    filter's own rule); height is the printed height from the same file.
    """
    text = subprocess.run(
        ["docker", "exec", CONTAINER, "cat", PAPER_INF], capture_output=True, check=True
    ).stdout.decode()
    for line in text.splitlines():
        if line.startswith(f"{page_size}:"):
            _, rest = line.split(":", 1)
            w, h = rest.split()
            return (int(w) + 31) & ~31, int(h)
    raise KeyError(page_size)


def build_ppm(width: int, height: int, rows: dict[int, bytes]) -> bytes:
    """Assemble a binary PPM, using `rows` for the given scanlines.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        rows: Sparse map of row index to raw RGB bytes; other rows are white.

    Returns:
        The complete P6 file.
    """
    white = b"\xff\xff\xff" * width
    out = bytearray(b"P6\n%d %d\n255\n" % (width, height))
    for y in range(height):
        out += rows.get(y, white)
    return bytes(out)


def run_filter(ppm: bytes, *, page_size: str = "Letter") -> bytes:
    """Push a PPM through the raster filter with the given page size."""
    subprocess.run(
        ["docker", "exec", CONTAINER, "sh", "-c",
         f"sed -i 's|^PageSize=.*|PageSize={page_size}|' {RC}"],
        capture_output=True, check=True,
    )
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c",
         f"{FILTER} -pi {PAPER_INF} -rc {RC}"],
        input=ppm, capture_output=True, check=True,
    )
    return proc.stdout


def main() -> None:
    """Run the single-line experiments and print the resulting entries."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import band
    import pclxl

    width, height = page_dims("Letter")
    print(f"Letter page: {width}x{height}")

    cases = {
        # A single scanline at row 100 with a known bit pattern.
        "half": {100: b"\x00\x00\x00" * (width // 2) + b"\xff\xff\xff" * (width - width // 2)},
        "white": {},
        "left4": {100: b"\x00\x00\x00" * 4 + b"\xff\xff\xff" * (width - 4)},
        "left64": {100: b"\x00\x00\x00" * 64 + b"\xff\xff\xff" * (width - 64)},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in cases.items():
        ppm = build_ppm(width, height, rows)
        data = run_filter(ppm)
        (OUT / f"{name}.xl2hb").write_bytes(data)
        ops = pclxl.parse(data)
        blocks = band.decode_blocks(ops)
        print(f"\n== {name}: {len(blocks)} blocks")
        for blk in blocks[:3]:
            print(f"   {blk.plane_name} start={blk.start_line} bh={blk.block_height} ent={len(blk.entries)}")
            for i, entry in enumerate(blk.entries[:2]):
                print(f"     [{i}] len={len(entry)} {entry[:48].hex()}")


if __name__ == "__main__":
    main()
