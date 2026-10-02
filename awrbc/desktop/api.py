"""What the desktop app exposes to the page.

This is the save-access half of the tool, and it exists only here. The hosted
build of the editor has no object like this and no code path to a file system
(decision #52) - a browser *cannot* read your save, rather than promising not
to. Which build you are running decides what you can touch.

Everything returns plain data and never raises across the bridge: pywebview
turns a Python exception into an unhelpful rejection in the page, so every
call answers ``{"ok": False, "error": ...}`` instead. The UI gets something it
can show a person.

No rendering happens here. Maps come back as the same documents the editor
already draws, so the picture in the save list is drawn by `render.js` with
whatever sprite pack is loaded - one renderer, as everywhere else.
"""
import os
import traceback

from ..core import archive, backup, derive, locate, savefile, schema, validate
from ..core.errors import AwrbcError


def _fail(exc):
    """A failure the page can show, rather than a rejected promise."""
    if isinstance(exc, AwrbcError):
        return {"ok": False, "error": str(exc), "kind": type(exc).__name__}
    # Unexpected: keep the detail for a log, give the page something plain.
    traceback.print_exc()
    return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
            "kind": "Unexpected"}


def _guard(fn):
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:                        # noqa: BLE001
            return _fail(exc)
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


class SaveApi:
    """The bridge object. Every public method is callable from the page."""

    def __init__(self, game_running=None):
        # Injected so a test does not have to own a process table, and so the
        # check can be stubbed where a developer has the emulator open.
        self._game_running = game_running or (lambda: False)
        self._path = None

    # --- finding a save --------------------------------------------------

    @_guard
    def find_saves(self, save_dir=None):
        """Every save this machine has, most likely first."""
        found = []
        for c in locate.find_saves(save_dir or None):
            found.append({
                "path": c.path, "profile": c.profile, "saveId": c.save_id,
                "source": c.source, "size": c.size,
                "label": getattr(c, "label", c.source),
            })
        return {"ok": True, "saves": found}

    @_guard
    def open_save(self, path):
        """Read a save and describe every map in it.

        The documents come back whole, so the page can draw each map with the
        same renderer it uses for editing. A save holds a handful of maps, so
        there is no paging to be clever about.
        """
        doc = savefile.read(path)
        self._path = path

        maps = []
        for index, m in enumerate(doc.maps):
            built = schema.build_document(m, save_version=doc.save_version)
            report = validate.check(m)
            maps.append({
                "index": index,
                "slot": m.slot,
                "name": m.name,
                "document": built,
                "id": built["id"],
                "derived": derive.derived_block(m),
                "playable": m.is_playable,
                "warnings": [vars(f) for f in report.warnings],
            })

        return {"ok": True, "path": path, "saveVersion": doc.save_version,
                "size": os.path.getsize(path), "maps": maps}

    # --- changing it -----------------------------------------------------

    def _refuse_if_running(self):
        if self._game_running():
            raise AwrbcError(
                "the game appears to be running. It flushes its own copy of "
                "the save over anything written underneath it, so close it "
                "first.")

    @_guard
    def import_map(self, path, document, name=None):
        """Add a map. Takes the same document the editor exports."""
        self._refuse_if_running()
        m = schema.from_json(document)
        report = validate.check(m)
        if report.errors:
            return {"ok": False, "error": "that map is not playable",
                    "kind": "ValidationFailed",
                    "findings": [vars(f) for f in report.errors]}

        doc = savefile.read(path)
        snap = backup.snapshot(path)
        slot = savefile.add_map(doc, m, name=name)
        written = savefile.write(doc, path)
        return {"ok": True, "slot": slot, "bytes": written,
                "backup": snap.path,
                "warnings": [vars(f) for f in report.warnings]}

    @_guard
    def remove_map(self, path, index):
        self._refuse_if_running()
        doc = savefile.read(path)
        if not 0 <= index < len(doc.maps):
            raise AwrbcError("no map at %d; the save holds %d"
                             % (index, len(doc.maps)))
        name = doc.maps[index].name
        snap = backup.snapshot(path)
        slot = savefile.remove_map(doc, index)
        savefile.write(doc, path)
        return {"ok": True, "removed": name, "slot": slot,
                "backup": snap.path}

    # --- backups ---------------------------------------------------------

    @_guard
    def snapshots(self, path):
        return {"ok": True, "snapshots": [
            {"name": s.name, "size": s.size, "taken": s.taken, "path": s.path}
            for s in backup.snapshots(path)]}

    @_guard
    def backup_now(self, path):
        snap = backup.snapshot(path)
        return {"ok": True, "backup": snap.path, "name": snap.name}

    @_guard
    def restore(self, path, snapshot_name):
        self._refuse_if_running()
        match = [s for s in backup.snapshots(path)
                 if s.name == snapshot_name or s.taken == snapshot_name]
        if not match:
            raise AwrbcError("no snapshot called %r" % snapshot_name)
        # The current state is kept too, so restoring is itself undoable.
        backup.snapshot(path)
        n = backup.restore(match[0].path, path)
        return {"ok": True, "restored": match[0].name, "bytes": n}

    # --- the archive -----------------------------------------------------

    @_guard
    def map_identity(self, document):
        """The content hash, so the page can tell a map it already has.

        Here rather than in JavaScript for the usual reason: one
        implementation of the hash (see awrbc/core/identity.py).
        """
        m = schema.from_json(document)
        return {"ok": True, "id": archive.map_hash(m),
                "folder": archive.folder_for(m)}
