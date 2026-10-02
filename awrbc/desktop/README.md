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

## Packaging

Not built yet. The intent is PyInstaller `--onedir` in a zip — unzip and run,
no installer (decision #55). Windows first; macOS and Linux are served by
`pip install` until a bundled build there is worth an Apple developer account
and WebKitGTK bundling respectively.
