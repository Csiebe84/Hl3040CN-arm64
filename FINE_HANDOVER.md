# Fine mode (BRResolution=Fine) — Handover

Task: make the port's Fine output **byte-identical** to Brother's filter, the
same way Normal already is.

Status: **not finished.** The Fine source-width bug is fixed and verified, and
there is now a Fine regression test (`hl3040cn/src/test_fine_mode.py`). The
main defect is localised: it is **not** the encoder (that is byte-identical to
the filter), it is the **Fine-mode colour separation / 4 bpp dither input**,
plus a plane-presence rule. Byte identity has not been reached
(`fine_compare.py` is 0/4).

---

## 1. What Fine is

`BRResolution` has exactly two values the filter understands: `Normal` and
`Fine`. `Fine` is not a different raster — the HL-30xxC family only ships
**600 dpi** colour tables (`HL-30xxC 600dpi ImpGray=…`). Fine changes two
things:

* the **dither tables** — `capt-*` instead of `0600-*` (finer screens,
  2400 dpi class), and
* the **encoder** — `encode_fine_plane` (two-stage RLE + pattern), 4 bpp,
  `bit_depth = 12`.

The port implements all of this (`fine_encoder.py`, `dither.py`
`_BRCD_PREFIX = {False: "0600", True: "capt"}`, `Resolution.FINE`), but it was
**never verified against the oracle**:

* `tools/oracle_run.py` had `BRResolution=Normal` **hardcoded** (now fixed),
* `hl3040cn/src/fine_encoder.py` is **byte-identical** to the HL-4150CDN
  reference driver, i.e. inherited unverified.

## 2. Fixed and verified — Fine source width

`get_image_dimensions_fine()` returned the **raw** paper width. The filter
rounds up, but to a different boundary than Normal.

Measured against the oracle, 7 paper sizes:

| page | raw | Fine (oracle) | Normal (oracle) |
|---|---|---|---|
| Letter | 5100 | **5104** | 5120 |
| A4 | 4958 | **4960** | 4960 |
| A5 | 3500 | **3504** | 3520 |
| Executive | 4350 | **4352** | 4352 |
| EnvDL | 2600 | 2600 | 2624 |
| Br3x5 | 1800 | 1800 | 1824 |
| EnvPRC5Rotated | 5200 | 5200 | 5216 |

* **Fine rounds to 8** (4 bpp: 8 px = one byte), **Normal to 32**.
* 7/7 each. An earlier guess of 16 was **wrong** — EnvDL and Br3x5 disprove it.

Fix in `hl3040cn/src/xl2hb.py`:

```python
def get_image_dimensions_fine(page_size: str) -> tuple[int, int]:
    pw, _ = PAPER_SIZES[page_size]
    return (pw + 7) & ~7, image_height(page_size)   # was: return pw, ...
```

After the fix the header matches for all 8 tested page sizes. All 49 unit
tests still pass, plus the new `hl3040cn/src/test_fine_mode.py` (15 tests,
added this round) — 64 total.

## 3. Open defect — the port emits ~3.5x too much (input, not encoder)

`tools/fine_compare.py` (new) compares a 60-bar ramp page, oracle
`BRResolution=Fine` vs port `Resolution.FINE`:

```
Normal Fine r    DIFF @168  oracle=7379159  port=25857891
Normal Fine g    DIFF @84   oracle=4448708  port=26505197
Normal Fine b    DIFF @168  oracle=6153695  port=16679345
Normal Fine gray DIFF @168  oracle=8608471  port=25602589
```

(Re-measured after the width fix. The `g` ramp now first differs at 84, not
168; the exact offset moves with the input, so do not over-read it.)

### 3a. The encoder is NOT the main defect (overturns the previous theory)

The filter binary is **i386** (stripped, `e_machine=3`). Disassemble with
capstone (`objdump` here has no i386 target):

* **Stage 1** lives at `0x804f398` (identifiable by its `mov byte [ebx],0x17` /
  `mov byte [ebx],0x1f` run-flush stores and the `or eax,0x10`/`or eax,0x18`
  run-head codes).
* **Stage 2** lives at `0x804f7c8`, with a 6-entry jump table at `0x8070b64`
  (modes 0..5) — the same six pattern modes the port's
  `compress_pattern_encode` implements.

A faithful transcription of the filter's stage 1 is *the same algorithm* as
`fine_encoder.compress_rle_preencode` — same white/black run counters, same
opcode layout, same branch structure. Run over **real** port dither output
(2496 scanlines across K/C/M/Y and every ink level) the two agree on
**2466/2496 (98.8%)**; the 30 differences are all one branch (a `0xA8` vs `0xB0`
style run-merge case). Which side is right there is not yet settled — the
transcription itself is not bug-free — but the point stands: the encoder is
structurally correct and cannot by itself produce a 3.5x gap.

