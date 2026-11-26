Push the verified work to GitHub and make CI green. This is the delivery step
for the task "publish finished work privately to GitHub".

Repo: Csiebe84/Hl3040CN-arm64  (PRIVATE)   branch `master`
Local root: /root/brother/native
`GITHUB_TOKEN` is set in the environment. There is no `gh` CLI installed; use
the REST API with curl, or `git push` with the token in the remote URL.

## State right now

Two commits are ahead of `origin/master` and are NOT yet pushed:

    b12267a  Pin the verified Fine-mode CAPT separation and plane-presence rules
    1792295  BRGray is a whole-page grid selection, not a per-pixel rule

`origin/master` is at `f5599f8`. Both commits are locally verified: the
board-free test suites pass. There are also UNCOMMITTED changes to
`hl3040cn/src/dither.py` and `hl3040cn/src/test_fine_mode.py` — leave those
alone, another conversation owns them and they are under verification. Do NOT
commit or push them.

## Task 1 — make CI green locally first

CI workflow: `.github/workflows/tests.yml`. It was made blob-safe earlier
(commit 23be78c added a `require_blobs` guard). Verify that is actually
sufficient by simulating a fresh checkout where the proprietary blobs are
absent:

    hl3040cn/src/lut/          (BRCD dither tables)
    hl3040cn/src/color_data/   (colour grids, inverse_lut.npy)

Those directories exist locally, which hides the CI failure. Reproduce CI
honestly: copy the repo to a temp dir (or use `git archive HEAD`), remove the
two blob directories from the COPY, and run every test file there with
`python3 -m unittest`. Report which tests skip and which fail.

If any test FAILS without the blobs, add the missing skip guard in the style
already used (`@require_blobs(...)` from `test_blobs`, or
`@unittest.skipUnless(pipeline.HAS_BAND_KERNEL, ...)`). Fix the guard, not the
test's meaning.

Then run the full suite WITH the blobs present and confirm everything passes.

## Task 2 — push

Push the two commits to `origin/master`. Use the token:

    git push https://x-access-token:$GITHUB_TOKEN@github.com/Csiebe84/Hl3040CN-arm64.git master

Do NOT force-push. Do NOT push any other branch. Do NOT push the uncommitted
`dither.py` / `test_fine_mode.py` changes.

## Task 3 — watch CI and fix what is genuinely broken

Poll the Actions runs for the pushed SHA:

    curl -s -H "Authorization: token $GITHUB_TOKEN" \
      "https://api.github.com/repos/Csiebe84/Hl3040CN-arm64/actions/runs?per_page=5"

Wait for the run on your SHA to finish (allow a few minutes; poll, do not sleep
blindly). If it fails, read the failing step's log and fix the cause. Only fix
genuine failures in code or workflow; never weaken a test or skip it just to get
green — a skip is only acceptable when it guards a missing proprietary blob.

## Constraints

- Never commit the blobs themselves (`lut/`, `color_data/` are gitignored on
  purpose — Brother's data is proprietary and must not be published).
- Never commit the `tools/graytol_*.py` / `tools/grid_*.py` exploration scripts
  or the `backup-quality-*` directory.
- Do not touch `dither.py` or `test_fine_mode.py`.
- If the push is rejected (auth, protected branch), report the exact error and
  stop — do not force anything.

## Report

Say: which tests skip without blobs and whether any had to be guarded, the
pushed SHA, the final CI conclusion, and the run URL. If CI is red and you could
not fix it, give the failing step and the error text.
