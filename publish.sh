#!/usr/bin/env bash
#
# publish.sh - create the GitHub repository and push the driver to it.
#
# Run this once you have a token that may create repositories. A
# fine-grained token needs "Administration: write" on the account (to
# create the repo) plus "Contents: write" (to push); a classic token needs
# the "repo" scope. The read-only token that shipped with the workspace
# cannot do either - it answers 403 on POST /user/repos.
#
# The repository is created PRIVATE by default. Flip it to public later
# with --public once you have read the README and are happy with it:
#
#   ./publish.sh                      # private repo, push everything
#   ./publish.sh --public             # create it public instead
#   ./publish.sh --repo other-name    # pick a different repository name
#   ./publish.sh --owner someone      # push under another account
#   ./publish.sh --check              # only report, change nothing
#
# The token is read from $GITHUB_TOKEN, or from ~/.gh_token, and is never
# written into .git/config or the shell history.
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

REPO_NAME="Hl3040CN-arm64"
OWNER="${OWNER:-}"
VISIBILITY="private"
CHECK=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --public)  VISIBILITY="public"; shift ;;
        --private) VISIBILITY="private"; shift ;;
        --repo)    REPO_NAME="${2:-}"; shift 2 ;;
        --owner)   OWNER="${2:-}"; shift 2 ;;
        --check)   CHECK=1; shift ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done

# --- Token -------------------------------------------------------------------
TOKEN="${GITHUB_TOKEN:-}"
if [[ -z "$TOKEN" && -f "$HOME/.gh_token" ]]; then
    TOKEN="$(tr -d ' \t\r\n' < "$HOME/.gh_token")"
fi
if [[ -z "$TOKEN" ]]; then
    printf 'Error: no token. Set GITHUB_TOKEN or write one to ~/.gh_token\n' >&2
    exit 1
fi

api() {
    # api METHOD PATH [JSON]
    local method="$1" path="$2" body="${3:-}"
    if [[ -n "$body" ]]; then
        curl -sS -X "$method" \
            -H "Authorization: token $TOKEN" \
            -H "Accept: application/vnd.github+json" \
            -d "$body" \
            "https://api.github.com$path"
    else
        curl -sS -X "$method" \
            -H "Authorization: token $TOKEN" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com$path"
    fi
}

# --- Who are we? -------------------------------------------------------------
me="$(api GET /user)"
login="$(printf '%s' "$me" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("login",""))' 2>/dev/null)"
if [[ -z "$login" ]]; then
    printf 'Error: the token was rejected by GitHub.\n' >&2
    printf '%s\n' "$me" | head -3 >&2
    exit 1
fi
[[ -n "$OWNER" ]] || OWNER="$login"
printf 'Token belongs to : %s\n' "$login"
printf 'Target repository: %s/%s (%s)\n' "$OWNER" "$REPO_NAME" "$VISIBILITY"

# --- Can this token create repositories? -------------------------------------
code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    -H "Authorization: token $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -d '{}' \
    "https://api.github.com/user/repos")"
case "$code" in
    422) can_create=1 ;;   # 422 = request understood, body incomplete
    403|404) can_create=0 ;;
    *) can_create=0 ;;
esac

if [[ $CHECK -eq 1 ]]; then
    printf 'Can create repos  : %s\n' "$([[ $can_create -eq 1 ]] && echo yes || echo "no (HTTP $code)")"
    printf 'Unpushed commits  : %s\n' "$(git rev-list --count origin/master..HEAD 2>/dev/null || echo '?')"
    printf 'Working tree      : %s\n' "$(git status --porcelain | wc -l) changed paths"
    exit 0
fi

if [[ $can_create -eq 0 ]]; then
    cat >&2 <<EOF

Error: this token may not create repositories (HTTP $code).

Create a token with the right permission and try again:

  * fine-grained token: "Administration: write" (to create the repo)
    and "Contents: write" (to push), scoped to your account.
  * classic token: the "repo" scope.

Then either export it:

    export GITHUB_TOKEN=github_pat_...

or save it where this script looks for it:

    printf '%s' 'github_pat_...' > ~/.gh_token && chmod 600 ~/.gh_token
EOF
    exit 1
fi

# --- Create the repository (idempotent) --------------------------------------
exists="$(api GET "/repos/$OWNER/$REPO_NAME" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print("yes" if d.get("full_name") else "no")' 2>/dev/null)"

if [[ "$exists" == "yes" ]]; then
    printf 'Repository already exists; pushing into it.\n'
else
    printf 'Creating repository ...\n'
    out="$(api POST /user/repos "$(python3 - "$REPO_NAME" "$VISIBILITY" <<'PY'
import json, sys
print(json.dumps({
    "name": sys.argv[1],
    "private": sys.argv[2] == "private",
    "description": "Native ARM64 CUPS driver for the Brother HL-3040CN "
                   "(XL2HB), ported from the GPL-3.0 hl4150 driver. No qemu-i386.",
    "has_issues": True,
    "has_wiki": False,
    "auto_init": False,
}))
PY
)")"
    if ! printf '%s' "$out" | grep -q '"full_name"'; then
        printf 'Error creating the repository:\n%s\n' "$out" >&2
        exit 1
    fi
    printf '  created.\n'
fi

# --- Point origin at it and push ---------------------------------------------
git remote set-url origin "https://github.com/$OWNER/$REPO_NAME.git" 2>/dev/null \
    || git remote add origin "https://github.com/$OWNER/$REPO_NAME.git"

printf 'Pushing master ...\n'
if ! git push "https://$TOKEN@github.com/$OWNER/$REPO_NAME.git" master:master 2>&1 | grep -v "$TOKEN"; then
    printf 'Error: push failed.\n' >&2
    exit 1
fi

printf '\nDone.\n'
printf '  https://github.com/%s/%s\n' "$OWNER" "$REPO_NAME"
if [[ "$VISIBILITY" == "private" ]]; then
    cat <<'EOF'

The repository is PRIVATE. When you are ready to let others install it:

  1. Read README.md once more - it is the installation guide.
  2. Check that no Brother blob slipped in:
       git ls-files | grep -E '\.bin$|\.deb$' || echo "clean"
  3. Flip it public, either in the web UI
     (Settings -> General -> Danger Zone -> Change visibility)
     or with:
       curl -X PATCH -H "Authorization: token $TOKEN" \
         -d '{"private":false}' \
         https://api.github.com/repos/OWNER/REPO
EOF
fi
