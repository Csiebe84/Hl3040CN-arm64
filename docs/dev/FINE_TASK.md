Fix the Fine mode (BRResolution=Fine) of the native HL-3040CN CUPS driver in
/root/brother/native so its output is byte-identical to Brother's filter, the
way Normal mode already is.

READ FIRST: /root/brother/native/FINE_HANDOVER.md — it has the exact state, the
verified measurements, the tools, and the constraints. Do not redo the work
listed there as already done.

What is already done (do not repeat):
- `tools/oracle_run.py` supports `--resolution Normal|Fine` and `--page`.
- `tools/fine_compare.py` (new) diffs Fine ramp output, oracle vs port.
- The Fine source-width bug is FIXED in `hl3040cn/src/xl2hb.py`
  (`get_image_dimensions_fine`: round up to 8, not 32, not raw). Verified
  against 7 paper sizes; all 49 unit tests pass. Leave that fix in place.
- The dither-table question is answered: no better Fine tables exist anywhere
  (all ours are bit-identical to the printer's; `cache08b` is Normal-only;
  the 4150's `cache09` is a different printer). Do not go looking again.

The actual task — make Fine byte-identical:
1. Run `python3 tools/fine_compare.py --matching Normal`. Today: 0/4, first
   diff @168, port emits ~3.5x too much on a full Letter ramp.
2. Find the block framing rule from the oracle. Verified facts: 21 ReadImage
   ops for a 600x400 image, StartLine stride 3, BlockHeight values
   {2, 48, 2021, 2249}, all four planes present. The port emits 7 blocks with
   BlockHeight 97/12/400 and misses plane 1.
3. Then chase per-scanline compression efficiency — the gap grows with image
   size (1.26x at 600x400, 3.5x at full Letter), so framing alone will not
   explain it. `hl3040cn/src/fine_encoder.py` is inherited from the HL-4150CDN
   driver and was never verified; treat it as suspect, not as truth.
4. Add a regression test for Fine so this cannot silently break again. There
   is currently no Fine test at all. Follow the style of
   `hl3040cn/src/test_dither_tables.py`; it must run without Brother binaries
   (the CI on ubuntu-latest has none) — compare against a checked-in expected
   fixture or a structural invariant, not against the oracle.

Rules:
- Use `band.decode_blocks` / `pclxl.parse` for any stream inspection. Never
  hand-parse the hex; a previous attempt desynchronised and produced a bogus
  finding (documented in the handover).
- Write all test fixtures to /mnt/ssd/finecmp. NEVER /tmp — it is tmpfs (RAM)
  and the machine has ~3.7 GB total; a 100 MB PPM in /tmp already caused
  ENOSPC once.
- Files in /tmp named t2_*.xl2hb, tt*.xl2hb, rpc_* and /tmp/rampdiag.out belong
  to another running conversation. Leave them alone.
- RAM is tight (~45 MB free). One oracle job at a time; prefer 200x100 images
  for header checks and 600x400 for block structure.
- Run one oracle job at a time and do not run anything in parallel that uses
  much memory.
- Do not commit or push. Leave changes in the working tree; the user reviews
  first.
- Verify with the oracle before claiming anything works. If you cannot make
  Fine byte-identical, report precisely how far you got and what the remaining
  difference is — an honest partial result is worth more than an optimistic
  claim.
- Update FINE_HANDOVER.md as you learn things, so the next reader is not misled.

Report at the end: what you changed, the fine_compare.py result, and what is
still open.
