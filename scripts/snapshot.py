#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snapshot.py — snapshots of the Second Brain files that agents rewrite every day (audit, ISSUE-4).

The vault has no git and no Time Machine, and iCloud keeps only the latest version — a TASKS.md
broken by an agent could not have been restored from anything. Twice a day (launchd
com.example.secondbrain.snapshot: 08:40 — before the morning agents, 20:20 — before the evening ones)
this script copies the key files into

    ~/Library/Application Support/second-brain/snapshots/YYYY-MM-DD_HHMM/
        vault/<relative path>               — TASKS.md, CLAUDE.md, Daily for yesterday/today/tomorrow, …
        scheduled/<agent>/SKILL.md          — prompts of the Cowork scheduled agents (SECOND_BRAIN_SCHEDULED)

Snapshots live OUTSIDE the vault: otherwise copies of TASKS.md would show up in Obsidian search and
backlinks, agents would see them, and iCloud would evict them from disk. They are kept for
SNAPSHOT_KEEP_DAYS days; older ones are deleted by this same script (they are its own copies, not notes).

A file that iCloud has evicted from disk (dataless) is first requested back (`brctl download`, wait 20 s);
if it does not come back, it is skipped and noted in the manifest: a background read of such a file
can hang. (Eviction gets aggressive when the disk is nearly full — on 2026-10-06 only ~6% was free.)

Usage:   python3 snapshot.py [--vault PATH] [--dry-run]
         (vault defaults to $SECOND_BRAIN_VAULT, else ~/Vault)
Restore: copy the file back from snapshots/<stamp>/vault/<path> into the vault.
Reset:   delete the whole snapshots/ folder — the next run starts over.
"""
import argparse
import os
import shutil
import stat
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT", "~/Vault")).expanduser()
SCHEDULED = Path(os.environ.get("SECOND_BRAIN_SCHEDULED", "~/Documents/Claude/Scheduled")).expanduser()
SNAP_ROOT = Path.home() / "Library/Application Support/second-brain/snapshots"
SNAPSHOT_KEEP_DAYS = 30
SF_DATALESS = getattr(stat, "SF_DATALESS", 0x40000000)

# Vault layout (keep in sync with check_vault.py)
TASKS = "TASKS.md"
DAILY = "Daily"
ARCHIVE = "Archive"
VERSIONS_FILE = "Projects/Second Brain/Agent versions.md"
HOME_NOTE = "🏠 Home.md"


def vault_files(vault: Path, today: date) -> list[str]:
    days = [today - timedelta(days=1), today, today + timedelta(days=1)]
    months = {today.strftime("%Y-%m"), (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")}
    rel = [TASKS, "CLAUDE.md", "Data Governance.md", HOME_NOTE, VERSIONS_FILE]
    rel += [f"{DAILY}/{d.isoformat()}.md" for d in days]
    rel += [f"{ARCHIVE}/Done — {m}.md" for m in sorted(months)]
    return rel


def is_dataless(p: Path) -> bool:
    try:
        return bool(os.stat(p).st_flags & SF_DATALESS)
    except (OSError, AttributeError):
        return False


def materialize(p: Path, wait_s: int = 20) -> bool:
    """Asks iCloud to bring the file back to disk (brctl download) and waits. True — the file is local."""
    import subprocess, time
    if not is_dataless(p):
        return True
    try:
        subprocess.run(["brctl", "download", str(p)], timeout=15, check=False, capture_output=True)
    except Exception:
        return False
    for _ in range(wait_s):
        if not is_dataless(p):
            return True
        time.sleep(1)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot the vault files that agents rewrite daily.")
    ap.add_argument("--vault", default=str(DEFAULT_VAULT), help="vault path (default: $SECOND_BRAIN_VAULT or ~/Vault)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be copied, write nothing")
    a = ap.parse_args()
    vault = Path(a.vault).expanduser()
    if not (vault / TASKS).exists():
        print(f"vault not found: {vault}", file=sys.stderr)
        return 2

    now = datetime.now()
    dest = SNAP_ROOT / now.strftime("%Y-%m-%d_%H%M")
    plan = [(vault / r, Path("vault") / r) for r in vault_files(vault, now.date())]
    if SCHEDULED.is_dir():
        plan += [(p, Path("scheduled") / p.parent.name / p.name) for p in sorted(SCHEDULED.glob("*/SKILL.md"))]

    copied, skipped = [], []
    for src, rel in plan:
        if not src.exists():
            continue
        if is_dataless(src) and (a.dry_run or not materialize(src)):
            skipped.append(f"{rel} (evicted by iCloud and not back within 20 s — not reading it)")
            continue
        if a.dry_run:
            copied.append(str(rel))
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, out)
            copied.append(str(rel))
        except OSError as e:
            skipped.append(f"{rel} ({e.__class__.__name__}: {e})")

    if a.dry_run:
        print("DRY", dest, "\n  " + "\n  ".join(copied), "\nskipped:", skipped)
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.txt").write_text(
        f"snapshot {now.isoformat(timespec='seconds')}\ncopied {len(copied)}:\n"
        + "".join(f"  {c}\n" for c in copied)
        + (f"skipped {len(skipped)}:\n" + "".join(f"  {s}\n" for s in skipped) if skipped else ""),
        encoding="utf-8")

    cutoff = now - timedelta(days=SNAPSHOT_KEEP_DAYS)
    pruned = 0
    for d in SNAP_ROOT.iterdir():
        try:
            when = datetime.strptime(d.name, "%Y-%m-%d_%H%M")
        except ValueError:
            continue
        if d.is_dir() and when < cutoff:
            shutil.rmtree(d)
            pruned += 1

    print(f"{now:%Y-%m-%d %H:%M} OK snapshot {dest.name}: {len(copied)} files, skipped {len(skipped)}, pruned old {pruned}")
    return 1 if not copied else 0


if __name__ == "__main__":
    sys.exit(main())
