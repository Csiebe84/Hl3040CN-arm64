// SPDX-License-Identifier: GPL-3.0-or-later
//! Fine-mode (1200 dpi) XL2HB encoders: nibble-aware RLE (Stage 1) and the
//! pattern-matching encoder (Stage 2).
//!
//! Rust counterpart of `_fine_fast.pyx`.  `compress_rle_preencode` maps 4bpp
//! nibble-packed scanlines to a byte stream in 0x10..0xFF; `compress_pattern_encode`
//! detects stride-1/2/3 patterns in a 12-byte look-ahead window and emits
//! 0x00..0x0F pattern headers; `encode_fine_plane` chains both stages.
//!
//! Bit-exactness is the contract: every `& 0xFF` mask and the i32 wrap-around of
//! the Cython arithmetic is reproduced on purpose.  The reference keeps a `ring`
//! copy of the input for Stage 2; here the input slice is read directly, which
//! is equivalent because nothing ever rewrites it.

use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Quantize 4bpp nibbles to 9 levels: clear the LSB of each nibble unless it is
/// 0xF.  Byte-for-byte the same table as `fine_encoder._QUANTIZE`.
static QUANT: [u8; 256] = build_quant();

const fn build_quant() -> [u8; 256] {
    let mut t = [0u8; 256];
    let mut i = 0usize;
    while i < 256 {
        let mut hi = (i >> 4) & 0xF;
        let mut lo = i & 0xF;
        if hi != 0xF {
            hi &= 0xE;
        }
        if lo != 0xF {
            lo &= 0xE;
        }
        t[i] = ((hi << 4) | lo) as u8;
        i += 1;
    }
    t
}

/// Growable output buffer, the Rust counterpart of the Cython `OutBuf`.
#[derive(Default)]
struct OutBuf {
    data: Vec<u8>,
}

impl OutBuf {
    #[inline]
    fn put(&mut self, b: u8) {
        self.data.push(b);
    }

    /// Emit a run length as count-extension bytes: 0xFF for each 255, then the
    /// remainder.  Matches `_emit_ext_count`.
    fn emit_ext_count(&mut self, mut remaining: i64) {
        while remaining > 0xFE {
            self.put(0xFF);
            remaining -= 0xFF;
        }
        self.put((remaining & 0xFF) as u8);
    }
}

// ---------------------------------------------------------------------------
// Stage 1: nibble-aware RLE
// ---------------------------------------------------------------------------

/// Flush a white run: 0x17 per full group of eight, then the remainder with the
/// 0x10 base.  Matches `_flush_white`.
#[inline]
fn flush_white(o: &mut OutBuf, run: &mut i32) {
    let mut r = *run;
    while r > 8 {
        o.put(0x17);
        r -= 8;
    }
    o.put((((r - 1) | 0x10) & 0xFF) as u8);
    *run = 0;
}

/// Flush a black run: 0x1F per full group of eight, then the remainder with the
/// 0x18 base.  Matches `_flush_black`.
#[inline]
fn flush_black(o: &mut OutBuf, run: &mut i32) {
    let mut r = *run;
    while r > 8 {
        o.put(0x1F);
        r -= 8;
    }
    o.put((((r - 1) | 0x18) & 0xFF) as u8);
    *run = 0;
}

