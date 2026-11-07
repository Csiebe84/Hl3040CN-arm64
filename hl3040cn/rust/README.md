# Native kernels (Rust / PyO3)

The hot paths of the driver were Cython (`.pyx` + a C compiler).  They are
being replaced by a single Rust extension, `_hl3040cn_native`, so that the
driver needs no C toolchain and no `cython` at install time, and so that a
prebuilt wheel is possible for any platform CUPS runs on.

The replacement is a **drop-in**: every function keeps the name and the
argument list of the `_*_fast` module it replaces, and the shims in
`shims/` re-export them under the old module names.  No call site in
`hl3040cn/src/` changes.

## Layout

```
rust/
├── Cargo.toml          # crate `hl3040cn-native`, cdylib + rlib
├── pyproject.toml      # maturin metadata (for wheels)
├── src/
│   ├── lib.rs          # #[pymodule] _hl3040cn_native
│   ├── dither.rs       # _dither_fast
│   ├── color.rs        # _color_fast
│   ├── rle.rs          # _rle_fast (+ the RLE core shared with band.rs)
│   ├── band.rs         # _band_fast
│   └── fine.rs         # _fine_fast
└── shims/              # the old module names, re-exporting the native ones
    ├── _dither_fast.py
    ├── _color_fast.py
    ├── _rle_fast.py
    ├── _band_fast.py
    └── _fine_fast.py
```

## API map

| old module | function | replaces |
|---|---|---|
| `_dither_fast` | `dither_row_1bpp` | `dither.dither_channel_1bpp_arr` |
| `_dither_fast` | `dither_row_4bpp_pattern` | `dither.dither_channel_4bpp_pattern_arr` |
| `_color_fast` | `gather_kcmy` | `color_lut._gather_planes` |
| `_color_fast` | `interp_kcmy` | `color_lut._rgb_to_cmyk_interp_arr` |
| `_rle_fast` | `group_bits`, `pack_groups` | `rle.group_bits_py`, `rle.pack_groups_py` |
| `_rle_fast` | `encode_sw_rle` | `rle.sw_rle_encode` + `rle.finalize_compressed` |
| `_band_fast` | `render_band` | the per-line loop in `pipeline._render_page` |
| `_fine_fast` | `compress_rle_preencode`, `compress_pattern_encode`, `encode_fine_plane` | the two pure-Python byte loops in `fine_encoder.py` |

`test_kernel_signature.py` pins the argument lists to the call sites, so a
signature drift fails the build instead of aborting jobs at print time.

## Loading

The driver imports the kernels from `hl3040cn/src/`, next to the Python
modules, and falls back to pure Python on `ImportError`.  So the built
`lib_hl3040cn_native.so` is copied there as `_hl3040cn_native.so`, and the
shims as `_*_fast.py`.  Nothing else has to change.

## Building

```bash
cd hl3040cn/rust
cargo build --release
cp target/release/lib_hl3040cn_native.so ../src/_hl3040cn_native.so
cp shims/_*_fast.py ../src/
```

> **Do not build on the Odroid.**  The board has 3.7 GB of RAM and a
> wear-sensitive micro SD; a parallel build has hard-reset it before, taking
> running chats and Home Assistant with it (AGENTS.md, Regel Nr. 1).  Build
> in CI or on the laptop worker.

## Correctness

Byte-exactness is the contract, not an aspiration:

* `test_fine_fast_equiv.py` replays a frozen golden corpus (26 256 real
  scanlines plus edge cases) through both stages of `_fine_fast` and requires
  byte-identical output, and cross-checks the native and Python paths on
  inputs the corpus never saw.
* `test_native_kernels_equiv.py` does the same for `_dither_fast`,
  `_color_fast`, `_rle_fast` and `_band_fast` from synthetic inputs, so the
  check runs even without Brother's proprietary blobs.
* The rest of the suite (191 tests) runs unchanged against the native
  kernels.

`cargo build` alone proves nothing about parity — it only proves it
compiles.  The tests are the proof.

## CI

`.github/workflows/rust-kernels.yml` builds the crate, stages the module and
the shims into `src/`, asserts that the native `.so` (not the Python
fallback) is what got imported, and runs the full suite.  The plain `tests`
workflow stays pure-Python, so it can be green while a kernel does not even
compile; this job is the one that covers the native path.
