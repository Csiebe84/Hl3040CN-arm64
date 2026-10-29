# AGENTS.md — /root/brother/native

Repository-specific knowledge for the Brother HL-3040CN driver port.

## Repo layout
- `hl3040cn/src/` — Python port (dither.py, color_lut.py, transforms.py, test_fine_mode.py).
- `ref/brhl3040cnfilter.bin` — i386 filter binary to reverse engineer.
- `tools/` — analysis harnesses. `.venv312/bin/python` is the interpreter.
- `logs/` — deliverable reports (e.g. logs/fine_levels.md).
- Oracle fixtures live on /mnt/ssd/finecmp (NVRAM-hostile /tmp must be avoided for data).

## Mopria / Android discovery state (2026-10-29)
- Report: `logs/mopria2.md`. Prior: `logs/mopria_analyse.md` (27./28.10.).
- The Odroid CUPS is the IPP/Mopria server; the printer .50 only speaks
  `application/vnd.brother-hbp` (RAW 9100). Server-side Mopria advert is stable:
  `_ipp`/`_ipps` + `_universal._sub._ipp`, one queue, URF + mopria-certified=1.3.
- CUPS routes IPP by the **body** `printer-uri`, not the HTTP path: `/ipp/print`
  as an HTTP path is 404, but an IPP request there with body printer-uri=queue is
  `successful-ok`. A `/ipp/print` alias is therefore unnecessary.
- Discovery relies only on UDP 5353 (allowed by `fw_rules.py`, LAN_TCP 631 too).
  UDP 3702 (WSD) is not allowed and no WSD traffic exists on this LAN.
- Regression "printer vanished from Mopria" (2026-10-29) = the **printer is off**.
  Router proof: FRITZ!Box TR-064 `GetGenericHostEntry` shows `.50` MAC
  `00:1B:A9:6D:33:D2` (Brother) with `NewActive=0`. `.50` is unreachable on all
  ports; the server-side advert is unchanged vs. the last good state.
- Correction to the old report: `.50` is a real Brother (MAC `00:1B:A9:...`), NOT
  `Mi-9T-Pro`. `dc:15:c8:df:84:42` is the FRITZ!Box itself (`.1`).
- HA (Supervisor) python3 also binds 0.0.0.0:5353; harmless, avahi answers fine.
- File queue `HL3040_TEST` -> `/tmp/e2e_out.prn` is the paper-free test path.

## Fine mode state (2026-10-28)
- Oracle `/mnt/ssd/finecmp/s128_fine.xl2hb` (gray 128, Letter, Fine) is byte-identical
  decode target. Defect = Fine colour separation / 4bpp dither input + plane-presence rule,
  NOT the encoder.
- Fine = ONE screen per plane + level function (Model A), NOT per-scanline screen swap.
  C period 20 / 15 rows, M period 10 / 10 rows, Y period 12 / 6 rows; all 6564 rows follow.
- Recovered per-row level histograms + periods + first-20 nibbles: see logs/fine_levels.md.
- Row width = 5104 px (2552 B nibble packed) = 5100 px dither body + 4 px pad.
- Level sets: C {0,15}/{0,14,15}, M {0,10,15}, Y {0,15}/{0,4,15}/{0,4,12,15}.
- Y id3/id5 stage-1 forward is non-injective; their unconstrained inverse is 3402 B
  (level histogram still valid). Others are clean 2552 B.
- Per-scanline phase steps: C +3 px/+2 sl (10er) & +6/+2 (20er), M +7 px/sl, Y +1 (+3/+3 6er).
- M effectively uses a 10-row screen, not the shipped capt-m 160x20.
- Binary anchors: stage-1 RLE 0x804f398, stage-2 encoder 0x804f7c8, mode table 0x8070b64,
  .text vaddr base 0x8048e48 (foff = va - 0x8048e48 + 0xe48).
- Handover docs: FINE_HANDOVER.md (has uncommitted stale §7d claim), TASK_FINE_LEVELS.md.

## Fine mode — 4/3 stretch resolved (2026-10-29)
- The last byte-identical gap is closed. `dither_channel_4bpp_pattern_arr`
  (`hl3040cn/src/dither.py`) now 4/3-stretches a screen row whose byte width
  `wb = width//8` is a multiple of 3 (Y and K: 96 px -> wb=12): a `0x00` is
  inserted before every packed byte whose HIGH nibble (even pixel's level) is
  intermediate (not 0/15). C/M (wb=20) are never stretched; rows whose
  intermediates sit only on odd pixels stay verbatim. Geometry-based, not
  channel-based (K follows the same rule).
- Proof: C/M/Y 6564/6564 for gray 128 and 192, all planes 6564/6564 for gray 64,
  K 6564/6564 for black; whole Job byte-identical after the `session()` marker.
  Details + reproduction: logs/fine_stretch.md. Regression: test_fine_mode.py
  `FineStretchTest`.
- Still open (out of scope, unchanged): MIXED colours (`s_128_128_130`,
  `s_200_50_100`, gradients) deviate in C/M/Y/K — a separation/level-choice
  issue, not this geometry.
