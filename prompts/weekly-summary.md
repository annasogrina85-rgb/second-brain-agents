---
name: weekly-summary
description: Sunday weekly summary and TASKS.md review (no daily notes) — promote tasks, check ❓, audit the system, catch up missed colleague runs
version: 3.0
---

Weekly summary + task review for the user. Sunday, end of the week.

Vault: `<vault>/`. First read `CLAUDE.md` (§2 — TASKS.md: sections `🔥 Today` / `❓ Decide` / `📅 This week` / `📥 Later`). Daily notes no longer exist (since v3.0): do not read or create `Daily/*`, and do not build a weekly review queue — the `❓ Decide` section in TASKS.md itself replaces it.

⚠️ Save the summary ONLY to `Summaries/Weeks/YYYY-W[number].md` inside the vault. Not to Drive, not to `Journal/`, not to the session's temporary folder.

**Write race on `TASKS.md`.** Before every Write, re-read the file and apply your edits to the fresh copy; do nothing else between that Read and the Write.

## Step 0 — Which week

`date "+%F %a"`. The week = Monday–Sunday of the ISO week that ended on the last Sunday ≤ today. A run on Monday–Tuesday = catching up last Sunday: the summary goes into that week's file, and the summary and run log say "catch-up for dd.mm" (the Sunday being caught up). A run on Wednesday–Saturday is also a catch-up, but should not happen: "⚠️ run on <day>, check the task's schedule".

## Steps

1. **Journal.** `Journal/2*.md` for the last 7 days: events, mood.
2. **Done.** `Archive/Done — YYYY-MM.md` (at a month boundary, both files): everything closed in the last 7 days (✅ / ⛔ / ⏳ / 💬).
3. **TASKS.md review** (the main ritual):
   - Update the heading `## 📅 This week — until Sun DD.MM`. Promote into it from `📥 Later` the lines dated within the next 7 days and the 3–5 most important ones (by project backlogs and deadlines); move, do not copy, and do not touch the wording.
   - Lines that sat in `📅` for a week without movement and without a date in the new week → into `📥 Later`.
   - From project backlogs (`## Backlog` in `Projects/…`, `Work/…`, `Personal/…`), promote 3–5 ripe tasks into `📥 Later` in flat form; `Later` ≤ 30 lines, anything over goes back to the project backlog.
   - **"Waiting on people" — only the most recent block** in the file (inside dated `## Update YYYY-MM-DD` headings; the rest is history). Before listing someone under "who to nudge", check the latest outcome for that contact (declines, `❌`/`✅`, dated updates). From the recent block, waits older than 7 days go into the summary (not into TASKS.md).
   - Tasks without movement for >30 days — only a list of candidates for dropping in the summary; do not drop them yourself.
   - **`❓ Decide` section:** delete nothing. Count the questions; those older than 14 days (by the date at the end of the line) are listed in the summary as "candidates to decide or drop — answer with `//`". More than 10 lines — note it in the summary, move nothing.
   - No new sections, no `*(source)*` tails, no `//` of your own; every task in exactly one section. Re-read TASKS.md and Write.
4. **Projects.** `Projects/**/*.md` and `Work/**/*.md`: `## Update YYYY-MM-DD` headings from this week — what moved.
4b. **Meaning audit — "System this week".** Read for the last 7 days: `Inbox/System check — *.md`, `Inbox/Processed — *.md`, `Inbox/Runs — YYYY-MM.md`, `Archive/Done`, `TASKS.md`. Look for what code cannot see: a closed `[x]` reappeared in TASKS; an agent rewrote the user's line or wrote `//` itself; context / sources / per-project sections got into TASKS; `Daily/` is suddenly being created again (it should not be); `Sessions/` says "No sessions" while work files changed; an external doc is mentioned but the project file has no link to it; duplicate meeting notes; files outside the vault's data map; runs that did not happen while the computer was on; stale "snapshots" in project files read as current; run-log lines longer than 300 characters; slots that were missed and not caught up (no line from the agent and no `| catch-up |`). Fix nothing and do not edit instructions — write a `## 🩺 System this week` section: what was caught and fixed automatically, what you found yourself, and 1–3 sentences on "which instruction to fix". If a decision from the user is needed — a `❓` line in TASKS.md (with dedup, at most 10).
5. **Summary** → `Summaries/Weeks/YYYY-W[number].md`: `# Week [number] — [dates]`, `## 🎯 The week in brief` (2–3 sentences), `## ✅ Closed this week`, `## 📁 What moved in projects` (one line per project), `## 👥 Who to nudge`, `## 🗑 Candidates for "Someday"` (move / delete / keep), `## 📔 From the journal` (2–3 sentences), `## ❓ Questions for you` (how many are open, which are older than 14 days), `## 🩺 System this week`, `## 🔮 Next week` (deadlines and focus).
5b. **Run log:** `- YYYY-MM-DD HH:MM | weekly-summary v3.0 | ok | summary 2026-Wnn, promoted to This week N, to Later N, to project backlog N, ❓ open N (older than 14 days: N), system: N findings`. No longer than 300 characters; the version in the stamp is mandatory.

## Step C — Catch up colleagues (after the run-log line, before the summary in chat)

The platform does not re-run missed tasks when the computer comes back online. So the agents catch up for each other: if you have reached this step, the computer is online and you can re-launch whoever did not run. The user does not have to press anything.

1. If you yourself were launched as a catch-up (the launch message contains the word "catch-up"), skip this step entirely.
2. If the run log has a `| catch-up |` line younger than 60 minutes, skip.
3. Call `list_triggers` (Claude Code Remote connector). Colleagues: `Daily focus briefing`, `Ai sessions capture`, `Daily inbox processing`, `system-doctor`. For each enabled one, use `cron_expression` (respect `CRON_TZ=<user-tz>`) to find the last slot that has passed. Ignore slots older than 48 hours — those belong to the doctor.
4. A colleague has missed a slot if all three hold: the slot passed more than 60 minutes ago; `Inbox/Runs — YYYY-MM.md` has no line from that agent with status `ok`/`warn` and a time ≥ slot − 2 h (some lines are written in UTC); `last_fired_at` in `list_triggers` is older than 45 minutes. Re-launch `Daily focus briefing` only before 14:00 local time; `Weekly summary` only on Monday–Tuesday.
5. For each one that missed — `fire_trigger` with `text`: `catch-up for <slot date dd.mm HH:MM>, launched by weekly-summary at HH:MM`. Order: capture → inbox → briefing → weekly → doctor.
6. Append one line to the run log: `- YYYY-MM-DD HH:MM | catch-up | ok | weekly-summary → re-launched: <who> (<slot>)`. If you re-launched nobody, write no line and do not mention it. If you did — one line in the summary: "re-launched: …".
7. If `list_triggers` / `fire_trigger` are unavailable — one line in the summary, "colleague catch-up: connector unavailable", without `warn`.

6. **Summary in chat** (7–10 lines): the main points, what was closed, who to nudge, candidates for dropping (ask the user to decide), how many ❓ are waiting and which are oldest, focus for next week. Warm, honest, no empty words.
