#!/usr/bin/env python3
"""
tg_pull.py — Telegram -> Obsidian backstop.

Pulls messages from the configured chats via Telethon (a user account, not a bot)
and drops them into the vault in the same format as the Telegram Sync plugin.
Works independently of Obsidian: all it needs is a running Mac.

Modes:
    python3 tg_pull.py --login        # one-time authorisation (asks for phone/code/2FA)
    python3 tg_pull.py --list-chats   # list dialogs, to fill in the config
    python3 tg_pull.py --dry-run      # show what would be created, write nothing
    python3 tg_pull.py                # normal run (this is what launchd calls)

Config:  tg_pull_config.json next to the script (created on first run; see tg_pull_config.example.json).
Secrets: TELEGRAM_API_ID / TELEGRAM_API_HASH (+ optional TELEGRAM_PROXY) from the environment
         or from a .env file next to the script (see .env.example).
State:   tg_pull_state.json — ids of messages already pulled.
Log:     tg_pull.log
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "tg_pull_config.json"
STATE_PATH = BASE_DIR / "tg_pull_state.json"
LOG_PATH = BASE_DIR / "tg_pull.log"
LOCK_PATH = BASE_DIR / "tg_pull.lock"
SESSION_PATH = BASE_DIR / "tg_pull"  # a separate session — do NOT reuse the MCP server's session
# Install into ~/Library/Application Support/second-brain/tg_pull, NOT ~/Documents:
# ~/Documents is synced by iCloud, which evicted the venv and the session from disk — the script hung on reads.
SUCCESS_MARKER = Path.home() / "Library" / "Logs" / "second-brain" / "tgpull.ok"

DEFAULT_VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT", "~/Vault")).expanduser()

# Vault folder names (keep in sync with check_vault.py)
INBOX = "Inbox"
ARCHIVE = "Archive"        # Archive/YYYY-MM/...

# The Telegram Sync plugin cuts the file name to 30 characters of content
NAME_LEN = 30
# Window within which a plugin note counts as the same message as ours
DEDUP_WINDOW_SEC = 300
# How many ids to keep in the state per chat
STATE_KEEP_IDS = 2000
# Maximum log size before truncation
LOG_MAX_BYTES = 2 * 1024 * 1024

DEFAULT_CONFIG = {
    "vault": str(DEFAULT_VAULT),
    "note_folder": "Telegram",
    "days_back": 14,
    "per_chat_limit": 300,
    "transcribe_voices": True,
    "whisper_model": "medium",
    "download_media": True,
    "max_media_mb": 100,
    "chats": [
        {"id": "me", "label": "Saved Messages"},
    ],
}

# Characters the plugin replaces with "_" in the file name
_BAD_CHARS_RE = re.compile(r'[\\/:*?"<>|\r\n\t]')
_TS_RE = re.compile(r" - (\d{17})$")


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            tail = LOG_PATH.read_text(encoding="utf-8", errors="replace")[-LOG_MAX_BYTES // 2 :]
            LOG_PATH.write_text(tail, encoding="utf-8")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_json(CONFIG_PATH, DEFAULT_CONFIG)
        log(f"Created config {CONFIG_PATH} — add your chats there and check the vault path")
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG_PATH, {}))
    return cfg


def load_dotenv(path: Path) -> dict:
    """Reads .env without requiring python-dotenv."""
    out = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        out[key.strip()] = val
    return out


def get_credentials() -> tuple[int, str, str | None]:
    """API_ID / API_HASH from the environment or a .env next to the script."""
    env = {**load_dotenv(BASE_DIR / ".env"), **os.environ}

    def pick(*names):
        for n in names:
            if env.get(n):
                return env[n]
        return None

    api_id, api_hash, proxy = (
        pick("TELEGRAM_API_ID", "TG_API_ID", "API_ID"),
        pick("TELEGRAM_API_HASH", "TG_API_HASH", "API_HASH"),
        pick("TELEGRAM_PROXY", "TG_PROXY", "PROXY_URL"),
    )
    if not api_id or not api_hash:
        raise SystemExit(
            "API_ID / API_HASH not found.\n"
            f"Put TELEGRAM_API_ID and TELEGRAM_API_HASH into {BASE_DIR / '.env'} (see .env.example)\n"
            "(get them at https://my.telegram.org; the same values a telegram-mcp server would use)"
        )
    return int(api_id), api_hash, proxy


def parse_proxy(proxy_url: str | None):
    """socks5://user:pass@host:port -> tuple for Telethon. None if not set."""
    if not proxy_url:
        return None
    m = re.match(
        r"^(?P<scheme>socks5|socks4|http)://"
        r"(?:(?P<user>[^:@]+)(?::(?P<pw>[^@]*))?@)?"
        r"(?P<host>[^:/]+):(?P<port>\d+)/?$",
        proxy_url.strip(),
    )
    if not m:
        log(f"Could not parse proxy '{proxy_url}' — connecting directly")
        return None
    import socks  # type: ignore

    kinds = {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}
    parts = [kinds[m.group("scheme")], m.group("host"), int(m.group("port")), True]
    if m.group("user"):
        parts += [m.group("user"), m.group("pw") or ""]
    return tuple(parts)


