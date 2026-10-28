# Lessons learned

Running five scheduled agents and a few scripts every day for three months (August–October 2026) taught more than designing them did. Most of these lessons are about the same thing: **a system that fails quietly is worse than one that fails loudly.** Each lesson below is a real incident, followed by what changed.

## 1. "Alive" has to be proven by the work, not by the process

**What happened.** The Telegram backstop puller collected nothing from late August until 2026-10-06, about five weeks. The daily check said "alive" every morning. The job was launched as `python …; touch heartbeat`, so the heartbeat file was updated on every launch, whether or not Python did anything. The checker looked at that file's timestamp.

**What changed.** The script now writes a success marker only after a completed run, and launchd starts Python directly, with no shell wrapper. The checker trusts only that marker. The same rule now applies to every job: liveness is a trace of finished work, never a sign that something started.

## 2. Synced folders and runtimes don't mix

**What happened.** The root cause of lesson 1 was that the scripts, their virtualenv and their session files lived in a cloud-synced Documents folder with "optimise storage" switched on. The disk was over 90% full, so the sync client evicted 28,635 of the virtualenv's 28,780 files, leaving placeholders. Python blocked on reading the first evicted library and printed nothing. A month earlier (2026-09-19), the same folder had made launchd fail before it even started the script (exit code 78), because it could not open a log file there. For three weeks that was treated as a scheduling problem.

**What changed.** Working copies of scripts, virtualenvs, sessions, state and logs moved to local, non-synced folders. Master copies stay in the vault for reading and versioning. The rule: nothing written by automation ever goes into a synced folder.

## 3. Two writers on one file will eventually overwrite each other

**What happened.** The earliest recurring bug was "a closed task comes back". Every time, two agents were writing into the same container, each working from its own idea of the file. Later, after the computer woke from sleep, several catch-up runs sometimes started within the same minute. They overwrote each other's edits to `TASKS.md` four times in October.

**What changed.** A file-ownership table, where an agent not listed as a writer does not write. For the one shared file, TASKS.md, each agent owns specific sections and operations, and every agent re-reads the file immediately before each write and applies its edits to the fresh copy.

## 4. A file on disk is not proof the agent runs it

**What happened.** On 2026-09-25 four prompts were updated, and two of them never took effect. Nobody noticed for a week. On 2026-10-06 updated prompt files had been on disk for four days, yet no run showed the new version. The scheduler was running its own stored copy of each prompt, not the file.

**What changed.** Every prompt carries a `version:` and writes it into its run-log line. A registry lists the expected version of each agent, and the daily check compares the two. A rollout now has four steps: bump the version, update the registry, put the file in place *and* paste the text into the task, then run it once. An agent counts as updated only when a run-log line shows the new version.

## 5. The cloud scheduler does not re-run missed slots, and says "succeeded" anyway

**What happened.** Observed on 2026-10-12: when the computer was asleep at a slot, the run was either skipped or delivered hours later at a random time. The scheduler marked it "succeeded" after 4–7 seconds even when the session never reached the vault, and the failure note went to a place the vault never sees. On 2026-10-17 the platform also switched one daily task off without warning.

**What changed.** The agents now catch up for each other. At the end of each run, an agent checks whether a colleague missed a slot (no run-log line, slot older than an hour) and re-launches it, with the run log acting as a lock. The weekly doctor also checks that every task is still enabled. The only accepted sign of success is the agent's own line in the run log.

## 6. Check that the fix itself works, not just that it fired

**What happened.** Two days after catch-up launched (2026-10-14), a re-launched evening agent turned out to run in the cloud only, with no access to the local computer, so it could neither read the vault nor use the local browser. The catch-up lines in the run log looked fine; the work had not happened.

**What changed.** A catch-up only counts if the re-launched agent's own line appears afterwards. For agents that need the local machine, the real safety net is the next scheduled run, which widens its collection window from the run log automatically.

## 7. A checker that always warns teaches you to ignore it

**What happened.** By early October, the daily check had returned `warn` on 29 of 29 runs. The same warnings sat there for days, and a genuinely new failure looked just like the old ones. An earlier alarm ("Telegram silent for 664 hours") was correct, and it was dismissed as noise.

**What changed.** Each warning now has a stable key. Anything not seen in the last 48 hours is marked new, goes to the top of the report and triggers a desktop notification. Known warnings are listed further down with "open since dd.mm".

## 8. Missing data is not a mismatch

**What happened.** After a rollout on 2026-10-06/07, the check reported a version mismatch for the two weekly agents for five days in a row, because they had simply not had a slot yet. On 2026-10-11 an agent repeated that warning as fact.

**What changed.** Both the checker's documentation and the doctor's instructions now say: before treating a version mismatch as a failed rollout, compare the rollout date with the agent's schedule. If no slot has passed since then, there is no data yet, and nothing is wrong.

## 9. Without snapshots, an agent's mistake is permanent

**What happened.** The vault had no git and no backup, and the sync service kept only the latest version of each file. When checked on 2026-10-06, the most recent spare copy of `TASKS.md` was two weeks old. A bad write by any agent could not be undone.

**What changed.** A snapshot script copies the files that agents rewrite daily (task list, rules, dashboard, registry, archive, all prompts) twice a day, before the morning and evening runs, to a folder outside the vault, and keeps them for 30 days. The daily check warns if a snapshot is overdue or if `TASKS.md` has shrunk by half in three days, and gives the path to the intact copy. Rolling back is a documented four-step routine that never deletes the broken version.

## 10. A rule without an owner is a wish

**What happened.** The vault's data rules said service reports should be archived "by the end of the month", but no agent was assigned to do it. By 2026-10-21, 62 daily reports had piled up in the Inbox since early August. While fixing this, another trap appeared: the checker sometimes rewrites old files, so file modification times were off by weeks.

**What changed.** Archiving became an explicit step for the evening agent (reports older than 14 days, dated by the file *name*, never by mtime, with links fixed after the move). The weekly doctor acts as a backstop and flags it if more than three files have piled up, since that means the evening step is not working.

## 11. Instructions that live only inside a tool can't be reviewed

**What happened.** Until 2026-10-07 the doctor's prompt existed only inside the scheduler. It could not be read, compared or rolled back. When it was finally saved to disk, a review found that its table of ready-made fixes recommended re-running an old install script, which would have undone the 2026-10-06 repair.

**What changed.** Every prompt now has a master copy on disk and is included in the snapshots. The doctor's command table has an explicit "never recommend" row.

## 12. One place for answers beats two

**What happened.** Before v4, decisions were split between a daily note's review queue and `TASKS.md`, and the user had several markers to learn (`>`, `→`, `x`, `//`) across two files, each read by different agents at different times.

**What changed.** In v4 (2026-10-19) daily notes were retired. Everything that needs the user's action or answer lives in `TASKS.md`, with a `❓ Decide` section capped at 10 questions. The only way to reply is `//` at the end of a line. Whichever of the morning and evening agents runs first executes the reply.
