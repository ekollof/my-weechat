#!/usr/bin/env bash
# Sync live WeeChat config into this repo (live → weechat-export).
#
# Run after changing settings in WeeChat (/set, /fset, script edits in
# ~/.config/weechat and ~/.local/share/weechat). Then commit/push.
#
# Deliberately NOT copied (stay on the machine only):
#   sec.conf, irc.conf, xmpp.conf, relay.conf
#
# Scrubbed after copy (safe to commit):
#   Slack token → placeholder
#   xmpp.account.* / irc.server.* lines in weechat.conf
#   spell plugin forced off (!spell autoload, spell.check.enabled = off)
#
# Deploy repo → live with: ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
LEGACY_HOME="$HOME/.weechat"

# WeeChat uses XDG dirs only when WEECHAT_HOME is unset and ~/.weechat does not
# exist; otherwise it uses the legacy home. Match that logic.
if [[ -n "${WEECHAT_HOME:-}" ]]; then
    WEECHAT_HOME="$WEECHAT_HOME"
    WEECHAT_CONF="$WEECHAT_HOME"
    WEECHAT_DATA="$WEECHAT_HOME"
elif [[ -d "$LEGACY_HOME" ]]; then
    WEECHAT_HOME="$LEGACY_HOME"
    WEECHAT_CONF="$LEGACY_HOME"
    WEECHAT_DATA="$LEGACY_HOME"
else
    WEECHAT_CONF="$XDG_CONFIG_HOME/weechat"
    WEECHAT_DATA="$XDG_DATA_HOME/weechat"
fi

if [[ -n "${WEECHAT_HOME:-}" && "$WEECHAT_HOME" == "$LEGACY_HOME" ]]; then
    echo "!! Using legacy WeeChat home: $LEGACY_HOME" >&2
fi

SKIP_CONF=(sec.conf xmpp.conf irc.conf relay.conf)
PYTHON_SCRIPTS=(
    autosort.py cmd_help.py go.py grep.py notify_send.py
    urlgrab.py slack.py wallust.py weechat_debug_socket.py sys_usage.py
)

# Remove secret-bearing confs that must never be committed.
for f in "${SKIP_CONF[@]}"; do
    rm -f "$SCRIPT_DIR/weechat-conf/$f"
done

# Sync *.conf from live, skipping machine-local files.
mkdir -p "$SCRIPT_DIR/weechat-conf"
live_conf=()
for f in "$WEECHAT_CONF"/*.conf; do
    [[ -f "$f" ]] || continue
    fname="$(basename "$f")"
    for skip in "${SKIP_CONF[@]}"; do
        [[ "$fname" == "$skip" ]] && continue 2
    done
    cp "$f" "$SCRIPT_DIR/weechat-conf/$fname"
    live_conf+=("$fname")
done

# Drop conf files removed from live.
for f in "$SCRIPT_DIR/weechat-conf"/*.conf; do
    [[ -f "$f" ]] || continue
    fname="$(basename "$f")"
    found=0
    for live in "${live_conf[@]}"; do
        [[ "$fname" == "$live" ]] && found=1 && break
    done
    if [[ "$found" -eq 0 ]]; then
        rm -f "$f"
        echo "!! Removed stale export conf: $fname" >&2
    fi
done

# Scrub secrets and machine-specific settings from the synced copy.
sed -i 's/\(slack_api_token\s*=\s*\)"xox[^"]*"/\1"YOUR_SLACK_TOKEN_HERE"/' \
    "$SCRIPT_DIR/weechat-conf/plugins.conf"
sed -i -E '/^xmpp\.(account|[^.]+)\./d' "$SCRIPT_DIR/weechat-conf/weechat.conf"
sed -i '/^irc\.server\./d' "$SCRIPT_DIR/weechat-conf/weechat.conf"

# spell.so causes typing lag — keep disabled in the export.
if [[ -f "$SCRIPT_DIR/weechat-conf/spell.conf" ]]; then
    sed -i 's/^enabled = on/enabled = off/' "$SCRIPT_DIR/weechat-conf/spell.conf"
fi
if [[ -f "$SCRIPT_DIR/weechat-conf/weechat.conf" ]] && \
   ! grep -q '!spell' "$SCRIPT_DIR/weechat-conf/weechat.conf"; then
    sed -i 's/autoload = "\([^"]*\)"/autoload = "\1,!spell"/' \
        "$SCRIPT_DIR/weechat-conf/weechat.conf"
fi

# Sync python scripts from live.
mkdir -p "$SCRIPT_DIR/weechat-python"
for script in "${PYTHON_SCRIPTS[@]}"; do
    src="$WEECHAT_DATA/python/$script"
    if [[ -f "$src" ]]; then
        cp "$src" "$SCRIPT_DIR/weechat-python/$script"
    else
        echo "!! Missing live script (skipped): $script" >&2
    fi
done

# Drop python scripts removed from the export list / live.
for f in "$SCRIPT_DIR/weechat-python"/*.py; do
    [[ -f "$f" ]] || continue
    fname="$(basename "$f")"
    found=0
    for script in "${PYTHON_SCRIPTS[@]}"; do
        [[ "$fname" == "$script" ]] && found=1 && break
    done
    if [[ "$found" -eq 0 ]]; then
        rm -f "$f"
        echo "!! Removed stale export script: $fname" >&2
    fi
done

# weechat-cmd wrapper — prefer live copy, fall back to repo / ~/.local/bin.
for src in \
    "$WEECHAT_DATA/python/weechat-cmd.sh" \
    "$SCRIPT_DIR/weechat-cmd.sh" \
    "$HOME/.local/bin/weechat-cmd"; do
    if [[ -f "$src" ]]; then
        cp "$src" "$SCRIPT_DIR/weechat-cmd.sh"
        break
    fi
done

# xmpp.so — optional; many machines rebuild locally via xepher.
if [[ -f "$WEECHAT_DATA/plugins/xmpp.so" ]]; then
    mkdir -p "$SCRIPT_DIR/weechat-plugins"
    cp "$WEECHAT_DATA/plugins/xmpp.so" "$SCRIPT_DIR/weechat-plugins/"
fi

python3 "$SCRIPT_DIR/install.py" --audit-export

printf '\e[32m=>\e[0m Export done. Review with git diff, then commit.\n'