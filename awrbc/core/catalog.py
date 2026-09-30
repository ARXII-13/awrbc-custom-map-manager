"""The archive's index.

``catalog.json`` is a generated file. It exists so a client can search the
library without cloning it and so ``publish`` can tell a new map from a revision
without reading every file in the repo.

It is never authoritative. Everything in it is recomputed from the map files,
CI regenerates it on merge, and a mismatch is the catalog's fault. The one
exception is ``added``: when a version first appeared is not recoverable from
its contents, so a rebuild carries the old date forward and only dates entries
it has never seen. Losing the catalog would therefore lose submission dates -
which is a real cost, and the reason it is committed rather than built on
demand.
"""
import datetime
import json
import os

from . import archive, derive, schema

SCHEMA_VERSION = 1

FILENAME = "catalog.json"


def _today():
    return datetime.date.today().isoformat()


def version_entry(m, doc, version, added=None):
    """One published revision, as the catalog records it.

    The derived facts are copied in so a browser can filter on "4 players, has
    navy, no fog" against the index alone. They are still derived - this is a
    cache of ``derive.derived_block``, not a second source for it.
    """
    d = derive.derived_block(m)
    return {
        "version": version,
        "hash": archive.map_hash(m),
        "cols": m.cols,
        "rows": m.rows,
        "players": d["players"],
        "predeployed": d["predeployed"],
        "navy": d["navy"],
        "structures": d["structures"],
        "fog": d["fog"],
        "tags": sorted(m.tags),
        "added": added or _today(),
    }


def map_entry(m, doc, path, added=None):
    """A whole map folder, holding one version."""
    p = archive.parse(path)
    return {
        "category": p.category,
        "slug": p.slug,
        "name": m.name,
        "author": doc.get("author") or "",
        "versions": [version_entry(m, doc, p.version, added)],
    }


def add(catalog, m, doc, path, added=None):
    """Fold one map file into a catalog, in place, and return it.

    Later versions win for the fields that describe the map as a whole - a
    rename or a change of author in v2 is what the archive should show, since
    that is the author's latest word on it.
    """
    p = archive.parse(path)
    entry = catalog.get(p.folder)
    if entry is None:
        catalog[p.folder] = map_entry(m, doc, path, added)
        return catalog

    entry["versions"] = [v for v in entry["versions"]
                         if v.get("version") != p.version]
    entry["versions"].append(version_entry(m, doc, p.version, added))
    entry["versions"].sort(key=lambda v: v["version"])
    if p.version >= max(v["version"] for v in entry["versions"]):
        entry["name"] = m.name
        entry["author"] = doc.get("author") or ""
    return catalog


