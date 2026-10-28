#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_vault.py — morning invariant check for a Second Brain (Obsidian vault).

A dumb, deterministic checker: it reads files, compares them with the rules from
Data Governance / CLAUDE.md, fixes only what is SAFE (move files out of a resurrected
Archive/Inbox, move exact duplicates into _to_delete/; before v4 it also created a missing
Daily note), and writes everything else into a report. The report is read by the morning
briefing agent (daily-focus-briefing).

Usage:  python3 check_vault.py [--vault PATH] [--dry-run] [--days 3]
        (vault defaults to $SECOND_BRAIN_VAULT, else ~/Vault)
Output: <vault>/Inbox/System check — YYYY-MM-DD.md   (overwritten, idempotent)
        + a line in <vault>/Inbox/Runs — YYYY-MM.md
        + a macOS notification if there are NEW warnings (not seen in the last 48 h)
"New vs known" bookkeeping: ~/Library/Logs/second-brain/checkvault.seen.json.
        Reset: delete that file — the next run treats everything current as known, without a notification.
Test the notification: python3 check_vault.py --test-notify

v2.7 (2026-10-19, "Instructions v4 (no Daily)"): v4 mode switches on by itself when the agent
versions table expects daily-focus-briefing at version >= 4.0. In v4 mode Daily notes are neither
created nor read; instead of the Daily checks there are: the four TASKS.md sections, "❓ Decide" <= 10,
❓ questions older than 14 days, and new Daily/*.md after DAILY_LAST (= an agent still on an old prompt).
A catch-up run for yesterday (a log line before 12:00, or "catch-up for dd.mm") counts as a run.
"""
import argparse
import hashlib
import os
import re
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

# ---------------------------------------------------------------- vault layout (rename here only)
DEFAULT_VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT", "~/Vault")).expanduser()

INBOX = "Inbox"
INBOX_AI = "Inbox/AI Sessions"          # raw AI-session exports land here
INBOX_FILES = "Inbox/Files"             # attachments / voice notes from the Telegram bot
TELEGRAM = "Telegram"                   # Telegram Sync plugin + tg_pull backstop write here
SESSIONS = "Sessions"                   # one digest per day: Sessions/YYYY-MM-DD.md
DAILY = "Daily"                         # Daily/YYYY-MM-DD.md (retired in v4)
ARCHIVE = "Archive"                     # Archive/YYYY-MM/...
TO_DELETE = "_to_delete"                # nothing is deleted by agents; it is moved here
DUPES = "duplicates"                    # _to_delete/duplicates/
TASKS = "TASKS.md"
DAILY_TEMPLATE = "Templates/Daily Note.md"
WORK_FOLDERS = ("Meetings", "Work", "Projects")   # "a session happened" traces
SCRIPTS_MASTER_DIR = "Projects/Second Brain"      # master copies of these scripts inside the vault
VERSIONS_FILE = "Projects/Second Brain/Agent versions.md"

# file-name prefixes inside Inbox/
RUN_LOG_PREFIX = "Runs — "              # Inbox/Runs — YYYY-MM.md
PROCESSED_PREFIX = "Processed — "       # Inbox/Processed — YYYY-MM-DD.md (inbox-processing report)
CHECK_REPORT_PREFIX = "System check — " # Inbox/System check — YYYY-MM-DD.md (this script)
DOCTOR_PREFIX = "Doctor — "             # Inbox/Doctor — YYYY-MM-DD.md (system-doctor report)

# markers that agents write into their output files
PROCESSED_EVENING = "Evening"           # section in the Processed report written by the evening run
PROCESSED_MORNING = "Morning"           # ... and by the morning run
NO_SESSIONS = "No sessions"             # Sessions/<day>.md body when nothing was captured
CATCHUP_TAG = "catch-up for"            # run-log note of a late catch-up run: "catch-up for dd.mm"
BACKLOG_NAME = "Backlog"                # backlog files are touched often; ignore as session traces

# TASKS.md sections
SEC_TODAY = "## 🔥 Today"
SEC_DECIDE = "## ❓ Decide"
SEC_WEEK = "## 📅 This week"
SEC_LATER = "## 📥 Later"

# outside the vault (not synced by iCloud)
LOG_DIR = Path.home() / "Library/Logs/second-brain"
APP_DIR = Path.home() / "Library/Application Support/second-brain"
SCHEDULED_DIR = Path(os.environ.get("SECOND_BRAIN_SCHEDULED", "~/Documents/Claude/Scheduled")).expanduser()
EXPORT_SCRIPT = Path.home() / ".claude/export-to-obsidian.py"
SNAPSHOT_LABEL = "com.example.secondbrain.snapshot"

EN_WD = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EN_MON = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

CHECK_VERSION = "2.7"
EVENING_AGENTS = ["ai-sessions-capture", "daily-inbox-processing"]   # the live list is in the agent versions table
MORNING_AGENT = "daily-focus-briefing"


def load_expected_versions(vault):
    """-> dict[agent] = (version|None, status, schedule) from the agent versions table"""
    out = {}
    for line in read(vault / VERSIONS_FILE).splitlines():
        if not line.startswith("| ") or line.startswith("| Agent") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        agent, version, status, schedule = cells[0], cells[1], cells[2], cells[3]
        out[agent] = (version if re.fullmatch(r"\d+(\.\d+)*", version) else None, status, schedule)
    return out
TASKS_SECTIONS_V3 = [SEC_TODAY, SEC_WEEK, SEC_LATER]
TASKS_SECTIONS_V4 = [SEC_TODAY, SEC_DECIDE, SEC_WEEK, SEC_LATER]
ASK_LIMIT = 10          # "❓ Decide" — at most 10 questions (CLAUDE.md §2)
ASK_OLD_DAYS = 14       # an older question is a candidate to answer or drop (weekly-summary v3.0)
DAILY_LAST = date(2026, 10, 19)   # the last Daily note; since v4 there must be no new ones


def is_v4(vault) -> bool:
    """v4 (no Daily) is in force when the versions table expects the morning briefing at >= 4.0."""
    want = load_expected_versions(vault).get(MORNING_AGENT, (None,))[0]
    try:
        return want is not None and int(want.split(".")[0]) >= 4
    except ValueError:
        return False
LATER_LIMIT = 30
TASK_LINE_MAX = 110


class Report:
    def __init__(self):
        self.ok, self.fixed, self.warn, self.info = [], [], [], []
        self.new = []          # warnings not seen during the last SEEN_GAP_H hours
        self.since = {}        # warning text -> date it has been hanging since (for known ones)
        self.seeded = False    # first run of the bookkeeping: everything current counts as known

    def status(self):
        if self.warn:
            return "warn"
        if self.fixed:
            return "fixed"
        return "ok"


# ---------------------------------------------------------------- new vs known (audit, ISSUE-3)
# For about two weeks (2026-09-25 .. 10-06) the check never once said "ok": the same warnings hung
# there every day, and a genuinely new breakage (Telegram) looked exactly like yesterday's noise.
# Now the check remembers what it has already seen: new items get their own block at the top of the
# report plus a macOS notification; known ones go below with a "since" date.
SEEN_PATH = LOG_DIR / "checkvault.seen.json"
SEEN_GAP_H = 48        # gone for more than 48 h and back again -> "new" again
SEEN_KEEP_DAYS = 30


def warn_key(text: str) -> str:
    """Stable key for a warning: no digits/dates, and no tail that changes from run to run."""
    t = re.sub(r"\d+", "#", text.lower())
    t = re.sub(r"[*`]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    colon = t.find(":", 25)
    return t[:colon] if 0 < colon <= 90 else t[:70]


def classify_warnings(rep, dry):
    import json
    now = datetime.now()
    try:
        seen = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = None
    if seen is None:
        rep.seeded = True
        seen = {}
    for w in rep.warn:
        k = warn_key(w)
        e = seen.get(k)
        fresh = e is None or (now - datetime.fromisoformat(e["last"])).total_seconds() > SEEN_GAP_H * 3600
        if fresh:
            if not rep.seeded:
                rep.new.append(w)
            seen[k] = {"first": now.isoformat(timespec="minutes"), "last": now.isoformat(timespec="minutes")}
        else:
            e["last"] = now.isoformat(timespec="minutes")
        rep.since[w] = seen[k]["first"][:10]
    cutoff = now - timedelta(days=SEEN_KEEP_DAYS)
    seen = {k: v for k, v in seen.items() if datetime.fromisoformat(v["last"]) >= cutoff}
    if not dry:
        SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")


def notify(title: str, text: str) -> None:
    import subprocess
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}"'],
                       timeout=15, check=False, capture_output=True)
    except Exception as e:
        print(f"notification not sent: {e!r}", file=sys.stderr)


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def fmt_d(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def run_log(vault: Path, month: str) -> Path:
    return vault / INBOX / f"{RUN_LOG_PREFIX}{month}.md"


def processed_report(vault: Path, day: str) -> Path:
    return vault / INBOX / f"{PROCESSED_PREFIX}{day}.md"


def daily_from_template(vault: Path, d: date) -> str:
    tpl = read(vault / DAILY_TEMPLATE)
    if not tpl:
        tpl = ("---\ndate: {{date:YYYY-MM-DD}}\n---\n\n# {{date:dddd, D MMMM}}\n\n## Focus — max 3\n\n"
               "## Inbox of the day\n\n## To sort\n\n## Evening — 5 minutes\n\n"
               "- Done:\n- Carried over and why:\n- Thought of the day:\n")
    title = f"{EN_WD[d.weekday()]}, {d.day} {EN_MON[d.month - 1]}"
    out = tpl.replace("{{date:YYYY-MM-DD}}", fmt_d(d)).replace("{{date:dddd, D MMMM}}", title)
    out = out.replace("## To sort\n", "## To sort\n\n*(note created by the morning check — the evening agent did not create it; the \"To sort\" queue is empty)*\n", 1)
    return out


# ---------------------------------------------------------------- checks

def check_daily(vault, today, rep, dry):
    if is_v4(vault):
        # v4: no Daily notes. A new Daily after DAILY_LAST = some scheduled task is still on an old prompt.
        d = vault / DAILY
        fresh = sorted(p.name for p in d.glob("2*.md") if p.stem > fmt_d(DAILY_LAST)) if d.exists() else []
        if fresh:
            rep.warn.append(f"Daily notes are being created again after the switch to v4 ({', '.join(fresh[:3])}) — some agent "
                            f"is running an old prompt: check the versions in the run log, update the prompt in Cowork")
        else:
            rep.ok.append("v4: no new Daily notes")
        return
    p = vault / DAILY / f"{fmt_d(today)}.md"
    if p.exists():
        rep.ok.append(f"{DAILY}/{fmt_d(today)}.md is in place")
        return
    if dry:
        rep.warn.append(f"{DAILY}/{fmt_d(today)}.md is missing (dry-run: not creating it)")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(daily_from_template(vault, today), encoding="utf-8")
    rep.fixed.append(f"{DAILY}/{fmt_d(today)}.md was not created by the evening agent (ai-sessions-capture, part 2) — created it from the template, \"To sort\" is empty")


RUN_RE = re.compile(r"^-\s*(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})\s*\|\s*([\w-]+)(?:\s+v([\d.]+))?\s*\|\s*(\w+)\s*\|?\s*(.*)$")


def parse_runs(vault, months):
    """-> dict[(date_str, agent)] = (time, status, note, version)"""
    runs = {}
    for m in months:
        for line in read(run_log(vault, m)).splitlines():
            mm = RUN_RE.match(line.strip())
            if mm:
                d, t, agent, ver, st, note = mm.groups()
                runs[(d, agent)] = (t, st, note, ver)
    return runs


def parse_runs_all(vault, months):
    """-> list[(date_str, time, agent, status, note)] — every line, not just the last one of the day"""
    out = []
    for m in months:
        for line in read(run_log(vault, m)).splitlines():
            mm = RUN_RE.match(line.strip())
            if mm:
                d, t, agent, _v, st, note = mm.groups()
                out.append((d, t, agent, st, note))
    return out


def find_catchup(all_runs, d: date, agent):
    """Catch-up for evening d: an agent line on d+1 before 12:00 (CLAUDE.md §2.6), or a line on d+1/d+2 with "catch-up for … dd.mm"."""
    tag = f"{d.day:02d}.{d.month:02d}"
    nxt = {fmt_d(d + timedelta(days=1)), fmt_d(d + timedelta(days=2))}
    for rd, rt, ag, st, note in all_runs:
        if ag != agent or rd not in nxt:
            continue
        if re.search(re.escape(CATCHUP_TAG) + r"[^|]*?" + re.escape(tag), note) or (rd == fmt_d(d + timedelta(days=1)) and rt < "12:00"):
            return (rt, st, note, rd)
    return None


def check_versions(vault, today, rep, days=7):
    """the live version of each agent (last stamp in the run log) vs. the agent versions table"""
    expected = load_expected_versions(vault)
    if not expected:
        rep.info.append(f"{VERSIONS_FILE} not found or empty — version check skipped")
        return
    months = sorted({(today - timedelta(days=i)).strftime("%Y-%m") for i in range(days + 1)})
    runs = parse_runs(vault, months)
    for agent, (want, status, sched) in expected.items():
        if not want or not status.startswith("active"):
            continue
        if agent in ("check-vault", "tg-pull"):
            continue  # scripts: check-vault stamps its own version; tg-pull liveness is checked separately
        last = None
        for i in range(0, days + 1):
            key = (fmt_d(today - timedelta(days=i)), agent)
            if key in runs:
                last = runs[key]; break
        if last is None:
            rep.info.append(f"{agent}: not a single run-log line in {days} days (schedule \"{sched}\") — never ran, or the task was never created")
            continue
        got = last[3]
        # Blind spot found 2026-10-11: a weekly agent may have no run at all between a rollout and its slot.
        # If the file in Scheduled/ is newer than the last log line and the rollout is < 8 days old,
        # report "has not run yet" instead of a version mismatch.
        skill = SCHEDULED_DIR / agent / "SKILL.md"
        if got != want and not sched.startswith("daily") and skill.exists():
            rolled = datetime.fromtimestamp(skill.stat().st_mtime)
            last_dt = datetime.strptime(f"{fmt_d(today - timedelta(days=i))} {last[0]}", "%Y-%m-%d %H:%M")
            if last_dt < rolled and (datetime.now() - rolled).days < 8:
                rep.info.append(f"{agent}: v{want} rolled out {rolled:%d.%m}, its \"{sched}\" slot has not come up since — "
                                f"the log still says v{got}; paste the prompt into Cowork if you haven't yet")
                continue
        if got is None:
            rep.warn.append(f"{agent}: no version in the run log, expected v{want}. The file in Scheduled/ may already be new — "
                            f"update the prompt inside the Cowork task itself and run it manually")
        elif got != want:
            rep.warn.append(f"{agent}: run log says v{got}, expected v{want}. The file in Scheduled/ may already be new — "
                            f"update the prompt inside the Cowork task itself and run it manually")
        else:
            rep.ok.append(f"{agent} v{got} — version matches")


def check_runs(vault, today, rep, days):
    months = sorted({(today - timedelta(days=i)).strftime("%Y-%m") for i in range(days + 1)})
    runs = parse_runs(vault, months)
    all_runs = parse_runs_all(vault, sorted({(today - timedelta(days=i)).strftime("%Y-%m") for i in range(days + 3)}))
    if not runs:
        rep.info.append(f"Run log {INBOX}/{RUN_LOG_PREFIX}YYYY-MM.md is empty or not kept yet — checking by traces in files")
    for i in range(1, days + 1):
        d = today - timedelta(days=i)
        ds = fmt_d(d)
        # traces of evening d: Processed — d (the evening section), Sessions/d
        obr = read(processed_report(vault, ds))
        traces = {
            "daily-inbox-processing": (PROCESSED_EVENING in obr) or (vault / SESSIONS / f"{ds}.md").exists(),
            # writes into today's Daily — by mtime it is indistinguishable from the user's own edits,
            # so only the run log counts
            "ai-sessions-capture": None,
        }
        for agent in EVENING_AGENTS:
            key = (ds, agent)
            if key in runs:
                t, st, note, _v = runs[key]
                if st.lower() != "ok":
                    short = note if len(note) <= 220 else note[:220].rstrip() + "…"
                    rep.warn.append(f"{ds} {agent} finished with status {st}: {short}")
                continue
            cu = find_catchup(all_runs, d, agent)
            if cu:
                rt, st, note, rd = cu
                if st.lower() not in ("ok", "warn"):
                    rep.warn.append(f"{ds} {agent}: catch-up {rd} {rt} finished with status {st}")
                else:
                    rep.ok.append(f"{ds} {agent}: caught up on {rd[8:10]}.{rd[5:7]} at {rt}")
                continue
            tr = traces.get(agent)
            if tr is True:
                rep.info.append(f"{ds} {agent}: no run-log line, but there are traces of work — prompt without the log-line step?")
            elif tr is False:
                if i == 1:
                    rep.warn.append(f"{ds} {agent}: run not found (no log line, no traces). Was the Mac asleep/off? Tonight's evening run should widen its collection window")
                else:
                    rep.info.append(f"{ds} {agent}: did not run (Mac asleep/off)")
        # the morning agent, for yesterday
        if (ds, MORNING_AGENT) not in runs and PROCESSED_MORNING not in obr and i == 1:
            rep.info.append(f"{ds} {MORNING_AGENT}: no log line")


def check_archive_inbox(vault, rep, dry):
    bad = vault / ARCHIVE / INBOX
    if not bad.exists():
        rep.ok.append(f"{ARCHIVE}/{INBOX} has not come back")
        return
    moved = 0
    for p in sorted(bad.rglob("*")):
        if p.is_dir() or p.name == ".DS_Store":
            continue
        rel = p.relative_to(bad)  # e.g. 2026-08/AI Sessions/x.md
        parts = rel.parts
        month = parts[0] if re.match(r"\d{4}-\d{2}$", parts[0]) else datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m")
        sub = Path(*parts[1:-1]) if len(parts) > 2 else Path()
        dst = vault / ARCHIVE / month / sub / p.name
        if dst.exists():
            dst = vault / TO_DELETE / DUPES / p.name
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            p.rename(dst)
        moved += 1
    if moved:
        rep.fixed.append(f"{ARCHIVE}/{INBOX}/ came back — {moved} file(s) moved to {ARCHIVE}/YYYY-MM/ (some agent writes using the old layout; check step 10.5 of the evening prompt)")
    else:
        rep.info.append(f"{ARCHIVE}/{INBOX}/ exists but is empty — can be moved to {TO_DELETE}/")


def stale_files(folder: Path, older_days: float, exclude=()):
    out = []
    if not folder.exists():
        return out
    cutoff = datetime.now() - timedelta(days=older_days)
    for p in folder.iterdir():
        if not p.is_file() or p.name.startswith(".") or p.name in exclude:
            continue
        if any(p.name.startswith(e) for e in exclude if e.endswith("—")):
            continue
        if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
            out.append(p)
    return out


def check_inbox_stale(vault, rep):
    ai = stale_files(vault / INBOX_AI, 2)
    if ai:
        rep.warn.append(f"{INBOX_AI}: {len(ai)} file(s) older than 2 days not collected into {SESSIONS}/ — the evening run did not pick them up: " + ", ".join(p.name[:40] for p in ai[:3]))
    root = [p for p in stale_files(vault / INBOX, 2)
            if p.suffix == ".md" and p.name != "README.md"
            and not p.name.startswith((PROCESSED_PREFIX, RUN_LOG_PREFIX, CHECK_REPORT_PREFIX))
            # the system-doctor report stays in Inbox for a week: the morning briefing reads it (<= 7 days)
            and not (p.name.startswith(DOCTOR_PREFIX) and (datetime.now().timestamp() - p.stat().st_mtime) < 8 * 86400)]
    if root:
        rep.warn.append(f"{INBOX}/: {len(root)} file(s) older than 2 days are stuck unprocessed: " + ", ".join(p.name[:40] for p in root[:3]))
    tg = [p for p in stale_files(vault / TELEGRAM, 2) if p.suffix == ".md"]
    if tg:
        rep.warn.append(f"{TELEGRAM}/: {len(tg)} notes older than 2 days not processed")
    files = vault / INBOX_FILES
    if files.exists():
        audio = [p for p in stale_files(files, 2) if p.suffix.lower() in (".oga", ".ogg", ".mp3", ".wav", ".m4a")]
        if audio:
            rep.warn.append(f"{INBOX_FILES}: {len(audio)} audio file(s) older than 2 days — no transcript, or the bot did not process them")
    if not (ai or root or tg):
        rep.ok.append(f"{INBOX}/ and {TELEGRAM}/ have no stuck files")


def check_duplicates(vault, rep, dry):
    """exact duplicates (same content) between Inbox/* and Archive/** -> move the Inbox copy to _to_delete/duplicates/"""
    arch = {}
    for p in (vault / ARCHIVE).rglob("*.md"):
        try:
            arch.setdefault(sha(p), p)
        except Exception:
            pass
    moved = []
    for folder in (INBOX, INBOX_AI, INBOX_FILES, TELEGRAM):
        f = vault / folder
        if not f.exists():
            continue
        for p in f.iterdir():
            if not p.is_file() or p.suffix != ".md" or p.name == "README.md" or p.name.startswith((PROCESSED_PREFIX, RUN_LOG_PREFIX, CHECK_REPORT_PREFIX)):
                continue
            h = sha(p)
            if h in arch:
                if not dry:
                    dst = vault / TO_DELETE / DUPES / p.name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        dst = dst.with_name(dst.stem + "~" + dst.suffix)
                    p.rename(dst)
                moved.append((p.name, arch[h].relative_to(vault)))
    if moved:
        rep.fixed.append(f"{len(moved)} exact duplicate(s) of already archived files moved from Inbox/Telegram to {TO_DELETE}/{DUPES}/ (the Claude Code exporter re-exported them?): " + "; ".join(f"{a[:35]} = {b}" for a, b in moved[:3]))
    else:
        rep.ok.append(f"No duplicates between {INBOX} and {ARCHIVE}")


def check_tasks(vault, rep, today=None):
    t = read(vault / TASKS)
    if not t:
        rep.warn.append(f"{TASKS} cannot be read")
        return
    v4 = is_v4(vault)
    TASKS_SECTIONS = TASKS_SECTIONS_V4 if v4 else TASKS_SECTIONS_V3
    heads = [l for l in t.splitlines() if l.startswith("## ")]
    extra = [h for h in heads if not any(h.startswith(s) for s in TASKS_SECTIONS)]
    if extra:
        rep.warn.append(f"{TASKS}: extra sections (an agent writes by the old rules): " + ", ".join(extra[:4]))
    missing = [s for s in TASKS_SECTIONS if not any(h.startswith(s) for h in heads)]
    if missing:
        rep.warn.append(f"{TASKS}: missing sections " + ", ".join(missing))
    done = [l for l in t.splitlines() if l.lstrip().startswith("- [x]")]
    if done:
        rep.warn.append(f"{TASKS}: {len(done)} [x] lines not moved to {ARCHIVE}/Done — the evening agent skipped step 7a")
    src = [l for l in t.splitlines() if l.lstrip().startswith("- [") and re.search(r"\*\([^)]*\)\*", l)]
    if src:
        rep.warn.append(f"{TASKS}: {len(src)} tasks with a source tail *(…)* — not the plain, one-glance format")
    long = [l for l in t.splitlines() if l.lstrip().startswith("- [") and len(l) > TASK_LINE_MAX]
    if long:
        rep.info.append(f"{TASKS}: {len(long)} tasks longer than {TASK_LINE_MAX} characters — simplify")
    # length of "Later"
    m = re.search(re.escape(SEC_LATER) + r"(.*?)(\n## |\Z)", t, re.S)
    if m:
        n = len([l for l in m.group(1).splitlines() if l.lstrip().startswith("- [")])
        if n > LATER_LIMIT:
            rep.warn.append(f"{TASKS}: \"Later\" has {n} lines (> {LATER_LIMIT}) — move the excess into project backlogs")
        else:
            rep.ok.append(f"{TASKS}: \"Later\" has {n} lines, format is fine" if not (extra or src or done) else f"{TASKS}: \"Later\" has {n} lines")
    m5 = re.search(re.escape(SEC_TODAY) + r"[^\n]*\n(.*?)(\n## |\Z)", t, re.S)
    if m5:
        n5 = len([l for l in m5.group(1).splitlines() if l.lstrip().startswith("- [")])
        if n5 > 5:
            rep.warn.append(f"{TASKS}: \"🔥 Today\" has {n5} tasks, limit is 5 — the morning agent or an evening catch-up overfilled the focus")
    info = [l for l in t.splitlines() if re.match(r"^\s*- \(", l)]
    if info:
        rep.warn.append(f"{TASKS}: {len(info)} informational \"- (…)\" lines — they belong in project files")
    today = today or date.today()
    # The briefing logged a run today but the 🔥 heading is not today's — its TASKS.md write was lost
    # (seen 2026-10-19).
    h5 = next((h for h in heads if h.startswith(SEC_TODAY)), "")
    br = [r for r in parse_runs_all(vault, [today.strftime("%Y-%m")]) if r[0] == fmt_d(today) and r[2] == MORNING_AGENT and r[3] in ("ok", "warn")]
    if br and f"{today.day:02d}.{today.month:02d}" not in h5:
        rep.warn.append(f"{TASKS}: {MORNING_AGENT} logged a run at {br[-1][1]}, but the heading \"{h5[3:] or '🔥 Today'}\" is not today's — "
                        f"its {TASKS} write was lost (write race or iCloud?)")
    if v4:
        ma = re.search(re.escape(SEC_DECIDE) + r"[^\n]*\n(.*?)(\n## |\Z)", t, re.S)
        if ma:
            asks = [l.strip() for l in ma.group(1).splitlines() if l.strip().startswith("- ")]
            boxed = [l for l in asks if l.startswith("- [")]
            if boxed:
                rep.warn.append(f"{TASKS}: \"❓ Decide\" has {len(boxed)} lines with a checkbox — questions are written as `- ❓ …` without a checkbox")
            if len(asks) > ASK_LIMIT:
                rep.warn.append(f"{TASKS}: \"❓ Decide\" has {len(asks)} questions (> {ASK_LIMIT}) — agents must stop adding; time to go through them")
            old = []
            for l in asks:
                tail = re.findall(r"_([^_]*)_\s*(?://.*)?$", l)
                dm = re.search(r"\b(\d{2})\.(\d{2})\b", tail[-1]) if tail else None
                if not dm:
                    continue
                try:
                    qd = date(today.year, int(dm.group(2)), int(dm.group(1)))
                except ValueError:
                    continue
                if qd > today:
                    qd = qd.replace(year=today.year - 1)
                if (today - qd).days > ASK_OLD_DAYS:
                    old.append(f"{l[4:50]}… ({dm.group(0)})")
            if old:
                rep.info.append(f"{TASKS}: {len(old)} ❓ questions older than {ASK_OLD_DAYS} days — answer or drop: " + "; ".join(old[:3]))
            if not (boxed or len(asks) > ASK_LIMIT):
                rep.ok.append(f"{TASKS}: \"❓ Decide\" {len(asks)} of {ASK_LIMIT}")


# Extra folders where open checkboxes should not live (everything actionable belongs in TASKS.md).
CHECKBOX_FOLDERS: tuple = ()


def check_checkboxes_elsewhere(vault, today, rep):
    hits = []
    for folder in CHECKBOX_FOLDERS:
        f = vault / folder
        if f.exists():
            for p in f.glob("*.md"):
                n = len(re.findall(r"^\s*- \[ \]", read(p), re.M))
                if n:
                    hits.append(f"{folder}/{p.name[:30]}: {n}")
    for i in (range(0, 2) if not is_v4(vault) else ()):   # v4: no Daily notes
        p = vault / DAILY / f"{fmt_d(today - timedelta(days=i))}.md"
        txt = read(p)
        m = re.search(r"## To sort(.*?)(\n## |\Z)", txt, re.S)
        if m:
            n = len(re.findall(r"^\s*- \[ \]", m.group(1), re.M))
            if n:
                hits.append(f"{DAILY}/{p.name}: \"To sort\" with {n} checkboxes")
    if hits:
        rep.info.append(f"Checkboxes outside {TASKS} (single-register rule, 2026-08-17): " + "; ".join(hits[:4]))


MARK_START_RE = re.compile(r"^\s*-\s*(?:>|→|x)(?:\s|$)", re.I)   # `- x Text`, `- > Text`, `- → [[…]]`
MARK_TAIL_RE = re.compile(r"//\s*(?:>|→|x)(?:\s|$)", re.I)         # `… // x already sent`, `// x - waiting`
STAMP_RE = re.compile(r"✓\s*agent")


def check_daily_marks(vault, today, rep):
    """The user's marks in "To sort" (`>` / `→` / `x` — at the start of a line or right after `//`) without the
    stamp "✓ agent dd.mm" = a decision made but not carried out. Yesterday's marks are still waiting for the
    morning briefing (which runs after this check) — info; older than a day — warn: the morning agent skipped
    step 0.5 (it is supposed to look back 7 days)."""
    if is_v4(vault):
        return  # v4: no marks in Daily; the user's answers are `//` lines in TASKS.md (check_tasks sees them)
    stale, fresh = [], []
    for i in range(1, 8):
        d = today - timedelta(days=i)
        txt = read(vault / DAILY / f"{fmt_d(d)}.md")
        m = re.search(r"## To sort(.*?)(\n## |\Z)", txt, re.S)
        if not m:
            continue
        for line in m.group(1).splitlines():
            s = line.strip()
            if not s.startswith("- ") or STAMP_RE.search(s):
                continue
            if MARK_START_RE.search(s) or MARK_TAIL_RE.search(s):
                (fresh if i == 1 else stale).append((fmt_d(d), s[2:62]))
    if stale:
        rep.warn.append(
            f"{DAILY}: {len(stale)} of the user's decisions in \"To sort\" are older than a day without a \"✓ agent\" stamp — the morning briefing skipped step 0.5 "
            f"(it should look back 7 days): " + "; ".join(f"{d}: {t}" for d, t in stale[:3]))
    if fresh:
        rep.info.append(f"{DAILY}: {len(fresh)} of the user's decisions from yesterday are waiting for the morning briefing")
    if not stale and not fresh:
        rep.ok.append(f"{DAILY}: the user's marks for the last 7 days are done (or there are none)")


def check_sessions(vault, today, rep):
    y = fmt_d(today - timedelta(days=1))
    obr = processed_report(vault, y).exists()
    ses = (vault / SESSIONS / f"{y}.md").exists()
    if obr and not ses:
        rep.warn.append(f"{SESSIONS}/{y}.md was not created, although the \"{PROCESSED_PREFIX}{y}\" report exists")
    elif ses:
        txt = read(vault / SESSIONS / f"{y}.md")
        if NO_SESSIONS in txt:
            # traces: work files changed yesterday
            cutoff = datetime.combine(today - timedelta(days=1), datetime.min.time()).timestamp()
            changed = []
            for folder in WORK_FOLDERS:
                f = vault / folder
                if f.exists():
                    changed += [p for p in f.rglob("*.md") if p.stat().st_mtime >= cutoff and BACKLOG_NAME not in p.name]
            if len(changed) >= 2:
                rep.warn.append(f"{SESSIONS}/{y}.md says \"{NO_SESSIONS.lower()}\", but {len(changed)} work files changed yesterday — the step 1 cross-check did not fire")


def check_telegram_pull(rep):
    # 2026-10-06 (audit, ISSUE-2): liveness is judged ONLY by the tgpull.ok marker that tg_pull writes
    # itself at the end of a SUCCESSFUL run. Previously the check looked at a heartbeat/log that was
    # updated on every launch — and for over a month it reported "alive" while the script was hanging
    # (iCloud had evicted its venv from ~/Documents). An earlier alarm of "silent for 664 h" had
    # actually been true. The working folder now lives in ~/Library/Application Support/second-brain/tg_pull.
    marker = LOG_DIR / "tgpull.ok"
    if not marker.exists():
        rep.warn.append("Telegram backstop: no tgpull.ok — tg_pull has never finished a run successfully. "
                        "Run it by hand: ~/Library/Application\\ Support/second-brain/tg_pull/.venv/bin/python3 "
                        "~/Library/Application\\ Support/second-brain/tg_pull/tg_pull.py --dry-run")
        return
    age_h = (datetime.now().timestamp() - marker.stat().st_mtime) / 3600
    if age_h > 6:
        rep.warn.append(f"Telegram backstop (tg_pull) has not finished a run for {age_h:.0f} h — see the tail of "
                        f"~/Library/Logs/second-brain/tgpull.log; if it is empty, the process is hanging (iCloud / disk access)")
    else:
        rep.ok.append(f"Telegram backstop is alive (last successful run {age_h:.1f} h ago)")


def check_export(rep):
    # 2026-10-06 (audit, ISSUE-9): the Claude Code session export (~/.claude/export-to-obsidian.py, scheduled
    # task claude-sessions-to-obsidian at 19:00) used to leave no trace — zero exports looked normal.
    # Judge it by the result: (1) a success marker no older than 36 h; (2) no "session-day" pairs older
    # than yesterday that are missing from the dedup log. The logic is borrowed from the export script itself.
    import importlib.util, time
    marker = LOG_DIR / "export.ok"
    script = EXPORT_SCRIPT
    if not script.exists():
        rep.info.append(f"Claude Code session export: {script} not installed — check skipped")
        return
    if not marker.exists():
        rep.warn.append("Claude Code session export: no export.ok — the script has never finished a run (task claude-sessions-to-obsidian, 19:00)")
    else:
        age_h = (time.time() - marker.stat().st_mtime) / 3600
        if age_h > 36:
            rep.warn.append(f"Claude Code session export has not run for {age_h:.0f} h — is the claude-sessions-to-obsidian task (19:00) not running?")
    spec = importlib.util.spec_from_file_location("export_to_obsidian", script)
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    log = ex.load_log()
    limit = date.today() - timedelta(days=1)   # yesterday is exported today at 19:00 — that is not a miss
    missing = []
    for jsonl in ex.PROJECTS_DIR.glob("*/*.jsonl"):
        if time.time() - jsonl.stat().st_mtime > 14 * 86400:
            continue
        for d, bucket in ex.extract_by_date(jsonl).items():
            if d < limit and bucket["messages"] and f"{jsonl.stem}|{d.isoformat()}" not in log:
                missing.append(d)
    if missing:
        rep.warn.append(f"Claude Code session export: {len(missing)} session-days (earliest {min(missing):%d.%m}) did not reach {INBOX} — "
                        f"run `python3 ~/.claude/export-to-obsidian.py` or the export-transcripts skill")
    elif marker.exists():
        rep.ok.append("Claude Code session export: everything up to the day before yesterday is exported")


