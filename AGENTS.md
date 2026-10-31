# AGENTS.md — /root/brother/native

Repository-specific knowledge for the Brother HL-3040CN driver port.

## Repo layout
- `hl3040cn/src/` — Python port (dither.py, color_lut.py, transforms.py, test_fine_mode.py).
- `ref/brhl3040cnfilter.bin` — i386 filter binary to reverse engineer.
- `tools/` — analysis harnesses. `.venv312/bin/python` is the interpreter.
- `logs/` — deliverable reports (e.g. logs/fine_levels.md).
  - Oracle fixtures live on /mnt/ssd/finecmp (NVRAM-hostile /tmp must be avoided for data).

## Status (2026-10-30, Ende dieser Sitzung)
- **Emulatorfrei bewiesen:** kein `qemu`/`i386`/`binfmt` irgendwo im CUPS-Pfad
  (`/etc/cups`, `/usr/lib/cups/filter`, `/usr/local/lib/brhl3040cn`). Der Filter
  laeuft unter `/usr/bin/python3.11` auf `aarch64` – native, kein Emulator.
- **Installation == Repo:** alle 29 Module unter `/usr/local/lib/brhl3040cn/`
  sind byte-identisch zu `hl3040cn/src/` (`cmp` je Datei).
- **Tests: 89 gruen** (`unittest discover -s hl3040cn/src`), davon 3 neue in
  `Stage2LosslessTest`.
- **Ende-zu-Ende ohne Hardware:** PostScript -> Filter -> 583104 B XL2HB,
  24 Bloecke, `comp_size 0` (Fine), alle Checksummen ok, exit 0.
- **Echter CUPS-Job 123** (`lp -d Brother_HL-3040CN`): Filter und socket-Backend
  je `exited with no errors`; kein Papier -> nichts gedruckt.
- **Veroeffentlicht:** privat `Csiebe84/Hl3040CN-arm64`, Branch `master`, HEAD
  `80e2c0d`, 0 unpushed, CI gruen. Push nur ueber `./gitpush.sh` (`~/.gh_token`,
  Konto `Csiebe84`) – `$GITHUB_TOKEN` gehoert `christiansiebe` und darf nicht.
