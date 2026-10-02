"""The intake endpoint.

Deliberately small: Discord sign-in, and an upload that becomes a pull request.
No database, no ratings, no server-side rendering - those are in the
architecture (decisions #47-#50) and not here yet.

    pip install -e ".[server]"
    python -m server.app

Everything secret lives here and nowhere else: the Discord client secret, the
GitHub bot token, the session key. The editor is static and holds none of it.

Flask is the one dependency, and it is carried for its session handling. A
signed cookie is the piece of this most worth not writing by hand - getting it
subtly wrong is how sessions get forged, and it would not be obvious from the
outside that anything was wrong.
"""
import os
import secrets
import time

from flask import (Flask, jsonify, redirect, request, session, url_for)

from awrbc.core import repo

from . import auth, github, submit

app = Flask(__name__)

# A new key every restart signs everybody out, which is correct for a missing
# configuration: better that than a predictable default somebody forgets to
# change and an attacker can forge sessions with.
app.secret_key = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("INSECURE_COOKIES") != "1",
    MAX_CONTENT_LENGTH=submit.MAX_UPLOAD,
)

DISCORD_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://127.0.0.1:5000")
EDITOR_URL = os.environ.get("EDITOR_URL", "http://127.0.0.1:8731/")

LIBRARY_REPO = os.environ.get("LIBRARY_REPO", "ARXII-13/awrbc-custom-map-library")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

#: One submission a minute, ten an hour, per Discord account. In memory, so it
#: resets on restart and does not survive more than one process - which is
#: honest for a single small instance and is the first thing to replace when
#: there is a database. It is a speed bump, not a wall.
RATE = {}
PER_MINUTE = 1
PER_HOUR = 10

_recent = {}


def _rate_limited(user_id):
    now = time.time()
    seen = [t for t in _recent.get(user_id, []) if now - t < 3600]
    _recent[user_id] = seen
    if sum(1 for t in seen if now - t < 60) >= PER_MINUTE:
        return "one submission a minute, please"
    if len(seen) >= PER_HOUR:
        return "ten submissions an hour, please"
    return None


def _record(user_id):
    _recent.setdefault(user_id, []).append(time.time())


def _user():
    return session.get("user")


def _configured():
    """What is missing, so a misconfigured deploy says so rather than failing
    at the first click."""
    missing = []
    for name, value in (("DISCORD_CLIENT_ID", DISCORD_ID),
                        ("DISCORD_CLIENT_SECRET", DISCORD_SECRET),
                        ("GITHUB_TOKEN", GITHUB_TOKEN)):
        if not value:
            missing.append(name)
    return missing


@app.get("/health")
def health():
    return jsonify({"ok": True, "configured": not _configured(),
                    "missing": _configured()})


# --- sign in ---------------------------------------------------------------

@app.get("/auth/login")
def login():
    if _configured():
        return jsonify({"error": "server is not configured",
                        "missing": _configured()}), 503
    state = auth.new_state()
    session["oauth_state"] = state
    # Where to send them back to afterwards, so sign-in does not lose their
    # place. Only a path, never a full URL - an open redirect is how a sign-in
    # button becomes a phishing link.
    nxt = request.args.get("next", "")
    session["after_login"] = nxt if nxt.startswith("/") else ""
    return redirect(auth.login_url(DISCORD_ID,
                                   PUBLIC_URL.rstrip("/") + "/auth/callback",
                                   state))


@app.get("/auth/callback")
def callback():
    expected = session.pop("oauth_state", None)
    got = request.args.get("state")
    # Compared in constant time and refused when either side is missing. This
    # is the check that stops a crafted callback signing somebody into an
    # attacker's account.
    if not expected or not got or not secrets.compare_digest(expected, got):
        return jsonify({"error": "that sign-in did not come from here"}), 400

    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Discord sent no code"}), 400

    try:
        token = auth.exchange(code, DISCORD_ID, DISCORD_SECRET,
                              PUBLIC_URL.rstrip("/") + "/auth/callback")
        who = auth.identity(token)
    except auth.AuthError as exc:
        return jsonify({"error": str(exc)}), 502

    # The access token is not kept. Everything this needs is the identity, and
    # a token held is a token that can leak.
    session["user"] = who
    return redirect(session.pop("after_login", "") or EDITOR_URL)


@app.post("/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/auth/me")
def me():
    who = _user()
    if not who:
        return jsonify({"signedIn": False}), 200
    return jsonify({"signedIn": True, "user": who})


# --- submitting ------------------------------------------------------------

@app.post("/submit")
def submit_map():
    who = _user()
    if not who:
        return jsonify({"error": "sign in first", "code": "unauthenticated"}), 401

    slow = _rate_limited(who["id"])
    if slow:
        return jsonify({"error": slow, "code": "rate-limited"}), 429

    # The checkbox is the whole of the licence grant. Without it the archive
    # has no right to redistribute the map, so it is a hard requirement rather
    # than a form nicety.
    if request.form.get("agree") != "true":
        return jsonify({"error": "the licence confirmation is required",
                        "code": "no-licence"}), 400

    upload = request.files.get("file")
    if upload is None:
        return jsonify({"error": "no file", "code": "no-file"}), 400
    blob = upload.read()

    try:
        index, _ = repo.fetch_catalog()
    except Exception as exc:                            # noqa: BLE001
        return jsonify({"error": "could not read the archive: %s" % exc,
                        "code": "archive-unreachable"}), 503

    try:
        prepared = submit.prepare(blob, index, who,
                                  update=request.form.get("update") or None,
                                  filename=upload.filename or "")
    except submit.Rejected as exc:
        return jsonify({"error": str(exc), "code": exc.code,
                        "findings": exc.findings}), 422

    title, body = submit.pull_request_text(prepared, who)
    library = github.Library(LIBRARY_REPO, GITHUB_TOKEN)
    try:
        url, number = library.submit(
            submit.branch_name(prepared["placement"], who),
            prepared["files"], title, body)
    except github.GitHubError as exc:
        return jsonify({"error": "could not open the pull request: %s" % exc,
                        "code": "github"}), 502

    _record(who["id"])
    return jsonify({
        "ok": True,
        "pullRequest": url,
        "number": number,
        "path": prepared["placement"].path,
        "kind": prepared["placement"].kind,
        "warnings": prepared["warnings"],
        "hasPreview": prepared["has_preview"],
    })


if __name__ == "__main__":
    missing = _configured()
    if missing:
        print("warning: not configured; missing " + ", ".join(missing))
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5000")))
