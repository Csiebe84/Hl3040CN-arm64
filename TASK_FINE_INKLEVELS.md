> **UEBERHOLT (2026-10-28).** Diese Datei beschreibt den Ansatz, der als
> **widerlegt** zurueckgerollt wurde (siehe `FINE_HANDOVER.md` §8 und
> `logs/verify_fine.md`, Verdikt b). **Nicht bearbeiten.**
> Massgeblich sind jetzt: `TASK_FINE_LEVELS.md` (Phase 1) und
> `TASK_FINE_REVERSE.md` (Phase 2).

Find the Fine-mode ink-level function that reproduces Brother's filter output.

READ FIRST: /root/brother/native/FINE_HANDOVER.md (state + already-excluded work)
and FINE_TASK.md (block framing). Do not repeat what they list as done.

Repo: /root/brother/native. Tests: /root/brother/native/.venv312/bin/python -m unittest
Use `python3 -m unittest` (no pytest in the venv). Never use qemu for new work
except `tools/oracle_run.py` to produce a reference; the oracle files already
exist under /mnt/ssd/finecmp/.

## Verified state (measured today, do not re-derive)

The Fine colour table is CORRECT and already selected:
  `transforms.py:51`  capt = (resolution == FINE and profile != "cmyk")
  -> table `rgb_capt` for colour matching Normal, `srgb_capt` for Vivid.
  CAPT ink for greys (measured, `color_lut.ColorTable(capt=True)`):
    gray  64 -> K=74  C=111 M=80 Y=79
    gray 128 -> K= 0  C= 87 M=64 Y=64     <- K is 0, so the K plane is dropped
    gray 192 -> K= 0  C= 44 M=32 Y=32
  The plane-presence rule therefore FALLS OUT of the table, it is not a special
  case: `pipeline.py:553` writes a plane only if it accumulated a non-empty line.
  Both oracle and port omit K at gray 128. This is settled — do not chase it.

## The open defect

Full-page comparison, gray 128, Letter, Fine (`/mnt/ssd/finecmp/s128_fine.xl2hb`
vs a port render of the same solid page), decoded with
`band.decode_blocks` + `fine_decode.decode_stage2` over ALL entries:

```
plane | oracle stage2 bytes | port stage2 bytes | oracle blocks | port blocks
  C   |     4 212 118       |    3 769 706      |     157       |    140
  M   |        66 297       |    3 769 703      |       4       |    140
  Y   |       537 154       |    1 891 526      |      22       |     71
```

The oracle is strongly C-dominant and nearly M-free; the port spreads ink
evenly over C/M/Y. Per-block the port is in the right range (~26.9 KB), so the
defect is the per-plane ink distribution, not the block size.

WARNING — measurement trap: decode ALL entries of every block. An earlier
measurement in this repo decoded only `entries[0]` of the first block and
reported ~1020 B per plane, understating the true size by ~7000x. That mistake
produced a now-retracted claim that the oracle's C stream is a 1020-byte
2-byte-periodic pattern. Do not trust any plane size that is not summed over
all entries.

The dither quantiser is the suspect. `dither.py` currently has an uncommitted
flag `_FINE_BINARY = True` that switches Fine to a 2-level screen
(`np.where(ink > thresholds, 15, 0)`). Measured effect on the C plane, gray 128,
one 5100-px row, through `fine_encoder.compress_rle_preencode`:

```
binary 0/15   ->  831 B   first bytes 2f80278027802780
4 levels      -> 2550 B   first bytes 51516c6c51516c6c
8/16 levels   -> 2550 B   first bytes 51515a5a51515a5a
ORACLE        -> 1020 B   first bytes c812c812c812c812
```

The oracle sits BETWEEN binary and the 16-level ramp, and its stream is
2-byte periodic with mixed-nibble tokens (`0xC8`,`0x12` are stage-1 mixed-byte
codes, not 0/15 nibbles). A brute force over all constant nibble patterns with
period 1..4 found NO pattern that produces `c812` through
`compress_rle_preencode` — so the oracle's 4 bpp levels are not a simple level
function of a single constant ink value.

## Your task

Find the ink-level function (quantiser + screen) that turns the CAPT ink value
into the 4 bpp nibble stream the oracle produces, so that a solid page is
byte-identical per plane.

Suggested first steps, cheapest first:
1. Decode the oracle's stage-1 stream for one row (`fine_decode.decode_stage2`)
   and invert stage 1 by hand for that row to recover the NIBBLE sequence the
   filter fed in. `fine_decode.py` deliberately has no stage-1 inverse, but a
   single known row can be done manually.
2. Compare that recovered nibble sequence against the CAPT ink value (C=87 at
   gray 128) and against the `capt-c_cache08.bin` threshold matrix row.
3. Test candidate functions directly against the recovered sequence before
   wiring anything into `pipeline.py`.

Constraints:
- Do not change the CAPT table selection; it is verified.
- Do not change `fine_encoder.py`; the handover shows both stages reproduce the
  oracle byte for byte when fed the oracle's stage-1.
- Keep the change behind the existing `fine` flag so Normal is untouched.
- Add a regression test under `hl3040cn/src/` (unittest) that pins the recovered
  nibble sequence for at least gray 64 and gray 128.
- Report: the recovered nibble sequence, the function you found, and the
  per-plane byte counts before/after against the oracle file.
