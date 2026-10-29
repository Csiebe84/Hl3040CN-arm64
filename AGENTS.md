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

## Decoder + Ink-Level: was wirklich gilt (2026-10-25, aus /root/AGENTS.md)

Uebernommen aus der Odroid-Arbeitsnotiz, weil es **hier** hingehoert (die Notiz
dort ist inzwischen gekuerzt). Alles in `/root/brother/native/` gemessen, Oracle
`brother-cups`.

- **Der 10-bit-Decoder EXISTIERT und ist byte-genau.** `src/rle_decode.py` hat
  `decode_10bit` UND `decode_12bit`; nur `decode_20bit` fehlt. Beweis:
  `tools/test_decoders.py` -> `12-bit OK`, `10-bit OK`, `oracle M-Zeilen
  dekodiert: 120 ok, 0 fehlerhaft`. Round-Trip gegen echte Oracle-Eintraege:
  12-bit 5/5 identisch (Y/Gelb), 10-bit 5/5 identisch (M/Rot). Die frueheren
  Notizen "10-bit/20-bit nicht lesbar" sind **falsch**.
- **Der 20-bit-Decoder fehlt, wird aber NICHT gebraucht.** Die Pipeline
  *encodiert* 20-bit C korrekt ohne je zu dekodieren. Zum Abgleich genuegt die
  **Vorwaerts-Methode**: `encode_c_plane(dither(level))` Byte fuer Byte gegen den
  Oracle-Eintrag.
- **FALLE: `Dichte*255` ist NICHT der Ink-Level.** Die Dither-Abbildung ist
  nichtlinear (`dots = (255-ink) > threshold`, 80x80-Schwellen). Fuer Rot:
  M-Dichte 0.797, Y-Dichte 0.581 -> die frueheren "M~177/Y~127" waren nur
  `Dichte*255`. Bit-genau (24 Zeilen, Restfehler 0,22 %) ist Rot **Y-Level 65 =
  Ink 190** (deckt sich mit STATUS.md, nicht mit NOTES.md). Immer per Dither
  bit-genau suchen oder vorwaerts vergleichen.
- **Blockaufteilung ist KEIN eigener Bug:** Oracle M 450 Zeilen @60 B vs. native
  M 2159 Zeilen @12,5 B - **beide flushen bei ~27000 B**
  (`PLANE_BUF_INIT_FREE 32754 - FLUSH_THRESH 5768 = 26986`). Die Blockhoehe ist
  Folge der Datendichte, nicht des Trenners.
- **Pruefstand-Falle:** `compare.py` nutzt `PrintSettings()`-Defaults
  (`improve_gray=False`, `color_matching=NORMAL`) -> Tabelle `rgb_default`. Die
  Oracle-rc (`brhl3040cn/inf/brhl3040cnrc`) sagt aber **`BRGray=ON`** ->
  `rgb_ig_default`. Der Vergleich lief also gegen die **falsche** Tabelle -
  zuerst korrigieren, sonst ist jede Suche irrefuehrend.
- **Vorwaerts-Sweep Rot:** `srgb_default` 480.701 B vs. Oracle 475.191 B
  (**1,2 % daneben**), alle anderen um Faktor 2-9. 13 Tabellen sind extrahiert
  und benannt (im Binary 0x2a541 cmyk, 0x47340 cmyk_ig, 0x814b3 rgb, ...).
- **Bevorzugter Weg:** Vorwaerts-Bytvergleich der **ganzen Session** (der
  Encoder ist fuer K-Seiten byte-genau) statt Oracle-Dekodieren - das umgeht
  die 10/20-bit-Frage vollstaendig. `tools/table_search.py` macht das;
  `tools/find_red_cell.py` liest den Grid-Eckknoten direkt (Rot (255,0,0) ist
  exakt Knoten 16, keine Interpolation).

## Erster echter Fix: `_BRCD_CACHE = "cache08"` (2026-10-25)