- **Offen:** Sichtpruefung auf Papier (blockiert: `Kein Papier`, CODE=41202).
  Sobald Papier eingelegt ist, laeuft `tools/hw_verify.py` den Beweis
  (PAGECOUNT vor/nach).

  ## Verbrauchsmaterial-Anzeige: zwei Fehler in CUPS, nicht im Treiber (2026-10-31)

  Ausgangsfrage war, warum die Toner-Balken leer stehen und Magenta/Gelb
  vertauscht sind. **Beides kommt von CUPS, nicht vom Drucker und nicht vom
  Filter.**

  ### Fund 1: alle vier Toner lesen `-1`

  Der Drucker laesst `prtMarkerSuppliesMaxCapacity` (1.3.6.1.2.1.43.11.1.1.8) bei
  **allen vier** Tonerkartuschen auf **-2** ("none"). CUPS rechnet den Prozentwert
  nur, wenn es eine Kapazitaet hat - ohne sie publiziert es `-1` ("unbekannt"),
  und die
  Balken bleiben leer. Die echten Staende stehen in Brothers privater MIB
  (`1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.8.0`), die CUPS nie liest.

  Die Trommeln und die Belt-Unit haben dagegen eine Kapazitaet und werden korrekt
  angezeigt - nur die Toner nicht. Genau das war der Hinweis: es liegt nicht am
  SNMP-Zugriff (der funktioniert), sondern an der fehlenden Kapazitaet.

  ### Fund 2: Magenta und Gelb sind vertauscht

  CUPS nimmt die Farbe jedes Markers aus `prtMarkerColorantValue`, indiziert ueber
  den **Colorant-Index** des Supplies. Dieser Drucker nummeriert seine Colorants
  `1=black, 2=cyan, 3=yellow, 4=magenta`, benennt seine Supplies aber
  `..., Magenta Toner Cartridge, Yellow Toner Cartridge`. Supply 3 bekommt also
  Colorant 3, den der Drucker "yellow" nennt - die Magenta-Saeule wird gelb
  gezeichnet und umgekehrt. Die Namen stimmen, die Farben nicht: ein Widerspruch
  in den Geraetedaten selbst.

  ### Fund 3: der Tabellenindex ist zweistufig (fiel erst am echten Geraet auf)

  Das war der Fehler, den der Simulator verdeckt hat. `prtMarkerSuppliesTable`
  ist nach RFC 3805 ueber `hrDeviceIndex.prtMarkerSuppliesIndex` indiziert: ein
  **echter** HL-3040CN antwortet auf einen Walk der Spalte `.6` mit `.6.1.1`
  bis `.6.1.10`, nicht mit `.6.1` bis `.6.10`. Der Simulator antwortete
  einstufig, und der alte Code nahm per `oid.rsplit(".", 1)[1]` nur die
  **letzte** Zahl.

  Folge am echten Geraet: jeder Typ-Lookup und jeder Kapazitaets-Lookup ging ins
  Leere. Alle zehn Supplies kamen als `unknown` zurueck, und Belt plus die vier
  Trommeln lasen `-1`, obwohl der Drucker echte Werte lieferte (Belt
  20488/50000, Trommeln je 4083/15000). Der Tausch-Fix aus Fund 2 hat davon
  nichts gemerkt - der rechnet nur mit dem Namen.

  `_by_index()` behaelt jetzt den **ganzen** Index als Tupel. Beide
  Schreibweisen landen in derselben Struktur, ohne dass eine fuer die andere
  gehalten wird. `RealIndexLayoutTest` haelt die echten Druckerwerte fest und
  `FlatIndexLayoutTest` sichert die einstufige Form ab, damit der Fix nicht das
  eine gegen das andere tauscht. Gegen den alten Code schlaegt der Test fehl mit
  `'unknown' != 'toner'` und `-1 != 40` - genau die Symptome vom Geraet.

  **Lehre:** ein Simulator, den man selbst geschrieben hat, bestaetigt nur die
  eigene Annahme. Der Index-Fehler war die ganze Zeit da und blieb unsichtbar,
  bis der Drucker wirklich antwortete.

  ### Der Fix: der Filter meldet die Werte selbst

  `marker.py` liest Namen/Typen/Level aus der Standard-MIB und die Toner-Prozente
  aus der Brother-MIB, und schreibt vier `ATTR:`-Zeilen auf stderr. CUPS liest sie:

  * `scheduler/statbuf.c` erkennt das `ATTR:`-Praefix,
  * `scheduler/job.c` (`CUPSD_LOG_ATTR`) legt jeden Wert per
    `cupsdSetPrinterAttr` am Drucker ab.

  Kein zusaetzlicher Daemon, kein Schreiben in den CUPS-Zustand. **Wichtig:** der
  Filter bekommt den Druckerhost aus `DEVICE_URI` - CUPS reicht die Variable an
  jeden Filter durch (`cupsdStartProcess(..., job->status_pipes[1], ...)`, siehe
  `job.c`), nicht nur ans Backend. Ohne das muesste man den Host raten.

  Die Farbe wird aus dem **Namen** abgeleitet, nicht aus der Colorant-Tabelle -
  so kann sie nicht mehr auseinanderlaufen.

  ### `*cupsSNMPSupplies: false` ist Teil des Fixes

  Ohne das Keyword liest das `socket`-Backend dieselbe MIB und **ueberschreibt**
  die korrigierten Werte mit seinen eigenen. Die Wache sitzt in
  `backend_init_supplies` (`snmp-supplies.c`): nur wenn das PPD-Attribut fehlt
  ODER `true` ist, wird ueberhaupt SNMP gefragt.

  ### Werkzeuge

  * `src/snmp.py` - SNMP-v1-Client (GET + GETNEXT-Walk) nur mit stdlib; dieses
    Board hat kein `pysnmp`. Zeitbudget (`deadline`), damit ein toter Drucker den
    Job nicht aufhaelt.
  * `src/brsupply.py` - Decoder der Brother-Hexwoerter. Gegen die mitgelieferten
    Geraetedaten der Apache-2.0-Bibliothek `brother` (bieniu/brother) geprueft:
    **0 Abweichungen** bei 9 Prozenten und 4 Zaehlern.
  * `src/marker.py` - der Emitter. `python3 marker.py <host>` zeigt, was der
    Drucker meldet.

  **Ein nicht antwortender Drucker ist kein Fehler:** die Meldung wird
  uebersprungen, der Job laeuft normal weiter.

  ### Nachgewiesen (nicht nur getestet)

  * `test_supplies.py`: **68 Tests**, davon 6 fuer die Filter-Verdrahtung ueber
    `DEVICE_URI`. Gesamtlauf `unittest discover -s hl3040cn/src`: **173 gruen**.
  * **Ende-zu-Ende mit dem INSTALLIERTEN Filter als Benutzer `lp`**, echtem venv
    und einem SNMP-Agent auf `127.0.0.1:161`: exit 0, 60014 B XL2HB und die vier
    `ATTR:`-Zeilen mit `#FF00FF` an Position 3 (Magenta) und `#FFFF00` an
    Position 4 (Gelb) - der Tausch ist weg.
  * **Achtung beim Testen:** `sudo -u lp` verwirft die Umgebung. `DEVICE_URI` und
    `PPD` muessen per `sudo -u lp env VAR=...` mitgegeben werden, sonst meldet der
    Filter "no network printer in DEVICE_URI=''" und der Test beweist nichts.
  * **Am echten Drucker nachgewiesen** (2026-10-31, 192.168.178.50). Ein echter
    CUPS-Job (Nr. 126) lief durch, der Filter `exited with no errors`, und CUPS
    meldet danach per `ipptool get-printer-attributes`:

    ```
    marker-levels  = 83,64,48,43,-1,40,27,27,27,27
    marker-colors  = #000000,#00FFFF,#FF00FF,#FFFF00,none,none,#000000,...
    marker-types   = toner,toner,toner,toner,waste-toner,other,opc,opc,opc,opc
    ```

    Vorher stand dort `-1,-1,-1,-1,-1,40,27,27,27,27` mit vertauschten Farben
    (`#FFFF00` an Position 3). `marker-change-time` wandert mit, CUPS hat die
    Werte also wirklich uebernommen und nicht nur zwischengespeichert.
  * Die laufenden CUPS-Binaries wurden gegengeprueft, nicht nur die Quelle:
    `strings /usr/sbin/cupsd` kennt `ATTR:`, `marker-names` und `marker-levels`;
    `strings /usr/lib/cups/backend/socket` kennt `cupsSNMPSupplies` und
    `prtMarkerSuppliesMaxCapacity`. Installierte Version: 2.4.2-3+deb12u9.

