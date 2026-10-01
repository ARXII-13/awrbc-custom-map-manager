"""Where a map lives in the library, and how it gets there.

The archive path is three questions stacked: ``maps/<category>/<slug>/vN.json``.

* **category** is the player count, derived from the map. It is the only
  category that partitions - every map has exactly one - which is what makes it
  usable as a directory. Predeployed, naval and fog overlap, so they stay facts
  in the catalog and are queried rather than foldered.
* **slug** is the map's identity across revisions. It is what ``version: 2`` is
  a revision *of*.
* **vN.json** is one published revision.

The content hash is still the identity of a *file*, and the catalog records it.
The two answer different questions: the slug says which map, the hash says which
exact bytes. See docs/phase-3-archive.md, decisions #8 and #43.

Nothing here touches a filesystem or a network. These are pure rules, so the
CLI, the editor and the library's CI can agree on them without agreeing on
anything else - and so the submission pipeline is testable without a repo.
"""
import re
from dataclasses import dataclass, field

from . import identity
from .validate import ERROR, WARNING, Report

ROOT = "maps"

#: The archive holds 2- to 5-army maps. There is no matching minimum here:
#: validation already refuses a one-army map, so nothing ever reaches this
#: module needing a floor checked.
MAX_PLAYERS = 5

#: The one authored category. It is not a sixth player count - it is the bucket
#: for maps where player count is not the point, so a map goes in `special/`
#: *instead of* `3p/`. The catalog still records its real player count, so
#: nothing becomes unfindable by being filed here.
SPECIAL = "special"

#: Long enough to stay readable, short enough that the whole path survives
#: Windows' limit inside a deep checkout.
MAX_SLUG = 48

#: Device names Windows will not accept as a directory, whatever the extension.
#: A map called "Aux" or "Con" is a perfectly ordinary name and would otherwise
#: produce a repository nobody on Windows can check out.
RESERVED = frozenset(
    ["con", "prn", "aux", "nul"]
    + ["com%d" % i for i in range(1, 10)]
    + ["lpt%d" % i for i in range(1, 10)]
)

_SEPARATORS = re.compile(r"[\s_/\\]+")
_DISALLOWED = re.compile(r"[^a-z0-9-]+")
_RUNS = re.compile(r"-{2,}")

CATEGORY_RE = re.compile(r"^(?:[2-5]p|special)$")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
VERSION_RE = re.compile(r"^v([1-9][0-9]*)\.json$")


