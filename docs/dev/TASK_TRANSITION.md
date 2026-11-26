# Auftrag: Der „7-Transition"-Mechanismus — Zwischenlevel-Zeilen jenseits der 4/3-Dehnung

## Ziel in einem Satz

Die **letzte** byte-identische Lücke schließen: Bei **Zwischen-Ink-Leveln**
weichen ganze Zeilen ab, obwohl die 4/3-Dehnung der Y/K-Screen-Zeilen schon
eingebaut ist (Fine: grau 128/192 byte-identisch). Gesucht ist die Regel, die
das Orakel dort anwendet — vermutlich ein **„7-Transition"-Modus** (die
BRCD-v1-Raster mit gemischten Leveln in einer Zeile).

## Was bereits bewiesen ist — NICHT neu herleiten

**1. Fine, uniforme Spalten (grau 128/192/64) sind gelöst:**
`logs/fine_reverse.md`, `FINE_HANDOVER.md`, `logs/dup_gradient.md`.

| Fall | Stand |
|---|---|
| grau 64 (Y ink=79, keine Zwischenlevel) | **6564/6564** identisch |
| grau 128 (Y ink=64) | **6564/6564** nach der 4/3-Dehnung |
| grau 192 (Y ink=32) | **6564/6564** nach der 4/3-Dehnung |
| Vollfarben (`solid_blue (0,0,255)`, `solid_olive (128,128,64)`) | **byte-identisch** |
| grau 128, C und M | **byte-identisch** |

**2. Die verbleibende Abweichung — der eigentliche Auftrag:**
`logs/dup_gradient.md` Messung B/C, gegen `s_200_50_100`, `s_128_128_130` und den
Blau→Gelb-Verlauf:

| Testbild | C | M | Y | K |
|---|---|---|---|---|
| `grad2` (korr. Verlauf) | 3282/6564 (50 %) | 3282 (50 %) | 6564 (100 %) | 3282 (50 %) |
| `drucktest2` (via gs) | 450/961 (47 %) | 376 (39 %) | 751 (78 %) | 516 (27 %) |

Muster: **die Abweichung tritt genau dann auf, wenn ein Kanal einen
Zwischen-Level dithert** (partielle Deckung, kein 0/15). Bei Volltönen und reinem
Grau stimmt alles. Es ist eine **Raster-/Level-Wahl** (Dot-Pattern), **kein**
Hue- oder Skalenfehler — die Separation selbst ist korrekt (Messung A).

**3. Der 4/3-Mechanismus (schon implementiert, `hl3040cn/src/dither.py` ~Zeile 403):**
`capt-y`/`capt-k` sind 96×12 (12 Byte/Zeile). Der Filter weitet eine Screen-Zeile
mit Zwischenleveln an **geraden** Pixeln auf `wb*4/3` (12 → 16 Byte) durch
Einfügen von Null-Bytes; Zeilen mit `wb % 3 != 0` werden **nie** gedehnt. Das
ist in `dither.py` in `dither_channel_4bpp_pattern_arr` umgesetzt und durch
`FineStretchTest` (5 Tests) abgesichert.

**4. Die entscheidende offene Spur (`logs/fine_reverse.md` §4b/§4c):**
Der Orakel-Preimage einer Sonderzeile ist **3402 B = 2552 × 4/3**; die
16er-Periodik lautet

```
00 C 00 F 0000 4 00 F 0000 C 00 F 0000 4 00 F …   (16er-Periode)
```

also **dieselben Level-Komponenten** (C/F/4/F) wie die 12er-Zeile, nur in 16er-
Periodik. Die Dehnung fügt Null-Nibbles ein, sie erfindet keine neuen Level.

**5. Was bei der 4/3-Dehnung noch nicht stimmt:** Nach der Dehnung bleiben bei
**C (50 %)** und **K (17 %)** der Zeilen Abweichungen — eine **Level-Differenz
`b8` vs `b0`** (8 zu niedrig), **keine Längen-Differenz**. Die Dehnung greift
also, aber die **Level-Wahl** in der gedehnten Zeile ist nicht exakt.

