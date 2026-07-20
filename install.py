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
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
LEGACY_HOME = Path.home() / ".weechat"

# WeeChat uses XDG dirs only when WEECHAT_HOME is unset and ~/.weechat does not
# exist; otherwise it uses the legacy home. Match that logic so we install to
# the directory WeeChat will actually load.
if os.environ.get("WEECHAT_HOME"):
    WEECHAT_HOME = Path(os.environ["WEECHAT_HOME"])
    WEECHAT_CONF = WEECHAT_HOME
    WEECHAT_DATA = WEECHAT_HOME
elif LEGACY_HOME.exists():
    WEECHAT_HOME = LEGACY_HOME
    WEECHAT_CONF = LEGACY_HOME
    WEECHAT_DATA = LEGACY_HOME
else:
    WEECHAT_HOME = None
    WEECHAT_CONF = XDG_CONFIG_HOME / "weechat"
    WEECHAT_DATA = XDG_DATA_HOME / "weechat"

SRC_CONF = SCRIPT_DIR / "weechat-conf"
SRC_PYTHON = SCRIPT_DIR / "weechat-python"
SRC_SO = SCRIPT_DIR / "weechat-plugins" / "xmpp.so"

# Config files that must live only on the local machine, never in this repo.
FORBIDDEN_EXPORT_FILES = frozenset({
    "sec.conf",
    "irc.conf",
    "xmpp.conf",
    "relay.conf",
})

# Patterns that must never appear in committed export config.
SECRET_PATTERNS = (
    (re.compile(r"xox[pabrs]-[A-Za-z0-9-]+"), "Slack API token"),
)


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

SLACK_TOKEN_KEY = "python.slack.slack_api_token"


def is_slack_token_placeholder(value: str) -> bool:
    return "YOUR_SLACK_TOKEN" in value


def is_real_slack_token(value: str) -> bool:
    return bool(re.search(r"xox[pabrs]-", value))


def slack_token_from_conf(path: Path):
    """Return the [var] slack token value from a plugins.conf, if present."""
    if not path.is_file():
        return None
    for key, value in parse_var_section(path):
        if key == SLACK_TOKEN_KEY:
            return value
    return None


def preserved_slack_token(dst: Path) -> str | None:
    """Find a real Slack token from the destination or other WeeChat homes."""
    candidates = [
        dst,
        dst.with_name("plugins.conf.pre-install.bak"),
        XDG_CONFIG_HOME / "weechat" / "plugins.conf",
        LEGACY_HOME / "plugins.conf",
    ]
    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        value = slack_token_from_conf(path)
        if value and is_real_slack_token(value):
            return value
    return None


def set_var_line(lines: list[str], key: str, value: str) -> bool:
    """Replace or insert a [var] key. Returns True if lines changed."""
    for i, line in enumerate(lines):
        m = re.match(r"^(\S+)\s*=\s*", line)
        if m and m.group(1) == key:
            new_line = f"{key} = {value}\n"
            if lines[i] == new_line:
                return False
            lines[i] = new_line
            return True

    for i, line in enumerate(lines):
        if line.rstrip("\n") == "[var]":
            lines.insert(i + 1, f"{key} = {value}\n")
            return True
    return False


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


def audit_export_conf(conf_dir: Path) -> list[str]:
    """Return human-readable errors if the export tree contains secrets."""
    errors = []

    for name in sorted(FORBIDDEN_EXPORT_FILES):
        if (conf_dir / name).is_file():
            errors.append(f"forbidden file present: weechat-conf/{name}")

    if not conf_dir.is_dir():
        return errors

    for path in sorted(conf_dir.glob("*.conf")):
        text = path.read_text()
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"{path.name}: contains {label}")

        if path.name == "plugins.conf":
            token = slack_token_from_conf(path)
            if token and is_real_slack_token(token):
                errors.append(f"{path.name}: contains Slack API token")

    return errors


