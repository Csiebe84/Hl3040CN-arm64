> **UEBERHOLT (2026-10-28).** Diese Datei beschreibt den Ansatz, der als
> **widerlegt** zurueckgerollt wurde (siehe `FINE_HANDOVER.md` §8 und
> `logs/verify_fine.md`, Verdikt b). **Nicht bearbeiten.**
> Massgeblich sind jetzt: `TASK_FINE_LEVELS.md` (Phase 1) und
> `TASK_FINE_REVERSE.md` (Phase 2).

Harden the verified Fine-mode findings with regression tests, and commit the
pending work. Do NOT hunt the Fine ink-level function — another conversation is
already doing that. Stay on the bounded tasks below.

Repo: /root/brother/native
Test runner: /root/brother/native/.venv312/bin/python -m unittest  (no pytest)
Run tests from /root/brother/native/hl3040cn/src.

## Context

`FINE_HANDOVER.md` has the state. Today's cheap tests (no qemu, oracle files
already in /mnt/ssd/finecmp) settled four questions. Pin them so they cannot
regress, because they are currently only verified by hand.

## Task 1 — pin the CAPT colour-table selection

Verified fact: Fine uses a DISTINCT separation grid, not the 600 dpi one.

    transforms.color_table(settings):
      resolution NORMAL -> rgb_default     capt=False
      resolution FINE   -> rgb_capt        capt=True
      color_matching VIVID + FINE -> srgb_capt
      color_matching NONE  + FINE -> cmyk_default   capt=False

    transforms.py:51   capt = settings.resolution == Resolution.FINE and profile != "cmyk"

The CAPT grid matters because it drops the black component on mid greys:

    color_lut.ColorTable(capt=True), ink = 255 - value:
      gray  64 -> K=74  C=111 M=80 Y=79
      gray 128 -> K= 0  C= 87 M=64 Y=64
      gray 192 -> K= 0  C= 44 M=32 Y=32

Write a unittest that asserts both the table NAME selected per
(resolution, color_matching) and the K ink value at gray 64/128/192 for the CAPT
table. Guard it with the same blob-presence helper the other tests use
(`test_blobs.require_blobs`) so CI without Brother's blobs still passes.

## Task 2 — pin the plane-presence rule

Verified fact: the plane set is DERIVED, not special-cased. `pipeline.py:553`
writes a plane only if it accumulated a non-empty line. So at gray 128 no K
plane is emitted (K ink is 0), and at gray 64 K IS emitted (K ink 74).

Measured with a full-page solid render (Letter, Fine), counting planes via
`band.decode_blocks(pclxl.parse(...))`:

    gray   0 -> {K}
    gray  64 -> {C, K, M, Y}
    gray 128 -> {C, M, Y}          <- no K
    gray 192 -> {C, M, Y}

Write a unittest asserting the plane SET per grey level. Keep the page short
(a few hundred rows) so it stays fast; the rule is per-plane presence, not size.

## Task 3 — record the ink-level state without chasing it

Add a short note to `FINE_HANDOVER.md` (a new subsection, do not rewrite the
file) recording these measurements so the ink-level work has them:

- The port's per-plane stage-2 bytes do NOT match the oracle. Full-page gray 128
  (raw entry bytes, all entries, via `decode_stage2`):
      C oracle 4212118 | port 3769706
      M oracle   66297 | port 3769703      (oracle has only 4 M blocks)
      Y oracle  537154 | port 1891526
- `dither.py` carries an uncommitted `_FINE_BINARY = True` that switches Fine to
  a 2-level screen. On the C plane, gray 128, one 5100-px row through
  `fine_encoder.compress_rle_preencode`:
      binary 0/15 -> 831 B (2f80278027802780)
      16 levels   -> 2550 B (51515a5a51515a5a)
      ORACLE      -> 1020 B (c812c812c812c812)
  The oracle is BETWEEN the two and is 2-byte periodic with mixed-nibble tokens.
  A brute force over all constant nibble patterns, period 1..4, found NO pattern
  producing `c812`. So the oracle's 4 bpp levels are not a level function of a
  single constant ink value. State this; do not try to solve it.
- A measurement trap worth recording: decoding only `entries[0]` of the first
  block understates a plane by ~7000x. Always sum over all entries.

## Task 4 — commit

Once tasks 1-3 pass, commit the pending, verified changes. `git status` currently
shows these modified (verify each is intended before staging):

    hl3040cn/src/transforms.py    CAPT selection  — verified, keep
    hl3040cn/src/color_lut.py     — check the diff, keep if it is the CAPT grid
    hl3040cn/src/settings.py      print-quality -> Resolution mapping — keep
    hl3040cn/src/dither.py        _FINE_BINARY — see below
    hl3040cn/src/test_consistency.py, test_toner_save.py
    hl3040cn/cups/brhl3040cn.ppd, hl3040cn/cups/install.sh

Do NOT commit `dither.py` at all. Leave `_FINE_BINARY` unstaged.

Reason: another conversation is actively editing the Fine dither path right now.
Committing `dither.py` would race with it and could capture a half-finished
state. `_FINE_BINARY` is in any case only a partial improvement (C drops from
2551 B to 831 B per row) and the oracle is 1020 B, so it is not the answer.

Concurrency guard for the whole task: if a test fails and the cause is a source
file you did not touch (i.e. another agent is mid-edit), do NOT modify that file.
Report the failure and stop. Do not "fix" files outside the list above.

There is a large number of untracked `tools/graytol_*.py` and `tools/grid_*.py`
exploration scripts. Do NOT commit those — leave them untracked.

## Report

Say which tests you added, the pass/fail counts, exactly which files you staged,
and the commit hash.
