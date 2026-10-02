# Sprite packs

Drop a sprite pack here and the renderer uses it. There is no drawn-art
alternative any more (decision #46) - the fallback for an id a pack does not
cover is a letter on a flat colour, so a partial pack is fine but a missing one
is drab.

**The pack here is committed** (decision #56): `manifest.json`, `units.png`
and `terrain.png`. A clone renders properly with no extra step, and so does
the deployed editor.

The builders that produced it are not committed. They read a checkout of
somebody else's project, so they are a record of how the pack was made rather
than something this repository can run.

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

## What this is, and what it costs

The committed pack is derived from [Commander Wars][cw], whose own credits
describe its art as Advance Wars derived. So these sprites are, at one remove,
Nintendo and Intelligent Systems copyright.

That was the argument for keeping them out of git, and it is still the
argument. It was overruled deliberately, in stages, by the person who owns the
risk: drawn substitute art was rejected (#46), the desktop build was allowed to
ship the pack (#54), and finally the repository itself (#56). Each step was
taken knowing the next became easier.

What is worth understanding is the one-way door. A release can be deleted and a
binary can be withdrawn; **a committed file stays in git history**, and taking
it back out means rewriting history rather than deleting a file - which breaks
every clone and fork that already exists.

Other Advance Wars sites ship ripped assets and have not been troubled. That is
tolerance rather than a licence, and the project now rests on it.

[cw]: https://github.com/Robosturm/Commander_Wars
