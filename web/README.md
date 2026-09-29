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

Then open <http://127.0.0.1:8731/> and use **Open** to pick a map JSON. (There is no
drag-and-drop; it is a file picker.) To load one straight away, pass its path:

    http://127.0.0.1:8731/?map=samples/ALL.json

Export a map to feed it — the index comes from `list`:

```bash
python -m awrbc list
python -m awrbc export 0 -o ALL.json
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

**64x64 is a hard ceiling.** Both New and Resize refuse a larger size, because the
CLI and the archive reject one. Shrinking past a 3x3 structure removes the whole
structure rather than truncating it into eight orphaned body tiles.

Between 30x20 and 64x64 the size is flagged as a note rather than an error: those
maps play fine but the in-game editor will not open them, so this is the only place
they can be edited.

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

## What gets checked

The live check under the map name:

| | | |
|---|---|---|
| every army has an HQ | error | the game's own rule |
| every army has a unit or a production property | error | the game's own rule |
| at least two armies | error | ours - nobody to play against |
| no army over 50 units | error | ours - Advance Wars' standard army cap |
| bigger than 64x64 | error | ours - the archive will not accept it |
| bigger than the in-game editor's 30x20 | note | plays fine, just not editable in game |

Only the first two are decoded game behaviour; the rest are rules this project
chose. See docs/format.md for which is which and why it matters.

`awrbc/core/validate.py` is the full set and the authoritative one, including
checks the editor cannot produce but an imported file can - an incomplete 3x3
structure, ownership on terrain that cannot be owned, a grid that does not match
its declared size. Its codes are a stable contract; the CLI renders them and
archive CI will key off them.

## Flags are not the editor's job

Export writes **no `flags` grid at all**. `schema.from_json` derives flags from
terrain and ownership when the JSON omits them, so the autotile rule lives in
exactly one place - `awrbc/core/autotile.py` - instead of being reimplemented in
JavaScript and drifting.

This is also why editing is safe: the editor cannot produce a map with wrong
flags, because it never produces flags. Verified end to end - an export with no
flags imports to a save the game's own deserializer accepts.

## Known gaps

- **No symmetry helpers and no rectangle select.** Paint is per-tile with a drag
  stroke, plus flood fill. Mirroring a quadrant is the single most useful thing
  missing for anyone building a competitive map.
- **Author, fog and water colour are not editable.** They round-trip faithfully
  through an opened map, but nothing in the UI sets them, so a map created here is
  always `anonymous`, fog off, water colour 0.
- Icons exist for terrain that needs one, all six property types, and all 19
  units. Plain terrain (grass, sea, road, river) is deliberately bare - an icon
  on every tile is noise.
- **Pipe and pipe seam are drawn from their connections**, so a run reads as a run.
  The icon is handed the same `N+E+S+W` set the sprite lookup uses, which is why a
  corner bends and a seam shows its collar. Any terrain that runs rather than sits
  can use that.
- Pipe art in a sprite pack may need its own resolver. The pack built by
  `sprites/build_terrain.py` carries one: pipeline sprites encode their shade in the
  red channel alone and match no colour table or biome palette, so the builder maps
  that index onto a metal ramp it defines itself. Their shapes, our colours.