def merge_plugins_conf(src: Path, dst: Path):
    """
    Merge [var] keys from src into dst.
    Keys present in src overwrite dst; keys only in dst are left alone.
    A real Slack token is never replaced by the export placeholder.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        shutil.copy2(dst, dst.with_name("plugins.conf.pre-install.bak"))

    if dst.exists():
        with open(dst) as f:
            dst_lines = f.readlines()
    else:
        with open(src) as f:
            dst_lines = f.readlines()
        info("  plugins.conf: installed from export")

    kept_token = preserved_slack_token(dst)
    src_vars = parse_var_section(src)
    updated = 0

    for key, value in src_vars:
        if key == SLACK_TOKEN_KEY and (
            is_slack_token_placeholder(value) or is_real_slack_token(value)
        ):
            continue

        if key == SLACK_TOKEN_KEY and kept_token:
            value = kept_token

        if set_var_line(dst_lines, key, value):
            updated += 1

    if kept_token and set_var_line(dst_lines, SLACK_TOKEN_KEY, kept_token):
        updated += 1
        info("  plugins.conf: preserved existing Slack token")

    with open(dst, "w") as f:
        f.writelines(dst_lines)

    info(f"  plugins.conf: merged {updated} keys")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # Preflight
    if not SRC_CONF.is_dir():
        error(f"Source conf dir not found: {SRC_CONF}")
    if not SRC_PYTHON.is_dir():
        error(f"Source python dir not found: {SRC_PYTHON}")

    secret_errors = audit_export_conf(SRC_CONF)
    if secret_errors:
        error(
            "Refusing to install: export contains secrets or machine-specific config.\n"
            + "\n".join(f"  - {err}" for err in secret_errors)
            + "\nRemove them from weechat-conf/ and use export.sh (which scrubs tokens)."
        )

    if not shutil.which("weechat"):
        error("weechat not found in PATH")

    if WEECHAT_HOME == LEGACY_HOME:
        warn(f"Using legacy WeeChat home: {LEGACY_HOME}")
        warn("To switch to XDG directories, move ~/.weechat to ~/.config/weechat")
        warn("and ~/.local/share/weechat, then remove ~/.weechat.")

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
    # irc.conf, xmpp.conf, sec.conf, relay.conf are local-only — never shipped here.
    INSTALL_ONCE = ["perl.conf", "python.conf"]

    info("Installing optional config files (skipped if already present)...")
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
    autoload_dir = WEECHAT_DATA / "python" / "autoload"
    # Migrate off legacy wee_slack.py filename (script still registers as "slack")
    legacy_autoload = autoload_dir / "wee_slack.py"
    if legacy_autoload.exists() or legacy_autoload.is_symlink():
        legacy_autoload.unlink()
        info("  removed legacy autoload symlink: wee_slack.py")
    for script in (
        "autosort",
        "urlgrab",
        "slack",
        "wallust",
        "notify_send",
        "sys_usage",
        "go",
        "weechat_debug_socket",
    ):
        src = WEECHAT_DATA / "python" / f"{script}.py"
        link = autoload_dir / f"{script}.py"
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
  4. Configure IRC/XMPP locally (see README — not included in this export)
  5. Run: wallust run <wallpaper>   (wallust.py then watches colors.json automatically)

Debug socket (optional):
  /script load weechat_debug_socket.py
  weechat-cmd '${{info:version}}'
  weechat-cmd '/set weechat.color.chat_bg default'

Rebuild xmpp.so for a different architecture:
  git clone --depth 1 https://github.com/ekollof/xepher.git
  cd xepher && sudo make install-deps && make && make install
""")


def audit_export_main():
    errors = audit_export_conf(SRC_CONF)
    if errors:
        for err in errors:
            print(f"{RED}SECRET:{RESET} {err}", file=sys.stderr)
        sys.exit(1)
    info("Export audit passed: no secrets found in weechat-conf/")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--audit-export":
        audit_export_main()
    else:
        main()
