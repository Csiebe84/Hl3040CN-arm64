# SPDX-License-Identifier: GPL-3.0-or-later
"""Shim: `_dither_fast` backed by the Rust extension `_hl3040cn_native`.

The driver imports the Cython modules by name and falls back to pure Python on
`ImportError`.  Keeping the old names lets the Rust build drop in without
touching a single call site; only `install.sh` decides which shims are
installed.
"""

from _hl3040cn_native import dither_row_1bpp, dither_row_4bpp_pattern

__all__ = ["dither_row_1bpp", "dither_row_4bpp_pattern"]
