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

def web_dir():
    """Where the editor's files are.

    Two layouts. From a checkout, `web/` sits at the repository root, three
    directories above this file. Packaged, PyInstaller unpacks the bundled
    copy and points `sys._MEIPASS` at it - the same attribute for a --onedir
    build and a --onefile one, which is why neither is special-cased here.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return os.path.join(bundled, "web")
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "web")


#: Read once, at import, so a test can point `entry_point` somewhere else
#: without reaching into the module's internals.
WEB = web_dir()

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


def entry_point(folder=WEB):
    """The page to load. A file:// URL, so there is no server and no port."""
    index = os.path.join(folder, "index.html")
    if not os.path.exists(index):
        raise SystemExit(
            "cannot find the editor at %s.\n"
            "A packaged build bundles it; from a checkout it lives in web/."
            % index)
    return index


def report(message, box=None):
    """Tell somebody who may have no console.

    A packaged build is built with `console=False`, because a terminal window
    sitting beside the app reads as a fault - which leaves stderr going
    nowhere. Everything below is a startup failure where the whole point is
    that the person can act on it, so on Windows it also goes to a message
    box. `box` is injected so a test can see what would have been shown.
    """
    sys.stderr.write(message)
    if box is None:
        if not getattr(sys, "frozen", False) or sys.platform != "win32":
            return
        try:
            import ctypes
            box = lambda text: ctypes.windll.user32.MessageBoxW(  # noqa: E731
                None, text, TITLE, 0x10)
        except Exception:                                   # noqa: BLE001
            return
    try:
        box(message)
    except Exception:                                       # noqa: BLE001
        # Reporting a failure must not become a second failure.
        pass


#: The assembly .NET actually refuses to load. Naming it is worth more than
#: listing whichever files `os.walk` happened to reach first - the bundle has
#: dozens of api-ms-win-core-*.dll beside it and none of them explain anything.
THE_ASSEMBLY = "python.runtime.dll"


def blocked_files(folder):
    """Files Windows has marked as having come from the internet.

    Returns ``(count, example)``. Extracting a downloaded zip stamps every
    file with a Zone.Identifier stream, and the .NET loader then refuses to
    load an assembly from the Internet zone. pywebview reaches WebView2
    through pythonnet, so the whole app falls over on a mark nobody can see.

    Reads the alternate data stream directly: a path of the form
    ``file:Zone.Identifier`` is the stream, and opening it fails when there is
    none. Only NTFS has them, and only Windows, so anywhere else this is zero.
    """
    if sys.platform != "win32" or not os.path.isdir(folder):
        return 0, ""
    count, example = 0, ""
    for root, _dirs, names in os.walk(folder):
        for name in names:
            if not name.lower().endswith((".dll", ".exe", ".pyd")):
                continue
            path = os.path.join(root, name)
            try:
                with open(path + ":Zone.Identifier", "rb") as fh:
                    if b"ZoneId=3" not in fh.read(512):
                        continue
            except OSError:
                continue            # no stream, or not a filesystem with them
            count += 1
            # Prefer the one that matters; otherwise the first seen.
            if not example or name.lower() == THE_ASSEMBLY:
                example = path
    return count, example


def why_no_window(exc, folder):
    """The message for a window that would not open.

    Written as a diagnosis rather than a guess. The first release blamed a
    missing WebView2 runtime for every failure, and the actual cause was a
    zone mark on the bundled .NET assembly - so the one person who hit it was
    sent to install a runtime they already had.
    """
    count, example = blocked_files(folder)
    if count:
        # The install root, not _internal: that is the folder a person has and
        # the one the command below should be pointed at.
        root = os.path.dirname(folder) or folder
        return (
            "This app cannot start, and it is not broken - Windows has it "
            "blocked.\n\n"
            "It was extracted from a downloaded zip, so Windows marked its "
            "files as coming from the internet. .NET refuses to load a marked "
            "assembly, and this app reaches the browser engine through .NET. "
            "%d files are marked, including:\n\n"
            "    %s\n\n"
            "To unblock them, paste this into PowerShell:\n\n"
            "    Get-ChildItem -Recurse '%s' | Unblock-File\n\n"
            "Or delete that folder, right-click the .zip, tick Unblock in "
            "Properties, and extract it again.\n\n"
            "(%s)\n"
            % (count, example or root, root, exc))

    return (
        "could not open a window: %s\n\n"
        "On Windows this usually means the WebView2 runtime is missing. It "
        "ships with Windows 11 and with Edge; otherwise install it from "
        "Microsoft's 'WebView2 Runtime' download page.\n" % exc)


def main(argv=None, box=None):
    argv = sys.argv[1:] if argv is None else argv

    try:
        import webview
    except ImportError:
        report("the desktop app needs pywebview:\n"
               "    pip install \"awrbc-custom-map-manager[desktop]\"\n", box)
        return 1

    try:
        index = entry_point()
    except SystemExit as exc:
        report("%s\n" % exc, box)
        return 1

    api = SaveApi(game_running=game_running)

    # Everything a launch does except open the window, so a packaged build can
    # be checked without a desktop. It is the only part of packaging that can
    # fail silently: a bundle that cannot import itself or cannot find its own
    # editor still zips, and the first person to know would be whoever
    # double-clicked it.
    if "--check" in argv:
        sys.stdout.write("ok: editor at %s\n" % index)
        return 0

    window = webview.create_window(TITLE, index, js_api=api,
                                   width=1280, height=860, min_size=(900, 600))
    try:
        webview.start(debug=bool(os.environ.get("AWRBC_DEBUG")))
    except Exception as exc:                            # noqa: BLE001
        # A window that never appears is not a diagnosis anybody can act on,
        # and neither is the wrong one - see why_no_window.
        # The bundle root, not the editor's folder: the marked file that
        # matters is the .NET assembly in _internal, which is where
        # sys._MEIPASS points. Unfrozen there is nothing to scan.
        report(why_no_window(exc, getattr(sys, "_MEIPASS", "")), box)
        return 1
    del window
    return 0


if __name__ == "__main__":
    sys.exit(main())