What the port's `compress_rle_preencode(bytes([0x4F])*40) -> 40 bytes` really
shows is a *symptom*: stage 1 only collapses runs of `0x00`/`0xFF`, and the
port's **dither never hands it any**. The blow-up is upstream.

### 3a-bis. The real defect is the Fine dither / separation input

**Use full-height pages for any plane probe.** The filter *scales* a short PPM
to the whole page (a 2-row or 16-row PPM comes back as `SourceHeight=6558`),
so short probes give garbage block tables and bogus plane data. All numbers
below are from full-height (5100x6564) solid pages.

Compare a solid mid-grey page (RGB 128,128,128) at full height:

```
                 oracle planes            port planes
blackfull        K only (CMY absent)      K only (matches!)
whitefull        none (empty page)       none
grayfull         C, M, Y  (K absent)     K, C, M, Y   (K wrongly present)
```

For `grayfull`, the oracle's per-plane stage-1 (via `decode_stage2`):

```
plane1 (C): 0xC8,0x12 repeated, len 1020
plane2 (M): 0x10,0x3C,0x80 repeated, len 1022
plane3 (Y): 0xC0,0x47,0xAF repeated, len 1701
```

The port's for the same page:

```
plane0 (K): 0x1F*318 + 0x1D + 0x11, len 319      (stage-1 0x1F = black run)
plane1 (C): 0x11,0x17... len 2551
plane2 (M): len 2551
plane3 (Y): len 2551
```

The port's 4bpp dither of gray128 produces constant-level bytes
(`K 0x00/0x11`, `C 0x44/0x55`, `M 0x33/0x44`, `Y 0x33/0x44`) that stage 1
cannot run-compress, hence 2551-byte streams. The filter's streams are 2-3x
shorter and are *periodic*, i.e. its dither produces a repeating ink pattern.

I could not reproduce the oracle's C/M/Y stage-1 streams by feeding
`compress_rle_preencode` any constant or 2-byte-periodic nibble input (brute
forced 0..255 and all 2-byte pairs), which means the oracle's 4bpp levels are
**not** any simple level function of a single ink value — they come from the
filter's own Fine dither/quantiser.

**Decisive check that the encoder is not at fault.** Feed the oracle's own
stage-1 bytes back through the port's stage 2:

```
plane1: decode_stage2(oracle entry) -> compress_pattern_encode(...) == oracle entry  OK
plane2: ... OK
plane3: ... OK
```

The port's stage-2 reproduces the oracle's entries **byte for byte** when given
the oracle's stage-1. Combined with the stage-1 agreement above, both encoder
stages are correct; the entire gap is the input.

**The Fine colour input differs from Normal.** For gray128 the oracle emits:

* **Normal**: K-dominant (`{K:3282, Y:2188, C:15, M:4}` blocks) — and the port
  matches exactly.
* **Fine**: C,M,Y only, no K (`{C:157, Y:22, M:4}` blocks) — the port emits
  K-dominant instead.

So the filter's Fine colour path produces a different result than its Normal
one, and the port reuses the Normal path. The ink levels confirm it: for
gray128 the oracle's Fine C is a sparse isolated-dot pattern (`0xC8,0x12` ≈ 2
levels) while the port's is a uniform mid-level (`0x44/0x55` ≈ 4.5 levels).

(Plane ids are standard — red → M,Y; green → C,Y; black → K — so the mapping is
not in question. The question is *what* ink each plane gets in Fine.)

So the fix is **not** in `fine_encoder.py`. It is in the Fine colour input.
Two candidates, and the current evidence does not yet separate them:

1. **A Fine-specific colour separation grid.** The binary carries a
   `Fine(2400 dpi class)` colour set, and `extract_blobs.py` extracts several
   `*_ig_*` / density / glossy grids by position — one of those, or an
   unextracted grid, may be the Fine separation. Normal's grids are already
   byte-identical (which is why Normal works).
2. **Fine-specific dither thresholds**, which could alone empty the K plane
   (thresholds above the K ink level) and change the dot pattern. The `capt-*`
   BRCD tables are loaded, but the *quantiser* in
   `dither.dither_channel_4bpp_arr`
   (`base=(ink*15)//255`, `frac=(ink*15)%255`,
   `levels=min(15, base+(frac>thresholds))`) has never been verified against
   the binary.

