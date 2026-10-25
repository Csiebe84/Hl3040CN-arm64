#!/usr/bin/env python3
"""Pull the HL-3040CN calibration tables out of Brother's filter binary.

The driver needs the printer's colour grids and dither tables.  The dither
tables ship as BRCD files in the LPR package; the colour grids are embedded
in the filter binary with no symbol table.  This script copies the BRCD set
and extracts the grids it can identify, writing both into the source tree
so the native filter has no dependency on the container.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from find_luts import LUT_BYTES, LUT_ENTRIES, unpack

CONTAINER = "brother-cups"
PRINTER = "/opt/brother/Printers/hl3040cn"
SRC = Path(__file__).resolve().parent
WORK = SRC.parent.parent
FILTER = WORK / "ref" / "brhl3040cnfilter.bin"
LUT_DIR = SRC / "lut"
COLOR_DATA = SRC / "color_data"

# Grids located in the filter binary.  The first three are byte-identical to
# the HL-4150CDN's colour-matching-None grids, which is what fixes their
# meaning; the rest are 3040-specific and are named by position until the
# colour oracle pins their profile.
GRIDS = {
    "cmyk_ig_default": 0x47340,
    "cmyk_default": 0x2A541,
    "srgb_ig_default": 0x9E25C,
    "srgb_ig_density2": 0xA7C5E,
    "srgb_ig_glossy": 0xBB054,
    "rgb_ig_default": 0xC4A36,
    "rgb_ig_density2": 0x646BB,
    "rgb_ig_glossy": 0x6E0BD,
    "rgb_default": 0x814B3,
    "rgb_density2": 0x8AE95,
    "rgb_glossy": 0x94875,
    "srgb_default": 0xBB06E,
    "srgb_density2": 0xC4A4E,
    "srgb_glossy": 0xCE466,
}

# The dither tables are BRCD files; the 3040 uses the cache08 set where the
# 4150 uses cache09.  Copy them rather than regenerate.
BRCD_SUFFIX = "cache08"


def copy_brcd() -> int:
    """Copy the 3040's BRCD dither tables out of the container."""
    LUT_DIR.mkdir(parents=True, exist_ok=True)
    listing = subprocess.run(
        ["docker", "exec", CONTAINER, "ls", f"{PRINTER}/inf/lut"],
        capture_output=True, check=True,
    ).stdout.decode().split()
    count = 0
    for name in listing:
        if not name.endswith(f"_{BRCD_SUFFIX}.bin"):
            continue
        data = subprocess.run(
            ["docker", "exec", CONTAINER, "cat", f"{PRINTER}/inf/lut/{name}"],
            capture_output=True, check=True,
        ).stdout
        (LUT_DIR / name).write_bytes(data)
        count += 1
    return count


def extract_grids() -> None:
    """Write each identified colour grid into color_data/."""
    COLOR_DATA.mkdir(parents=True, exist_ok=True)
    raw = FILTER.read_bytes()
    seen: dict[str, str] = {}
    for name, offset in GRIDS.items():
        blob = raw[offset : offset + LUT_BYTES]
        if len(blob) != LUT_BYTES:
            print(f"  {name}: offset 0x{offset:x} past end of binary, skipped")
            continue
        grid = unpack(raw, offset)
        digest = hashlib.sha256(blob).hexdigest()[:16]
        # Two names pointing at the same bytes would make the table selection
        # meaningless, so report duplicates instead of silently overwriting.
        if digest in seen:
            print(f"  {name}: same bytes as {seen[digest]}, skipped")
            continue
        seen[digest] = name
        (COLOR_DATA / f"{name}_lut.bin").write_bytes(blob)
        print(f"  {name}_lut.bin  black={grid[0].tolist()}  white={grid[LUT_ENTRIES - 1].tolist()}")


def main() -> None:
    """Refresh the LUT and colour-data directories."""
    if not FILTER.exists():
        print(f"missing {FILTER}; run the container extraction first", file=sys.stderr)
        raise SystemExit(1)
    if LUT_DIR.exists():
        shutil.rmtree(LUT_DIR)
    print("dither tables:")
    print(f"  copied {copy_brcd()} BRCD files")
    print("colour grids:")
    extract_grids()


if __name__ == "__main__":
    main()