## Performance-Profil: Fine-Modus ist der Hebel (2026-10-30)
Gemessen an `drucktest2.ps` (eine Letter-Seite, 4958x6981) auf dem Odroid N2+.

- **Ghostscript ist NICHT das Problem: 0,23 s.** Die uebrigen **~10-13 s** stecken
  vollstaendig in der Python-Pipeline. Wer Zeit sparen will, muss dort ansetzen.
- **Zeitverteilung (`cProfile`, Fine):** `compress_rle_preencode` (Stage 1) 6,4 s
  und `compress_pattern_encode` (Stage 2) 5,6 s – praktisch **1:1**, kein
  einseitiger Suendenbock. Dazu 8,5 Mio `bytearray.append` = 4,1 s.
  Auf einer grossen Flaeche (5100x6564) sind es **57 Mio `append` = 28 s**.
  Ursache: beide Stufen sind **reines Python**, Byte fuer Byte, ohne numpy.
- **Fine gegen Normal (gleiche Seite):** Fine 10,06 s / 1.234.964 B,
  Normal 0,66 s / 748.716 B -> **Fine ist 15x teurer**.
- **Erledigt (2026-10-30): Quantisierung per `bytes.translate`.** Die
  nibble-Quantisierung lief Byte fuer Byte in Python; jetzt macht das eine
  256er-Tabelle in C. Beweis der Gleichwertigkeit: die Tabelle stimmt fuer
  **alle 256 Werte** mit der Inline-Formel ueberein, und der XL2HB-Output ist
  **byte-identisch** (`cmp` auf `e2e.ps` und `drucktest2.ps`). Gemessen:
  A4-Platte 3139 ms -> 15 ms; eine Letter-Seite **13,2 s -> 9,4 s (-29 %)**,
  die Testsuite 54,7 s -> 44,3 s. 89 Tests gruen.
