Execute Task C: decommission the i386 emulator path. The preparation is already
done — read it, do not redo it.

Read first, in this order:
  1. /root/brother/native/DECOMMISSION_PLAN.md   (the plan, read-only prep)
  2. /root/brother/native/prompts/task_c_emulator.md  (the step-by-step orders)
  3. /root/brother/native/HANDOVER-2026-10-25.md section "Task C"

## Why now (the blocker is gone)

The plan said the sole active blocker was conversation `4d6ddbbf` (Fine mode)
needing the oracle. That conversation is finished. The other oracle user
(`57750776`, gray-replace) is also finished and its work has LANDED as commit
`1792295`. Re-verify this yourself before acting — the plan gives the command:

    python3 /mnt/ssd/taskC/count_oracle.py brother-cups

and the running-conversation list:

    curl -s "http://127.0.0.1:8000/api/conversations/search?limit=100"

Only proceed if NO conversation in state `running` has a recent real
`docker exec brother-cups`. Do not be fooled by prose matches — the plan
explains why a plain grep gives false positives. Use the oracle script.

## Do this

Follow prompts/task_c_emulator.md steps 0-4. In short:

  Step 0  prove the container is not in the print path (PPD cupsFilter,
          the filter wrapper).
  Step 1  prove no running agent needs it (above).
  Step 2  `docker stop brother-cups` then
          `docker update --restart=no brother-cups`.
  Step 3  check whether anything else needs binfmt/qemu before removing the
          packages. If any other foreign-architecture image or add-on needs
          them, remove NOTHING and just document who needs them.
  Step 4  regression test: restart cups, print the test PostScript to the file
          queue `HL3040_TEST`, confirm the output is >30 KB, starts with
          `%-12345X@PJL` and contains `BROTHER XL2HB`.

## Hard rules

- Never `docker rm` the container and never delete the image. `docker stop` +
  `restart=no` only. The rollback must stay a single `docker start`.
- Do not run `apt-get remove` if anything else needs binfmt. Document instead.
- No success claim without visible command output.
- Write measurements to a log file, not just the screen.
- This is a shared machine and the agent-server is ONE process for all
  conversations: do NOT run `systemctl restart` broadly. `systemctl restart
  cups.service` is fine and expected; anything else, justify it.

## Report

Append to /root/brother/native/logs/emulator-removal.md:
- what was stopped, with the command and its output
- what was deliberately NOT removed, and why
- the regression-test result
- the exact rollback commands
- the current `docker ps -a` state and the qemu binfmt count
