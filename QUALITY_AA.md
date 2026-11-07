# Qualität: ist mehr als "byte-identisch zum Original" möglich?

Stand 2026-11-01, Branch `feat/rust-kernels`. Messungen auf dem Odroid N2+
(gs 10.00.0), Testseite `reference/refsheet.ps` (A4, 4958x6981 px @600 dpi).

## Ausgangslage

Der Treiber ist **byte-identisch** zu Brothers `psconvertij2` (79 503 B
XL2HB). Das ist der Beweis, dass wir nichts kaputt machen — aber es ist
kein Beweis, dass Brothers Ausgabe *optimal* ist. Brothers Filter ist ein
i386-Binary, das Ghostscript mit festen Flags aufruft; daran ist nichts
heilig.

## Wo Spielraum ist (und wo nicht)

| Hebel | Befund |
|---|---|
| **Ghostscript-Antialiasing** | **Nicht gesetzt.** Der Filter ruft `gs` ohne `-dTextAlphaBits`/`-dGraphicsAlphaBits` auf (`cups/brhl3040cn-filter`, `build_gs_command`). Text und Grafik werden hart, treppig gerastert. |
| Rasterauflösung | `-r600` ist **richtig**: Fine ist 600 dpi Raster + 4bpp-Level-Dither (16 Stufen/Pixel), der Drucker macht daraus die "2400 dpi class". Mit 2400 dpi zu rastern wäre 16x Datenmenge und ein anderer Bytstream — **nicht** anfassen. |
| Farbseparation | Offen, liegt im Python-Code (`color_lut.py`). Der Rust-Port berührt sie nicht. |
| Dither/Band/RLE-Encoder | Byte-exakt zum Oracle; jede Änderung wäre eine Verhaltensänderung, kein "Fix". |

Der einzige saubere, risikolose Hebel ist also **Antialiasing**.

## Messung (warum AA die Qualität hebt)

`ppmraw`-Ausgabe mit und ohne `-dTextAlphaBits=4 -dGraphicsAlphaBits=4`,
Pixel für Pixel verglichen:

```
geaenderte Pixel: 201 054 / 34 611 798 = 0.58 %
max Aenderung (einkanalig): 255
Pixel mit Summe >8: 179 419 (0.518 %)
```

0.58 % der Pixel ändern sich, aber mit **großer Amplitude** — das sind
ausschließlich die Kanten. Genau die Treppenstufen an Buchstaben und
Grafikkanten, die bei 600 dpi hart sichtbar sind. Der Rest der Seite ist
identisch.

Kosten:

```
ohne AA: 0.319 s real   (0.222 s user)
mit  AA: 0.393 s real   (0.324 s user)   -> +23 % gs-Zeit
```

Auf dieser leichten Testseite ~74 ms. Bei einer dichten Textseite mehr,
aber es bleibt ein Bruchteil der Gesamt-Jobzeit (die Python-Renderphase
dominiert).

## Vorschlag (Nutzer-Entscheid nötig)

`-dTextAlphaBits=4 -dGraphicsAlphaBits=4` in `build_gs_command` ergänzen —
**opt-in** über eine PPD-Option oder RC-Variable, nicht als harter
Default:

* Vorteil: sichtbar glatterer Text und glattere Kanten, näher an dem, was
  ein moderner Druckertreiber liefert. Der Treiber wird damit **besser als
  das Original**, ohne die Kompatibilität zu brechen (AA ist ein reiner
  Raster-Vorverarbeitungsschritt, der Bytstream bleibt gültiges XL2HB).
* Kosten: ~+20 % gs-Zeit, minimal mehr Toner an Kanten.
* Warum opt-in: es **bricht die Byte-Identität** zum Oracle. Der
  Byte-Identitäts-Beweis ist wertvoll und soll der Default bleiben; wer
  schärfer will, schaltet es zu.

Umsetzung wäre **Python/Filter-Code** (`cups/brhl3040cn-filter`) — der ist
laut Projektvorgabe unangetastet zu lassen, also erst nach Freigabe.
