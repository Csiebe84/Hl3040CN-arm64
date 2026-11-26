# Phase 4 — Adversariale Verifikation des Fine-Fixes

Repo `/root/brother/native`. Deine Aufgabe ist **nicht**, die Arbeit zu
bestätigen, sondern sie zu **widerlegen**. Suche aktiv nach Gegenbeweisen.

## Kontext

Phase 3 (Agent C, `logs/fine_reverse.md`, `TASK_FINE_IMPL.md`) hat den
Fine-Dither umgestellt: der Level eines Pixels ist jetzt das **Low-Nibble des
BRCD-Pattern-Bytes** statt einer 1-bpp-Schwellwertmatrix.

Geänderte Dateien: `hl3040cn/src/dither.py`, `hl3040cn/src/pipeline.py`.
Neue Funktion: `dither_channel_4bpp_pattern_arr`; `_DITHER_FNS[True]` zeigt
jetzt darauf.

Die Orchestrierung hat folgende Behauptungen selbst gemessen und gibt sie dir
als **zu prüfende** Aussagen (nicht als Wahrheit):

1. Grau 64 (BRGray=OFF, Fine): alle vier Ebenen C/M/Y/K sind **byte-identisch**
   zur Orakel-Stage-1 (je 6564 Zeilen).
2. Grau 128/192 (OFF): C, M, K byte-identisch; Y weicht ab.
3. **Live-Konfiguration (BRGray=ON), Vollton grau 128, Fine:** der gesamte
   PCL-XL-Body (nach dem `XL2HB`-Zeilenende) ist **byte-identisch**
   (1 034 547 B). Unterschied nur im PJL-Vorspann (230 B: `@PJL JOB NAME`,
   `PRINTLOG ITEM = 2,<Zeitstempel>`).
4. Der **Normal-Pfad** (`is_fine=False`) ist unverändert.

## Was du tun sollst

Prüfe jede Aussage **unabhängig** nach und versuche sie zu brechen:

- Baue die Vergleiche selbst neu auf, nicht aus den Harnessen der Vorgänger
  (`/mnt/ssd/finecmp/rev_dither.py`, `verify_stage1.py` sind **Referenz**, nicht
  Beweis — prüfe, ob sie selbst korrekt sind, insbesondere die
  `pageW=5104`-Annahme und ob `rgb_to_cmyk_ink` die richtige Tabelle nutzt).
- Prüfe Aussage 3 besonders kritisch: ist der "Body" wirklich nach dem
  `XL2HB`-Marker geschnitten, oder verschiebt der Schnitt nur die Differenz?
  Vergleiche **roh** (ohne jede Normalisierung) und benenne die exakten
  abweichenden Byte-Offsets.
- Prüfe Aussage 4: erzeuge für **Normal** eine Rampe gegen das Orakel und
  vergleiche **vorher/nachher** (`git stash` / `git show HEAD:hl3040cn/src/dither.py`).
  Eine Regression im Normal-Pfad wäre ein Blocker.
- Prüfe, ob die neue Funktion bei **Randfällen** korrekt ist: Breite nicht
  durch 8 teilbar, `width > sw` (Padding), Ink außerhalb 0..255, y außerhalb
  des Screens, leere Ebene. Wo fällt sie auf den Threshold-Pfad zurück und ist
  das dort richtig?
- Prüfe die behauptete **Plane-Presence** (K-Ebene bei Ink 0 weggelassen)
  gegen das Orakel — nicht gegen den Port.
- **Zähle ehrlich**: wie viele Zeilen/Prozent weichen im ON-Ramp ab, und sind
  es die in `logs/fine_reverse.md` §4 genannten Y-Zwischenlevel oder mehr?

## Regeln

- **Nichts ändern** an `hl3040cn/src/*` — nur lesen und messen. Wenn du einen
  Fehler findest, dokumentiere ihn, statt ihn zu beheben.
- Fixtures nach `/mnt/ssd/finecmp`, **nie** `/tmp`.
- Nur **ein** Orakel-Lauf gleichzeitig (RAM ~3,8 GB total, knapp).
- Testsuite laufen lassen: `.venv312/bin/python -m unittest discover -s hl3040cn/src -t hl3040cn/src`
- Kein Commit, kein Push.

## Abgabe

`logs/fine_verify3.md` mit:
- je Behauptung 1–4: **bestätigt / widerlegt / teilweise**, mit den rohen
  Zahlen und dem Befehl, der sie erzeugt.
- einer Liste **jeder** Abweichung, die du gefunden hast, mit Byte-Offset und
  Kontext (hex).
- einer klaren Aussage, ob der Fix **druckreif** ist oder nicht — und wenn
  nicht, was genau fehlt.
