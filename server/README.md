# The intake endpoint

Discord sign-in, and an upload that becomes a pull request on the map library.
That is all it does: no database, no ratings, no server-side rendering. Those
are in `docs/app-architecture.md` and are not built.

It exists so a contributor never needs a GitHub account, let alone git. They
upload a map; a bot does the branch, the commit and the pull request.

## Running it

TypeScript on Node, with the Python tool beside it.

```bash
pip install -e .          # the rules, as a command
cd server && npm install && npm run build && npm start
```

`GET /health` says whether it is configured and what is missing, so a bad
deploy is visible before anyone clicks anything. On startup it also checks it
can actually run the validator and **exits** if it cannot — that is not
something to discover at somebody's first upload, after they have written a
map.

### Why two runtimes

This server knows nothing about what a valid map is, where one belongs, or how
a map's identity is computed. It shells out to `awrbc prepare`, which is
Python, and reads JSON back.

That is deliberate. Those rules are ~1,200 lines in `awrbc.core`, covered by
its tests and re-run by the library's CI. Reimplementing them here would mean
two answers to the same question — and the most important of them is a content
hash. A hash that drifted would not throw. De-duplication would quietly stop
working and the archive would fill with copies of one map.

A process per submission costs about 200ms. At a handful of uploads a day that
is nothing, and it buys one implementation of the rules.

`AWRBC_COMMAND` may carry arguments, so `python -m awrbc` or an absolute path
into a venv both work — useful in a container where the console script need
not be on `PATH`.

## What you have to set up

| Variable | What it is |
|---|---|
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` | A Discord application. Add `PUBLIC_URL/auth/callback` as a redirect URI |
| `GITHUB_TOKEN` | A **bot account's** token with push access to the library repo |
| `SESSION_SECRET` | Any long random string. Without one a fresh key is generated per restart, which signs everybody out |
| `AWRBC_COMMAND` | How to run the tool. Default `awrbc`; may carry arguments, e.g. `python -m awrbc` |
| `ALLOWED_ORIGINS` | Comma-separated origins allowed to call this. `EDITOR_URL` is included automatically |
| `PUBLIC_URL` | Where this is reachable, e.g. `https://intake.example` |
| `EDITOR_URL` | Where to send people after they sign in |
| `LIBRARY_REPO` | `owner/name` of the archive |

Two of those are worth a sentence each.

**The GitHub token should belong to a bot account**, not to you. Commits made
with your token say you wrote the map. A separate identity keeps history
honest about who contributed what, and keeps the blast radius of a leaked
token to one repository.

**`SESSION_SECRET` has no default on purpose.** A hardcoded fallback is the
kind of thing that survives into production and lets anybody forge a session.
A random key per restart is inconvenient and safe; a shared default is
convenient and not.

### If the editor can never sign in

Check `ALLOWED_ORIGINS` first, and `/health` reports what it resolved to.

The editor and this server are different origins - different ports in
development, probably different subdomains in production - so without the right
CORS headers the browser will not send the session cookie or let the page read
the reply. The editor treats an unreachable server as "signed out", which is
correct (editing has never needed a server), so a *present* server with wrong
CORS looks exactly like no server: the button says "Sign in to submit" forever,
including immediately after signing in successfully. Nothing errors.

Two things the allowlist must never become: `*`, which browsers refuse with
credentials anyway and which would let any site read authenticated replies; and
a reflection of whatever `Origin` arrived, which would let any page act as a
signed-in user.

If the editor and the server are on different registrable domains rather than
different subdomains, the session cookie also needs `SameSite=None; Secure`,
which this does not currently set.

## Endpoints

| | |
|---|---|
| `GET /auth/login` | Redirects to Discord. `?next=/path` returns there afterwards |
| `GET /auth/callback` | Discord returns here; sets the session |
| `GET /auth/me` | Who is signed in |
| `POST /auth/logout` | Clears it |
| `POST /submit` | `file` (bundle zip or map JSON), `agree=true`, optional `update=2p/slug` |

A successful submit returns the pull request URL.

## What it refuses, and why

- **Not signed in** — 401. Attribution and rate limiting both need an identity.
- **No licence confirmation** — 400. The checkbox *is* the grant of rights;
  without it the archive has no right to redistribute the map, and that cannot
  be retrofitted later.
- **A map that fails validation** — 422, with every finding at once rather than
  one per round trip. Nothing reaches GitHub.
- **A preview that is not a plain PNG of exactly the right size** — same path.
  The image is untrusted input heading for a public repository.
- **Already in the archive, or a slug somebody else owns** — 422. The archive
  will not guess.
- **More than one submission a minute, or ten an hour** — 429. A refused
  submission does not count, so being told your map is broken does not lock
  you out while you fix it.

## Things that are deliberate

**The author is the session, not the file.** A map JSON carries an `author`
field and anybody can type anything into it. What gets committed is the
Discord account that signed in. A file is a claim; a session is not.

**The Discord id never reaches the archive** (decision #44). It lives in the
session and in the pull request body for a reviewer. What is committed is a
display name.

**The access token is not kept.** It is exchanged for an identity and dropped.
A token held is a token that can leak.

**`state` is checked on the callback, in constant time, and is single-use.**
Without it, a crafted callback link signs a victim into the attacker's account
and everything they upload carries the attacker's name.

**`?next=` only accepts a path.** An absolute URL would make the sign-in button
an open redirect, which is how a legitimate domain ends up hosting a phishing
hop.

## What is honestly missing

- **Rate limits are in memory.** They reset on restart and do not survive more
  than one process. That is a speed bump, not a wall, and the first thing to
  replace when there is a database.
- **No ban list.** Moderation is the pull request, and a human closing it.
- **No preview provenance.** `preview.check_png` can show an image is a plain
  PNG of the right dimensions; it cannot show the editor drew it. The fix is
  rendering server-side, which is in the architecture and not built.
- **One instance only.** Sessions are cookies so that is fine, but the rate
  limiter is not shared.

## Tests

```bash
npm test                  # after npm run build
```

The bridge tests call the **real** `awrbc prepare` rather than stubbing it.
Stubbing the subprocess would test the stub, and would stay green through
exactly the breakage this design exists to prevent — the two sides disagreeing
about what a map is. They skip when the tool is not installed, which is
checked at module load: a `before` hook would run too late and skip the whole
suite while reporting success.
