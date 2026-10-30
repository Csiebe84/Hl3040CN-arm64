# Übergabe 2026-10-29 — alle offenen Arbeiten delegiert

Nach dem Stand-Check wurden **alle offenen Treiber-Arbeiten** an eigene Agenten
gegeben. Jeder hat eine Auftragsdatei mit Beweislage, Ausschlussliste und
Beweis-Kommando; keiner muss etwas neu herleiten.

| Agent | Auftrag | Datei | Ziel |
|---|---|---|---|
| `f734bb51` | Fine: Y-Zwischenlevel **4/3 dehnen** | `TASK_FINE_STRETCH.md` | Y 6564/6564 bei grau 128 + 192 |
| `ea4fbe72` | Privates Repo pushen, **CI ohne Blobs** ehrlich grün | `TASK_PUSH_CI.md` | Push + grüner CI-Lauf |
| `414b0c57` | **Adversariale** Prüfung der Dither-Behauptung | `TASK_VERIFY_FINE4.md` | Verdikt a/b/c |

## Warum genau diese drei — und sonst nichts

Der Stand-Check ergab, dass **die meisten alten Task-Dateien erledigt oder
überholt** sind. Deshalb wurden sie **nicht** erneut vergeben:

| Aufgabe | Stand (geprüft, nicht aus der Datei übernommen) |
|---|---|
| `TASK_C_EXECUTE` / `TASK_C_EMULATOR` | **erledigt** — `/usr/lib/cups/filter/brhl3040cn-filter` ist ein 283-B-Python-Wrapper, **keine** qemu-/i386-Referenz im Filter oder in `hl3040cn/src` |
| `TASK_CI_GREEN` | **erledigt** — letzter CI-Lauf `b12267a` = `success` |
| `TASK_CI_PUSH` | **abgelöst** durch `TASK_PUSH_CI.md` (Token-Falle dokumentiert, Blob-Reproduktion präzisiert) |
| `TASK_MOPRIA` / `TASK_MOPRIA2` | **geklärt** — Ursache ist der **ausgeschaltete Drucker** (`NewActive=0`, keine Antwort auf 80/515/631/9100). Server-Seite nachweislich intakt, 7 Hypothesen widerlegt. Kein Code-Fix möglich. |
| `TASK_FINE_HARDENING` / `TASK_FINE_INKLEVELS` | **überholt** — selbst als „widerlegt, nicht bearbeiten“ markiert (`FINE_HANDOVER.md` §8) |
| `TASK_FINE_LEVELS` (Phase 1) / `TASK_FINE_REVERSE` (Phase 2) | **erledigt** — Verdikt Modell A, Dither-Funktion bei `0x804ed38` gefunden, C/M byte-identisch |
| `TASK_FINE_IMPL` (Phase 3) | **abgelöst** durch `TASK_FINE_STRETCH.md` — die offene Restfrage ist genau die Y-Dehnung |
| `TASK_VERIFY_FINE` / `TASK_VERIFY_FINE3` | **abgelöst** durch `TASK_VERIFY_FINE4.md` (prüft den **neuen** Commit `99516c9`) |
| `1c139beb` (3×-Druck + Verlauf) | **läuft noch** — 3×-Druck ist als extern (Mopria) eingegrenzt, nicht Treiber |

## Der Kern der verbleibenden Arbeit

**Nur eine** echte Treiber-Lücke ist offen: die Y-Ebene weicht auf Zeilen mit
Zwischenleveln ab, weil das Orakel diese Zeilen **4/3 gedehnt** (2552 → 3402 B)
**vor** dem Dither-Zugriff erzeugt. C und M sind byte-identisch (6564/6564).

Die Y-Dehnung (`f734bb51`) und ihre unabhängige Prüfung (`414b0c57`) sind
bewusst **getrennt** vergeben: dieses Projekt hat schon einmal eine falsche
„byte-identisch“-Behauptung produziert, die eine unabhängige Messung widerlegte.
Deshalb prüft `414b0c57` adversarial gegen das Orakel und benennt den
**Zirkelschluss** in `verify_stage1.py` (nutzt dieselbe Port-Funktion wie die
Behauptung — das ist kein unabhängiger Beweis).

## Gemeinsame harte Grenzen (in jeder Auftragsdatei)

- **Kein Druckauftrag** (Papierverbrauch) — Test nur gegen Datei-Backend
  `HL3040_TEST` -> `/tmp/e2e_out.prn`.
- **Keine Neustarts** von agent-server/HA.
- **Speicher knapp** (3,7 GB, ~0,8 GB frei): kein `-j2`, `nice -n 19` — ein
  `-j2`-Kernel-Build hat das Board schon einmal hart resettet.
- **Keine Ziele fälschen** — bei unvollständigem Ergebnis den exakten Stand
  melden, keine Testabschwächung.

## Token-Falle (in `TASK_PUSH_CI.md` dokumentiert)

`$GITHUB_TOKEN` gehört **`christiansiebe`** und sieht `Csiebe84/Hl3040CN-arm64`
**nicht** (HTTP 404). Das richtige Token liegt in **`~/.gh_token`** (Modus 600)
und gehört `Csiebe84`. `publish.sh --check` bestätigt das.

## Berichte (entstehen beim Lauf)

- `logs/fine_stretch.md` — Dehnungsregel, Messung, Restfehler
- `logs/ci_push.md` — Push-SHA, CI mit/ohne Blobs, Skip-Liste
- `logs/verify_fine4.md` — Verdikt a/b/c mit Rohzahlen

## Nächster Schritt nach den Berichten

1. `logs/verify_fine4.md` lesen: bei Verdikt **(b)** den Commit `99516c9`
   zurückrollen; bei **(a)** ist die C/M-Behauptung gesichert.
2. `logs/fine_stretch.md` lesen: geht Y auf 6564/6564, ist Fine byte-identisch —
   dann nur noch die Verifikation nachziehen.
3. Danach bleibt **außerhalb der Software**: der Ausdruck selbst. Der Nutzer
   berichtete „am Ende hellblau“; der berechnete Verlauf endet korrekt gelbgrün.
   Das braucht den **eingeschalteten Drucker** oder ein Foto/Scan der Seite.
