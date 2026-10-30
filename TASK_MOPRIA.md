# Auftrag: HL-3040CN mit Android Mopria kompatibel machen

## Ziel

Ermittle, wie sich der Brother HL-3040CN unter Android ueber den **Mopria Print
Service** zuverlaessig erkennen und zum Drucken verwenden laesst. Untersuche
dafuer das bestehende Treiberprojekt. **Keine Annahmen ueber die Architektur** —
erst lesen, dann urteilen.

## Grenzen (hart)

- **Nur lesen und analysieren.** Keine Aenderung an Dateien, Configs, Diensten
  oder dem laufenden System.
- **Keine Neustarts**, keine zusaetzlichen dauerhaften Dienste.
- **Keine Druckauftraege** ausloesen (Papierverbrauch).
- Vor jeder Aenderung: Loesungsvorschlag mit betroffenen Dateien, Voraussetzungen
  und Risiken vorlegen. Dann warten.
- Der agent-server ist EIN Prozess fuer alle Conversations: kein `systemctl
  restart` ueber den Dienst hinaus, der wirklich noetig ist.

## Projekt

- Root `/root/brother/native`, Treiber unter `hl3040cn/`, Queue
  `Brother_HL-3040CN`. Python `/root/brother/native/.venv312/bin/python`.
- Tests sind **unittest**, nicht pytest, und muessen aus `hl3040cn/src` laufen
  (sonst `ModuleNotFoundError: settings`). Beispiel:
  `cd hl3040cn/src && /root/brother/native/.venv312/bin/python -m unittest test_fine_mode`
- Handover lesen: `HANDOVER-2026-10-25.md`, `logs/android.md`,
  `logs/android-anleitung.md`.

## Ausgangslage (vom Nutzer berichtet)

- Android **Standarddruckdienst** findet den Drucker unter „Alle Drucker".
- In **Mopria** wurde der Drucker manuell hinzugefuegt — **ohne** `ipp://`-Praefix.
- Beim Drucken ueber „Teilen → Drucken → Mopria" erscheint dauerhaft
  „Suche nach Druckern …".
- Der Drucker taucht offenbar nur im Standarddruckdienst auf, nicht in Mopria.

## Belege, die ich schon gemessen habe — bitte gegenpruefen, nicht glauben

Diese Werte stammen aus einer Sitzung von heute. Sie sind **Spuren, keine
Beweise**. Pruefe jede selbst nach; wenn eine nicht stimmt, sag das.

1. **Der Drucker selbst kann kein IPP.** `192.168.178.50:9100` (RAW/JetDirect)
   ist offen. Der Drucker advertiert laut frueherer Messung nur
   `pdl=application/vnd.brother-hbp`; `/ipp/print` auf dem Drucker → 404.
   → **Pruefe neu:** `nmap -Pn -p 80,443,515,631,9100 192.168.178.50`, dann
   `ipptool` gegen jeden 631-Endpunkt, den du findest. LPD (515) mitdenken.
2. **Der Odroid ist der IPP-Server.** CUPS auf `192.168.178.71:631`, lauscht auf
   `0.0.0.0:631` und `[::]:631`. Diese URL funktioniert:
   `ipp://192.168.178.71:631/printers/Brother_HL-3040CN`
3. **`/ipp/print` liefert 404** — auf dem Odroid **und** auf dem Drucker:
   ```
   /ipp/print                       -> 404
   /printers/Brother_HL-3040CN      -> 200
   ```
   Das ist der **Mopria-Standardpfad**. Ohne ihn findet Mopria den Drucker oft
   nicht, selbst wenn IPP sonst funktioniert. → Das ist mein Hauptverdacht.
   Pruefe, ob CUPS 2.4.2 `/ipp/print` per `ServerAlias`/`<Location>` anbieten
   kann, oder ob Mopria auch den `/printers/<name>`-Pfad akzeptiert.
4. **mDNS-Advert des Odroid:** Name
   `Brother HL-3040CN (Open Source) @ odroidn2`, SRV-Ziel `odroidn2.local`,
   Port 631, mit `mopria-certified=1.3` und
   `URF=V1.4,CP1,W8,PQ3-4-5,SRGB24,RS600,FN3`. Beide Adressen werden beworben
   (IPv4 `192.168.178.71`, IPv6 `2001:16b8:...:127c`).
   → Pruefe mit `avahi-browse -rt _ipp._tcp`, ob das stimmt und ob `_ipps._tcp`
   fehlt (TLS-Variante).
