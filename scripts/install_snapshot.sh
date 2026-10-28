#!/bin/bash
# Install the twice-daily snapshot job: snapshot.py under launchd.
# (Derived from install_check.sh and the launchd job the original setup used.)
# Run it from the folder that holds snapshot.py. Recommended location (outside iCloud):
#     cd ~/Library/Application\ Support/second-brain/scripts && bash install_snapshot.sh
#
# Schedule: 08:40 — just before the morning agents and the 08:45 check; 20:20 — just before the
# evening agents. So there is always a copy of TASKS.md from right before an agent touched it.
# No RunAtLoad: a snapshot at a random login time adds noise, and check_vault.py warns if the
# newest snapshot is older than 26 h, which covers a missed slot.
#
# Optional env: SECOND_BRAIN_VAULT (default ~/Vault), SECOND_BRAIN_SCHEDULED, PYTHON.

set -euo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$HOME/Library/Logs/second-brain"   # NOT in ~/Documents — that folder is synced by iCloud
mkdir -p "$LOGDIR"
LABEL="com.example.secondbrain.snapshot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
VAULT="${SECOND_BRAIN_VAULT:-$HOME/Vault}"
SCHEDULED="${SECOND_BRAIN_SCHEDULED:-$HOME/Documents/Claude/Scheduled}"
TGPULL_VENV="$HOME/Library/Application Support/second-brain/tg_pull/.venv/bin/python3"
PY="${PYTHON:-$(command -v python3)}"
# the tg_pull venv already has Full Disk Access — reuse it so the vault is readable
[ -z "${PYTHON:-}" ] && [ -x "$TGPULL_VENV" ] && PY="$TGPULL_VENV"

[ -f "$BASE/snapshot.py" ] || { echo "!! snapshot.py not found in $BASE"; exit 1; }

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
        <string>$BASE/snapshot.py</string>
    </array>
    <key>WorkingDirectory</key><string>$BASE</string>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>40</integer></dict>
        <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>20</integer></dict>
    </array>
    <key>RunAtLoad</key><false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key><string>$HOME</string>
        <key>LANG</key><string>en_US.UTF-8</string>
        <key>SECOND_BRAIN_VAULT</key><string>$VAULT</string>
        <key>SECOND_BRAIN_SCHEDULED</key><string>$SCHEDULED</string>
    </dict>
    <key>StandardOutPath</key><string>$LOGDIR/snapshot.log</string>
    <key>StandardErrorPath</key><string>$LOGDIR/snapshot.log</string>
    <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLIST_END

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
echo "==> Snapshots installed: $LABEL (08:40 and 20:20). Python: $PY"
echo "    Vault:              $VAULT"
echo "    Dry run right now:  $PY \"$BASE/snapshot.py\" --dry-run"
echo "    Snapshots:          ~/Library/Application Support/second-brain/snapshots/"
echo "    Log:                $LOGDIR/snapshot.log"
