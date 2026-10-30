# Auftrag: Fine-Modus — entscheidende Level-Messung (Phase 1)

Repo: `/root/brother/native` · Tests: `/root/brother/native/.venv312/bin/python -m unittest`
Arbeitsverzeichnis für den Agenten: `/root/brother/native`

## Ziel in einem Satz

**Eine einzige Messung**, die entscheidet, welches Modell der Fine-Modus hat:
„ein Screen + 16-Level-Ramp" **oder** „per-Scanline wechselnde Screens".
Diese Frage ist seit zwei Agenten-Runden offen und blockiert alles Weitere.

## Kontext (belegt, nicht neu herleiten)

- Normal-Modus ist **byte-identisch** zum Brother-Filter. Fine ist es nicht.
- Der Encoder ist **nicht** schuld: beide Stufen reproduzieren die Orakel-Bytes
  exakt, wenn man ihnen die Orakel-Stage-1 füttert (siehe `FINE_HANDOVER.md` §3a).
- Die Fine-**Farbtabelle** (`rgb_capt`/`srgb_capt`, `transforms.py:51`) ist
  **richtig** — nur mit ihr fehlt die K-Ebene wie im Orakel.
- Die Fine-**Dither-Screens** sind **ungeklärt**: weder `capt` noch `0600`
  ist byte-exakt.
- **WIDERLEGT** (nicht wiederholen): „Fine = `0600`-Screens + binärer
  Quantisierer". Der Verify-Agent (`logs/verify_fine.md`, Verdikt b) hat gezeigt:
  das Orakel enthält die Nibble-Level **4, 10 und 14** — ein
  `np.where(ink>thr,15,0)` kann die nie erzeugen. Ausserdem divergiert
  `capt/bin` auf der Ganzseiten-Metrik **weniger** als `0600/bin`.
  Der damalige Code-Änderungsversuch wurde zurückgerollt.
- Die Doku `FINE_HANDOVER.md` enthält **uncommittet** noch den widerlegten
  Befund in §7d — **ignorieren**. Maßgeblich ist `logs/verify_fine.md`.

## Das Orakel

Läuft (Docker-Container `brother-cups`, Image `brother-hl3040cn:local`, i386
über qemu — nur für die Analyse, die Druck-Pipeline ist emulatorfrei).

- Referenzdatei: `/mnt/ssd/finecmp/s128_fine.xl2hb` (grau 128, Letter, Fine)
- Neuer Lauf: `tools/oracle_run.py <ppm> <out.xl2hb> --resolution Fine`
- Entpacken: `pclxl.parse` + `band.decode_blocks` + `fine_decode.decode_stage2`
- **FALLE:** immer über **alle** Entries einer Ebene summieren, nie nur
  `entries[0]` (das unterschätzt um ~7000x — siehe §7c).
- **FALLE:** Eingaben müssen **volle Breite UND Höhe** haben (Letter =
  5100x6564). Der Filter skaliert kurze PPMs auf die ganze Seite, dann ist die
  Block-Tabelle wertlos.

## Die Messung (genau das, nichts anderes)

Für **eine** Ebene (C) und wenn möglich M und Y:

1. Invertiere **alle** Scanlines der Ebene mit dem **vollen** Alphabet
   (`/tmp/verify/capt_check.py` hat den Ansatz; die dortige Memoisierung ist
   wiederverwendbar). Nicht nur e0–e11 — das war der Fehler der Vorgänger.
2. Histogramm der zurückgewonnenen 4-bpp-Level **pro Zeile**.
3. Periode **pro Zeile** bestimmen (kleinste Wiederholung).

## Entscheidungsregel (vorab festgelegt, damit das Ergebnis eindeutig ist)

- **Level-Menge konstant über alle Zeilen UND Periode konstant**
  → Modell A: „ein Screen + Level-Funktion". Dann ist die nächste Frage: welche
  Funktion bildet den CAPT-Ink-Wert auf dieses Level ab?
- **Level-Menge oder Periode wechselt zeilenweise**
  → Modell B: „per-Scanline Screen-Alternation". Dann ist die nächste Frage:
  nach welcher Regel wird der Screen je Zeile gewählt (Zeilenindex? Muster?)
- **Kein stabiles Muster** → das ausdrücklich so berichten, mit den Rohdaten.

## Grenzen (hart)

- **Nur lesen und messen.** Kein Treibercode ändern (`dither.py`,
  `pipeline.py`, `transforms.py`, `fine_encoder.py`, `xl2hb.py` bleiben
  unangetastet). Kein Commit, kein Push.
- Harnesse nach `/tmp/` schreiben (dort liegen schon die Werkzeuge des
  Verify-Agenten: `capt_check.py`, `bin_rows.py`, `bound_stability.py`,
  `natural.py` — **wiederverwenden**, nicht neu bauen).
- Fixtures nach `/mnt/ssd/finecmp`, **nie** `/tmp` (tmpfs, RAM ist knapp:
  ~40 MB frei. Ein 100-MB-PPM in `/tmp` hat schon ENOSPC ausgelöst).
- Nur **einen** Orakel-Lauf gleichzeitig.

## Abgabe

Schreibe `logs/fine_levels.md` mit:

1. **Verdikt**: Modell A oder B (oder „kein stabiles Muster").
2. Die Rohdaten: Level-Histogramm und Periode pro Zeile, für C/M/Y.
3. Die zurückgewonnenen Nibble-Sequenzen der ersten ~20 Zeilen je Ebene.
4. **Konkrete nächste Aufgabe** für den Reverse-Engineering-Agenten: welcher
   Code-Pfad im i386-Binary zu suchen ist (Adressen/Ankerpunkte).

Diese Datei ist der Input für Phase 2. Sie muss ohne Rückfragen verständlich sein.
