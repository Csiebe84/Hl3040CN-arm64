"""Minimal PCL-XL / Brother XL2HB stream parser.

The HL-3040CN (and its siblings) do not speak PCL6 or PostScript.  Brother's
filter emits a PCL-XL-shaped tagged stream introduced by

    ) BROTHER XL2HB;1;0

This module decodes that stream into a list of operations so the native driver
can be validated against captures from Brother's own filter.  Only the subset
the printer actually uses is implemented; unknown tags abort with a clear
error rather than silently desynchronising.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b") BROTHER XL2HB;1;0"

# --- data type tags -------------------------------------------------------
TAG_UBYTE = 0xC0
TAG_UINT16 = 0xC1
TAG_UBYTE_ARRAY = 0xC8
TAG_UINT16_ARRAY = 0xC9
TAG_UINT16_XY = 0xD1
TAG_SINT16_XY = 0xD3
TAG_ATTR = 0xF8
TAG_EXT_UINT32 = 0xFA
TAG_EXT_UINT8 = 0xFB

# --- operators ------------------------------------------------------------
OPS = {
    0x41: "BeginSession",
    0x42: "EndSession",
    0x43: "BeginPage",
    0x44: "EndPage",
    0x48: "OpenDataSource",
    0x49: "CloseDataSource",
    0x75: "SetPageOrigin",
    0xB0: "BeginImage",
    0xB1: "ReadImage",
    0xB2: "EndImage",
}

# --- attribute names, keyed by the operator they belong to ---------------
ATTRS: dict[str, dict[int, str]] = {
    "BeginSession": {0x86: "Measure", 0x89: "UnitsPerMeasure"},
    "OpenDataSource": {0x88: "SourceType", 0x82: "DataOrg"},
    "BeginPage": {
        0x28: "Orientation",
        0x26: "MediaSource",
        0x25: "MediaSize",
        0x27: "MediaType",
        0x34: "SimplexPageMode",
        0x35: "DuplexPageMode",
        0x81: "DuplexBackSide",
    },
    "SetPageOrigin": {0x2A: "PageOrigin"},
    "BeginImage": {
        0x64: "ColorMapping",
        0x62: "ColorDepth",
        0x6C: "SourceWidth",
        0x6B: "SourceHeight",
        0x67: "DestinationSize",
        0x31: "PageCopies",
        0x81: "CommentData",
    },
    "ReadImage": {
        0x6D: "StartLine",
        0x63: "BlockHeight",
        0x65: "CompressMode",
        0x81: "CommentData",
    },
}

# `*)`-style attribute ids that carry a byte array of trailing config.
ARRAY_ATTRS = {0x81}


class PclXlError(Exception):
    """The stream does not decode as the expected PCL-XL subset."""


@dataclass
class Op:
    """One decoded operation: an operator plus its attributes and data."""

    name: str
    offset: int
    attrs: dict[str, object] = field(default_factory=dict)
    data: bytes | None = None
    raw_attrs: list[tuple[int, object]] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [f"{self.name}"]
        for attr_id, value in self.raw_attrs:
            name = ATTRS.get(self.name, {}).get(attr_id, f"attr{attr_id:#04x}")
            if isinstance(value, bytes):
                shown = value.hex()
                if len(shown) > 64:
                    shown = shown[:64] + f"...({len(value)}B)"
                parts.append(f"{name}=0x{shown}")
            else:
                parts.append(f"{name}={value}")
        if self.data is not None:
            parts.append(f"data={len(self.data)}B")
        return " ".join(parts)


def _need(buf: bytes, pos: int, n: int, what: str) -> None:
    if pos + n > len(buf):
        raise PclXlError(f"truncated {what} at offset {pos} (need {n} bytes)")


def parse(buf: bytes, *, skip_pjl: bool = True) -> list[Op]:
    """Decode an XL2HB job into operations.

    Args:
        buf: The full job, including PJL and the XL2HB magic.
        skip_pjl: Skip everything up to and including the magic line.

    Returns:
        The decoded operations in stream order.

    Raises:
        PclXlError: If the stream cannot be decoded.
    """
    pos = buf.find(MAGIC)
    if pos < 0:
        raise PclXlError("XL2HB magic not found")
    pos += len(MAGIC)
    if skip_pjl and buf[pos : pos + 1] == b"\n":
        pos += 1

    ops: list[Op] = []
    pending: list[tuple[int, object]] = []
    while pos < len(buf):
        tag = buf[pos]
        if tag in OPS:
            op = Op(name=OPS[tag], offset=pos, raw_attrs=pending)
            for attr_id, value in pending:
                op.attrs[ATTRS.get(op.name, {}).get(attr_id, f"attr{attr_id:#04x}")] = value
            pending = []
            pos += 1
            if op.name == "ReadImage":
                pos = _read_image_data(buf, pos, op)
            ops.append(op)
            if op.name == "EndSession":
                break
            continue
        if tag == 0x1B:
            break  # trailing PJL / UEL
        value, pos = _read_value(buf, pos)
        if pos < len(buf) and buf[pos] == TAG_ATTR:
            pending.append((buf[pos + 1], value))
            pos += 2
        else:
            raise PclXlError(f"attribute value without attr id at offset {pos}")
    return ops


def _read_value(buf: bytes, pos: int) -> tuple[object, int]:
    """Decode one typed value; return it and the offset just past it."""
    tag = buf[pos]
    if tag == TAG_UBYTE:
        _need(buf, pos, 2, "ubyte")
        return buf[pos + 1], pos + 2
    if tag == TAG_UINT16:
        _need(buf, pos, 3, "uint16")
        return struct.unpack_from("<H", buf, pos + 1)[0], pos + 3
    if tag in (TAG_UINT16_XY, TAG_SINT16_XY):
        _need(buf, pos, 5, "xy pair")
        fmt = "<HH" if tag == TAG_UINT16_XY else "<hh"
        return struct.unpack_from(fmt, buf, pos + 1), pos + 5
    if tag == TAG_UBYTE_ARRAY:
        _need(buf, pos, 3, "ubyte array header")
        length = buf[pos + 2]
        _need(buf, pos, 3 + length, "ubyte array body")
        return buf[pos + 3 : pos + 3 + length], pos + 3 + length
    if tag == TAG_UINT16_ARRAY:
        _need(buf, pos, 4, "uint16 array header")
        count = struct.unpack_from("<H", buf, pos + 2)[0]
        _need(buf, pos, 4 + 2 * count, "uint16 array body")
        return struct.unpack_from(f"<{count}H", buf, pos + 4), pos + 4 + 2 * count
    if tag == TAG_EXT_UINT8:
        _need(buf, pos, 2, "ext8 header")
        length = buf[pos + 1]
        _need(buf, pos, 2 + length, "ext8 body")
        return buf[pos + 2 : pos + 2 + length], pos + 2 + length
    if tag == TAG_EXT_UINT32:
        _need(buf, pos, 5, "ext32 header")
        length = struct.unpack_from("<I", buf, pos + 1)[0]
        _need(buf, pos, 5 + length, "ext32 body")
        return buf[pos + 5 : pos + 5 + length], pos + 5 + length
    raise PclXlError(f"unknown tag {tag:#04x} at offset {pos}")


def _read_image_data(buf: bytes, pos: int, op: Op) -> int:
    """ReadImage carries its payload as extended data; consume it."""
    if pos < len(buf) and buf[pos] == TAG_EXT_UINT32:
        length = struct.unpack_from("<I", buf, pos + 1)[0]
        op.data = buf[pos + 5 : pos + 5 + length]
        return pos + 5 + length
    if pos < len(buf) and buf[pos] == TAG_EXT_UINT8:
        length = buf[pos + 1]
        op.data = buf[pos + 2 : pos + 2 + length]
        return pos + 2 + length
    raise PclXlError(f"ReadImage without data at offset {pos}")


def _read_attrs(buf: bytes, pos: int, op: Op) -> None:
    """Collect tag/value/attr triplets for an operator (for display)."""
    while pos < len(buf):
        tag = buf[pos]
        if tag in OPS:
            return
        if tag == TAG_UBYTE:
            value: object = buf[pos + 1]
            pos += 2
        elif tag == TAG_UINT16:
            value = struct.unpack_from("<H", buf, pos + 1)[0]
            pos += 3
        elif tag in (TAG_UINT16_XY, TAG_SINT16_XY):
            fmt = "<HH" if tag == TAG_UINT16_XY else "<hh"
            value = struct.unpack_from(fmt, buf, pos + 1)
            pos += 5
        elif tag == TAG_UBYTE_ARRAY:
            length = buf[pos + 2]
            value = buf[pos + 3 : pos + 3 + length]
            pos += 3 + length
        elif tag == TAG_UINT16_ARRAY:
            count = struct.unpack_from("<H", buf, pos + 2)[0]
            value = struct.unpack_from(f"<{count}H", buf, pos + 4)
            pos += 4 + 2 * count
        elif tag == TAG_EXT_UINT8:
            value = buf[pos + 2 : pos + 2 + buf[pos + 1]]
            pos += 2 + buf[pos + 1]
        elif tag == TAG_EXT_UINT32:
            length = struct.unpack_from("<I", buf, pos + 1)[0]
            value = buf[pos + 5 : pos + 5 + length]
            pos += 5 + length
        else:
            raise PclXlError(f"unknown tag {tag:#04x} at offset {pos}")
        if pos < len(buf) and buf[pos] == TAG_ATTR:
            attr_id = buf[pos + 1]
            op.raw_attrs.append((attr_id, value))
            op.attrs[ATTRS.get(op.name, {}).get(attr_id, f"attr{attr_id:#04x}")] = value
            pos += 2
        else:
            # A value with no attribute id terminates the operator's attr run.
            return


def dump(buf: bytes) -> str:
    """Render a decoded stream as one line per operation."""
    return "\n".join(str(op) for op in parse(buf))
