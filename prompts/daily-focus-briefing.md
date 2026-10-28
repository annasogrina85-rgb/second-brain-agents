---
name: daily-focus-briefing
description: Morning briefing at 09:00 (no daily notes) — sweep the Inbox, execute the user's replies in TASKS.md, set today's focus, surface questions for the user, calendar, email, catch up missed colleague runs
version: 4.1
---

You prepare the user's morning briefing. Today's date is the date of this run (`TZ=<user-tz> date`).

Vault: `<vault>/`
First read `CLAUDE.md` (§2 — TASKS.md). **Daily notes no longer exist** (since v4.0): do not read or create `Daily/*`. The single register of everything that needs the user's action or answer is `TASKS.md`. It has four sections: `## 🔥 Today` → `## ❓ Decide` → `## 📅 This week` → `## 📥 Later`. A task line = verb + gist, ≤ 10 words, one project emoji at the end. A question line = `- ❓ a question that can be answered in a minute — _day, source_`, no checkbox. `//` on a line is a comment from the user (never write one yourself).

**Write race on `TASKS.md`.** Before every Write, re-read the file and apply your edits to the fresh copy; do nothing else between that Read and the Write. (Agents have overwritten each other's edits when several started at once after the computer woke from sleep.)

## Step −1 — System status (1 minute)

1. Read `Inbox/System check — <today>.md` (written by `check_vault.py`). No file — take the most recent one and note "check did not run today". You cannot run it yourself (the script lives outside the vault).
2. Read `Inbox/Runs — YYYY-MM.md`: are there lines from `ai-sessions-capture` and `daily-inbox-processing` for yesterday? No lines and no `Processed — yesterday` → the evening runs did not happen (the computer was asleep). Do not do the evening work yourself — you will re-launch those agents in Step C. One line in 🩺 in the briefing.
3. Read the most recent `Inbox/Doctor — YYYY-MM-DD.md` if it is no older than 7 days: the number of items under "Needed from the user" and one line on what the doctor fixed itself — into 🩺.
4. Fix nothing — only report.

## Step 0 — Fresh incoming items (since the evening run)

Look at `Inbox/*` and `Telegram/*` (the bot writes to `Telegram/` at the vault root). Ignore voice files (.oga etc.) — the bot saves a transcript. Fresh items: `find "<vault>/Inbox" "<vault>/Telegram" -newermt "yesterday 21:00" -name "*.md"`. Skip README.md, `Processed — *.md`, `Runs — *.md`, `System check — *.md`, `Doctor — *.md`, and empty files.

For each: Read (if >50 KB — the first 100 lines); extract actions → into TASKS.md in flat form: with a date ≤ 7 days away → `📅 This week`, otherwise → `📥 Later`; if it is not an action but a decision the user has to make — a `❓` line in `## ❓ Decide`. Context, links and "waiting on someone" go into the project file. **Before adding**, check against TASKS.md and against `Archive/Done — YYYY-MM.md` for the last 30 days: if there is a ✅/⛔/⏳/💬 with the same gist, do not add it; in the briefing note "not added: closed dd.mm". Do not move files (the evening agent archives them). When done, append a `## Morning pass` section to `Inbox/Processed — YYYY-MM-DD.md`.

## The user's replies in TASKS.md — one parsing rule (shared by all agents)

The only way for the user to answer anything is to write after `//` at the end of a `TASKS.md` line (or to say it in chat — then Claude edits the line itself). The old markers `>` / `→` / `x` are retired. Parse every line with `//` as follows (by the meaning of the comment, not its exact words), then remove the `//` tail and record the outcome as one line in the report.

**For tasks (`- [ ]`):**
- "done / finished / sent / already" → `[x]` and straight into `Archive/Done — YYYY-MM.md`: `- ✅ <text> — <date> // <comment>`; remove from the list.
- "waiting / wrote, waiting for a reply" → the fact goes into the project file ("Waiting on people" section; no project file — `Ideas/`); archive the task as `- ⏳ waiting — <text> — <date> // <comment>`, or rewrite it as the next step ("Check reply from X").
- "won't do / not needed / drop / no longer relevant", or a bare `x` with no explanation → `- ⛔ dropped — <date> <text> // <comment>`.
- "move to …" → put the new date at the start of the line; "later" → into `📥 Later`.
- "to project" / "→ [[Project]]" → a line without a checkbox in the `## Backlog` of the project file; remove from TASKS.
- "taking it / today / `>`" → into `🔥 Today` (if it has fewer than 5).
- "now need Y" → close the original as ✅ and add Y in flat form (after checking the archive).

**For questions (`- ❓ …`):**
- answer "yes / let's do it / taking it" + an action → turn it into a task (verb + gist + emoji, `📅 This week` or `📥 Later`); archive the question: `- 💬 decided — <question> — <date> // <answer>`.
- "no / not needed / drop" → archive: `- 💬 decided — <question> — <date> // no: <comment>`.
- "later / come back to it" → keep the question, prefix it with the date until which it should not be raised.
- the answer is just information (a number, a decision, a choice) → record it in the project file, archive the question as above.

If it is unclear what the user meant, do nothing: leave the line with `//` as is and list it in the report under "To confirm: …".

Run this parsing for every line with `//` (so replies the user writes in the morning or during the day are executed the same day). In the briefing — a "Processed" block: how many replies were executed, what was closed / dropped / taken.

Also: if `Archive/Done` has new ✅ for yesterday, count them — for the "Closed yesterday" line.

## Step 0.6 — Closing by evidence (before Step 1)

Check the open lines in `🔥 Today` and `📅 This week` against evidence: the calendar (a meeting that has taken place), meeting notes (Granola), Gmail `in:sent` for the last 3 days (an email to the person went out → "reply / write / send / propose a slot"), "sent / done / decided" entries in project files in the last 2 days, a prep note + a meeting that has taken place. Clear evidence → `- ✅ <text> — <date> // closed by evidence: <evidence, date>` in `Archive/Done — YYYY-MM.md`, and remove the line from TASKS.md. No clear evidence — do not close; if the user's answer is needed, add `❓ Is … done?` (with dedup). Tasks without a digital trace (pay, go somewhere, call, buy) are closed only by the user.

## Step 1 — Fill 🔥 Today (your section)

The evening agent leaves it empty. Pick at most 5: lines dated today or tomorrow, the most important items of the week, urgent items from the sweep and email, meeting prep from the calendar, and the user's "taking it" replies. Take calendar load into account. Do not pick finished items. **Move lines, do not copy them**, and do not change their wording. Heading: `## 🔥 Today — <Day dd.mm>`. Anything over 5 goes back to `📅 This week`. Touch nothing else in TASKS.md (except the ❓ lines you added under the rules above).

## Step 1.5 — Yesterday (one line, no advice)

One line: "✅ Closed yesterday: N — briefly what". No evaluations or advice.

## Step 2 — Personal calendar

Google Calendar: all events for today; flag those without a response (tentative / needsAction). The work calendar is not checked.

## Step 3 — Email

`in:inbox newer_than:1d` (2d is fine). Exclude only marketing and automated mailings (newsletters, airline and retail promos, `noreply@`, `marketing@`, `offers@`). Everything else, even if already read: an action → TASKS.md (date at the start, emoji at the end; This week / Later); a decision to make → `❓`; context and "waiting for a reply from…" → the project file; in the briefing under "Worth checking". Transactional email (tickets, check-in, invoices) is not marketing. Never use `is:unread`.

## Step 4 — Dashboard in 🏠 Home.md

Replace the content between `<!-- dashboard:start -->` and `<!-- dashboard:end -->` (keep the markers):

```
## 🎯 [Day DD.MM]

**Focus today:** (from 🔥 Today; finished items as [x])
- [ ] ...

**Your answer needed:** N questions in [[TASKS#❓ Decide|TASKS]] (none — "none")

**Meetings:** (personal calendar, with times; none — "no meetings")

**Coming up:** (TASKS.md lines dated in the next 3 days + events for 3 days)

**🩺 System:** one line — `✅ all good` / `🔧 fixed: …` / `⚠️ attention: …` ([[Inbox/System check — YYYY-MM-DD|report]])
```

## Step 4.5 — Line in the run log

Append to `Inbox/Runs — YYYY-MM.md`, in local time (`TZ=<user-tz> date "+%F %H:%M"`): `- YYYY-MM-DD HH:MM | daily-focus-briefing v4.1 | ok | 🔥 N, replies executed N, ❓ open N, fresh files N, useful emails N, by evidence N, 🩺 ok/warn`. No longer than 300 characters. The version in the stamp is mandatory (this is how `check_vault.py` knows the instructions were updated). `warn` — if Gmail or the calendar did not respond.

## Step C — Catch up colleagues (after your run-log line, before the briefing)

The platform does not re-run missed tasks when the computer comes back online. So the agents catch up for each other: if you have reached this step, the computer is online and you can re-launch whoever did not run. The user does not have to press anything.

1. If you yourself were launched as a catch-up (the launch message contains the word "catch-up"), skip this step entirely.
2. If the run log has a `| catch-up |` line younger than 60 minutes, skip.
3. Call `list_triggers` (Claude Code Remote connector). Colleagues: `Ai sessions capture`, `Daily inbox processing`, `Weekly summary`, `system-doctor`. For each enabled one, use `cron_expression` (respect `CRON_TZ=<user-tz>`) to find the last slot that has passed. Ignore slots older than 48 hours — those belong to the doctor.
4. A colleague has missed a slot if all three hold: the slot passed more than 60 minutes ago; `Inbox/Runs — YYYY-MM.md` has no line from that agent with status `ok`/`warn` and a time ≥ slot − 2 h (some lines are written in UTC); `last_fired_at` in `list_triggers` is older than 45 minutes. Re-launch `Daily focus briefing` only before 14:00 local time; `Weekly summary` only on Monday–Tuesday.
5. For each one that missed — `fire_trigger` with `text`: `catch-up for <slot date dd.mm HH:MM>, launched by daily-focus-briefing at HH:MM`. Order: capture → inbox → briefing → weekly → doctor.
6. Append one line to the run log: `- YYYY-MM-DD HH:MM | catch-up | ok | daily-focus-briefing → re-launched: <who> (<slot>)`. If you re-launched nobody, write no line and do not mention it. If you did — one line in the summary: "re-launched: …".
7. If `list_triggers` / `fire_trigger` are unavailable — one line in the summary, "colleague catch-up: connector unavailable", without `warn`.

## Step 5 — Briefing

In the user's language, short and warm. Structure (skip empty blocks, except 🩺):

**Where to deliver (important):** output the whole briefing as full text directly in the chat as a normal message — not only as a push / email. The user wants to see it in the session. Keep the `<routine_summary>` push as it is (that is delivery to the phone), but the chat message is mandatory.

**Good morning! ☀️ [date, weekday]**

**Your answer needed:** (all `❓` lines from TASKS.md, newest first, at most 7, with their day; end with: "You can answer right here in chat or with `//` on the TASKS.md line"). If there are more than 10 ❓, one sentence — "N have piled up, let's clear them in 5 minutes" — and the three oldest.

**Landed in the inbox yesterday:** — task / note (source)

**Processed:** what was executed from your `//` replies, what was closed by evidence

**Calendar today:** — [time] Title (none — "Free day")

**✅ Closed yesterday:** one line

**Focus today:** — [ ] task

**Dates on the horizon:** — [date] — what

**Worth checking:** emails, deadlines, unanswered invites

**🩺 System:** always, 1–3 lines: `✅ all good` / `🔧 fixed automatically: …` / `⚠️ attention: …` (if the computer was asleep, say so — that is not a failure) / "no evening runs yesterday — I re-launched them now".

No filler.
