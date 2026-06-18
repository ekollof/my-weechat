#!/usr/bin/env bash
# Re-export current weechat config into this directory.
# Run this whenever you want to update the export with your latest config.
# Then commit/push to share with another machine.

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

WALLUST_SCRIPTS="${XDG_CONFIG_HOME}/wallust/scripts"

if [[ -n "${WEECHAT_HOME:-}" && "$WEECHAT_HOME" == "$LEGACY_HOME" ]]; then
    echo "!! Using legacy WeeChat home: $LEGACY_HOME" >&2
fi

# conf files: skip secrets and machine-specific files
for f in "$WEECHAT_CONF"/*.conf; do
    fname="$(basename "$f")"
    case "$fname" in
        sec.conf|xmpp.conf|irc.conf|relay.conf) continue ;;
    esac
    cp "$f" "$SCRIPT_DIR/weechat-conf/$fname"
done

# scrub slack token
sed -i 's/\(slack_api_token\s*=\s*\)"xox[^"]*"/\1"YOUR_SLACK_TOKEN_HERE"/' \
    "$SCRIPT_DIR/weechat-conf/plugins.conf"

# scrub xmpp account names and irc server references from weechat.conf
sed -i -E '/^xmpp\.(account|andrath)\./d' "$SCRIPT_DIR/weechat-conf/weechat.conf"
sed -i '/^irc\.server\./d' "$SCRIPT_DIR/weechat-conf/weechat.conf"

# python scripts
cp "$WEECHAT_DATA/python/autosort.py" \
   "$WEECHAT_DATA/python/cmd_help.py" \
   "$WEECHAT_DATA/python/go.py" \
   "$WEECHAT_DATA/python/grep.py" \
   "$WEECHAT_DATA/python/notify_send.py" \
   "$WEECHAT_DATA/python/urlgrab.py" \
   "$WEECHAT_DATA/python/wee_slack.py" \
   "$WEECHAT_DATA/python/wallust.py" \
   "$WEECHAT_DATA/python/weechat_debug_socket.py" \
   "$WEECHAT_DATA/python/sys_usage.py" \
   "$SCRIPT_DIR/weechat-python/"

# weechat-cmd wrapper
cp "$WEECHAT_DATA/python/weechat-cmd.sh" "$SCRIPT_DIR/"

# xmpp plugin
cp "$WEECHAT_DATA/plugins/xmpp.so" "$SCRIPT_DIR/weechat-plugins/"

printf '\e[32m=>\e[0m Export done.\n'
