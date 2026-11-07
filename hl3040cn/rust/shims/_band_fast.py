# SPDX-License-Identifier: GPL-3.0-or-later
"""Shim: `_band_fast` backed by the Rust extension `_hl3040cn_native`."""

from _hl3040cn_native import render_band

__all__ = ["render_band"]
