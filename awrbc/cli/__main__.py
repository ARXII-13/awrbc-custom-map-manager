"""Command line entry point.

All presentation lives here. core returns values and raises typed errors; this
module is the only place that formats text, picks exit codes, or writes to a
stream.
"""
import argparse
import json
import sys

from ..core import locate, savefile
from ..core.errors import AwrbcError, SaveNotFound

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
                       maps=len(doc.maps))
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
        out.write("    size     %s bytes\n" % f"{r['size']:,}")
        if r["readable"]:
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


def _common():
    """Global flags, shared so they work before OR after the subcommand."""
    c = argparse.ArgumentParser(add_help=False)
    c.add_argument("--save-dir", help="Ryujinx data folder, JKSV dump, or maps file")
    c.add_argument("--profile", help="profile id when a save has several")
    c.add_argument("--json", action="store_true", help="emit structured output")
    return c


def build_parser():
    common = _common()
    p = argparse.ArgumentParser(
        prog="awrbc", parents=[common],
        description="Custom map tools for Advance Wars 1+2: Re-Boot Camp. "
                    "Not affiliated with Nintendo or WayForward.")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("doctor", parents=[common],
                   help="find save data and report what is readable")
    sub.add_parser("list", parents=[common],
                   help="list the custom maps in a save")
    return p


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(out)
        return EXIT_USAGE

    handlers = {"doctor": cmd_doctor, "list": cmd_list}
    try:
        return handlers[args.command](args, out)
    except AwrbcError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