Distinguishing these is the next concrete step. A first measurement (full-height
16-band grey ramp, `graybands.ppm`) shows the oracle's Fine plane presence
varies *irregularly* with grey — e.g. v=51 has no Y plane, v=68 no M, v=136 no
K and no Y — and the per-plane stage-1 lengths cluster around 851 / 1020 / 1021
/ 1531 / 1700. That irregular presence is what an ordered-dither threshold
producing 0-2 dot levels per plane looks like, and it is *not* what a plain
"separation + fixed level" would give. So the evidence leans toward the
**dither thresholds / quantiser** (candidate 2) rather than the separation
grid, but this is not yet proven — confirm by comparing the oracle's Fine ink
level for one grey against the Normal separation for that grey.

Do **not** "fix" `compress_rle_preencode` to run-length-encode mixed bytes: the
filter does not, and matching the filter is the goal. (The `0xA8` vs `0xB0`
branch difference is real and worth fixing eventually, but it is a ~1% effect.)

### 3a-ter. Plane presence is part of the framing

The filter emits a `ReadImage` block **only for planes that carry ink**:
`blackfull` → K only; `grayfull` → C,M,Y only (no K); `whitefull` → nothing.
The port always emits all four planes for every row. This changes the block
table and the byte count and must be reproduced.

### 3b. Block framing (the old 600x400 numbers were contaminated)

The previous block table here came from a **600x400 PPM**, which the filter
**scales up** to the full page (BeginImage becomes `SourceWidth=5104
SourceHeight=6558` for Letter). A 600x400 *solid* page therefore comes out as
constant full-ink plane-0 blocks (`03ff391f1d11` per line), and the old
`StartLine stride 3` / `BlockHeight {2,48,2021,2249}` table is a scaling
artefact, not the per-scanline rule. Use full-width (5100/5104) inputs.

On the full-width `r` ramp, verified with `pclxl.parse` / `band.decode_blocks`:

* Blocks flush at ~**27000-27400 bytes** of payload in both oracle and port
  (same `PLANE_BUF_INIT_FREE` region), so the block *sizes* already agree. The
  difference is entirely the entry *content* (3a / 3a-bis), not the framing.
* The oracle emits the four planes per flush in the order C, M, Y, K, same as
  the port.

So framing is **not** the thing to chase; the colour **input** is (3a-bis).
Both encoder stages are already correct.

(Do not read the plane block table from a short ramp either: a 16-row PPM is
**scaled to the full page height**, so `start_line`/`block_height` there are
output-page rows, not the input rows. This is the same trap as the 600x400
case. Use a full-height input if you need the real framing rule.)

### 3c. What is still open

