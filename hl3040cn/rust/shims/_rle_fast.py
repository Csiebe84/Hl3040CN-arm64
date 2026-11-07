# SPDX-License-Identifier: GPL-3.0-or-later
"""Shim: `_rle_fast` backed by the Rust extension `_hl3040cn_native`."""

from _hl3040cn_native import encode_sw_rle, group_bits, pack_groups

__all__ = ["group_bits", "pack_groups", "encode_sw_rle"]
