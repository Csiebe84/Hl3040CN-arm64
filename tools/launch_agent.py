#!/usr/bin/env python3
"""Start a fresh agent-server conversation for the colour-transform task.

The task brief points at HANDOVER.md so the new conversation starts from the
verified state instead of re-deriving it.  The LLM settings are read from the
installed default profile; no credentials are printed.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000/api/conversations"
PROFILE = Path("/root/.openhands/profiles/default.json")

TASK = """\
Arbeite die Aufgabe in /root/brother/native/HANDOVER.md ab.

Lies zuerst HANDOVER.md vollständig. Darin steht der verifizierte Stand:
zwei RLE-Encoder sind bit-genau, der 10-Bit-Decoder ist validiert, die
Dither-Tabellen laden korrekt (cache08), und die Oracle-Tintenstufen der
sechs Primärfarben sind gemessen. Ebenso steht dort, was bereits
ausgeschlossen ist (Encoder, Dither-Tabellen, alle 18 Farbtabellen, alle 29
Gitter im Binary) — wiederhole diese Messungen nicht.

Deine Aufgabe: Finde die Farbtransformation zwischen Farb-LUT und Dithering,
die die Oracle-Tintenstufen reproduziert. Empfohlener erster Schritt steht in
HANDOVER.md: eine Tonwert-Rampe durch den Oracle erzeugen (Docker-Container
brother-cups), dann mit den vorhandenen Werkzeugen in /root/brother/native/tools/
auswerten.

Harte Regeln (in HANDOVER.md begründet):
- Jede Hypothese bekommt Status: offen / bestätigt / widerlegt.
- Vor einer Wiederholung erklären, welche NEUE Information sie liefert.
- Neue Skripte nur, wenn vorhandene Werkzeuge die Frage nicht beantworten.
- Keine Erfolgsmeldung ohne sichtbares Testergebnis. Keine erfundenen Prozente.
- Bei einem Fehler höchstens EINEN gezielten Diagnoseversuch, danach beheben
  oder den Blocker dokumentieren und weitermachen.
- Messwerte in Logdateien sichern, nicht nur auf dem Bildschirm ausgeben.

Nicht Teil dieser Aufgabe: CUPS-Integration, PPD, Git, Lizenzprüfung,
Dokumentation, reale Drucktests. Nur die Farbtransformation.

Berichte am Ende: gemessene Rampe, abgeleitete Transformation, Abweichung
zwischen Modell und Messung, und ob die Korrektur die Referenzfälle besteht.
Falls die Rampe keine eindeutige Ursache ergibt, ist das Ergebnis ausdrücklich
"Farbtransformation weiterhin ungeklärt" — dann nicht weiter raten.
"""


def main() -> int:
    """POST the task to the agent server and print the new conversation id."""
    prof = json.loads(PROFILE.read_text())
    payload = {
        "workspace": {"working_dir": "/root/brother", "kind": "LocalWorkspace"},
        "initial_message": {"role": "user", "content": [{"type": "text", "text": TASK}]},
        "agent_settings": {"llm": prof},
        "max_iterations": 500,
        "confirmation_policy": {"kind": "NeverConfirm"},
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()[:600]}")
        return 1
    cid = body.get("id") or body.get("conversation_id")
    print(f"Conversation gestartet: {cid}")
    print(f"Status: {body.get('execution_status')}")
    Path("/root/brother/native/.color_agent_id").write_text(str(cid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