/// Stage 1: nibble-aware RLE, native counterpart of the Python version.
///
/// Input: 4bpp nibble-packed scanline data.  Output opcodes use 0x10..0xFF;
/// 0x00..0x0F are reserved for Stage 2.
#[pyfunction]
pub fn compress_rle_preencode<'py>(py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    let n = data.len();
    let mut o = OutBuf {
        data: Vec::with_capacity(n + 64),
    };

    let mut run_white: i32 = 0;
    let mut run_black: i32 = 0;

    for i in 0..n {
        let src_val = i32::from(QUANT[data[i] as usize]);

        if src_val == 0x00 {
            // White byte
            if run_black == 0 {
                run_white += 1;
            } else {
                if run_black < 5 {
                    o.put(((((run_black * 8 - 8) & 0xFF) | 0x80) & 0xFF) as u8);
                } else {
                    flush_black(&mut o, &mut run_black);
                    run_white += 1;
                }
                run_black = 0;
            }
        } else if src_val == 0xFF {
            // Black byte
            if run_white == 0 {
                run_black += 1;
            } else {
                if run_white < 3 {
                    o.put(((((run_white * 8 - 8) & 0xFF) | 0x27) & 0xFF) as u8);
                } else {
                    flush_white(&mut o, &mut run_white);
                    run_black += 1;
                }
                run_white = 0;
            }
        } else {
            let hi_nibble = src_val & 0xF0;
            let lo_nibble = src_val & 0x0F;

            if hi_nibble == 0xF0 {
                // Hi = full ink (0xF_)
                if run_white == 0 {
                    if run_black != 0 {
                        if run_black > 3 {
                            run_black -= 3;
                            flush_black(&mut o, &mut run_black);
                            run_black = 3;
                        }
                        o.put((((run_black * 8) | (lo_nibble >> 1) | 0xC0) & 0xFF) as u8);
                        run_black = 0;
                        continue;
                    }
                } else {
                    if lo_nibble == 0 {
                        if run_white > 3 {
                            run_white -= 3;
                            flush_white(&mut o, &mut run_white);
                            run_white = 3;
                        }
                        o.put((((run_white * 8) | 0xA7) & 0xFF) as u8);
                        run_white = 0;
                        continue;
                    }
                    flush_white(&mut o, &mut run_white);
                }
                o.put((((lo_nibble >> 1) | 0xC0) & 0xFF) as u8);
            } else if lo_nibble == 0 {
                // Lo = no ink (0x_0)
                if run_white != 0 {
                    if run_white > 3 {
                        run_white -= 3;
                        flush_white(&mut o, &mut run_white);
                        run_white = 3;
                    }
                    o.put(((((run_white * 8) & 0xFF) | ((hi_nibble >> 5) - 1) | 0xA0) & 0xFF) as u8);
                    run_white = 0;
                    continue;
                }
                if run_black != 0 {
                    if run_black > 4 {
                        run_black -= 4;
                        flush_black(&mut o, &mut run_black);
                        run_black = 4;
                    }
                    o.put(((((run_black * 8 - 8) & 0xFF) | (hi_nibble >> 5) | 0x80) & 0xFF) as u8);
                    run_black = 0;
                    continue;
                }
                o.put(((((hi_nibble >> 5) - 1) | 0xA0) & 0xFF) as u8);
            } else if lo_nibble == 0x0F {
                // Lo = full ink (0x_F)
                if run_white != 0 {
                    if run_white > 2 {
                        run_white -= 2;
                        flush_white(&mut o, &mut run_white);
                        run_white = 2;
                    }
                    if hi_nibble == 0 {
                        o.put((((run_white * 8 - 8) & 0xFF) | 0x37) as u8);
                    } else {
                        o.put((((run_white * 8 - 8) & 0xFF) | ((hi_nibble >> 5) - 1) | 0x20) as u8);
                    }
                    run_white = 0;
                    continue;
                }
                if run_black != 0 {
                    if run_black > 4 {
                        run_black -= 4;
                        flush_black(&mut o, &mut run_black);
                        run_black = 4;
                    }
                    o.put((((run_black * 8 - 8) & 0xFF) | (hi_nibble >> 5) | 0xE0) as u8);
                    run_black = 0;
                    continue;
                }
                o.put((((hi_nibble >> 2) | 0x47) & 0xFF) as u8);
            } else if hi_nibble == 0 {
                // General mixed: both nibbles non-zero, non-full
                if run_black == 0 {
                    if run_white != 0 {
                        if run_white > 2 {
                            run_white -= 2;
                            flush_white(&mut o, &mut run_white);
                            run_white = 2;
                        }
                        o.put((((run_white * 8 - 8) & 0xFF) | ((lo_nibble >> 1) - 1) | 0x30) as u8);
                        run_white = 0;
                        continue;
                    }
                } else {
                    flush_black(&mut o, &mut run_black);
                }
                o.put((((lo_nibble >> 1) - 1) | 0x40) as u8);
            } else {
                if run_white == 0 {
                    if run_black != 0 {
                        flush_black(&mut o, &mut run_black);
                    }
                } else {
                    flush_white(&mut o, &mut run_white);
                }
                o.put((((hi_nibble >> 2) | ((lo_nibble >> 1) - 1) | 0x40) & 0xFF) as u8);
            }
        }
    }

    // Flush trailing runs
    if run_white != 0 {
        flush_white(&mut o, &mut run_white);
    } else if run_black != 0 {
        flush_black(&mut o, &mut run_black);
    }

    Ok(PyBytes::new(py, &o.data))
}

// ---------------------------------------------------------------------------
// Stage 2: pattern-matching encoder
// ---------------------------------------------------------------------------

