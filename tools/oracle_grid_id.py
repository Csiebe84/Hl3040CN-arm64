#!/usr/bin/env python3
"""Pin which embedded grid each colour setting selects, using the red fixture.

The port maps BRColorMatching / BRGray / toner-save / media-type onto grid
*names*, but those names are position-based guesses.  A red page is a single
grid node (R=16, G=0, B=0), so its oracle M and Y ink read off the grid entry
directly.  Running red under one changed setting at a time and matching the
(M, Y) pair against every grid in the binary says exactly which blob the
driver loads, and therefore which port setting is wrong.

Usage: oracle_grid_id.py
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
import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402
from find_luts import scan, unpack  # noqa: E402

RAW = HERE.parent / "ref" / "brhl3040cnfilter.bin"
PPM = Path("/mnt/ssd/bprobe/red.ppm")
WIDTH = 5120
LINE_BYTES = WIDTH // 8
SRC_WIDTH = 5100
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit}
RED_NODE = (16, 0, 0)
# port name -> offset, for reporting
PORT_NAMES = {
    0x9E25C: "srgb_ig_default", 0xA7C5E: "srgb_ig_density2", 0xBB054: "srgb_ig_glossy",
    0xC4A36: "rgb_ig_default", 0x646BB: "rgb_ig_density2", 0x6E0BD: "rgb_ig_glossy",
    0x814B3: "rgb_default", 0x8AE95: "rgb_density2", 0x94875: "rgb_glossy",
    0xBB06E: "srgb_default", 0xC4A4E: "srgb_density2", 0xCE466: "srgb_glossy",
    0x47340: "cmyk_ig_default", 0x2A541: "cmyk_default",
}

SETTINGS = [
    ("Normal gray=ON  (baseline)", ["--matching", "Normal", "--gray", "ON"]),
    ("Normal gray=OFF", ["--matching", "Normal", "--gray", "OFF"]),
    ("Vivid  gray=ON", ["--matching", "Vivid", "--gray", "ON"]),
    ("Vivid  gray=OFF", ["--matching", "Vivid", "--gray", "OFF"]),
    ("None   gray=ON", ["--matching", "None", "--gray", "ON"]),
    ("Normal gray=ON toner=ON", ["--matching", "Normal", "--gray", "ON", "--toner", "ON"]),
    ("Normal gray=ON enhance=ON", ["--matching", "Normal", "--gray", "ON", "--enhance", "ON"]),
    ("Normal gray=ON glossy", ["--matching", "Normal", "--gray", "ON", "--media", "Glossy"]),
]


def grid_red_my(raw: bytes, off: int) -> tuple[int, int]:
    """Red-node (M, Y) ink of the grid at `off` in the oracle's convention."""
    grid = unpack(raw, off)
    v = grid[RED_NODE[0] * 289 + RED_NODE[1] * 17 + RED_NODE[2]]
    return int(v[1]), int(v[2])


def plane_rows(blob: bytes, plane: str) -> np.ndarray | None:
    """First block of `plane` as bool rows."""
    for b in decode_blocks(pclxl.parse(blob)):
        if b.plane_name == plane and b.entries:
            dec = DECODERS.get(b.header.comp_size)
            if dec is None:
                continue
            return np.stack([
                np.unpackbits(np.frombuffer(dec(e, LINE_BYTES), np.uint8))[:WIDTH].astype(bool)
                for e in b.entries
            ])
    return None


def ink_level(blob: bytes, plane: str, tables: dict) -> tuple[int, int]:
    """Best (ink, mismatch bits) for the plane's first rows."""
    obs = plane_rows(blob, plane)
    if obs is None:
        return -1, -1
    t = tables[plane]
    w = (SRC_WIDTH // t.width) * t.width
    tiled = np.tile(t.threshold_matrix, (1, w // t.width + 2))[:, :w]
    h = min(obs.shape[0], t.height)
    th = tiled[:h]
    levels = np.arange(256, dtype=np.int32)[:, None, None]
    err = np.count_nonzero(((255 - levels) > th[None]) ^ obs[:h, :w][None], axis=(1, 2))
    return 255 - int(np.argmin(err)), int(err.min())


def main() -> int:
    """Run red under each setting and report the matching grid offset."""
    raw = RAW.read_bytes()
    tables = dither.load_dither_tables(str(HERE.parent / "hl3040cn" / "src" / "lut"), fine=False, toner_save=False)
    grids = {off + 2: grid_red_my(raw, off + 2) for off in scan(raw)}
    for label, flags in SETTINGS:
        out = Path(f"/tmp/red_id.xl2hb")
        subprocess.run([sys.executable, str(HERE / "oracle_run.py"), str(PPM), str(out), *flags], check=True)
        blob = out.read_bytes()
        m, em = ink_level(blob, "M", tables)
        y, ey = ink_level(blob, "Y", tables)
        hits = [f"0x{o:x}({PORT_NAMES.get(o, '?')})" for o, (gm, gy) in grids.items() if gm == m and gy == y]
        print(f"{label:28s} M={m:3d}(e{em}) Y={y:3d}(e{ey})  grid={hits or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
