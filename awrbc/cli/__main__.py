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

from ..core import (archive, backup, catalog, identify, locate, preview,
                    savefile, schema, validate)
from ..core.errors import (AwrbcError, MapNotFound, PublishRefused, SaveInUse,
                           SaveNotFound, ValidationFailed)

EXIT_OK = 0
EXIT_USAGE = 1


def _resolve(args):
    """Pick the save to operate on, or raise SaveNotFound with a useful message."""
    candidates = locate.find_saves(args.save_dir)
    if not candidates:
        where = args.save_dir or "the default Ryujinx locations"
        raise SaveNotFound(
            "no save data found in %s.\n"
            "Pass --save-dir pointing at a Ryujinx data folder, a JKSV dump, or "
            "a maps file directly." % where)
    chosen = locate.select(candidates, args.profile)
    if chosen is None:
        have = ", ".join(str(c.profile) for c in candidates)
        raise SaveNotFound("no profile %r; found: %s" % (args.profile, have))
    return chosen, candidates


def _game_running():
    """Is the title running? It flushes its own copy over external writes.

    Only a loaded game holds the save; the emulator sitting open with no title
    is fine, so this must not refuse merely because Ryujinx is on screen.

    Asks the platform's own process list. This used to shell out to `tasklist`
    unconditionally, which meant that on macOS and Linux the command did not
    exist, the exception was swallowed, and the check silently answered "not
    running" every time - turning a guard against the emulator overwriting our
    write into a no-op on two of the three platforms.

    It still answers False when it cannot tell, because refusing to write
    because `ps` is missing would be worse than the risk. That is a deliberate
    fail-open, not an oversight.
    """
    if os.environ.get("AWRBC_SKIP_PROCESS_CHECK"):
        return False
    if sys.platform == "win32":
        argv = ["tasklist"]
    else:
        argv = ["ps", "-A", "-o", "comm="]
    try:
        out = subprocess.run(argv, capture_output=True, text=True,
                             timeout=10).stdout.lower()
    except Exception:                               # noqa: BLE001
        return False
    return "ryujinx" in out


def cmd_doctor(args, out):
    candidates = locate.find_saves(args.save_dir)
    result = {"candidates": [], "ok": False}
    if not candidates:
        where = args.save_dir or "default Ryujinx locations"
        if args.json:
            json.dump(result, out, indent=2)
            out.write("\n")
        else:
            out.write("No save data found in %s.\n\n" % where)
            out.write("Looked in:\n")
            for r in locate.ryujinx_roots():
                out.write("  %s\n" % r)
            out.write("\nUse --save-dir to point at a Ryujinx folder, a JKSV "
                      "dump, or a maps file.\n")
        return SaveNotFound.exit_code

    for c in candidates:
        row = {"path": c.path, "profile": c.profile, "source": c.source,
               "size": c.size, "readable": False}
        try:
            doc = savefile.read(c.path)
            row.update(readable=True, save_version=doc.save_version,
                       maps=len(doc.maps),
                       titleId=None if doc.title_id is None
                       else "%016X" % doc.title_id,
                       game=identify.TITLE_NAME)
        except AwrbcError as exc:
            row["error"] = str(exc)
        result["candidates"].append(row)
    result["ok"] = any(r["readable"] for r in result["candidates"])

    if args.json:
        json.dump(result, out, indent=2)
        out.write("\n")
        return EXIT_OK if result["ok"] else SaveNotFound.exit_code

    out.write("Found %d save%s:\n\n" % (len(candidates),
                                        "" if len(candidates) == 1 else "s"))
    for r in result["candidates"]:
        out.write("  %s\n" % r["path"])
        out.write("    source   %s%s\n" % (
            r["source"],
            "" if r["profile"] is None else ", profile %s" % r["profile"]))
        out.write("    size     %s bytes\n" % format(r["size"], ","))
        if r["readable"]:
            out.write("    game     %s\n" % r["game"])
            out.write("    title id %s\n"
                      % (r["titleId"] or "not present (bare SaveData dump)"))
            out.write("    version  %s (supported)\n" % r["save_version"])
            out.write("    maps     %d\n" % r["maps"])
        else:
            out.write("    ERROR    %s\n" % r.get("error"))
        out.write("\n")
    return EXIT_OK if result["ok"] else SaveNotFound.exit_code


