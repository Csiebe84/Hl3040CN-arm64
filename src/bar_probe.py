#!/usr/bin/env python3
"""Read the compressed scanline encoding off controlled black bars.

A full-height black bar of a known width gives an exact, reproducible run
pattern in the K plane, so the entry bytes can be attributed to a known bit
sequence without Ghostscript guessing at anything.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CONTAINER = "brother-cups"
PRINTER = "/opt/brother/Printers/hl3040cn"
WRAPPER = f"{PRINTER}/lpd/filterhl3040cn"
RC = f"{PRINTER}/inf/brhl3040cnrc"
OUT = Path(__file__).resolve().parent.parent / "ref" / "bars"


def run_ps(ps: bytes) -> bytes:
    """Filter a PostScript job through the CUPS wrapper in the container."""
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"{WRAPPER} 1 CUPS USB"],
        input=ps, capture_output=True, check=True,
    )
    return proc.stdout


def main() -> None:
    """Print the first few K entries for a range of bar widths."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import band
    import pclxl

    subprocess.run(
        ["docker", "exec", CONTAINER, "sh", "-c",
         f"sed -i 's|^PageSize=.*|PageSize=Letter|' {RC}"],
        capture_output=True, check=True,
    )
    OUT.mkdir(parents=True, exist_ok=True)

    widths = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 300, 400, 512]
    for w in widths:
        ps = f"%!PS\n0 setgray 0 0 {w} 792 rectfill\nshowpage\n".encode()
        data = run_ps(ps)
        (OUT / f"bar{w}.xl2hb").write_bytes(data)
        blocks = band.decode_blocks(pclxl.parse(data))
        if not blocks:
            print(f"w={w:4d}: no blocks")
            continue
        blk = blocks[0]
        entries = blk.entries
        # Entries are identical down the bar; report the first and last.
        print(f"w={w:4d} plane={blk.plane_name} ent={len(entries):5d} "
              f"first({len(entries[0])}B)={entries[0].hex()} "
              f"last({len(entries[-1])}B)={entries[-1].hex()}")


if __name__ == "__main__":
    main()