# --------------------------------------------------------------------------
# File names — exactly like the Telegram Sync plugin
# --------------------------------------------------------------------------


def sanitize(text: str) -> str:
    """The plugin replaces forbidden characters and line breaks with '_'."""
    return _BAD_CHARS_RE.sub("_", text or "")


def content_prefix(text: str, length: int = NAME_LEN) -> str:
    """
    First N characters of the sanitised text — the base of the file name.
    Inner spaces and underscores from line breaks are preserved:
    the plugin does not collapse them, and we must match it character for character,
    otherwise dedup against already-captured notes will not work.
    """
    return sanitize((text or "").strip())[:length]


def stamp_ms(dt: datetime) -> str:
    """YYYYMMDDHHmmssSSS — like the plugin's {{messageTime:YYYYMMDDHHmmssSSS}}."""
    return dt.strftime("%Y%m%d%H%M%S") + f"{dt.microsecond // 1000:03d}"


def note_filename(text: str, dt: datetime) -> str:
    prefix = content_prefix(text) or "message"
    return f"{prefix} - {stamp_ms(dt)}.md"


def chat_field(chat_spec, field: str, default=None):
    """chats in the config may be written either as a string or as an object."""
    if isinstance(chat_spec, dict):
        value = chat_spec.get(field)
        return default if value in (None, "") else value
    return default


def media_filename(name: str, ext: str, dt: datetime) -> str:
    base = sanitize(name).strip() or "file"
    ext = (ext or "bin").lstrip(".")
    return f"{base} - {stamp_ms(dt)}.{ext}"


# --------------------------------------------------------------------------
# Dedup against what the plugin has already written
# --------------------------------------------------------------------------


def build_existing_index(vault: Path, note_folder: str) -> list[tuple[str, float]]:
    """
    Collects (name prefix, epoch) for every note already sitting in the
    inbox folder and in the Archive. Needed so we do not duplicate what
    the plugin managed to capture on its own.
    """
    index: list[tuple[str, float]] = []
    roots = [vault / note_folder, vault / INBOX]
    archive = vault / ARCHIVE
    if archive.is_dir():
        for month in archive.iterdir():
            if month.is_dir():
                roots.append(month / "Telegram")
                roots.append(month)
    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_file():
                continue
            m = _TS_RE.search(p.stem)
            if not m:
                continue
            try:
                raw = m.group(1)
                dt = datetime.strptime(raw[:14], "%Y%m%d%H%M%S")
            except ValueError:
                continue
            prefix = p.stem[: m.start()]
            index.append((prefix, dt.timestamp()))
    return index


def already_captured(index: list[tuple[str, float]], text: str, dt: datetime) -> bool:
    """Same content prefix and a time within the window -> already captured by the plugin."""
    prefix = content_prefix(text)
    if not prefix:
        return False
    target = dt.replace(tzinfo=None).timestamp()
    for existing_prefix, ts in index:
        if existing_prefix == prefix and abs(ts - target) <= DEDUP_WINDOW_SEC:
            return True
    return False


# --------------------------------------------------------------------------
# Voice message transcription
# --------------------------------------------------------------------------

_whisper_backend = None  # per-process cache of the chosen backend


