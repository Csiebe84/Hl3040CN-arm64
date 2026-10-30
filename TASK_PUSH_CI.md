# Auftrag: Privates GitHub-Repo aktuell halten + CI ehrlich grün

## Ziel in einem Satz

Den verifizierten Stand von `/root/brother/native` ins **private** Repo
`Csiebe84/Hl3040CN-arm64` pushen und dabei **ehrlich** belegen, dass CI auch
**ohne** die proprietären Blobs grün ist.

## Stand jetzt (gemessen, nicht geschätzt)

```
origin        https://github.com/Csiebe84/Hl3040CN-arm64.git   (PRIVATE)
lokal         99516c9   (Fine dither: read levels from BRCD patterns …)
origin/master b12267a
unpushed      1 Commit
letzter CI    b12267a  completed  success
```

**Token-Falle — wichtig, sonst 404:** `$GITHUB_TOKEN` in dieser Umgebung gehört
dem Account **`christiansiebe`** und sieht `Csiebe84/Hl3040CN-arm64` **nicht**
(HTTP 404). Das **richtige** Token liegt in `~/.gh_token` (Modus 600) und gehört
**`Csiebe84`**. Immer so lesen:

```bash
T=$(cat ~/.gh_token | tr -d '\n\r ')
curl -s -H "Authorization: Bearer $T" \
  https://api.github.com/repos/Csiebe84/Hl3040CN-arm64 | head -c 200
```

`publish.sh --check` benutzt dasselbe Token und ist der bequemste Vorab-Test
(er ändert nichts).

## Aufgabe 1 — CI ohne Blobs ehrlich reproduzieren

`hl3040cn/src/lut/` und `hl3040cn/src/color_data/` existieren lokal und
**verdecken** einen CI-Fehler. Reproduziere CI sauber:

```bash
TMP=$(mktemp -d)
git archive HEAD | tar -x -C "$TMP"
rm -rf "$TMP/hl3040cn/src/lut" "$TMP/hl3040cn/src/color_data"
cd "$TMP/hl3040cn/src" && python3 -m unittest discover -p 'test_*.py'
```

Berichte **ehrlich**, welche Tests skippen und welche **fehlschlagen**. Wenn
einer fehlschlägt: den fehlenden Skip-Guard ergänzen im vorhandenen Stil
(`@require_blobs(...)` aus `test_blobs.py`, oder
`@unittest.skipUnless(pipeline.HAS_BAND_KERNEL, ...)`). **Den Guard fixen, nicht
die Testbedeutung.**

## Aufgabe 2 — Push

1. Vor dem Push: `git status` prüfen. **Nicht** committen/pushen:
   - `logs/`, `samples/`, `*.xl2hb`, `*.ppm`, `.venv312/` (sind gitignored)
   - `hl3040cn/src/lut/`, `hl3040cn/src/color_data/` (proprietär, gitignored)
   - **nichts** aus `backup-quality-20261026-231248/`
2. Push über die Remote-URL mit dem `~/.gh_token`-Token (nie in `.git/config`
   schreiben, nie in die History):

```bash
T=$(cat ~/.gh_token | tr -d '\n\r ')
git push "https://Csiebe84:${T}@github.com/Csiebe84/Hl3040CN-arm64.git" master
```

3. Danach verifizieren: `origin/master` == lokal, und der neue CI-Lauf ist
   `success`:

```bash
curl -s -H "Authorization: Bearer $T" \
  "https://api.github.com/repos/Csiebe84/Hl3040CN-arm64/actions/runs?per_page=3" \
  | python3 -c "import json,sys;[print(r['head_sha'][:8],r['status'],r.get('conclusion')) for r in json.load(sys.stdin)['workflow_runs']]"
```

## Was **nicht** anzufassen ist

- `hl3040cn/src/dither.py`, `hl3040cn/src/pipeline.py`: bereits committet
  (`99516c9`). Falls sie **wieder** uncommittet sind, gehören sie einem anderen
  Agenten (Fine-Dehnung) — **nicht** committen.
- `TASK_*.md` und `tools/graytol_*.py` (37) / `tools/grid_*.py` (11): Analyse-
  Werkzeuge. Nur committen, wenn sie für den Treiber nötig sind — vorher fragen,
  nicht in Massen hochladen.
- Keine Neustarts von agent-server/HA.

## Grenzen (hart)

- **Privat halten.** Nicht auf public stellen.
- **Keine Secrets pushen.** Vor dem Push: `git diff --cached --stat` und nach
  `~/.gh_token`, `api_key`, `Bearer`, `password` in den gestagten Diffs greppen.
  Die BRCD-LUTs und `color_data/` sind absichtlich draußen (proprietär).
- **Keine Ziele fälschen.** Wenn CI rot ist, den Fehler berichten und den Guard
  fixen — keinen Test abschwächen, kein `continue-on-error`.

## Ergebnis

Bericht nach `logs/ci_push.md`: Push-SHA, CI-Ergebnis (mit Blobs und ohne),
Liste der geskippten Tests, etwaige Guard-Fixes. Danach fertig.
