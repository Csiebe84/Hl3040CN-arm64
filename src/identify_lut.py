#!/usr/bin/env python3
"""Work out which colour LUT blob in the HL-3040CN filter is which profile.

The filter keeps several 17x17x17 RGB-to-CMYK grids and picks one per job.
Only some of them are recognisable by comparing against the HL-4150 driver's
known set, so the rest are identified by feeding solid colours that land
exactly on grid points and matching the measured ink against each candidate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import band
import pclxl
import rle_decode

CONTAINER = "brother-cups"
PRINTER = "/opt/brother/Printers/hl3040cn"
FILTER = f"{PRINTER}/lpd/brhl3040cnfilter"
PAPER_INF = f"{PRINTER}/inf/paperinfij2"
RC = f"{PRINTER}/inf/brhl3040cnrc"

WIDTH, HEIGHT = 5120, 6564  # Letter at 600 dpi, the filter's own size
LUT_ENTRIES = 17**3
LUT_BYTES = LUT_ENTRIES * 8

# Candidate blobs found by scanning the filter binary for 17^3 packed CMYK grids.
CANDIDATES = {
    "cmyk@2a541": 0x2A541,
    "cmyk_ig@47340": 0x47340,
    "X@9e25c": 0x9E25C,
    "Y@a7c5e": 0xA7C5E,
    "Z@bb054": 0xBB054,
    "W@c4a36": 0xC4A36,
}

# Solid colours on exact grid points (multiples of 16) plus black and white.
COLOURS = {
    "black": (0, 0, 0),
    "grey25": (64, 64, 64),
    "grey50": (128, 128, 128),
    "white": (240, 240, 240),
    "red": (240, 0, 0),
    "green": (0, 240, 0),
    "blue": (0, 0, 240),
    "cyan": (0, 240, 240),
    "magenta": (240, 0, 240),
    "yellow": (240, 240, 0),
}


def set_rc(**values: str) -> None:
    """Set rc-file keys in the container."""
    for key, value in values.items():
        subprocess.run(
            ["docker", "exec", CONTAINER, "sh", "-c", f"sed -i 's|^{key}=.*|{key}={value}|' {RC}"],
            capture_output=True, check=True,
        )


def filter_ppm(ppm: bytes) -> bytes:
    """Run the raster filter on a PPM and return the XL2HB stream."""
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"{FILTER} -pi {PAPER_INF} -rc {RC}"],
        input=ppm, capture_output=True, check=False,
    ).stdout


def solid_ppm(rgb: tuple[int, int, int]) -> bytes:
    """Build a whole-page solid colour PPM."""
    return b"P6\n%d %d\n255\n" % (WIDTH, HEIGHT) + bytes(rgb) * (WIDTH * HEIGHT)


def plane_ink(data: bytes, plane: str) -> float | None:
    """Fraction of set bits in the middle scanline of one 12-bit plane."""
    blocks = band.decode_blocks(pclxl.parse(data))
    for blk in blocks:
        if blk.plane_name != plane or not blk.entries:
            continue
        entry = blk.entries[len(blk.entries) // 2]
        try:
            packed = rle_decode.decode_12bit(entry, blk.header.row_width)
        except rle_decode.RleError:
            return None
        return sum(bin(byte).count("1") for byte in packed) / (blk.header.row_width * 8)
    return None


def lut_ink(lut: np.ndarray, rgb: tuple[int, int, int], channel: int) -> int:
    """Ink value a grid predicts for an RGB triple, using the 4150 indexing.

    Index is b*289 + g*17 + r with each channel divided by 16, which is how
    the driver walks the packed grid.
    """
    r, g, b = (c // 16 for c in rgb)
    return int(lut[b * 289 + g * 17 + r][channel])


def main() -> None:
    """Measure each solid colour and rank the candidates by agreement."""
    raw = (Path(__file__).resolve().parent.parent / "ref" / "brhl3040cnfilter.bin").read_bytes()
    luts = {
        name: np.frombuffer(raw[off : off + LUT_BYTES], dtype=np.int32).reshape(-1, 2)
        for name, off in CANDIDATES.items()
    }
    unpacked = {}
    for name, packed in luts.items():
        arr = np.empty((LUT_ENTRIES, 4), dtype=np.int32)
        arr[:, 0] = packed[:, 0] & 0xFFFF
        arr[:, 1] = packed[:, 0] >> 16
        arr[:, 2] = packed[:, 1] & 0xFFFF
        arr[:, 3] = packed[:, 1] >> 16
        unpacked[name] = arr

    # Plain Normal colour matching, no grey handling, no toner save.
    set_rc(BRColorMatching="Normal", BRGray="OFF", TonerSaveMode="OFF", MediaType="Plain")

    measured: dict[str, float | None] = {}
    for name, rgb in COLOURS.items():
        data = filter_ppm(solid_ppm(rgb))
        measured[name] = plane_ink(data, "Y")
        print(f"{name:9s} rgb={rgb} Y-ink={measured[name]}")

    print("\nCandidate Y values (0-255) per colour:")
    header = f"{'colour':9s} {'measured':>9s} " + " ".join(f"{n:>13s}" for n in unpacked)
    print(header)
    for name, rgb in COLOURS.items():
        vals = " ".join(f"{lut_ink(unpacked[c], rgb, 2):13d}" for c in unpacked)
        m = measured[name]
        print(f"{name:9s} {('%.3f' % m) if m is not None else 'n/a':>9s} {vals}")

    print("\nRank correlation (measured Y fraction vs LUT yellow):")
    xs = np.array([measured[c] for c in COLOURS if measured[c] is not None], dtype=float)
    for cand, arr in unpacked.items():
        ys = np.array([lut_ink(arr, COLOURS[c], 2) for c in COLOURS if measured[c] is not None], dtype=float)
        if ys.std() == 0 or xs.std() == 0:
            corr = float("nan")
        else:
            corr = float(np.corrcoef(xs, ys)[0, 1])
        print(f"  {cand:16s} corr={corr:+.4f}")


if __name__ == "__main__":
    main()