def _detect_whisper(model_name: str):
    """mlx-whisper (Apple Silicon) -> faster-whisper -> nothing."""
    global _whisper_backend
    if _whisper_backend is not None:
        return _whisper_backend

    try:
        import mlx_whisper  # type: ignore

        repo = {
            "tiny": "mlx-community/whisper-tiny",
            "base": "mlx-community/whisper-base-mlx",
            "small": "mlx-community/whisper-small-mlx",
            "medium": "mlx-community/whisper-medium-mlx",
            "large": "mlx-community/whisper-large-v3-mlx",
        }.get(model_name, "mlx-community/whisper-medium-mlx")

        def run(path: str) -> str:
            res = mlx_whisper.transcribe(path, path_or_hf_repo=repo)
            return (res.get("text") or "").strip()

        _whisper_backend = ("mlx-whisper", run)
        return _whisper_backend
    except Exception:
        pass

    try:
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(model_name, device="cpu", compute_type="int8")

        def run(path: str) -> str:
            segments, _ = model.transcribe(path, beam_size=5)
            return " ".join(s.text.strip() for s in segments).strip()

        _whisper_backend = ("faster-whisper", run)
        return _whisper_backend
    except Exception:
        pass

    _whisper_backend = (None, None)
    return _whisper_backend


def transcribe(path: Path, model_name: str) -> str | None:
    name, run = _detect_whisper(model_name)
    if not run:
        return None
    try:
        started = time.time()
        text = run(str(path))
        log(f"  transcript ({name}, {time.time() - started:.0f}s): {len(text)} characters")
        return text or None
    except Exception as exc:  # transcription must not take the run down
        log(f"  transcription failed: {exc}")
        return None


# --------------------------------------------------------------------------
# Building the note
# --------------------------------------------------------------------------


def forward_header(msg) -> str:
    """**Forwarded from [Name](https://t.me/username)** — like the plugin."""
    fwd = getattr(msg, "forward", None)
    if not fwd:
        return ""
    name = None
    username = None
    sender = getattr(fwd, "sender", None) or getattr(fwd, "chat", None)
    if sender is not None:
        first = getattr(sender, "first_name", "") or ""
        last = getattr(sender, "last_name", "") or ""
        name = (f"{first} {last}".strip()) or getattr(sender, "title", None)
        username = getattr(sender, "username", None)
    if not name:
        name = getattr(fwd, "from_name", None)
    if not name:
        return ""
    if username:
        return f"**Forwarded from [{name}](https://t.me/{username})**"
    return f"**Forwarded from {name}**"


def build_note(msg, media_link: str | None, transcript: str | None) -> str:
    parts = []
    header = forward_header(msg)
    if header:
        parts.append(header)
    if media_link:
        parts.append(f"[[{media_link}]]")
    body = (getattr(msg, "text", "") or "").strip()
    if transcript:
        stamp = msg.date.astimezone().strftime("%Y-%m-%d %H:%M")
        block = f"**🎤 Voice message, transcript** ({stamp})\n\n{transcript}"
        parts.append(block if not body else f"{block}\n\n---\n\n{body}")
    elif body:
        parts.append(body)
    return "\n\n".join(parts).strip() + "\n"


def note_text_for_name(msg, transcript: str | None) -> str:
    """What to name the file after: the message text, or the transcript if there is no text."""
    body = (getattr(msg, "text", "") or "").strip()
    if body:
        return body
    if transcript:
        return transcript
    return ""


def media_kind(msg) -> str | None:
    """photo / voice / audio / document — like the plugin's {{file:type}}."""
    if getattr(msg, "photo", None):
        return "photo"
    if getattr(msg, "voice", None):
        return "voice"
    if getattr(msg, "audio", None):
        return "audio"
    if getattr(msg, "video", None) or getattr(msg, "video_note", None):
        return "video"
    if getattr(msg, "document", None):
        return "document"
    return None


def guess_media_name(msg, kind: str, chat_id: int) -> tuple[str, str]:
    """Returns (name without extension, extension)."""
    doc = getattr(msg, "document", None)
    if doc is not None:
        for attr in getattr(doc, "attributes", []) or []:
            fname = getattr(attr, "file_name", None)
            if fname:
                stem, _, ext = fname.rpartition(".")
                return (stem or fname), (ext or "bin")
    defaults = {
        "photo": ("jpg"),
        "voice": ("ogg"),
        "audio": ("mp3"),
        "video": ("mp4"),
        "document": ("bin"),
    }
    ext = defaults.get(kind, "bin")
    mime = getattr(doc, "mime_type", "") if doc is not None else ""
    if kind == "voice" and "mpeg" in mime:
        ext = "mp3"
    return f"{kind}_{abs(chat_id)}_{msg.id}", ext


