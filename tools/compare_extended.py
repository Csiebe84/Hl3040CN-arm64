#!/usr/bin/env python3
"""Reference-case comparison across gray levels and colour settings.

Extends compare.py: several grey levels, a mixed grey/red page, BRGray on/off,
Vivid and None colour matching, and a few 50% colours. Reports byte-identity
per case so a regression in any setting is visible.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "hl3040cn" / "src"))

import compare  # noqa: E402
from settings import ColorMatching, PrintSettings  # noqa: E402

W, H = 5100, 6564


def ppm(pixel_fn):
    return compare.ppm(W, H, pixel_fn)


def solid(rgb):
    return lambda y: bytes(rgb) * W


def bar(rgb, x0, x1):
    return lambda y: bytes((255, 255, 255)) * x0 + bytes(rgb) * (x1 - x0) + bytes((255, 255, 255)) * (W - x1)


CASES = [
    ("grey 12%", solid((32, 32, 32))),
    ("grey 25%", solid((64, 64, 64))),
    ("grey 37%", solid((96, 96, 96))),
    ("grey 50%", solid((128, 128, 128))),
    ("grey 63%", solid((160, 160, 160))),
    ("grey 75%", solid((192, 192, 192))),
    ("grey 88%", solid((224, 224, 224))),
    ("grey/red split", lambda y: bytes((128, 128, 128)) * (W // 2) + bytes((255, 0, 0)) * (W - W // 2)),
    ("grey bar 300px", bar((128, 128, 128), 2000, 2300)),
    ("dark grey bar", bar((64, 64, 64), 1000, 1300)),
    ("red 50%", solid((128, 0, 0))),
    ("cyan 50%", solid((0, 128, 128))),
]


def main() -> None:
    for label, gray in (("Normal gray=OFF", False), ("Normal gray=ON", True)):
        settings = PrintSettings()
        settings.page_size = "Letter"
        settings.improve_gray = gray
        print(f"=== {label} ===")
        results = [compare.compare(name, ppm(fn), W, H, settings) for name, fn in CASES]
        print(f"  {sum(results)}/{len(results)} byte-identical")
    for label, match in (("Vivid gray=OFF", ColorMatching.VIVID), ("None gray=OFF", ColorMatching.NONE)):
        settings = PrintSettings()
        settings.page_size = "Letter"
        settings.color_matching = match
        print(f"=== {label} ===")
        results = [compare.compare(name, ppm(fn), W, H, settings) for name, fn in CASES]
        print(f"  {sum(results)}/{len(results)} byte-identical")


if __name__ == "__main__":
    main()