* **Fine dither / separation input** (3a-bis) — the main lever. Establish what
  separation the filter uses for Fine mode (a `Fine(2400 dpi class)` grid, per
  the binary's strings) and how it maps ink to the 4 bpp level.
* The stage-1 `0xA8` vs `0xB0` branch (`lo==0` white-run merge) — a ~1% effect.
* Byte identity has **not** been reached: `fine_compare.py` is still 0/4.

### 3d. The current first difference is content, not the 0xA8/0xB0 branch

Stable measurement (oracle is deterministic on the XL2HB payload — the only
run-to-run variation is the PJL timestamp near the top of the file; the session
bytes are identical across repeated runs):

```
r    ramp: first diff @168  oracle=7379159  port=25857891  3.50x
gray ramp: first diff @168  oracle=8608471  port=25602589  2.97x
```

At the first difference the bytes are (session-relative):

```
oracle: c1 00 00 f8 6d c1 36 00 f8 63 c0 01 f8 65 c1 02 00 f8 81 b1 fa f5 69 00
port  : c1 00 00 f8 6d c1 12 00 f8 63 c0 01 f8 65 c1 02 00 f8 81 b1 fa 85 69 00
```

i.e. `0x00` vs `0x01`, `0x36` vs `0x12`, `0x00` vs `0x01` — these are *block
payload* bytes, i.e. a **different encoded entry**, not the stage-1 run-merge
branch. 99.9% of the common prefix differs and the port is 3.0-3.5x larger with
roughly 3.4x as many blocks (938 vs 274). This is exactly what a different
dither/quantiser input predicts, and it confirms the 0xA8/0xB0 branch is *not*
the current problem. Block counts per plane also differ (oracle `r`:
`{M:122, Y:85, K:56, C:11}`), again pointing at the colour input.

## 4. Answer to "can we steal better Fine dither tables?"

**No.** Verified, don't redo:

* All 16 tables in `hl3040cn/src/lut/` are **bit-identical** to the original
  printer's `inf/lut/` (`cmp` = 0 on every file).
* The printer ships a **second set** `0600-*_cache08b.bin` (8 files, Normal
  only, already present in `hl3040cn/lut/`). There is **no `capt_*_cache08b`**
  — no Fine variant exists.
* The HL-4150CDN uses `cache09` (`capt-*_cache09.bin`). It is a **different
  printer**; k/c/m/y all differ. Not interchangeable.
* No other BRCD table set exists anywhere on this machine outside backups.

Fine is already using the only Fine tables Brother ships for this model. Any
quality gain must come from the **encoder/block layer**, not the tables.

Measured table geometry (BRCD header: magic, flag, w, h):

| set | K | C | M | Y |
|---|---|---|---|---|
| `capt_*_cache08` (Fine) | 96x12 | 160x20 | 160x20 | 96x12 |
| `0600_*_cache08` (Normal) | 80x80 | 80x80 | 80x80 | 24x24 |
| `0600_*_cache08b` (Normal alt) | 24x24 | 40x40 | 40x40 | 24x24 |

`cache08b` is referenced by the filter but nothing in the port uses it — worth
a look as a *Normal*-mode quality option, but it is **not** a Fine table.

Two wrong claims found in the current code, both worth fixing while here:

* `dither.py:167` says cache08/cache09 differ in k/c/m but "y happens to be
  identical" — **false**: the y tables are 36874 vs 18442 bytes.
* `get_image_dimensions_fine`'s docstring said "Fine A4 = (4760, 6808)" — that
  was never a measurement, and 4760 is not even in `PAPER_SIZES`.

## 5. Tools

| tool | purpose |
|---|---|
| `tools/oracle_run.py` | run the filter; now supports `--resolution`, `--page` |
| `tools/fine_compare.py` | **new** — Fine ramp page, oracle vs port, byte diff |
| `tools/fine_decode.py` | **new** — `decode_stage2`, inverse of `compress_pattern_encode` |
| `tools/block_dump.py` | block table (plane, start, height, bytes) for one stream |
| `tools/ramp_pipeline_compare.py` | Normal-mode ramp comparison (unchanged) |
| `hl3040cn/src/test_fine_mode.py` | **new** — Fine regression tests, no oracle needed |

`fine_compare.py` writes its PPMs to `/mnt/ssd/finecmp`; it is safe to leave
them there. For ad-hoc inspection, `/mnt/ssd/finecmp/finedecode.py` holds
`decode_stage2` (the verified inverse of `compress_pattern_encode`).

Oracle container: `brother-cups` (image `brother-hl3040cn:local`).
All fixtures: write to **`/mnt/ssd/finecmp`**, never `/tmp` — `/tmp` is tmpfs
(RAM) and only ~3.7 GB total; a 100 MB PPM in `/tmp` has already caused ENOSPC.

**Inputs must be full-width AND full-height.** The filter scales any input whose
width/height is not the paper's source size up to the full page, so a small
probe (600x400, or a 2-row / 16-row strip) comes out as scaled content and its
block table is meaningless. Use 5100x6564 (the Letter source size) for any
plane/block probe. Solid pages are fine and cheap (one 100 MB PPM on
`/mnt/ssd/finecmp`, ~5 MB oracle output).

### Disassembly recipe (for the encoder / dither / separation)

The filter `ref/brhl3040cnfilter.bin` is **i386** ELF, stripped. This host's
`objdump` has no i386 target, so use capstone:

```python
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
# .text is section 12: vaddr 0x8048e48 -> file offset 0xe48
def foff(va): return va - 0x8048e48 + 0xe48
```

Landmarks already found:

| addr | what |
|---|---|
| `0x804f398` | stage-1 RLE compressor (look for `mov byte [ebx],0x17` / `0x1f`) |
| `0x804f7c8` | stage-2 pattern encoder |
| `0x8070b64` | stage-2 6-entry mode jump table (modes 0..5) |

The strings `Fine(2400 dpi class)` and `Fine` in the binary are the lead for
the Fine-specific colour path.

## 6. Constraints

* Do not touch `hl3040cn/src/xl2hb.py` beyond the width fix without checking
  `git diff` — the file is otherwise clean.
* Another conversation is editing this same working tree (it owns the
  `color_lut.py` / `_band_fast.pyx` changes for BRGray=OFF near-grey). Do not
  revert or reformat those; keep your edits to `xl2hb.py`, `dither.py`,
  `test_fine_mode.py`, the workflow and this file.
* `/tmp` files named `t2_*.xl2hb`, `tt*.xl2hb`, `rpc_*` and `/tmp/rampdiag.out`
  belong to another running conversation. Leave them alone.
* RAM is tight (≈45 MB free). Run one oracle job at a time. For header checks
  a 200x100 probe is fine, but for anything about block structure or encoder
  output the probe **must be full-width** (5100 px) — see section 5.
