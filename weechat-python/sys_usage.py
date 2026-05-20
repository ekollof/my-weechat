"""
sys_usage.py — cached CPU/mem/swap stats for the weechat powerline statusbar.

Polls psutil on a timer (default every 5s) and stores results in:
  plugins.var.python.sys_usage.cpu
  plugins.var.python.sys_usage.mem
  plugins.var.python.sys_usage.swap

The powerline segments read these vars instead of calling psutil inline,
eliminating the per-keypress blocking psutil calls that cause typing lag.

Commands:
  /sys_usage                     — force refresh now
  /sys_usage interval <seconds>  — change poll interval (default: 5)
"""

import weechat
import psutil

SCRIPT_NAME = "sys_usage"
SCRIPT_AUTHOR = "local"
SCRIPT_VERSION = "1.0"
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC = "Cached CPU/mem/swap stats for powerline statusbar (timer-based)"

_hook_timer = None


def _fmt(value):
    """Format a float percent to a right-aligned 4-char string."""
    if value >= 100.0:
        return " 100"
    return f"{value:.1f}".rjust(4)


def poll_cb(data, remaining_calls):
    weechat.config_set_plugin("cpu", _fmt(psutil.cpu_percent(interval=0.0)))
    weechat.config_set_plugin("mem", _fmt(psutil.virtual_memory().percent))
    weechat.config_set_plugin("swap", _fmt(psutil.swap_memory().percent))
    weechat.bar_item_update("powerline_items_sys_usage")
    return weechat.WEECHAT_RC_OK


def cmd_cb(data, buf, args):
    global _hook_timer
    args = args.strip()
    if args.startswith("interval "):
        try:
            secs = max(1, int(args.split()[1]))
            if _hook_timer:
                weechat.unhook(_hook_timer)
            _hook_timer = weechat.hook_timer(secs * 1000, 0, 0, "poll_cb", "")
            weechat.prnt("", f"{SCRIPT_NAME}: poll interval set to {secs}s")
        except (ValueError, IndexError):
            weechat.prnt("", "Usage: /sys_usage interval <seconds>")
    else:
        poll_cb("", "")
        weechat.prnt("", f"{SCRIPT_NAME}: refreshed")
    return weechat.WEECHAT_RC_OK


if weechat.register(
    SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE, SCRIPT_DESC, "", "UTF-8"
):
    poll_cb("", "")
    _hook_timer = weechat.hook_timer(5000, 0, 0, "poll_cb", "")
    weechat.hook_command(
        "sys_usage",
        "Force refresh or configure sys_usage poll interval",
        "[interval <seconds>]",
        "  interval: set poll interval in seconds (default: 5)\n"
        "  (no args): force an immediate refresh",
        "interval",
        "cmd_cb",
        "",
    )