def cmd_list(args, out):
    chosen, _ = _resolve(args)
    doc = savefile.read(chosen.path)

    rows = []
    for i, m in enumerate(doc.maps):
        counts = m.per_team()
        rows.append({
            "index": i, "name": m.name, "slot": m.slot, "creator": m.creator,
            "cols": m.cols, "rows": m.rows, "fog": m.fog,
            "teams": m.teams, "playable": m.is_playable,
            "units": sum(c.units for c in counts.values()),
            "perTeam": {str(t): vars(c) for t, c in counts.items()},
        })

    if args.json:
        json.dump({"path": chosen.path, "saveVersion": doc.save_version,
                   "maps": rows}, out, indent=2)
        out.write("\n")
        return EXIT_OK

    if not rows:
        out.write("No custom maps in %s\n" % chosen.path)
        return EXIT_OK

    out.write("%s  (%s)\n\n" % (chosen.path, chosen.label))
    out.write("  #  %-24s %-7s %-6s %-8s %s\n"
              % ("name", "size", "teams", "units", "playable"))
    for r in rows:
        out.write("  %-2d %-24s %-7s %-6s %-8s %s\n" % (
            r["index"], r["name"][:24], "%dx%d" % (r["cols"], r["rows"]),
            len(r["teams"]), r["units"], "yes" if r["playable"] else "NO"))
    out.write("\n%d map%s\n" % (len(rows), "" if len(rows) == 1 else "s"))
    return EXIT_OK


def _safe_name(text, fallback):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-")
    return slug[:60] or fallback


