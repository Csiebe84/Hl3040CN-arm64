# Phase 3 — Implementierung der Fine-Strecke (Auftrag für Agent C)

Repo: `/root/brother/native` · Arbeitsverzeichnis für den Agenten: `/root/brother/native`

## Vorbedingung

**Lies zuerst `logs/fine_reverse.md`** (Phase 2, fertig) und
`logs/finding_gray_default.md`. Sie enthalten die rekonstruierte Funktion, die
Binary-Adressen und die Byte-Zahlen. Ohne diese beiden Dateien nicht starten.

## Was bereits bewiesen ist (nicht neu herleiten)

Phase 2 hat die Dither-Funktion aus dem i386-Binary extrahiert
(`0x804ed38`, „Fine-Dither (4bpp)") und **unabhängig verifiziert**:

```
level(px x, Zeile y) = pattern[ink][ (y % H) * (W/8) + (x % (W/8)) ] & 0x0F
Ausgabebyte k        = (level[2k] << 4) | level[2k+1]
```

- `pattern` = BRCD-`cache08`-Datei `capt-<c|m|y|k>.bin`, 256 Ink-Ebenen,
  je Ebene `(W*H+7)/8` Bytes. C/M: 160×20, Y/K: 96×12.
- **Das Low-Nibble des Pattern-Bytes ist der Level direkt** — es ist **keine**
  1-bpp-Schwellwertmatrix. Der aktuelle Port baut aus den Patterns eine
  Threshold-Matrix (`_extract_threshold_matrix`) und rechnet
  `base = ink*15//255`, `frac > threshold`. **Genau das ist der Defekt.**
- Verifikation gegen die Orakel-Stage-1 (via `compress_rle_preencode`):

  | grau | Kanal | Zeilen ok |
  |---|---|---|
  | 64 | C / M / Y / K | 6564/6564 (alle byte-identisch) |
  | 128 | C / M | 6564/6564 byte-identisch |
  | 128 | Y | 5470/6564 |
  | 192 | C / M | 6564/6564 byte-identisch |
  | 192 | Y | 5470/6564 |

  Selbst nachgeprüft mit `/mnt/ssd/finecmp/verify_stage1.py` → identische Zahlen.

- Die Ink-Werte kommen aus `ColorTable('rgb', capt=True)` (Tetraeder-Interpolation),
  **nicht** aus einer Threshold-Matrix:

  | grau | C | M | Y | K |
  |---|---|---|---|---|
  | 64 | 111 | 80 | 79 | 74 |
  | 128 | 87 | 64 | 64 | 0 |
  | 192 | 44 | 32 | 32 | 0 |

  (Konvention `0 = volle Farbe`, `255 = keine`; `ink = 255 - wert`.)
  **Achtung:** Das gilt für `BRGray=OFF`. Für `BRGray=ON` (Live-Default) gilt
  `rgb_ig_capt` — siehe `logs/finding_gray_default.md`.

- **Plane-Presence:** ist der Kanal-Ink 0, wird die Ebene **komplett
  weggelassen** (keine Blöcke). Beobachtet bei grau 128/192 (K=0).

- **Referenzimplementierung:** `/mnt/ssd/finecmp/rev_dither.py` (von Phase 2,
  mit `fine_dither_row()` und `rgb_to_cmyk_ink()`). Nutze sie als Vorlage,
  aber **kopiere keine Analyse-Harnesse ins Repo** — schreibe sauberen Code in
  `hl3040cn/src/`.

## Aufgabe

1. **`dither.py`:** einen Fine-Pfad ergänzen, der den Level **direkt aus dem
   Low-Nibble** liest, statt über die Threshold-Matrix zu gehen.
   - `DitherChannel` um die Roh-Patterns erweitern (oder eine eigene
     `FineDitherChannel`-Klasse). Die Patterns sind schon da, sie werden nur
     weggeworfen.
   - Neue Funktion, z. B. `dither_channel_4bpp_pattern_arr(row, y, width, channel)`,
     die obige Formel umsetzt. **Die alte `dither_channel_4bpp_arr` NICHT
     löschen** — sie wird noch gebraucht, bis der Fine-Pfad vollständig ist.
   - Wichtig: Die Ausgabe ist **5100 px Dither-Körper + 4 px Null-Pad**
     (= 2552 B/Zeile). Der Port schreibt aktuell `(width+1)//2` Bytes.

2. **`pipeline.py`:** den Fine-Pfad (`is_fine=True`) auf die neue Funktion
   umstellen und die Separation auf `rgb_capt`/`rgb_ig_capt` verdrahten.
   Der Normal-Pfad (`is_fine=False`) darf sich **nicht** ändern.

3. **Plane-Presence:** K-Ebene (und jede andere) bei Ink 0 weglassen.
   Prüfe, ob das schon so ist — die Beobachtung sagt ja, aber verifiziere es.

4. **Der offene Rest (Y-Zwischenlevel):** siehe `logs/fine_reverse.md` §4/§4b.
   Die capt-y-Zeilen mit Zwischenleveln ({4,12} bei grau 128, {2,10} bei
   grau 192) werden vom Filter **um Faktor 4/3 gedehnt** (3402 B statt 2552 B).
   Betrifft y≡4, y≡10 (mod 12) bzw. y≡2, y≡8 → je 1094 von 6564 Zeilen.
   **Wenn du den Dehnungsalgorithmus nicht sicher rekonstruieren kannst, lass
   ihn weg und dokumentiere das** — 83 % identisches Y ist ein riesiger
   Fortschritt gegenüber dem Ist-Zustand. Keine Rateversuche einbauen.

5. **`fine_compare.py`:** auf die Live-Konfiguration umstellen (BRGray=ON
   **und** OFF getrennt prüfen, siehe `logs/finding_gray_default.md`).
   Ziel: von **0/4** auf **4/4**. Falls die Y-Restabweichung 4/4 verhindert,
   berichte den exakten Stand (z. B. 2/4) — **keine Ziele fälschen.**

6. **Regression:** Der Normal-Pfad muss byte-identisch bleiben. Prüfe das
   explizit (Normal-Rampe gegen Orakel, wie `ramp_pipeline_compare.py`).
   Alle bestehenden Tests müssen grün bleiben:
   ```
   .venv312/bin/python -m unittest discover -s hl3040cn/src -t hl3040cn/src
   ```

## Regeln

- **Nur `hl3040cn/src/*` und `tools/fine_compare.py` ändern.** Kein Commit,
  kein Push (das macht die Orchestrierung nach der Verifikation).
- Fixtures nach `/mnt/ssd/finecmp`, **nie** nach `/tmp` (RAM!).
- Nur **ein** Orakel-Lauf gleichzeitig. RAM ist knapp (~60–130 MB frei).
- Orakel: `tools/oracle_run.py <ppm> <out> --resolution Fine --gray ON|OFF`
- Neue Orakel-Referenzen für den ON-Pfad anlegen (falls noch nicht da):
  ```
  .venv312/bin/python tools/oracle_run.py /mnt/ssd/finecmp/g128.ppm \
      /mnt/ssd/finecmp/g128_fine_ig.xl2hb --resolution Fine --gray ON
  ```
- **Abgabe:** `logs/fine_impl.md` mit (a) den geänderten Dateien, (b) den
  gemessenen Byte-Zahlen Orakel vs. Port je Ebene und Modus, (c) dem
  Testergebnis, (d) ehrlich benannten Restabweichungen.
