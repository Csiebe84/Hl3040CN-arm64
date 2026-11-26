# Auftrag: Fine-Modus — Farbstrecke aus dem i386-Binary rekonstruieren (Phase 2)

Repo: `/root/brother/native` · Arbeitsverzeichnis für den Agenten: `/root/brother/native`

## Vorbedingung

**Lies zuerst `logs/fine_levels.md`** (Phase 1, fertig). Es sagt dir, welches
Modell gilt und wo im Binary zu suchen ist. Ohne dieses Ergebnis nicht starten —
sonst wiederholst du die Fehler der Vorgänger.

## Phase-1-Ergebnis (fertig, nicht neu messen)

**Verdikt: Modell A — EIN Screen pro Ebene + Level-Funktion.** Kein
per-Scanline Screen-Wechsel. Belege in `logs/fine_levels.md` §1–§3.

- Zeilen-Periode == capt-Screen-Höhe: C 20 (= capt-c 160×20), Y 12
  (= capt-y 96×12), M **10** (capt-m ist 160×20 — der Filter nutzt für M nur
  10 Zeilen; das ist ein eigener Hinweis, siehe unten).
- Alle Zeilen einer Familie sind **Rotationen einer Basiszeile** mit festem
  Phasenschritt (C +6 px/Zeile in der 20er-Familie, +3 px/+2 Zeilen in der
  10er; M +7 px/Zeile; Y +3 px/+3 Zeilen).
- Die Level-Mengen sind {0,15}, {0,14,15} (C), {0,10,15} (M),
  {0,15}/{0,4,15}/{0,4,12,15} (Y).

**Die entscheidende Schlussfolgerung:** Der Quantiser ist **nicht** das Problem
und die Screens sind es **auch nicht**. Die Level passen zur Port-Formel
(`base = ink*15//255`, `frac > threshold`) — nur mit **anderen Ink-Werten** als
der Port liefert. Der Defekt sitzt damit in der **Separationstabelle**.

**Wichtige Einschränkung, die du beachten musst:** Die Rückrechnung
„Level-Wahrscheinlichkeit → Ink-Wert" ist **unterbestimmt**. Viele Ink-Werte
bilden über den Dither auf dieselbe Level-Verteilung ab. Die in §5 genannten
Werte (C≈64–76, M≈56–68, Y≈49–85) sind daher **Schätzungen, keine Messungen**.
Nimm sie als Suchrichtung, nicht als Wahrheit. Der Beweis muss aus dem Binary
kommen.

**Achtung — möglicher Widerspruch, den du klären sollst:** Eine frühere Messung
(nicht verifiziert, `FINE_HANDOVER.md` §8, Punkt 2) fand Oracle-Inks C≈58/Y≈24
und dass diese zu **keiner** der 17 ausgelieferten `*_lut.bin` passen. Die
Phase-1-Schätzung liegt höher (C≈64–76). Kläre im Binary, welcher Wert stimmt —
das ist genau die Kernfrage.

### Konkrete Suchaufträge im i386-Binary (aus Phase 1 §5)

1. **Die Level-Berechnung:** suche die `v*15//255` / `v*15%255`-Arithmetik
   (im Binär: `imul`/`idiv` mit 15 bzw. 255) oder eine 4-bpp-Level-LUT. Die
   Level {4,10,12,14} müssen erzeugbar sein; `np.where(ink>thr,15,0)` ist
   **ausgeschlossen** (widerlegt).
2. **Die capt-Screen-Zeilenrotation:** die Funktion, die die Dither-Matrix auf
   Breite 5100 kachelt. Erwartet: `(y + phase) % screen_height`. Prüfe
   **warum M nur 10 Zeilen nutzt** (capt-m hat 20).
3. **Die Separationstabelle** (der eigentliche Verdacht): die 3×3-Matrix bzw.
   LUT, die auf die 4-bpp-Quantisierung abbildet. Vergleiche mit
   `hl3040cn/src/color_lut.py` (`rgb_capt`).

## Ziel

Die **exakte** Fine-Farbstrecke aus dem Brother-Filter rekonstruieren, sodass
der Port für eine Vollseite **byte-identisch** wird — nicht „ähnlich".

## Was schon feststeht (nicht neu herleiten)

