"""
weechat_debug_socket.py — two-way debug interface via Unix socket

Listens on a Unix socket. Each connection sends one expression (or /command),
gets one line back, then closes.

Protocol:
  - Send any string ending with newline.
  - If it starts with '/' it is executed as a weechat command (no output returned).
  - Otherwise it is evaluated with weechat.string_eval_expression() and the
    result is written back, followed by a newline.

Socket path: ${weechat_runtime_dir}/weechat_debug.sock
  (usually /run/user/1000/weechat/weechat_debug.sock)

Usage:
  echo 'weechat.color.chat_bg' | socat - UNIX-CONNECT:/run/user/1000/weechat/weechat_debug.sock
  echo '/set weechat.color.chat_bg default' | socat - UNIX-CONNECT:/run/user/1000/weechat/weechat_debug.sock

Or use the weechat-cmd wrapper script.
"""

import weechat
import socket
import os
import errno

SCRIPT_NAME = "weechat_debug_socket"
SCRIPT_AUTHOR = "local"
SCRIPT_VERSION = "1.0"
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC = "Two-way debug interface via Unix socket (eval + command execution)"

_server_sock = None
_hook_fd = None
_sock_path = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runtime_dir():
    """Return weechat's runtime dir (same as ${weechat_runtime_dir})."""
    return weechat.info_get("weechat_dir", "").replace(
        weechat.info_get("weechat_config_dir", ""),
        weechat.info_get("weechat_runtime_dir", ""),
    ) or os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
        "weechat",
    )


def _get_sock_path():
    runtime = weechat.info_get("weechat_runtime_dir", "")
    if not runtime:
        runtime = os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
            "weechat",
        )
    os.makedirs(runtime, exist_ok=True)
    return os.path.join(runtime, "weechat_debug.sock")


def _eval(expr):
    """Evaluate a weechat expression and return the string result."""
    return weechat.string_eval_expression(expr, {}, {}, {})


def _exec_command(cmd):
    """Execute a weechat command on the core buffer."""
    buf = weechat.buffer_search_main()
    weechat.command(buf, cmd)


# ---------------------------------------------------------------------------
# Socket handling
# ---------------------------------------------------------------------------


def _accept_cb(data, fd):
    """Called by weechat when the listening socket is readable (new connection)."""
    global _server_sock
    if _server_sock is None:
        return weechat.WEECHAT_RC_OK

    try:
        conn, _ = _server_sock.accept()
    except OSError:
        return weechat.WEECHAT_RC_OK

    try:
        conn.settimeout(2.0)
        raw = b""
        while not raw.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            raw += chunk

        line = raw.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")

        if not line:
            conn.sendall(b"(empty input)\n")
        elif line.startswith("/"):
            # Command — execute, no output
            _exec_command(line)
            conn.sendall(b"ok\n")
        elif line.startswith("!py "):
            # Python eval/exec — expressions return their value; statements are
            # also supported. print() output is captured and returned.
            code = line[4:]
            try:
                import io
                import sys
                import weechat as _wc  # noqa: F401 — expose to eval'd code

                ns = {"weechat": _wc}
                buf = io.StringIO()
                old_stdout = sys.stdout
                sys.stdout = buf
                try:
                    try:
                        result = eval(code, ns)  # noqa: S307
                        output = buf.getvalue()
                        if output:
                            response = output.rstrip("\n")
                        elif result is not None:
                            response = str(result)
                        else:
                            response = "None"
                    except SyntaxError:
                        exec(code, ns)  # noqa: S102
                        output = buf.getvalue()
                        response = output.rstrip("\n") if output else "ok"
                finally:
                    sys.stdout = old_stdout
                conn.sendall((response + "\n").encode("utf-8"))
            except Exception as e:
                conn.sendall(f"ERROR: {e}\n".encode("utf-8"))
        else:
            # Eval expression
            result = _eval(line)
            conn.sendall((result + "\n").encode("utf-8"))
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass

    return weechat.WEECHAT_RC_OK


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------


def _start_server():
    global _server_sock, _hook_fd, _sock_path

    _sock_path = _get_sock_path()

    # Remove stale socket file if it exists
    try:
        os.unlink(_sock_path)
    except FileNotFoundError:
        pass

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)
    try:
        sock.bind(_sock_path)
    except OSError as e:
        weechat.prnt("", f"{SCRIPT_NAME}: failed to bind {_sock_path}: {e}")
        sock.close()
        return False

    sock.listen(8)
    _server_sock = sock

    _hook_fd = weechat.hook_fd(
        sock.fileno(),
        1,  # flag_read
        0,  # flag_write
        0,  # flag_exception
        "_accept_cb",
        "",
    )

    weechat.prnt("", f"{SCRIPT_NAME}: listening on {_sock_path}")
    return True


def _stop_server():
    global _server_sock, _hook_fd, _sock_path

    if _hook_fd:
        weechat.unhook(_hook_fd)
        _hook_fd = None

    if _server_sock:
        try:
            _server_sock.close()
        except OSError:
            pass
        _server_sock = None

    if _sock_path:
        try:
            os.unlink(_sock_path)
        except FileNotFoundError:
            pass
        _sock_path = None


# ---------------------------------------------------------------------------
# Script entry / exit
# ---------------------------------------------------------------------------


def weechat_debug_socket_unload_cb():
    _stop_server()
    return weechat.WEECHAT_RC_OK


if weechat.register(
    SCRIPT_NAME,
    SCRIPT_AUTHOR,
    SCRIPT_VERSION,
    SCRIPT_LICENSE,
    SCRIPT_DESC,
    "weechat_debug_socket_unload_cb",
    "UTF-8",
):
    _start_server()