def slugify(name, fallback=""):
    """A map name reduced to a directory name.

    Lossy on purpose. The name is kept verbatim in the JSON; this only has to be
    stable, readable, and safe on every filesystem the archive is cloned onto.

    A name with nothing ASCII in it - ordinary for a Japanese or Russian map -
    slugs to empty. Rather than mangle it, fall back to what the caller offers,
    normally the content hash.
    """
    s = _SEPARATORS.sub("-", name.strip().lower())
    s = _RUNS.sub("-", _DISALLOWED.sub("", s)).strip("-")
    if len(s) > MAX_SLUG:
        # Cut at a word boundary when there is one near the limit, so a slug
        # does not end mid-word.
        s = s[:MAX_SLUG]
        if "-" in s[MAX_SLUG // 2:]:
            s = s.rsplit("-", 1)[0]
        s = s.strip("-")
    if s in RESERVED:
        s += "-map"
    return s or fallback


def map_hash(m, length=16):
    """The content hash, taken from the canonical form of the map.

    Always this, never ``identity.content_hash`` on a document that arrived from
    outside. Two files can describe the same map and hash differently - omitted
    flags, a team on a tile that cannot own one (decision #42), key order - and
    normalising is exactly what ``schema.to_json`` is for. Hashing the raw
    document instead makes de-duplication depend on how the submitter's editor
    happened to format its output, which is a dedupe that quietly does nothing.
    """
    from . import schema                        # local: schema imports model too
    return identity.content_hash(schema.to_json(m), length)


def slug_for(m):
    """The slug this map would claim, hash-backed when the name will not slug."""
    return slugify(m.name, map_hash(m, 8))


def category_for(m):
    """Which folder the map belongs in.

    The `special` tag is the single authored input to an otherwise derived
    decision, and it wins. Everything else follows from the terrain, so a map
    cannot be filed under a player count it does not have.
    """
    if SPECIAL in m.tags:
        return SPECIAL
    return "%dp" % len(m.teams)


def version_file(version):
    return "v%d.json" % version


def folder_for(m, slug=None):
    return "/".join([ROOT, category_for(m), slug or slug_for(m)])


def path_for(m, slug=None):
    """Where this map goes, as a repo-relative POSIX path."""
    return "/".join([folder_for(m, slug), version_file(m.version)])


@dataclass
class ArchivePath:
    category: str
    slug: str
    version: int

    @property
    def folder(self):
        """The map, without the revision - what a version is a version of."""
        return "/".join([ROOT, self.category, self.slug])

    def __str__(self):
        return "/".join([self.folder, version_file(self.version)])


def parse(path):
    """Read a path back, or raise ``ValueError`` naming the part that is wrong.

    CI runs this on every file a pull request adds, so the message is the whole
    of the feedback a contributor gets about their path.
    """
    parts = str(path).replace("\\", "/").strip("/").split("/")
    if len(parts) != 4 or parts[0] != ROOT:
        raise ValueError(
            "expected %s/<category>/<slug>/vN.json, got %r" % (ROOT, path))
    _, category, slug, filename = parts
    if not CATEGORY_RE.match(category):
        raise ValueError("%r is not a category; expected 2p-%dp or %s"
                         % (category, MAX_PLAYERS, SPECIAL))
    if not SLUG_RE.match(slug) or len(slug) > MAX_SLUG:
        raise ValueError(
            "%r is not a usable folder name; lowercase letters, digits and "
            "single hyphens, up to %d characters" % (slug, MAX_SLUG))
    match = VERSION_RE.match(filename)
    if not match:
        raise ValueError("%r is not a version file; expected v1.json, v2.json, "
                         "and so on" % filename)
    return ArchivePath(category, slug, int(match.group(1)))


def check_path(path, m):
    """Whether a map agrees with the path it was filed under.

    Separate from ``validate.check`` because it asks a question only the archive
    has: not "is this map sound" but "is it where it says it is". A map can be
    perfect and still be in the wrong folder.
    """
    r = Report()
    try:
        p = parse(path)
    except ValueError as e:
        r.add("path.shape", ERROR, str(e), "path")
        return r

    want = category_for(m)
    if p.category != want:
        if SPECIAL in (p.category, want):
            # Only the `special` tag can move a map off its player count, and
            # that tag is in the file - so this is the file and the path
            # disagreeing about a claim, not about a fact.
            carries = "does not carry" if p.category == SPECIAL else "carries"
            r.add("path.category", ERROR,
                  "path says %s but the file %s the %r tag"
                  % (p.category, carries, SPECIAL), "path")
        else:
            r.add("path.category", ERROR,
                  "path says %s; the map has %d armies, so it belongs in %s"
                  % (p.category, len(m.teams), want), "path")

    if p.version != m.version:
        r.add("path.version", ERROR,
              "file is named %s but declares version %d; the two have to agree "
              "because this file is read outside the archive too"
              % (version_file(p.version), m.version), "version")

    expected = slugify(m.name)
    if expected and p.slug != expected:
        # A warning, not an error. Renaming a map must not orphan its earlier
        # revisions, so a folder keeps the name it was first published under.
        r.add("path.slug", WARNING,
              "folder is %r but the map is called %r (slug %r); expected after "
              "a rename, otherwise check the folder"
              % (p.slug, m.name, expected), "path")
    return r


# --- Submission -------------------------------------------------------------
#
# Publishing asks one question the map cannot answer: is this a new map, or the
# next revision of one already here? Only the submitter knows. Two people can
# build a similar map and a name collision is not lineage, so claiming an
# existing folder is an explicit act - never inferred from the name.

NEW = "new"
REVISION = "revision"
DUPLICATE = "duplicate"
CONFLICT = "conflict"


@dataclass
class Placement:
    """The result of planning a submission: where it goes, and what it is."""
    kind: str
    reason: str
    path: str = ""
    folder: str = ""
    version: int = 0
    existing: str = ""
    findings: list = field(default_factory=list)

    @property
    def ok(self):
        return self.kind in (NEW, REVISION)


def _versions(entry):
    return sorted(v.get("version", 0) for v in (entry or {}).get("versions", []))


def find_by_hash(catalog, digest):
    """The path a hash already occupies, or "" - the archive's dedupe check."""
    for folder, entry in (catalog or {}).items():
        for v in entry.get("versions", []):
            if v.get("hash") == digest:
                return "/".join([folder, version_file(v.get("version", 1))])
    return ""


def plan(m, catalog=None, update=None, author=None):
    """Work out where a submitted map goes, without writing anything.

    Takes the map, not the document it arrived in, so that placement cannot
    depend on how the submitter formatted their JSON - see ``map_hash``.

    ``catalog`` is the archive's index, keyed by folder. ``update`` names the
    folder this claims to revise - ``"2p/daibi"`` or the full path - and is
    required to add a version to an existing map.

    The four outcomes are deliberate. ``DUPLICATE`` and ``CONFLICT`` are not
    errors in the map; they are the pipeline saying it will not guess.
    """
    catalog = catalog or {}
    digest = map_hash(m)

    # Identical bytes are already here, whatever they are called. This is also
    # what stops a v2 that changed nothing: the hash excludes name, author, tags
    # and version, so a revision with no actual edit lands right here.
    seen = find_by_hash(catalog, digest)
    if seen:
        return Placement(DUPLICATE,
                         "this map is already in the archive as %s" % seen,
                         existing=seen)

    if update:
        folder = update if update.startswith(ROOT + "/") else \
            "/".join([ROOT, update.strip("/")])
        folder = "/".join(folder.split("/")[:3])
        entry = catalog.get(folder)
        if entry is None:
            return Placement(CONFLICT,
                             "nothing at %s to revise; drop --update to "
                             "publish this as a new map" % folder)
        owner = entry.get("author")
        if author is not None and owner and owner != author:
            # `author` is whoever the caller vouches for, and how much that is
            # worth depends on who calls. The CLI can only pass the name the
            # file claims; the intake endpoint passes the Discord account that
            # actually signed in (decision #28). This layer takes it on trust
            # either way - it has no way to tell the two apart, and pretending
            # otherwise would put authorisation somewhere it cannot be enforced.
            return Placement(CONFLICT,
                             "%s was published by %r, not %r; a maintainer has "
                             "to approve a revision by someone else"
                             % (folder, owner, author))
        version = (_versions(entry)[-1] if entry.get("versions") else 0) + 1
        return Placement(REVISION,
                         "revision %d of %s" % (version, folder),
                         path="/".join([folder, version_file(version)]),
                         folder=folder, version=version)

    folder = folder_for(m)
    if folder in catalog:
        # Deliberately does not guess which of the two this is. The common case
        # is your own map, revised and submitted without saying so; the case
        # that matters is a stranger's. They read identically from here.
        return Placement(CONFLICT,
                         "%s already exists; pass --update %s if this is a new "
                         "version of it, or rename this map" % (folder, folder))
    return Placement(NEW, "new map at %s" % folder,
                     path="/".join([folder, version_file(1)]),
                     folder=folder, version=1)
