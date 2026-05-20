"""
wallust.py — Apply wallust/pywal palette colors to weechat.

Watches ~/.cache/wal/colors.json for changes (mtime poll every 3s) and
applies all color settings directly via the weechat config API — no /set
commands, no "Option unchanged" noise.

Also applies colors immediately on load (handles startup).

Usage:
  /wallust          — force re-apply colors now
  /wallust reload   — same as above
"""

import json
import os
import re
import weechat

SCRIPT_NAME = "wallust"
SCRIPT_AUTHOR = "local"
SCRIPT_VERSION = "2.1"
SCRIPT_LICENSE = "WTFPL"
SCRIPT_DESC = "Live wallust/pywal palette colors — watches colors.json for changes"

COLORS_JSON = os.path.expanduser("~/.cache/wal/colors.json")
BUFLIST_CONF = os.path.expanduser("~/.config/weechat/buflist.conf")
PLUGINS_CONF = os.path.expanduser("~/.config/weechat/plugins.conf")
POLL_MS = 1000  # mtime check interval in milliseconds

_last_mtime = 0.0


# ---------------------------------------------------------------------------
# Config API helpers
# ---------------------------------------------------------------------------


def cfg_set(option_name, value):
    """Set a weechat config option silently via the API (no chat output)."""
    ptr = weechat.config_get(option_name)
    if ptr:
        weechat.config_option_set(ptr, str(value), 1)