- **Naechster Hebel: die Cython-Beschleuniger decken nur den Normal-Modus.** `_rle_fast`,
  `_band_fast`, `_color_fast`, `_dither_fast` werden aus `rle.py`,
  `plane_encoders.py`, `pipeline.py`, `color_lut.py`, `dither.py` importiert –
  `fine_encoder.py` importiert **nichts** davon (kein `_fast`-Treffer).
  Ein `_fine_fast.pyx` fuer `compress_rle_preencode` + `compress_pattern_encode`
  waere der Weg; die Werkzeuge (`build_cython.sh`, `setup_cython.py`) liegen bereit.
- **Falle:** `.so`-Dateien im Repo sind **cpython-312**, die Installation laeuft
  aber auf **python3.11** (`.so` = cpython-311). Nicht wild kopieren – der
  Installer baut selbst. `python3 -c "import Cython"` schlaegt fehl, im
  `.venv312` liegt Cython 3.3.0.

## Offene Punkte, die KEIN Defekt sind (2026-10-30)
- ~~`interp_tables.bin` fehlt~~ **erledigt (2026-10-30):** die Datei liegt jetzt in
  `src/color_data/` (44217 B, sha256 `68ba7464…`) und wird von `install.sh`
  mitkopiert. Beweis der Gleichwertigkeit: mit und ohne Datei ist der XL2HB-Output
  **byte-identisch** (sha256 `eba9e1f1…`, 10454 B) – die Datei ist nur der
  zwischengespeicherte Wert der analytischen Erzeugung. Die Log-Zeile
  "generating analytically" erscheint nicht mehr, und die 33 ms/Job entfallen.
- **Der Verlaufs-Vergleich mit den alten Fixtures ist NICHT belastbar.**
  `grad2_port.xl2hb` und `drucktest2_port.xl2hb` stammen vom 29.10. 09:04/09:14,
  der Stage-1-Fix (`1e55eb2`) aber erst vom 29.10. 20:29 – sie sind veraltet.
  Ein frischer Render gegen `drucktest2_or.xl2hb` ergab **0 von 334 Zeilen
  gleich**, also eine Zeilen-Verschiebung (andere Capture-Bedingungen), keinen
  Rasterbefund. Vor jeder Aussage ueber Verlaeufe muessen Orakel und Port
  **aus derselben Quelle und mit denselben Settings** stammen.

## Hardware-Verifikation (2026-10-30)
- Drucker `192.168.178.50:9100` ist ein **echter HL-3040CN** (MAC `00:1b:a9`,
  PJL `INFO ID` = `"Brother HL-3040CN series:84E-201:Ver.1.18"`). Web-UI braucht
  Auth (404 ohne), SNMP antwortet nicht – **PJL auf 9100 ist der Zugang**:
  `@PJL INFO ID|STATUS|PAGECOUNT`.
- **Ein "Job completed" beweist NICHTS.** Der `socket`-Backend meldet Erfolg,
  sobald die Bytes im TCP-Puffer sind. Der einzige harte Beweis ist der
  **Hardware-Seitenzähler** `@PJL INFO PAGECOUNT`: er stieg in dieser Sitzung
  **7916 -> 7917**. `tools/hw_verify.py` fährt genau das (ID-Prüfung, dann
  Zähler vor/nach; `--status` nur berichten).
