# Auftrag: HL-3040CN verschwindet aus Mopria — Ursache + Fix

## Symptom (Nutzer, 2026-10-29)

> „Und der Drucker taucht unter Mopria nicht mehr auf."

Das **„mehr"** ist der Kern: er war schon einmal sichtbar. Es ist also eine
**Regression**, kein „hat nie funktioniert". Suche die Änderung, die ihn
verschwinden ließ.

## Grenzen (hart)

- Erst **lesen und messen**, dann urteilen. Keine Architektur-Annahmen.
- Änderungen nur nach Vorlage (Datei + Diff-Plan + Risiko + Rollback), dann warten.
- **Keine Druckauftraege** (Papierverbrauch). Test nur gegen Datei-Backend
  (`HL3040_TEST` -> `/tmp/e2e_out.prn`), nicht gegen den echten Drucker.
- **Keine Neustarts** von agent-server/HA. `systemctl reload nginx` und
  `systemctl reload cups` sind ok, `restart` nur mit Begruendung.
- Vorhandene Firewall (`fw_rules.py`) **nicht abschalten** — nur gezielt ergaenzen.
  Rollback steht bereit: `fw_rules.py --rollback`.
- Frueheren Auftrag `TASK_MOPRIA.md` und `logs/mopria_analyse.md` lesen — dort
  steht der Stand vom 27./28.10. **Widersprich ihm, wo er falsch liegt.**

## Projekt

- Root `/root/brother/native`. Queue `Brother_HL-3040CN` -> `socket://192.168.178.50:9100`.
- Python `/root/brother/native/.venv312/bin/python`.
- Tests sind `unittest` und muessen aus `hl3040cn/src` laufen.

## Was ich heute gemessen habe — Spuren, keine Beweise. Pruef jede selbst.

### 1. Der physische Drucker ist gerade OFFLINE

```
ping 192.168.178.50        -> 100% packet loss
ip neigh show 192.168.178.50 -> dev wlxdc627949ba79 FAILED
9100, 631 am Drucker        -> beide zu
```

**Das allein erklaert „taucht nicht auf".** Klaere zuerst, ob das ein
Dauerzustand ist oder der Drucker nur schlaeft/aus war. Ein Geraet, das nicht
antwortet, wird von **keinem** Discovery-Dienst gefunden. Miss ueber laengere
Zeit, nicht einmalig.

### 2. NEU: Default-deny-Firewall seit 2026-10-24 — zeitliche Korrelation

`/usr/local/sbin/fw_rules.py`, `fw-rules.service`/`.timer`, in Betrieb seit
**24.10.** Das ist **nach** dem letzten bekannten Mopria-Erfolg.

```
-P INPUT DROP
FW-Kette: lo, ESTABLISHED, icmp, udp/68, udp/1900, udp/5353, udp/5355, dann
          LAN-TCP-Ports, dann -j DROP
UDP 3702 (WSD)  -> NICHT erlaubt
LAN_UDP_PORTS   -> leer
```

- **UDP 5353 (mDNS) ist erlaubt** — DNS-SD sollte also gehen.
- **UDP 3702 (WSD/WS-Discovery) fehlt.** Manche Android-/Mopria-Stapel suchen
  per WSD. **Pruefe, ob das der Erkennungsweg ist** (tcpdump am Handy).
- `LAN_UDP_PORTS` ist leer: kein SNMP (161), kein WSD. Bewerte, ob das stoert.
- **Wichtig:** Mopria und der Android-Standarddienst nutzen *verschiedene* Wege.
  Klaere getrennt, welcher Weg welchen Port braucht.

### 3. `/ipp/print` liefert 404 — auf dem Odroid

```
/ipp/print                   -> 404
/printers/Brother_HL-3040CN  -> 200
```

`/ipp/print` ist der Mopria-Standardpfad. Pruefe, ob CUPS 2.4.2 ihn per
`ServerAlias`/`<Location>` anbieten kann, oder ob Mopria auch den
`/printers/<name>`-Pfad akzeptiert.

