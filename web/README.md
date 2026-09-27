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
| `render.js` | The renderer. Pure: a 2D context plus a map document. |
| `index.html` | The viewer shell - loading, pan, zoom, hover, stats. |

`render.js` is deliberately free of editing state so the archive's thumbnail
generator can use it unchanged; `thumbnail(doc, w, h)` is there for that.

## Colours are not the game's

Every colour here is chosen, not sampled from the game's art. That is what keeps
the renderer - and anything built on it - publishable. Do not replace these with
ripped sprites.

## Known gaps

- Terrain `4` and `8` are mountain and woods in some order, shown as `Mountain?`
  and `Woods?`. Neither autotiles, so only a look at a rendered map settles it.
- Multi-tile structures render tile-by-tile. They look right because each tile
  carries its own terrain id, but the viewer does not yet know they are one
  object - that matters for the editor, not for viewing.
- Read-only. Painting, ownership and unit placement are the next slice.
