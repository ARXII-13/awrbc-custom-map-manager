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
    await this.createBranch(branch, await this.headSha());
    for (const [path, content] of Object.entries(files)) {
      await this.putFile(branch, path, content, title);
    }
    return this.openPullRequest(branch, title, body);
  }
}
