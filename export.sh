#!/usr/bin/env bash
# Re-export current weechat config into this directory.
# Run this whenever you want to update the export with your latest config.
# Then commit/push to share with another machine.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEECHAT_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/weechat"
WEECHAT_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/weechat"
WALLUST_SCRIPTS="${XDG_CONFIG_HOME:-$HOME/.config}/wallust/scripts"

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
