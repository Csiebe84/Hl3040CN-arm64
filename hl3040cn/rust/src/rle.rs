// SPDX-License-Identifier: GPL-3.0-or-later
//! Native plane encoders for XL2HB: bit packing and sliding-window RLE.
//!
//! Rust counterpart of `_rle_fast.pyx`.  `group_bits` reads a byte stream as
//! N-bit groups (MSB first) and `pack_groups` is its inverse.  `encode_sw_rle`
//! is the native counterpart of `rle.sw_rle_encode`, parametrised by word size
//! (10, 12 or 20 bits); its core `encode_line` is shared with `band.rs`.
//!
//! Bit-exactness is the contract: the output must match the Cython module byte
//! for byte, so the plane encoders below reproduce the same overflow behaviour
//! (every `& 0xFF`, `& 0xF`, `& 0x3` mask is deliberate).

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Growable output buffer, the Rust counterpart of the Cython `OutBuf`.
#[derive(Default)]
pub struct OutBuf {
    pub data: Vec<u8>,
}

impl OutBuf {
    #[inline]
    pub fn put(&mut self, b: u8) {
        self.data.push(b);
    }

    /// Emit count-extension bytes: 0xFF for each 255, then a remainder byte.
    #[inline]
    fn count_ext(&mut self, mut remaining: i64) {
        while remaining > 254 {
            self.put(0xFF);
            remaining -= 255;
        }
        self.put((remaining & 0xFF) as u8);
    }
}

/// Group raw bytes into MSB-first values of `group_size` bits each.
///
/// Last group is zero-padded if the bit count isn't a multiple of
/// `group_size`.
#[pyfunction]
pub fn group_bits(py: Python<'_>, data: &[u8], group_size: i32) -> PyResult<Py<PyAny>> {
    let n = data.len();
    let total_bits = n * 8;
    if total_bits == 0 {
        return Ok(pyo3::types::PyList::empty(py).into_any().unbind());
    }

    let gs = group_size as usize;
    let n_full = total_bits / gs;
    let remaining = total_bits - n_full * gs;
    let mask: u64 = (1u64 << group_size) - 1;

    let out = pyo3::types::PyList::empty(py);
    let mut buf: u64 = 0;
    let mut buf_bits: i32 = 0;
    let mut byte_i = 0usize;

    for _ in 0..n_full {
        while buf_bits < group_size {
            buf = (buf << 8) | u64::from(data[byte_i]);
            byte_i += 1;
            buf_bits += 8;
        }
        out.append(((buf >> (buf_bits - group_size)) & mask) as u64)?;
        buf_bits -= group_size;
    }

    if remaining > 0 {
        while byte_i < n {
            buf = (buf << 8) | u64::from(data[byte_i]);
            byte_i += 1;
            buf_bits += 8;
        }
        // Take the next `remaining` bits MSB-first and place them at the
        // high end of a `group_size`-bit value (zero-padded at the bottom).
        let value = ((buf >> (buf_bits - remaining as i32)) & ((1u64 << remaining) - 1)) << (group_size - remaining as i32);
        out.append(value)?;
    }

    Ok(out.into_any().unbind())
}

/// Pack a list of N-bit values into bytes, MSB-first.
#[pyfunction]
pub fn pack_groups<'py>(
    py: Python<'py>,
    groups: &Bound<'py, PyAny>,
    group_size: i32,
) -> PyResult<Bound<'py, PyBytes>> {
    let n = groups.len()?;
    if n == 0 {
        return Ok(PyBytes::new(py, &[]));
    }

    let total_bits = n * group_size as usize;
    let out_len = (total_bits + 7) / 8;
    let mut out = vec![0u8; out_len];

    let mut buf: u64 = 0;
    let mut buf_bits: i32 = 0;
    let mut oi = 0usize;
    let mask: u64 = (1u64 << group_size) - 1;

    for i in 0..n {
        let val = (groups.get_item(i)?.extract::<u64>()?) & mask;
        buf = (buf << group_size) | val;
        buf_bits += group_size;
        while buf_bits >= 8 {
            out[oi] = ((buf >> (buf_bits - 8)) & 0xFF) as u8;
            oi += 1;
            buf_bits -= 8;
        }
    }

    if buf_bits > 0 {
        out[oi] = ((buf << (8 - buf_bits)) & 0xFF) as u8;
    }

    Ok(PyBytes::new(py, &out))
}

