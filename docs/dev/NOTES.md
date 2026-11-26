# HL-3040CN native ARM64 driver — work notes

Goal: print from the Odroid N2+ (arm64) without the i386 Docker container and
its qemu-i386 binfmt emulation.  Approach: port the GPL-3.0 hl4150 codebase,
which speaks the same XL2HB dialect.

Directories: `src/` (my tools), `hl3040cn/src/` (ported driver),
`ref/` (both proprietary filter binaries), `lut/`, `color_data/`.

## The 3040 speaks the same dialect as the 4150

Confirmed byte-for-byte, not by eye:

* Raster block layout identical: 8-byte header, `comp_type=0`, `bit_depth=4`,
  `quant_type=2`, `comp_size=12`, `row_width=640`, `line_count`, `data_size`.
* The 12-bit RLE encoder is the same.  For a 100 px black bar the oracle emits
  `ffff008f00f000ff9b`, and the ported encoder produces exactly that.
* The `CommentData` attribute (the 23-word band config) is identical:
  `(0,3,1,1,5,0,4,524,1,5,1,4,532,1,5,2,4,1034,1,5,3,4,524)`.
  The 3rd word is the colour flag: 1 = colour, 0 = grayscale (K only).
* K plane semantics: bit 1 = black.

## What is already byte-identical

For **solid black**, the whole XL2HB session is identical to Brother's filter —
79109 bytes, zero differences (`compare.py`).  That covers:

* band config, block headers, RLE, band splitting (2249/2249/2066 entries)
* **geometry** (see below)
* PJL header
* `@PJL EOJ` footer

Monochrome and all K-only patterns therefore pass.

## Geometry: solved

The printer's own `paperinfij2` is the authority.  Rule, verified for all 22
paper sizes against the filter's real output:

    image_width  = (paper_width + 31) & ~31
    image_height = (paper_height * 72 // 600) * 600 // 72

Examples: Letter 5100x6564 -> 5120x6558; A4 4958x6981 -> 4960x6975;
EnvDL 2600x5164 -> 2624x5158.  All 22 match exactly.

The 4150 formula (`min(ImagingArea, …)`) is wrong for the 3040 — there is no
ImagingArea file here and the paper table differs.

Two more 3040-specific details found by diffing:
* `SetPageOrigin` is **(0, 0)**, not the 4150's (100, 100).
* The PJL footer needs **`@PJL EOJ NAME="Print Job"`** before the final UEL.

## The remaining gap: colour separation

4 of 12 patterns are byte-identical; every failing one is a colour page.
Black, white, and all K-only bars pass.

Measured ink levels for a solid red page (from the oracle, via dither density):

| plane | oracle | ported driver |
|---|---|---|
| M | ~177 | 255 |
| Y | ~127 | 6 |

So the 3040 separates red very differently: much less magenta, much more
yellow.  The 4150's `rgb_default` grid gives `C=255 M=255 Y=6` for red, which
is nothing like it.

### Colour grids: located, not yet identified

The grids are 17x17x17 packed CMYK arrays in the filter binary.  Found by
structure (every value fits a byte, white corner zero, smoothly varying) —
note some sit at odd byte offsets, which is why a u16-only scan misses them.

Two are proven by hash, because they are byte-equal to the 4150's own tables:

| offset | equals 4150 | meaning |
|---|---|---|
| `0x2a541` | `cmyk_default` | colour matching = None |
| `0x47340` | `cmyk_ig_default` | None + grey handling |

`0x9e25c`, `0xbb054`, `0xc4a36`, `0x646bb`, `0x814b3`, `0xce416`, `0x6e0bd`,
`0x8ae95`, `0x94875`, `0xa7c5e` are 3040-specific and still unnamed.  Candidate
grids are enumerated by `src/find_luts.py`.

**None of the located grids produces the oracle's red ink values** (M~177,
Y~127).  Best so far is `0x9e25c` at M=105 Y=1.  So either the right grid is
still unfound, or there is a colour-management stage before/after the grid
lookup (saturation, UCR/GCR, brightness/contrast remap) that differs.

Note: the `rc` file's `BRGray=ON` makes the filter emit a grayscale
`BeginPage` (`ColorMapping=1`) but it still produces CMY planes, so the
grayscale path needs its own investigation.

### Dither tables

BRCD format is identical; the 3040 uses the `cache08` set where the 4150 uses
`cache09` (`0600-{k,c,m,y}[-TS]_cache08.bin`, plus the `capt-` fine set, 16
files).  Copied into `src/lut/`.  Only the filename suffix differs — the
loader in `dither.py` needed no format change.

## Tools

* `compare.py` — feeds the same PPM to both filters, reports first divergence.
  Current: 4/12 identical.
* `src/find_luts.py` — locate colour grids by structure.
* `src/identify_grids.py` — score grids against oracle ink measurements.
* `src/extract_blobs.py` — copy BRCD tables + grids into `src/`.
* `src/pclxl.py`, `src/band.py`, `src/rle_decode.py` — oracle-side parser.

## Notes / traps

* Python here is 3.11, which lacks `collections.abc.Buffer` (3.12+).
  `src/_compat.py` is imported by `color_lut/pipeline/saturation/transforms`
  to shim it.  Without it nothing imports.
* Feed the filter the paper's real width (5100 for Letter), not the rounded
  image width — otherwise the right-hand padding bits differ.
* `docker exec … cat` works around a glibc stdio-pipe incompatibility in the
  2011 binary; `POST`-style stdin redirection alone is unreliable.
* The printer (`192.168.178.50:9100`) is reachable again; a real job printed
  byte-identical to the oracle.  `LogLevel warn` in `/etc/cups/cupsd.conf`
  keeps per-job detail out of `error_log`, so watch the socket with
  `tcpdump -i any -n host 192.168.178.50 and tcp port 9100` instead.
* numpy 1.24.2 is present in the system 3.11; the Cython accelerators build in
  `/root/brother/native/.venv312` (3.12) — run `install.sh`/`build_cython.sh`
  there.  Force the rebuild: `setuptools` skips a `.pyx` whose `.c` is newer
  and never notices a `.pxd` change, so a stale `.so` silently keeps running.
* **Test pages: reset the PostScript colour state before every `show`.** PS
  carries `setrgbcolor` forward, so a text block after `1 1 0 setrgbcolor`
  (the yellow swatch) prints yellow.  The oracle does the same with the same
  file — it is a bug in the test page, not in the port.  A yellow-on-white
  text line under a colour chart is this trap, not a colour bug.