/// Flush a detected pattern; returns the updated `pattern_start`.
///
/// `pattern_mode` selects the stride layout, `p0`/`p1`/`p2` are the pattern's
/// first bytes and `src`/`pattern_start` locate it in the input.  Matches
/// `_pattern_flush` in `_fine_fast.pyx` byte for byte.
fn pattern_flush(
    o: &mut OutBuf,
    pattern_mode: i32,
    match_count: i32,
    p0: u8,
    p1: u8,
    p2: u8,
    src: &[u8],
    pattern_start: i64,
) -> i64 {
    let mut ps = pattern_start;
    let mc = i64::from(match_count);

    match pattern_mode {
        0 => {
            // Stride-1 repeat (A,A,A,...)
            if mc - 3 < 3 {
                o.put(((mc - 3) & 0xFF) as u8);
            } else {
                o.put(3);
                o.emit_ext_count(mc - 6);
            }
            o.put(p0);
            ps += mc;
        }
        1 => {
            // Stride-2 half (A,x,A,x,...) — emit A then each odd byte
            if mc == 3 {
                o.put(0x08);
            } else {
                o.put(0x09);
                o.emit_ext_count(mc - 4);
            }
            o.put(p0);
            for _ in 0..mc {
                o.put(src[(ps + 1) as usize]);
                ps += 2;
            }
        }
        2 => {
            // Stride-2 full (A,B,A,B,...)
            if mc - 2 < 3 {
                o.put((((mc - 2) | 0x04) & 0xFF) as u8);
            } else {
                o.put(0x07);
                o.emit_ext_count(mc - 5);
            }
            o.put(p0);
            o.put(p1);
            ps += mc * 2;
        }
        3 => {
            // Stride-3 third (A,x,x,A,x,x,...) — emit A then each non-A pair
            if mc == 3 {
                o.put(0x0A);
            } else {
                o.put(0x0B);
                o.emit_ext_count(mc - 4);
            }
            o.put(p0);
            for _ in 0..mc {
                o.put(src[(ps + 1) as usize]);
                o.put(src[(ps + 2) as usize]);
                ps += 3;
            }
        }
        4 => {
            // Stride-3 two-thirds (A,B,x,A,B,x,...) — emit A,B then each third byte
            if mc == 2 {
                o.put(0x0C);
            } else {
                o.put(0x0D);
                o.emit_ext_count(mc - 3);
            }
            o.put(p0);
            o.put(p1);
            for _ in 0..mc {
                o.put(src[(ps + 2) as usize]);
                ps += 3;
            }
        }
        5 => {
            // Stride-3 full (A,B,C,A,B,C,...)
            if mc == 2 {
                o.put(0x0E);
            } else {
                o.put(0x0F);
                o.emit_ext_count(mc - 3);
            }
            o.put(p0);
            o.put(p1);
            o.put(p2);
            ps += mc * 3;
        }
        _ => {}
    }

    ps
}