// ---------------------------------------------------------------------------
// Sliding-window RLE encoder (native port of rle.sw_rle_encode + plane glue)
// ---------------------------------------------------------------------------

/// Emit a run of identical N-bit values.
fn emit_run(o: &mut OutBuf, value: u32, count: i64, bits: i32) {
    if bits == 10 {
        let v_hi = (value >> 8) & 0x3;
        if count <= 31 {
            o.put((0x80 | ((count - 1) << 2) | v_hi as i64) as u8);
            o.put((value & 0xFF) as u8);
        } else {
            o.put((0xFC | v_hi) as u8);
            o.put((value & 0xFF) as u8);
            o.count_ext(count - 32);
        }
        return;
    }

    let v_hi = (value >> (bits - 4)) & 0xF;
    if count < 8 {
        o.put((0x80 | ((count - 1) << 4) | v_hi as i64) as u8);
    } else {
        o.put((0xF0 | v_hi) as u8);
    }
    if bits > 12 {
        o.put(((value >> 8) & 0xFF) as u8);
    }
    o.put((value & 0xFF) as u8);
    if count >= 8 {
        o.count_ext(count - 8);
    }
}

/// Emit a block of literal N-bit values.
fn emit_literal(o: &mut OutBuf, vals: &[u32], count: i64, bits: i32) {
    let mut buf: u64 = 0;
    let mut buf_bits: i32 = 0;
    if count < 0x41 {
        o.put(((count - 2) | 0x40) as u8);
    } else {
        o.put(0x7F);
        o.count_ext(count - 0x41);
    }
    for &v in &vals[..count as usize] {
        buf = (buf << bits) | u64::from(v);
        buf_bits += bits;
        while buf_bits >= 8 {
            o.data.push(((buf >> (buf_bits - 8)) & 0xFF) as u8);
            buf_bits -= 8;
        }
    }
    if buf_bits > 0 {
        o.data.push(((buf << (8 - buf_bits)) & 0xFF) as u8);
    }
}

/// Emit a context-skip command for the sliding-window encoder.
fn emit_context_skip(o: &mut OutBuf, count: i64) {
    if count < 64 {
        o.put((count - 1) as u8);
    } else {
        o.put(0x3F);
        o.count_ext(count - 64);
    }
}

/// Split the scanline into `bits`-bit words, MSB first, like `rle.group_bits`.
///
/// The last word is zero-padded.
fn extract_words(p: &[u8], bits: i32, out: &mut Vec<u32>) -> usize {
    let n_bytes = p.len();
    let n_words = (n_bytes * 8 + bits as usize - 1) / bits as usize;
    out.clear();
    out.reserve(n_words);
    let mut byte_i = 0usize;
    let mut buf: u64 = 0;
    let mut buf_bits: i32 = 0;
    let mask: u64 = (1u64 << bits) - 1;
    for _ in 0..n_words {
        // Refill so that at least `bits` bits are buffered (zeros past end).
        while buf_bits < bits {
            if byte_i < n_bytes {
                buf = (buf << 8) | u64::from(p[byte_i]);
            } else {
                buf <<= 8;
            }
            byte_i += 1;
            buf_bits += 8;
        }
        out.push(((buf >> (buf_bits - bits)) & mask) as u32);
        buf_bits -= bits;
    }
    n_words
}

