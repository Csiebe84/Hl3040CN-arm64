Decommission the i386 emulator path for the HL-3040CN print pipeline on this
Odroid N2+ (arm64). The native ARM64 driver already works and is proven
byte-identical to the emulator; the emulator is now pure ballast.

Project root: /root/brother/native
Read first: /root/brother/native/HANDOVER-2026-10-25.md, section "Task C —
Emulator-Treiber: offen (VORSICHT)". It has the exact inventory and the
recommended steps. Do not re-derive it.

WHAT EXISTS TODAY (verified, do not re-measure):
1. Docker container `brother-cups` (i386 image `brother-hl3040cn:local`,
   RestartPolicy=unless-stopped, 2.9 MiB RAM, no ports published).
2. binfmt_misc: 29 qemu registrations from `qemu-user-static` +
   `binfmt-support` (currently loaded).
3. Source/deploy for the container: /root/brother/brother-hl3040cn/
   (Dockerfile, entrypoint.sh, deploy_brother_cups.sh, README.md; UID 10001,
   mode 0700).

BOTH queues (Brother_HL-3040CN, HL3040_TEST) already use the native filter
(/usr/lib/cups/filter/brhl3040cn-filter -> .venv python). The container is not
in the print path.

*** CRITICAL — DO NOT START THE DESTRUCTIVE PART YET ***
As of now, TWO other conversations are STILL USING the oracle container:
  4d6ddbbf  (Fine mode)   and   67b45a59  (ESP32 firmware)
Both run `docker exec brother-cups`. If you stop/remove the container or drop
the binfmt handlers while they work, you break their runs mid-task.

So: do the SAFE, READ-ONLY preparation first and REPORT, then wait.
  - Confirm the current user list of the oracle with:
      find /root/esp32-IR/workspace/conversations -name "event-*.json" \
        -newermt "-20 minutes" | xargs grep -l "docker exec" | \
        sed 's|.*/conversations/||;s|/events.*||' | sort -u
    Any id that is still `running` (check
    http://127.0.0.1:8000/api/conversations/search?limit=100) is a BLOCKER.
  - Inventory what would be removed (package list, container, source dir).
  - Check whether anything else needs binfmt: `docker images` for foreign
    architectures, and `grep -rl binfmt /etc/systemd /usr/local/sbin 2>/dev/null`.
    Report what you find; do NOT remove packages if anything still needs them.
  - Write the exact commands you WOULD run into
    /root/brother/native/DECOMMISSION_PLAN.md, including the rollback for each
    step (container: `docker start`; packages: `apt-get install`).
  - Then message the user with the plan and the current blocker list, and STOP.

Only after the user says the other agents are done:
  - `docker stop brother-cups && docker update --restart=no brother-cups`
    (stop, do NOT delete — keep the way back open).
  - Verify the print path still works WITHOUT the emulator:
    `lpstat -p Brother_HL-3040CN` and a real test page through the native
    filter. Prove the native filter does not call docker.
  - Then handle binfmt ONLY if the inventory says it is safe.

Rules:
- Do not delete anything. Stop/deactivate, keep rollback.
- Do not touch other conversations' files.
- Do not restart the agent-server (it is ONE process for all conversations).
- If unsure whether something still needs the emulator, leave it and say so.
  A clean stop with an open question beats a broken print path.
- Write test fixtures to /mnt/ssd, never /tmp (tmpfs, tight RAM).

Report: what is blocked, what is ready, and the exact commands you would run.
