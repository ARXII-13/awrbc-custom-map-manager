# Map editor

A static page that opens, edits and exports the map JSON the CLI reads. No
install, no backend, no save access - so it cannot damage anything, and anyone
can design a map whether or not they own the game.

## Running it

ES modules need to be served over HTTP; opening `index.html` from disk will not
work.

```bash
cd web && python -m http.server 8731
```

Then open <http://127.0.0.1:8731/>, and drop a map JSON on the page. To open one
directly, pass its path:

    http://127.0.0.1:8731/?map=samples/ALL.json

Export a map to feed it:

```bash
python -m awrbc export --name ALL --out ALL.json
```

## Files

| | |
|---|---|
| `terrain.js` | Terrain, team and unit tables. Data only - no drawing, no DOM. |
| `icons.js` | Terrain, property and unit icons, drawn procedurally. |
| `sprites.js` | Optional sprite-pack loader; overrides the drawn icons. |
| `edit.js` | Editing operations, undo, and live stats. No rendering. |
| `render.js` | The renderer. Pure: a 2D context plus a map document. |
| `index.html` | The viewer shell - loading, pan, zoom, hover, stats. |

`render.js` is deliberately free of editing state so the archive's thumbnail
generator can use it unchanged; `thumbnail(doc, w, h)` is there for that.

## No game assets, ever

Every colour and every icon here is original. None of it is sampled, traced or
ripped from Advance Wars, on the GBA or the Switch. That is not a style choice -
it is the whole reason this project can publish an archive and a website at all,
and it is the first thing somebody will be tempted to "improve".

If you want different art on your own machine, drop a sprite pack into
`web/sprites/` - it overrides the drawn icons per id, and it is gitignored so it
never reaches the repository, the archive or the website. See
`sprites/README.md`. That boundary is decision #37.

Icons are drawn in a 0..1 box and scaled, so they stay sharp anywhere between a
13px tile and a 72px one. A 16x16 sprite sheet could not do that.

`inkFor()` in `render.js` picks icon ink from the background's luma rather than
always using white. Neutral properties are light grey and Yellow Comet is a
light yellow; both washed out entirely with white icons.

## Tools

| | | |
|---|---|---|
| Paint | `B` | Terrain; dragging paints a stroke |
| Fill | `G` | Flood fill the contiguous region under the cursor |
| Unit | `U` | Place the selected unit for the selected army |
| Owner | `O` | Re-assign a property or unit to the selected army |
| Erase | `E` | Remove a unit |
| Pan | `H` | Or hold Shift, or use the middle/right button, from any tool |

`1`-`5` pick an army. Ctrl+Z / Ctrl+Shift+Z undo and redo; a drag is one step.
The wheel zooms about the cursor.

## Flags are not the editor's job

Export writes **no `flags` grid at all**. `schema.from_json` derives flags from
terrain and ownership when the JSON omits them, so the autotile rule lives in
exactly one place - `awrbc/core/autotile.py` - instead of being reimplemented in
JavaScript and drifting.

This is also why editing is safe: the editor cannot produce a map with wrong
flags, because it never produces flags. Verified end to end - an export with no
flags imports to a save the game's own deserializer accepts.

## Known gaps

- Multi-tile structures render tile-by-tile. They look right because each tile
  carries its own terrain id, but the viewer does not yet know they are one
  object - that matters for the editor, not for viewing.
- Icons exist for terrain that needs one, all six property types, and all 19
  units. Plain terrain (grass, sea, road, river) is deliberately bare - an icon
  on every tile is noise.
- No multi-tile structures in the palette. A Black Cannon is nine tiles with
  offsets and structure bits, and the placement rule is not worked out yet.
- No symmetry helpers or rectangle select yet.
- Resize exists in `edit.js` but has no UI.
