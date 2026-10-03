**Windows only, and submitting maps from the editor is not live yet.**

## What works

- **Desktop app** — download `awrbc-windows.zip`, unzip it, run `awrbc.exe`.
  Opens your Ryujinx save, lists the maps in it, and puts new ones in. Every
  write takes a backup first, and it refuses to write while the game is
  running, because a loaded game flushes its own copy of the save over
  anything put underneath it.
- **Map editor** — in a browser, nothing to install:
  <https://arxii-13.github.io/awrbc-custom-map-manager/>
  Paint terrain, place units and structures, live validity checks, and
  **Export bundle** for a zip holding the map and a picture of it.
- **Command line** — `pip install .` gives `awrbc`: export, import, remove,
  backup, restore, and `search` / `show` / `import` against the public
  archive.

## What does not work yet

- **Submitting from the editor.** The intake server is built and tested but
  is not hosted anywhere, so the deployed editor has no Submit button. Use
  **Export bundle** and send the zip instead.
- **macOS and Linux desktop builds.** `pip install ".[desktop]"` and then
  `python -m awrbc.desktop` works on both; there is no packaged download.
- **Sea, river and shoal** draw as a letter on flat colour — they have no
  sprites in the pack yet. Every other terrain does.
- **The archive is nearly empty.** One map, so far.

## Before you run it

Needs the **WebView2 runtime**, which ships with Windows 11 and with Edge.
The app says so if it is missing rather than opening no window and leaving you
to guess.

It writes to your save. It takes a backup before every write and keeps them,
but take your own first — this is a release candidate and it has not been
through a full round of testing on a machine that is not the one it was built
on.

## Reporting something

Open an issue with what you did, what happened, and the save's size if it is
about a save. `awrbc doctor` prints what the tool can see, which is usually
the fastest thing to paste.
