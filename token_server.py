#!/usr/bin/env python3
"""One-shot local web form that stores a GitHub token in ~/.gh_token.

Run it on the machine that will push, then open the printed URL. The token
is validated against the GitHub API before it is saved, so a wrong scope
shows up as an error in the page instead of a 403 later.

Binds to loopback only. The URL carries a one-time nonce so that a random
web page cannot post to the form. The token is never logged and never sent
back to the browser.
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8899"))
OWNER = os.environ.get("OWNER", "christiansiebe")
REPO = os.environ.get("REPO", "Hl3040CN-arm64")
TOKEN_FILE = Path(os.environ.get("TOKEN_FILE", f"{os.environ.get('HOME') or '/root'}/.gh_token"))

NONCE = secrets.token_urlsafe(16)

PAGE = """<!doctype html>
<html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GitHub Token</title>
<style>
 body{{font:16px/1.5 system-ui,sans-serif;background:#16181d;color:#e6e8ec;
      margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}}
 main{{background:#1e2128;padding:28px;border-radius:14px;max-width:520px;width:100%;
      box-shadow:0 8px 30px #0006}}
 h1{{font-size:19px;margin:0 0 6px}} p{{color:#a9b0bd;margin:0 0 16px;font-size:14px}}
 input{{width:100%;box-sizing:border-box;padding:12px;border-radius:9px;font-size:15px;
       border:1px solid #39404d;background:#14161b;color:#e6e8ec;font-family:ui-monospace,monospace}}
 button{{margin-top:14px;width:100%;padding:12px;border:0;border-radius:9px;font-size:15px;
        font-weight:600;background:#3b82f6;color:#fff;cursor:pointer}}
 .ok{{color:#4ade80}} .err{{color:#f87171}} code{{color:#c7d2fe;word-break:break-all}}
 a{{color:#93c5fd}}
</style>
<main>{body}</main></html>
"""

FORM = PAGE.format(body=f"""
<h1>GitHub Token speichern</h1>
<p>Ziel: <code>{OWNER}/{REPO}</code><br>
Datei: <code>{TOKEN_FILE}</code></p>
<form method="post" action="/{NONCE}/save" autocomplete="off">
  <input name="token" type="password" spellcheck="false" autocomplete="off"
         placeholder="ghp_… oder github_pat_…" autofocus>
  <button type="submit">Prüfen und speichern</button>
</form>
<p style="margin-top:14px">Nötig: Recht <b>Contents: Read and write</b>.<br>
Neu erzeugen: <a href="https://github.com/settings/tokens/new?scopes=repo&description={REPO}">
github.com/settings/tokens/new</a></p>
""")

# Set once a token is stored, so the process can exit after answering.
DONE = {"flag": False}


def api(path, token):
    """Call the GitHub API with the token.

    Returns:
        Tuple of (status, parsed_json_or_text).
    """
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "hl3040cn-token-form",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"message": str(e)}


def check(token):
    """Validate the token and its access to the target repository.

    Returns:
        Tuple of (ok, message) with a ready-to-show message.
    """
    status, body = api("/user", token)
    if status != 200:
        return False, f"Token ungültig (HTTP {status}). {body.get('message', '')}".strip()
    login = body.get("login", "?")

    status, body = api(f"/repos/{OWNER}/{REPO}", token)
    if status == 200:
        perms = body.get("permissions", {})
        if not perms.get("push"):
            return False, (
                f"Angemeldet als {login}, aber kein Schreibrecht auf "
                f"{OWNER}/{REPO}. Beim Token 'Contents: Read and write' setzen."
            )
        return True, f"Angemeldet als <b>{login}</b>, Schreibrecht auf {OWNER}/{REPO} bestätigt."
    if status == 404:
        return False, (
            f"Angemeldet als {login}, aber {OWNER}/{REPO} ist für diesen Token "
            "nicht sichtbar. Repository-Auswahl des Tokens prüfen."
        )
    return False, f"Repository-Abfrage fehlgeschlagen (HTTP {status})."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # never log the request line: the nonce is in the URL

    def _send(self, html, code=200):
        data = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == f"/{NONCE}":
            self._send(FORM)
        else:
            self._send(PAGE.format(body='<h1 class="err">Falscher Link</h1>'
                                   "<p>Nutze die URL, die im Terminal ausgegeben wurde.</p>"), 404)

    def do_POST(self):
        if self.path.rstrip("/") != f"/{NONCE}/save":
            self._send(PAGE.format(body='<h1 class="err">Falscher Link</h1>'), 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 4096:
            self._send(PAGE.format(body='<h1 class="err">Eingabe zu lang</h1>'), 413)
            return
        from urllib.parse import parse_qs
        fields = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        token = (fields.get("token") or [""])[0].strip()

        if not token:
            self._send(PAGE.format(body='<h1 class="err">Kein Token eingegeben</h1>'
                                        f'<p><a href="/{NONCE}">Zurück</a></p>'), 400)
            return

        ok, message = check(token)
        if not ok:
            self._send(PAGE.format(body=f'<h1 class="err">Nicht gespeichert</h1>'
                                        f'<p>{message}</p><p><a href="/{NONCE}">Zurück</a></p>'), 400)
            return

        # 0600 before writing: the token must never be world-readable.
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        os.chmod(TOKEN_FILE, 0o600)
        DONE["flag"] = True

        self._send(PAGE.format(body=f"""
        <h1 class="ok">Gespeichert</h1>
        <p>{message}</p>
        <p>Datei: <code>{TOKEN_FILE}</code> (Rechte 600)</p>
        <p>Weiter im Terminal:<br><code>cd /root/brother/native &amp;&amp; ./push_to_github.sh {REPO}</code></p>
        """))


def main():
    srv = HTTPServer((HOST, PORT), Handler)
    print(f"URL:  http://{HOST}:{PORT}/{NONCE}/")
    print("Vom eigenen Rechner per SSH-Tunnel erreichbar:")
    print(f"  ssh -L {PORT}:{HOST}:{PORT} root@odroidn2")
    print(f"  dann http://localhost:{PORT}/{NONCE}/ im Browser öffnen")
    print("Beenden mit Ctrl+C.")
    sys.stdout.flush()
    try:
        while not DONE["flag"]:
            srv.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    if DONE["flag"]:
        print(f"Token gespeichert in {TOKEN_FILE}. Dienst beendet.")
        return 0
    print("Abgebrochen, nichts gespeichert.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