/// Stage 2: pattern-matching encoder, native counterpart of the Python one.
#[pyfunction]
pub fn compress_pattern_encode<'py>(py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    let n = data.len() as i64;
    let mut o = OutBuf {
        data: Vec::with_capacity(data.len() + 64),
    };

    let mut pattern_start: i64 = 0;
    let mut has_pattern = false;
    let mut pattern_mode: i32 = 0;
    let mut match_count: i32 = 0;
    let mut phase_idx: i32 = 0;
    let mut p0: u8 = 0;
    let mut p1: u8 = 0;
    let mut p2: u8 = 0;

    for i in 0..n {
        let src_val = i32::from(data[i as usize]);
        let buf_len = i + 1 - pattern_start;

        let mut do_flush = false;
        let mut skip_phase_reset = false;

        if has_pattern {
            phase_idx += 1;
            let mut pattern_continues = false;

            if pattern_mode == 0 {
                if src_val == i32::from(p0) {
                    match_count += 1;
                    phase_idx = 0;
                    if buf_len < 0x400 {
                        pattern_continues = true;
                    }
                }
            } else if pattern_mode == 1 {
                let mut do_buffer_check = false;
                if phase_idx == 1 {
                    if src_val == i32::from(p0) {
                        do_buffer_check = true;
                    }
                } else {
                    match_count += 1;
                    phase_idx = 0;
                    do_buffer_check = true;
                }
                if do_buffer_check && buf_len < 0x400 {
                    pattern_continues = true;
                }
            } else if pattern_mode == 2 {
                let mut do_buffer_check = false;
                if phase_idx == 1 {
                    if src_val == i32::from(p0) {
                        do_buffer_check = true;
                    }
                } else if src_val == i32::from(p1) {
                    match_count += 1;
                    phase_idx = 0;
                    do_buffer_check = true;
                }
                if do_buffer_check && buf_len < 0x400 {
                    pattern_continues = true;
                }
            } else if pattern_mode == 3 {
                let mut do_buffer_check = false;
                if phase_idx == 1 {
                    if src_val == i32::from(p0) {
                        do_buffer_check = true;
                    }
                } else {
                    if phase_idx != 2 {
                        match_count += 1;
                        phase_idx = 0;
                    }
                    do_buffer_check = true;
                }
                if do_buffer_check && buf_len < 0x400 {
                    pattern_continues = true;
                }
            } else if pattern_mode == 4 {
                let mut do_buffer_check = false;
                if phase_idx == 1 {
                    if src_val == i32::from(p0) {
                        do_buffer_check = true;
                    }
                } else if phase_idx == 2 {
                    if src_val == i32::from(p1) {
                        do_buffer_check = true;
                    }
                } else {
                    match_count += 1;
                    phase_idx = 0;
                    do_buffer_check = true;
                }
                if do_buffer_check && buf_len < 0x400 {
                    pattern_continues = true;
                }
            } else if pattern_mode == 5 {
                let mut do_buffer_check = false;
                if phase_idx == 1 {
                    if src_val == i32::from(p0) {
                        do_buffer_check = true;
                    }
                } else if phase_idx == 2 {
                    if src_val == i32::from(p1) {
                        do_buffer_check = true;
                    }
                } else if src_val == i32::from(p2) {
                    match_count += 1;
                    phase_idx = 0;
                    do_buffer_check = true;
                }
                if do_buffer_check && buf_len < 0x400 {
                    pattern_continues = true;
                }
            }

            if pattern_continues {
                skip_phase_reset = true;
            } else {
                do_flush = true;
                has_pattern = false;
            }
        } else if buf_len != 12 {
            skip_phase_reset = true;
        } else {
            // Analyze the 12-byte window for patterns
            let pp = pattern_start as usize;
            p0 = data[pp];

            // Stride-1: consecutive bytes matching p0
            let mut stride1_len: i32 = 1;
            while stride1_len < 12 && data[pp + stride1_len as usize] == p0 {
                stride1_len += 1;
            }

            // Stride-2 half: p0 at even positions
            let mut stride2_half: i32 = 2;
            while stride2_half < 12 && data[pp + stride2_half as usize] == p0 {
                stride2_half += 2;
            }
            stride2_half >>= 1;

            // Stride-3 first: p0 at positions 0,3,6,9
            let mut stride3_first: i32 = 3;
            let mut stride2_len: i32 = 1;
            while stride3_first < 12 && data[pp + stride3_first as usize] == p0 {
                stride3_first += 3;
                stride2_len += 1;
            }

            p1 = data[pp + 1];

            // Stride-2 B: p1 at odd positions (3,5,7,...)
            let mut stride2_b_len: i32 = 1;
            if stride2_half > 1 {
                let mut s: i32 = 3;
                while s < 12 && data[pp + s as usize] == p1 {
                    s += 2;
                }
                stride2_b_len = (s - 1) >> 1;
                if stride2_half < stride2_b_len {
                    stride2_b_len = stride2_half;
                }
            }

            p2 = data[pp + 2];

            // Stride-3 B and C lengths
            let mut stride3_b_len: i32;
            let mut stride3_c_len: i32;
            if stride2_len < 2 {
                stride3_b_len = 1;
                stride3_c_len = 1;
            } else {
                let mut s: i32 = 4;
                stride3_b_len = 1;
                while s < 12 && data[pp + s as usize] == p1 {
                    s += 3;
                    stride3_b_len += 1;
                }
                if stride2_len < stride3_b_len {
                    stride3_b_len = stride2_len;
                }

                s = 5;
                stride3_c_len = 1;
                while s < 12 && data[pp + s as usize] == p2 {
                    s += 3;
                    stride3_c_len += 1;
                }
                if stride2_len < stride3_c_len {
                    stride3_c_len = stride2_len;
                }
            }

            // Min of stride3_b and stride3_c
            let mut stride3_alt_len: i32 = 1;
            if stride3_b_len > 1 {
                stride3_alt_len = stride3_b_len;
                if stride3_c_len <= stride3_b_len {
                    stride3_alt_len = stride3_c_len;
                }
            }

            // Select best pattern
            if stride1_len == 12 {
                pattern_mode = 0;
                has_pattern = true;
                match_count = 12;
            } else if stride2_b_len == 6 {
                pattern_mode = 2;
                has_pattern = true;
                match_count = 6;
            } else if stride2_half == 6 {
                pattern_mode = 1;
                has_pattern = true;
                match_count = 6;
            } else if stride3_alt_len == 4 {
                pattern_mode = 5;
                has_pattern = true;
                match_count = 4;
            } else if stride3_b_len == 4 {
                pattern_mode = 4;
                has_pattern = true;
                match_count = 4;
            } else if stride2_len == 4 {
                pattern_mode = 3;
                has_pattern = true;
                match_count = 4;
            } else {
                // No long pattern — try short flush or literal copy
                let mut do_literal_copy = false;
                let mut lit_count: i32 = 2;

                if stride3_c_len == 4 && stride2_len >= 2 {
                    do_literal_copy = true;
                    lit_count = 2;
                } else if stride3_alt_len >= 2 {
                    lit_count = stride3_alt_len;
                    if stride3_alt_len > 2 {
                        pattern_mode = 5;
                        match_count = stride3_alt_len;
                        do_flush = true;
                    } else {
                        lit_count = stride3_alt_len * 3;
                        do_literal_copy = true;
                    }
                } else if stride3_b_len > 1 {
                    lit_count = stride3_b_len;
                    if stride3_b_len > 2 {
                        pattern_mode = 4;
                        match_count = stride3_b_len;
                        do_flush = true;
                    } else {
                        lit_count = stride3_b_len * 3;
                        do_literal_copy = true;
                    }
                } else if stride3_c_len >= 2 && stride2_len >= 2 {
                    lit_count = 2;
                    do_literal_copy = true;
                } else if stride2_len >= 3 {
                    lit_count = stride2_len;
                    if stride2_len > 3 {
                        pattern_mode = 3;
                        match_count = stride2_len;
                        do_flush = true;
                    } else {
                        lit_count = stride2_len * 3;
                        do_literal_copy = true;
                    }
                } else if stride2_b_len >= 2 {
                    lit_count = stride2_b_len;
                    if stride2_b_len > 4 {
                        pattern_mode = 2;
                        match_count = stride2_b_len;
                        do_flush = true;
                    } else {
                        lit_count <<= 1;
                        do_literal_copy = true;
                    }
                } else if stride2_half >= 3 {
                    lit_count = stride2_half;
                    if stride2_half > 3 {
                        pattern_mode = 1;
                        match_count = stride2_half;
                        do_flush = true;
                    } else {
                        lit_count <<= 1;
                        do_literal_copy = true;
                    }
                } else {
                    if stride1_len < 3 {
                        lit_count = 1;
                    } else {
                        lit_count = stride1_len;
                        if stride1_len > 5 {
                            pattern_mode = 0;
                            match_count = stride1_len;
                            do_flush = true;
                        }
                    }
                    if !do_flush {
                        do_literal_copy = true;
                    }
                }

                if do_literal_copy {
                    for _ in 0..lit_count {
                        o.put(data[pattern_start as usize]);
                        pattern_start += 1;
                    }
                }
            }
        }

        if do_flush {
            pattern_start = pattern_flush(
                &mut o,
                pattern_mode,
                match_count,
                p0,
                p1,
                p2,
                data,
                pattern_start,
            );
            has_pattern = false;
        }

        if !skip_phase_reset {
            phase_idx = 0;
        }
    }

    // End of input — flush remaining pattern + literals
    if has_pattern {
        pattern_start = pattern_flush(
            &mut o,
            pattern_mode,
            match_count,
            p0,
            p1,
            p2,
            data,
            pattern_start,
        );
    }

    while pattern_start < n {
        o.put(data[pattern_start as usize]);
        pattern_start += 1;
    }

    Ok(PyBytes::new(py, &o.data))
}

/// Run both stages back to back; empty bytes for an all-zero scanline.
#[pyfunction]
pub fn encode_fine_plane<'py>(py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    if data.iter().all(|&b| b == 0) {
        return Ok(PyBytes::new(py, &[]));
    }

    let stage1 = compress_rle_preencode(py, data)?;
    if stage1.as_bytes().is_empty() {
        return Ok(PyBytes::new(py, &[]));
    }
    compress_pattern_encode(py, stage1.as_bytes())
}
