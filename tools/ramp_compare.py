#!/usr/bin/env python3
"""Compare the oracle ramp with the port's colour LUT along the same axis.

The ramp gives the oracle's ink per input level with a bit-exact fit (error 0).
Computing the port's LUT for the same levels shows whether the difference is a
per-channel tone curve (oracle_ink = f(port_ink)), a scale/offset, or a
different shape entirely.

Usage: ramp_compare.py <axis> [--bars N]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import color_lut  # noqa: E402
import dither  # noqa: E402
import pclxl  # noqa: E402
import rle_decode  # noqa: E402
from band import decode_blocks  # noqa: E402
from color_lut import ColorTable  # noqa: E402

FIX = Path("/mnt/ssd/bprobe")
LUT_DIR = HERE.parent / "hl3040cn" / "src" / "lut"
WIDTH = 5120
LINE_BYTES = WIDTH // 8
SRC_WIDTH = 5100
DECODERS = {10: rle_decode.decode_10bit, 12: rle_decode.decode_12bit}


def axis_colour(axis: str, value: int) -> tuple[int, int, int]:
    """RGB triple for a ramp step."""
    if axis == "r":
        return (value, 0, 0)
    if axis == "g":
        return (0, value, 0)
    if axis == "b":
        return (0, 0, value)
    return (value, value, value)


def oracle_cycle(name: str, plane: str) -> np.ndarray | None:
    """First block's decoded scanlines of one plane as bool rows."""
    for b in decode_blocks(pclxl.parse((FIX / f"{name}.xl2hb").read_bytes())):
        if b.plane_name != plane or not b.entries:
            continue
        dec = DECODERS.get(b.header.comp_size)
        if dec is None:
            continue
        return np.stack(
            [np.unpackbits(np.frombuffer(dec(e, LINE_BYTES), np.uint8))[:WIDTH].astype(bool) for e in b.entries]
        )
    return None


def solve(obs: np.ndarray, table, x0: int, x1: int, phase: int = 0) -> tuple[int, int]:
    """Best (ink, error) for a period-aligned window."""
    period = table.width
    span = x1 - x0
    use = (span // period) * period or span
    reps = use // period + 2
    tiled = np.tile(table.threshold_matrix, (1, reps))[:, x0 % period : x0 % period + use]
    h = min(obs.shape[0], table.height)
    th = np.roll(tiled, -phase, axis=0)[:h]
    levels = np.arange(256, dtype=np.int32)[:, None, None]
    err = np.count_nonzero(((255 - levels) > th[None]) ^ obs[:h, x0 : x0 + use][None], axis=(1, 2))
    i = int(np.argmin(err))
    return 255 - i, int(err[i])


def port_ink(table: ColorTable, rgb: tuple[int, int, int]) -> dict[str, int]:
    """Port's ink per channel for one colour."""
    k, c, m, y = color_lut.rgb_to_cmyk_lut_arr(bytes(rgb) * 16, 16, table)
    return {"K": 255 - int(k[0]), "C": 255 - int(c[0]), "M": 255 - int(m[0]), "Y": 255 - int(y[0])}


def main() -> int:
    """Print oracle vs port ink per ramp step."""
    axis = sys.argv[1] if len(sys.argv) > 1 else "r"
    bars = 60
    if "--bars" in sys.argv:
        bars = int(sys.argv[sys.argv.index("--bars") + 1])
    tables = dither.load_dither_tables(str(LUT_DIR), fine=False, toner_save=False)
    name = f"ramp_{axis}"
    step = SRC_WIDTH // bars
    cycles = {p: oracle_cycle(name, p) for p in ("K", "C", "M", "Y")}
    planes = [p for p in cycles if cycles[p] is not None]
    table = ColorTable("rgb")
    print(f"# axis={axis} bars={bars} planes={planes} table={table.name}")
    print(f"{'bar':>3s} {'val':>3s} " + " ".join(f"{p}_or|{p}_port|{p}_diff" for p in planes))
    for bi in range(bars):
        val = round(bi * 255 / (bars - 1))
        rgb = axis_colour(axis, val)
        pinks = port_ink(table, rgb)
        cells = []
        for p in planes:
            o, err = solve(cycles[p], tables[p], bi * step, (bi + 1) * step)
            pt = pinks[p]
            cells.append(f"{o:4d}|{pt:4d}|{pt - o:+4d}")
        print(f"{bi:3d} {val:3d} " + " ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
