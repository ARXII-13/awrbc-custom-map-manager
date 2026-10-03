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

## Not the map editor

The save editor and the map editor are shipped apart on purpose: one is a
download that writes to a file the game owns, the other is hosted and talks to
a public archive of maps. Keeping the archive out of the download keeps them
separable.

The first packaged build did not do that. It loaded `web/index.html` — the map
editor's own page — so the download contained the editing engine, Export
bundle, and the path that submits a map to the archive, Submit button and CC
BY licence dialog included.

It now loads `web/save.html`, which imports the renderer and nothing else.
What the two share is drawing a map, because a save manager has to show which
one is which. `tools/desktop_payload.py` holds the list, and
`tests/test_desktop_payload.py` fails if anything on the forbidden list gets
back in — a convention nobody checks is how this happened the first time.

Maps come from somewhere else now: the hosted editor, a friend, the archive.
The panel imports a `.json` from disk rather than offering "add the map you
are editing", because nothing is being edited here.

The sprite pack does ship, which was weighed rather than assumed: it is
Advance Wars derived art, and a preview that does not look like the game is
harder to recognise.

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

But saying the *wrong* thing is worse than saying nothing, and the first
release candidate did. It blamed WebView2 for every failure to open a window,
and the real cause was unrelated: Windows stamps a `Zone.Identifier` stream on
everything extracted from a downloaded zip, and .NET refuses to load an
assembly from the Internet zone. pywebview reaches WebView2 through pythonnet,
so the app fell over on a mark nobody can see — and the one person who hit it
was sent to install a runtime they already had.

`why_no_window` looks for that mark before blaming anything, and prints the
`Unblock-File` command that fixes it. A confident wrong answer is the one
people act on.

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