# --------------------------------------------------------------------------
# Main run
# --------------------------------------------------------------------------


async def process_chat(client, chat_spec, cfg, state, existing, dry_run: bool) -> int:
    chat_id = chat_field(chat_spec, "id", chat_spec)
    label = chat_field(chat_spec, "label", str(chat_id))

    vault = Path(cfg["vault"]).expanduser()
    note_dir = vault / chat_field(chat_spec, "note_folder", cfg["note_folder"])

    try:
        entity = await client.get_entity(chat_id)
    except Exception as exc:
        log(f"[{label}] could not open chat: {exc}")
        return 0

    key = str(getattr(entity, "id", chat_id))
    chat_state = state.setdefault(key, {"seen": []})
    seen = set(chat_state.get("seen", []))

    since = datetime.now(timezone.utc) - timedelta(days=int(cfg["days_back"]))
    created = 0

    messages = []
    async for msg in client.iter_messages(entity, limit=int(cfg["per_chat_limit"])):
        if msg.date < since:
            break
        messages.append(msg)
    messages.reverse()  # oldest first — the order in the vault then makes sense

    for msg in messages:
        if msg.id in seen:
            continue
        if getattr(msg, "action", None) is not None:
            seen.add(msg.id)
            continue

        local_dt = msg.date.astimezone()
        kind = media_kind(msg)
        media_link = None
        transcript = None
        downloaded: Path | None = None

        if kind and cfg.get("download_media", True):
            size = getattr(getattr(msg, "document", None), "size", 0) or 0
            if size and size > int(cfg["max_media_mb"]) * 1024 * 1024:
                log(f"[{label}] msg {msg.id}: file is {size // 1024 // 1024}MB — skipping")
            else:
                stem, ext = guess_media_name(msg, kind, getattr(entity, "id", 0))
                fname = media_filename(stem, ext, local_dt)
                target_dir = note_dir / f"{kind}s"
                target = target_dir / fname
                if dry_run:
                    log(f"[{label}] DRY media -> {target.relative_to(vault)}")
                    media_link = fname
                else:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        try:
                            await client.download_media(msg, file=str(target))
                        except Exception as exc:
                            log(f"[{label}] msg {msg.id}: download failed — {exc}")
                            target = None  # type: ignore
                    if target and target.exists():
                        downloaded = target
                        media_link = fname

        if kind == "voice" and cfg.get("transcribe_voices", True) and downloaded and not dry_run:
            transcript = transcribe(downloaded, str(cfg.get("whisper_model", "medium")))

        name_source = note_text_for_name(msg, transcript)
        if not name_source and not media_link:
            seen.add(msg.id)
            continue
        if not name_source:
            name_source = media_link or "file"

        if already_captured(existing, name_source, local_dt):
            log(f"[{label}] msg {msg.id}: already captured by the plugin — skipping")
            seen.add(msg.id)
            continue

        fname = note_filename(name_source, local_dt)
        target = note_dir / fname
        content = build_note(msg, media_link, transcript)

        if dry_run:
            log(f"[{label}] DRY note -> {target.relative_to(vault)}")
        else:
            note_dir.mkdir(parents=True, exist_ok=True)
            if target.exists():
                seen.add(msg.id)
                continue
            target.write_text(content, encoding="utf-8")
            existing.append((content_prefix(name_source), local_dt.replace(tzinfo=None).timestamp()))
            log(f"[{label}] + {fname}")
        created += 1
        seen.add(msg.id)

    chat_state["seen"] = sorted(seen)[-STATE_KEEP_IDS:]
    return created


def wait_for_network(host: str = "149.154.167.50", port: int = 443, max_wait_s: int = 120) -> bool:
    """After the Mac wakes up, launchd starts the run before Wi-Fi is back (2026-10-07: "Network is
    unreachable" at 11:03 — the run failed and waited for the next hour, and the morning check raised
    an alarm). Wait up to max_wait_s seconds for the network; if it never comes, carry on and let
    Telethon report the error itself."""
    import socket
    deadline = time.time() + max_wait_s
    waited = False
    while True:
        try:
            socket.create_connection((host, port), timeout=5).close()
            if waited:
                log("Network is back — connecting")
            return True
        except OSError:
            if time.time() >= deadline:
                log(f"No network for {max_wait_s} s — trying to connect anyway")
                return False
            if not waited:
                log("No network yet (Mac just woke up?) — waiting up to 2 minutes")
                waited = True
            time.sleep(10)


