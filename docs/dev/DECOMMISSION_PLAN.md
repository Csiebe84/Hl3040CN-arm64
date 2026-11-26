# Task C — Decommission the i386 emulator path (PREPARE ONLY, not executed)

Status: **READ-ONLY PREPARATION DONE. Nothing destructive executed.**
Author conversation: `d2b74d33-beda-4191-8715-317dfe7740a7`
Date: 2026-10-26 ~15:52 (blocker list corrected — see §1)
Source of truth: `HANDOVER-2026-10-25.md` §"Task C" + `TASK_C_EMULATOR.md`.

---

## 0. What is being decommissioned (scope)

The i386 emulator path exists **twice**; both are pure ballast once the native
filter is the only thing in the print path:

| # | Artifact | Detail |
|---|---|---|
| 1 | Container `brother-cups` | image `brother-hl3040cn:local` (arch **386/linux**, 209 MB), `RestartPolicy=unless-stopped`, `NetworkMode=bridge`, no published ports, RAM ~2.9 MiB. Runs `qemu-binfmt/i386-binfmt-P /usr/sbin/cupsd`. |
| 2 | binfmt_misc qemu registrations | **29** entries from `qemu-user-static 1:7.2+dfsg-7+deb12u18+b3` + `binfmt-support 2.2.2-2` (both `ii`). Conf files live in `/usr/lib/binfmt.d/qemu-*.conf` (owned by the packages, **not** `/etc/binfmt.d/` which is empty). |
| 3 | Container source/deploy dir | `/root/brother/brother-hl3040cn/` — Dockerfile, entrypoint.sh, deploy_brother_cups.sh, README.md, cupsd.conf. UID/GID 10001, mode 0700, **24 KB total**. |

The native print path is **already** emulator-free and is what both queues use:

```
/usr/lib/cups/filter/brhl3040cn-filter  (283 B bash)
  -> exec /usr/local/lib/brhl3040cn/.venv/bin/python3 \
          /usr/local/lib/brhl3040cn/brhl3040cn-filter.py "$@"
```
`lpstat -p` shows both `Brother_HL-3040CN` and `HL3040_TEST` idle/enabled.
The deployed filter (`brhl3040cn-filter.py`) has **no** docker/qemu call
(`import` list: itertools, logging, os, re, shutil, subprocess, sys, tempfile
+ local modules). The only docker reference in the deployed lib is
`extract_blobs.py` (a build-time blob extractor, **not imported** by the filter)
and inside pip's vendored pygments — both irrelevant to the print path.

---

## 1. BLOCKERS — do NOT stop the container or drop binfmt yet

### Counting method (corrected)

A plain string match (`grep "docker exec brother-cups"`) is **wrong** — it also
hits **prose**: task texts, thoughts, and even a conversation's *own
measurement commands* that embed the search string. That produced a false alarm
on `7fc18fd1`.

The correct count is over **executed commands only**:
- read the event JSON, keep only `action.kind == "TerminalAction"`,
- inspect `action.command`,
- ignore **heredoc bodies** (a message/task-text heredoc may contain the literal
  string) and any self-referential probe that merely *searches* for the string.

```bash
# ground truth: only real TerminalAction commands (see /mnt/ssd/taskC/count_oracle.py)
python3 /mnt/ssd/taskC/count_oracle.py brother-cups
```

### Real oracle usage (TerminalAction only)

| Conv (short) | Real calls | Last real `docker exec brother-cups` | Status | Verdict |
|---|---|---|---|---|
| **4d6ddbbf** ("Fix HL-3040CN Fine mode…") | **3** | **2026-10-26 15:43:14** | **running** | **THE ONLY ACTIVE BLOCKER** |
| 57750776 ("Fix gray-replace rule…") | 3 | 2026-10-26 04:54:00 | running | idle 11 h — low risk, may resume |
| 7fc18fd1 ("…driver for Odroid without emulator", admin chat) | 102 | **2026-10-26 11:29** | running | **NOT active** — all hits after 11:29 are prose/self-probes (see below) |
| d92e526d | 7 | 2026-10-25 17:13 | finished | — |
| 88b18202 | 2 | 2026-10-25 23:44 | finished | — |
| b207f1a3 | 1 | 2026-10-25 17:07 | finished | — |
| 711a23f0 | 0 | — | finished | prose only |
| d2b74d33 (this conversation) | 6 | 15:50 | running | our own status probes |
| 89627819 / 67b45a59 / f57e9fea | 0 | — | — | **never touched the oracle** |

