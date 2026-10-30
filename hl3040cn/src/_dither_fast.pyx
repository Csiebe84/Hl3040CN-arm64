# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Ordered 1bpp dither of one plane scanline against a tiled threshold row, and
the Fine-mode 4bpp BRCD pattern gather."""

from cpython.bytes cimport PyBytes_FromStringAndSize


def dither_row_1bpp(const unsigned char[:] row, const unsigned char[::1] thresholds, Py_ssize_t width):
    """Set a dot where ink (255 - pixel) exceeds the threshold; pack MSB-first.

    Returns:
        ceil(width / 8) bytes.
    """
    cdef Py_ssize_t bpl = (width + 7) // 8
    cdef Py_ssize_t i
    cdef unsigned char acc
    if row.shape[0] < width or thresholds.shape[0] < width:
        raise ValueError("row or thresholds shorter than width")
    cdef bytes out = PyBytes_FromStringAndSize(NULL, bpl)
    cdef unsigned char *po = <unsigned char *><char *>out
    for i in range(bpl):
        po[i] = 0
    with nogil:
        for i in range(width):
            if 255 - row[i] > thresholds[i]:
                po[i >> 3] |= <unsigned char>(0x80 >> (i & 7))
    return out


def dither_row_4bpp_pattern(
    const unsigned char[:] row,
    const unsigned char[::1] patterns,
    Py_ssize_t n_ink,
    Py_ssize_t pattern_row_bytes,
    Py_ssize_t pattern_offset,
    Py_ssize_t wb,
    Py_ssize_t width,
):
    """Dither one Fine-mode scanline through the BRCD dot patterns.

    Native counterpart of ``dither.dither_channel_4bpp_pattern_arr``.  For each
    pixel the ink amount selects a pattern row and the column is taken modulo the
    pattern width; the byte's low nibble is the level, and two levels pack into
    one output byte (high nibble first).

    `patterns` is the flattened ``(n_ink, pattern_row_bytes)`` table,
    `pattern_offset` is ``(y % height) * wb`` and `wb` the pattern bytes per
    screen row.  Values of `width` beyond the caller's pixel count are not read.

    Returns:
        ``width // 2`` nibble-packed bytes.
    """
    cdef Py_ssize_t i, ink, col, level0, level1
    cdef Py_ssize_t half = width // 2
    if row.shape[0] < width:
        raise ValueError("row shorter than width")
    if patterns.shape[0] < n_ink * pattern_row_bytes:
        raise ValueError("patterns smaller than n_ink * pattern_row_bytes")
    if width % 2:
        raise ValueError("width must be even")

    cdef bytes out = PyBytes_FromStringAndSize(NULL, half)
    cdef unsigned char *po = <unsigned char *><char *>out
    cdef const unsigned char *pr = &row[0]
    cdef const unsigned char *pp = &patterns[0]

    with nogil:
        for i in range(half):
            # Pixel 2i
            ink = 255 - pr[2 * i]
            if ink > n_ink - 1:
                ink = n_ink - 1
            col = pattern_offset + ((2 * i) % wb)
            level0 = pp[ink * pattern_row_bytes + col] & 0x0F
            # Pixel 2i + 1
            ink = 255 - pr[2 * i + 1]
            if ink > n_ink - 1:
                ink = n_ink - 1
            col = pattern_offset + ((2 * i + 1) % wb)
            level1 = pp[ink * pattern_row_bytes + col] & 0x0F
            po[i] = <unsigned char>((level0 << 4) | level1)
    return out
