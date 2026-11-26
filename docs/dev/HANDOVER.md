# Übergabe: HL-3040CN Farbtransformation (Aufgabe Nr. 1)

## Auftrag

Finde die Farbtransformation des Original-Filters, die zwischen Farb-LUT und
Dithering liegt. Ziel: die Oracle-Tintenstufen bit-genau reproduzieren, danach
den vollen Pipeline-Vergleich bestehen.

**Kein Emulator-Lauf nötig, um zu beginnen.** Alle nötigen Fixtures liegen
bereits vor. Ein Emulator-Lauf (Docker-Container `brother-cups`) ist nur
sinnvoll, wenn du eine Tonwert-Rampe als neues Fixture brauchst — und das ist
der wahrscheinlich nächste Schritt.

## Ausgangslage (verifiziert, nicht geschätzt)

### Was funktioniert

1. **Dither-Tabellen laden jetzt korrekt.** `hl3040cn/src/dither.py` suchte
   `0600-*_cache09.bin`; der HL-3040CN liefert `cache08`. Jede Suche schlug
   fehl, die Pipeline fiel still auf ein 32x32-Bayer-Raster zurück.
   Fix: `_BRCD_CACHE = "cache08"`. Regressionstests:
   `hl3040cn/src/test_dither_tables.py` (9 Tests, alle grün).

2. **Beide RLE-Encoder sind bit-genau identisch mit Brother's.** Das ist der
   stärkste Befund und schließt die Kompression als Fehlerquelle aus:
   ```
   Y (cs=12): 80 identisch, 0 abweichend
   M (cs=10): 80 identisch, 0 abweichend
   ```
   Reproduzierbar mit `tools/encoder_check.py red`.
   Verfahren: Oracle-Ebene dekodieren, mit dem Port-Encoder neu kodieren,
   Bytes vergleichen.

3. **Der 10-Bit-Decoder existiert und ist validiert.** In
   `src/rle_decode.py` neu: `decode_10bit()` (5-Wort-Kontext, 2-Bit-High-Feld,
   Kontext-Skip = Wort 4 Positionen zurück). Validierung:
   `tools/test_decoders.py` → 12-bit round-trip OK, 10-bit round-trip OK,
   120 Oracle-M-Zeilen fehlerfrei.

### Der offene Fehler

Die Tintenstufen der Farbseparation stimmen nicht. Gemessen mit demselben
Verfahren auf beiden Seiten (`tools/level_compare.py red`):

```
ORACLE  M(cs=10)  TabZeile=0  Stufe= 36  Tinte=219  Fehler=16/5120
ORACLE  Y(cs=12)  TabZeile=0  Stufe= 65  Tinte=190  Fehler=12/5120
NATIVE  M(cs=10)  TabZeile=0  Stufe=108  Tinte=147  Fehler= 0/5120
NATIVE  Y(cs=12)  TabZeile=0  Stufe=  9  Tinte=246  Fehler= 7/5120
```

Der Fit-Fehler ist winzig (≤16 Bit von 5120), die Stufen sind also belastbar.
Der Port nimmt für Rot **zu wenig Magenta** (147 statt 219) und **zu viel
Gelb** (246 statt 190).

Gemessene Oracle-Tinten aller Primärfarben (`tools/ink_table.py`):

| Farbe | Ebene | Oracle-Tinte |
|---|---|---|
| rot | M / Y | 219 / 190 |
| grün | Y | 225 |
| blau | M | 96 |
| cyan | Y | 13 |
| magenta | M | 219 |
| gelb | Y | 225 |

## Was bereits ausgeschlossen ist

- **Nicht die Encoder** — beide bit-genau (s.o.).
- **Nicht die Dither-Tabellen** — cache08 geladen, Level-Fit nahezu perfekt.
- **Nicht die Auswahl unter den 18 Tabellen** — `tools/table_search.py`
  rechnet alle 18 durch; keine reproduziert das Oracle, alle weichen bei
  Offset 168 ab (im ersten M-Block).
- **Nicht eines der 29 Gitter im 3040-Binary.** Rot ist exakt ein Gitterknoten
  (R=255, G=0, B=0 → Index 16 auf der R-Achse), die Oracle-Tinte wäre dort
  also direkt ablesbar. `tools/grid_solve.py` prüft alle 29 Kandidaten × 6
  Achsenordnungen: bester Treffer 468 Gesamtfehler über 6 Farben.
  `tools/grid_red.py` findet **keinen** Kandidaten mit dem Paar (Y=65, M=36).
- **Nicht ein Parser-/Decoder-Artefakt** — beide Ebenen dekodieren fehlerfrei,
  der Round-Trip ist bit-genau.

## Wichtige Struktur-Befunde

1. **`CommentData` als Ebenen-ID ist unzuverlässig.** Rot öffnet mit einem
   cs=10-Block (CommentData=2), Magenta mit einem cs=20-Block
   (CommentData=1). Die Blöcke heißen je Farbe anders, obwohl dasselbe
   physikalische Bild vorliegt. **Verlasse dich auf `comp_size` + Bitmap, nicht
   auf `CommentData`.** Das steht so auch in der ursprünglichen Aufgabenstellung.

2. **Gleiche Bitmaps, verschiedene Farben.** Bit-genau per SHA-256:
   - Rot und Magenta haben **identische M-Ebene** (`6399e5ffb8677b0c`,
     Dichte 0.7969). Beide haben G=0.
   - Grün und Gelb haben **identische Y-Ebene** (`93b4c8bd95940ac5`,
     Dichte 0.6641). Beide haben B=0.
   Das ist konsistent und kein Messfehler — aber es heißt, dass die
   Farbseparation von **zwei** Eingangskanälen abhängt, nicht von allen dreien.