**`7fc18fd1` is NOT a blocker.** Its last *genuine* exec is 11:29. Every match
after 11:29 is one of: `docker ps/inspect` status probes, a `find|grep` that
searches for the string, a `python -c` that counts events, or a
`cat > msg.json <<EOF` heredoc quoting the user's correction text. Verified by
printing the raw commands.

**Verdict: BLOCKED — sole active blocker is `4d6ddbbf` (Fine mode).**
It needs the oracle right now. `57750776` is running but idle 11 h (may resume)
→ treat as a secondary/soft blocker. Everything else is clear.

Re-check before acting:
```bash
python3 /mnt/ssd/taskC/count_oracle.py brother-cups   # real calls, newest last
curl -s "http://127.0.0.1:8000/api/conversations/search?limit=100" \
  | python3 -c "import sys,json;[print(x['id'][:8],x['execution_status']) for x in json.load(sys.stdin)['items']]"
```

---

## 2. Inventory — what would actually be removed / deactivated

Read-only facts gathered (no changes made):

```bash
docker ps -a --filter name=brother-cups --format '{{.Names}} {{.Status}} {{.Size}}'
#  brother-cups Up 36 minutes 175MB (virtual 384MB)

docker image inspect brother-hl3040cn:local --format '{{.Architecture}} {{.Os}} {{.Size}}'
#  386 linux 208504754
docker image inspect i386/debian:bookworm-slim --format '{{.Architecture}} {{.Os}}'
#  386 linux

dpkg -l | grep -Ei 'qemu|binfmt'
#  ii binfmt-support     2.2.2-2
#  ii qemu-user-static   1:7.2+dfsg-7+deb12u18+b3
#  ii qemu-system-arm / -common / -data   (NOT part of binfmt; leave alone)

ls /proc/sys/fs/binfmt_misc/ | grep -c qemu   # 29
cat /proc/sys/fs/binfmt_misc/qemu-i386        # enabled, interpreter i386-binfmt-P, flags POF

du -sh /root/brother/brother-hl3040cn/        # 24K  (uid 10001, mode 0700)
```

### binfmt safety check — is anything else foreign-arch?
```bash
docker images            # all other images are arm64:
#   home-assistant/aarch64-*      (arm64)
#   ghcr.io/home-assistant/aarch64-*
#   ghcr.io/home-assistant/odroid-n2-homeassistant  (arm64)
#   espressif/idf:v6.1            ->  arm64  (checked, NOT foreign)
#   victoriametrics/*             (arm64)
#   debian:bookworm-slim / trixie-slim  (arm64)
# ONLY foreign-arch images: brother-hl3040cn:local (386) + i386/debian:bookworm-slim (386)

grep -rl binfmt /etc/systemd /usr/local/sbin 2>/dev/null   # (empty)
grep -rl brother /etc/systemd/system 2>/dev/null           # (empty)
crontab -l                                                 # only acme.sh, unrelated
```
**Verdict: the ONLY consumer of binfmt in the i386 sense is the oracle container.
No HA add-on, no systemd unit, no cron, no other container image needs a foreign
architecture. Removing binfmt is safe *once the oracle is no longer in use*.**

> Note: `qemu-system-*` (full-system emulation) and `binfmt-support` are separate
> from `qemu-user-static`. The 29 registrations come from `qemu-user-static`;
> `binfmt-support` provides the registration glue. Both are removable together,
> or binfmt can be deactivated reversibly without touching packages (§3, step 3a).

---

## 3. The exact commands I WOULD run (with rollback per step)

> Do these **in order**, only after the user confirms the oracle is free.
> Nothing is deleted — every step has an inline rollback.