# ---------------------------------------------------------------------------
# Color math helpers
# ---------------------------------------------------------------------------


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def xterm256_rgb(idx):
    if idx < 16:
        system = [
            (0, 0, 0),
            (128, 0, 0),
            (0, 128, 0),
            (128, 128, 0),
            (0, 0, 128),
            (128, 0, 128),
            (0, 128, 128),
            (192, 192, 192),
            (128, 128, 128),
            (255, 0, 0),
            (0, 255, 0),
            (255, 255, 0),
            (0, 0, 255),
            (255, 0, 255),
            (0, 255, 255),
            (255, 255, 255),
        ]
        return system[idx]
    if idx >= 232:
        v = 8 + 10 * (idx - 232)
        return (v, v, v)
    idx -= 16
    b = idx % 6
    g = (idx // 6) % 6
    r = idx // 36

    def cv(i):
        return 0 if i == 0 else 55 + 40 * i

    return (cv(r), cv(g), cv(b))


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def nearest_xterm256(hex_color, start=16):
    """Return nearest xterm-256 index (>= start) for a hex color."""
    rgb = hex_to_rgb(hex_color)
    return min(range(start, 256), key=lambda i: dist(rgb, xterm256_rgb(i)))


def relative_luminance(hex_color):
    """Return the relative luminance of a hex color (0-255 scale)."""
    r, g, b = hex_to_rgb(hex_color)
    return (r * 299 + g * 587 + b * 114) / 1000


def _readable_palette_colors(r, min_contrast=40):
    """Return palette colors readable against the background, sorted by contrast descending.

    Returns list of (palette_index, xterm_idx) tuples with distinct xterm indices.
    """
    bg_lum = relative_luminance(r["bg_hex"])
    candidates = []
    seen = set()
    for i in range(16):
        hex_c = r[f"c{i}_hex"]
        lum = relative_luminance(hex_c)
        contrast = abs(lum - bg_lum)
        if contrast < min_contrast:
            continue
        idx = r[f"c{i}"]
        if idx in seen:
            continue
        seen.add(idx)
        candidates.append((contrast, i, idx))
    candidates.sort(reverse=True)
    return [(i, idx) for _contrast, i, idx in candidates]


def _resolve_color(r, preferred, readable_list, used):
    """Resolve a preferred palette slot to a readable xterm index.

    If the preferred slot is readable and not already used, return it.
    Otherwise pick the first unused readable color.
    """
    hex_c = r[f"c{preferred}_hex"]
    lum = relative_luminance(hex_c)
    bg_lum = relative_luminance(r["bg_hex"])
    idx = r[f"c{preferred}"]
    if abs(lum - bg_lum) >= 40 and idx not in used:
        used.add(idx)
        return idx
    for i, idx in readable_list:
        if idx not in used:
            used.add(idx)
            return idx
    # ultimate fallback — return whatever the preferred slot mapped to
    return r[f"c{preferred}"]


# ---------------------------------------------------------------------------
# Palette role derivation
# ---------------------------------------------------------------------------


def derive_roles(data):
    """
    Convert colors.json to a dict of xterm-256 ints and hex strings.

    Palette mapping:
      color0  = dark bg variant      color8  = mid grey / dimmed
      color1  = accent 1 (quit/err)  color9  = bright accent 1 (highlight)
      color2  = accent 2 (join/ok)   color10 = bright accent 2 (private/input)
      color3  = accent 3 (server)    color11 = bright accent 3 (error prefix)
      color4  = accent 4 (marker)    color12 = bright accent 4
      color5  = accent 5 (network)   color13 = bright accent 5 (insecure)
      color6  = accent 6 (nicks)     color14 = bright accent 6
      color7  = fg variant           color15 = bright fg (self/status)
    """
    colors = data["colors"]
    special = data.get("special", {})
    bg_hex = special.get("background", "#1a1a1a")
    fg_hex = special.get("foreground", colors.get("color15", "#ffffff"))
    hex_list = [colors[f"color{i}"] for i in range(16)]

    c = [nearest_xterm256(h) for h in hex_list]
    bg = nearest_xterm256(bg_hex)
    fg = nearest_xterm256(fg_hex)

    accent_bg = c[4]

    # very_dark_bg: nudge one step lighter than terminal bg in grey ramp
    vd_idx = nearest_xterm256(bg_hex, start=232)
    vd_idx = min(vd_idx + 1, 243)
    very_dark_bg = vd_idx

    # dark_bg: two steps lighter (alternate powerline segments)
    dark_bg = min(vd_idx + 2, 245)

    separator = c[8]

    return {
        **{f"c{i}": c[i] for i in range(16)},
        **{f"c{i}_hex": hex_list[i] for i in range(16)},
        "bg": bg,
        "bg_hex": bg_hex,
        "fg": fg,
        "accent_bg": accent_bg,
        "very_dark_bg": very_dark_bg,
        "dark_bg": dark_bg,
        "separator": separator,
        "accent_bg_hex": hex_list[4],
    }


# ---------------------------------------------------------------------------
# Apply sections — all via cfg_set(), no /set commands
# ---------------------------------------------------------------------------


def apply_chat_colors(r):
    bg_lum = relative_luminance(r["bg_hex"])
    seen = set()
    candidates = []
    # prefer the traditional accent / bright slots
    for i in [1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 7, 8, 0]:
        hex_c = r[f"c{i}_hex"]
        lum = relative_luminance(hex_c)
        if abs(lum - bg_lum) < 35:
            continue  # too close to background → unreadable
        idx = r[f"c{i}"]
        if idx in seen:
            continue
        seen.add(idx)
        candidates.append(str(idx))
        if len(candidates) >= 12:
            break
    nick_colors = ",".join(candidates)
    opts = {
        "weechat.color.chat": "default",
        "weechat.color.chat_bg": "default",
        "weechat.color.chat_buffer": r["c15"],
        "weechat.color.chat_channel": r["c15"],
        "weechat.color.chat_day_change": r["c6"],
        "weechat.color.chat_delimiters": r["c8"],
        "weechat.color.chat_highlight": r["c9"],
        "weechat.color.chat_highlight_bg": "default",
        "weechat.color.chat_host": r["c8"],
        "weechat.color.chat_inactive_buffer": "default",
        "weechat.color.chat_inactive_window": r["c8"],
        "weechat.color.chat_nick": r["c6"],
        "weechat.color.chat_nick_offline": r["c8"],
        "weechat.color.chat_nick_offline_highlight": "default",
        "weechat.color.chat_nick_offline_highlight_bg": "default",
        "weechat.color.chat_nick_other": r["c6"],
        "weechat.color.chat_nick_prefix": r["c2"],
        "weechat.color.chat_nick_self": r["c15"],
        "weechat.color.chat_nick_suffix": r["c2"],
        "weechat.color.chat_prefix_action": r["c15"],
        "weechat.color.chat_prefix_buffer": r["c3"],
        "weechat.color.chat_prefix_buffer_inactive_buffer": "default",
        "weechat.color.chat_prefix_error": r["c11"],
        "weechat.color.chat_prefix_join": r["c10"],
        "weechat.color.chat_prefix_more": r["c8"],
        "weechat.color.chat_prefix_network": r["c5"],
        "weechat.color.chat_prefix_quit": r["c1"],
        "weechat.color.chat_prefix_suffix": r["c8"],
        "weechat.color.chat_read_marker": r["very_dark_bg"],
        "weechat.color.chat_read_marker_bg": "default",
        "weechat.color.chat_server": r["c3"],
        "weechat.color.chat_status_disabled": r["c1"],
        "weechat.color.chat_status_enabled": r["c2"],
        "weechat.color.chat_tags": r["c9"],
        "weechat.color.chat_text_found": r["c11"],
        "weechat.color.chat_text_found_bg": r["c5"],
        "weechat.color.chat_time": r["c8"],
        "weechat.color.chat_time_delimiters": r["c3"],
        "weechat.color.chat_value": r["c6"],
        "weechat.color.chat_value_null": r["c4"],
        "weechat.color.emphasized": r["c11"],
        "weechat.color.emphasized_bg": r["c5"],
        "weechat.color.input_actions": r["c10"],
        "weechat.color.input_text_not_found": r["c1"],
        "weechat.color.item_away": r["c11"],
        "weechat.color.nicklist_away": r["c8"],
        "weechat.color.nicklist_group": r["c2"],
        "weechat.color.separator": r["c8"],
        "weechat.color.status_count_highlight": r["c5"],
        "weechat.color.status_count_msg": r["c3"],
        "weechat.color.status_count_other": "default",
        "weechat.color.status_count_private": r["c2"],
        "weechat.color.status_data_highlight": r["c13"],
        "weechat.color.status_data_msg": r["c7"],
        "weechat.color.status_data_other": "default",
        "weechat.color.status_data_private": r["c10"],
        "weechat.color.status_filter": r["c2"],
        "weechat.color.status_modes": "default",
        "weechat.color.status_more": r["c15"],
        "weechat.color.status_mouse": r["c10"],
        "weechat.color.status_name": r["c10"],
        "weechat.color.status_name_insecure": r["c13"],
        "weechat.color.status_name_tls": r["c10"],
        "weechat.color.status_nicklist_count": r["c15"],
        "weechat.color.status_number": r["c15"],
        "weechat.color.status_time": r["c15"],
        "weechat.color.chat_nick_colors": nick_colors,
        "weechat.color.bar_more": r["c7"],
    }
    for opt, val in opts.items():
        cfg_set(opt, val)


def apply_bar_colors(r):
    ab, fg, c4 = r["accent_bg"], r["fg"], r["c4"]
    for bar in ("titlesep", "titlenosep"):
        cfg_set(f"weechat.bar.{bar}.color_bg", ab)
        cfg_set(f"weechat.bar.{bar}.color_bg_inactive", ab)
        cfg_set(f"weechat.bar.{bar}.color_fg", fg)
        cfg_set(f"weechat.bar.{bar}.color_delim", fg)
    cfg_set("weechat.bar.nicklist.color_fg", fg)
    cfg_set("weechat.bar.nicklist.color_delim", c4)


def apply_powerline_colors(r):
    ab, db, vd, sp = r["accent_bg"], r["dark_bg"], r["very_dark_bg"], r["separator"]

    segment_bg = {
        "buffer_plugin_server": ab,
        "mem": ab,
        "buffer_info": db,
        "cpu": db,
        "time": vd,
        "swap": vd,
        "date": vd,
        "nick": ab,
        "chan": ab,
        "serv": ab,
        "symbol": "white",
    }

    for group in ("powerline_items", "chanmon", "highmon"):
        prefix = f"plugins.var.group_tools.{group}.segment"
        for seg, bg in segment_bg.items():
            cfg_set(f"{prefix}.{seg}.bg", bg)
            cfg_set(f"{prefix}.{seg}.fg", "white")
            cfg_set(f"{prefix}.{seg}.sep", sp)


def apply_buflist_hotlist(r):
    readable = _readable_palette_colors(r)
    used = set()
    # semantic mapping: highlight (red-ish accent), message (bright accent),
    # private (bright), low (dim)
    highlight = _resolve_color(r, 9, readable, used)
    message = _resolve_color(r, 12, readable, used)
    private = _resolve_color(r, 10, readable, used)
    low = _resolve_color(r, 8, readable, used)
    cfg_set("buflist.format.hotlist_highlight", f"${{color:*{highlight}}}")
    cfg_set("buflist.format.hotlist_message", f"${{color:{message}}}")
    cfg_set("buflist.format.hotlist_private", f"${{color:{private}}}")
    cfg_set("buflist.format.hotlist_low", f"${{color:{low}}}")
    cfg_set("buflist.format.hotlist_none", "${color:default}")


def _read_conf_key(filepath, section, key):
    """Read a single key from an ini-style weechat conf file."""
    try:
        with open(filepath) as f:
            lines = f.readlines()
    except OSError:
        return None
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == f"[{section}]":
            in_section = True
            continue
        if in_section and stripped.startswith("["):
            break
        if not in_section or not stripped.startswith(key):
            continue
        m = re.match(rf'^{re.escape(key)}\s*=\s*"(.*)"$', stripped)
        if m:
            return m.group(1)
        m2 = re.match(rf"^{re.escape(key)}\s*=\s*(.+)$", stripped)
        if m2:
            return m2.group(1).strip()
    return None


def apply_buflist_format(r):
    ab_int = r["accent_bg"]
    ab_hex = r["accent_bg_hex"]
    for fmt_key in ("buffer", "indent", "nick_prefix"):
        val = _read_conf_key(BUFLIST_CONF, "format", fmt_key)
        if val is None:
            continue
        new_val = re.sub(r"\$\{color:,#[0-9A-Fa-f]{6}\}", f"${{color:,{ab_int}}}", val)
        new_val = re.sub(r"\$\{color:,\d+\}", f"${{color:,{ab_int}}}", new_val)
        new_val = re.sub(
            r"\$\{color:#[0-9A-Fa-f]{6}\}", f"${{color:{ab_hex}}}", new_val
        )
        new_val = re.sub(r"\$\{color:(\d+)\}", f"${{color:{ab_hex}}}", new_val)
        if new_val != val:
            cfg_set(f"buflist.format.{fmt_key}", new_val)


def apply_buflist_name_colors(r):
    """Set buflist.format.name with palette-derived xterm-256 color indices per buffer type."""
    readable = _readable_palette_colors(r)
    used = set()
    # semantic mapping: server (bright fg), private (bright accent), feed (accent)
    c_server = _resolve_color(r, 15, readable, used)
    c_private = _resolve_color(r, 14, readable, used)
    c_feed = _resolve_color(r, 6, readable, used)

    type_color = (
        f"${{if:${{type}}==server?${{color:*{c_server}}}"
        f":${{if:${{type}}==feed?${{color:{c_feed}}}"
        f":${{if:${{type}}==private?${{color:{c_private}}}"
        f":${{color:default}}}}}}}}"
    )
    color_expr = f"${{if:${{hotlist}}!=?${{eval:${{color_hotlist}}}}:{type_color}}}"
    new_tail = color_expr + "${my_name}}"

    val = _read_conf_key(BUFLIST_CONF, "format", "name")
    if val is None:
        return

    # The format.name structure is:
    #   ${if:<enabled_check>?<preamble><color_prefix>${my_name}}
    # where <preamble> ends with the last ${define:my_name,...}} block.
    # Split on the known preamble boundary: the last "}}${if:" sequence,
    # which separates the last define block from the color prefix.
    split_marker = "}}${if:"
    idx = val.rfind(split_marker)
    if idx == -1:
        return

    preamble = val[: idx + 2]  # up to and including "}}"
    new_val = preamble + new_tail
    if new_val != val:
        cfg_set("buflist.format.name", new_val)


def apply_plugins_var_content(r):
    ab = r["accent_bg"]
    sp = r["separator"]

    filter_key = "group_tools.buflist.element.filter.format"
    val = _read_conf_key(PLUGINS_CONF, "var", filter_key)
    if val is not None:
        new_val = re.sub(r"\$\{color:(\d+)\}", f"${{color:{ab}}}", val)
        if new_val != val:
            cfg_set(f"plugins.var.{filter_key}", new_val)

    content_keys = [
        "group_tools.powerline_items.segment.buffer_info.content",
        "group_tools.powerline_items.segment.buffer_plugin_server.content",
        "group_tools.powerline_items.segment.cpu.content",
        "group_tools.powerline_items.segment.mem.content",
        "group_tools.powerline_items.segment.swap.content",
    ]
    for key in content_keys:
        val = _read_conf_key(PLUGINS_CONF, "var", key)
        if val is None:
            continue
        new_val = re.sub(r"\$\{color:(\d+)\}", f"${{color:{sp}}}", val)
        if new_val != val:
            cfg_set(f"plugins.var.{key}", new_val)


# ---------------------------------------------------------------------------
# Apply colors
# ---------------------------------------------------------------------------


def apply_colors(verbose=False, reload_slack=True):
    global _last_mtime

    if not os.path.exists(COLORS_JSON):
        weechat.prnt("", f"{SCRIPT_NAME}: {COLORS_JSON} not found — run wallust first")
        return

    try:
        with open(COLORS_JSON) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        weechat.prnt("", f"{SCRIPT_NAME}: error reading colors.json: {e}")
        return

    _last_mtime = os.path.getmtime(COLORS_JSON)

    r = derive_roles(data)

    apply_chat_colors(r)
    apply_bar_colors(r)
    apply_powerline_colors(r)
    apply_buflist_hotlist(r)
    apply_buflist_format(r)
    apply_buflist_name_colors(r)
    apply_plugins_var_content(r)

    buf = weechat.buffer_search_main()

    # Toggle nicklist nick colors to force a refresh
    weechat.command(buf, "/set irc.look.color_nicks_in_nicklist off")
    weechat.command(buf, "/set irc.look.color_nicks_in_nicklist on")

    weechat.command(buf, "/save")

    # /python reload wee_slack restarts the Python interpreter — never safe to run
    # during our own load sequence. Only issue it on explicit/timer-triggered calls.
    if reload_slack:
        weechat.command(buf, "/python reload wee_slack")

    if verbose:
        weechat.prnt("", f"{SCRIPT_NAME}: colors applied from {COLORS_JSON}")


# ---------------------------------------------------------------------------
# Timer callback — poll colors.json mtime
# ---------------------------------------------------------------------------


def timer_cb(data, remaining_calls):
    global _last_mtime
    try:
        mtime = os.path.getmtime(COLORS_JSON)
    except OSError:
        return weechat.WEECHAT_RC_OK
    if mtime != _last_mtime:
        apply_colors(verbose=True, reload_slack=True)
    return weechat.WEECHAT_RC_OK


# ---------------------------------------------------------------------------
# /wallust command
# ---------------------------------------------------------------------------


def wallust_cmd_cb(data, buf, args):
    apply_colors(verbose=True, reload_slack=True)
    return weechat.WEECHAT_RC_OK


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


weechat.register(
    SCRIPT_NAME,
    SCRIPT_AUTHOR,
    SCRIPT_VERSION,
    SCRIPT_LICENSE,
    SCRIPT_DESC,
    "",
    "",
)

# Apply immediately on load (handles startup + manual /script load)
# reload_slack=False: /python reload wee_slack during our own load would
# restart the Python interpreter and crash the load sequence.
apply_colors(verbose=False, reload_slack=False)

# Poll every POLL_MS milliseconds; 0 = repeat forever
weechat.hook_timer(POLL_MS, 0, 0, "timer_cb", "")

# /wallust command for manual force-refresh
weechat.hook_command(
    "wallust",
    "Re-apply wallust palette colors from colors.json",
    "[reload]",
    "reload: re-apply colors (default action)",
    "",
    "wallust_cmd_cb",
    "",
)
