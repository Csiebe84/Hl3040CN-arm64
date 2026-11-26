# Auftrag: Unabhängige Verifikation der Fine-Pattern-Dither-Behauptung

## Warum diese Aufgabe existiert

In diesem Projekt wurde **schon einmal** eine falsche „byte-identisch“-Behauptung
aufgestellt und von einer unabhängigen Messung widerlegt (`FINE_HANDOVER.md` §8,
`logs/verify_fine.md`, Verdikt b). Der Code wurde daraufhin zurückgerollt.

Gerade wurde erneut eine solche Behauptung committet (**`99516c9`**). Sie muss
**adversarial** geprüft werden — mit dem Ziel, sie zu **widerlegen**, nicht zu
bestätigen.

## Die zu prüfende Behauptung (wörtlich aus dem Commit)

> Die Pattern-Dither-Strecke (`dither_channel_4bpp_pattern_arr`) ist für die
> **C- und M-Ebene** byte-identisch zum Brother-Filter auf einer ganzseitigen
> grau-128-Seite (**6564/6564 Zeilen je Ebene**). Nur die **Y-Ebene** weicht ab,
> und zwar nur auf Zeilen mit Zwischenleveln.

Teilbehauptungen:
1. C: 6564/6564 Zeilen identisch.
2. M: 6564/6564 Zeilen identisch.
3. Y: 5470/6564; abweichend `y≡4` und `y≡10` (mod 12).
4. grau 192 (Y ink=32): abweichend `y≡2` und `y≡8` (mod 12).
5. grau 64 (Y ink=79): 6564/6564, **keine** Abweichung.
6. Die Abweichung ist **keine** Level-Transformation (weder `+8`, noch Modulo,
   noch Nibble-Tausch) — sie ist eine **4/3-Dehnung vor** dem Dither-Zugriff.

## Wie geprüft wird — Vorgaben

- **Zuerst den Test schreiben, der scheitern MUSS, wenn die Behauptung falsch
  ist.** Nicht die Implementierung als Wahrheit nehmen.
- **Unabhängige Quelle:** das echte Brother-Orakel
  `/mnt/ssd/finecmp/s128_fine.xl2hb` (+ `g192_fine.xl2hb`, `g64_fine.xl2hb`).
  **Nicht** die Port-Ausgabe gegen sich selbst vergleichen.
- **Eigene Werkzeugkette bauen**, nicht die vorhandene kopieren. Wenn du
  `verify_stage1.py` benutzt: **lies es zuerst** und prüfe, ob es die Behauptung
  überhaupt testet (es nutzt `s1model.forward` + `dither_channel_4bpp_pattern_arr`
  — also **denselben** Code wie die Behauptung. Das ist ein Zirkelschluss und
  **kein** unabhängiger Beweis). Ein echter Test dekodiert das Orakel **und**
  vergleicht gegen eine vom Port unabhängige Rekonstruktion.
- **Gegenprobe einbauen:** eine bewusst falsche Variante (z. B. `0600-y` statt
  `capt-y`, oder `+8`-Verschiebung) muss **auffallen**. Wenn dein Test sie
  durchwinkt, testet er nichts.
- **Die Testsuite ansehen:** wurde `hl3040cn/src/test_fine_mode.py` in `99516c9`
  so geändert, dass sie die Behauptung nur noch bestätigt (z. B. `assertEqual`
  statt `assertNotEqual`, Konstanten auf die Implementierung gezogen)? Wenn ja:
  das ist ein Befund, auch wenn die Zahlen stimmen.

## Umgebung

- Repo `/root/brother/native`, Python `/root/brother/native/.venv312/bin/python`.
- Orakel + Werkzeuge in `/mnt/ssd/finecmp/` (`s1inv6.py`, `s1model.py`,
  `s128_levels_cache.json`, `verify_stage1.py`, `rev_dither.py`).
- Tests laufen aus `hl3040cn/src` (`python3 -m unittest`).

## Grenzen (hart)

- **Nur lesend messen.** Keine Änderung an `hl3040cn/src/**` — wenn du etwas
  ändern willst, schreib es in den Bericht als Vorschlag.
- **Kein Druckauftrag.** Test nur gegen Datei-Backend (`HL3040_TEST` ->
  `/tmp/e2e_out.prn`), nie gegen den echten Drucker.
- **Keine Neustarts** von agent-server/HA.
- **Speicher ist knapp** (3,7 GB): kein ganzseitiges numpy mehrfach parallel
  halten, `nice -n 19`, keine `-j2`-Builds.
- **Nicht schönreden.** Wenn die Zahlen stimmen, sag das — aber nenne die
  Schwäche des Beweises (Zirkelschluss, falls vorhanden). Wenn sie nicht
  stimmen, sag das mit Messwerten.

## Verdikt-Format (wie `logs/verify_fine.md`)

Genau eine der drei Antworten, mit Konfidenz und Messwerten:

- **(a) Behauptung bestätigt** — und warum der Beweis nicht zirkulär ist.
- **(b) Behauptung falsch** — mit der Zahl, die nicht stimmt.
- **(c) Nicht entscheidbar** — und was fehlt.

## Ergebnis

Bericht nach `logs/verify_fine4.md`: Verdikt, Messmethode, Rohzahlen,
Gegenprobe, Testsuite-Bewertung, Restrisiko. **Nichts committen** — nur berichten.
