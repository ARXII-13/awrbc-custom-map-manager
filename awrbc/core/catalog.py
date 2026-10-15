"""The archive's index.

``catalog.json`` exists so a client can search the library without cloning it,
and so ``publish`` can tell a new map from a revision without reading every
file in the repo. Directory listing is the thing HTTP does not give you, and
this is the answer to it.

**Built and published, not committed** (decision #57). It is derived from
every map in the archive, so a copy in the repository was one file each
submission had to agree about. CI builds it on merge with ``--build-into``
and publishes it; anything working against a checkout builds its own, which
costs a directory walk and cannot be out of step with the maps beside it.

It is never authoritative. Everything in it is recomputed from the map files
and a mismatch is the index's fault - with one exception. When a version
first appeared is not recoverable from its contents, so it is stored beside
the map in ``meta.json``, keyed by version and only ever appended to. That is
what made the index safe to throw away: the one fact it held that nothing
else could rebuild no longer lives in it.
"""
import datetime
import json
import os
import re

from . import archive, derive, schema

SCHEMA_VERSION = 1

FILENAME = "catalog.json"


def today():
    """Today, UTC, as an ISO date.

    Public because provenance is written in two places now: here when a
    catalog entry is first dated, and in `submission.prepare` when the
    meta.json beside a map is written. Both have to agree on what day it is.
    """
    return datetime.date.today().isoformat()


def _today():
    return datetime.date.today().isoformat()


def version_entry(m, version, added=None):
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
        "versions": [version_entry(m, version=p.version, added=added)],
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
    entry["versions"].append(version_entry(m, p.version, added))
    entry["versions"].sort(key=lambda v: v["version"])
    if p.version >= max(v["version"] for v in entry["versions"]):
        entry["name"] = m.name
        entry["author"] = doc.get("author") or ""
    return catalog


#: The only JSON under ``maps/`` that is a map. A folder also holds
#: ``meta.json``, which is about the submission rather than the map, and
#: feeding that to the schema reports it as a map that will not parse.
VERSION_JSON = re.compile(r"^v[1-9][0-9]*\.json$")

#: Submission provenance, beside the map it describes. Holds the one fact a
#: map file cannot: when each version arrived. See decision #57.
META = "meta.json"


def map_files(root):
    """Every map file in a library checkout, as repo-relative POSIX paths.

    Sorted, so a rebuilt catalog is byte-identical run to run and a regeneration
    commit shows only real changes.
    """
    base = os.path.join(root, archive.ROOT)
    found = []
    for dirpath, _, filenames in os.walk(base):
        for name in filenames:
            if not VERSION_JSON.match(name):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def read_meta(root, folder):
    """One folder's ``meta.json``, or ``{}``.

    Unreadable reads as absent on purpose: a corrupt provenance file must not
    make the archive unbuildable. What is lost is a submission date, and
    `build` says so by falling back rather than failing.
    """
    path = os.path.join(root, *folder.split("/"), META)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:                                   # noqa: BLE001
        return {}
    return doc if isinstance(doc, dict) else {}


def meta_document(added):
    """``meta.json`` as it should be written. ``added`` is {version: date}."""
    return {"schema": SCHEMA_VERSION,
            "added": {str(k): v for k, v in sorted(
                added.items(), key=lambda kv: int(kv[0]))}}


def meta_dates(root):
    """``{path: added}`` taken from the map folders themselves.

    This is where submission dates live now (decision #57). It is the one
    thing in a catalog entry that is not recomputed from the map file, so it
    has to be stored somewhere - and beside the map, keyed by version and only
    ever appended to, two submissions cannot collide over it.
    """
    dates = {}
    for path in map_files(root):
        folder = path.rsplit("/", 1)[0]
        got = read_meta(root, folder).get("added")
        if not isinstance(got, dict):
            continue
        for version, when in got.items():
            try:
                rel = archive.version_path(folder, int(version))
            except (TypeError, ValueError):
                continue
            if isinstance(when, str) and when:
                dates[rel] = when
    return dates


def previous_dates(catalog):
    """``{path: added}`` from an existing catalog, so a rebuild keeps them."""
    dates = {}
    for folder, entry in (catalog or {}).items():
        for v in entry.get("versions", []):
            path = archive.version_path(folder, v["version"])
            if v.get("added"):
                dates[path] = v["added"]
    return dates


def build(root, keep_dates_from=None):
    """Rebuild the index from the map files themselves.

    Returns ``(catalog, problems)``. A file that will not parse is reported
    rather than raised: one bad map must not make the whole catalog
    unbuildable, or a single bad merge takes the archive offline.
    """
    # meta.json first, then whatever a previous catalog recorded. The
    # fallback is what lets this change ship before the catalog is gone: an
    # archive that has not grown meta.json files yet keeps its dates.
    dates = previous_dates(keep_dates_from)
    dates.update(meta_dates(root))
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

    index, problems = build(root, keep_dates_from)

    # Previews are not made here. The editor renders them: it owns the icons and
    # whatever sprite pack is loaded, and a second renderer in Python could only
    # ever draw a worse picture of the same map while needing to be kept in step
    # with the first. All this does is notice which versions have one, so a
    # README never embeds an image that is not there.
    files = {}
    for folder, entry in index.items():
        have = set()
        for v in entry.get("versions", []):
            rel = "/".join([folder, preview.preview_file(v["version"])])
            target = os.path.join(root, *rel.split("/"))
            if not os.path.exists(target):
                continue
            have.add(v["version"])
            # A preview is untrusted input sitting in the repository, and a
            # pull request can add one without going anywhere near `publish`.
            # The catalog already knows what size the map is, so checking the
            # image against it costs nothing extra here.
            with open(target, "rb") as fh:
                found = preview.check_png(fh.read(),
                                          tiles=(v["cols"], v["rows"]))
            for f in found.errors:
                # Same wording `verify` uses, so a caller doing both checks can
                # drop the duplicate rather than print the same fault twice.
                problems.append({"path": rel,
                                 "error": "%s: %s" % (f.code, f.message)})
        files["/".join([folder, "README.md"])] = \
            preview.readme(entry, previews=have).encode("utf-8")
    files[FILENAME] = payload_bytes(index)
    return files, problems


def payload_bytes(catalog):
    """The catalog as it is written, so it can be compared without writing.

    ``sort_keys`` and the trailing newline are not cosmetic: without them a
    regeneration commit is an unreadable diff every time.
    """
    payload = {
        "schema": SCHEMA_VERSION,
        "generated": _today(),
        "count": len(catalog),
        "maps": catalog,
    }
    return (json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")


#: Generated, but not committed (decision #57). It is built from every map in
#: the archive and published, so writing it into the checkout would put back
#: the one file every submission has to agree about. `--build-into` is how it
#: is produced; these two skip it.
NOT_COMMITTED = (FILENAME,)


def write_generated(root, files):
    """Write the generated files, returning the paths that actually changed."""
    changed = []
    for rel, data in sorted(files.items()):
        if rel in NOT_COMMITTED:
            continue
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

    The index is not among them: it is published rather than committed, so an
    archive with no catalog.json in it is correct rather than out of date.
    Reporting it stale is how `verify` on main failed the moment the file was
    removed, which is the check working from a premise that had changed.
    """
    out = []
    for rel, data in sorted(files.items()):
        if rel in NOT_COMMITTED:
            continue
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
