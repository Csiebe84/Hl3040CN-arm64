# SPDX-License-Identifier: GPL-3.0-or-later
"""Shim: `_color_fast` backed by the Rust extension `_hl3040cn_native`."""

from _hl3040cn_native import gather_kcmy, interp_kcmy

__all__ = ["gather_kcmy", "interp_kcmy"]
