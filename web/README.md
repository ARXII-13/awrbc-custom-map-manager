# Map editor

A static page that opens, edits and exports the map JSON the CLI reads. No
install, no backend, no save access - so it cannot damage anything, and anyone
can design a map whether or not they own the game.

## Running it

ES modules need to be served over HTTP; opening `index.html` from disk will not
work.

```bash
cd web && python serve.py
```

Use `serve.py` rather than `python -m http.server`: it sends no-cache headers.
Without them the browser holds on to ES modules, an edit appears to do nothing,
and you debug code the page is not actually running.

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

`1`-`5` pick an army and `0` picks neutral. Ctrl+Z / Ctrl+Shift+Z undo and
redo; a drag is one step. The wheel zooms about the cursor.

## Size

The Map section carries the dimensions. Change them and press Resize: the
top-left corner stays put, growing fills with plains, and shrinking discards
whatever falls outside - it asks first when that would lose anything. Resize is
a single undo step, dimensions included.

Anything past 30x20 is flagged. Those maps play fine but the in-game editor
will not open them, so this is the only place they can be edited.

## The palette is split by who can own a thing

That is the question the sidebar exists to answer, so it is the thing it is
organised around.

| Section | Holds | Army picker |
|---|---|---|
| **Terrain** | plains, woods, mountain, road, bridge, river, shoal, sea, reef | does not apply - ground has no owner |
| **Structures** | HQ, city, base, airport, seaport, com tower | the selected army owns what you place |
| | plus pipe, seam, silo, mini cannon, laser | **only when neutral is selected** - these are never owned |
| **Units** | all 19 | hidden under neutral; a unit always belongs to an army |

Palette swatches show the whole object, assembled and scaled to fit - a 3x3
structure is drawn from all nine of its tiles, not the one the sprite lookup
returns, and a building is not cropped to its base.

An **Aims** row appears under Structures when the selected one is a cannon,
and sets which way it points. The palette icon turns with it, so the swatch
shows what you are about to place. That direction is stored on the cell, and
the flags the game wants are derived from it - see docs/format.md.

Road and bridge direction works the other way round: nothing is stored, and
the renderer reads it off the neighbours each time it draws, so a road fixes
itself when you paint beside it. A cannon cannot be derived that way - only
the mapmaker knows where it should point.

The 3x3 Black Cannon and Death Ray place as a block: click sets the **top-left**
tile and the other eight follow, with the facing on the anchor and hit points at
offset [1,0]. Placing one where it will not fit is refused rather than clipped,
because a partial structure is worse than none, and painting over any part of an
existing one removes all nine rather than orphaning eight body tiles.

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