- **Falle:** `@PJL INFO STATUS` wechselte mitten in der Messung auf
  `CODE=41202 DISPLAY="Kein Papier" ONLINE=FALSE` – der Job lag an, es kam nur
  kein Papier raus. Vor dem Test `--status` lesen; ohne Papier bleibt der
  Zähler stehen und man hält es fälschlich für einen Treiberfehler.
- Stream-Form stimmt mit dem Orakel überein: gleicher PJL-Kopf
  (`@PJL SET ECONOMODE…` / `ENTER LANGUAGE=XL2HB`) und gleiches Ende
  (`1DIB` + `@PJL EOJ NAME="Print Job"` + UEL). Nur `@PJL JOB NAME=`/`PRINTLOG`
  fehlt, den der Vendor-Wrapper setzt (kosmetisch).

## Stage-2-Verlaufsabweichung: KEIN Druckfehler (2026-10-30)
- **Befund: das gedruckte Bild ist identisch.** Über die graue 60-Balken-Rampe
  sind **alle 26256 Zeilen (4 Platten) auf Rasterebene gleich** – Stage 1 ist auf
  **allen 3282 abweichenden Zeilen identisch**. Die Differenz ist **ausschließlich
  die Kompressionsgröße** (Port 10127324 B vs. Orakel 8608471 B, **+17,6 %**).
- Warum das Orakel kleiner ist: es findet auf denselben Bytes **längere Muster**
  (Mode 4/Stride 3) wo der Port Mode 3 + Literale schreibt. Erste Abweichung ist
  immer `or=0x10` (Literal) gegen `port=0x0b` (Mode-3-Extended-Header).
- `compress_pattern_encode(s1) == oracle_entry` ist **false** – das Orakel wählt
  eine andere, kürzere Tokenisierung; es ist **kein** Bug im Decoder.
- **Konsequenz:** kein sichtbarer Fehler, nur mehr Bytes über den Socket (bei
  einer 600-dpi-A4-Seite ~1,5 MB). Fix wäre eine reine Optimierung in
  `compress_pattern_encode` (Stride-3/4-Kandidaten länger verfolgen) – offen.
- **Falle:** `grad2chk.py` baut eine ANDERE Rampe (Rot->Cyan) als das Fixture und
  meldet deshalb "6564 s1-diffs" – Artefakt des Skripts, kein Befund. Für
  Aussagen über `gray` immer dieselbe Rampe rekonstruieren.
- Werkzeug: `tools/stage2_diag.py`.
  - **Verlustfreiheit bewiesen (2026-10-30):** `decode_stage2(compress_pattern_encode(s1))
    == s1` auf **allen 26256 Zeilen** der gray-Rampe, je Platte K/M/C/Y. Aufgeschluesselt
    (byte-identisch / Stage-1-gleich / Roundtrip-verlustfrei): K 6564/6564/6564,
    Y 6564/6564/6564, C 3282/6564/6564, M 3282/6564/6564. C und M weichen also nur in
    der Tokenisierung ab, **kein einziges Byte** geht verloren. Regressionstests:
    `Stage2LosslessTest` in `test_fine_mode.py`.
  - **Falle (neu, hat mich selbst erwischt):** `v3_normal_ramp_or.xl2hb` ist ein
    **Normal-Modus**-Capture (600 dpi, `comp_size` 10/12/20). Der Fine-Stage-2-Decoder
    gehoert dort **nicht** hinein - er desynchronisiert und stirbt mitten im Stream mit
    `IndexError`, was wie ein Decoder-Bug aussieht, aber eine Modusverwechslung ist.
    `tools/fine_decode.py` prueft jetzt `comp_size` der Block-Header und lehnt einen
    solchen Stream mit Begruendung ab. Modus vorher pruefen: Fine == `comp_size 0`.

