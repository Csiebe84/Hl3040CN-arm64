# Auftrag: Fine-Modus — die 4/3-Dehnung der Y-Zwischenlevel-Zeilen

## Ziel in einem Satz

Die **letzte** byte-identische Lücke schließen: `capt-y`-Dither-Zeilen mit
Zwischenleveln müssen **4/3 gedehnt** werden (2552 → ~3402 B), bevor Stage 1
läuft. Danach ist Fine für grau 128 und grau 192 vollständig byte-identisch
(6564/6564 je Ebene).

## Was bereits bewiesen ist — NICHT neu herleiten

Gemessen gegen das echte Brother-Orakel `s128_fine.xl2hb` (grau 128, Letter),
Port-Funktion `dither_channel_4bpp_pattern_arr` + `s1model.forward`:

| Ebene | Zeilen identisch | Abweichung |
|---|---|---|
| **C** | **6564/6564** | keine |
| **M** | **6564/6564** | keine |
| Y | 5470/6564 | 1094 Zeilen, `y≡4` und `y≡10` (mod 12) |
| K | (Orakel hat bei grau 128 keine K-Ebene) | Ebenen-Präsenz getrennt geregelt |

Abweichungsmuster ist **exakt** und **ink-abhängig**:

```
grau128  Y ink=64: 5470/6564, abweichend mod 12 = {4: 547, 10: 547}
grau192  Y ink=32: 5470/6564, abweichend mod 12 = {2: 547,  8: 547}
grau64   Y ink=79: 6564/6564  (keine Zwischenlevel -> keine Abweichung)
```

Die betroffenen Zeilen sind **genau** die mit Zwischenleveln. Der Orakel-Preimage
dieser Zeilen ist **3402 B = 2552 × 4/3** (+2 B Pad); der Port emittiert 2552 B.
Dadurch landet der Level **8 zu niedrig** (4 statt 12):

```
Orakel stage-1: a5 47 a9 47 ad 47 a9 47 ad 47 a9 47 ad 47 …
Port   stage-1: a5 47 a1 47 a5 47 a1 47 a5 47 a1 47 a5 47 …
```

## Bereits ausgeschlossen — nicht wieder versuchen

- **Falsche Y-Tabelle:** alle vier geprüft. `capt-y` ist mit 5470/6564 klar am
  besten; `capt-y-TS` 2188/6564; `0600-y` und `0600-y-TS` **0/6564**. `capt-y`
  ist die richtige Tabelle.
- **Level-Transformation allein:** `unverändert`, `+8 clamp15`, `+8 mod16`,
  Nibble-Swap, High-Nibble — **alle nein**. Die Dehnung liegt **vor** dem
  Dither-Zugriff, nicht danach.
- **Phasen-/Indexfehler:** kein Screen-Zyklus `ry` (0..11) und kein Ink-Wert
  (0..255) erzeugt die Orakel-Zeile. Es ist keine Verschiebung, sondern eine
  andere Zeilenlänge.
- **Encoder:** Stage 2 ist byte-identisch; Stage 1 stimmt auf allen
  Nicht-Sonderzeilen.

## Die entscheidende Spur (aus `logs/fine_reverse.md` §4b)

Lauf-Struktur des Orakel-Preimages für y=4 (6804 Nibbles = 5100 × 4/3):

```
00 C 00 F 0000 4 00 F 0000 C 00 F 0000 4 00 F …   (16er-Periode)
```

Die Orakel-Version nutzt **dieselben Level-Komponenten** (C/F/4/F) wie die
12er-Port-Zeile, aber in **16er-Periodik**. Die Dehnung fügt also Null-Nibbles
ein, sie erfindet keine neuen Level.

**Geometrie-Hinweis (prüfen, nicht annehmen):** `capt-y` ist **96×12**
(12 Byte/Zeile), `capt-c`/`capt-m` sind **160×20**. K hat **dieselbe** Geometrie
wie Y (96×12). Wenn die Dehnung an der Screen-Geometrie hängt, muss die **K-Ebene
dasselbe** zeigen — gegen `black_fine_tsON.xl2hb` / `black_fine_tsOFF.xl2hb`
prüfen. Wenn K nicht gedehnt ist, hängt es an der Ink-Zahl, nicht an der Breite.

