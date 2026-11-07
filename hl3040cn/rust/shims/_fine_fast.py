# SPDX-License-Identifier: GPL-3.0-or-later
"""Shim: `_fine_fast` backed by the Rust extension `_hl3040cn_native`."""

from _hl3040cn_native import (
    compress_pattern_encode,
    compress_rle_preencode,
    encode_fine_plane,
)

__all__ = ["compress_rle_preencode", "compress_pattern_encode", "encode_fine_plane"]
