# The intake endpoint

Discord sign-in, and an upload that becomes a pull request on the map library.
That is all it does: no database, no ratings, no server-side rendering. Those
are in `docs/app-architecture.md` and are not built.

It exists so a contributor never needs a GitHub account, let alone git. They
upload a map; a bot does the branch, the commit and the pull request.

## Running it

```bash
pip install -e ".[server]"
python -m server.app
```

The tool itself stays dependency-free — Flask is an optional extra, and only
someone running a server installs it.

`GET /health` says whether it is configured and what is missing, so a bad
deploy is visible before anyone clicks anything.

## What you have to set up

| Variable | What it is |
|---|---|
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` | A Discord application. Add `PUBLIC_URL/auth/callback` as a redirect URI |
| `GITHUB_TOKEN` | A **bot account's** token with push access to the library repo |
| `SESSION_SECRET` | Any long random string. Without one a fresh key is generated per restart, which signs everybody out |
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