Aus /root/AGENTS.md hierher gehoert (dort gekuerzt). `dither.py` suchte die
BRCD-Tabellen als `0600-k_cache09.bin` (HL-4150CDN-Satz), die **HL-3040CN
liefert aber `cache08`**. Jede Suche schlug fehl -> stiller Fallback auf eine
generierte 32x32-Bayer-Matrix (falsche Farben, aber kein Fehler). Korrektur:
`_BRCD_CACHE = "cache08"`.
- **Beleg:** rote Seite 8.520.560 B -> **162.634 B** (Oracle 475.612 B); M- und
  Y-Zeile je 643 B -> **6 B** (Oracle 6 B). Y-Ebene **bit-genau** gegen das
  Oracle bei Level 190 (`err=0` ueber 11520 Bit), Round-Trip identisch.
- 9 Regressionstests, inkl. einem, der den Bayer-Fallback erkennt (haelt den
  Fehler fern). Backup: `/root/brother/backup-lut-fix-20261024-224335/`.

## Normal-Modus war still tot: veraltetes `_band_fast`-Modul (2026-10-29)

**Symptom:** keines. Fine druckte (PPD-Standard ist `600x2400dpi`), die Queue
sah gesund aus. **Jeder Normal-Job** lieferte aber nur einen **375-Byte-PJL-
Stummel** - keine Seite, kein sichtbarer CUPS-Fehler.

**Ursache:** `pipeline._band_kernel_colour()` uebergibt `render_band()`
**14** Positionsargumente. Die **installierte** `_band_fast`-Erweiterung
(Python 3.11, 29.10. 00:09) stammte aus einem **verworfenen Experiment** mit
zweitem Per-Pixel-Graugitter: **18** Parameter (`gray_lut, gray_grid,
gray_weights, gray_black` extra). Die Quelle war spaeter zurueckgebaut
(`_band_fast.pyx` und `pipeline.py` beide 14, kein `gray_`), die `.so` aber nie
neu gebaut -> `TypeError: render_band() takes exactly 18 positional arguments
(14 given)`. Der Kernel laeuft **nur im Normal-Modus** (`is_fine` -> `None`),
deshalb blieb der Fehler in Fine unsichtbar.

| Artefakt | mtime | `render_band`-Argumente |
|---|---|---|
| `src/_band_fast.pyx` (Quelle) | 2026-10-26 18:44 | 14 |
| `pipeline.py` (Quelle) | 2026-10-28 23:31 | uebergibt 14 |
| installierte `.so` | **2026-10-29 00:09** | **18** |

**Fix:** alle vier Erweiterungen mit dem Interpreter des Filters neu bauen
(Python 3.11, Cython 3.3.0): `cd hl3040cn && /usr/local/lib/brhl3040cn/.venv/
bin/python3 setup_cython.py build_ext --inplace --force`. Danach
**byte-identisch** zum Python-Pfad (KernelParityTest + direkter Vergleich
50571/5212/32316 B gleich).

**Beleg:** Normal durch die echte CUPS-Kette **375 B -> 748684 B** (exit 0);
Fine unveraendert 1495842 B; Fine gegen Orakel weiter 65640/65640; Suite 82 OK.
Backups: `backup-install-20261029/so-stale/` (die alte 18-Arg-`.so`),
`so-vor-rebuild/` (die vier vor dem Neubau).

**Lehre:** Die gruene Suite fing das NICHT - `KernelParityTest` ist
`skipUnless`-Kernel und in CI werden die Erweiterungen gar nicht gebaut (und die
Brother-Blobs sind gitignored), also skip. **Ein kompiliertes Artefakt, das
neuer ist als seine Quelle, ist ein Warnsignal**; `install.sh` baut mit `--force`
genau deshalb, aber eine von Hand abgelegte `.so` umgeht das. Bei Eingriffen in
den installierten Baum `mtime` UND Aufrufsignatur vergleichen, nicht den Namen.
