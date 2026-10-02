"""The desktop app.

    python -m awrbc.desktop

A Python process hosting the editor in the operating system's webview
(pywebview). The codec is an import rather than a subprocess, and the frontend
is the same one the website serves - nothing is written twice (decision #51).

This is what makes the archive usable. Importing a map was always going to be
the step most players failed at, and a terminal was never going to be how they
did it.

Save access exists here because a Python process is hosting the page. The
hosted build has no equivalent and no code path to a file system (#52), so the
boundary is structural rather than a promise.
"""
import os
import subprocess
import sys

from .api import SaveApi

WEB = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "web")

TITLE = "Advance Wars 1+2 map tool"


def game_running():
    """Is the emulator holding the save?

    Asks the platform's own process list. The same check the CLI makes, and
    for the same reason: a loaded game writes its own copy over anything put
    underneath it.

    Answers False when it cannot tell. Refusing to work because `ps` is
    missing would be worse than the risk, and that is a deliberate fail-open.
    """
    if os.environ.get("AWRBC_SKIP_PROCESS_CHECK"):
        return False
    argv = ["tasklist"] if sys.platform == "win32" else ["ps", "-A", "-o", "comm="]
    try:
        out = subprocess.run(argv, capture_output=True, text=True,
                             timeout=10).stdout.lower()
    except Exception:                                   # noqa: BLE001
        return False
    return "ryujinx" in out


def entry_point(web_dir=WEB):
    """The page to load. A file:// URL, so there is no server and no port."""
    index = os.path.join(web_dir, "index.html")
    if not os.path.exists(index):
        raise SystemExit(
            "cannot find the editor at %s.\n"
            "Running from a source checkout? The editor lives in web/."
            % index)
    return index


def main(argv=None):
    try:
        import webview
    except ImportError:
        sys.stderr.write(
            "the desktop app needs pywebview:\n"
            "    pip install \"awrbc-custom-map-manager[desktop]\"\n")
        return 1

    index = entry_point()
    api = SaveApi(game_running=game_running)

    window = webview.create_window(TITLE, index, js_api=api,
                                   width=1280, height=860, min_size=(900, 600))
    try:
        webview.start(debug=bool(os.environ.get("AWRBC_DEBUG")))
    except Exception as exc:                            # noqa: BLE001
        # The usual cause on Windows is a missing WebView2 runtime. A window
        # that never appears is not a diagnosis anybody can act on.
        sys.stderr.write(
            "could not open a window: %s\n\n"
            "On Windows this usually means the WebView2 runtime is missing. "
            "It ships with Windows 11 and with Edge; otherwise install it "
            "from Microsoft's 'WebView2 Runtime' download page.\n" % exc)
        return 1
    del window
    return 0


if __name__ == "__main__":
    sys.exit(main())
