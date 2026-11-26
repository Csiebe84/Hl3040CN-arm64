Independently verify or refute a claim another conversation just made about
Fine mode. Be adversarial: the author of the claim also EDITED A TEST to match
its own change, which is exactly the pattern that needs outside checking.

Repo: /root/brother/native   Python: /root/brother/native/.venv312/bin/python
Oracle files (already decoded, no emulator needed): /mnt/ssd/finecmp/

## What is being claimed

Conversation `2ca66b04` (now finished) changed `hl3040cn/src/dither.py`:

    _BRCD_PREFIX = {False: "0600", True: "0600"}   # was {False:"0600", True:"capt"}
    _FINE_BINARY = True                            # new; binary 0/15 quantiser

and rewrote `hl3040cn/src/test_fine_mode.py` to match. Its claim (in
`FINE_HANDOVER.md` section 7d):

  1. Fine uses the Normal `0600` screens, NOT the `capt` screens.
  2. Decoding the whole first block and driving `s1model.forward` reproduces
     the oracle's per-scanline stage-1 bytes for specific rows:
         oracle C e0 (gray128) = 0600-k row, period-10 screen [F,F,F,0,0,0,0,0,0,0]
         oracle M e0 (gray128) = 0600-k row, period-10 screen [0,0,0,0,0,0,0,A,F,F]
         oracle Y e0 (gray128) = 0600-y row, period-3  screen [F,0,0]
  3. The `capt-*` screens contain NO such row (claimed brute force).
  4. So Fine = 0600 screens + binary quantiser.

## Counter-evidence already measured (verify these too)

The same session measured the FULL page, gray 128, Letter, all entries summed
(NOT just entries[0]):

```
plane | oracle      | port 0600+binary | port capt+binary
  C   |  7 538 096  |    8 951 049     |   3 769 706
  M   |  8 374 352  |    8 375 664     |   3 769 703
  Y   |  9 305 564  |    7 269 250     |   3 727 258
```

So 0600+binary hits the M LENGTH to 0.016%, but:

```
M: 7 972 441 of 8 375 664 bytes differ (95.2%), first difference at offset 0
   oracle 103c803c...   port 2737c0af...
Y: first 1702 bytes are BYTE-IDENTICAL to the oracle (c047af47...), then diverge
C: 100% differ
```

A local screen match on a few scanlines does not explain a 95% byte divergence
on a full plane. That is the contradiction to resolve.

## Task

Decide, with evidence, which is true:

  (a) The claim is right: 0600 screens + binary quantiser is correct, and the
      remaining divergence is a separate, later defect (e.g. row phase / block
      layout), OR
  (b) The claim is wrong: the local match is a coincidence (a period-3 or
      period-10 pattern can match many screens on a short window), and `capt`
      was right after all.

Do not pick a side from the prose. Measure. Concretely:

1. Reproduce claim 2 yourself. Take the oracle's C, M and Y first block, decode
   the whole block, and check whether the quoted rows really come out of
   `s1model.forward` with the stated screen. Report the exact command and output.
2. Test claim 3 honestly: does `capt-k` / `capt-y` really contain no row that
   matches? If you find a match the author missed, say so with the numbers.
3. The decisive test: render the full gray-128 page with BOTH configurations and
   compare each plane byte-for-byte against the oracle, reporting the number of
   differing bytes and the first differing offset. A configuration that is
   correct should diverge far less than 95%.
4. Explain the Y result: why do the first 1702 bytes match exactly and then
   stop? That boundary is a clue (1702 is not obviously a block or row size —
   check).

## Constraints

- Do NOT edit `dither.py`, `test_fine_mode.py` or any source file. This is a
  read-only investigation. Another conversation owns those files.
- Do NOT edit tests to make a claim pass.
- Do NOT touch the emulator container; use the saved oracle files only.
- Measurement trap that already cost this repo time: decoding only `entries[0]`
  understates a plane by ~7000x. Always sum over all entries.
- If you cannot decide, say so and give the single next measurement that would.

## Report

Write `/root/brother/native/logs/verify_fine.md`:
- claim 1/2/3 each: confirmed or refuted, with the command and its output
- the full-page byte-diff table for both configurations
- your verdict: (a) or (b), and the confidence
- if (b): what should be reverted, precisely
- if (a): what the remaining defect is, narrowed

Also state plainly whether `test_fine_mode.py` was edited in a way that weakens
the check (e.g. an assertion flipped from assertNotEqual to assertEqual).
