"""Command line entry point.

All presentation lives here. core returns values and raises typed errors; this
module is the only place that formats text, picks exit codes, or writes to a
stream.
"""
import argparse
import json
import os
import re
import subprocess
import sys

from ..core import (archive, catalog, preview, repo, schema, submission,
                    validate)
from ..core.errors import (AwrbcError, MapNotFound, PublishRefused,
                           ValidationFailed)

EXIT_OK = 0
EXIT_USAGE = 1


def _safe_name(text, fallback):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-")
    return slug[:60] or fallback


def _read_submission(path):
    """Read a map from a .json file, a bundle directory, or a .zip of one.

    Returns ``(document, preview_bytes_or_None)``. The editor's bundle carries a
    preview drawn by its own renderer, which is a better picture than anything
    this package can produce - it has the icons, and Python does not.
    """
    if os.path.isdir(path):
        with open(os.path.join(path, "map.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        shot = os.path.join(path, "preview.png")
        if os.path.exists(shot):
            with open(shot, "rb") as fh:
                return doc, fh.read()
        return doc, None

    if path.lower().endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            # Tolerate a zip that wraps its contents in a folder, which is what
            # a round trip through a file manager usually produces.
            entry = next((n for n in names
                          if n.rsplit("/", 1)[-1] == "map.json"), None)
            if entry is None:
                raise MapNotFound("%s has no map.json in it" % path)
            doc = json.loads(z.read(entry).decode("utf-8"))
            stem = entry[:-len("map.json")]
            shot = stem + "preview.png"
            return doc, (z.read(shot) if shot in names else None)

    with open(path, encoding="utf-8") as fh:
        return json.load(fh), None


def cmd_publish(args, out):
    """Place a map in a local checkout of the library.

    Validation is blocking here, unlike export. A work-in-progress map is a
    reasonable thing to have on disk and an unreasonable thing to put in a
    public archive.
    """
    root = args.library or os.environ.get("AWRBC_LIBRARY")
    if not root:
        raise MapNotFound(
            "give --library pointing at a checkout of awrbc-custom-map-library, "
            "or set AWRBC_LIBRARY")
    if not os.path.isdir(root):
        raise MapNotFound("no library checkout at %s" % root)

    doc, supplied = _read_submission(args.file)
    m = schema.from_json(doc)

    report = validate.check(m)
    if supplied:
        # The image is untrusted input being copied into a public repository,
        # so it is checked before it gets there rather than after.
        for f in preview.check_png(supplied, m).findings:
            report.add(f.code, f.severity, f.message, f.path)
    if report.errors:
        for f in report.errors:
            sys.stderr.write("error: %-18s %s\n" % (f.code, f.message))
        raise ValidationFailed(report)

    index = catalog.load(root) if not args.rescan else catalog.build(root)[0]
    placement = archive.plan(m, index, update=args.update,
                             author=doc.get("author"))
    if not placement.ok:
        raise PublishRefused(placement)

    # The archive assigns the version, so the file has to be told: `version` is
    # read outside the archive too, and a file that disagrees with its own path
    # is what CI rejects.
    m.version = placement.version
    built = schema.build_document(m, author=doc.get("author"))
    target = os.path.join(root, *placement.path.split("/"))

    result = {"kind": placement.kind, "path": placement.path,
              "version": placement.version, "id": built["id"],
              "warnings": [vars(f) for f in report.warnings]}

    if args.dry_run:
        result["dryRun"] = True
        if args.json:
            json.dump(result, out, indent=2)
            out.write("\n")
        else:
            out.write("dry run: would write %s\n" % placement.path)
            _write_warnings(out, report)
        return EXIT_OK

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(built, fh, indent=1, ensure_ascii=False)
        fh.write("\n")

    # The preview goes down with the map rather than waiting for a catalog run,
    # so what the contributor pushes is what a reviewer sees in the pull
    # request. `awrbc catalog` regenerates it along with everything else.
    if supplied:
        shot = os.path.join(os.path.dirname(target),
                            preview.preview_file(placement.version))
        with open(shot, "wb") as fh:
            fh.write(supplied)
        result["preview"] = "/".join([placement.folder,
                                      preview.preview_file(placement.version)])

    if args.json:
        json.dump(result, out, indent=2)
        out.write("\n")
        return EXIT_OK

    out.write("%s %s\n" % ("added" if placement.kind == archive.NEW
                           else "revised", placement.path))
    out.write("  %-24s id %s\n" % (m.name[:24], built["id"]))
    _write_warnings(out, report)
    if not supplied:
        # Not an error - a map without a picture is still a playable map - but
        # it will sit in the archive with nothing to look at, and the person
        # publishing it is the only one who can fix that.
        out.write("  no preview   open the map in the editor and use Export "
                  "bundle to include one\n")
    # Phase 3 stops here: the contributor runs these. The intake endpoint
    # (decision #28) does the same thing with a token, so nobody has to.
    out.write("\nTo submit it:\n")
    out.write("  cd %s\n" % root)
    out.write("  git checkout -b %s\n" % placement.folder.replace("maps/", ""))
    # Add the folder, not the file: the preview sits beside the JSON and a
    # branch pushed without it shows a broken image in the pull request.
    message = ("'Add %s'" % m.name if placement.kind == archive.NEW
               else "'Update %s to v%d'" % (m.name, placement.version))
    out.write("  git add %s && git commit -m %s\n"
              % (placement.folder, message))
    out.write("  git push -u origin HEAD\n")
    return EXIT_OK


def _write_warnings(out, report):
    for f in report.warnings:
        out.write("  warning %-18s %s\n" % (f.code, f.message))


def cmd_verify(args, out):
    """Check every map in a library checkout. What CI runs on a pull request.

    Deliberately one command rather than a workflow full of shell: the rules are
    the same ones `publish` applies, they are covered by this package's tests,
    and a contributor can run exactly what CI will run before they push.

    `--changed` adds the rules that are about a submission rather than a map -
    one map per pull request, and no edits to generated files.
    """
    root = args.library or os.environ.get("AWRBC_LIBRARY")
    if not root or not os.path.isdir(root):
        raise MapNotFound("give --library pointing at a library checkout")

    problems = []

    def fail(path, message):
        # `catalog.regenerate` checks previews too, so the same bad image can
        # arrive twice. A contributor reading CI output should see each problem
        # once.
        entry = {"path": path, "error": message}
        if entry not in problems:
            problems.append(entry)

    checked, seen_hashes = 0, {}
    for rel in catalog.map_files(root):
        checked += 1
        try:
            with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
                doc = json.load(fh)
            m = schema.from_json(doc)
        except Exception as exc:                        # noqa: BLE001
            fail(rel, str(exc))
            continue

        for f in validate.check(m).errors:
            fail(rel, "%s: %s" % (f.code, f.message))
        for f in archive.check_path(rel, m).errors:
            fail(rel, "%s: %s" % (f.code, f.message))

        digest = archive.map_hash(m)
        if digest in seen_hashes:
            fail(rel, "duplicate: identical content to %s" % seen_hashes[digest])
        else:
            seen_hashes[digest] = rel

        try:
            p = archive.parse(rel)
            shot = os.path.join(root, *p.folder.split("/"),
                                preview.preview_file(p.version))
            if os.path.exists(shot):
                with open(shot, "rb") as fh:
                    for f in preview.check_png(fh.read(), m).errors:
                        fail(p.folder + "/" + preview.preview_file(p.version),
                             "%s: %s" % (f.code, f.message))
        except ValueError:
            pass                        # check_path already reported the path

    # Generated files have to be in step, or the archive shows one thing and
    # serves another.
    files, parse_problems = catalog.regenerate(root,
                                               keep_dates_from=catalog.load(root))
    for p in parse_problems:
        fail(p["path"], p["error"])
    for rel in catalog.stale(root, files):
        fail(rel, "generated file is out of date; run `awrbc catalog`")

    if args.changed is not None:
        for p in _submission_rules(args.changed):
            fail(p["path"], p["error"])

    if args.json:
        json.dump({"maps": checked, "problems": problems}, out, indent=2)
        out.write("\n")
    else:
        for p in problems:
            out.write("  %s\n    %s\n" % (p["path"], p["error"]))
        out.write("%d map%s checked, %d problem%s\n"
                  % (checked, "" if checked == 1 else "s",
                     len(problems), "" if len(problems) == 1 else "s"))
    return EXIT_OK if not problems else ValidationFailed.exit_code


#: Files CI generates. A pull request that edits one is either confused or
#: trying to make the index disagree with the maps.
GENERATED = ("catalog.json", "README.md")


def _submission_rules(changed):
    """Rules about a pull request, not about a map."""
    out = []
    paths = [c.strip().replace("\\", "/") for c in changed if c.strip()]

    maps = sorted({p.rsplit("/", 1)[0] for p in paths
                   if p.startswith(archive.ROOT + "/") and p.endswith(".json")})
    if len(maps) > 1:
        out.append({"path": ", ".join(maps),
                    "error": "one map per pull request; this touches %d"
                             % len(maps)})

    for p in paths:
        base = p.rsplit("/", 1)[-1]
        if base in GENERATED or p == "catalog.json":
            out.append({"path": p,
                        "error": "generated by `awrbc catalog` on merge; "
                                 "remove it from this pull request"})
        elif not p.startswith(archive.ROOT + "/") and not p.startswith("."):
            out.append({"path": p,
                        "error": "a map submission should only touch %s/"
                                 % archive.ROOT})
    return out


def cmd_catalog(args, out):
    """Regenerate the catalog, previews and folder READMEs.

    What CI runs on merge, and with --check what it runs on a pull request: the
    generated files are committed, so they can be out of step with the maps
    beside them and something has to notice.
    """
    root = args.library or os.environ.get("AWRBC_LIBRARY")
    if not root or not os.path.isdir(root):
        raise MapNotFound("give --library pointing at a library checkout")

    files, problems = catalog.regenerate(root,
                                         keep_dates_from=catalog.load(root))
    drifted = catalog.stale(root, files) if args.check else []
    written = [] if args.check else catalog.write_generated(root, files)
    count = len(catalog.load(root)) if args.check else \
        len(json.loads(files[catalog.FILENAME].decode("utf-8"))["maps"])

    if args.json:
        json.dump({"count": count, "problems": problems,
                   "stale": drifted, "written": written}, out, indent=2)
        out.write("\n")
    else:
        for p in problems:
            out.write("  unreadable %s: %s\n" % (p["path"], p["error"]))
        for rel in drifted:
            out.write("  stale      %s\n" % rel)
        if written:
            out.write("  wrote %d file%s\n"
                      % (len(written), "" if len(written) == 1 else "s"))
        out.write("%d map%s in the catalog%s\n"
                  % (count, "" if count == 1 else "s",
                     " (checked, not written)" if args.check else ""))

    # One bad file does not make the catalog unbuildable, but it does mean the
    # archive holds something nobody can read. Drift is the same severity: a
    # preview that no longer matches its map is a lie in the browser.
    if problems or drifted:
        return ValidationFailed.exit_code
    return EXIT_OK


def _catalog_for(args):
    """The archive index, from a local checkout if given, else the network."""
    if getattr(args, "library", None):
        return repo.load_local(args.library)
    return repo.fetch_catalog(args.base, refresh=getattr(args, "refresh", False))


def _warn_stale(out, stale):
    if stale is None:
        return
    hours = stale / 3600.0
    sys.stderr.write(
        "warning: the archive is unreachable; using a copy cached %s ago\n"
        % ("%.0f minutes" % (stale / 60.0) if hours < 1
           else "%.0f hours" % hours))


def _facts(entry):
    v = entry.get("versions", [{}])[-1]
    bits = ["%dp" % v.get("players", 0),
            "%dx%d" % (v.get("cols", 0), v.get("rows", 0))]
    bits += [k for k in ("predeployed", "navy", "structures", "fog")
             if v.get(k)]
    bits += list(v.get("tags", []))
    return bits


def cmd_prepare(args, out):
    """Decide what a submission would become. Writes nothing, anywhere.

    This is the contract the TypeScript intake server calls across. It exists
    so that server never has to reimplement a rule - above all the content
    hash, which would not raise when it drifted, it would just quietly stop
    de-duplicating.

    Reads the bundle from a path or from stdin, and answers in JSON on stdout:
    either a complete description of the branch, the commit message and the
    files to write, or a refusal with the findings behind it. File contents are
    base64 because a preview is binary and this has to survive JSON.
    """
    import base64

    if args.file == "-":
        stdin = getattr(sys.stdin, "buffer", sys.stdin)
        blob = stdin.read()
    else:
        with open(args.file, "rb") as fh:
            blob = fh.read()

    author = {"id": args.author_id or "", "username": args.author_name or ""}

    if args.catalog:
        with open(args.catalog, encoding="utf-8") as fh:
            index = json.load(fh).get("maps", {})
    elif args.library:
        index, _ = repo.load_local(args.library)
    else:
        # --refresh matters most here: the server asks whether a submission
        # duplicates something, and an hour-stale catalog answers that wrong.
        index, _ = repo.fetch_catalog(args.base, refresh=args.refresh)

    try:
        prepared = submission.prepare(blob, index, author, update=args.update)
    except submission.Rejected as exc:
        json.dump({"ok": False, "code": exc.code, "error": str(exc),
                   "folder": exc.folder, "findings": exc.findings},
                  out, indent=2)
        out.write("\n")
        # A refusal is this command working, not failing - the caller reads
        # `ok`. A non-zero exit is reserved for the command itself breaking.
        return EXIT_OK

    placement = prepared["placement"]
    title, body = submission.pull_request_text(prepared, author)
    json.dump({
        "ok": True,
        "kind": placement.kind,
        "path": placement.path,
        "folder": placement.folder,
        "version": placement.version,
        "branch": submission.branch_name(placement, author),
        "title": title,
        "body": body,
        "files": {p: base64.b64encode(c).decode("ascii")
                  for p, c in prepared["files"].items()},
        "warnings": prepared["warnings"],
        "hasPreview": prepared["has_preview"],
    }, out, indent=2)
    out.write("\n")
    return EXIT_OK


def cmd_search(args, out):
    index, stale = _catalog_for(args)
    _warn_stale(out, stale)
    found = repo.search(index, " ".join(args.query or []))

    if args.json:
        json.dump({"query": " ".join(args.query or []),
                   "results": [{"folder": f, "name": e.get("name"),
                                "author": e.get("author"),
                                "slug": e.get("slug"),
                                "versions": [v["version"]
                                             for v in e.get("versions", [])],
                                "facts": _facts(e)}
                               for f, e in found]}, out, indent=2)
        out.write("\n")
        return EXIT_OK

    if not found:
        out.write("nothing matched. `awrbc search` with no words lists "
                  "everything.\n")
        return EXIT_OK
    out.write("  %-20s %-18s %-22s %s\n"
              % ("slug", "name", "by", "what it is"))
    for folder, entry in found:
        out.write("  %-20s %-18s %-22s %s\n"
                  % (entry.get("slug", "")[:20], (entry.get("name") or "")[:18],
                     (entry.get("author") or "")[:22],
                     ", ".join(_facts(entry))))
    out.write("\n%d map%s. `awrbc show <slug>` for one.\n"
              % (len(found), "" if len(found) == 1 else "s"))
    return EXIT_OK


def cmd_show(args, out):
    index, stale = _catalog_for(args)
    _warn_stale(out, stale)
    folder, entry, version = repo.resolve(index, args.slug)
    versions = sorted(entry.get("versions", []), key=lambda v: v["version"],
                      reverse=True)

    if args.json:
        json.dump({"folder": folder, "name": entry.get("name"),
                   "author": entry.get("author"), "latest": version,
                   "versions": versions}, out, indent=2)
        out.write("\n")
        return EXIT_OK

    out.write("%s\n" % (entry.get("name") or entry.get("slug")))
    out.write("  by %s\n" % (entry.get("author") or "anonymous"))
    out.write("  %s\n" % ", ".join(_facts(entry)))
    out.write("  %s\n\n" % folder)
    out.write("  %-6s %-12s %s\n" % ("", "added", "id"))
    for v in versions:
        out.write("  %-6s %-12s %s%s\n"
                  % ("v%d" % v["version"], v.get("added", ""),
                     v.get("hash", ""),
                     "   <- latest" if v["version"] == version else ""))
    out.write("\nawrbc import %s\n" % (entry.get("slug") or folder))
    return EXIT_OK


def _common(suppress):
    """Global flags, accepted before OR after the subcommand.

    The subcommand copies use SUPPRESS: with a real default, an unset flag on the
    subparser silently overwrites the value already parsed from before the
    subcommand. That bug sent a write to the wrong save file.
    """
    c = argparse.ArgumentParser(add_help=False)
    # --save-dir and --profile went with the save editor; nothing here opens
    # a save.
    c.add_argument("--json", action="store_true",
                   default=argparse.SUPPRESS if suppress else False,
                   help="emit structured output")
    return c


def build_parser():
    common = _common(suppress=True)
    p = argparse.ArgumentParser(
        prog="awrbc", parents=[_common(suppress=False)],
        description="Custom map tools for Advance Wars 1+2: Re-Boot Camp. "
                    "Not affiliated with Nintendo or WayForward.")
    sub = p.add_subparsers(dest="command")

    def archive_flags(p):
        """Where to read the published archive from."""
        p.add_argument("--base", default=repo.DEFAULT_BASE,
                       help="archive URL (default: the public library)")
        p.add_argument("--library",
                       help="a local checkout to read instead of the network")
        p.add_argument("--refresh", action="store_true",
                       help="ignore the cached catalog")
        return p


    pub = sub.add_parser("publish", parents=[common],
                         help="place a map in a library checkout")
    pub.add_argument("file", help="an Export bundle zip, a bundle folder, or a bare map JSON")
    pub.add_argument("--library", help="checkout of awrbc-custom-map-library "
                                       "(or set AWRBC_LIBRARY)")
    pub.add_argument("--update", metavar="FOLDER",
                     help="publish as the next version of an existing map, "
                          "e.g. 2p/daibi")
    pub.add_argument("--rescan", action="store_true",
                     help="read the map files instead of catalog.json")
    pub.add_argument("--dry-run", action="store_true",
                     help="say where it would go, write nothing")

    ver = sub.add_parser("verify", parents=[common],
                         help="check every map in a library checkout")
    ver.add_argument("--library", help="checkout of awrbc-custom-map-library")
    ver.add_argument("--changed", nargs="*", default=None, metavar="PATH",
                     help="files this submission touches, for the "
                          "one-map-per-pull-request rules")

    cat = sub.add_parser("catalog", parents=[common],
                         help="regenerate catalog.json from the map files")
    cat.add_argument("--library", help="checkout of awrbc-custom-map-library")
    cat.add_argument("--check", action="store_true",
                     help="report without writing")

    se = archive_flags(sub.add_parser("search", parents=[common],
                                      help="find maps in the archive"))
    se.add_argument("query", nargs="*",
                    help="words to match; all of them must match")

    sh = archive_flags(sub.add_parser("show", parents=[common],
                                      help="details for one map"))
    sh.add_argument("slug", help="slug, 2p/slug, or slug@v2")

    pre = archive_flags(sub.add_parser(
        "prepare", parents=[common],
        help="decide what a submission would become, as JSON (writes nothing)"))
    pre.add_argument("file", help="bundle zip or map JSON; - for stdin")
    pre.add_argument("--author-id", help="the submitter's account id")
    pre.add_argument("--author-name", help="the name to publish")
    pre.add_argument("--update", metavar="FOLDER",
                     help="publish as the next version of an existing map")
    pre.add_argument("--catalog", help="a catalog.json to read instead")



    return p


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(out)
        return EXIT_USAGE

    handlers = {"publish": cmd_publish, "catalog": cmd_catalog,
                "verify": cmd_verify, "search": cmd_search,
                "show": cmd_show, "prepare": cmd_prepare}
    try:
        return handlers[args.command](args, out)
    except PublishRefused as exc:
        # Not "your map is broken" - the archive has something to say about
        # where it would go. The reason is the whole message.
        sys.stderr.write("refused: %s\n" % exc)
        return exc.exit_code
    except AwrbcError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