## `copies` — KEIN Bug, Messartefakt (2026-10-29)
- Verdacht war: der Filter erzeugt bei `-n N` nur EINE Seite und setzt nur das
  Attribut. **Widerlegt.** Die Kette ist `pstops | gs | Filter`; **`pstops`**
  setzt `#copies N` (und `%RBINumCopies: N`), **Ghostscript** expandiert das zu
  `N` Seiten, und der Filter rendert jede genau **einmal** – genau wie der
  Vendor-Filter (`Copies=3` -> 3 Seiten, attr `[3,3,3]`).
- Beweis (echte Queue + Socket-Capture): `lp -n 3 one.ps` -> **3 Seiten**,
  `lp -n 3 pp.ps` (2 Seiten) -> **6 Seiten**, deterministisch (3x identisch).
  `pstops` ist bei JEDEM Job in der Kette (`/var/log/cups/error_log`) und CUPS
  übergibt `copies=3` als **argv[4]** (Log: `job=116 ... copies=3`).
- **Der Trugschluss (zweimal dieselbe Falle):** `pstops` zählt Seiten am
  `%%Page:`-Marker. Eine Datei ohne Marker (Body vor `%%BeginProlog`, wie das
  alte `/mnt/ssd/fuzz/cups_test.ps` **und** der frühere `page()`-Helper in
  `tools/fuzz_filter.py`) wird als **0 Seiten** durchgereicht – der Filter sieht
  dann eine Seite, egal was `-n` sagt. Für Kopien-Tests **immer**
  `%%Page: 1 1` + `%%BeginPageSetup`/`%%EndPageSetup` setzen.
- Die zwei Mechanismen sind bewusst getrennt und beide korrekt:
  * `ATTR_PAGE_COPIES = 0x31` (`C1 <lo> <hi> F8 31`, uint16, je BeginImage und
    EndPage) trägt die Kopienzahl **in-band** – wie die Referenz
    (`ref/hl4150/tests/test_print_settings.py::TestCopies` erwartet
    `b"\xc1\x03\x00\xf8\x31"`).
  * die **Seitenwiederholung** macht `pstops`+`gs`, weil das PPD
    `*cupsManualCopies: false` sagt (der Drucker kann keine Kopien in Hardware).
- **Nicht** "fixen": eine eigene Wiederholung im Filter würde bei `-n 3` **9**
  Seiten drucken (3 von gs × 3 im Filter). Der Brother-Wrapper pinnt in der
  rc-Datei `Copies=1` (`cupswrapperhl3040cn:224`), sein i386-Filter wiederholt
  deshalb selbst – das ist die **alte** Architektur ohne pstops, kein Vorbild.
- Regression: `tools/fuzz_filter.py::run_copies_case` fährt die **echte**
  `pstops | Filter`-Kette (1 Seite, `-n 3`) und verlangt 3 Bilder mit Zähler 3.
  Die malformed-Fälle stehen in `EXPECT_FAIL` (sauberer RC != 0 ist dort Erfolg).

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

## Mopria regression 2026-10-31: two server-side defects, both fixed
The printer was visible to the phone again after these. Both are *state* defects:
the advert itself was always correct, so mDNS looked healthy while the IPP
attributes were wrong.
- **`media-default` disagreed with `media-ready`.** The PPD shipped
  `*DefaultPageSize: Letter` on a German A4 printer. cupsd derives `media-ready`
  from `ReadyPaperSizes`, which is built from `DefaultPaperSize`; that is
  auto-detected from the locale (`de_DE` -> A4) as `A4,A3,A5,A6,EnvDL`. So the
  queue advertised `media-default=na_letter_8.5x11in` while `media-ready` listed
  only A4/A5/DL/A6 -- a default size the queue never reports as loaded. Mopria
  and AirPrint clients drop such a printer. Fixed in the PPD:
  `*DefaultPageSize`/`*DefaultImageableArea`/`*DefaultPaperDimension` Letter->A4.
  Verify: `ipptool ... gpa.test | grep media-default` -> `iso_a4_210x297mm`, and
  it must be a member of `media-ready`. Pinned by `DefaultMediaTest` in
  `src/test_consistency.py` (fails if any of the three defaults goes back to
  Letter).
