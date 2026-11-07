# Performance: was der native Pfad bringt

Gemessen mit `tools/bench_kernels.py`, Median aus N Wiederholungen nach einem
Warm-up. Eingaben synthetisch in **echter Geometrie** (A4 @600 dpi: 4958 px,
620 B/1bpp-Zeile, 128-Zeilen-Baender), Python-Seite = dieselbe Referenz wie im
Aequivalenztest. Zwei Umgebungen, weil die absoluten Zahlen von der CPU
abhaengen — der **Speedup** ist die belastbare Groesse:

* **Odroid N2+** (Cortex-A73/A53, Cython-Kernel) — der Produktivdrucker.
* **GitHub-CI** (x86-64) — die **Rust**-Kernel, wo der Port hin soll.

| kernel | Odroid: py | Odroid: cython | Speedup | CI: py | CI: **rust** | Speedup |
|---|---:|---:|---:|---:|---:|---:|
| `_dither_fast.dither_row_1bpp` | 0.017 ms | 0.029 ms | **0.6x** | 0.003 | 0.004 | **0.6x** |
| `_dither_fast.dither_row_4bpp_pattern` | 0.198 | 0.025 | 7.9x | 0.030 | 0.010 | 3.1x |
| `_color_fast.gather_kcmy` | 1.381 | 0.116 | 12.0x | 0.083 | 0.015 | 5.5x |
| `_color_fast.interp_kcmy` | 6.432 | 0.301 | 21.4x | 1.520 | 0.133 | 11.4x |
| `_rle_fast.group_bits` | 0.092 | 0.017 | 5.5x | 0.021 | 0.007 | 3.0x |
| `_rle_fast.pack_groups` | 0.230 | 0.024 | 9.6x | 0.038 | 0.016 | 2.4x |
| `_rle_fast.encode_sw_rle` | 0.931 | 0.010 | 95.0x | 0.202 | 0.006 | 35.2x |
| `_fine_fast.compress_rle_preencode` | 1.225 | 0.024 | 51.3x | 0.293 | 0.009 | 32.5x |
| `_fine_fast.compress_pattern_encode` | 4.453 | 0.043 | 102.9x | 1.312 | 0.020 | 65.9x |
| `_band_fast.render_band` | 15.034 | 0.447 | 33.6x | 2.281 | 0.154 | 14.8x |

## Was das heisst

* **Die Band-Engine ist der Hebel.** `render_band` ist der teuerste Kernel
  (pro Band: Farbe, Dither, RLE fuer 4 Ebenen). 33.6x / 14.8x heisst: aus
  15 ms Python werden 0.45 ms — das ist der Unterschied, den man auf einer
  vollen Seite merkt.
* **Rust vs Cython:** vergleichbare Groessenordnung, Rust meist etwas
  schneller (Band 0.154 vs 0.447 ms, `pack_groups` 0.016 vs 0.024). Beide
  sind nativer Code; der Port ist **kein** Geschwindigkeitswunder, sondern
  eine Modernisierung mit **vergleichbarer** Performance. Wer „viel
  schneller als Cython" behauptet, luegt.
* **`dither_row_1bpp` ist ehrlich langsamer (0.6x).** Die Python-Seite ist
  ein einzelner `np.packbits`-Aufruf; der Kernel zahlt den
  Python<->Rust-Aufrufoverhead und kann das nicht wettmachen. Der Fall ist
  mit ~0.02 ms ohnehin irrelevant — **kein Grund zur Aenderung**.
* **Absolute Zeit dominiert die Renderphase**, nicht die Kernel. Bei ~4.5 M
  Pixeln/Seite und ~0.15 ms/Band bleibt die Gesamtzeit von der
  Python-Orchestrierung und Ghostscript bestimmt. Die Kernel sind
  inzwischen zu vernachlaessigen.

## Reproduzieren

```
PYTHONPATH=/usr/local/lib/brhl3040cn:. python3 tools/bench_kernels.py   # Cython
python3 tools/bench_kernels.py                                          # Rust (nach Build)
python3 tools/bench_kernels.py --json                                   # Rohwerte
```

In der CI laeuft der Benchmark als Schritt „Kernel benchmark" im Workflow
`rust-kernels.yml`, direkt nach der vollen Suite.
