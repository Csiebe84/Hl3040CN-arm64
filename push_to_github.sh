#!/bin/bash
# Push the native HL-3040CN driver to the private GitHub repository.
#
# Asks for the token on the terminal (hidden input), checks it against the
# GitHub API before touching git, then pushes. The token never reaches the
# shell history and never lands in .git/config.
#
# Usage:
#   ./push_to_github.sh [repo-name] [--check] [--save]

set -uo pipefail

REPO_NAME="brother-hl3040cn-native"
CHECK=0
SAVE=0
for arg in "$@"; do
    case "$arg" in
        --check) CHECK=1 ;;
        --save)  SAVE=1 ;;
        --*)     printf 'unbekannte Option: %s\n' "$arg" >&2; exit 2 ;;
        *)       REPO_NAME="$arg" ;;
    esac
done

OWNER="${OWNER:-christiansiebe}"
TOKEN_FILE="${TOKEN_FILE:-${HOME:-/root}/.gh_token}"
TOKEN=""

clean_token() {
    # A paste over SSH can drag CR, bracketed-paste markers and stray quotes in.
    local t="$1"
    t="${t//$'\r'/}"
    t="${t//$'\n'/}"
    t="${t//$'\e[200~'/}"
    t="${t//$'\e[201~'/}"
    t="${t#"${t%%[![:space:]]*}"}"
    t="${t%"${t##*[![:space:]]}"}"
    t="${t%\"}"; t="${t#\"}"
    t="${t%\'}"; t="${t#\'}"
    printf '%s' "$t"
}

prompt_token() {
    printf '\n' >&2
    printf '  GitHub-Token fuer %s/%s\n' "$OWNER" "$REPO_NAME" >&2
    printf '  (Eingabe bleibt unsichtbar, mit Enter abschliessen): ' >&2
    if [ -t 0 ]; then
        IFS= read -rs TOKEN || true
    else
        IFS= read -r TOKEN || true
    fi
    printf '\n' >&2
}

verify_token() {
    # Prints "OK|..." or "ERR|...". Uses python3, stdlib only.
    python3 - "$OWNER" "$REPO_NAME" "$1" <<'PY'
import json, sys, urllib.error, urllib.request
owner, repo, token = sys.argv[1], sys.argv[2], sys.argv[3]

def api(path):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": "token " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "hl3040cn-push"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"message": str(e)}

status, body = api("/user")
if status != 200:
    print("ERR|Token abgelehnt (HTTP %s): %s" % (status, body.get("message", "")))
    sys.exit(0)
login = body.get("login", "?")

status, body = api("/repos/%s/%s" % (owner, repo))
if status == 200:
    if body.get("permissions", {}).get("push"):
        print("OK|Angemeldet als %s, Schreibrecht auf %s/%s bestaetigt." % (login, owner, repo))
    else:
        print("ERR|Angemeldet als %s, aber kein Schreibrecht auf %s/%s. "
              "Beim Token 'Contents: Read and write' setzen." % (login, owner, repo))
elif status == 404:
    print("ERR|Angemeldet als %s, aber %s/%s ist fuer diesen Token nicht sichtbar. "
          "Repository-Auswahl des Tokens pruefen." % (login, owner, repo))
else:
    print("ERR|Repository-Abfrage fehlgeschlagen (HTTP %s)." % status)
PY
}

# --- Token beschaffen -------------------------------------------------------
TOKEN="$(clean_token "${GH_TOKEN:-}")"
if [ -z "$TOKEN" ] && [ -s "$TOKEN_FILE" ]; then
    TOKEN="$(clean_token "$(cat "$TOKEN_FILE")")"
fi
if [ -z "$TOKEN" ]; then
    prompt_token
    TOKEN="$(clean_token "$TOKEN")"
fi

if [ -z "$TOKEN" ]; then
    cat >&2 <<EOF

  Kein Token eingegeben.

  Einen erzeugen (Recht 'Contents: Read and write'):
    https://github.com/settings/tokens/new?scopes=repo&description=${REPO_NAME}

  Dann dieses Skript erneut starten.
EOF
    exit 1
fi

if [ "${#TOKEN}" -ge 8 ]; then
    printf '  Token: %s...%s (%d Zeichen)\n' \
        "${TOKEN:0:4}" "${TOKEN:${#TOKEN}-4}" "${#TOKEN}" >&2
else
    printf '  Token: (%d Zeichen, ungewoehnlich kurz)\n' "${#TOKEN}" >&2
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf '\n  FEHLER: python3 fehlt, Pruefung nicht moeglich.\n\n' >&2
    exit 1
fi

# --- Pruefen, BEVOR git angefasst wird --------------------------------------
printf '  Pruefe Token bei GitHub ...\n' >&2
RESULT="$(verify_token "$TOKEN")"
case "$RESULT" in
    OK\|*)  printf '  %s\n' "${RESULT#OK|}" >&2 ;;
    ERR\|*) printf '\n  FEHLER: %s\n\n' "${RESULT#ERR|}" >&2; exit 1 ;;
    *)      printf '\n  FEHLER: unerwartete Antwort der Pruefung.\n\n' >&2; exit 1 ;;
esac

if [ "$CHECK" = "1" ]; then
    printf '  --check: nur geprueft, nichts gepusht.\n' >&2
    exit 0
fi

if [ "$SAVE" = "1" ]; then
    ( umask 077; printf '%s\n' "$TOKEN" >"$TOKEN_FILE" )
    printf '  Token in %s gespeichert (Rechte 600).\n' "$TOKEN_FILE" >&2
fi

# --- Push -------------------------------------------------------------------
cd "$(dirname "$0")"

TOKENF="$(mktemp)"; chmod 600 "$TOKENF"; printf '%s\n' "$TOKEN" >"$TOKENF"
ASKPASS="$(mktemp)"; chmod 700 "$ASKPASS"
trap 'rm -f "$TOKENF" "$ASKPASS"' EXIT
{
    printf '#!/bin/sh\n'
    printf 'cat %s\n' "$TOKENF"
} >"$ASKPASS"
export GIT_ASKPASS="$ASKPASS"

git remote remove origin 2>/dev/null || true
git remote add origin "https://${OWNER}@github.com/${OWNER}/${REPO_NAME}.git"

printf '  Pushe nach %s/%s ...\n\n' "$OWNER" "$REPO_NAME" >&2
if git -c credential.helper= push -u origin master; then
    cat >&2 <<EOF

  Fertig.
    Repository: https://github.com/${OWNER}/${REPO_NAME}
    CI-Lauf:    https://github.com/${OWNER}/${REPO_NAME}/actions
EOF
else
    printf '\n  Push fehlgeschlagen.\n' >&2
    exit 1
fi
