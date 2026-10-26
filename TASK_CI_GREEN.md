Make the GitHub Actions CI green again for the HL-3040CN native driver.

Repo: Csiebe84/Hl3040CN-arm64 (PRIVATE), branch `master`.
Project root: /root/brother/native
CI workflow: .github/workflows/tests.yml

## The problem (measured, not guessed)

CI is red on `master`. Last green run was 51ef4b0 (2026-10-25 15:59); every run
after it failed. The failing step is:

  "Colour-grid selection (BRGray on/off)"   -> test_gray_replace

and the steps after it are skipped, so at least these three are broken:

  test_gray_replace      FAILED
  test_dither_tables     FAILED
  test_toner_save        FAILED

## Root cause (verified — do not re-derive)

The tests need Brother's proprietary blobs, which are deliberately NOT in the
repo (.gitignore):

    hl3040cn/src/lut/          (16 BRCD dither tables)
    hl3040cn/src/color_data/   (rgb/cmyk colour grids, inverse_lut.npy)

Locally those directories exist, so all tests pass. On a fresh CI checkout
they are missing, and the tests then fail instead of skipping. Two distinct
symptoms:

* `test_dither_tables`: FileNotFoundError on
  `hl3040cn/src/lut/0600-k_cache08.bin`, and a silent Bayer fallback makes
  `test_never_falls_back_to_bayer` fail.
* `test_gray_replace`: `cmyk and rgb grids are identical` — without
  `color_data/` both grids fall back to the same built-in default, so the
  "cmyk differs from rgb" assertion cannot hold.

There is currently NO skip guard for missing blobs. The only existing guard is
`@unittest.skipUnless(pipeline.HAS_BAND_KERNEL, ...)` in test_gray_replace.py:150
— follow that style.

## What to do

1. Reproduce it locally in a clean tree first, so you can actually see the
   failure and then the fix:
     git -C /root/brother/native worktree add -f /mnt/ssd/finecmp/ci HEAD
     cd /mnt/ssd/finecmp/ci/hl3040cn/src
     python3 -m unittest test_dither_tables test_gray_replace test_toner_save
   (A fresh worktree has no lut/ or color_data/, exactly like CI.)
2. Add a skip guard so those tests SKIP (not fail) when the blobs are absent.
   A small shared helper is fine, e.g. `test_blobs.py` with
   `HAS_LUT` / `HAS_COLOR_DATA` and a `require_blobs` decorator, or a
   module-level `skipUnless` in each file. Keep it in the style of the
   existing `HAS_BAND_KERNEL` guard.
   IMPORTANT: do not silently weaken the tests. When the blobs ARE present
   (the normal case on this machine), every assertion must still run and pass.
   A skip must only happen when the data genuinely cannot be loaded.
3. Make sure the CI workflow does not report success for a run where
   everything was skipped without saying so. If the whole blob-dependent suite
   skips, that must be visible in the log — a short message per skip is enough.
4. Also check the two steps that CI never reached (test_toner_save,
   test_a4_geometry) — confirm they pass once the guard is in.
5. Verify in the clean worktree (all tests should now be OK-or-skipped, zero
   failures), and verify again in the REAL tree (all tests must still pass for
   real, no new skips).

## Rules

- Do NOT commit or push. Leave the change in the working tree; the user
  reviews and pushes.
- Do NOT add the Brother blobs to the repo. The .gitignore comment explains
  why (licence — they ship in Brother's LPR driver). That decision stands.
- Do NOT touch other conversations' files or the shared driver code
  (color_lut.py logic, pipeline.py) — this task is about the TEST harness
  only. Another agent is actively editing color_lut.py.
- Write any scratch files to /mnt/ssd, never /tmp (tmpfs, tight RAM).
- Do not restart the agent-server.
- Clean up the worktree when done: `git worktree remove /mnt/ssd/finecmp/ci`.

## Report

State: which files you changed, the before/after result in the clean worktree,
and the result in the real tree. If you cannot make CI green without
committing blobs, say so and propose the alternative.
