# Second Brain agents

A personal operating system built from five scheduled AI agents and a few small scripts. They run on top of a plain-text notes vault (Obsidian).

I'm a People and Organisational Development lead, not a software engineer. I built this with Claude Code, and I designed it the way I would design work for a team. Every file has an owner, the hand-offs are written down, there is a check that does not depend on anyone's goodwill, and the human keeps the decisions.

## What it does

Every day, without me opening anything:

- **Evening.** One agent collects my conversations with AI assistants. A second sorts everything that arrived during the day: email, meeting notes, Telegram messages, calendar. Each item lands where it belongs: meetings, projects, sessions or the archive. Anything that needs action becomes one line in a single task list, `TASKS.md`.
- **Morning.** Code runs first. `check_vault.py` verifies that each agent actually did its job, fixes what is safe to fix and writes a short health report. Then the briefing agent acts on my replies in the task list, picks at most five things for today, and lists the questions only I can answer.
- **Sunday.** A weekly summary, a review of the task list and an audit of the system itself.
- **Monday.** A "doctor" agent checks that every agent is alive and running the version it should. It repairs what it can inside the vault and turns everything else into a task with a ready-made command.

I reply to the agents in one place: `TASKS.md`, with a `//` comment next to a task. They never act on anything that only I can decide.

## How it is designed

The design rests on four principles, each learned from a failure:

1. **One writer per file.** When two agents write to the same file, closed tasks come back. The ownership table in [docs/architecture.md](docs/architecture.md) is the rule.
2. **Agents talk through files, not memory.** Every run ends with one line in a shared run log, and the next agent reads that log to know where to start.
3. **Code checks, not the agent.** Whether a file exists, whether a note is a duplicate, whether a section is present: a script checks these every morning. An agent reviews only meaning, once a week.
4. **Errors show up in one place.** The morning briefing has a "System" block. Nothing is reported anywhere else.

A version registry records which prompt each agent should be running, and the checker compares it with what the agents report in the run log. I learned the hard way that a prompt file on disk is no proof that the scheduler runs it.

## What's in the repo

| Path | What it is |
|---|---|
| [`prompts/`](prompts/) | The five agent instructions, as they run today: `daily-focus-briefing`, `ai-sessions-capture`, `daily-inbox-processing`, `weekly-summary`, `system-doctor` |
| [`scripts/check_vault.py`](scripts/check_vault.py) | The daily checker. It looks at missing or stale runs, version drift, duplicates, the task-list structure, notes that disappeared, and snapshots |
| [`scripts/tg_pull.py`](scripts/tg_pull.py) | A Telegram-to-vault backstop. It pulls messages from chosen chats once an hour, so nothing depends on the notes app being open |
| [`scripts/snapshot.py`](scripts/snapshot.py) | Twice-daily snapshots of the files that agents rewrite, so a bad edit can be rolled back |
| `scripts/install_*.sh` | macOS launchd installers for the three scripts |
| [`docs/architecture.md`](docs/architecture.md) | The daily flow, the file-ownership table, the run-log contract, the error matrix and the two-level checker |
| [`docs/lessons.md`](docs/lessons.md) | Twelve things that broke and what changed because of them |

## Running it yourself

This is a reference implementation, not a product. Folder names, schedules and sources match one person's vault.

1. Point the scripts at your vault: `export SECOND_BRAIN_VAULT=~/path/to/vault`. The default is `~/Vault`.
2. Try the checker without changing anything: `python3 scripts/check_vault.py --dry-run`.
3. For Telegram, copy `scripts/.env.example` to `scripts/.env` and add your own API id and hash from my.telegram.org. Then copy `tg_pull_config.example.json` to `tg_pull_config.json` and run `python3 scripts/tg_pull.py --login`.
4. Load the prompts into your scheduler. I use scheduled tasks in Claude (Cowork). Bump the `version:` field and the registry together whenever you change a prompt.

Code comments mention audit items such as `ISSUE-3` and dated precedents. They come from a review of the whole system in October 2026, and I kept them because the reason for a check matters more than the check itself.

## License

MIT
