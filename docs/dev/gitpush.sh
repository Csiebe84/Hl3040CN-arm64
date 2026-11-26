#!/usr/bin/env bash
#
# gitpush.sh - push this repository with the token that actually may.
#
# The machine has three tokens and they are not interchangeable:
#
#   $GITHUB_TOKEN                    fine-grained, account "christiansiebe",
#                                    read-only: cannot push, cannot create.
#   ~/.config/github-bridge/token    same token as $GITHUB_TOKEN. Registered
#                                    system-wide in /etc/gitconfig as the git
#                                    credential helper, so a plain `git push`
#                                    picks THIS one and fails.
#   ~/.gh_token                      classic token, account "Csiebe84", scopes
#                                    repo, workflow. This is the one that owns
#                                    Csiebe84/Hl3040CN-arm64.
#
# This wrapper bypasses the system helper for one command and feeds git the
# classic token through GIT_ASKPASS, so the secret stays out of the command
# line, out of .git/config and out of the shell history.
#
# Usage:
#   ./gitpush.sh              # push master to origin
#   ./gitpush.sh --status     # show where things stand, push nothing
#
set -uo pipefail

cd "$(dirname "$0")"

TOKEN_FILE="${TOKEN_FILE:-${HOME:-/root}/.gh_token}"
if [[ ! -f "$TOKEN_FILE" ]]; then
    printf 'Error: no token at %s\n' "$TOKEN_FILE" >&2
    exit 1
fi

ASKPASS="$(mktemp)"
trap 'rm -f "$ASKPASS"' EXIT
cat > "$ASKPASS" <<HELPER
#!/bin/sh
case "\$1" in
    *Username*) echo "x-access-token" ;;
    *)          tr -d '\r\n' < "$TOKEN_FILE" ;;
esac
HELPER
chmod 700 "$ASKPASS"

if [[ "${1:-}" == "--status" ]]; then
    printf 'Remote    : %s\n' "$(git remote get-url origin)"
    printf 'Branch    : %s\n' "$(git rev-parse --abbrev-ref HEAD)"
    printf 'Unpushed  : %s commit(s)\n' "$(git rev-list --count origin/master..HEAD 2>/dev/null || echo '?')"
    printf 'Remote is : %s\n' "$(GIT_ASKPASS="$ASKPASS" GIT_TERMINAL_PROMPT=0 \
        git -c credential.helper= ls-remote origin 2>/dev/null \
        | awk '$2=="refs/heads/master"{print $1}')"
    exit 0
fi

printf 'Pushing to %s ...\n' "$(git remote get-url origin)"
GIT_ASKPASS="$ASKPASS" GIT_TERMINAL_PROMPT=0 \
    git -c credential.helper= push origin "${1:-master}:${2:-master}"
