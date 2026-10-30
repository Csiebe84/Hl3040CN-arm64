#!/usr/bin/env python3
"""Ueberblick ueber alle Agenten-Conversations: Status, Aktivitaet, letzte Aktion.

Aufruf:  monitor_agents.py [--loop SECONDS]
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
import time
from pathlib import Path

CONV = Path("/root/esp32-IR/workspace/conversations")
API = "http://127.0.0.1:8000/api/conversations/search?limit=100"

LABELS = {
    "7fc18fd1": "Admin/Driver",
    "4d6ddbbf": "Fine-Modus",
    "57750776": "Task B gray",
    "89627819": "Buderus",
    "67b45a59": "ESP32-C6",
    "f57e9fea": "CI-green",
    "d2b74d33": "Emulator",
}


def api() -> list[dict]:
    try:
        out = subprocess.run(["curl", "-s", "-m", "15", API],
                             capture_output=True, text=True, timeout=25).stdout
        return json.loads(out).get("items") or []
    except Exception:
        return []


def conv_dir(cid: str) -> Path | None:
    m = list(CONV.glob(cid + "*"))
    return m[0] if m else None


def last_action(cid: str, n: int = 2) -> list[str]:
    d = conv_dir(cid)
    if not d:
        return ["(Ordner fehlt)"]
    fs = sorted(glob.glob(str(d / "events" / "event-*.json")))
    out: list[str] = []
    for f in reversed(fs):
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if e.get("kind") != "ActionEvent":
            continue
        a = e.get("action", {}) or {}
        c = a.get("command") or a.get("path") or a.get("content") or ""
        if isinstance(c, str) and c.strip():
            out.append(f"[{a.get('kind','?')}] " + c.strip().replace("\n", " ")[:110])
        if len(out) >= n:
            break
    return out or ["(keine Aktion)"]


def events_in(cid: str, minutes: int) -> int:
    d = conv_dir(cid)
    if not d:
        return 0
    try:
        return len(subprocess.run(
            ["find", str(d / "events"), "-name", "event-*.json",
             "-newermt", f"-{minutes} minutes"],
            capture_output=True, text=True, timeout=20).stdout.split())
    except Exception:
        return 0


def total_events(cid: str) -> int:
    d = conv_dir(cid)
    return len(glob.glob(str(d / "events" / "event-*.json"))) if d else 0


def mem() -> str:
    try:
        d = [int(x) for x in Path("/sys/block/zram0/mm_stat").read_text().split()[:9]]
        ds = int(Path("/sys/block/zram0/disksize").read_text())
        return (f"zram {d[0]/1048576:.0f}/{ds/1048576:.0f} MB "
                f"({100*d[0]/ds:.0f}%, frei {(ds-d[0])/1048576:.0f} MB)")
    except Exception:
        return "zram n/a"


def report() -> None:
    items = api()
    run = [c for c in items if c.get("execution_status") == "running"]
    print(f"\n{'='*94}")
    print(f"  {time.strftime('%H:%M:%S')}   {len(run)} laufen / {len(items)} gesamt"
          f"   Last {Path('/proc/loadavg').read_text().split()[0]}"
          f"   Kerne {Path('/sys/devices/system/cpu/online').read_text().strip()}")
    print(f"  {mem()}")
    print(f"{'='*94}")
    for c in sorted(items, key=lambda x: x.get("updated_at") or "", reverse=True):
        i = c["id"][:8]
        st = c.get("execution_status", "?")
        if st not in ("running", "waiting_for_confirmation"):
            continue
        tag = LABELS.get(i, "")
        print(f"\n  {i}  {st:9s} {tag:12s} {total_events(i):5d} Events"
              f"  (+{events_in(i,5)} in 5min)")
        for a in last_action(i):
            print(f"      {a}")


if __name__ == "__main__":
    loop = 0
    if "--loop" in sys.argv:
        loop = int(sys.argv[sys.argv.index("--loop") + 1])
    if loop:
        while True:
            report()
            time.sleep(loop)
    else:
        report()
