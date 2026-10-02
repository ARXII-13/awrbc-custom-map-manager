"""Opening a pull request on the library, as a bot.

The whole reason this exists: a contributor should never need a GitHub account,
let alone know git. They upload a map; this does the branch, the commit and the
pull request under a bot identity.

Only the four calls that needs. No SDK - the GitHub REST API over stdlib
``urllib`` is a few dozen lines, and a dependency that holds a token is a
dependency worth not having.
"""
import base64
import json
import urllib.error
import urllib.request

API = "https://api.github.com"
TIMEOUT = 30


class GitHubError(RuntimeError):
    """A call failed. Carries the status so the caller can tell apart "your
    fault" from "ours"."""

    def __init__(self, status, message, url=""):
        self.status = status
        self.url = url
        super().__init__("GitHub %s: %s" % (status, message))


class Library:
    """The archive repository, through a bot account."""

    def __init__(self, repo, token, branch="main", author=None):
        self.repo = repo                      # "owner/name"
        self.token = token
        self.branch = branch
        # What appears in `git log`. A bot that commits as a person is a bot
        # that makes history lie about who wrote a map.
        self.author = author or {
            "name": "awrbc-bot",
            "email": "awrbc-bot@users.noreply.github.com",
        }

    # --- plumbing --------------------------------------------------------

    def _call(self, method, path, body=None):
        url = path if path.startswith("http") else API + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer %s" % self.token)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "awrbc-intake")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise GitHubError(exc.code, detail, url)
        except urllib.error.URLError as exc:
            raise GitHubError(0, str(exc.reason), url)

    # --- the four things it needs ---------------------------------------

    def head_sha(self):
        ref = self._call("GET", "/repos/%s/git/ref/heads/%s"
                         % (self.repo, self.branch))
        return ref["object"]["sha"]

    def create_branch(self, name, from_sha):
        return self._call("POST", "/repos/%s/git/refs" % self.repo,
                          {"ref": "refs/heads/" + name, "sha": from_sha})

    def put_file(self, branch, path, content, message):
        """Create a file on a branch. Deliberately does not handle updating an
        existing one: every submission is a new path, and a call that could
        silently overwrite somebody else's map is not one to have lying
        around."""
        return self._call(
            "PUT", "/repos/%s/contents/%s" % (self.repo, path),
            {"message": message, "branch": branch,
             "content": base64.b64encode(content).decode("ascii"),
             "committer": self.author, "author": self.author})

    def open_pull_request(self, branch, title, body):
        pr = self._call("POST", "/repos/%s/pulls" % self.repo,
                        {"title": title, "body": body,
                         "head": branch, "base": self.branch})
        return pr["html_url"], pr["number"]

    # --- what the submission flow actually calls -------------------------

    def submit(self, branch, files, title, body):
        """Branch, commit each file, open a pull request. Returns its URL.

        Files are committed one call at a time rather than as a tree. That is
        slower and far simpler, and a submission is two files.
        """
        self.create_branch(branch, self.head_sha())
        for path, content in files.items():
            self.put_file(branch, path, content, title)
        return self.open_pull_request(branch, title, body)
