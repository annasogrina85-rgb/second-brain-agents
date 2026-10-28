#!/bin/bash
# Install the Telegram backstop (tg_pull): venv + dependencies + an hourly launchd job.
#
# Run it from the folder that holds tg_pull.py. Recommended location (outside iCloud):
#     mkdir -p ~/Library/Application\ Support/second-brain/tg_pull
#     cp tg_pull.py .env.example tg_pull_config.example.json ~/Library/Application\ Support/second-brain/tg_pull/
#     cd ~/Library/Application\ Support/second-brain/tg_pull && bash /path/to/install_tgpull.sh
#
# Why not ~/Documents: that folder is synced by iCloud.
#   - 2026-08-28: all three launchd jobs died at once — launchd could not open their log files
#     (they lived in ~/Documents) for writing and exited with code 78. Logs now go to ~/Library/Logs.
#   - Later iCloud evicted the venv and the Telethon session from disk, and the script silently
#     hung on reads for weeks. The working folder must live outside iCloud.
#
# Liveness: tg_pull.py itself writes ~/Library/Logs/second-brain/tgpull.ok at the end of a
# SUCCESSFUL run, and check_vault.py judges liveness only by that file. (An earlier version of this
# installer touched a heartbeat after every launch — it kept saying "alive" while the script hung.)
#
# Optional env: SECOND_BRAIN_VAULT (default ~/Vault) is passed to the job; tg_pull_config.json
# "vault" overrides it.

set -euo pipefail

BASE="$(cd "$(pwd)" && pwd)"
[ -f "$BASE/tg_pull.py" ] || BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$HOME/Library/Logs/second-brain"
mkdir -p "$LOGDIR"
LABEL="com.example.secondbrain.tgpull"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
VENV="$BASE/.venv"
VAULT="${SECOND_BRAIN_VAULT:-$HOME/Vault}"

echo "==> Script folder: $BASE"

if [ ! -f "$BASE/tg_pull.py" ]; then
  echo "!! tg_pull.py not found in $BASE. Put it there and run again."
  exit 1
fi
case "$BASE" in
  "$HOME/Documents"*|"$HOME/Desktop"*)
    echo "!! $BASE is inside an iCloud-synced folder — iCloud may evict the venv/session. Use ~/Library/Application Support/second-brain/tg_pull instead." ;;
esac

# --- 1. Virtual environment ---------------------------------------------------
if [ ! -x "$VENV/bin/python3" ]; then
  echo "==> Creating environment $VENV"
  python3 -m venv "$VENV"
fi
PY="$VENV/bin/python3"

echo "==> Installing dependencies"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet telethon pysocks

# --- 2. Voice transcription ---------------------------------------------------
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
  echo "==> Apple Silicon: installing mlx-whisper (fast, runs on the Neural Engine/GPU)"
  "$PY" -m pip install --quiet mlx-whisper || {
    echo "   mlx-whisper failed to install, falling back to faster-whisper"
    "$PY" -m pip install --quiet faster-whisper
  }
else
  echo "==> Installing faster-whisper"
  "$PY" -m pip install --quiet faster-whisper
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "!! ffmpeg not found — it is needed for voice messages. Install it: brew install ffmpeg"
fi

# --- 3. .env and config -------------------------------------------------------
if [ ! -f "$BASE/.env" ]; then
  echo "!! No .env in $BASE with TELEGRAM_API_ID / TELEGRAM_API_HASH."
  echo "   Copy .env.example to .env and fill it in (values from https://my.telegram.org)."
fi
if [ ! -f "$BASE/tg_pull_config.json" ] && [ -f "$BASE/tg_pull_config.example.json" ]; then
  echo "==> No tg_pull_config.json yet — copy tg_pull_config.example.json and edit it (or let the first run create a default)."
fi

# --- 4. launchd job -----------------------------------------------------------
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST" "$PLIST.bak-$(date +%Y%m%d)" 2>/dev/null || true

cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$BASE/tg_pull.py</string>
    </array>

    <key>WorkingDirectory</key><string>$BASE</string>

    <!-- hourly; after the Mac wakes up launchd catches up the missed run -->
    <key>StartInterval</key><integer>3600</integer>
    <key>RunAtLoad</key><true/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key><string>$HOME</string>
        <key>SECOND_BRAIN_VAULT</key><string>$VAULT</string>
    </dict>

    <key>StandardOutPath</key><string>$LOGDIR/tgpull.log</string>
    <key>StandardErrorPath</key><string>$LOGDIR/tgpull.log</string>

    <key>ProcessType</key><string>Background</string>
    <key>LowPriorityIO</key><true/>
    <key>Nice</key><integer>5</integer>
</dict>
</plist>
PLIST_END

echo "==> Plist written: $PLIST"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
echo "==> Job loaded: $LABEL (hourly + at login)"

# --- 5. What's next -----------------------------------------------------------
cat <<NEXT

────────────────────────────────────────────────────────────
Three one-time steps left:

1) Log in to Telegram (asks for phone, code, and the 2FA password if set):
     $PY "$BASE/tg_pull.py" --login

2) List your chats and add the ones you want to tg_pull_config.json:
     $PY "$BASE/tg_pull.py" --list-chats

3) IMPORTANT. If your vault lives in ~/Documents (or another protected folder),
   grant this Python Full Disk Access, otherwise launchd will silently fail
   to write into the vault:
     System Settings -> Privacy & Security -> Full Disk Access -> "+" -> add:
     $PY
   (in the file picker: Cmd+Shift+G and paste the path above)

Dry run, writes nothing:
     $PY "$BASE/tg_pull.py" --dry-run

Logs:            $LOGDIR/tgpull.log  and  $BASE/tg_pull.log
Success marker:  $LOGDIR/tgpull.ok
Remove the job:  launchctl bootout gui/$UID/$LABEL
────────────────────────────────────────────────────────────
NEXT