/// Port of `rle.sw_rle_encode`; state names follow the Python version.
///
/// `bits` selects the settings of `rle.CONFIG_10BIT` / `CONFIG_12BIT` /
/// `CONFIG_20BIT` (context size, literal overflow, skip_counts_current); keep
/// the two in sync.  `wbuf` is scratch space for at least `n + 2` words.
fn sw_rle(words: &[u32], bits: i32, o: &mut OutBuf) {
    let ctx_size: usize = if bits == 10 { 5 } else { 3 };
    let lit_overflow: i64 = if bits == 10 { 0xFFF } else { 0x7FF };
    let skip_counts_current = bits == 10;

    let n = words.len() as i64;
    let mut ctx = [0u32; 5];
    let mut match_count: i64 = 0;
    let mut run_len: i64 = 0;
    // `wlen` and `run_len` are function-scope in the Cython original; `wlen` is
    // written in MAIN and read again in LITERAL, so it must outlive the block.
    let mut wlen: i64 = 0;
    let mut wbuf: Vec<u32> = vec![0; words.len() + 2];

    if n == 0 {
        return;
    }

    let mut wi: i64 = 1;
    let mut cur = words[0];
    ctx[ctx_size - 1] = cur;
    if cur == 0 {
        match_count = 1;
    }
    // States: 0 MAIN, 1 RUN, 2 LITERAL, 3 CONTEXT_SKIP, 4 FINALIZE_LIT
    let mut state = 0;

    loop {
        if state == 0 {
            // MAIN
            let reference = ctx[1];
            for k in 0..ctx_size - 1 {
                ctx[k] = ctx[k + 1];
            }
            wbuf[0] = cur;
            wlen = 1;
            run_len = 1;
            if wi >= n {
                state = 4;
                continue;
            }
            let w = words[wi as usize];
            wi += 1;
            if reference == w {
                match_count += 1;
            } else {
                match_count = 0;
            }
            ctx[ctx_size - 1] = w;
            if cur == w {
                run_len = 2;
                state = 1;
                continue;
            }
            if match_count == 2 {
                if !skip_counts_current {
                    emit_run(o, cur, 1, bits);
                }
                state = 3;
                continue;
            }
            wbuf[1] = w;
            wlen = 2;
            run_len = 2;
            state = 2;
            continue;
        }

        if state == 1 {
            // RUN
            let reference = ctx[1];
            for k in 0..ctx_size - 1 {
                ctx[k] = ctx[k + 1];
            }
            if wi >= n {
                emit_run(o, cur, run_len, bits);
                return;
            }
            let w = words[wi as usize];
            wi += 1;
            if reference == w {
                match_count += 1;
            } else {
                match_count = 0;
            }
            ctx[ctx_size - 1] = w;
            if cur == w {
                run_len += 1;
                continue;
            }
            emit_run(o, cur, run_len, bits);
            cur = w;
            if match_count != 0 {
                match_count = 1;
            }
            state = 0;
            continue;
        }

        if state == 2 {
            // LITERAL
            let reference = ctx[1];
            for k in 0..ctx_size - 1 {
                ctx[k] = ctx[k + 1];
            }
            if wi >= n {
                state = 4;
                continue;
            }
            let w = words[wi as usize];
            wi += 1;
            if reference == w {
                match_count += 1;
            } else {
                match_count = 0;
            }
            ctx[ctx_size - 1] = w;

            if match_count > 1 {
                if match_count - 1 < run_len {
                    let lit_n = run_len - match_count + 1;
                    if lit_n == 1 {
                        emit_run(o, wbuf[0], 1, bits);
                    } else {
                        emit_literal(o, &wbuf, lit_n, bits);
                    }
                    state = 3;
                    continue;
                }
                if !skip_counts_current {
                    emit_run(o, wbuf[0], 1, bits);
                }
                state = 3;
                continue;
            }

            if wbuf[(wlen - 1) as usize] == w {
                if run_len > 2 {
                    emit_literal(o, &wbuf, wlen - 1, bits);
                } else if run_len == 2 {
                    emit_run(o, wbuf[0], 1, bits);
                }
                cur = w;
                wbuf[0] = w;
                wlen = 1;
                run_len = 2;
                if match_count > 2 {
                    match_count = 2;
                }
                state = 1;
                continue;
            }

            if run_len + 1 > lit_overflow {
                let lit_n = run_len - 1;
                if lit_n == 1 {
                    emit_run(o, wbuf[0], 1, bits);
                } else {
                    emit_literal(o, &wbuf, lit_n, bits);
                }
                let last = wbuf[(wlen - 1) as usize];
                emit_run(o, last, 1, bits);
                cur = w;
                wbuf[0] = last;
                wbuf[1] = w;
                wlen = 2;
                run_len = 2;
                if match_count > 2 {
                    match_count = 2;
                }
                continue;
            }

            wbuf[wlen as usize] = w;
            wlen += 1;
            run_len += 1;
            continue;
        }

        if state == 3 {
            // CONTEXT_SKIP
            let reference = ctx[1];
            for k in 0..ctx_size - 1 {
                ctx[k] = ctx[k + 1];
            }
            if wi >= n {
                emit_context_skip(o, match_count);
                return;
            }
            let w = words[wi as usize];
            wi += 1;
            ctx[ctx_size - 1] = w;
            if reference != w {
                emit_context_skip(o, match_count);
                match_count = 0;
                cur = w;
                state = 0;
                continue;
            }
            match_count += 1;
            continue;
        }

        // state == 4: FINALIZE_LIT
        if match_count < run_len {
            let lit_n = run_len - match_count;
            if lit_n == 1 {
                emit_run(o, wbuf[0], 1, bits);
            } else {
                emit_literal(o, &wbuf, lit_n, bits);
            }
        } else if !skip_counts_current {
            emit_run(o, wbuf[0], 1, bits);
        }
        if match_count > 0 {
            emit_context_skip(o, match_count);
        }
        return;
    }
}

