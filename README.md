# awrbc-custom-map-manager

Custom map tools for *Advance Wars 1+2: Re-Boot Camp*.

Read the custom maps out of a save file, write them back, and exchange them as a
neutral JSON format. Works with Ryujinx save data and with JKSV dumps from real
hardware.

> Not affiliated with or endorsed by Nintendo or WayForward. Distributes no game
> assets, code, or keys. You need your own copy of the game.

## Status

Early. `doctor`, `list` and `export` work; import is next. See
`../docs/phase-1-core-cli.md` for the plan and `../docs/format.md` for the save
format record.

## Usage

```
awrbc doctor                      find save data and report what is readable
awrbc list                        list the custom maps in a save
awrbc export 3 -o map.json        write one map out as JSON
awrbc export --all -o ./maps/     write them all out
```

Flags: `--save-dir` (Ryujinx folder, JKSV dump, or a maps file), `--profile`,
`--json`. Export also takes `--author` and `--keep-creator`.

**The creator name is scrubbed by default.** The save stores the console profile
name, which for many people is their real name; `--keep-creator` opts in.

Export is advisory: an unplayable map still exports, with its findings printed.
Publishing to the archive is where validation blocks.

Run from a checkout with `python -m awrbc.cli <command>`.

## Layout

```
awrbc/core/    codec, save reading, domain model - never prints, never exits
awrbc/cli/     the only place that formats output or picks exit codes
tools/         bfcheck.ps1 and nrbfcheck - format validators
tools/poc/     the reverse-engineering scripts, kept for reference
tests/
```

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
python -m unittest discover -s tests
```

Save-backed tests are skipped unless `AWRBC_TEST_SAVE` points at a maps file.
Real saves are never committed — they carry creator names and game-format data.
