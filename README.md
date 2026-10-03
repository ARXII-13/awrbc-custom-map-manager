# Advance Wars 1+2: Re-Boot Camp — map editor and archive

Make custom maps in a browser, and publish them to a public archive.

**Not affiliated with Nintendo or WayForward.** This holds map data — grids of
numbers describing terrain and ownership — and the tools to edit and share it.
No game assets, no code from the game, nothing extracted from a cartridge.

Getting a map **into your save** is a separate tool in a separate repository:
[awrbc-save-editor](https://github.com/ARXII-13/awrbc-save-editor). That split
is deliberate. A tool that writes to a save file and a public archive of maps
are different things with different risks, and nothing in either repository
depends on the other.

## The map editor

In a browser, nothing to install:
<https://arxii-13.github.io/awrbc-custom-map-manager/>

Paint terrain, place units and structures, live validity checks. **Export
bundle** gives you a zip holding the map and a picture of it — that zip is what
the save editor imports, and what gets submitted here.

Locally:

```bash
python web/serve.py 8731 127.0.0.1
```

## The archive

Maps live in
[awrbc-custom-map-library](https://github.com/ARXII-13/awrbc-custom-map-library),
one folder per map, versions as files inside it, with a generated
`catalog.json` so a client can search without cloning.

```bash
pip install .

awrbc search 4p                   find maps in the public archive
awrbc show renew                  what one map is, and its versions
awrbc publish map.zip --library . place a map in a library checkout
awrbc catalog --library .         rebuild the index and folder READMEs
awrbc verify --library .          what CI runs on a pull request
awrbc prepare bundle.zip          decide what a submission would become
```

`prepare` is the contract the intake server calls across: it answers in JSON
and writes nothing, so the server never reimplements a rule — above all the
content hash, which would not raise when it drifted, it would just quietly stop
de-duplicating.

## The intake server

`server/` turns an upload into a pull request on the archive, so a contributor
never needs a GitHub account or any git at all. TypeScript on Node, shelling
out to `awrbc prepare` for every decision about what a valid map is.

See [server/README.md](server/README.md) for running and deploying it, and for
`OPEN_SUBMISSIONS`, which takes maps with nobody signed in.

## What is in here

```
awrbc/core/    the map document: schema, validation, identity, the archive's
               placement rules, the catalog, the archive client
awrbc/cli/     publish, verify, catalog, search, show, prepare
web/           the map editor, and the renderer it draws with
server/        the intake endpoint
```

## The shared layer

`awrbc/core/{model,schema,validate,identity,derive,anonymize,autotile}.py` and
`web/{render,terrain,sprites}.js` exist here *and* in the save editor. The two
repositories are independent on purpose, and the cost of that is two copies.

`tests/test_shared_format.py` is the guard, and it is kept byte-identical in
both: it pins the content hash of a fixed map to a literal. A hash that drifts
does not raise — de-duplication quietly stops working — so whichever copy
changes fails its own suite instead.

## Tests

```bash
python -m unittest discover -s . -t . -q    # the archive and the map document
node --test web/test/*.test.mjs             # the editor's modules
cd server && npm test                       # the intake endpoint
```

The editor's suite runs under node with no DOM, because its modules are plain
ES modules that take what they need rather than reaching for globals. The
editor once ran dead for five commits behind a check that only asked whether a
button existed; `tests/test_editor_syntax.py` is the half that syntax checking
can see, and `web/test/` is the half it cannot.
