#!/usr/bin/env python3
"""Verify the Fine 4/3 stretch against the real Brother oracle.

Compares the port's Fine dither + stage-1 output, plane by plane, against the
captured oracle XL2HB files in /mnt/ssd/finecmp.  The oracle is decoded
independently (pclxl + band + fine_decode), so this is not a self-comparison.

Usage:  .venv312/bin/python tools/verify_fine_stretch.py
Exit code 0 if every plane is byte-identical, 1 otherwise.
"""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
FIX = Path("/mnt/ssd/finecmp")
for p in (str(FIX), str(HERE / "src"), str(HERE / "hl3040cn" / "src"), str(HERE / "tools")):
    sys.path.insert(0, p)

from fine_decode import decode_stage2  # noqa: E402
import pclxl  # noqa: E402
import band  # noqa: E402
from dither import load_dither_tables, dither_channel_4bpp_pattern_arr as PORT  # noqa: E402

_spec = importlib.util.spec_from_file_location("s1model", str(FIX / "s1model.py"))
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)

WIDTH = 5100
CASES = [
    ("s128_fine.xl2hb", "gray128", {"C": 87, "M": 64, "Y": 64}),
    ("g192_fine.xl2hb", "gray192", {"C": 44, "M": 32, "Y": 32}),
    ("g64_fine.xl2hb", "gray64", {"C": 111, "M": 80, "Y": 79, "K": 74}),
]


def main() -> int:
    if not FIX.is_dir():
        print(f"oracle directory {FIX} is missing", file=sys.stderr)
        return 1
    channels = load_dither_tables(str(HERE / "hl3040cn" / "src" / "lut"), fine=True, toner_save=False)
    total_ok = total = 0
    for fname, label, inks in CASES:
        path = FIX / fname
        if not path.exists():
            print(f"  {label}: oracle {fname} missing")
            continue
        oracle: dict[str, dict[int, bytes]] = {}
        for block in band.decode_blocks(pclxl.parse(path.read_bytes())):
            rows = oracle.setdefault(block.plane_name, {})
            for k, entry in enumerate(block.entries):
                rows[block.start_line + k] = decode_stage2(entry)
        print(f"  === {label} ({fname}) ===")
        for plane, ink in inks.items():
            want = oracle.get(plane, {})
            if not want:
                continue
            row = np.full(WIDTH, 255 - ink, np.uint8)
            bad = [y for y in sorted(want) if s1.forward(PORT(row, y, WIDTH, channels[plane]) + b"\x00\x00") != want[y]]
            ok = len(want) - len(bad)
            total_ok += ok
            total += len(want)
            tag = f"DIFF {len(bad)}/{len(want)} mod12={dict(sorted(Counter(y % 12 for y in bad).items()))}" if bad else f"IDENTICAL {ok}/{len(want)}"
            print(f"    {plane} ink={ink:3d}: {tag}")
    print(f"\n  TOTAL: {total_ok}/{total}")
    return 0 if total and total_ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