NOTES_STATE = LOG_DIR / "checkvault.notes.json"
NOTES_SKIP = (TO_DELETE, ".obsidian", ".trash", "harness-audits")


def check_vanished_notes(vault, rep, dry):
    # 2026-10-07 (audit, ISSUE-11): the "never delete anything" rule (CLAUDE.md §0) was not checked by anything.
    # The list of notes is kept between runs; a note that disappeared and cannot be found under the same
    # name anywhere in the vault (in _to_delete/, Archive/, or moved to another folder) is a signal.
    # Listing only, contents are not read — files evicted by iCloud do not get in the way.
    # Reset: delete ~/Library/Logs/second-brain/checkvault.notes.json (the next run starts over).
    import json
    current = {str(p.relative_to(vault)) for p in vault.rglob("*.md")
               if not any(part in NOTES_SKIP for part in p.relative_to(vault).parts)}
    try:
        prev = set(json.loads(NOTES_STATE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        prev = None
    if prev is not None:
        gone = prev - current
        if gone:
            names_now = {Path(r).name for r in current}
            names_now |= {p.name for p in (vault / TO_DELETE).rglob("*.md")} if (vault / TO_DELETE).is_dir() else set()
            lost = sorted(r for r in gone if Path(r).name not in names_now)
            if lost:
                rep.warn.append(f"Notes vanished without a trace: {len(lost)}  (not in {TO_DELETE}/, not in {ARCHIVE}, not under the same name in other folders): "
                                + "; ".join(lost[:5]) + (" …" if len(lost) > 5 else "")
                                + " — if you did not delete them yourself, look in the snapshots or the Obsidian trash (.trash)")
            else:
                rep.ok.append(f"No notes vanish ({len(gone)} moved, all found)")
        else:
            rep.ok.append("No notes vanish")
    if not dry:
        NOTES_STATE.parent.mkdir(parents=True, exist_ok=True)
        NOTES_STATE.write_text(json.dumps(sorted(current), ensure_ascii=False), encoding="utf-8")


def check_script_copies(vault, rep):
    # 2026-10-07 (audit, ISSUE-20): master copies of the scripts live in the vault (Projects/Second Brain/),
    # working copies in ~/Library/Application Support/second-brain/ (outside iCloud). They were only ever
    # synced by hand, so drift went unnoticed.
    import stat as _stat
    sb = APP_DIR
    master_dir = vault / SCRIPTS_MASTER_DIR
    pairs = [(sb / "scripts/check_vault.py", "check_vault.py"),
             (sb / "scripts/snapshot.py", "snapshot.py"), (sb / "tg_pull/tg_pull.py", "tg_pull.py")]
    differ, skipped = [], []
    for work, name in pairs:
        master = master_dir / name
        if not work.exists() or not master.exists():
            differ.append(f"{name} (no {'working' if not work.exists() else 'master'} copy)")
            continue
        if os.stat(master).st_flags & getattr(_stat, "SF_DATALESS", 0x40000000):
            skipped.append(name)
            continue
        if sha(work) != sha(master):
            differ.append(name)
    if differ:
        rep.warn.append(f"Master copies in \"{SCRIPTS_MASTER_DIR}/\" differ from the working ones: " + ", ".join(differ)
                        + " — edited the working copy? copy it to the master (or the other way round)")
    elif skipped:
        rep.info.append("Script master-copy comparison skipped for " + ", ".join(skipped) + " — iCloud evicted them from disk")
    else:
        rep.ok.append("Script master copies match the working ones")


def check_snapshots(vault, rep):
    # 2026-10-06 (audit, ISSUE-4): snapshots of TASKS/CLAUDE/Daily/prompts twice a day (snapshot.py, launchd 08:40 and 20:20).
    # Judge by the result: is there a fresh snapshot, and have the key files not "lost weight" — that is
    # what an agent that dropped a section or rewrote a file looks like.
    root = APP_DIR / "snapshots"
    snaps = []
    for d in (root.iterdir() if root.is_dir() else []):
        try:
            snaps.append((datetime.strptime(d.name, "%Y-%m-%d_%H%M"), d))
        except ValueError:
            pass
    if not snaps:
        rep.warn.append(f"No snapshots — snapshot.py (launchd {SNAPSHOT_LABEL}) has never run; there is nothing to restore a broken {TASKS} from")
        return
    snaps.sort()
    newest_t, newest = snaps[-1]
    age_h = (datetime.now() - newest_t).total_seconds() / 3600
    if age_h > 26:
        rep.warn.append(f"Last snapshot {newest.name} is {age_h:.0f} h old: snapshot.py stopped running (log ~/Library/Logs/second-brain/snapshot.log)")
    else:
        rep.ok.append(f"Snapshot of key files is fresh ({newest.name})")
    recent = [d for t, d in snaps if datetime.now() - t <= timedelta(days=3)]
    for rel in (TASKS, "CLAUDE.md"):
        cur = vault / rel
        sizes = [(d / "vault" / rel).stat().st_size for d in recent if (d / "vault" / rel).exists()]
        if not cur.exists() or not sizes:
            continue
        big = max(sizes)
        now_size = cur.stat().st_size
        if now_size < big * 0.5 and big - now_size > 1500:
            src = max((d for d in recent if (d / "vault" / rel).exists()), key=lambda d: (d / "vault" / rel).stat().st_size)
            rep.warn.append(f"{rel} shrank from {big} to {now_size} bytes within 3 days — check whether an agent dropped sections; "
                            f"copy: ~/Library/Application Support/second-brain/snapshots/{src.name}/vault/{rel}")


# ---------------------------------------------------------------- main

def write_report(vault, today, rep, dry):
    lines = [f"---", f"date: {fmt_d(today)}", f"status: {rep.status()}", f"new: {len(rep.new)}", f"type: system check", f"---", "",
             f"# 🩺 System check — {fmt_d(today)} ({datetime.now().strftime('%H:%M')})", ""]
    if rep.new:
        lines += ["## 🚨 New since previous checks — look at these first"] + [f"- {x}" for x in rep.new] + [""]
    if rep.fixed:
        lines += ["## 🔧 Fixed automatically"] + [f"- {x}" for x in rep.fixed] + [""]
    known = [w for w in rep.warn if w not in rep.new]
    if known:
        head = "## ⚠️ Needs attention — known" if not rep.seeded else \
               "## ⚠️ Needs attention (new/known bookkeeping starts with this check — everything below counts as known)"
        lines += [head] + [f"- {x} *(since {rep.since[x][8:10]}.{rep.since[x][5:7]})*" if x in rep.since else f"- {x}"
                           for x in known] + [""]
    if rep.info:
        lines += ["## ℹ️ Notes"] + [f"- {x}" for x in rep.info] + [""]
    lines += ["## ✅ All good"] + [f"- {x}" for x in rep.ok] + [""]
    out = "\n".join(lines)
    if dry:
        print(out)
        return
    p = vault / INBOX / f"{CHECK_REPORT_PREFIX}{fmt_d(today)}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out, encoding="utf-8")
    # heartbeat
    runs = run_log(vault, today.strftime('%Y-%m'))
    if not runs.exists():
        runs.write_text("# Runs — agent run log\n\n> Every agent appends one line when it finishes: `- YYYY-MM-DD HH:MM | task-name | ok/warn | what was done`. Read by the morning check.\n\n", encoding="utf-8")
    with open(runs, "a", encoding="utf-8") as f:
        f.write(f"- {fmt_d(today)} {datetime.now().strftime('%H:%M')} | check-vault v{CHECK_VERSION} | {rep.status()} | fixed={len(rep.fixed)} warn={len(rep.warn)} new={len(rep.new)}\n")
    if rep.new:
        first = rep.new[0] if len(rep.new[0]) <= 110 else rep.new[0][:110].rstrip() + "…"
        notify(f"Second Brain: {len(rep.new)} new problems" if len(rep.new) > 1 else "Second Brain: new problem",
               first + (" — details in \"System check\"" if len(rep.new) == 1 else f" (+ {len(rep.new) - 1} more)"))
    print(f"OK status={rep.status()} fixed={len(rep.fixed)} warn={len(rep.warn)} new={len(rep.new)} → {p.name}")


def main():
    ap = argparse.ArgumentParser(description="Morning invariant check for a Second Brain Obsidian vault.")
    ap.add_argument("--vault", default=str(DEFAULT_VAULT), help="vault path (default: $SECOND_BRAIN_VAULT or ~/Vault)")
    ap.add_argument("--dry-run", action="store_true", help="print the report, change nothing")
    ap.add_argument("--days", type=int, default=3, help="how many past days to check for missed runs")
    ap.add_argument("--test-notify", action="store_true", help="only show a test notification and exit")
    a = ap.parse_args()
    if a.test_notify:
        notify("Second Brain: notification test", "This is what a new-problem alert will look like")
        return
    vault = Path(a.vault).expanduser()
    if not (vault / TASKS).exists():
        print(f"vault not found: {vault}", file=sys.stderr)
        sys.exit(2)
    today = date.today()
    rep = Report()
    for fn, args in [
        (check_daily, (vault, today, rep, a.dry_run)),
        (check_runs, (vault, today, rep, a.days)),
        (check_versions, (vault, today, rep)),
        (check_archive_inbox, (vault, rep, a.dry_run)),
        (check_inbox_stale, (vault, rep)),
        (check_duplicates, (vault, rep, a.dry_run)),
        (check_tasks, (vault, rep, today)),
        (check_checkboxes_elsewhere, (vault, today, rep)),
        (check_daily_marks, (vault, today, rep)),
        (check_sessions, (vault, today, rep)),
        (check_telegram_pull, (rep,)),
        (check_snapshots, (vault, rep)),
        (check_export, (rep,)),
        (check_vanished_notes, (vault, rep, a.dry_run)),
        (check_script_copies, (vault, rep)),
    ]:
        try:
            fn(*args)
        except Exception as e:  # the checker must never crash as a whole
            rep.warn.append(f"check {fn.__name__} crashed: {e!r}")
    try:
        classify_warnings(rep, a.dry_run)
    except Exception as e:  # new/known bookkeeping must not take the report down
        rep.info.append(f"new/known bookkeeping failed: {e!r}")
    write_report(vault, today, rep, a.dry_run)


if __name__ == "__main__":
    main()
