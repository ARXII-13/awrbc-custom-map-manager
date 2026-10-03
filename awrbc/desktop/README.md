# The desktop app

The editor, hosted by a Python process that can reach your save.

```bash
pip install -e ".[desktop]"
python -m awrbc.desktop
```

This is the thing that makes the archive usable. Importing a map was always
going to be the step most players failed at, and a terminal was never going to
be how they did it (decision #51). The CLI remains, demoted to the scriptable
surface.

## Why pywebview and not Electron

The codec is Python and the renderer is JavaScript. pywebview is the only
option where neither gets written twice: Python *is* the process, the codec is
an import, and the frontend is the same `web/` the website serves, loaded into
the operating system's webview.

Electron or Tauri would mean bundling a Python runtime alongside Node and
Chromium, or porting MS-NRBF to JavaScript — two implementations of a format
that must agree forever. A Python GUI toolkit would mean a second map
renderer. Both are mistakes this project has already made once and undone.

## Save access follows the shell

`api.py` exists only here. The hosted build of the editor has no object like it
and no code path to a file system (decision #52), so `saves.available()` is
false in a browser and the save panel never appears.

That is a structural boundary rather than a promise: the browser version
*cannot* read your save, as opposed to being asked not to.

## Two things that are not style

**Failures cross the bridge as data.** pywebview turns a Python exception into
an unhelpful rejection in the page, so every method answers
`{"ok": false, "error": ...}` instead. The UI gets something it can show a
person rather than a promise that rejected for reasons nobody can see.

**Writes refuse while the game is running.** A loaded title flushes its own
copy of the save over anything written underneath it, so this is data loss
rather than an inconvenience. The check answers "not running" when it cannot
tell, which is a deliberate fail-open: refusing to work because `ps` is missing
would be worse than the risk.

## Previews

Drawn by the editor's own renderer from the documents the bridge returns —
with whatever sprite pack is loaded, same as everywhere else. There is no
second renderer here and there should never be one.

The pack ships inside a packaged build (decision #54). Without one, terrain
falls back to a letter on a flat colour.

## If no window opens

On Windows this is almost always a missing **WebView2 runtime**. It ships with
Windows 11 and with Edge; otherwise it is a free download from Microsoft. The
app says so rather than failing silently, because a window that never appears
is not a diagnosis anybody can act on.

A packaged build is built with `console=False`, so there is no terminal for
that message to appear in — `report()` puts it in a message box as well. A
diagnostic written to a stream nobody can see is the same as no diagnostic.

## Packaging

```bash
pip install -e ".[package]"
python tools/build_desktop.py
```

PyInstaller `--onedir` in a zip — unzip and run, no installer (decision #55).
An installer is a thing to trust, and this writes to a save file people care
about; a folder they can look inside asks for less. `dist/awrbc-windows.zip`
comes out around 13 MB and holds the executable, its runtime, and the editor
with its sprite pack.

Windows first. macOS and Linux keep using `pip install` until a bundled build
there is worth an Apple developer account and WebKitGTK bundling respectively;
the zip is named for its platform so those can land beside it.

Two things in there are not incidental. The entry script is
`tools/desktop_entry.py` rather than this package's `__main__.py`, because
PyInstaller runs its entry script *as* `__main__`, with no parent package — so
pointed straight at `__main__.py`, its relative imports fail on the first line.
That build zipped cleanly and then died on launch.

And the build runs what it has just made. `awrbc --check` does everything a
launch does except open the window, so a bundle that cannot import itself, or
cannot find its own editor, fails the build rather than the download. Checking
that the files are in there is not the same as the thing starting — which is
exactly how the import failure above got as far as a zip.
