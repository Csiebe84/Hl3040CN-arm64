"""Decode the XL2HB raster blocks a HL-3040CN capture carries.

Each ``ReadImage`` operator delivers one *block* of one colour plane.  A block
is a 14-byte plane header followed by a sequence of row entries, a two-byte
terminator and a checksum byte.  Everything multi-byte is big-endian except the
entry payload, which is the compressed scanline itself.

This module exists to check the driver's encoder against Brother's own output,
so it decodes rather than encodes and is deliberately strict.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

PLANE_NAMES = {0: "K", 1: "C", 2: "M", 3: "Y"}


class BandError(Exception):
    """The block does not decode as a plane header plus row entries."""


@dataclass
class PlaneHeader:
    """The 14-byte header that opens every block."""

    comp_type: int
    bit_depth: int
    quant_type: int
    comp_size: int
    row_width: int
    line_count: int
    data_size: int
    reserved: int

    @classmethod
    def parse(cls, buf: bytes, offset: int = 0) -> tuple["PlaneHeader", int]:
        """Read a plane header; return it and the offset just past it."""
        if len(buf) - offset < 14:
            raise BandError(f"truncated plane header at {offset}")
        (
            comp_type,
            bit_depth,
            quant_type,
            comp_size,
            row_width,
            line_count,
            data_size,
            reserved,
        ) = struct.unpack_from(">BBBBHHIH", buf, offset)
        return (
            cls(comp_type, bit_depth, quant_type, comp_size, row_width, line_count, data_size, reserved),
            offset + 14,
        )


@dataclass
class Block:
    """One decoded raster block: its header plus the row entries."""

    plane: int
    start_line: int
    block_height: int
    header: PlaneHeader
    entries: list[bytes] = field(default_factory=list)
    checksum_ok: bool = False

    @property
    def plane_name(self) -> str:
        """'K', 'C', 'M' or 'Y'."""
        return PLANE_NAMES.get(self.plane, f"?{self.plane}")


def decode_block(plane: int, start_line: int, block_height: int, data: bytes) -> Block:
    """Decode one ReadImage payload.

    Args:
        plane: The plane id from the operator's CommentData.
        start_line: StartLine attribute.
        block_height: BlockHeight attribute.
        data: The extended data payload.

    Returns:
        The decoded block, with one entry per emitted scanline.

    Raises:
        BandError: If the block is malformed or its checksum does not add up.
    """
    header, pos = PlaneHeader.parse(data)
    entries: list[bytes] = []
    while pos + 2 <= len(data):
        size = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        if size == 0:
            break
        if pos + size > len(data):
            raise BandError(f"entry of {size} bytes overruns the block at {pos}")
        entries.append(data[pos : pos + size])
        pos += size
        # Entries are padded to a 4-byte boundary before the trailing size.
        pad = (-size) % 4
        pos += pad
        if pos + 2 > len(data):
            raise BandError(f"missing trailing size at {pos}")
        trailing = struct.unpack_from(">H", data, pos)[0]
        if trailing != size:
            raise BandError(f"entry size mismatch: {size} != {trailing} at {pos}")
        pos += 2
    checksum_ok = (sum(data) & 0xFF) == 0
    return Block(plane, start_line, block_height, header, entries, checksum_ok)


def decode_blocks(ops) -> list[Block]:
    """Decode every ReadImage in a parsed operation list.

    Args:
        ops: Operations from `pclxl.parse`.

    Returns:
        The decoded blocks in stream order.
    """
    blocks: list[Block] = []
    for op in ops:
        if op.name != "ReadImage" or op.data is None:
            continue
        plane = op.attrs.get("CommentData", 0)
        if isinstance(plane, bytes):
            plane = plane[0] if plane else 0
        blocks.append(decode_block(plane, op.attrs["StartLine"], op.attrs["BlockHeight"], op.data))
    return blocks
