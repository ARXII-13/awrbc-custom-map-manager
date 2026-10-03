# PyInstaller spec for the desktop app.
#
# --onedir in a zip: unzip and run, no installer (decision #55). A --onefile
# build unpacks itself to a temp directory on every launch, which is slower
# and is what antivirus software notices; a folder is also something a person
# can look inside, which matters for a tool that writes to their save.
#
#     python tools/build_desktop.py
#
# Not run by CI. It needs a machine of the target platform and PyInstaller,
# and the thing it produces is a release artifact rather than a test.

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.getcwd())
WEB = os.path.join(ROOT, "web")

if not os.path.exists(os.path.join(WEB, "index.html")):
    raise SystemExit("run this from the repository root; no web/index.html "
                     "under %s" % ROOT)

# The editor, the sprite pack included (decision #54 - a build without it
# renders terrain as letters on flat colour, which looks broken rather than
# plain). The test directory and the dev server are not part of a shipped app.
web_files = []
for folder, _dirs, names in os.walk(WEB):
    rel = os.path.relpath(folder, WEB)
    parts = rel.replace("\\", "/").split("/")
    if parts[0] in ("test", "cache"):
        continue
    for name in names:
        if name in ("serve.py", "README.md", "manifest.example.json"):
            continue
        if name.startswith("build_") and name.endswith(".py"):
            continue
        web_files.append((os.path.join(folder, name),
                          os.path.join("web", rel) if rel != "." else "web"))

a = Analysis(
    # tools/desktop_entry.py, not awrbc/desktop/__main__.py - see that file.
    # Pointed straight at __main__.py, PyInstaller runs it as `__main__` with
    # no parent package and its relative imports fail on the first line.
    [os.path.join(ROOT, "tools", "desktop_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=web_files,
    # pywebview loads its platform backend by name, so static analysis does
    # not see it and the window never opens.
    hiddenimports=collect_submodules("webview"),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PIL", "numpy", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="awrbc",
    debug=False,
    strip=False,
    upx=False,
    # A console window beside the app reads as a fault. The cost is that
    # stderr goes nowhere, so `report()` in __main__ puts startup failures -
    # the WebView2 one above all - into a message box as well.
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="awrbc",
)
