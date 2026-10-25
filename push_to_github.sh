#!/bin/bash
# Push the native HL-3040CN driver to a private GitHub repository.
#
# Run this after creating the repository (the tokens available here may not
# create one). Either:
#   * create it in the web UI, or
#   * use a token with "Administration: write" / classic "repo" scope:
#       curl -X POST -H "Authorization: token <TOKEN>" \
#         https://api.github.com/user/repos \
#         -d '{"name":"brother-hl3040cn-native","private":true}'
#
# Usage:
#   ./push_to_github.sh [repo-name]        # then paste the token at the prompt
set -euo pipefail

REPO_NAME="${1:-brother-hl3040cn-native}"
OWNER="${OWNER:-christiansiebe}"
TOKEN_FILE="${TOKEN_FILE:-${HOME:-/root}/.gh_token}"
TOKEN="${GH_TOKEN:-}"

# Accept the token from a file as well, so it can be pasted once with an
# editor instead of typed into the terminal.
if [ -z "$TOKEN" ] && [ -s "$TOKEN_FILE" ]; then
    TOKEN="$(tr -d '[:space:]' <"$TOKEN_FILE")"
fi

if [ -z "$TOKEN" ]; then
    # `read` fails at EOF, which under `set -e` killed this script silently.
    # Ask, but treat "no input" as an empty token rather than an abort.
    printf 'GitHub token for %s/%s: ' "$OWNER" "$REPO_NAME" >&2
    if [ -t 0 ]; then
        read -rs TOKEN || true
    else
        IFS= read -r TOKEN || true
    fi
    echo >&2
fi

if [ -z "$TOKEN" ]; then
    cat >&2 <<EOF
error: no token given.

Create one (needs Contents: Read and write on ${OWNER}/${REPO_NAME}):
  https://github.com/settings/tokens/new?scopes=repo&description=${REPO_NAME}

Then either paste it at the prompt, or save it once and rerun:
  printf '%s' 'THE_TOKEN' > ${TOKEN_FILE} && chmod 600 ${TOKEN_FILE}
EOF
    exit 1
fi

cd "$(dirname "$0")"

# Push with the token passed via askpass, so it never lands in .git/config.
export GIT_ASKPASS="$(mktemp)"
trap 'rm -f "$GIT_ASKPASS"' EXIT
cat >"$GIT_ASKPASS" <<EOF
#!/bin/sh
echo "$TOKEN"
EOF
chmod +x "$GIT_ASKPASS"

git remote remove origin 2>/dev/null || true
git remote add origin "https://${OWNER}@github.com/${OWNER}/${REPO_NAME}.git"
git -c credential.helper= push -u origin master

echo "pushed to https://github.com/${OWNER}/${REPO_NAME}"
echo "the 'tests' workflow runs on the first push; watch it at"
echo "  https://github.com/${OWNER}/${REPO_NAME}/actions"