## Bereits ausgeschlossen — nicht wieder versuchen

- **Falsche Tabellen:** `capt-y` ist mit 5470/6564 klar am besten; `capt-y-TS`
  2188/6564; `0600-y` und `0600-y-TS` **0/6564**.
- **Reine Level-Transformation** (nach dem Dither): unverändert, `+8 clamp15`,
  `+8 mod16`, Nibble-Swap, High-Nibble — alle nein.
- **Phasen-/Indexfehler:** kein Screen-Zyklus `ry` (0..11) und kein Ink-Wert
  (0..255) erzeugt die Orakel-Zeile.
- **Encoder/Stage 2:** byte-identisch. Stage 1 stimmt auf allen Nicht-Sonderzeilen.
- **Der Nutzer-Effekt „gruen-gelb statt gelb":** das war das **alte Testblatt**
  (`drucktest.ps` endete bei R=51/255), **kein** Treiber-Bug. Der Nutzer hat auf
  echtem Papier bestätigt: „Blau endet rechts gelb" (Abschnitt B des neuen
  Referenzblatts). Nicht erneut untersuchen.
- **Normal-Modus:** läuft (die stale 18-Arg-`_band_fast.so` wurde durch einen
  Neubau ersetzt, `test_kernel_signature.py` bewacht das). Nicht Teil dieses
  Auftrags.

## Werkzeuge, die es schon gibt (nicht neu schreiben)

**In `/root/brother/native/tools/` (im Git):**

- `level_compare.py`, `solve_level.py` — Level + vertikale Phase gemeinsam gegen
  den ganzen Tabellen-Zyklus suchen, **ehrlicher Fehlerzähler**.
- `oracle_run.py` — schreibt ein PPM und ruft den i386-Filter im Container.
- `fine_decode.py` (`decode_stage2`), `cross_oracle.py`, `verify_fine_stretch.py`.
- `verify_fine_stretch.py` ist der **dauerhafte** Beweis (65640/65640); nach
  jeder Änderung laufen lassen.

**In `/mnt/ssd/finecmp/` (SSD, reboot-fest; `/tmp` ist tmpfs und war beim Reboot weg):**

- `s1model.py` / `s1inv6.py` — exakte Stage-1-Vorwärts-/Invers-Modelle
  (`forward == stage1` ist die Absicherung jeder Inversion).
- `rev_dither.py` (`rgb_to_cmyk_ink`), `render_port.py`, `filter_s1.py`.
- `verify_stage1.py`, `verify_stage1_64.py`, `verify_stage1_192.py`.
- `finedecode.py`, `capt_verify.py`, `captsearch.py`.
- Preimage-Cache: `/mnt/ssd/finecmp/s128_levels_cache.json` (240 KB; macht
  Wiederholungen sekundenschnell; Keys `a547a947…` / `a147a947…`).
- Orakel-Fixtures: `s128_fine.xl2hb`, `s_200_50_100_or.xl2hb`, `grad2_or.xl2hb`,
  `drucktest2.ps`, `black_fine_tsON.xl2hb` / `black_fine_tsOFF.xl2hb`.

**Echtes Orakel** (i386-Filter im Docker, NICHT im Druckpfad — nur zum Messen):
Container `brother-cups` (`docker start brother-cups`, ist gerade **up**).
Aufruf wie in `logs/emulator-removal.md`; `oracle_run.py` schreibt ein PPM und
ruft den Filter. `docker exec … cat` umgeht eine glibc-stdio-Pipe-Inkompatibilität
der 2011-Binary — reine stdin-Umleitung ist unzuverlässig.

