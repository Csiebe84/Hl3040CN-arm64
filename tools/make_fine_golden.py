"""Regenerate hl3040cn/src/fine_golden.json.gz, the _fine_fast equivalence corpus.

Run against the *Python* implementation, with no `_fine_fast.so` importable, so
the corpus records reference behaviour rather than native behaviour:

    python3 tools/make_fine_golden.py

The inputs are synthetic and generated here on purpose.  The repository does not
redistribute anything derived from Brother's driver (see .gitignore), and real
scanlines come out of printer captures, so committing them would contradict that
policy.  Instead the generator builds scanlines that have the shapes real planes
have - full-width gradients, long blank and solid runs, stride-2/3 halftone
patterns, mixed nibbles and noise, at the two plane widths the printer uses.

That is enough to pin a byte-level rewrite: `--with-captures` additionally folds
in real scanlines from /mnt/ssd/finecmp when they are present, which is how the
native encoder was checked against all 26256 captured lines during development.
Use it for a deep local run; the committed corpus stays synthetic.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for extra in (ROOT / "src", ROOT / "hl3040cn" / "src", ROOT / "tools"):
    sys.path.insert(0, str(extra))

FIXTURES = Path("/mnt/ssd/finecmp")

# 4bpp packed widths for the plane sizes the printer is driven at.
WIDTHS = (2480, 2550, 5100)


def _gradient(width: int, rnd: random.Random) -> bytes:
    """Full-range ramp: every byte value appears, nibbles sweep 0..15."""
    step = rnd.choice((1, 3, 7, 16))
    return bytes(((i * step) + rnd.randrange(256)) & 0xFF for i in range(width))


def _runs(width: int, rnd: random.Random) -> bytes:
    """Blank and solid stretches, as a mostly-white page has."""
    out = bytearray()
    while len(out) < width:
        value = rnd.choice((0x00, 0xFF, 0x0F, 0xF0, 0x11, 0xEE))
        out += bytes([value]) * rnd.randrange(1, 300)
    return bytes(out[:width])


def _stride(width: int, rnd: random.Random) -> bytes:
    """Halftone-style repeats at strides 1/2/3, which is what Stage 2 keys on."""
    period = rnd.randrange(1, 4)
    pattern = bytes(rnd.randrange(256) for _ in range(period))
    out = bytearray()
    while len(out) < width:
        out += pattern
        if rnd.random() < 0.25:
            out += bytes([rnd.randrange(256)]) * rnd.randrange(1, 12)
    return bytes(out[:width])


def _mixed(width: int, rnd: random.Random) -> bytes:
    """Text-like: short runs of mixed nibbles with occasional blanks."""
    out = bytearray()
    while len(out) < width:
        if rnd.random() < 0.3:
            out += bytes([0x00]) * rnd.randrange(1, 40)
        else:
            out += bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 30)))
    return bytes(out[:width])


def _noise(width: int, rnd: random.Random) -> bytes:
    return bytes(rnd.randrange(256) for _ in range(width))


def _nibble_edges(width: int, rnd: random.Random) -> bytes:
    """Only the nibble boundaries: 0x00/0x0F/0xF0/0xFF in varying proportion."""
    pool = (0x00, 0x0F, 0xF0, 0xFF, 0x0E, 0xE0, 0xFE, 0xEF)
    return bytes(rnd.choice(pool) for _ in range(width))


def synthetic_cases(per_shape: int, seed: int):
    rnd = random.Random(seed)
    cases = [
        b"", b"\x00", b"\xff", b"\x0f\xf0", b"\xf0\x0f",
        b"\x00" * 4096, b"\xff" * 4096, bytes(range(256)), bytes(range(255, -1, -1)),
        b"\x00" * 8 + b"\xff" * 8, b"\xf0" * 12, b"\x0f" * 12, b"\xff" * 3 + b"\x00" * 9,
        b"\x11\x22\x33" * 40, b"\xf1\xf2\xf3" * 40, b"\x10\x20\x30\x40" * 30,
    ]
    for width in WIDTHS:
        for builder in (_gradient, _runs, _stride, _mixed, _noise, _nibble_edges):
            for _ in range(per_shape):
                cases.append(builder(width, rnd))
    for _ in range(per_shape * 8):
        # Short random and short periodic inputs hit the 12-byte window edges.
        n = rnd.randrange(0, 60)
        cases.append(bytes(rnd.randrange(256) for _ in range(n)))
    return cases


def capture_cases(per_plane: int):
    """Real scanlines from local captures; only used with --with-captures."""
    import band
    import pclxl
    from fine_decode import decode_stage2

    def session(blob: bytes) -> bytes:
        at = blob.find(b") BROTHER XL2HB;1;0\n")
        return blob[at:] if at >= 0 else blob

    for name in ("gray_or", "black", "blank"):
        path = FIXTURES / f"{name}.xl2hb"
        if not path.exists():
            continue
        seen: dict[str, int] = {}
        for block in band.decode_blocks(pclxl.parse(session(path.read_bytes()))):
            for offset, entry in enumerate(block.entries):
                plane = block.plane_name
                if seen.get(plane, 0) >= per_plane:
                    continue
                seen[plane] = seen.get(plane, 0) + 1
                yield f"{name}:{plane}:{block.start_line + offset}", decode_stage2(bytes(entry))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-shape", type=int, default=6, help="synthetic lines per shape and width")
    ap.add_argument("--with-captures", action="store_true",
                    help="also fold in local printer captures (never committed)")
    ap.add_argument("--per-plane", type=int, default=400)
    ap.add_argument("--out", default=str(ROOT / "hl3040cn" / "src" / "fine_golden.json.gz"))
    args = ap.parse_args()

    import fine_encoder as ref

    if getattr(ref, "HAS_CYTHON_FINE", False):
        print("refusing to run: _fine_fast is importable, so the corpus would record")
        print("native output instead of reference output. Build without the .so.")
        return 1

    cases = list(synthetic_cases(args.per_shape, seed=20261030))
    if args.with_captures:
        captured = list(capture_cases(args.per_plane))
        cases += captured
        print(f"captures: {len(captured)} scanlines (local verification only)")
    print(f"synthetic: {len(cases)} scanlines")

    record = {"cases": []}
    for tag, stage1_in in enumerate(cases):
        stage1 = ref.compress_rle_preencode(stage1_in)
        record["cases"].append([tag, stage1_in.hex(), stage1.hex(), ref.compress_pattern_encode(stage1).hex()])

    out = Path(args.out)
    # gzip: the corpus is hex-encoded JSON and compresses about 20x, which keeps
    # the repository small without weakening the byte comparison.
    with gzip.open(out, "wt", compresslevel=9) as handle:
        json.dump(record, handle)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
