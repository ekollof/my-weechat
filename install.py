#!/usr/bin/env python3
"""
weechat config installer
Installs weechat config, python scripts, and xmpp plugin.

Idempotent — safe to run multiple times:
  - Appearance/UI conf files are always updated (colors, buflist, triggers, keybinds)
  - plugins.conf: group_tools/script vars are merged in; machine-specific keys
    (slack token, etc.) are left untouched
  - Server/account conf files (irc.conf, xmpp.conf) are only installed if they
    don't already exist — never overwritten, to preserve secrets and server config
  - Python scripts are updated if the source is newer than the destination
  - xmpp.so is only installed if not already present (preserve locally rebuilt binaries)
  - Autoload symlinks are created if missing, never replaced
"""

import os
import re
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
WEECHAT_CONF = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "weechat"
)
WEECHAT_DATA = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "weechat"
)
SRC_CONF = SCRIPT_DIR / "weechat-conf"
SRC_PYTHON = SCRIPT_DIR / "weechat-python"
SRC_SO = SCRIPT_DIR / "weechat-plugins" / "xmpp.so"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def info(msg):
    print(f"{GREEN}=>{RESET} {msg}")


def warn(msg):
    print(f"{YELLOW}!!{RESET} {msg}")


def error(msg):
    print(f"{RED}ERROR:{RESET} {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def copy_if_newer(src: Path, dst: Path) -> bool:
    """Copy src to dst if src is newer or dst doesn't exist. Returns True if copied."""
    if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


def copy_if_missing(src: Path, dst: Path) -> bool:
    """Copy src to dst only if dst doesn't exist. Returns True if copied."""
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


def symlink_if_missing(target: Path, link: Path) -> bool:
    """Create a relative symlink at link -> target if link doesn't exist."""
    if not link.exists() and not link.is_symlink():
        rel = os.path.relpath(target, link.parent)
        link.symlink_to(rel)
        return True
    return False


# ---------------------------------------------------------------------------
# plugins.conf merge
# ---------------------------------------------------------------------------


def parse_var_section(path: Path):
    """Return list of (key, raw_value_string) from the [var] section."""
    pairs = []
    in_var = False
    with open(path) as f:
        for line in f:
            s = line.rstrip("\n")
            if s == "[var]":
                in_var = True
                continue
            if in_var and s.startswith("["):
                break
            if not in_var or not s.strip() or s.strip().startswith("#"):
                continue
            m = re.match(r"^(\S+)\s*=\s*(.*)$", s)
            if m:
                pairs.append((m.group(1), m.group(2)))
    return pairs


def merge_plugins_conf(src: Path, dst: Path):
    """
    Merge [var] keys from src into dst.
    Keys present in src overwrite dst; keys only in dst are left alone.
    The slack token placeholder in src is never written to dst.
    """
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        info("  plugins.conf: installed")
        return

    src_vars = parse_var_section(src)
    with open(dst) as f:
        dst_lines = f.readlines()

    updated = 0
    for key, value in src_vars:
        # Never overwrite a real slack token with the export placeholder
        if "slack_api_token" in key and "YOUR_SLACK_TOKEN" in value:
            continue

        found = False
        for i, line in enumerate(dst_lines):
            m = re.match(r"^(\S+)\s*=\s*", line)
            if m and m.group(1) == key:
                dst_lines[i] = f"{key} = {value}\n"
                found = True
                updated += 1
                break

        if not found:
            # Insert after [var] header
            for i, line in enumerate(dst_lines):
                if line.rstrip("\n") == "[var]":
                    dst_lines.insert(i + 1, f"{key} = {value}\n")
                    updated += 1
                    break

    with open(dst, "w") as f:
        f.writelines(dst_lines)

    info(f"  plugins.conf: merged {updated} keys")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # Preflight
    if not shutil.which("weechat"):
        error("weechat not found in PATH")
    if not SRC_CONF.is_dir():
        error(f"Source conf dir not found: {SRC_CONF}")
    if not SRC_PYTHON.is_dir():
        error(f"Source python dir not found: {SRC_PYTHON}")

    WEECHAT_CONF.mkdir(parents=True, exist_ok=True)
    (WEECHAT_DATA / "python" / "autoload").mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Conf files — always update (UI/appearance only, no secrets)
    # -------------------------------------------------------------------------
    ALWAYS_UPDATE = [
        "weechat.conf",
        "buflist.conf",
        "trigger.conf",
        "alias.conf",
        "autosort.conf",
        "charset.conf",
        "logger.conf",
        "spell.conf",
        "typing.conf",
        "fifo.conf",
        "fset.conf",
        "script.conf",
        "urlgrab.conf",
    ]

    info("Installing UI/appearance config files...")
    for fname in ALWAYS_UPDATE:
        src = SRC_CONF / fname
        dst = WEECHAT_CONF / fname
        if not src.exists():
            continue
        if copy_if_newer(src, dst):
            info(f"  updated: {fname}")

    # -------------------------------------------------------------------------
    # Conf files — install once (server addresses, account details)
    # -------------------------------------------------------------------------
    INSTALL_ONCE = ["irc.conf", "xmpp.conf", "perl.conf", "python.conf"]

    info("Installing server/account config files (skipped if already present)...")
    for fname in INSTALL_ONCE:
        src = SRC_CONF / fname
        dst = WEECHAT_CONF / fname
        if not src.exists():
            continue
        if copy_if_missing(src, dst):
            info(f"  installed: {fname}")
        else:
            info(f"  skipped (already exists): {fname}")

    # -------------------------------------------------------------------------
    # plugins.conf — merge
    # -------------------------------------------------------------------------
    info("Merging plugins.conf...")
    merge_plugins_conf(SRC_CONF / "plugins.conf", WEECHAT_CONF / "plugins.conf")

    # -------------------------------------------------------------------------
    # Python scripts — update if newer
    # -------------------------------------------------------------------------
    info("Installing python scripts...")
    updated = 0
    for src in sorted(SRC_PYTHON.glob("*.py")):
        dst = WEECHAT_DATA / "python" / src.name
        if copy_if_newer(src, dst):
            info(f"  updated: {src.name}")
            updated += 1
    if updated == 0:
        info("  all scripts up to date")

    # Autoload symlinks — create if missing
    for script in (
        "autosort",
        "urlgrab",
        "wee_slack",
        "wallust",
        "notify_send",
        "sys_usage",
        "go",
    ):
        src = WEECHAT_DATA / "python" / f"{script}.py"
        link = WEECHAT_DATA / "python" / "autoload" / f"{script}.py"
        if src.exists() and symlink_if_missing(src, link):
            info(f"  autoload symlink created: {script}.py")

    # -------------------------------------------------------------------------
    # weechat-cmd wrapper
    # -------------------------------------------------------------------------
    cmd_src = SCRIPT_DIR / "weechat-cmd.sh"
    local_bin = Path.home() / ".local" / "bin"
    if local_bin.is_dir():
        dst = local_bin / "weechat-cmd"
        if copy_if_newer(cmd_src, dst):
            dst.chmod(dst.stat().st_mode | 0o111)
            info("Installed weechat-cmd to ~/.local/bin/weechat-cmd")
    else:
        dst = WEECHAT_DATA / "python" / "weechat-cmd.sh"
        if copy_if_newer(cmd_src, dst):
            dst.chmod(dst.stat().st_mode | 0o111)
            warn(
                f"~/.local/bin not found — installed weechat-cmd to {dst} (add to PATH manually)"
            )

    # -------------------------------------------------------------------------
    # xmpp.so — install only if not already present
    # -------------------------------------------------------------------------
    dst_so = WEECHAT_DATA / "plugins" / "xmpp.so"
    if SRC_SO.exists():
        (WEECHAT_DATA / "plugins").mkdir(parents=True, exist_ok=True)
        if copy_if_missing(SRC_SO, dst_so):
            info("Installed xmpp.so")
        else:
            info("xmpp.so already present — skipped (rebuild locally if needed)")
    else:
        warn("xmpp.so not found in export — skipping")
        warn("Build from: https://github.com/ekollof/xepher")

    # -------------------------------------------------------------------------
    # Done
    # -------------------------------------------------------------------------
    print(f"""
{GREEN}Installation complete.{RESET}

First-time setup (in weechat):
  1. /secure set xmpp_yourname <your-xmpp-password>
  2. /secure set znc_libera <your-znc-password>
  3. /slack register   (or paste your Slack token when prompted)
  4. Edit {WEECHAT_CONF}/irc.conf — update server addresses if not using the same ZNC
  5. Edit {WEECHAT_CONF}/xmpp.conf — set your JID, nickname, etc.
  6. Run: wallust run <wallpaper>   (wallust.py then watches colors.json automatically)

Debug socket (optional):
  /script load weechat_debug_socket.py
  weechat-cmd '${{info:version}}'
  weechat-cmd '/set weechat.color.chat_bg default'

Rebuild xmpp.so for a different architecture:
  git clone --depth 1 https://github.com/ekollof/xepher.git
  cd xepher && sudo make install-deps && make && make install
""")


if __name__ == "__main__":
    main()
