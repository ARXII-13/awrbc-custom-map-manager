"""Discord sign-in.

The editor is static and holds nothing secret, so the OAuth exchange happens
here: the browser gets a session cookie, the client secret never leaves this
process.

Only enough of Discord's identity to attribute a map and rate-limit a person -
the ``identify`` scope, which is id, username and avatar. Not email, not
guilds, not anything else. An endpoint that asks for more than it uses is an
endpoint that leaks more than it needs to when it is breached.

**The Discord id never reaches the archive** (decision #44). It lives here and
in the session; what gets committed is a display name the author chose.
"""
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

AUTHORIZE = "https://discord.com/api/oauth2/authorize"
TOKEN = "https://discord.com/api/oauth2/token"
ME = "https://discord.com/api/v10/users/@me"

SCOPE = "identify"
TIMEOUT = 20


class AuthError(RuntimeError):
    pass


def login_url(client_id, redirect_uri, state):
    """Where to send the browser. ``state`` is not optional.

    Without it, anyone can hand a victim a crafted callback URL and have their
    account signed in as the attacker - the session ends up attached to the
    wrong person, and maps they upload go to the attacker's name. It costs one
    random string and one comparison.
    """
    return AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "prompt": "none",
    })


def new_state():
    return secrets.token_urlsafe(24)


def _post(url, fields):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "awrbc-intake")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise AuthError("Discord refused the exchange (%s): %s"
                        % (exc.code, exc.read().decode("utf-8", "replace")[:200]))
    except urllib.error.URLError as exc:
        raise AuthError("could not reach Discord: %s" % exc.reason)


def exchange(code, client_id, client_secret, redirect_uri):
    """Authorization code -> access token."""
    got = _post(TOKEN, {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    })
    if "access_token" not in got:
        raise AuthError("no access token in Discord's reply")
    return got["access_token"]


def identity(access_token):
    """Who signed in. Returns ``{id, username, avatar}`` and nothing more."""
    req = urllib.request.Request(ME)
    req.add_header("Authorization", "Bearer %s" % access_token)
    req.add_header("User-Agent", "awrbc-intake")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            who = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise AuthError("Discord would not say who this is (%s)" % exc.code)
    except urllib.error.URLError as exc:
        raise AuthError("could not reach Discord: %s" % exc.reason)

    if not who.get("id"):
        raise AuthError("Discord returned no user id")
    return {
        "id": str(who["id"]),
        "username": who.get("global_name") or who.get("username") or "someone",
        "avatar": who.get("avatar"),
    }