/// Append one plane scanline, sliding-window RLE encoded, to `o`.
///
/// Native equivalent of `plane_encoders._encode_via_sw_rle` over the words from
/// `rle.group_bits(data, bits)`.  `bits` is the word size and picks the config:
/// 12 (CONFIG_12BIT), 20 (CONFIG_20BIT) or 10 (CONFIG_10BIT).
///
/// Returns the number of bytes appended (0 if every word is zero).
pub fn encode_line(p: &[u8], bits: i32, o: &mut OutBuf) -> usize {
    let n_bytes = p.len();
    let start = o.data.len();
    if n_bytes == 0 {
        return 0;
    }
    let mut words: Vec<u32> = Vec::new();
    let n_words = extract_words(p, bits, &mut words);
    if !words.iter().any(|&w| w != 0) {
        return 0;
    }

    o.data.reserve(n_words * 3 + 64);
    sw_rle(&words, bits, o);

    if o.data.len() - start > n_bytes + 0x14 {
        // Raw fallback, see rle.finalize_compressed.
        o.data.truncate(start);
        if n_words < 0x41 {
            o.put(((n_words - 2) | 0x40) as u8);
        } else {
            o.put(0x7F);
            o.count_ext(n_words as i64 - 0x41);
        }
        let padded_bytes = (n_words * bits as usize + 7) / 8;
        let pad_count = padded_bytes - n_bytes;
        o.data.extend_from_slice(p);
        o.data.resize(o.data.len() + pad_count, 0);
    }

    o.data.len() - start
}

/// Encode one plane scanline with the sliding-window RLE, incl. raw fallback.
#[pyfunction]
pub fn encode_sw_rle<'py>(py: Python<'py>, data: &[u8], bits: i32) -> PyResult<Bound<'py, PyBytes>> {
    if bits != 10 && bits != 12 && bits != 20 {
        return Err(PyValueError::new_err(format!("unsupported word size {bits}")));
    }
    if data.is_empty() {
        return Ok(PyBytes::new(py, &[]));
    }
    let mut o = OutBuf::default();
    encode_line(data, bits, &mut o);
    Ok(PyBytes::new(py, &o.data))
}