async def run(cfg: dict, dry_run: bool) -> int:
    from telethon import TelegramClient

    api_id, api_hash, proxy_url = get_credentials()
    if not proxy_url:
        wait_for_network()
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash, proxy=parse_proxy(proxy_url))

    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise SystemExit(
            "Session is not authorised. Run this once in a terminal:\n"
            f"    python3 {Path(__file__).name} --login"
        )

    vault = Path(cfg["vault"]).expanduser()
    if not vault.is_dir():
        await client.disconnect()
        raise SystemExit(f"Vault not found: {vault}. Fix 'vault' in {CONFIG_PATH}")

    state = load_json(STATE_PATH, {})
    existing = build_existing_index(vault, cfg["note_folder"])
    log(f"Known notes in the vault: {len(existing)}")

    total = 0
    for chat_spec in cfg["chats"]:
        total += await process_chat(client, chat_spec, cfg, state, existing, dry_run)

    if not dry_run:
        save_json(STATE_PATH, state)
    await client.disconnect()
    return total


async def do_login() -> None:
    from telethon import TelegramClient

    api_id, api_hash, proxy_url = get_credentials()
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash, proxy=parse_proxy(proxy_url))
    # start() is interactive — this is the only mode where that is appropriate
    await client.start()
    me = await client.get_me()
    print(f"Done. Authorised as {me.first_name} (@{me.username}).")
    print(f"Session: {SESSION_PATH}.session")
    await client.disconnect()


async def do_list_chats(limit: int = 60) -> None:
    from telethon import TelegramClient

    api_id, api_hash, proxy_url = get_credentials()
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash, proxy=parse_proxy(proxy_url))
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise SystemExit("First run: python3 tg_pull.py --login")
    print(f"{'id':>16}  {'type':<10}  name")
    print("-" * 70)
    async for dialog in client.iter_dialogs(limit=limit):
        ent = dialog.entity
        kind = "bot" if getattr(ent, "bot", False) else ("group" if dialog.is_group else "private")
        if dialog.is_channel:
            kind = "channel"
        uname = getattr(ent, "username", None)
        suffix = f"  @{uname}" if uname else ""
        print(f"{dialog.id:>16}  {kind:<10}  {dialog.name}{suffix}")
    print("\nSaved Messages is id 'me'. Add the chats you want to tg_pull_config.json -> chats.")
    await client.disconnect()


def acquire_lock():
    """Do not let two runs work at the same time."""
    import fcntl

    fh = LOCK_PATH.open("w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("Another run is already in progress — exiting")
        sys.exit(0)
    return fh


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram -> Obsidian backstop")
    parser.add_argument("--login", action="store_true", help="one-time authorisation")
    parser.add_argument("--list-chats", action="store_true", help="list dialogs")
    parser.add_argument("--dry-run", action="store_true", help="write nothing")
    args = parser.parse_args()

    if args.login:
        asyncio.run(do_login())
        return
    if args.list_chats:
        asyncio.run(do_list_chats())
        return

    lock = acquire_lock()  # noqa: F841 — held until the process exits
    cfg = load_config()
    try:
        created = asyncio.run(run(cfg, args.dry_run))
    except SystemExit:
        raise
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
    log(f"Done. New notes: {created}")
    # Success marker: check_vault judges liveness by this, not by the fact that the script was launched
    # (for over a month a "heartbeat" kept being updated while the script was hanging — audit ISSUE-2).
    if not args.dry_run:
        try:
            SUCCESS_MARKER.parent.mkdir(parents=True, exist_ok=True)
            SUCCESS_MARKER.write_text(f"{datetime.now().isoformat(timespec='seconds')} new={created}\n", encoding="utf-8")
        except OSError as exc:
            log(f"Could not write success marker {SUCCESS_MARKER}: {exc}")


if __name__ == "__main__":
    main()