**Drucker** `192.168.178.50:9100` ist erreichbar. Ein echter Testdruck ist
**erlaubt**, aber sparsam (Papier!): höchstens am Ende, wenn eine Korrektur
bewiesen ist. Vorher reicht der Datei-Vergleich gegen das Orakel.

**Interpreter:** `/root/brother/native/.venv312/bin/python` (Python 3.12) für die
Harnesse; der Filter selbst läuft unter Python 3.11
(`/usr/local/lib/brhl3040cn/.venv`). Cython-Erweiterungen liegen für **beide**
vor; nach einer Änderung an `*.pyx` mit dem **3.11**-Interpreter neu bauen
(`hl3040cn/setup_cython.py build_ext --inplace --force`), sonst schlägt
`test_kernel_signature` zu Recht an.

## Vorgehen (Vorschlag — eigene Messung schlägt Vorschlag)

1. **Fehlerbild exakt eingrenzen.** Für `s_200_50_100` (C 3282/6564) eine
   abweichende C-Zeile heraussuchen und die Orakel-Nibbles neben die Port-Nibbles
   legen. Bestätige oder widerlege die `b8`/`b0`-Differenz und ob sie an der
   **Level-Wahl** oder an der **Füll-Regel** hängt.
2. **Die 16er-Periodik zuordnen.** Die gedehnte Orakel-Zeile auf die 12er-Zeile
   abbilden: welche Nibbles sind Füllung, wie hängt die Phase von `y` und vom
   Level ab? `s1inv6.invert` liefert die Nibbles (Cache nutzen).
3. **K-Muster klären** (Geometrie-Hinweis aus §4c): K hat **dieselbe** Geometrie
   wie Y (96×12). Zeigt K dasselbe Verhalten? Wenn nicht, hängt es an der
   Ink-Zahl, nicht an der Breite — das entscheidet die Implementierung.
4. **Implementieren** in `hl3040cn/src/dither.py` (bzw. `pipeline.py`).
5. **Beweisen:** Die abweichenden C/K-Zeilen auf **0** bringen, ohne
   grau 64/128/192, C, M, Y und die Vollfarben zu verschlechtern.
6. **Regressionstest** in `hl3040cn/src/test_fine_mode.py` ergänzen.

## Harte Regeln

- Jede Hypothese bekommt Status: **offen / bestätigt / widerlegt**.
- Vor einer Wiederholung erklären, welche **NEUE** Information sie liefert.
- Neue Skripte nur, wenn die vorhandenen die Frage nicht beantworten.
- **Keine Erfolgsmeldung ohne sichtbares Testergebnis.** Keine erfundenen
  Prozente. Messwerte in Logdateien unter `logs/` sichern, nicht nur auf dem
  Bildschirm.
- Bei einem Fehler höchstens **EINEN** gezielten Diagnoseversuch, danach beheben
  oder den Blocker dokumentieren und weitermachen.
- **Fixtures NIE nach `/tmp`** — die Maschine hat nur 3,7 GB RAM; ein 100-MB-PPM
  hat schon ENOSPC ausgelöst. Immer `/mnt/ssd/...`.
- Schwere Läufe mit `nice -n 19` und `-j1`; parallele Builds haben das Board
  schon einmal hart resettet.
- Wenn die Regel nicht eindeutig herleitbar ist, ist das Ergebnis ausdrücklich
  **„Transition-Modus weiterhin ungeklärt"** — dann nicht weiter raten.

## Nicht Teil dieser Aufgabe

CUPS-Integration, PPD, Git/Push, Lizenzprüfung, Dokumentation, Emulator-Entfernung.

## Bericht am Ende

- Die abweichenden Zeilen je Ebene (C/M/Y/K) vorher/nachher, als Zahlen.
- Die abgeleitete Regel (oder „ungeklärt" mit dem, was ausgeschlossen wurde).
- Ob grau 64/128/192, C, M, Y und die Vollfarben unverändert byte-identisch sind.
- Der neue Regressionstest und sein Ergebnis.
