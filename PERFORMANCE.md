# Performance: was der native Pfad bringt

Gemessen mit `tools/bench_kernels.py`, Warm-up 2 Laeufe, dann **Median** aus N
Wiederholungen. Eingaben synthetisch in **echter Geometrie** (A4 @600 dpi:
4958 px Quellbreite, 620 B/1bpp-Zeile, 128-Zeilen-Baender = `pipeline._BAND_ROWS`,
BRCD-Pattern 96x12), Python-Seite = dieselbe Referenz wie im Aequivalenztest.
Weil die absoluten Zeiten von der CPU abhaengen, ist der **Speedup** die
belastbare Groesse. Zwei Umgebungen:

* **Odroid N2+** (Cortex-A73/A53) mit den **Cython**-Kerneln — der
  Produktivdrucker.
* **GitHub-CI** (x86-64) mit den **Rust**-Kerneln — wo der Port hin soll.

| kernel | Odroid: py | Odroid: cython | Speedup | CI: py | CI: **rust** | Speedup |
|---|---:|---:|---:|---:|---:|---:|
| `_rle_fast.group_bits` | 11.605 ms | 2.404 ms | 4.8x | 3.041 | 0.685 | 4.4x |
| `_rle_fast.pack_groups` | 9.322 | 0.644 | 14.5x | 2.569 | 1.031 | 2.5x |
| `_rle_fast.encode_sw_rle` | 1.017 | 0.010 | 102.5x | 0.178 | 0.004 | 48.6x |
| `_dither_fast.dither_row_1bpp` | 2.453 | 3.979 | **0.6x** | 0.281 | 2.564 | **0.1x** |
| `_dither_fast.dither_row_4bpp_pattern` | 21.644 | 3.164 | 6.8x | 4.022 | 1.065 | 3.8x |
| `_color_fast.gather_kcmy` | 1.456 | 0.664 | 2.2x | 0.062 | 0.018 | 3.4x |
| `_color_fast.interp_kcmy` | 6.771 | 0.325 | 20.8x | 1.412 | 0.091 | 15.5x |
| `_band_fast.render_band` | 50.418 | 3.637 | 13.9x | 10.181 | 2.018 | 5.0x |
| `_fine_fast.compress_rle_preencode` | 1.182 | 0.023 | 50.6x | 0.267 | 0.010 | 26.4x |
| `_fine_fast.compress_pattern_encode` | 4.491 | 0.044 | 103.1x | 0.979 | 0.016 | 61.0x |

(Zeiten gelten fuer den jeweiligen **Batch**: 128 Zeilen bei den Zeilen-Kerneln,
ein 128-Zeilen-Band bei `render_band`.)

## Was das heisst

* **Die Band-Engine ist der Hebel.** `render_band` ist der teuerste Kernel
  (pro Band: Farbe, Dither, RLE fuer 4 Ebenen). 13.9x heisst: aus 50 ms
  Python werden 3.6 ms — das ist der Unterschied, den man auf einer vollen
  Seite merkt.
* **Rust vs Cython:** vergleichbare Groessenordnung, beide nativer Code. Der
  Port ist **kein** Geschwindigkeitswunder, sondern eine Modernisierung mit
  **vergleichbarer** Performance. Wer „viel schneller als Cython" behauptet,
  luegt.
* **`dither_row_1bpp` ist ehrlich langsamer** (0.6x auf ARM, 0.1x auf x86).
  Die Python-Seite ist `np.packbits`, vektorisiert/SIMD; der Kernel ist eine
  skalare Pixel-Schleife und zahlt zusaetzlich den Python<->native-Aufruf.
  Direktmessung: `np.packbits` allein 7 us, die volle Referenz 17 us,
  Cython 29 us pro Zeile. Der Fall ist mit ~0.02 ms/Zeile ohnehin
  **vernachlaessigbar** — **kein Grund zur Aenderung**, aber auch kein
  Schoenreden.
* **Absolute Zeit dominiert die Renderphase**, nicht die Kernel. Bei ~4.5 M
  Pixeln/Seite bleiben Gesamtzeit und Speicher von Python-Orchestrierung und
  Ghostscript bestimmt; die Kernel sind inzwischen zu vernachlaessigen.

## Reproduzieren

```
PYTHONPATH=/usr/local/lib/brhl3040cn:. python3 tools/bench_kernels.py   # Cython
python3 tools/bench_kernels.py                                          # Rust (nach Build)
python3 tools/bench_kernels.py --json                                   # Rohwerte
```

Ohne importierbare Kernel bricht das Skript **nicht** ab: es meldet
„no native kernels importable" und endet mit Exit 0, damit der reine
Python-CI-Job gruen bleibt. In der CI laeuft der Benchmark als Schritt
„Kernel benchmark" im Workflow `rust-kernels.yml`, direkt nach der Suite.
