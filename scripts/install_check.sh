#!/bin/bash
# Install the Second Brain morning check: check_vault.py under launchd.
# Run it from the folder that holds check_vault.py. Recommended location (outside iCloud):
#     ~/Library/Application Support/second-brain/scripts/
#     cd ~/Library/Application\ Support/second-brain/scripts && bash install_check.sh
#
# 2026-09-15: originally there was only a fixed time (08:45) + RunAtLoad. That turned out not to be
# enough — if the Mac was not awake at exactly that moment (asleep / off / lid closed), launchd does
# not always reliably "catch up" the missed slot on the next wake, and the check could go weeks
# without running even though the Mac was in active use at other times of day. A StartInterval was
# added — the script now also tries every 3 hours, not only at 08:45 and at login. The point of 08:45
# is kept (finish before the 09:00 briefing if the Mac is already awake), but the system no longer
# depends on one specific moment.
#
# Optional env: SECOND_BRAIN_VAULT (default ~/Vault), PYTHON (interpreter to use).

set -euo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$HOME/Library/Logs/second-brain"   # 2026-09-19: NOT in ~/Documents — that folder is synced by iCloud
mkdir -p "$LOGDIR"
LABEL="com.example.secondbrain.checkvault"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
VAULT="${SECOND_BRAIN_VAULT:-$HOME/Vault}"
TGPULL_VENV="$HOME/Library/Application Support/second-brain/tg_pull/.venv/bin/python3"
PY="${PYTHON:-$(command -v python3)}"
# the tg_pull venv already has Full Disk Access — reuse it so the vault is readable
[ -z "${PYTHON:-}" ] && [ -x "$TGPULL_VENV" ] && PY="$TGPULL_VENV"

[ -f "$BASE/check_vault.py" ] || { echo "!! check_vault.py not found in $BASE"; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$BASE/check_vault.py</string>
    </array>
    <key>WorkingDirectory</key><string>$BASE</string>
    <!-- 08:45 — before the morning briefing (09:00), if the Mac is already awake -->
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>45</integer></dict>
    <!-- and at every login / boot -->
    <key>RunAtLoad</key><true/>
    <!-- and simply every 3 hours while the Mac is on and awake — a safety net in case both
         08:45 and the login moment are missed (2026-09-15: this was the real cause of an 18-day outage) -->
    <key>StartInterval</key><integer>10800</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key><string>$HOME</string>
        <key>LANG</key><string>en_US.UTF-8</string>
        <key>SECOND_BRAIN_VAULT</key><string>$VAULT</string>
    </dict>
    <key>StandardOutPath</key><string>$LOGDIR/checkvault.log</string>
    <key>StandardErrorPath</key><string>$LOGDIR/checkvault.log</string>
    <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLIST_END

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
echo "==> Check installed: $LABEL (08:45 + at login + every 3 hours). Python: $PY"
echo "    Vault:                 $VAULT"
echo "    Dry run right now:     $PY \"$BASE/check_vault.py\" --dry-run"
echo "    Log:                   $LOGDIR/checkvault.log"
echo "    IMPORTANT: if PY is not the tg_pull venv and the vault is in a protected folder, grant it Full Disk Access"
echo "    (System Settings -> Privacy & Security), otherwise the vault cannot be read."