## Vorgehen (Vorschlag, eigene Messung schlägt Vorschlag)

1. Orakel-Zeile y=4 mit `s1inv6.invert` zu den Dither-Nibbles invertieren
   (Preimages liegen im Cache `/mnt/ssd/finecmp/s128_levels_cache.json`, Keys
   `a547a947…` / `a147a947…`; Wiederholung ist damit sekundenschnell).
2. Die 16er-Position auf die 12er-Port-Zeile abbilden und die Einfügeregel
   ableiten (welche Nibbles sind Füllung, wie hängt die Phase von `y` ab).
3. In `hl3040cn/src/dither.py` / `pipeline.py` implementieren.
4. Beweisen: **Y 6564/6564** für grau 128 **und** grau 192, **C und M weiter
   byte-identisch**, grau 64 unverändert.
5. Regressionstest in `hl3040cn/src/test_fine_mode.py` ergänzen.

## Beweis-Kommando (reproduzierbar, ~1 min)

```bash
cd /mnt/ssd/finecmp
cat > /tmp/portval.py <<'PY'
import sys, importlib.util
from pathlib import Path
from collections import Counter
import numpy as np
FIX=Path('/mnt/ssd/finecmp'); HERE=Path('/root/brother/native')
for p in (str(FIX),str(HERE/'src'),str(HERE/'hl3040cn'/'src'),str(HERE/'tools')): sys.path.insert(0,p)
from fine_decode import decode_stage2
import pclxl, band
spec=importlib.util.spec_from_file_location('s1model',str(FIX/'s1model.py'))
s1=importlib.util.module_from_spec(spec); spec.loader.exec_module(s1)
from rev_dither import rgb_to_cmyk_ink
from dither import load_dither_tables, dither_channel_4bpp_pattern_arr
blob=(FIX/'s128_fine.xl2hb').read_bytes()
orac={}
for b in band.decode_blocks(pclxl.parse(blob)):
    orac.setdefault(b.plane_name,{})
    for k,e in enumerate(b.entries): orac[b.plane_name][b.start_line+k]=decode_stage2(e)
ch=load_dither_tables(str(HERE/'hl3040cn/src/lut'),fine=True,toner_save=False)
C,M,Y,K=rgb_to_cmyk_ink(128); ink={"K":K,"C":C,"M":M,"Y":Y}
for pn in "KCMY":
    rd=orac.get(pn,{})
    if not rd: print(f"  {pn}: Orakel hat keine Ebene"); continue
    ok=0; bad=[]
    for y in sorted(rd):
        row=np.full(5100,255-ink[pn],np.uint8)
        d=dither_channel_4bpp_pattern_arr(row,y,5100,ch[pn])+b"\x00\x00"
        if s1.forward(d)==rd[y]: ok+=1
        else: bad.append(y)
    m=Counter(y%12 for y in bad)
    print(f"  {pn}: {ok}/{len(rd)}", f"abw mod12={dict(sorted(m.items()))}" if bad else "IDENTISCH")
PY
/root/brother/native/.venv312/bin/python /tmp/portval.py
```

Erwartet **nach** dem Fix: `C/M/Y` alle `6564/6564 IDENTISCH`.

## Grenzen (hart)

- **Kein Druckauftrag** (Papierverbrauch). Test nur gegen Datei-Backend
  (`HL3040_TEST` -> `/tmp/e2e_out.prn`), nie gegen den echten Drucker.
- **Keine Neustarts** von agent-server/HA.
- **Speicher ist knapp** (3,7 GB, ~0,8 GB frei): keine `-j2`-Builds, kein
  paralleles numpy über ganze Seiten; `nice -n 19`. Ein `-j2`-Kernel-Build hat
  das Board schon einmal hart resettet.
- **Keine Ziele fälschen.** Wenn die Dehnung nicht vollständig aufgeht, den
  exakten Stand berichten (z. B. 3/4 Ebenen identisch) — keine Testabschwächung,
  kein `assertEqual` an die Implementierung anpassen.
- Tests müssen aus `hl3040cn/src` laufen (`python3 -m unittest`).

## Ergebnis

Bericht nach `logs/fine_stretch.md`: Regel, Messung, Rest-Fehler (falls einer
bleibt), Reproduktion. Danach committen (nicht pushen — das macht ein anderer
Agent).
