#!/usr/bin/env python3
"""Find which colour table reproduces the oracle, by full byte comparison.

The oracle fixture already exists, so this needs no emulator run and no
oracle-side decoder: the native encoder is proven byte-exact on black, so a
correct table must reproduce the whole session byte for byte.

Searches profile x improve_gray x variant (18 combinations) and reports, for
each, the session length and the first differing offset.
"""
from __future__ import annotations

import io
import itertools
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "hl3040cn" / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE.parent / "src"))

from color_lut import ColorTable            # noqa: E402
from pipeline import filter_page            # noqa: E402
from ppm import read_ppm                    # noqa: E402
from settings import PrintSettings          # noqa: E402

FIXTURE = Path("/mnt/ssd/bprobe")
SESSION = b") BROTHER XL2HB;1;0\n"


def session(stream: bytes) -> bytes:
    """Return the stream from the XL2HB session marker onwards."""
    at = stream.find(SESSION)
    return stream[at:] if at >= 0 else stream


def load(name: str):
    """Read a PPM fixture."""
    parsed = read_ppm(io.BytesIO((FIXTURE / f"{name}.ppm").read_bytes()))
    if parsed is None:
        raise SystemExit(f"cannot parse {name}.ppm")
    return parsed


def run(pixels, w, h, settings, table) -> bytes:
    """Run the native pipeline with an explicit colour table."""
    import pipeline as _p
    orig = _p.color_table
    _p.color_table = lambda s: table
    try:
        out = io.BytesIO()
        _p.filter_page(w, h, pixels, settings, out)
        return out.getvalue()
    finally:
        _p.color_table = orig


def main() -> int:
    """Search all tables for one fixture and report the best match."""
    name = sys.argv[1] if len(sys.argv) > 1 else "red"
    want = session((FIXTURE / f"{name}.xl2hb").read_bytes())
    w, h, _maxval, pixels = load(name)
    print(f"fixture={name}  ppm={w}x{h}  oracle session={len(want)} B")
    print(f"{'profile':6s} {'ig':5s} {'variant':9s} | {'native':>9s} {'first diff':>10s} | status")
    print("-" * 72)

    best = None
    for profile, ig, variant in itertools.product(
        ("rgb", "srgb", "cmyk"), (False, True), ("default", "density2", "glossy")
    ):
        table = ColorTable(profile=profile, improve_gray=ig, variant=variant)
        settings = PrintSettings()
        settings.page_size = "Letter"
        try:
            got = session(run(pixels, w, h, settings, table))
        except Exception as exc:  # noqa: BLE001
            print(f"{profile:6s} {str(ig):5s} {variant:9s} | {'-':>9s} {'-':>10s} | ERROR {exc}")
            continue
        if got == want:
            diff = "-"
            status = "IDENTICAL"
        else:
            limit = min(len(got), len(want))
            at = next((i for i in range(limit) if got[i] != want[i]), limit)
            diff = str(at)
            status = f"{len(got) - len(want):+d} B"
        print(f"{profile:6s} {str(ig):5s} {variant:9s} | {len(got):9d} {diff:>10s} | {status}")
        score = abs(len(got) - len(want))
        if best is None or score < best[0]:
            best = (score, profile, ig, variant, len(got), status)

    print()
    if best[1] is None:
        print("kein Ergebnis")
        return 1
    score, profile, ig, variant, size, status = best
    print(f"BESTE Annaeherung: {profile} ig={ig} {variant}  size={size}  ({status})")
    print(f"Oracle: {len(want)} B   Abweichung {size - len(want):+d} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
