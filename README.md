# awrbc-custom-map-manager

Custom map tools for *Advance Wars 1+2: Re-Boot Camp*.

Read the custom maps out of a save file, write them back, and exchange them as a
neutral JSON format. Works with Ryujinx save data and with JKSV dumps from real
hardware.

> Not affiliated with or endorsed by Nintendo or WayForward. Distributes no game
> assets, code, or keys. You need your own copy of the game.

## Status

**Phase 1 (core and CLI)** — read, export, import, remove, backup and restore.

**Phase 2 (editor)** — a browser map editor in `web/`. Paint terrain, place
units and structures, live validity, export JSON the CLI imports and the game
loads. No install and no save access: it speaks map JSON only.

Next is the archive. See `../docs/` for the plan, `../docs/format.md` for the
save format record, and `web/README.md` for the editor.

Maps are capped at 64x64. That is a policy limit rather than a measured one:
64x64 is the largest size confirmed to load, and 40x30 the largest played to
completion.

## Usage

```
awrbc doctor                      find save data and report what is readable
awrbc list                        list the custom maps in a save
awrbc export 3 -o map.json        write one map out as JSON
awrbc export --all -o ./maps/     write them all out
awrbc import map.json             add a map from JSON
awrbc remove 3                    delete a map
awrbc backup                      snapshot the save
awrbc restore [name]              list snapshots, or roll one back

python -m awrbc.desktop            the editor with save access, in a window

awrbc search "4p fog"             find maps in the public archive
awrbc show renew                  what one map is, and its versions
awrbc import renew                fetch it from the archive into your save

awrbc publish map.json            place a map in a library checkout
awrbc catalog                     rebuild the index and folder READMEs
```

`import` and `remove` take `--dry-run` and `--force`. `import` accepts a file
on disk or a slug from the archive - an existing path always wins, so a file
you can see is never passed over in favour of a download.

The archive commands take `--base` (a different archive), `--library` (a local
checkout, which also works offline) and `--refresh`. The catalog is cached for
an hour; when the network is down a stale copy is used with a warning rather
than failing.

Flags: `--save-dir` (Ryujinx folder, JKSV dump, or a maps file), `--profile`,
`--json`. Export also takes `--author` and `--keep-creator`.

Imported maps are marked with the game's own `IsDownload` flag, which
distinguishes a map that came from somebody else.

**The creator name is scrubbed by default.** The save stores the console profile
name, which for many people is their real name; `--keep-creator` opts in.

Export is advisory: an unplayable map still exports, with its findings printed.
Import blocks on validation errors unless you pass `--force`.

**Every write takes a backup first**, into a user data directory (override with
`AWRBC_BACKUP_DIR`). Writes are serialized fully in memory and then swapped into
place, so a partial save is never left behind. Import also refuses while the game
is running, because the title flushes its own copy over external edits.

Run from a checkout with `python -m awrbc <command>`, or install it with `pip install -e .` for a plain `awrbc`.

## Layout

```
awrbc/core/    codec, save reading, domain model - never prints, never exits
awrbc/cli/     the scriptable surface; formats output and picks exit codes
awrbc/desktop/ the editor in a window, with save access (pip install .[desktop])
server/        the intake endpoint - TypeScript, shells out to `awrbc prepare`
web/           the browser map editor; becoming part of the app (see docs)
tools/         bfcheck.ps1 and nrbfcheck - format validators
tests/
```

## A note on the `docs/` references

Comments and docstrings in here cite `docs/format.md`, `docs/decisions.md` and
the phase documents. **Those files are not in this repository.** The design
notes, the save-format research record and the decision register are kept
outside version control, and only the code is published.

So those citations are to a document set you do not have. They are left in
because they say *why* a piece of code is the shape it is, and a reader is
better served knowing a reason was written down somewhere than seeing the
reason deleted. If something here looks arbitrary, it probably has an entry in
that register.

## Validating output

**Nothing goes near a save without passing `tools/bfcheck.ps1`.** It deserializes
a file with the real .NET BinaryFormatter, which is the only validator that
agrees with the game — our own parser accepts broken files, and .NET 9's
`NrbfDecoder` gets it wrong in both directions.

```
powershell -File tools/bfcheck.ps1 path/to/maps
```

## Tests

```
python -m unittest discover -s . -p "test_*.py"
```

Runs anywhere with no save present: `tests/fixture.py` builds a complete, valid
save from `tests/fixtures/typetable.json`, which holds **only** the game's class
definitions — member names and types, no map content and no creator names. Real
saves are never committed.

Point `AWRBC_TEST_SAVE` at a maps file to additionally run everything against
the genuine article. Tests always work on a throwaway copy.

On Windows the suite also runs every save it writes through the real
BinaryFormatter, so the failure mode that shows the player zero custom maps is
caught automatically rather than by remembering to check.

Regenerate the type table from a save with:

```
python tools/extract_types.py <maps-file> tests/fixtures/typetable.json
```

## Is this the right save?

Two independent signals confirm a file belongs to this game before anything
reads or writes it:

| Signal | Where | Availability |
|---|---|---|
| root class `AW.UserGeneratedContent` from `Assembly-CSharp` | inside the maps file | always |
| title id `0100300012F2A000` | `ExtraData0`, three levels up | only with the full Ryujinx save tree |

The root class is the primary check. A wrong title id rejects even when the root
matches; a *missing* one proves nothing, because a JKSV dump of `SaveData` alone
has no `ExtraData`.

Pointing the tool at another title's save — or at this game's own `gameState`,
which is also `Assembly-CSharp` NRBF — now says so plainly instead of
complaining about an unsupported version number. `awrbc doctor` reports both.

## Known limitations

- `import` needs the target save to already hold one custom map, whose
  LevelSaveData supplies the shapes of the always-empty AIWaypoints /
  MagmaTargets / TransportedUnits members.
- Importing a map that places units additionally needs the save to contain at
  least one unit somewhere, to model them on.
- `AIWaypoints`, `MagmaTargets` and transport contents are not represented in
  the map JSON. A map using any of them is refused rather than silently
  flattened.