def map_files(root):
    """Every map file in a library checkout, as repo-relative POSIX paths.

    Sorted, so a rebuilt catalog is byte-identical run to run and a regeneration
    commit shows only real changes.
    """
    base = os.path.join(root, archive.ROOT)
    found = []
    for dirpath, _, filenames in os.walk(base):
        for name in filenames:
            if not name.endswith(".json"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def previous_dates(catalog):
    """``{path: added}`` from an existing catalog, so a rebuild keeps them."""
    dates = {}
    for folder, entry in (catalog or {}).items():
        for v in entry.get("versions", []):
            path = "/".join([folder, archive.version_file(v["version"])])
            if v.get("added"):
                dates[path] = v["added"]
    return dates


def build(root, keep_dates_from=None):
    """Rebuild the index from the map files themselves.

    Returns ``(catalog, problems)``. A file that will not parse is reported
    rather than raised: one bad map must not make the whole catalog
    unbuildable, or a single bad merge takes the archive offline.
    """
    dates = previous_dates(keep_dates_from)
    catalog, problems = {}, []
    for path in map_files(root):
        try:
            with open(os.path.join(root, path), encoding="utf-8") as fh:
                doc = json.load(fh)
            m = schema.from_json(doc)
            add(catalog, m, doc, path, dates.get(path))
        except Exception as exc:                        # noqa: BLE001
            problems.append({"path": path, "error": str(exc)})
    return catalog, problems


def load(root):
    """The committed catalog, or ``{}`` when there is not one yet.

    Falls back to empty rather than rebuilding: a fresh clone of an empty
    archive and a corrupt catalog are different situations, and silently
    rebuilding the second would hide it.
    """
    path = os.path.join(root, FILENAME)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc.get("maps", {})


def dump(catalog, root):
    """Write the catalog, returning the path.

    ``sort_keys`` and a trailing newline are not cosmetic - without them a
    regeneration commit is an unreadable diff every time.
    """
    path = os.path.join(root, FILENAME)
    payload = {
        "schema": SCHEMA_VERSION,
        "generated": _today(),
        "count": len(catalog),
        "maps": catalog,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    return path


# --- Generated files --------------------------------------------------------
#
# The catalog is not the only thing in the repository that is computed from the
# map files: each version has a preview image and each map folder a README. All
# of it is regenerated together, because a README that disagreed with the
# catalog beside it would be worse than having neither.


def regenerate(root, keep_dates_from=None):
    """Recompute every generated file. Returns ``(files, problems)``.

    ``files`` maps a repo-relative path to the bytes it should contain, so the
    caller can either write them or compare - which is the difference between
    what a merge does and what a pull request check does.
    """
    from . import preview

    dates = previous_dates(keep_dates_from)
    index, problems, maps = {}, [], {}
    for path in map_files(root):
        try:
            with open(os.path.join(root, path), encoding="utf-8") as fh:
                doc = json.load(fh)
            m = schema.from_json(doc)
            add(index, m, doc, path, dates.get(path))
            maps[path] = m
        except Exception as exc:                        # noqa: BLE001
            problems.append({"path": path, "error": str(exc)})

    # Previews are not made here. The editor renders them: it owns the icons
    # and whatever sprite pack is loaded, and a second renderer in Python could
    # only ever draw a worse picture of the same map while needing to be kept in
    # step with the first. What this does instead is notice which versions have
    # one, so a README never embeds an image that is not there.
    files, shots = {}, {}
    for path in maps:
        p = archive.parse(path)
        shot = "/".join([p.folder, preview.preview_file(p.version)])
        shots[shot] = os.path.exists(os.path.join(root, *shot.split("/")))

    for folder, entry in index.items():
        have = {v["version"] for v in entry.get("versions", [])
                if shots.get("/".join([folder,
                                       preview.preview_file(v["version"])]))}
        files["/".join([folder, "README.md"])] = \
            preview.readme(entry, folder, previews=have).encode("utf-8")
    files[FILENAME] = payload_bytes(index)
    return files, problems


def payload_bytes(catalog):
    """The catalog as it is written, so it can be compared without writing."""
    payload = {
        "schema": SCHEMA_VERSION,
        "generated": _today(),
        "count": len(catalog),
        "maps": catalog,
    }
    return (json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")


def write_generated(root, files):
    """Write the generated files, returning the paths that actually changed."""
    changed = []
    for rel, data in sorted(files.items()):
        target = os.path.join(root, *rel.split("/"))
        if os.path.exists(target):
            with open(target, "rb") as fh:
                if fh.read() == data:
                    continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
        changed.append(rel)
    return changed


def stale(root, files):
    """Generated files that are missing or out of step with the map beside them.

    ``catalog.json`` carries a generation date, so it differs on any day it is
    rebuilt whether or not anything changed. Comparing it byte for byte would
    make every check fail the next morning, so it is compared on content.
    """
    out = []
    for rel, data in sorted(files.items()):
        target = os.path.join(root, *rel.split("/"))
        if not os.path.exists(target):
            out.append(rel)
            continue
        with open(target, "rb") as fh:
            existing = fh.read()
        if rel == FILENAME:
            try:
                if json.loads(existing.decode("utf-8")).get("maps") == \
                        json.loads(data.decode("utf-8")).get("maps"):
                    continue
            except Exception:                           # noqa: BLE001
                pass
        if existing != data:
            out.append(rel)
    return out