5. **Namensaufloesung — moegliche Ursache des „kann hostname nicht aufloesen":**
   ```
   odroidn2            -> Router-DNS: 192.168.178.71      (rcode 0)
   odroidn2.fritz.box  -> Router-DNS: 192.168.178.71      (rcode 0)
   odroidn2.local      -> Router-DNS: NXDOMAIN (rcode 3)  nur per mDNS
   ```
   Das mDNS-SRV-Ziel ist `odroidn2.local`. Wenn das Handy mDNS nicht aufloest
   (Multicast im WLAN geblockt, Gastnetz, Energiesparmodus), scheitert es genau
   hier. → **Pruefe, welchen Namen Mopria braucht** und ob `odroidn2` (ohne
   `.local`) als SAN/Advert ergaenzt werden sollte.
6. **CUPS weist ein Host-Feld ab** (im Log belegt):
   ```
   E [27/Oct/2026:20:40:37] [Client 59] Request from "[v1.2001:16b8:...:127c]"
     using invalid Host: field "odroidn2.fritz.box:631".
   ```
   Reproduziert: `Host: odroidn2.fritz.box:631` → **HTTP 400**, waehrend
   `192.168.178.71`, `odroidn2`, `odroidn2.local` → 200.
   **Wichtig:** Der PTR von `.71` ist `odroidn2.fritz.box`. Ein Client, der den
   Host aus dem Reverse-Lookup bildet, laeuft also genau in den 400.
   → Pruefe, ob `ServerAlias` das behebt und ob das die Mopria-Ursache ist.
7. **Es kam nie ein Fremdclient an CUPS an:** `/var/log/cups/access_log`
   enthaelt ausschliesslich `localhost` (95 Zeilen, 0 fremde IPs). Die
   „invalid Host"-Zeilen kommen von meinen eigenen Tests.
   → **Pruefe mit `tcpdump`**, ob das Handy ueberhaupt Pakete schickt:
   `tcpdump -i any -n 'tcp port 631 or udp port 5353'`, dann am Handy suchen.

## Untersuchungsauftrag

1. **Ist-Zustand:** Welche Protokolle kann der Drucker wirklich (IPP, LPD, RAW,
   sonst)? Hat er einen IPP-Endpunkt? Wie erkennt der Android-Standarddienst ihn
   und was nutzt er zum Drucken? Was kuendigt mDNS/DNS-SD an?
2. **Mopria-Bewertung:** Anforderungen aus verlaesslicher Doku. Trenne sauber:
   Erkennung / IPP-Kompatibilitaet / Datenformat / Ausgabe. Kann Mopria den
   Drucker **direkt** ansprechen oder braucht es einen Proxy? Nutzen
   Standarddruckdienst und Mopria **verschiedene** Erkennungswege?
3. **Loesung:** Kleinste wartbare Erweiterung des vorhandenen Projekts. Pruefe
   DNS-SD/mDNS-Ankuendigung, IPP-Attribute, `/ipp/print`, Protokollbruecke.
   **Erfinde keine IPP-Faehigkeit, die der Drucker nicht hat.** Bevorzuge eine
   Loesung **ohne** dauerhaft laufenden Zusatzdienst. Der Drucker ist
   vermutlich **kein** Mopria-zertifiziertes Geraet — Ziel ist Interoperabilitaet,
   nicht eine Zertifizierungsbehauptung.
4. **Validierung:** Testplan, der Erkennung / manuelle Einrichtung / echten
   Ausdruck **getrennt** prueft. Keine unkontrollierten Druckauftraege.

## Ergebnis (in `/root/brother/native/logs/mopria_analyse.md`)

1. Wahrscheinlichste Ursache, mit Beleg (Kommando + Ausgabe).
2. Klare Aussage: reicht der bestehende Treiber allein?
3. Kleinste technisch tragfaehige Loesung.
4. Falls Aenderungen noetig: konkrete Dateien, geplante Aenderung, Testplan.
5. **Eindeutige Entscheidung:** direkt im Treiber loesbar / nur ueber
   Protokollbruecke / mit dieser Hardware nicht sinnvoll realisierbar.

Arbeitsweise: jede Hypothese mit Status offen/bestaetigt/widerlegt. Keine
Erfolgsmeldung ohne sichtbare Ausgabe. Bei einem Fehler hoechstens EINEN
gezielten Diagnoseversuch, dann dokumentieren und weitermachen. Messwerte in
`/root/brother/native/logs/` sichern, nicht nur auf den Bildschirm.

**Nicht** Teil des Auftrags: Fine-Modus (dither.py), Gray-Replace, Emulator.