3. **Die Oracle-Ebenen sind vertikal periodisch** mit der Tabellenhöhe
   (M: 80, Y: 24), horizontal mit Periode 10 (der 10-Bit-Wortbreite).
   `tools/plane_structure.py` zeigt das. Die Tinte ist über die ganze Seite
   konstant — eine Phase gibt es **nicht** (Phase=0 in allen Messungen).

4. **Der Oracle zerlegt in ~450-Zeilen-Blöcke, der Port in ~2200.** Das ist
   eine Folge des Inhalts (der Puffer läuft bei ~27000 B voll), kein eigener
   Fehler — aber es erschwert den Byte-Vergleich.

## Werkzeuge (alle in `native/tools/`, alle laufen ohne Emulator)

| Werkzeug | Zweck |
|---|---|
| `test_decoders.py` | Validierung beider RLE-Decoder (round-trip + Oracle-Zeilen) |
| `encoder_check.py` | Port-Encoder vs. Brother's, bit-genau |
| `level_compare.py` | Tintenstufe pro Ebene, Oracle vs. Port, ein Verfahren |
| `ink_table.py` | Oracle-Tinten aller Primärfarben |
| `plane_table.py` | Alle Ebenen je Fixture: Wortbreite, Zeilen, Dichte |
| `plane_identity.py` | Bitmap-Hashes je (CommentData, comp_size) |
| `plane_structure.py` | Periode, Dichte, horizontales Muster einer Ebene |
| `grid_solve.py` | Alle Gitter × Achsenordnungen gegen die Oracle-Tinten |
| `table_search.py` | Alle 18 Farbtabellen gegen das Oracle (Byte-Vergleich) |
| `op_diff.py` | Operator-für-Operator-Vergleich zweier Ströme |
| `block_dump.py` | Blockstruktur (Ebene, cs, Start, Höhe, Bytes) |

Gemeinsame Annahmen in allen Werkzeugen: `WIDTH=5120`, `LINE_BYTES=640`
(5120 px / 8), Fixtures unter `/mnt/ssd/bprobe/`.

## Daten

- Fixtures: `/mnt/ssd/bprobe/{red,grn,blu,cyn,mag,yel}.{ppm,xl2hb}`
  (5120x6564, Letter, 600 dpi). PPMs sind verifiziert: rot=(255,0,0),
  magenta=(255,0,255) usw.
- 4150-Vergleichsfixtures: `{red,grn}_4150.xl2hb` — **Achtung**, der
  vorhandene Parser `src/band.py` scheitert daran
  (`BandError: entry of 325 bytes overruns the block`). Der 4150 nutzt ein
  anderes Blockformat; hier ist noch Arbeit nötig.
- Oracle-Container: `docker exec -i brother-cups sh -c
  "/opt/brother/Printers/hl3040cn/lpd/brhl3040cnfilter -pi ... -rc ..."`
  (läuft, `brother-cups` Up).
- Quellcode: `hl3040cn/src/` (`pipeline.py`, `color_lut.py`, `dither.py`,
  `transforms.py`, `plane_encoders.py`, `rle.py`).
- Farbtabellen: `hl3040cn/src/color_data/*.bin` (13 von 18 vorhanden).
- Gitter im Binary: `ref/brhl3040cnfilter.bin`, lokalisiert via
  `hl3040cn/src/find_luts.py` (29 Kandidaten, 2 davon nachweislich identisch
  mit dem 4150).

## Empfohlener nächster Schritt

**Eine Tonwert-Rampe durch den Oracle erzeugen.** Die sechs Primärfarben geben
nur sechs Datenpunkte und reichen nicht, um die Form der Abbildung zu
bestimmen. Eine Rampe (z.B. 256 Graustufen-Balken, oder ein R-Achsen-Verlauf
bei G=B=0) liefert in **einem** Emulator-Lauf hunderte Punkte und zeigt, ob es
eine Gradationskurve, eine Tintenbegrenzung oder ein UCR/GCR ist.

Vorgehen:
1. Rampe als PPM bauen (5120x6564, Letter — kleinere Seiten skaliert der
   Oracle auf das volle Blatt, das ist bereits geprüft).
2. Durch den Oracle schicken, Ausgabe als Fixture ablegen.
3. Mit `tools/level_compare.py` (Rampe statt Vollton) die Stufe je Balken
   messen und gegen die Port-Ausgabe auftragen.
4. Erst dann eine Korrektur ableiten — und nur, wenn die Messung sie belegt.

**Regeln, die sich bewährt haben** (bitte einhalten, sonst droht die Schleife,
in der ich feststeckte):
- Jede Hypothese bekommt Status: offen / bestätigt / widerlegt.
- Vor einer Wiederholung erklären, welche **neue** Information sie liefert.
- Neue Skripte nur, wenn vorhandene die Frage nicht beantworten können.
- Keine Erfolgsmeldung ohne sichtbares Testergebnis.
- Keine erfundenen Fortschrittsprozente.
- Bei einem Fehler höchstens einen gezielten Diagnoseversuch, danach beheben
  oder Blocker dokumentieren.

## Nicht Teil dieser Aufgabe

CUPS-Integration, PPD, PJL-Vervollständigung, Git, Lizenzprüfung,
Dokumentation, reale Drucktests. Das läuft getrennt.
