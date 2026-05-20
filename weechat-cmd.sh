#!/usr/bin/env bash
# weechat-cmd — send an eval expression or /command to the weechat debug socket
#
# Usage:
#   weechat-cmd '${weechat.color.chat_bg}'        # eval option, prints result
#   weechat-cmd '${info:version}'                 # eval info
#   weechat-cmd '/set weechat.color.chat_bg red'  # execute command (prints "ok")
#   echo '${buflist.format.name}' | weechat-cmd   # read from stdin
#
# Note: eval expressions must use ${...} syntax — bare names are returned as literals.
#
# Requires: socat

SOCK_PATH="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/weechat/weechat_debug.sock"

if [[ ! -S "$SOCK_PATH" ]]; then
    echo "error: socket not found at $SOCK_PATH" >&2
    echo "  Is weechat running with weechat_debug_socket.py loaded?" >&2
    exit 1
fi

if [[ $# -gt 0 ]]; then
    printf '%s\n' "$*" | socat - "UNIX-CONNECT:${SOCK_PATH}"
else
    # read from stdin (allows piping)
    socat - "UNIX-CONNECT:${SOCK_PATH}"
fi
