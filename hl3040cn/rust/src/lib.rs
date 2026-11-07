// SPDX-License-Identifier: GPL-3.0-or-later
// Native (Rust) counterparts of the Cython acceleration kernels for the
// Brother HL-3040CN CUPS driver.  Every function keeps the exact name and
// argument list of the `_*_fast` Cython module it replaces, so the Python
// driver needs no change: the shims in `rust/shims/` re-export them under the
// old module names.
//
// Equivalence is not assumed.  `test_fine_fast_equiv.py` replays a frozen
// golden corpus (26 256 real scanlines plus edge cases) and the rest of the
// suite pins the normal-mode output byte for byte.

use pyo3::prelude::*;

mod band;
mod color;
mod dither;
mod fine;
mod rle;

#[pymodule]
fn _hl3040cn_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // _dither_fast
    m.add_function(wrap_pyfunction!(dither::dither_row_1bpp, m)?)?;
    m.add_function(wrap_pyfunction!(dither::dither_row_4bpp_pattern, m)?)?;

    // _color_fast
    m.add_function(wrap_pyfunction!(color::gather_kcmy, m)?)?;
    m.add_function(wrap_pyfunction!(color::interp_kcmy, m)?)?;

    // _rle_fast
    m.add_function(wrap_pyfunction!(rle::group_bits, m)?)?;
    m.add_function(wrap_pyfunction!(rle::pack_groups, m)?)?;
    m.add_function(wrap_pyfunction!(rle::encode_sw_rle, m)?)?;

    // _band_fast
    m.add_function(wrap_pyfunction!(band::render_band, m)?)?;

    // _fine_fast
    m.add_function(wrap_pyfunction!(fine::compress_rle_preencode, m)?)?;
    m.add_function(wrap_pyfunction!(fine::compress_pattern_encode, m)?)?;
    m.add_function(wrap_pyfunction!(fine::encode_fine_plane, m)?)?;

    Ok(())
}