### 4. CUPS lauscht auf v4 und v6, TLS-Zertifikat hat ein SAN

```
Listen 0.0.0.0:631 / [::]:631
ServerAlias odroidn2 odroidn2.local odroidn2.fritz.box
Zert-SAN: DNS:odroidn2, DNS:odroidn2.local, DNS:localhost
```

`_ipp._tcp` **und** `_ipps._tcp` werden beworben (je 2 Treffer, v4+v6), mit
`mopria-certified=1.3`, `URF=V1.4,CP1,W8,PQ3-4-5,SRGB24,RS600,FN3`, `TLS=1.2`.

**Pruefe:** das Zertifikat ist **selbstsigniert** (`verify error: num=18`).
Ein Android-Geraet, das `_ipps._tcp` waehlt und das Zert ablehnt, faellt aus.
Waere `_ipps._tcp` abzuschalten, damit nur das funktionierende `_ipp._tcp`
gewaehlt wird?

### 5. Der Drucker selbst kann kein IPP

Frueher gemessen: nur `pdl=application/vnd.brother-hbp`, `/ipp/print` -> 404.
Der Odroid ist der IPP-Server. **Pruef das neu**, aber verlass dich nicht darauf,
dass der Drucker IPP kann.

### 6. Namensaufloesung

```
odroidn2 / odroidn2.fritz.box -> Router-DNS ok
odroidn2.local                -> nur per mDNS (Router: NXDOMAIN)
```

Das mDNS-SRV-Ziel ist `odroidn2.local`. Loest das Handy kein mDNS auf, scheitert
die Erkennung genau hier. Pruefe `resolvectl query odroidn2.local` und ob ein
Advert auf `odroidn2` (ohne `.local`) hilft.

## Untersuchungsauftrag

1. **Regression eingrenzen.** Was hat sich zwischen „sichtbar" und „nicht mehr
   sichtbar" geaendert? Kandidaten: Firewall (24.10.), `chat-allow`/`fw-rules`,
   avahi-Konfig, CUPS-Config, Zertifikat, IP-Wechsel. Nenne **Belege** (Datum,
   Log, mtime), keine Vermutungen.
2. **Messpfad am echten Handy.** `tcpdump -i any -n 'udp port 5353 or udp port
   3702 or tcp port 631'` waehrend der Handy-Suche. Kommt ueberhaupt ein Paket
   an? Wenn nein: liegt es an der Firewall (Zaehler in `iptables -L FW -v`) oder
   sendet das Handy gar nicht?
3. **Entscheiden:** reicht ein Firewall-Loch (UDP 3702 / SNMP 161), ein
   `_ipps._tcp`-Abschalten, ein `/ipp/print`-Alias, oder braucht es eine
   Protokollbruecke? Kleinste wartbare Loesung waehlen.
4. **Beweisen, nicht behaupten.** Jede Aussage mit Kommando + Ausgabe.

## Ergebnis (nach `/root/brother/native/logs/mopria2.md`)

1. Ursache der Regression, mit Beleg.
2. Welche Änderung sie behebt (Datei, Diff, Risiko, Rollback).
3. Testplan getrennt nach: Erkennung / manuelle Einrichtung / echter Ausdruck.
4. Eindeutige Entscheidung: Firewall / CUPS-Config / mDNS / Bruecke / nicht
   sinnvoll realisierbar.

Arbeitsweise: Hypothesen mit Status **offen/bestaetigt/widerlegt**. Keine
Erfolgsmeldung ohne sichtbare Ausgabe. Messwerte nach
`/root/brother/native/logs/mopria2/`. Bei einem Fehler **einen** gezielten
Diagnoseversuch, dann dokumentieren und weitermachen.

**Nicht** Teil des Auftrags: Fine-Dither, Gray-Replace, Verlauf, Emulator.
