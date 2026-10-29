# Auftrag: 3x-Duplikatdruck + Blau-Gelb-Verlauf

## Nutzer-Bericht (2026-10-29)

> „Du hast wieder drin **3x dasselbe gedruckt**, bug? Es ist alles gut ausser
> **blau-gelb-Verlauf** — wird von blau zu grün-gelb und am Ende hellblau."

Zwei getrennte Dinge. Trenne sie sauber, vermische sie nicht.

## Grenzen (hart)

- **Keine Druckauftraege an den echten Drucker** (Papier!). Test nur gegen die
  Datei-Queue `HL3040_TEST` -> `/tmp/e2e_out.prn`.
- **Keine Neustarts** von agent-server/HA. `systemctl reload cups` ist ok.
- Erst lesen/messen, dann urteilen. Keine Architektur-Annahmen.
- Aenderungen nur nach Vorlage (Datei + Diff + Risiko + Rollback), dann warten.
- Der agent-server ist EIN Prozess fuer alle Conversations.

## Projekt

- Root `/root/brother/native`. Queue `Brother_HL-3040CN` -> `socket://192.168.178.50:9100`.
- Python `/root/brother/native/.venv312/bin/python`.
- Tests sind `unittest`, muessen aus `hl3040cn/src` laufen.
- Handover lesen: `HANDOVER-2026-10-25.md`, `FINE_HANDOVER.md`, `logs/fine_reverse.md`.

---

## Teil 1: „3x dasselbe gedruckt"

### Was ich schon gemessen habe — Spuren, keine Beweise. Pruef jede selbst.

**Der Treiber dupliziert NICHT.** Belege:

1. **`copies=1` in allen Job-Dateien:**
   ```
   c00070/71/72/73: b'copies\x00\x04\x00\x00\x00\x01'  -> 1
   ```
2. **Der Filter erzeugt genau EINE Seite:**
   ```
   /usr/lib/cups/filter/brhl3040cn-filter 1 lp T 1 "BRGray=ON BRResolution=600x2400dpi" drucktest.ps
   -> 1234428 B, genau 1 echter Header "XL2HB;1;0"
   ```
   (Das erste `XL2HB` @231 ist ein PostScript-Literal im PPD-Prolog, kein Seitenheader.
   Zaehle `XL2HB;`, nicht `XL2HB`.)
3. **Der Filter ist idempotent:** zwei Laeufe -> beide 1234428 B.
4. **Datei-Backend-Beweis (der staerkste):**
   ```
   rm -f /tmp/e2e_out.prn
   lp -d HL3040_TEST /mnt/ssd/finecmp/drucktest.ps
   -> /tmp/e2e_out.prn = 1234428 B, 1 Header, Faktor 1.00x
   ```
   Eine CUPS-Anfrage -> eine Seite. Also ist die Verdopplung **oberhalb** des
   Filters zu suchen, nicht im Filter.

**Meine Hauptvermutung: `ErrorPolicy retry-job`.** In `/etc/cups/cupsd.conf:15`.
Der `socket`-Backend meldet einen Fehler (Drucker offline/langsam), obwohl die
Daten schon uebertragen wurden — CUPS wiederholt dann den **ganzen** Job, und der
Drucker druckt die Seite erneut. **Pruefe das** (Testablauf unten).

**Zeitliche Spuren:**
```
/var/log/cups/access_log:
  00:02:58  Create-Job + Send-Document     (Job 71)
  00:05:00  Cancel-Jobs                    (Job 70 abgebrochen)
  00:05:45  Create-Job + Send-Document     (Job 72)
  01:17:05  Create-Job + Send-Document     (Job 73)
```
Das sind **drei getrennte Uebermittlungen** zu drei verschiedenen Zeiten — also
auch drei `lp`-Aufrufe. Klaere: hat der Nutzer einmal gedruckt und dreimal
bekommen (dann `retry-job`), oder wurde dreimal gedruckt (dann kein Bug)?

**Achtung Beweislage:** `error_log` hat nur 124 Zeilen (rotiert), `LogLevel warn`.
Backend-Starts sind `debug` — fuer Jobs 71-73 daher **nicht** protokolliert.
Nicht als „kein Backend gestartet" fehldeuten. Fuer den Test `LogLevel debug`
setzen und danach zurueckstellen.

### Auftrag Teil 1

1. **Reproduzieren.** Drucker aus lassen (oder Port blocken), einen Job an die
   Datei-Queue **und** einen an die socket-Queue geben. Zaehle mit `LogLevel debug`
   die `Started backend`-Zeilen pro Job. Kommt derselbe Job mehrfach?
