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
DIAGNOSE=0
for arg in "$@"; do
    case "$arg" in
        --check) CHECK=1 ;;
        --save)  SAVE=1 ;;
        --diagnose) DIAGNOSE=1 ;;
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

def can_push(o, r):
    st, bd = api("/repos/%s/%s" % (o, r))
    if st == 200:
        return bool(bd.get("permissions", {}).get("push")), st
    return False, st

status, body = api("/user")
if status != 200:
    print("ERR|Token abgelehnt (HTTP %s): %s" % (status, body.get("message", "")))
    sys.exit(0)
login = body.get("login", "?")

# The token's own account is the owner that almost always works: a token
# usually belongs to whoever created the repository.
ok, st = can_push(login, repo)
if ok and login != owner:
    print("OK|Angemeldet als %s, Schreibrecht auf %s/%s bestaetigt. "
          "Hinweis: das Repository liegt unter '%s', nicht unter '%s'."
          % (login, login, repo, login, owner))
    print("OWNER|%s" % login)
    sys.exit(0)
if ok:
    print("OK|Angemeldet als %s, Schreibrecht auf %s/%s bestaetigt." % (login, owner, repo))
    sys.exit(0)

ok, st = can_push(owner, repo)
if ok:
    print("OK|Angemeldet als %s, Schreibrecht auf %s/%s bestaetigt." % (login, owner, repo))
    sys.exit(0)

# Neither place worked. Look through what the token CAN see, so the error
# names the right owner instead of leaving the user to guess.
st, body = api("/user/repos?per_page=100&affiliation=owner,collaborator,organization_member")
found = []
if st == 200 and isinstance(body, list):
    for r in body:
        if r.get("name", "").lower() == repo.lower():
            found.append((r["owner"]["login"], bool(r.get("permissions", {}).get("push"))))

if found:
    lines = []
    for o, push in found:
        lines.append("  %s/%s (%s)" % (o, repo, "Schreibrecht" if push else "nur Lesen"))
    print("ERR|Angemeldet als %s. Das Repository '%s' liegt nicht unter '%s', "
          "sondern unter:\n%s\nMit dem richtigen Namen starten, z.B.:\n"
          "  ./push_to_github.sh %s"
          % (login, repo, owner, "\n".join(lines), found[0][0]))
else:
    if login == owner:
        print("ERR|Angemeldet als %s. Das Repository %s/%s ist mit diesem Token "
              "nicht sichtbar.\n"
              "Bei einem fine-grained Token muss es unter 'Repository access' "
              "ausgewaehlt und 'Contents: Read and write' gesetzt sein.\n"
              "Was der Token sieht: ./push_to_github.sh --diagnose"
              % (login, owner, repo))
    else:
        print("ERR|Angemeldet als %s. Weder %s/%s noch %s/%s sind mit diesem "
              "Token sichtbar, und kein Repository namens '%s' ist erreichbar.\n"
              "Moeglich: das Repo liegt unter einem anderen Konto, oder der "
              "Token hat es nicht in seiner Repository-Auswahl.\n"
              "Was der Token sieht: ./push_to_github.sh --diagnose"
              % (login, owner, repo, login, repo, repo))
PY
}

diagnose() {
    python3 - "$1" <<'PY'
import json, sys, urllib.error, urllib.request
token = sys.argv[1]

def call(path, raw=False):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": "token " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "hl3040cn-push"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers
    except Exception as e:
        return 0, str(e).encode(), {}

st, raw, hdrs = call("/user")
if st != 200:
    print("  Token ungueltig (HTTP %s)." % st)
    sys.exit(1)
me = json.loads(raw)
print("  Konto:    %s (id %s)" % (me.get("login"), me.get("id")))
scopes = hdrs.get("x-oauth-scopes")
if scopes is None:
    print("  Typ:      fine-grained (kein Scope-Header)")
else:
    print("  Scopes:   %s" % (scopes or "(keine)"))
    if "repo" not in scopes.split(","):
        print("            -> 'repo' fehlt! Ohne den Scope sieht der Token")
        print("               keine privaten Repositories.")

print("  Sichtbare Repositories:")
st, raw, _ = call("/user/repos?per_page=100&affiliation=owner,collaborator,organization_member")
if st == 200:
    repos = json.loads(raw)
    if not repos:
        print("    (keine)")
    for r in repos:
        perm = "Schreibrecht" if r.get("permissions", {}).get("push") else "nur Lesen"
        print("    %-45s %s" % (r["full_name"], perm))
else:
    print("    Abfrage fehlgeschlagen (HTTP %s)" % st)
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
if [ "$DIAGNOSE" = "1" ]; then
    printf '\n  Was dieser Token sieht:\n' >&2
    diagnose "$TOKEN" >&2
    printf '\n' >&2
    exit 0
fi

printf '  Pruefe Token bei GitHub ...\n' >&2
RESULT="$(verify_token "$TOKEN")"
case "$RESULT" in
    *OWNER\|*)
        # The repository turned out to live under a different account than
        # the one asked for. Use it rather than failing on a stale name.
        DETECTED="${RESULT##*OWNER|}"
        MSG="${RESULT%$'\n'OWNER|*}"
        printf '  %s\n' "${MSG#OK|}" >&2
        OWNER="$DETECTED"
        printf '  Owner auf %s gesetzt.\n' "$OWNER" >&2
        ;;
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