- **Stale `media-empty-warning`.** `/etc/cups/printers.conf` carried
  `Reason media-empty-warning` although the printer reports no paper problem
  (SNMP `hrPrinterDetectedErrorState` = `0x0000`; `prtInputCurrentLevel=0` is
  "unknown", not "empty"). Two independent code paths can set it, and neither is
  gated by the PPD's `*cupsSNMPSupplies: false` -- that attribute only guards
  `backend_init_supplies()` (the marker-levels walk), while
  `backendSNMPSupplies()` emits `STATE: +media-empty-warning` itself. The other
  path is `runloop.c` on `ENOSPC`. Once set, the reason is *sticky*: it survives
  until an explicit reset. Cleared with
  `/usr/sbin/lpadmin -p Brother_HL-3040CN -E -o printer-state-reasons=none`
  (note: `lpadmin` is not on `$PATH`, use the absolute path). Verify with
  `ipptool ... | grep printer-state-reasons` -> `none`, and re-check after a real
  job.
- **Diagnostic lesson:** `STATE: +media-empty-warning` never appeared in
  `error_log` for the affected jobs -- `envp[25]="PRINTER_STATE_REASONS=..."` on
  Job 126 is the reason *inherited into* the job, not one the job set. Don't read
  it as proof the backend set it; look for the `STATE:` line, and trust the
  printer's own SNMP state (`0x0000` = healthy) over the queue's cached reason.

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

## Fine mode — Zwischenlevel-Lücke geschlossen (2026-10-29)
- Die letzte byte-identische Lücke war **kein** Raster-/Transition-Modus,
  sondern ein **Off-by-one im Stage-1-RLE-Encoder**
  (`compress_rle_preencode`, `hl3040cn/src/fine_encoder.py`): im Zweig
  `lo_nibble == 0` (Byte `0x_0`, hi != 0) mit laufendem Weiss-Run emittiert der
  Filter `run_white * 8`, der Port emittierte `run_white * 8 - 8`. Binär-Beweis
  `0x804f623: lea ecx,[esi*8]; ... or ecx,0xa0`. Symptom war `b8` vs `b0`.
- Die frühere **4/3-Dehnung** der Y/K-Screen-Zeilen (`dither.py`) war ein
  **Workaround** für genau diesen Fehler und ist **entfernt**.
  `dither_channel_4bpp_pattern_arr` gibt jetzt immer `width // 2` Bytes zurück.
- Beweis: `tools/verify_fine_stretch.py` **87082/87082** (Orakel unabhängig
  dekodiert, Port-Seite = Produktions-Pfad), inkl. der zuvor offenen
  gemischten/Solid-Fixtures (`s_200_50_100`, `s_128_128_130`). Suite 86/86.
- Details: logs/fine_transition.md. Regression: test_fine_mode.py
  (`FineEncoderTest.test_lo_zero_run_white_token`, `FineStretchTest`).
- **Weiterhin offen (separater Auftrag):** Fine-**Verlaufs**-Bilder (`grad2`,
  `drucktest2`) weichen ab, aber **ausschliesslich in Stage 2**
  (`compress_pattern_encode`): Stage 1 (Dither + RLE) ist auf allen Ramp-Platten
  byte-identisch; nur die Stage-2-Tokenisierung weicht ab.

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

## Nutzerbestaetigung Referenzblatt (2026-10-29)

Rueckmeldung des Nutzers nach dem Druck von `reference/refsheet.ps` (Jobs 85 und
86): **"Blau endet mit rechts gelb."** Damit ist der offene Punkt "hellblau am
Ende" (`logs/dup_gradient.md` §2, "Nutzer fragen, welches Dokument") **geklaert
und geschlossen**: das alte `drucktest.ps` endete bei R=51/255, also nie bei
echtem Gelb - der Effekt war das **Testblatt**, nicht der Treiber. Abschnitt B
des neuen Blattes laeuft mit `t t 1 t sub setrgbcolor`, bei `t=1` also exakt
`(1,1,0)` = reines Gelb.