2. **`retry-job` bewerten.** Vergleiche `ErrorPolicy retry-job` vs. `retry-current-job`
   vs. `abort-job`. Belege mit dem Log, welcher Fall eintritt.
3. **Entscheiden:** ist es CUPS-Retry, ein doppelter `lp`-Aufruf, oder der
   Backend-Wrapper? Nenne die Ursache mit Beleg.
4. Falls CUPS-Retry: Vorschlag (Config-Zeile + Rollback). **Nicht** selbst
   scharf stellen ohne Rueckfrage — es aendert das Fehlerverhalten aller Queues.

---

## Teil 2: Blau-Gelb-Verlauf „wird grün-gelb und am Ende hellblau"

### Was ich gemessen habe: die Ursache liegt in MEINEM Testblatt

`/mnt/ssd/finecmp/drucktest.ps` Zeilen 29-38 zeichnen:
```
R = 0 + 0.2*t
G =     0.9*t
B = 0.9 - 0.9*t          (t = Streifen/149)
```

Das ist **kein** Blau->Gelb:

| t | Quell-RGB | wirkt |
|---|---|---|
| 0.00 | (0,0,229) | blau |
| 0.25 | (12,56,172) | tuerkis/gruen |
| 0.50 | (25,113,115) | tuerkis |
| 0.75 | (37,170,58) | gelbgruen |
| 1.00 | (51,229,0) | gelbgruen |

**R erreicht nur 51/255** — ein echtes Gelb braucht (255,255,0). Belegt durch
Rendern (`gs -sDEVICE=ppmraw -r72`) und durch `color_lut`: am Ende bleibt
**Cyan bei ~105/255 (41 %)** stehen, deshalb „grün-gelb" statt gelb.

**Zum „hellblau am Ende":** passt **nicht** zu diesem Testblatt (das endet bei
B=0). Pruefe, ob der Nutzer einen **anderen** Verlauf meint — z. B. die
Blau->Weiss-Karte oder eine Anzeige in einem Viewer. Frage im Zweifel nach,
welches Dokument gedruckt wurde. **Erfinde keine Ursache.**

### Korrigiertes Testblatt liegt bereit

`/mnt/ssd/finecmp/drucktest2.ps` (1855 B) zeichnet:
- Referenz-Volltoene: rot / gruen / blau / gelb
- **echter** Blau->Gelb-Verlauf `R=t, G=t, B=1-t` -> (0,0,255) -> Grau -> (255,255,0)
- Blau->Weiss `R=G=1, B=1-0.5t` zum Vergleich
- Graukeil 0..100 %
- Text 11 pt / 7 pt

### Auftrag Teil 2

1. **Treiber gegen das Orakel pruefen**, nicht gegen mein altes Testblatt.
   Fuer den korrigierten Verlauf den Fine-Pfad mit
   `tools/oracle_run.py` vergleichen (Muster: `/tmp/grad2.py` aus dieser Sitzung).
2. **Die bekannte Y-Abweichung einbeziehen** (`logs/fine_reverse.md §4`):
   Y weicht in geraden Zeilen ab (1094/6564), K jede 3. Zeile. C und M sind
   byte-identisch. Klaere, ob **diese** Abweichung den Verlauf sichtbar stoert.
   Das ist ein **offener** Punkt, kein neuer.
3. **Entscheiden:** ist der Verlauf nach dem korrigierten Testblatt in Ordnung,
   oder bleibt eine echte Treiber-Abweichung? Beleg mit Zahlen, nicht mit „sieht
   gut aus".
4. Nutzer fragen, **welches Dokument** den hellblauen Ausgang hatte, falls die
   Zuordnung unklar bleibt.

---

## Ergebnis (nach `/root/brother/native/logs/dup_gradient.md`)

1. Teil 1: Ursache des 3x mit Beleg; ist es ein Bug oder dreimal gedruckt?
2. Teil 2: Verlauf gegen das Orakel, Zahlen; bleibt eine Abweichung?
3. Getrennte Entscheidung je Teil: Treiber / CUPS-Config / Testblatt / Client.
4. Offene Punkte klar benennen (z. B. Y-Abweichung).

Arbeitsweise: Hypothesen mit Status **offen/bestaetigt/widerlegt**. Keine
Erfolgsmeldung ohne sichtbare Ausgabe. Messwerte nach
`/root/brother/native/logs/dup_gradient/`. Bei einem Fehler **einen** gezielten
Diagnoseversuch, dann dokumentieren und weitermachen.

**Nicht** Teil des Auftrags: Mopria (laeuft separat), Emulator, CI.
