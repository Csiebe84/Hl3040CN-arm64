# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Native Fine-mode (1200 dpi) XL2HB encoders.

Native counterparts of `fine_encoder.compress_rle_preencode` (Stage 1) and
`fine_encoder.compress_pattern_encode` (Stage 2).  Both are pure Python byte
loops in the reference implementation and cost 3.1 s (Stage 1) plus 5.5 s
(Stage 2) for one A4 plane on the Odroid N2+; here they run in C.

`fine_encoder` imports these when the extension is present and falls back to
its own implementations otherwise, so the filter keeps working on a machine
without a compiler.  Equivalence is not assumed: `test_fine_fast_equiv.py`
replays frozen golden output for 26256 real oracle scanlines plus edge cases.

The Stage-2 reference keeps a `ring` bytearray that mirrors the input; here the
input pointer is read directly, which is equivalent because nothing ever
rewrites `ring` in place.
"""

from cpython.bytes cimport PyBytes_FromStringAndSize
from libc.stdlib cimport free, malloc, realloc


# Quantize 4bpp nibbles to 9 levels: clear the LSB of each nibble unless it is
# 0xF.  Byte-for-byte the same table as `fine_encoder._QUANTIZE`.
cdef unsigned char _QUANT[256]


cdef int _init_quant() noexcept:
    cdef int i, hi, lo
    for i in range(256):
        hi = (i >> 4) & 0xF
        lo = i & 0xF
        if hi != 0xF:
            hi &= 0xE
        if lo != 0xF:
            lo &= 0xE
        _QUANT[i] = <unsigned char>((hi << 4) | lo)
    return 0


_ = _init_quant()


cdef struct OutBuf:
    unsigned char *data
    Py_ssize_t len
    Py_ssize_t cap
    bint failed


cdef bint _ensure(OutBuf *o, Py_ssize_t extra) noexcept nogil:
    cdef Py_ssize_t need = o.len + extra
    cdef Py_ssize_t cap
    cdef unsigned char *p
    if o.failed:
        return False
    if need <= o.cap:
        return True
    cap = o.cap * 2
    if cap < need:
        cap = need
    p = <unsigned char *>realloc(o.data, cap)
    if p == NULL:
        o.failed = True
        return False
    o.data = p
    o.cap = cap
    return True


cdef inline void _put(OutBuf *o, unsigned char b) noexcept nogil:
    if o.len >= o.cap and not _ensure(o, 1):
        return
    o.data[o.len] = b
    o.len += 1


# ---------------------------------------------------------------------------
# Stage 1: nibble-aware RLE
# ---------------------------------------------------------------------------

cdef inline void _flush_white(OutBuf *o, int *run) noexcept nogil:
    cdef int r = run[0]
    while r > 8:
        _put(o, 0x17)
        r -= 8
    _put(o, <unsigned char>(((r - 1) | 0x10) & 0xFF))
    run[0] = 0


cdef inline void _flush_black(OutBuf *o, int *run) noexcept nogil:
    cdef int r = run[0]
    while r > 8:
        _put(o, 0x1F)
        r -= 8
    _put(o, <unsigned char>(((r - 1) | 0x18) & 0xFF))
    run[0] = 0


def compress_rle_preencode(bytes data):
    """Stage 1: nibble-aware RLE, native counterpart of the Python version."""
    cdef const unsigned char *p = data
    cdef Py_ssize_t n = len(data)
    cdef Py_ssize_t i
    cdef int src_val
    cdef int run_white = 0
    cdef int run_black = 0
    cdef int hi_nibble, lo_nibble
    cdef OutBuf o
    cdef bytes result

    o.len = 0
    o.cap = n + 64
    if o.cap < 64:
        o.cap = 64
    o.data = <unsigned char *>malloc(o.cap)
    o.failed = False
    if o.data == NULL:
        o.cap = 0
        raise MemoryError()

    with nogil:
        for i in range(n):
            src_val = _QUANT[p[i]]

            if src_val == 0x00:
                # White byte
                if run_black == 0:
                    run_white += 1
                else:
                    if run_black < 5:
                        _put(&o, <unsigned char>((((run_black * 8 - 8) & 0xFF) | 0x80) & 0xFF))
                    else:
                        _flush_black(&o, &run_black)
                        run_white += 1
                    run_black = 0

            elif src_val == 0xFF:
                # Black byte
                if run_white == 0:
                    run_black += 1
                else:
                    if run_white < 3:
                        _put(&o, <unsigned char>((((run_white * 8 - 8) & 0xFF) | 0x27) & 0xFF))
                    else:
                        _flush_white(&o, &run_white)
                        run_black += 1
                    run_white = 0

            else:
                hi_nibble = src_val & 0xF0
                lo_nibble = src_val & 0x0F

                if hi_nibble == 0xF0:
                    # Hi = full ink (0xF_)
                    if run_white == 0:
                        if run_black != 0:
                            if run_black > 3:
                                run_black -= 3
                                _flush_black(&o, &run_black)
                                run_black = 3
                            _put(&o, <unsigned char>(((run_black * 8) | (lo_nibble >> 1) | 0xC0) & 0xFF))
                            run_black = 0
                            continue
                    else:
                        if lo_nibble == 0:
                            if run_white > 3:
                                run_white -= 3
                                _flush_white(&o, &run_white)
                                run_white = 3
                            _put(&o, <unsigned char>(((run_white * 8) | 0xA7) & 0xFF))
                            run_white = 0
                            continue
                        _flush_white(&o, &run_white)
                    _put(&o, <unsigned char>(((lo_nibble >> 1) | 0xC0) & 0xFF))

                elif lo_nibble == 0:
                    # Lo = no ink (0x_0)
                    if run_white != 0:
                        if run_white > 3:
                            run_white -= 3
                            _flush_white(&o, &run_white)
                            run_white = 3
                        _put(&o, <unsigned char>((((run_white * 8) & 0xFF) | ((hi_nibble >> 5) - 1) | 0xA0) & 0xFF))
                        run_white = 0
                        continue
                    if run_black != 0:
                        if run_black > 4:
                            run_black -= 4
                            _flush_black(&o, &run_black)
                            run_black = 4
                        _put(&o, <unsigned char>((((run_black * 8 - 8) & 0xFF) | (hi_nibble >> 5) | 0x80) & 0xFF))
                        run_black = 0
                        continue
                    _put(&o, <unsigned char>((((hi_nibble >> 5) - 1) | 0xA0) & 0xFF))

                elif lo_nibble == 0x0F:
                    # Lo = full ink (0x_F)
                    if run_white != 0:
                        if run_white > 2:
                            run_white -= 2
                            _flush_white(&o, &run_white)
                            run_white = 2
                        if hi_nibble == 0:
                            _put(&o, <unsigned char>((((run_white * 8 - 8) & 0xFF) | 0x37) & 0xFF))
                        else:
                            _put(&o, <unsigned char>((((run_white * 8 - 8) & 0xFF) | ((hi_nibble >> 5) - 1) | 0x20) & 0xFF))
                        run_white = 0
                        continue
                    if run_black != 0:
                        if run_black > 4:
                            run_black -= 4
                            _flush_black(&o, &run_black)
                            run_black = 4
                        _put(&o, <unsigned char>((((run_black * 8 - 8) & 0xFF) | (hi_nibble >> 5) | 0xE0) & 0xFF))
                        run_black = 0
                        continue
                    _put(&o, <unsigned char>(((hi_nibble >> 2) | 0x47) & 0xFF))

                # General mixed: both nibbles non-zero, non-full
                elif hi_nibble == 0:
                    if run_black == 0:
                        if run_white != 0:
                            if run_white > 2:
                                run_white -= 2
                                _flush_white(&o, &run_white)
                                run_white = 2
                            _put(&o, <unsigned char>((((run_white * 8 - 8) & 0xFF) | ((lo_nibble >> 1) - 1) | 0x30) & 0xFF))
                            run_white = 0
                            continue
                    else:
                        _flush_black(&o, &run_black)
                    _put(&o, <unsigned char>((((lo_nibble >> 1) - 1) | 0x40) & 0xFF))
                else:
                    if run_white == 0:
                        if run_black != 0:
                            _flush_black(&o, &run_black)
                    else:
                        _flush_white(&o, &run_white)
                    _put(&o, <unsigned char>(((hi_nibble >> 2) | ((lo_nibble >> 1) - 1) | 0x40) & 0xFF))

        # Flush trailing runs
        if run_white != 0:
            _flush_white(&o, &run_white)
        elif run_black != 0:
            _flush_black(&o, &run_black)

    if o.failed:
        free(o.data)
        raise MemoryError()
    result = PyBytes_FromStringAndSize(<char *>o.data, o.len)
    free(o.data)
    return result


# ---------------------------------------------------------------------------
# Stage 2: pattern-matching encoder
# ---------------------------------------------------------------------------

cdef void _emit_ext_count(OutBuf *o, Py_ssize_t remaining) noexcept nogil:
    while remaining > 0xFE:
        _put(o, 0xFF)
        remaining -= 0xFF
    _put(o, <unsigned char>(remaining & 0xFF))


cdef Py_ssize_t _pattern_flush(
    OutBuf *o,
    int pattern_mode,
    int match_count,
    unsigned char p0,
    unsigned char p1,
    unsigned char p2,
    const unsigned char *src,
    Py_ssize_t pattern_start,
) noexcept nogil:
    """Flush a detected pattern; returns the updated `pattern_start`."""
    cdef Py_ssize_t ps = pattern_start
    cdef int k

    if pattern_mode == 0:
        # Stride-1 repeat (A,A,A,...)
        if match_count - 3 < 3:
            _put(o, <unsigned char>((match_count - 3) & 0xFF))
        else:
            _put(o, 3)
            _emit_ext_count(o, match_count - 6)
        _put(o, p0)
        ps += match_count

    elif pattern_mode == 1:
        # Stride-2 half (A,x,A,x,...) — emit A then each odd byte
        if match_count == 3:
            _put(o, 0x08)
        else:
            _put(o, 0x09)
            _emit_ext_count(o, match_count - 4)
        _put(o, p0)
        for k in range(match_count):
            _put(o, src[ps + 1])
            ps += 2

    elif pattern_mode == 2:
        # Stride-2 full (A,B,A,B,...)
        if match_count - 2 < 3:
            _put(o, <unsigned char>(((match_count - 2) | 0x04) & 0xFF))
        else:
            _put(o, 0x07)
            _emit_ext_count(o, match_count - 5)
        _put(o, p0)
        _put(o, p1)
        ps += match_count * 2

    elif pattern_mode == 3:
        # Stride-3 third (A,x,x,A,x,x,...) — emit A then each non-A pair
        if match_count == 3:
            _put(o, 0x0A)
        else:
            _put(o, 0x0B)
            _emit_ext_count(o, match_count - 4)
        _put(o, p0)
        for k in range(match_count):
            _put(o, src[ps + 1])
            _put(o, src[ps + 2])
            ps += 3

    elif pattern_mode == 4:
        # Stride-3 two-thirds (A,B,x,A,B,x,...) — emit A,B then each third byte
        if match_count == 2:
            _put(o, 0x0C)
        else:
            _put(o, 0x0D)
            _emit_ext_count(o, match_count - 3)
        _put(o, p0)
        _put(o, p1)
        for k in range(match_count):
            _put(o, src[ps + 2])
            ps += 3

    elif pattern_mode == 5:
        # Stride-3 full (A,B,C,A,B,C,...)
        if match_count == 2:
            _put(o, 0x0E)
        else:
            _put(o, 0x0F)
            _emit_ext_count(o, match_count - 3)
        _put(o, p0)
        _put(o, p1)
        _put(o, p2)
        ps += match_count * 3

    return ps


def compress_pattern_encode(bytes data):
    """Stage 2: pattern-matching encoder, native counterpart of the Python one."""
    cdef const unsigned char *p = data
    cdef Py_ssize_t n = len(data)
    cdef Py_ssize_t i, pp, s, k
    cdef Py_ssize_t pattern_start = 0
    cdef int src_val
    cdef int buf_len
    cdef bint has_pattern = False
    cdef int pattern_mode = 0
    cdef int match_count = 0
    cdef int phase_idx = 0
    cdef unsigned char p0 = 0
    cdef unsigned char p1 = 0
    cdef unsigned char p2 = 0
    cdef bint do_flush, skip_phase_reset, pattern_continues
    cdef bint do_buffer_check, do_literal_copy
    cdef int stride1_len, stride2_half, stride3_first, stride2_len
    cdef int stride2_b_len, stride3_b_len, stride3_c_len, stride3_alt_len, lit_count
    cdef OutBuf o
    cdef bytes result

    o.len = 0
    o.cap = n + 64
    if o.cap < 64:
        o.cap = 64
    o.data = <unsigned char *>malloc(o.cap)
    o.failed = False
    if o.data == NULL:
        o.cap = 0
        raise MemoryError()

    with nogil:
        for i in range(n):
            src_val = p[i]
            buf_len = <int>(i + 1 - pattern_start)

            do_flush = False
            skip_phase_reset = False

            if has_pattern:
                phase_idx += 1
                pattern_continues = False

                if pattern_mode == 0:
                    if src_val == p0:
                        match_count += 1
                        phase_idx = 0
                        if buf_len < 0x400:
                            pattern_continues = True
                elif pattern_mode == 1:
                    do_buffer_check = False
                    if phase_idx == 1:
                        if src_val == p0:
                            do_buffer_check = True
                    else:
                        match_count += 1
                        phase_idx = 0
                        do_buffer_check = True
                    if do_buffer_check and buf_len < 0x400:
                        pattern_continues = True
                elif pattern_mode == 2:
                    do_buffer_check = False
                    if phase_idx == 1:
                        if src_val == p0:
                            do_buffer_check = True
                    elif src_val == p1:
                        match_count += 1
                        phase_idx = 0
                        do_buffer_check = True
                    if do_buffer_check and buf_len < 0x400:
                        pattern_continues = True
                elif pattern_mode == 3:
                    do_buffer_check = False
                    if phase_idx == 1:
                        if src_val == p0:
                            do_buffer_check = True
                    else:
                        if phase_idx != 2:
                            match_count += 1
                            phase_idx = 0
                        do_buffer_check = True
                    if do_buffer_check and buf_len < 0x400:
                        pattern_continues = True
                elif pattern_mode == 4:
                    do_buffer_check = False
                    if phase_idx == 1:
                        if src_val == p0:
                            do_buffer_check = True
                    elif phase_idx == 2:
                        if src_val == p1:
                            do_buffer_check = True
                    else:
                        match_count += 1
                        phase_idx = 0
                        do_buffer_check = True
                    if do_buffer_check and buf_len < 0x400:
                        pattern_continues = True
                elif pattern_mode == 5:
                    do_buffer_check = False
                    if phase_idx == 1:
                        if src_val == p0:
                            do_buffer_check = True
                    elif phase_idx == 2:
                        if src_val == p1:
                            do_buffer_check = True
                    elif src_val == p2:
                        match_count += 1
                        phase_idx = 0
                        do_buffer_check = True
                    if do_buffer_check and buf_len < 0x400:
                        pattern_continues = True

                if pattern_continues:
                    skip_phase_reset = True
                else:
                    do_flush = True
                    has_pattern = False
            elif buf_len != 12:
                skip_phase_reset = True
            else:
                # Analyze the 12-byte window for patterns
                pp = pattern_start
                p0 = p[pp]

                # Stride-1: consecutive bytes matching p0
                stride1_len = 1
                while stride1_len < 12 and p[pp + stride1_len] == p0:
                    stride1_len += 1

                # Stride-2 half: p0 at even positions
                stride2_half = 2
                while stride2_half < 12 and p[pp + stride2_half] == p0:
                    stride2_half += 2
                stride2_half >>= 1

                # Stride-3 first: p0 at positions 0,3,6,9
                stride3_first = 3
                stride2_len = 1
                while stride3_first < 12 and p[pp + stride3_first] == p0:
                    stride3_first += 3
                    stride2_len += 1

                p1 = p[pp + 1]

                # Stride-2 B: p1 at odd positions (3,5,7,...)
                stride2_b_len = 1
                if stride2_half > 1:
                    s = 3
                    while s < 12 and p[pp + s] == p1:
                        s += 2
                    stride2_b_len = <int>((s - 1) >> 1)
                    if stride2_half < stride2_b_len:
                        stride2_b_len = stride2_half

                p2 = p[pp + 2]

                # Stride-3 B and C lengths
                if stride2_len < 2:
                    stride3_b_len = 1
                    stride3_c_len = 1
                else:
                    s = 4
                    stride3_b_len = 1
                    while s < 12 and p[pp + s] == p1:
                        s += 3
                        stride3_b_len += 1
                    if stride2_len < stride3_b_len:
                        stride3_b_len = stride2_len

                    s = 5
                    stride3_c_len = 1
                    while s < 12 and p[pp + s] == p2:
                        s += 3
                        stride3_c_len += 1
                    if stride2_len < stride3_c_len:
                        stride3_c_len = stride2_len

                # Min of stride3_b and stride3_c
                stride3_alt_len = 1
                if stride3_b_len > 1:
                    stride3_alt_len = stride3_b_len
                    if stride3_c_len <= stride3_b_len:
                        stride3_alt_len = stride3_c_len

                # Select best pattern
                if stride1_len == 12:
                    pattern_mode = 0
                    has_pattern = True
                    match_count = 12
                elif stride2_b_len == 6:
                    pattern_mode = 2
                    has_pattern = True
                    match_count = 6
                elif stride2_half == 6:
                    pattern_mode = 1
                    has_pattern = True
                    match_count = 6
                elif stride3_alt_len == 4:
                    pattern_mode = 5
                    has_pattern = True
                    match_count = 4
                elif stride3_b_len == 4:
                    pattern_mode = 4
                    has_pattern = True
                    match_count = 4
                elif stride2_len == 4:
                    pattern_mode = 3
                    has_pattern = True
                    match_count = 4
                else:
                    # No long pattern — try short flush or literal copy
                    do_literal_copy = False
                    lit_count = 2

                    if stride3_c_len == 4 and stride2_len >= 2:
                        do_literal_copy = True
                        lit_count = 2
                    elif stride3_alt_len >= 2:
                        lit_count = stride3_alt_len
                        if stride3_alt_len > 2:
                            pattern_mode = 5
                            match_count = stride3_alt_len
                            do_flush = True
                        else:
                            lit_count = stride3_alt_len * 3
                            do_literal_copy = True
                    elif stride3_b_len > 1:
                        lit_count = stride3_b_len
                        if stride3_b_len > 2:
                            pattern_mode = 4
                            match_count = stride3_b_len
                            do_flush = True
                        else:
                            lit_count = stride3_b_len * 3
                            do_literal_copy = True
                    elif stride3_c_len >= 2 and stride2_len >= 2:
                        lit_count = 2
                        do_literal_copy = True
                    elif stride2_len >= 3:
                        lit_count = stride2_len
                        if stride2_len > 3:
                            pattern_mode = 3
                            match_count = stride2_len
                            do_flush = True
                        else:
                            lit_count = stride2_len * 3
                            do_literal_copy = True
                    elif stride2_b_len >= 2:
                        lit_count = stride2_b_len
                        if stride2_b_len > 4:
                            pattern_mode = 2
                            match_count = stride2_b_len
                            do_flush = True
                        else:
                            lit_count = lit_count << 1
                            do_literal_copy = True
                    elif stride2_half >= 3:
                        lit_count = stride2_half
                        if stride2_half > 3:
                            pattern_mode = 1
                            match_count = stride2_half
                            do_flush = True
                        else:
                            lit_count = lit_count << 1
                            do_literal_copy = True
                    else:
                        if stride1_len < 3:
                            lit_count = 1
                        else:
                            lit_count = stride1_len
                            if stride1_len > 5:
                                pattern_mode = 0
                                match_count = stride1_len
                                do_flush = True
                        if not do_flush:
                            do_literal_copy = True

                    if do_literal_copy:
                        for k in range(lit_count):
                            _put(&o, p[pattern_start])
                            pattern_start += 1

            if do_flush:
                pattern_start = _pattern_flush(
                    &o, pattern_mode, match_count, p0, p1, p2, p, pattern_start
                )
                has_pattern = False

            if not skip_phase_reset:
                phase_idx = 0

        # End of input — flush remaining pattern + literals
        if has_pattern:
            pattern_start = _pattern_flush(
                &o, pattern_mode, match_count, p0, p1, p2, p, pattern_start
            )

        while pattern_start < n:
            _put(&o, p[pattern_start])
            pattern_start += 1

    if o.failed:
        free(o.data)
        raise MemoryError()
    result = PyBytes_FromStringAndSize(<char *>o.data, o.len)
    free(o.data)
    return result


def encode_fine_plane(bytes data):
    """Run both stages back to back; empty bytes for an all-zero scanline."""
    cdef Py_ssize_t i, n = len(data)
    cdef const unsigned char *p = data
    cdef bint nonzero = False

    with nogil:
        for i in range(n):
            if p[i]:
                nonzero = True
                break
    if not nonzero:
        return b""

    cdef bytes stage1 = compress_rle_preencode(data)
    if not stage1:
        return b""
    return compress_pattern_encode(stage1)