def cmd_export(args, out):
    chosen, _ = _resolve(args)
    doc = savefile.read(chosen.path)

    if args.all:
        targets = list(enumerate(doc.maps))
    else:
        if args.index is None:
            raise MapNotFound("give a map index, or --all (see `awrbc list`)")
        if not 0 <= args.index < len(doc.maps):
            raise MapNotFound("no map at index %d; the save holds %d"
                              % (args.index, len(doc.maps)))
        targets = [(args.index, doc.maps[args.index])]

    written = []
    for index, m in targets:
        built = schema.build_document(
            m, author=args.author, keep_creator=args.keep_creator,
            save_version=doc.save_version)
        report = validate.check(m)

        if args.all:
            directory = args.output or "."
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "%s-%s.json"
                                % (_safe_name(m.name, "map"), built["id"][:8]))
        elif args.output:
            path = args.output
        else:
            path = "%s-%s.json" % (_safe_name(m.name, "map"), built["id"][:8])

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(built, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        written.append({"index": index, "name": m.name, "id": built["id"],
                        "path": path, "playable": m.is_playable,
                        "findings": [vars(f) for f in report.findings]})

    if args.json:
        json.dump({"exported": written}, out, indent=2)
        out.write("\n")
        return EXIT_OK

    for w in written:
        out.write("%s\n" % w["path"])
        out.write("  %-24s id %s\n" % (w["name"][:24], w["id"]))
        for f in w["findings"]:
            out.write("  %-7s %-18s %s\n"
                      % (f["severity"], f["code"], f["message"]))
    out.write("\nexported %d map%s\n"
              % (len(written), "" if len(written) == 1 else "s"))
    # Export is advisory: a work-in-progress map still exports.
    return EXIT_OK


def cmd_import(args, out):
    chosen, _ = _resolve(args)
    # Takes whatever the editor produced, bundle or bare JSON. The preview in a
    # bundle is ignored here - a save has no use for it - but refusing the file
    # over it would make people pick the right export before they know there is
    # a choice.
    doc_json, _preview = _read_submission(args.file)

    m = schema.from_json(doc_json)
    report = validate.check(m)
    if report.errors and not args.force:
        for f in report.errors:
            sys.stderr.write("error: %-18s %s\n" % (f.code, f.message))
        raise ValidationFailed(report)

    if _game_running() and not args.force:
        raise SaveInUse(
            "the emulator appears to be running. Close the game first, or pass "
            "--force if no title is loaded.")

    doc = savefile.read(chosen.path)
    slot = savefile.add_map(doc, m, name=args.name)
    data = savefile.serialize(doc, os.path.getsize(chosen.path))

    if args.dry_run:
        if args.json:
            json.dump({"dryRun": True, "slot": slot, "bytes": len(data),
                       "name": args.name or m.name}, out, indent=2)
            out.write("\n")
        else:
            out.write("dry run: would add %r as slot %s (%s bytes)\n"
                      % (args.name or m.name, slot, format(len(data), ",")))
        return EXIT_OK

    snap = backup.snapshot(chosen.path)
    written = savefile.write(doc, chosen.path)

    if args.json:
        json.dump({"slot": slot, "bytes": written, "backup": snap.path,
                   "name": args.name or m.name,
                   "warnings": [vars(f) for f in report.warnings]}, out, indent=2)
        out.write("\n")
        return EXIT_OK

    out.write("imported %r as slot %s\n" % (args.name or m.name, slot))
    for f in report.warnings:
        out.write("  warning %-18s %s\n" % (f.code, f.message))
    out.write("  save    %s (%s bytes)\n" % (chosen.path, format(written, ",")))
    out.write("  backup  %s\n" % snap.path)
    return EXIT_OK


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

    if args.changed:
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


def cmd_remove(args, out):
    chosen, _ = _resolve(args)
    if _game_running() and not args.force:
        raise SaveInUse("the emulator appears to be running; close the game first")
    doc = savefile.read(chosen.path)
    if not 0 <= args.index < len(doc.maps):
        raise MapNotFound("no map at index %d; the save holds %d"
                          % (args.index, len(doc.maps)))
    name = doc.maps[args.index].name
    slot = savefile.remove_map(doc, args.index)
    if args.dry_run:
        out.write("dry run: would remove %r (slot %s)\n" % (name, slot))
        return EXIT_OK
    snap = backup.snapshot(chosen.path)
    savefile.write(doc, chosen.path)
    out.write("removed %r (slot %s)\n  backup %s\n" % (name, slot, snap.path))
    return EXIT_OK


def cmd_backup(args, out):
    chosen, _ = _resolve(args)
    snap = backup.snapshot(chosen.path)
    out.write("%s\n" % snap.path)
    return EXIT_OK


def cmd_restore(args, out):
    chosen, _ = _resolve(args)
    snaps = backup.snapshots(chosen.path)
    if not snaps:
        out.write("no snapshots for %s\n" % chosen.path)
        return EXIT_OK
    if args.name is None:
        out.write("snapshots for %s\n\n" % chosen.path)
        for s in snaps:
            out.write("  %-28s %s bytes\n" % (s.name, format(s.size, ",")))
        out.write("\nawrbc restore <name> to roll back\n")
        return EXIT_OK
    match = [s for s in snaps if s.name == args.name or s.taken == args.name]
    if not match:
        raise MapNotFound("no snapshot named %r" % args.name)
    if _game_running() and not args.force:
        raise SaveInUse("the emulator appears to be running; close the game first")
    backup.snapshot(chosen.path)        # snapshot the current state too
    n = backup.restore(match[0].path, chosen.path)
    out.write("restored %s (%s bytes)\n" % (match[0].name, format(n, ",")))
    return EXIT_OK


def _common(suppress):
    """Global flags, accepted before OR after the subcommand.

    The subcommand copies use SUPPRESS: with a real default, an unset flag on the
    subparser silently overwrites the value already parsed from before the
    subcommand. That bug sent a write to the wrong save file.
    """
    c = argparse.ArgumentParser(add_help=False)
    default = argparse.SUPPRESS if suppress else None
    c.add_argument("--save-dir", default=default,
                   help="Ryujinx data folder, JKSV dump, or maps file")
    c.add_argument("--profile", default=default,
                   help="profile id when a save has several")
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
    sub.add_parser("doctor", parents=[common],
                   help="find save data and report what is readable")
    sub.add_parser("list", parents=[common],
                   help="list the custom maps in a save")

    ex = sub.add_parser("export", parents=[common],
                        help="write a map out as JSON")
    ex.add_argument("index", nargs="?", type=int, help="map index from `list`")
    ex.add_argument("--all", action="store_true", help="export every map")
    ex.add_argument("-o", "--output", help="output file, or directory with --all")
    ex.add_argument("--author", help="author name to publish")
    ex.add_argument("--keep-creator", action="store_true",
                    help="publish the console profile name (often a real name)")

    im = sub.add_parser("import", parents=[common],
                        help="add a map from JSON into the save")
    im.add_argument("file", help="map JSON, or an Export bundle zip")
    im.add_argument("--name", help="name to give the map in game")
    im.add_argument("--dry-run", action="store_true", help="build but do not write")
    im.add_argument("--force", action="store_true",
                    help="import despite validation errors or a running emulator")

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

    rm = sub.add_parser("remove", parents=[common], help="delete a map")
    rm.add_argument("index", type=int, help="map index from `list`")
    rm.add_argument("--dry-run", action="store_true")
    rm.add_argument("--force", action="store_true")

    sub.add_parser("backup", parents=[common], help="snapshot the save")

    rs = sub.add_parser("restore", parents=[common],
                        help="list snapshots, or roll back to one")
    rs.add_argument("name", nargs="?", help="snapshot name from `restore`")
    rs.add_argument("--force", action="store_true")
    return p


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(out)
        return EXIT_USAGE

    handlers = {"doctor": cmd_doctor, "list": cmd_list, "export": cmd_export,
                "import": cmd_import, "remove": cmd_remove,
                "backup": cmd_backup, "restore": cmd_restore,
                "publish": cmd_publish, "catalog": cmd_catalog,
                "verify": cmd_verify}
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
