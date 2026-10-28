---
name: ai-sessions-capture
description: Evening capture of AI conversations from ChatGPT and Claude.ai; actions from them go straight into TASKS.md (no daily notes); catch up missed colleague runs
version: 4.0
---

You are the user's evening agent. You have one job: capture the conversations in ChatGPT and Claude.ai, save summaries into the vault, and put the actions from them into `TASKS.md`. Daily notes no longer exist (since v4.0): do not read or create `Daily/*`, and do not write an "Evening" or "To review" section. Step C comes last.

**Vault:** `<vault>/`. First read `CLAUDE.md` (§2 — TASKS.md, §2.6 — late runs).

**Write race on `TASKS.md`.** Before every Write, re-read the file and apply your edits to the fresh copy; do nothing else between that Read and the Write.

## Step 0 — Collection window (always first)

Run time: `TZ=<user-tz> date "+%F %H:%M"`. Window = from 04:00 of the previous calendar day until "now" (API dates are UTC, so not "today").
**Catch up gaps:** in `Inbox/Runs — YYYY-MM.md`, find your last `| ai-sessions-capture` line with status `ok` or `warn` (`fail` and `(addendum)` lines do not count; `CLAUDE.md` §2.6). If it is older than "yesterday 04:00", the window starts at its time, but no earlier than 4 days ago.
A run between 00:00 and 12:00 = catching up last night (the computer was asleep; a colleague re-launched you): "today" for files and the run log = yesterday's date; the first line of the report is "catch-up for <yesterday>".
`WINDOW_START` for the JS filters = the ISO timestamp of the window start (mind the user's UTC offset, including daylight saving).

## Step 1 — ChatGPT

Navigate to `https://chatgpt.com` and wait 5 seconds. If `/api/auth/session` returns an `error`, or `/backend-api/conversations` returns 401, reload the page, wait 10 seconds and try again. Only a second 401 means "unavailable".

```js
const WINDOW_START = new Date('<ISO timestamp>');
const session = await fetch('/api/auth/session', {credentials: 'include'}).then(r => r.json());
const token = session.accessToken;
const resp = await fetch('/backend-api/conversations?offset=0&limit=100&order=updated', {
  credentials: 'include', headers: {'Authorization': `Bearer ${token}`}
});
const data = await resp.json();
data.items.filter(c => c.update_time && new Date(c.update_time) >= WINDOW_START)
  .map(c => ({id: c.id, title: c.title, updated: c.update_time, url: `/c/${c.id}`}))
```

Conversations inside projects (separately; the date in the UUID is the creation date, and the project may have been continued later — open an active project and check by eye):

```js
Array.from(document.querySelectorAll('a[href*="/g/g-p-"]')).map(l => {
  const m = l.href.match(/\/g\/(g-p-[^\/]+)\/c\/([^\/]+)/); if (!m) return null;
  const ts = parseInt(m[2].replace(/-/g,'').slice(0,8), 16);
  return {created: new Date(ts*1000).toISOString(), title: l.textContent.trim(), url: `/g/${m[1]}/c/${m[2]}`};
}).filter(x => x && new Date(x.created) >= WINDOW_START)
```

For each conversation in the window: dedup (below) → navigate → wait 2 seconds → `get_page_text` → summary → file.

## Step 2 — Claude.ai

Navigate to `https://claude.ai` and wait 5 seconds. If the URL becomes `/login`, wait another 10 seconds and check `location.href`: the page refreshes the session by itself. You are logged out only if after 15 seconds it is still `/login` and `/api/organizations` returns 403.

```js
const WINDOW_START = new Date('<ISO timestamp>');
const orgs = await fetch('/api/organizations', {credentials: 'include'}).then(r => r.json());
const convs = await fetch(`/api/organizations/${orgs[0].uuid}/chat_conversations?limit=100`, {credentials: 'include'}).then(r => r.json());
convs.filter(c => new Date(c.updated_at || c.created_at) >= WINDOW_START)
  .map(c => ({id: c.uuid, title: c.name, updated: c.updated_at, url: `/chat/${c.uuid}`}))
```

Filter by `updated_at`, not `created_at`. The rest is as in Step 1.

## File format

`Inbox/AI Sessions/YYYY-MM-DD — [ChatGPT|Claude] — [title] — [first 8 chars of id].md` (date = day of last activity, local time):

```
---
source: [chatgpt / claude]
conversation_id: [full id]
updated: [update_time / updated_at]
date: YYYY-MM-DD
---
# [Title]
## What the conversation was about
[2–3 sentences]
## Key decisions and conclusions
- ...
## Materials created
- ...
## Action items
- ...
```
(no checkboxes in these files — tasks live only in TASKS.md)

## Capture rules

- Create `Inbox/AI Sessions/` if it does not exist.
- Dedup by id in three places (Glob/Grep on the first 8 characters): `Inbox/AI Sessions/*.md`, `Archive/*/AI Sessions/*.md`, `Sessions/*.md`. If a conversation was already captured but has new messages, update the file — do not create a second one.
- Skip purely informational conversations. Save only those with real substance: decisions, plans, tasks, materials. For technical details, keep only the gist.
- Nothing found → "No AI sessions found for [window]" (if you know the user was working, add "⚠️ possibly a filter failure"). ChatGPT/Claude.ai did not open or is logged out → write "unavailable, capture skipped" and `warn`; that is not the same as "there were no conversations".

## Step 3 — Actions from sessions → TASKS.md

For each session file in the window, take its "Action items" and decide on each item:

1. **Check.** Compare with `TASKS.md` and `Archive/Done — YYYY-MM.md` for the last 30 days. Already there or closed (✅ / ⛔ / ⏳ / 💬) → do not add; in the report "not added: closed dd.mm". Merge duplicates that mean the same thing.
2. **A clear action** (who, what, understandable without context) → into TASKS.md in "dumb-simple" form: one action, imperative verb, ≤ 10 words, date at the start (if any), one project emoji at the end (from the vault's emoji list, e.g. 💼 work · 💶 finance · 🏠 home · 🧠 Second Brain · 👥 people · 📚 reading · 🧳 travel). With a date ≤ 7 days away → `📅 This week`, otherwise `📥 Later`. Never into `🔥 Today`. Context and links go into the project file.
3. **A decision the user has to make** (start or not, choose between options, confirm a fact) → the `## ❓ Decide` section: `- ❓ a question that can be answered in a minute — _day, from AI session "title"_`. Phrase the question so that "yes/no" or one word is enough. No more than 3 new ❓ per run; at most 10 in the section: if there are already 10, do not add more, and report "❓ full, N questions waiting".
4. Not sure whether it is an action or just a thought → do not add it; leave it in the session file.
5. Do not rewrite the user's lines and never write `//` yourself. Delete nothing.

## Run-log line (mandatory)

Append to `Inbox/Runs — YYYY-MM.md`: `- YYYY-MM-DD HH:MM | ai-sessions-capture v4.0 | ok | ChatGPT N, Claude.ai N, tasks +N, ❓ +N`. `warn` — only if ChatGPT/Claude.ai were unavailable or part of the work failed (reason in one sentence). An extended window (catch-up) is not a `warn`: put "window from dd.mm HH:MM" at the end; when catching up a missed evening, also add `catch-up for dd.mm` (the evening being caught up) — `check_vault.py` looks for exactly this marker. No longer than 300 characters; the date is today's (or yesterday's when catching up); the version in the stamp is mandatory.

## Step C — Catch up colleagues (last of all, after your run-log line)

The platform does not re-run missed tasks when the computer comes back online. So the agents catch up for each other: if you have reached this step, the computer is online and you can re-launch whoever did not run. The user does not have to press anything.

1. If you yourself were launched as a catch-up (the launch message contains the word "catch-up"), skip this step entirely.
2. If the run log has a `| catch-up |` line younger than 60 minutes, skip.
3. Call `list_triggers` (Claude Code Remote connector). Colleagues: `Daily focus briefing`, `Daily inbox processing`, `Weekly summary`, `system-doctor`. For each enabled one, use `cron_expression` (respect `CRON_TZ=<user-tz>`) to find the last slot that has passed. Ignore slots older than 48 hours — those belong to the doctor.
4. A colleague has missed a slot if all three hold: the slot passed more than 60 minutes ago; `Inbox/Runs — YYYY-MM.md` has no line from that agent with status `ok`/`warn` and a time ≥ slot − 2 h (some lines are written in UTC); `last_fired_at` in `list_triggers` is older than 45 minutes. `Daily inbox processing` runs 30 minutes after you — its slot for today has not passed yet, leave it alone; this is only about yesterday. Re-launch `Daily focus briefing` only before 14:00 local time; `Weekly summary` only on Monday–Tuesday.
5. For each one that missed — `fire_trigger` with `text`: `catch-up for <slot date dd.mm HH:MM>, launched by ai-sessions-capture at HH:MM`. Order: capture → inbox → briefing → weekly → doctor.
6. Append one line to the run log: `- YYYY-MM-DD HH:MM | catch-up | ok | ai-sessions-capture → re-launched: <who> (<slot>)`. If you re-launched nobody, write no line and do not mention it. If you did — one line in the summary: "re-launched: …".
7. If `list_triggers` / `fire_trigger` are unavailable — one line in the summary, "colleague catch-up: connector unavailable", without `warn`.

## Report in chat

Three lines (a fourth if there was a catch-up): capture (how many saved; "not found" and "unavailable" are different things); in TASKS: tasks +N, ❓ +N, "not added: closed" (if any); a warning if `Inbox/` has notes older than 7 days.
