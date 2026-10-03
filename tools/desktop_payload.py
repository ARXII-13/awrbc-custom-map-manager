"""What the save editor is allowed to contain.

The save editor and the map editor are shipped apart on purpose: one is a
downloadable tool that writes to a file the game owns, the other is a hosted
editor that talks to a public archive of maps. Keeping the archive out of the
download keeps them separable if they ever need to be.

The first packaged build did not do that. It bundled the whole of `web/`, so
the save editor contained the editing engine, Export bundle, and the archive
submission path - Submit button and licence dialog included - because the one
page it loaded was the map editor's own index.html.

So the list lives here rather than inside the .spec: the build reads it, and
tests/test_desktop_payload.py reads it too and fails if anything on the
forbidden list creeps back in. A convention nobody checks is how this happened
the first time.
"""
import os

#: Modules the save editor genuinely needs.
#:
#:   render.js   draws a map - the whole reason any of this is shared
#:   terrain.js  the tile table render.js reads
#:   sprites.js  loads the sprite pack render.js draws with
#:   saves.js    the pywebview bridge to Python
#:   save-ui.js  the panel itself
ALLOWED = (
    "save.html",
    "render.js",
    "terrain.js",
    "sprites.js",
    "saves.js",
    "save-ui.js",
)

#: Never in the download, and the reason for each.
#:
#:   index.html    the map editor's own page
#:   edit.js       the editing engine
#:   fixes.js      map repairs, part of editing
#:   zip.js        Export bundle
#:   intake.js     talking to the archive
#:   submit-ui.js  the Submit button and the CC BY licence dialog
FORBIDDEN = (
    "index.html",
    "edit.js",
    "fixes.js",
    "zip.js",
    "intake.js",
    "submit-ui.js",
)

#: Directories never worth shipping. `samples` is personal save data per
#: .gitignore, and a build on a developer's machine was putting it in the zip.
SKIP_DIRS = {"test", "cache", "samples", "__pycache__"}


def payload(web_dir):
    """``[(source, destination)]`` for everything the save editor ships.

    The named modules, plus the sprite pack - which is art derived from
    Advance Wars by way of Commander Wars, and is in here deliberately: a
    preview that does not look like the game is harder to recognise, and that
    was weighed against shipping the art and chosen.
    """
    out = []
    for name in ALLOWED:
        source = os.path.join(web_dir, name)
        if not os.path.exists(source):
            raise SystemExit("the save editor needs %s and it is missing from "
                             "%s" % (name, web_dir))
        out.append((source, "web"))

    pack = os.path.join(web_dir, "sprites")
    for folder, dirs, names in os.walk(pack):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(folder, web_dir)
        for name in names:
            if name in ("README.md", "manifest.example.json"):
                continue
            if name.startswith("build_") and name.endswith(".py"):
                continue
            out.append((os.path.join(folder, name), os.path.join("web", rel)))

    if not any(s.endswith("manifest.json") for s, _ in out):
        raise SystemExit("no sprite pack in %s - terrain would render as "
                         "letters (decision #54)" % pack)
    return out
