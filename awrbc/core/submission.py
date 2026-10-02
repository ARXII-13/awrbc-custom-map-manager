"""Turning an upload into a pull request.

Reached two ways: by ``awrbc prepare``, which is how the TypeScript intake
server asks this question, and directly by anything in Python.

That indirection is the point. The intake server is TypeScript and could have
reimplemented these checks; instead it shells out, so the rules - what a valid
map is, where it goes, whether it is already here, and above all the content
hash - exist exactly once. A second implementation of the hash would not throw
when it drifted. De-duplication would simply stop working and the archive would
fill with copies of the same map.

This module decides *where* a map goes and what the pull request says. It does
not invent a second opinion about what a valid map is; that is ``validate`` and
``archive``.

The browser is not trusted. It may have run the same checks for a nicer error
message; that is a convenience, not a gate.
"""
import json
import re
import zipfile

from . import archive, preview, schema, validate

#: Bigger than any real bundle - a 64x64 map is about 20 KB of JSON and the
#: preview a few hundred. Past this, something is wrong or hostile.
MAX_UPLOAD = 8 * 1024 * 1024
MAX_PREVIEW = 2 * 1024 * 1024

BRANCH_SAFE = re.compile(r"[^a-z0-9-]+")


class Rejected(Exception):
    """The submission will not be accepted, and the reason is the submitter's
    to act on. Carries findings so the caller can show them all at once rather
    than one per round trip."""

    def __init__(self, message, findings=None, code="rejected"):
        self.findings = findings or []
        self.code = code
        super().__init__(message)


def read_upload(blob, filename=""):
    """Unpack what the browser sent: a bundle zip, or a bare map JSON.

    Returns ``(document, preview_bytes_or_None)``.
    """
    if len(blob) > MAX_UPLOAD:
        raise Rejected("that upload is %d bytes; the limit is %d"
                       % (len(blob), MAX_UPLOAD), code="too-large")

    if blob[:2] == b"PK":
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                names = z.namelist()
                entry = next((n for n in names
                              if n.rsplit("/", 1)[-1] == "map.json"), None)
                if entry is None:
                    raise Rejected("that zip has no map.json in it")
                stem = entry[:-len("map.json")]
                shot = stem + "preview.png"
                # Read the preview's declared size before reading the preview:
                # a zip bomb is a small file that becomes a large one.
                if shot in names:
                    if z.getinfo(shot).file_size > MAX_PREVIEW:
                        raise Rejected("that preview is too large")
                    image = z.read(shot)
                else:
                    image = None
                return json.loads(z.read(entry).decode("utf-8")), image
        except zipfile.BadZipFile:
            raise Rejected("that file is not a readable zip")
        except UnicodeDecodeError:
            raise Rejected("map.json is not valid UTF-8")
        except json.JSONDecodeError as exc:
            raise Rejected("map.json is not valid JSON: %s" % exc)

    try:
        return json.loads(blob.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Rejected("that is neither a bundle zip nor a map JSON")


def _findings(report):
    return [{"code": f.code, "severity": f.severity, "message": f.message}
            for f in report.findings]


def prepare(blob, catalog, author, update=None, filename=""):
    """Check an upload and work out what would be committed.

    Returns a dict describing the submission. Does not talk to GitHub, so it is
    the whole of the decision and can be tested without a network.
    """
    doc, image = read_upload(blob, filename)

    try:
        m = schema.from_json(doc)
    except Exception as exc:                            # noqa: BLE001
        raise Rejected("that map cannot be read: %s" % exc)

    report = validate.check(m)
    if image is not None:
        for f in preview.check_png(image, m).findings:
            report.add(f.code, f.severity, f.message, f.path)
    if report.errors:
        raise Rejected("that map did not pass validation",
                       _findings(report), code="invalid")

    # The author is the Discord account that signed in, not whatever the file
    # claims. A file is a claim; a session is not.
    placement = archive.plan(m, catalog, update=update, author=author["id"])
    if not placement.ok:
        raise Rejected(placement.reason, code=placement.kind)

    m.version = placement.version
    built = schema.build_document(m, author=author["username"])

    files = {placement.path: (json.dumps(built, indent=1, ensure_ascii=False)
                              + "\n").encode("utf-8")}
    if image is not None:
        files[archive.version_path(
            placement.folder,
            placement.version).rsplit("/", 1)[0] + "/" +
            preview.preview_file(placement.version)] = image

    return {
        "placement": placement,
        "files": files,
        "map": m,
        "document": built,
        "warnings": [f for f in _findings(report) if f["severity"] != "error"],
        "has_preview": image is not None,
    }


def branch_name(placement, author):
    """A branch per submission, readable in a list of pull requests."""
    slug = BRANCH_SAFE.sub("-", placement.folder.rsplit("/", 1)[-1].lower())
    who = BRANCH_SAFE.sub("-", (author.get("username") or "anon").lower())
    return "submit/%s-v%d-%s" % (slug.strip("-") or "map",
                                 placement.version, who.strip("-") or "anon")


def pull_request_text(prepared, author):
    """What a reviewer sees. Written for someone deciding in thirty seconds."""
    p = prepared["placement"]
    m = prepared["map"]
    verb = "Add" if p.kind == archive.NEW else "Update"
    title = "%s %s%s" % (verb, m.name or p.slug,
                         "" if p.version == 1 else " to v%d" % p.version)

    facts = ["%d players" % len(m.teams), "%dx%d" % (m.cols, m.rows)]
    if any(True for _ in m.iter_units()):
        facts.append("predeployed")

    lines = [
        "Submitted through the map editor by **%s** (Discord `%s`)."
        % (author.get("username"), author.get("id")),
        "",
        "| | |",
        "|---|---|",
        "| Map | %s |" % (m.name or "(unnamed)"),
        "| Author | %s |" % prepared["document"].get("author", "anonymous"),
        "| Path | `%s` |" % p.path,
        "| What it is | %s |" % ", ".join(facts),
        "| Preview | %s |" % ("included" if prepared["has_preview"]
                              else "**none** - the map will have no picture"),
        "",
    ]
    if prepared["warnings"]:
        lines += ["Validation warnings, none of them blocking:", ""]
        lines += ["- `%s` %s" % (w["code"], w["message"])
                  for w in prepared["warnings"]]
        lines += [""]
    lines += [
        "The contributor confirmed at upload that this is their own work and "
        "licensed it under CC BY 4.0.",
        "",
        "<sub>Opened by the intake bot. CI checks the same rules "
        "`awrbc publish` applies.</sub>",
    ]
    return title, "\n".join(lines)
