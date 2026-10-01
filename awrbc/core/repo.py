"""Reading the published archive.

The library is a public git repository, so a client needs no API and no
account: the catalog and every map file are ordinary HTTPS GETs. That is the
whole reason git was chosen to hold map content (decision #10), and it means
this module is a cache and a URL builder rather than a protocol.

Nothing here writes to a save or to the archive. ``publish`` submits; this
fetches.

Offline is a normal state, not an error to hide. A stale cache is served with a
warning rather than nothing, because a map you downloaded yesterday is still a
map you can play today.
"""
import json
import os
import time
import urllib.error
import urllib.request

from . import archive
from .errors import AwrbcError

#: Where the published archive lives. Overridable so a fork, a branch, or a
#: local checkout can be used instead - which is also how this gets tested
#: without touching the network.
DEFAULT_BASE = ("https://raw.githubusercontent.com/"
                "ARXII-13/awrbc-custom-map-library/main")

CATALOG = "catalog.json"

#: How long a cached catalog is used without asking again. The archive changes
#: when somebody merges a pull request, so an hour is generous for freshness
#: and kind to the network on repeated searches.
MAX_AGE = 3600

TIMEOUT = 20


class ArchiveUnreachable(AwrbcError):
    """The archive could not be fetched and no usable cache exists."""

    exit_code = 3


class MapNotInArchive(AwrbcError):
    """No map in the catalog matches what was asked for."""

    exit_code = 1


def cache_root():
    base = os.environ.get("AWRBC_CACHE_DIR")
    if base:
        return base
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "awrbc", "cache")
    return os.path.join(os.path.expanduser("~"), ".cache", "awrbc")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "awrbc"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def fetch_catalog(base=DEFAULT_BASE, max_age=MAX_AGE, refresh=False):
    """The archive index. Returns ``(maps, staleness)``.

    ``staleness`` is None when the catalog was just fetched, or the cache's age
    in seconds when the network failed and a cached copy was used instead. The
    caller decides whether to mention it; this does not print.
    """
    path = os.path.join(cache_root(), CATALOG)
    age = None
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if not refresh and age < max_age:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh).get("maps", {}), None

    try:
        raw = _get(base.rstrip("/") + "/" + CATALOG)
    except (urllib.error.URLError, OSError) as exc:
        if age is None:
            raise ArchiveUnreachable(
                "could not reach the archive at %s (%s).\n"
                "Pass --library with a local checkout to work offline."
                % (base, exc))
        # Stale beats nothing.
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("maps", {}), age

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(raw)
    return json.loads(raw.decode("utf-8")).get("maps", {}), None


def load_local(root):
    """The catalog from a checkout on disk, for working offline."""
    path = os.path.join(root, CATALOG)
    if not os.path.exists(path):
        raise ArchiveUnreachable("no %s in %s" % (CATALOG, root))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("maps", {}), None


def _terms(entry, folder):
    """Everything a query is matched against, lowercased."""
    latest = entry.get("versions", [{}])[-1]
    bits = [folder, entry.get("name", ""), entry.get("author", ""),
            entry.get("category", ""), entry.get("slug", ""),
            "%dp" % latest.get("players", 0),
            "%dx%d" % (latest.get("cols", 0), latest.get("rows", 0))]
    bits += [k for k in ("predeployed", "navy", "structures", "fog")
             if latest.get(k)]
    bits += latest.get("tags", [])
    return " ".join(str(b) for b in bits).lower()


def search(catalog, query=""):
    """Folders whose text matches every word in the query.

    Every word, not any: "4p fog" should narrow rather than widen, which is
    what someone typing a second word is asking for.
    """
    words = [w for w in query.lower().split() if w]
    out = []
    for folder, entry in sorted(catalog.items()):
        if all(w in _terms(entry, folder) for w in words):
            out.append((folder, entry))
    return out


def resolve(catalog, ref):
    """Turn what somebody typed into ``(folder, entry, version)``.

    Accepts a slug (``daibi``), a qualified folder (``2p/daibi`` or
    ``maps/2p/daibi``), and either with a version (``daibi@v2``). A bare slug is
    the common case and only ambiguous if two categories hold the same name,
    which the archive's own path rules prevent.
    """
    ref = str(ref).strip()
    version = None
    if "@" in ref:
        ref, _, tail = ref.partition("@")
        tail = tail.lstrip("vV")
        if not tail.isdigit():
            raise MapNotInArchive("%r is not a version; try @v2" % tail)
        version = int(tail)

    ref = ref.strip("/")
    want = ref if ref.startswith(archive.ROOT + "/") else None
    matches = []
    for folder, entry in sorted(catalog.items()):
        tail = folder[len(archive.ROOT) + 1:]          # "2p/daibi"
        if folder == want or tail == ref or entry.get("slug") == ref:
            matches.append((folder, entry))

    if not matches:
        raise MapNotInArchive(
            "no map called %r in the archive. `awrbc search %s` to look."
            % (ref, ref))
    if len(matches) > 1:
        names = ", ".join(f for f, _ in matches)
        raise MapNotInArchive(
            "%r matches more than one map: %s. Use the longer form."
            % (ref, names))

    folder, entry = matches[0]
    versions = sorted(v["version"] for v in entry.get("versions", []))
    if not versions:
        raise MapNotInArchive("%s has no published versions" % folder)
    if version is None:
        version = versions[-1]
    elif version not in versions:
        raise MapNotInArchive(
            "%s has no v%d; it has %s"
            % (folder, version, ", ".join("v%d" % v for v in versions)))
    return folder, entry, version


def fetch_map(folder, version, base=DEFAULT_BASE, root=None):
    """One map document, from the network or a local checkout."""
    rel = archive.version_path(folder, version)
    if root:
        with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
            return json.load(fh)
    try:
        return json.loads(_get(base.rstrip("/") + "/" + rel).decode("utf-8"))
    except (urllib.error.URLError, OSError) as exc:
        raise ArchiveUnreachable("could not fetch %s (%s)" % (rel, exc))
