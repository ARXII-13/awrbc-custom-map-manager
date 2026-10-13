/**
 * Opening a pull request on the library, as a bot.
 *
 * The whole reason this exists: a contributor should never need a GitHub
 * account, let alone know git. They upload a map; this does the branch, the
 * commits and the pull request under a bot identity.
 *
 * Only the four calls it needs, over the REST API. No SDK - a dependency that
 * holds a push token is one worth not having.
 */
const API = 'https://api.github.com';
const TIMEOUT = 30_000;

export class GitHubError extends Error {
  constructor(readonly status: number, message: string, readonly url = '') {
    // The url is in the message because a GitHub failure is read from a log,
    // where "which call" is most of the diagnosis. It stays a field too, so a
    // caller can branch on it without parsing prose.
    super(`GitHub ${status}: ${message}${url ? ` (${url})` : ''}`);
    this.name = 'GitHubError';
  }
}

/**
 * The submitter already has this map awaiting review.
 *
 * Branch names are derived from the map, not from the moment - `submit/<slug>-
 * v<n>-<author>` - so sending the same map twice asks GitHub to create a ref
 * that is already there. That is a recoverable, ordinary thing for somebody to
 * do, usually because they never saw the pull request link or assumed the
 * first attempt failed. Reported as itself rather than folded into "could not
 * open the pull request", which told them nothing they could act on.
 */
export class AlreadySubmitted extends Error {
  constructor(readonly branch: string,
              readonly pullRequest = '',
              readonly number = 0) {
    super('this map is already waiting for review');
    this.name = 'AlreadySubmitted';
  }
}

export interface Committer {
  name: string;
  email: string;
}

export class Library {
  constructor(
    private readonly repo: string,          // "owner/name"
    private readonly token: string,
    private readonly branch = 'main',
    // What appears in `git log`. A bot that commits as a person is a bot that
    // makes history lie about who wrote a map.
    private readonly committer: Committer = {
      name: 'awrbc-bot',
      email: 'awrbc-bot@users.noreply.github.com',
    },
  ) {}

  private async call<T>(method: string, path: string,
                        body?: unknown): Promise<T> {
    const url = path.startsWith('http') ? path : API + path;
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), TIMEOUT);
    let res: Response;
    try {
      res = await fetch(url, {
        method,
        signal: abort.signal,
        headers: {
          authorization: `Bearer ${this.token}`,
          accept: 'application/vnd.github+json',
          'x-github-api-version': '2022-11-28',
          'user-agent': 'awrbc-intake',
          ...(body === undefined ? {} : { 'content-type': 'application/json' }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (e) {
      throw new GitHubError(0, (e as Error).message, url);
    } finally {
      clearTimeout(timer);
    }

    if (!res.ok) {
      throw new GitHubError(res.status, (await res.text()).slice(0, 400), url);
    }
    const text = await res.text();
    return (text ? JSON.parse(text) : {}) as T;
  }

  async headSha(): Promise<string> {
    const ref = await this.call<{ object: { sha: string } }>(
      'GET', `/repos/${this.repo}/git/ref/heads/${this.branch}`);
    return ref.object.sha;
  }

  async createBranch(name: string, fromSha: string): Promise<void> {
    await this.call('POST', `/repos/${this.repo}/git/refs`,
                    { ref: `refs/heads/${name}`, sha: fromSha });
  }

  /** The open pull request for a branch, if there is one.
   *
   *  Best effort on purpose: it exists to put a link in an error message, so
   *  a failure here must not replace the error being explained with a worse
   *  one about the explanation. */
  async openPullRequestFor(branch: string):
      Promise<{ url: string; number: number } | null> {
    const owner = this.repo.split('/')[0];
    try {
      const found = await this.call<{ html_url: string; number: number }[]>(
        'GET', `/repos/${this.repo}/pulls?state=open&head=`
               + encodeURIComponent(`${owner}:${branch}`));
      const pr = found[0];
      return pr ? { url: pr.html_url, number: pr.number } : null;
    } catch {
      return null;
    }
  }

  /**
   * Create a file on a branch.
   *
   * Deliberately cannot update an existing one: every submission is a new
   * path, and a call that could silently overwrite somebody else's map is not
   * one to leave lying around.
   */
  async putFile(branch: string, path: string, content: Buffer,
                message: string): Promise<void> {
    await this.call('PUT',
      `/repos/${this.repo}/contents/${encodeURI(path)}`, {
        message, branch,
        content: content.toString('base64'),
        committer: this.committer,
        author: this.committer,
      });
  }

  async openPullRequest(branch: string, title: string,
                        body: string): Promise<{ url: string; number: number }> {
    const pr = await this.call<{ html_url: string; number: number }>(
      'POST', `/repos/${this.repo}/pulls`,
      { title, body, head: branch, base: this.branch });
    return { url: pr.html_url, number: pr.number };
  }

  /** Branch, commit each file, open the pull request. A submission is two
   *  files, so committing them one call at a time is simpler than a tree and
   *  costs nothing that matters. */
  async submit(branch: string, files: Record<string, Buffer>, title: string,
               body: string): Promise<{ url: string; number: number }> {
    try {
      await this.createBranch(branch, await this.headSha());
    } catch (e) {
      // 422 "Reference already exists" is the only failure here that is about
      // the submitter rather than about us, so it is the only one translated.
      // Everything else stays a GitHubError and reads as a server fault,
      // because that is what it is.
      if (e instanceof GitHubError && e.status === 422 &&
          /Reference already exists/i.test(e.message)) {
        const pr = await this.openPullRequestFor(branch);
        throw new AlreadySubmitted(branch, pr?.url ?? '', pr?.number ?? 0);
      }
      throw e;
    }
    for (const [path, content] of Object.entries(files)) {
      await this.putFile(branch, path, content, title);
    }
    return this.openPullRequest(branch, title, body);
  }
}