- **Normal ist byte-identisch.** Fine ist es nicht: `tools/fine_compare.py`
  steht bei **0/4**, der Port ist ~3x zu gross (938 vs. 274 Blöcke).
- Der **Encoder ist korrekt**: `fine_encoder.py` reproduziert die Orakel-Bytes
  byteweise, wenn man ihm die Orakel-Stage-1 gibt (beide Stufen). **Nicht
  anfassen.**
- Die Fine-**Farbtabelle** `capt` (`transforms.py:51`) ist **richtig** und
  bleibt. Nur mit ihr fehlt die K-Ebene wie im Orakel (CAPT: K=0 bei grau 128,
  0600: K=240 → falsche K-Ebene).
- **Widerlegt** (Verdikt b, `logs/verify_fine.md`): „0600-Screens + binärer
  Quantisierer". Orakel hat die Level 4/10/14, binär kann nur 0/15.
  Auch: `capt` divergiert weniger als `0600` auf der Ganzseiten-Metrik.
- Kein fertiger Code zum Abklauen: der GPL-Referenztreiber (`ref/hl4150/`)
  sagt in seiner README selbst, Fine sei **nicht** byte-identisch. Es gibt
  also upstream keine Lösung — dieses Problem ist echt offen.

## Das Binary

`ref/brhl3040cnfilter.bin` — i386 ELF, **stripped**.

- `objdump` auf diesem Host hat **kein i386-Target** → **capstone** benutzen
  (`CS_ARCH_X86`, `CS_MODE_32`).
- `.text` ist Sektion 12: vaddr `0x8048e48` → Datei-Offset `0xe48`.
  ```python
  def foff(va): return va - 0x8048e48 + 0xe48
  ```
- Bereits gefundene Ankerpunkte:
  | Adresse | was |
  |---|---|
  | `0x804f398` | Stage-1 RLE-Kompressor (`mov byte [ebx],0x17` / `0x1f`) |
  | `0x804f7c8` | Stage-2 Pattern-Encoder |
  | `0x8070b64` | Stage-2 Sprungtabelle, 6 Modi (0..5) |
- Leitfaden für die Fine-Farbstrecke: die Strings `Fine(2400 dpi class)` und
  `Fine` im Binary. Von dort die Referenzen rückwärts verfolgen.
- Der LUT-Ordner im Image: `/opt/brother/Printers/hl3040cn/inf/lut/`
  (24 Dateien; `cache08`, `cache08b`, `capt`, `-TS`).

## Vorgehen

1. Ausgehend von den `Fine`-Strings und der Farbtabellen-Wahl die Funktion
   finden, die den Ink-Wert auf die 4-bpp-Level abbildet.
2. Wenn Phase 1 „Modell A" sagt: die Level-Funktion (Ramp + Screen) exakt
   nachbilden. Wenn „Modell B": die Zeilen-Auswahlregel finden.
3. **Jeden Zwischenschritt gegen das Orakel prüfen**, nicht gegen die eigene
   Erwartung. Das Binary ist die Wahrheit, nicht die Doku.

## Grenzen (hart)

- **Nur lesen/analysieren.** Keine Änderung an `hl3040cn/src/*` in dieser
  Phase — das ist Phase 3. Kein Commit, kein Push.
- Fixtures nach `/mnt/ssd/finecmp`, **nie** `/tmp` (RAM ~40 MB frei).
- Nur **einen** Orakel-Lauf gleichzeitig.
- Der Container `brother-cups` ist **i386 über qemu** — nur für Analyse.
  Die produktive Druck-Pipeline darf davon **nicht** abhängen (Auftrag des
  Nutzers: emulatorfrei).

## Abgabe

`logs/fine_reverse.md` mit:

1. **Der gefundenen Funktion** — als Pseudocode oder Python, so präzise, dass
   Phase 3 sie 1:1 umsetzen kann.
2. **Den Binary-Adressen** und dem Weg dorthin (damit es nachprüfbar ist).
3. **Messung**: per-Ebene-Byte-Zahlen Orakel vs. nachgebildet, für grau 64,
   128, 192. Ziel: Differenz 0.
4. **Was noch fehlt**, falls keine vollständige Byte-Identität erreicht wurde —
   ehrlich, mit Zahlen. Kein „fast fertig".