### Step 0 — capture current state (so rollback is exact)
```bash
mkdir -p /mnt/ssd/taskC
docker inspect brother-cups > /mnt/ssd/taskC/brother-cups.inspect.json
docker images --digests > /mnt/ssd/taskC/images.txt
dpkg -l | grep -Ei 'qemu|binfmt' > /mnt/ssd/taskC/packages.txt
ls -l /proc/sys/fs/binfmt_misc/ > /mnt/ssd/taskC/binfmt.list
```
Rollback: none needed (read-only; writes only to /mnt/ssd).

### Step 1 — stop the container (do NOT delete)
```bash
docker stop brother-cups
docker update --restart=no brother-cups
```
Rollback:
```bash
docker update --restart=unless-stopped brother-cups
docker start brother-cups
```
(Container ID is preserved; `docker rm` is deliberately NOT run.)

### Step 2 — verify the print path works WITHOUT the emulator
```bash
lpstat -p Brother_HL-3040CN
# real test page through the native filter (fixtures on /mnt/ssd, never /tmp):
lp -d Brother_HL-3040CN /mnt/ssd/taskC/testpage.ps
lpstat -o Brother_HL-3040CN          # job should drain, no error
# prove the native filter spawns no docker/qemu:
docker ps --filter name=brother-cups --format '{{.Names}} {{.Status}}'   # expect: Exited
pgrep -af 'qemu|docker exec'                                            # expect: (empty)
```
Rollback: `docker start brother-cups` (if the print test somehow regresses).

### Step 3a — deactivate binfmt for i386 ONLY (reversible, non-persistent)
Preferred "stop, keep rollback" option — disables the i386 handler without
removing any package; re-enabling is a one-liner and a reboot restores it.

> ⚠️ **This is GLOBAL.** `echo 0 > …/qemu-i386` disables the i386 handler for
> the whole host. While `4d6ddbbf` (or any conversation) still uses the oracle,
> their *next* `docker exec` would fail. **Only run this after the oracle is
> free — same gate as Step 1.** Do NOT run it during preparation.

```bash
echo 0 > /proc/sys/fs/binfmt_misc/qemu-i386     # disable i386 handler (GLOBAL)
cat /proc/sys/fs/binfmt_misc/qemu-i386          # shows "disabled"
```
Rollback:
```bash
echo 1 > /proc/sys/fs/binfmt_misc/qemu-i386     # re-enable instantly
```
(Other 28 qemu handlers are left untouched — minimal change.)

### Step 3b — OPTIONAL, only if the user wants it fully gone (persistent)
Removes all 29 registrations. **Only** do this if the user explicitly asks for
package removal and confirms nothing else needs foreign-arch execution.
```bash
apt-get remove --purge -y qemu-user-static binfmt-support
# (or, non-purging: apt-get remove -y qemu-user-static binfmt-support)
```
Rollback:
```bash
apt-get install -y qemu-user-static binfmt-support
systemctl restart systemd-binfmt    # re-register (or reboot)
```
> If you only ever want step 3a, skip 3b — it is the safest decommission with a
> guaranteed way back.

### Step 4 — the source dir
`/root/brother/brother-hl3040cn/` is **left in place** (24 KB). It is the
documented way back and costs nothing. Do **not** delete it unless the user asks.

---

## 4. Explicitly NOT doing
- No `docker rm`, no `docker rmi`, no `apt-get remove` during this preparation phase.
- No `systemctl restart` / no touching the agent-server (one process, all conversations).
- No changes to other conversations' files.
- No re-run of the Task-A byte comparison (already proven, per handover).

---

## 5. Open question to the user
Re-measured with the correct method (TerminalAction only): the **sole active
oracle user is `4d6ddbbf`** ("Fix HL-3040CN Fine mode…"), last real
`docker exec brother-cups` at **15:43**. `57750776` (Task B gray) is `running`
but idle since 04:54 (may resume) → soft blocker. `7fc18fd1` is **not** a
blocker (last genuine exec 11:29; later hits are prose/self-probes).
`89627819`, `67b45a59`, `f57e9fea` never touched the oracle.

**Confirm when `4d6ddbbf` (and ideally `57750776`) are `finished`** (or
explicitly released) and I will execute Steps 1–2, then 3a (or 3b if you want the
packages gone). Until then: nothing is executed — the container stays up and the
binfmt handlers stay enabled.
