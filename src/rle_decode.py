"""Decode the XL2HB sliding-window RLE used for the K/Y (12-bit) planes.

The encoder is a small state machine over 12-bit words with a three-word
context window; decoding it means replaying that window so the context-skip
commands expand to the words they stand for.  Having a decoder lets a capture
be turned back into the exact bitmap the printer would rasterise, which is
what makes it possible to check a reimplementation against Brother's filter.
"""

from __future__ import annotations

# Word size the 12-bit K/Y planes use.
WORD_BITS = 12

# Word size the 10-bit M plane uses.
WORD_BITS_10 = 10


class RleError(Exception):
    """The byte stream does not decode as 12-bit sliding-window RLE."""


def _unpack_groups(data: bytes, count: int, bits: int = WORD_BITS) -> tuple[list[int], int]:
    """Read `count` big-endian bit groups from `data`.

    Returns:
        The group values and the byte offset just past the groups.
    """
    values = []
    bitpos = 0
    total = len(data) * 8
    for _ in range(count):
        if bitpos + bits > total:
            raise RleError(f"literal needs {bits} bits at bit {bitpos}, only {total} present")
        value = 0
        for i in range(bits):
            byte = data[(bitpos + i) >> 3]
            bit = (byte >> (7 - ((bitpos + i) & 7))) & 1
            value = (value << 1) | bit
        values.append(value)
        bitpos += bits
    return values, (bitpos + 7) // 8


def decode_12bit(data: bytes, line_bytes: int) -> bytes:
    """Expand one compressed K/Y scanline back to its packed 1bpp bytes.

    Args:
        data: The entry payload from a ReadImage block.
        line_bytes: Bytes per line the plane was encoded from.

    Returns:
        `line_bytes` bytes of packed 1bpp data, MSB first.

    Raises:
        RleError: If the stream ends early or a literal runs past the line.
    """
    total_bits = line_bytes * 8
    total_words = total_bits // WORD_BITS  # the encoder drops the remainder
    out_words: list[int] = []
    ctx = [0, 0, 0]  # three-word context window, oldest first
    pos = 0

    def count_ext() -> int:
        """Read a 0xFF-terminated count extension."""
        nonlocal pos
        total = 0
        while pos < len(data) and data[pos] == 0xFF:
            total += 255
            pos += 1
        if pos >= len(data):
            raise RleError("count extension runs off the end")
        total += data[pos]
        pos += 1
        return total

    while pos < len(data) and len(out_words) < total_words:
        byte = data[pos]
        if byte >= 0xF0:  # long run
            v_hi = byte & 0x0F
            pos += 1
            if pos >= len(data):
                raise RleError("long run truncated")
            value = (v_hi << 8) | data[pos]
            pos += 1
            count = 8 + count_ext()
            out_words.extend([value] * count)
        elif byte >= 0x80:  # short run
            count = ((byte >> 4) & 0x07) + 1
            v_hi = byte & 0x0F
            pos += 1
            if pos >= len(data):
                raise RleError("short run truncated")
            value = (v_hi << 8) | data[pos]
            pos += 1
            out_words.extend([value] * count)
        elif byte >= 0x40:  # literal block
            pos += 1
            if byte == 0x7F:
                count = 0x41 + count_ext()
            else:
                count = (byte & 0x3F) + 2
            values, consumed = _unpack_groups(data[pos:], count)
            pos += consumed
            out_words.extend(values)
        else:  # context skip
            pos += 1
            count = 64 + count_ext() if byte == 0x3F else byte + 1
            # A skipped word repeats the reference, which is the word two
            # positions back (zero before the line starts).  Because the
            # encoder advances its window once per word, the reference is
            # always recoverable from the words already emitted.
            for _ in range(count):
                index = len(out_words)
                out_words.append(out_words[index - 2] if index >= 2 else 0)
                if len(out_words) >= total_words:
                    break

    return _pack_words(out_words, line_bytes)


def decode_10bit(data: bytes, line_bytes: int) -> bytes:
    """Expand one compressed M-plane scanline back to its packed 1bpp bytes.

    The M plane uses a narrower word than K/Y and a different context window:
    five words instead of three, so a context-skip command repeats the word
    four positions back rather than two.  Run and literal blocks carry a 2-bit
    high field instead of a 4-bit one, which is why the long-run opcode starts
    at 0xFC here and at 0xF0 for the 12-bit planes.

    Args:
        data: The entry payload from a ReadImage block.
        line_bytes: Bytes per line the plane was encoded from.

    Returns:
        `line_bytes` bytes of packed 1bpp data, MSB first.

    Raises:
        RleError: If the stream ends early or a literal runs past the line.
    """
    total_words = (line_bytes * 8) // WORD_BITS_10
    out_words: list[int] = []
    pos = 0

    def count_ext() -> int:
        """Read a 0xFF-terminated count extension."""
        nonlocal pos
        total = 0
        while pos < len(data) and data[pos] == 0xFF:
            total += 255
            pos += 1
        if pos >= len(data):
            raise RleError("count extension runs off the end")
        total += data[pos]
        pos += 1
        return total

    while pos < len(data) and len(out_words) < total_words:
        byte = data[pos]
        if byte >= 0xFC:  # long run: count >= 32
            v_hi = byte & 0x03
            pos += 1
            if pos >= len(data):
                raise RleError("long run truncated")
            value = (v_hi << 8) | data[pos]
            pos += 1
            count = 32 + count_ext()
            out_words.extend([value] * count)
        elif byte >= 0x80:  # short run: count 1..31
            count = ((byte >> 2) & 0x1F) + 1
            v_hi = byte & 0x03
            pos += 1
            if pos >= len(data):
                raise RleError("short run truncated")
            value = (v_hi << 8) | data[pos]
            pos += 1
            out_words.extend([value] * count)
        elif byte >= 0x40:  # literal block
            pos += 1
            count = 65 + count_ext() if byte == 0x7F else (byte & 0x3F) + 2
            values, consumed = _unpack_groups(data[pos:], count, WORD_BITS_10)
            pos += consumed
            out_words.extend(values)
        else:  # context skip: repeat the word four positions back
            pos += 1
            count = 64 + count_ext() if byte == 0x3F else byte + 1
            for _ in range(count):
                index = len(out_words)
                out_words.append(out_words[index - 4] if index >= 4 else 0)
                if len(out_words) >= total_words:
                    break

    return _pack_words(out_words, line_bytes, WORD_BITS_10)


def _pack_words(words: list[int], line_bytes: int, bits: int = WORD_BITS) -> bytes:
    """Pack fixed-width words back into a bit stream, most significant bit first."""
    out = bytearray(line_bytes)
    bitpos = 0
    for value in words:
        for i in range(bits):
            if bitpos >= line_bytes * 8:
                break
            bit = (value >> (bits - 1 - i)) & 1
            if bit:
                out[bitpos >> 3] |= 1 << (7 - (bitpos & 7))
            bitpos += 1
    return bytes(out)
