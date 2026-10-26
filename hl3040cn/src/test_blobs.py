#!/usr/bin/env python3
"""Skip guards for tests that need Brother's proprietary blobs.

`lut/` (BRCD dither tables) and `color_data/` (colour grids) are deliberately
not in the repository — see the .gitignore comment: they ship inside Brother's
LPR driver and each user extracts them locally. On a fresh checkout (CI) they
are absent, so a test that reads them must *skip with a message* instead of
failing; the message is what keeps a fully-skipped run visible in the log.

The flags mirror the existing `pipeline.HAS_BAND_KERNEL` guard: computed once
at import, and a test that genuinely cannot load the data is skipped.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

_HERE = Path(__file__).resolve().parent

LUT_DIR = _HERE / "lut"
COLOR_DATA_DIR = _HERE / "color_data"

# Normal-mode BRCD set the dither tests pin: four channels, plain and -TS.
_LUT_FILES = tuple(f"0600-{ch}{suffix}_cache08.bin" for ch in "kcmy" for suffix in ("", "-TS"))

# The colour grids whose difference the BRGray=OFF tests depend on.
_COLOR_DATA_FILES = ("rgb_ig_default_lut.bin", "cmyk_default_lut.bin")


def _has_files(directory: Path, names: tuple[str, ...]) -> bool:
    return directory.is_dir() and all((directory / name).exists() for name in names)


# True only when the blob directory holds every file the guarded tests read.
HAS_LUT = _has_files(LUT_DIR, _LUT_FILES)
HAS_COLOR_DATA = _has_files(COLOR_DATA_DIR, _COLOR_DATA_FILES)

_T = TypeVar("_T", bound=type)


def require_blobs(*, lut: bool = False, color_data: bool = False) -> Callable[[_T], _T]:
    """Skip a test or TestCase when a required blob directory is not extracted.

    Args:
        lut: the test reads `lut/` (BRCD dither tables).
        color_data: the test reads `color_data/` (colour grids).

    Returns:
        A `unittest.skipUnless` decorator carrying a message that names the
        missing directory, so a skipped run says why.
    """
    missing = []
    if lut and not HAS_LUT:
        missing.append("lut/")
    if color_data and not HAS_COLOR_DATA:
        missing.append("color_data/")
    reason = f"Brother blobs not extracted: {', '.join(missing)} (see .gitignore)"
    return unittest.skipUnless(not missing, reason)
