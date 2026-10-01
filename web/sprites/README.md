# Sprite packs

Drop a sprite pack here and the viewer uses it instead of the drawn icons. The
renderer falls back per id, so a partial pack is fine - cover what you have and
everything else keeps its drawn icon.

**Nothing in this directory is committed** except this file and
`manifest.example.json`. That is deliberate: see "What not to commit" below.

## Setting one up

1. Put your sheet images here, e.g. `terrain.png` and `units.png`.
2. Copy `manifest.example.json` to `manifest.json`.
3. Point `sheets` at your images and fill in each `[col, row]`.

Reload; the sidebar names the pack that loaded.

## Manifest

```json
{
  "tile": 16,
  "defaultSheet": "terrain",
  "sheets": { "terrain": "terrain.png", "units": "units.png" },

  "terrain":    { "1": [0, 0], "2": [1, 0] },
  "properties": { "512": { "neutral": [0, 1], "0": [1, 1], "1": [2, 1] } },
  "units":      { "9":   { "0": [0, 3, "units"], "1": [1, 3, "units"] } }
}
```

- `tile` is the source tile size in pixels. Sprites are scaled with
  nearest-neighbour, so 16x16 art stays crisp at any zoom.
- Coordinates are `[col, row]` in tiles, not pixels.
- A third element names a sheet: `[col, row, "units"]`. Without it,
  `defaultSheet` is used.
- `terrain` entries are a bare `[col, row]`. `properties` and `units` are keyed
  by team (`"neutral"`, `"0"`..`"4"`) because they are drawn per army; a bare
  `[col, row]` also works if your art is team-independent.
- Terrain ids are in `../terrain.js`; unit ids are in `docs/id-tables.md`.

A pack that fails to load - missing file, bad JSON - is ignored with a console
warning. The viewer never breaks because of a pack.

## What not to commit

`.gitignore` excludes the images and `manifest.json`, and that boundary is the
point of this whole mechanism rather than an afterthought.

Sprites ripped from Advance Wars, on any platform, are Nintendo and Intelligent
Systems copyright. Using them locally is one thing and is the user's own call.
Committing them puts them in a public repository, and from there into the
archive and the website in phases 3 and 5 - which is precisely the exposure this
project was scoped to avoid. Other Advance Wars sites ship ripped assets and
have not been troubled, but that is tolerance, not a licence, and it is not
something this repository should rely on.

So: use whatever art you like on your own machine. Keep the repository shipping
a letter on a flat colour, which is legible but not the intent.