Die "2x gedruckt"-Rueckmeldung ist ebenfalls geklaert: Jobs **85** (15:16) und
**86** (15:18) sind zwei **eigene** Uebermittlungen aus der Verifikation (einmal
Test, einmal Netzwerk-Mitschnitt), kein Doppeldruck des Treibers. Abschnitt E
(Grossflaechen-Duplikat) liegt dadurch **doppelt** auf dem Blatt - beim
Vergleich beachten.

**Weiterhin offen** (unveraendert, echte RE-Arbeit): Zwischen-Ink-Level-Raster.
Bei Volltoenen und reinem Grau ist der Port byte-identisch zum Orakel; bei
**Zwischen-Leveln** (z. B. der Blau->Gelb-Verlauf) weichen **C (50 %)** und
**K (17 %)** der Zeilen ab. Die Separation ist korrekt (Blau/Grau/Gelb stimmen),
die Abweichung ist eine **Raster-/Level-Wahl** (Dot-Pattern), kein Hue- oder
Skalenfehler. Das Orakel benutzt dort ein nicht ausgeliefertes Raster
(`logs/fine_reverse.md` §4, `logs/dup_gradient.md` Messung C).

## Transition-Modus delegiert + install.sh gehaertet (2026-10-29)

**Zwei neue Erkenntnisse in den Treiber eingebaut** (nicht nur dokumentiert):

1. **`install.sh` quarantaeniert veraltete `.so`.** Vorher warnte ein
   fehlgeschlagener Cython-Build nur und liess die **alte** `.so` liegen - genau
   der Weg, auf dem der Normal-Modus starb (18-Arg-`_band_fast` bei 14 Arg im
   Aufruf). Jetzt wandern sie nach `.stale-so-<zeitstempel>/`, der
   byte-identische Python-Pfad laeuft weiter. Isoliert getestet: 2 `.so` -> 0 im
   Ladepfad, 2 gesichert. `bash -n` sauber.
2. **`test_kernel_signature.py` prueft auch den installierten Baum** (Klasse
   `InstalledTreeTest`, in CI uebersprungen). Damit faengt die Suite eine von
   Hand abgelegte `.so`, nicht nur `install.sh`. 4 Tests, 86 gesamt - OK.

**Warum der PPD-Standard `600x2400dpi` (Fine) ist und das wichtig bleibt:** Der
Normal-Fehler blieb monatelang unentdeckt, weil Fine den Band-Kernel **nie**
aufruft. Normal ist aber verifiziert (`FINE_HANDOVER.md`: "Normal's grids are
already byte-identical - which is why Normal works"), der Kernel-Pfad ist mit
dem Python-Pfad byte-identisch (50571/5212/32316 B). Der PPD-Standard wurde
**nicht** geaendert - Fine ist die bessere Qualitaet und die dokumentierte Wahl.

**Offener Punkt an einen Agenten delegiert:** `TASK_TRANSITION.md` +
`TASK_TRANSITION_LAUNCH.md`, Conversation `909d0256-fde1-4487-932f-30b69313e890`
(Titel "Transition-Modus: Zwischenlevel-Zeilen", 500 Iterationen). Auftrag: die
Zwischen-Ink-Level-Luecke schliessen (C 50 %, K 17 % der Zeilen weichen ab,
Level `b8` vs `b0`). Der Auftrag nennt ausdruecklich, was **nicht** zu wiederholen
ist (falsche Tabellen, reine Level-Transformation, Phasenfehler, Encoder) und wo
die Harnesse liegen (`/mnt/ssd/finecmp/`, reboot-fest). Orakel-Container
`brother-cups` laeuft; Drucker `.50:9100` erreichbar.
