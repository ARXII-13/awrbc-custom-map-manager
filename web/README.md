# Map viewer

A static page that renders the map JSON the CLI exports. No install, no backend,
no save access - so it cannot damage anything, and anyone can open a map whether
or not they have the game.

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

## Known gaps

- Multi-tile structures render tile-by-tile. They look right because each tile
  carries its own terrain id, but the viewer does not yet know they are one
  object - that matters for the editor, not for viewing.
- Icons exist for terrain that needs one, all six property types, and all 19
  units. Plain terrain (grass, sea, road, river) is deliberately bare - an icon
  on every tile is noise.
- Read-only. Painting, ownership and unit placement are the next slice.
