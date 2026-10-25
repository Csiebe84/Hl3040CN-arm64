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
TOKEN="${GH_TOKEN:-}"

if [ -z "$TOKEN" ]; then
    # Read it here rather than taking it on the command line: a token given
    # as an argument or as GH_TOKEN=... ends up in the shell history.
    printf 'GitHub token (needs Contents: Read and write on %s): ' "$REPO_NAME" >&2
    read -rs TOKEN
    echo >&2
fi

if [ -z "$TOKEN" ]; then
    echo "error: no token given" >&2
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
