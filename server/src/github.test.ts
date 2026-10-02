/**
 * Talking to GitHub as the bot.
 *
 * This is the only code here that writes somewhere public, with a token that
 * can push. A bug in it does not fail loudly on a developer's machine - it
 * commits the wrong bytes to a branch in somebody else's repository, or
 * attributes a map to the wrong person, or puts a push token in a log.
 *
 * `fetch` is stubbed rather than a server being stood up, because what matters
 * is the shape of the request: which method, which path, what is in the body,
 * and which headers carry the token. A local server would prove the same
 * things through one more layer and make the assertions harder to read.
 */
import assert from 'node:assert/strict';
import { afterEach, describe, it } from 'node:test';

import { GitHubError, Library } from './github.js';

const TOKEN = 'ghp_notarealtoken';

interface Seen {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

/** Answer each call in turn, recording what was asked. */
function stub(replies: Array<{ status?: number; body?: unknown } | Error>) {
  const seen: Seen[] = [];
  let i = 0;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    const reply = replies[Math.min(i, replies.length - 1)];
    i += 1;
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(init.headers ?? {})) {
      headers[k.toLowerCase()] = String(v);
    }
    seen.push({
      method: init.method!, url: String(url), headers,
      body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
    });
    if (reply instanceof Error) throw reply;
    const status = reply?.status ?? 200;
    const text = reply?.body === undefined ? '' : JSON.stringify(reply.body);
    return new Response(text, { status });
  }) as unknown as typeof fetch;
  return seen;
}

const library = () => new Library('owner/lib', TOKEN);

const BOT = { name: 'awrbc-bot', email: 'awrbc-bot@users.noreply.github.com' };

describe('reading the branch head', () => {
  it('returns the sha the ref points at', async () => {
    const seen = stub([{ body: { object: { sha: 'abc123' } } }]);
    assert.equal(await library().headSha(), 'abc123');
    assert.equal(seen[0]!.method, 'GET');
    assert.match(seen[0]!.url, /\/repos\/owner\/lib\/git\/ref\/heads\/main$/);
  });

  it('sends the token and the pinned API version', async () => {
    const seen = stub([{ body: { object: { sha: 'abc123' } } }]);
    await library().headSha();
    assert.equal(seen[0]!.headers['authorization'], `Bearer ${TOKEN}`);
    assert.equal(seen[0]!.headers['x-github-api-version'], '2022-11-28');
    assert.equal(seen[0]!.headers['accept'], 'application/vnd.github+json');
  });
});

describe('creating a branch', () => {
  it('names it under refs/heads and points it at the sha given', async () => {
    const seen = stub([{ body: {} }]);
    await library().createBranch('submit/pat/daibi', 'abc123');
    assert.equal(seen[0]!.method, 'POST');
    assert.match(seen[0]!.url, /\/repos\/owner\/lib\/git\/refs$/);
    assert.deepEqual(seen[0]!.body,
                     { ref: 'refs/heads/submit/pat/daibi', sha: 'abc123' });
  });
});

describe('committing a file', () => {
  const put = async (path: string, content = Buffer.from('{"a":1}')) => {
    const seen = stub([{ body: {} }]);
    await library().putFile('a-branch', path, content, 'Add a map');
    return seen[0]!;
  };

  it('sends the content base64 encoded', async () => {
    const call = await put('maps/2p/daibi/v1.json');
    const body = call.body as { content: string };
    assert.equal(Buffer.from(body.content, 'base64').toString('utf8'),
                 '{"a":1}');
  });

  it('survives bytes that are not text', async () => {
    // A preview is a PNG. Anything that round-trips it through a string
    // corrupts it, and a corrupt preview is not what a reviewer would notice.
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00, 0xff, 0xfe]);
    const call = await put('maps/2p/daibi/v1.png', png);
    const body = call.body as { content: string };
    assert.deepEqual(Buffer.from(body.content, 'base64'), png);
  });

  it('commits as the bot, as author and as committer', async () => {
    // A bot that commits as a person makes git log lie about who wrote a map.
    const call = await put('maps/2p/daibi/v1.json');
    const body = call.body as { author: unknown; committer: unknown };
    assert.deepEqual(body.committer, BOT);
    assert.deepEqual(body.author, BOT);
  });

  it('puts the file on the branch, never on the default one', async () => {
    const call = await put('maps/2p/daibi/v1.json');
    assert.equal((call.body as { branch: string }).branch, 'a-branch');
  });

  it('uses PUT with no blob sha, so it creates and cannot overwrite', async () => {
    // Updating an existing file needs that file's sha; without one GitHub
    // refuses. That refusal is the guard against clobbering somebody's map,
    // so sending a sha here would quietly remove it.
    const call = await put('maps/2p/daibi/v1.json');
    assert.equal(call.method, 'PUT');
    assert.equal((call.body as { sha?: string }).sha, undefined);
  });

  it('escapes a path that needs it', async () => {
    const call = await put('maps/2p/a map/v1.json');
    assert.match(call.url, /\/contents\/maps\/2p\/a%20map\/v1\.json$/);
  });
});

describe('opening the pull request', () => {
  it('returns the human url and the number', async () => {
    const seen = stub([
      { body: { html_url: 'https://github.com/x/1', number: 7 } }]);
    const pr = await library().openPullRequest('a-branch', 'Add Daibi', 'by pat');
    assert.deepEqual(pr, { url: 'https://github.com/x/1', number: 7 });
    assert.deepEqual(seen[0]!.body, {
      title: 'Add Daibi', body: 'by pat', head: 'a-branch', base: 'main',
    });
  });
});

describe('a whole submission', () => {
  const files = {
    'maps/2p/daibi/v1.json': Buffer.from('{}'),
    'maps/2p/daibi/v1.png': Buffer.from([0x89, 0x50]),
  };

  it('reads the head, branches, commits each file, then opens the PR', async () => {
    const seen = stub([
      { body: { object: { sha: 'head1' } } },
      { body: {} }, { body: {} }, { body: {} },
      { body: { html_url: 'https://github.com/x/2', number: 9 } },
    ]);
    const pr = await library().submit('b', files, 'Add Daibi', 'by pat');

    assert.equal(seen.length, 5, 'head, branch, two files, pull request');
    assert.match(seen[0]!.url, /git\/ref\/heads\/main$/);
    assert.match(seen[1]!.url, /git\/refs$/);
    assert.equal((seen[1]!.body as { sha: string }).sha, 'head1',
                 'the branch must start from the head it just read');
    assert.equal(seen[2]!.method, 'PUT');
    assert.equal(seen[3]!.method, 'PUT');
    assert.match(seen[4]!.url, /\/pulls$/);
    assert.deepEqual(pr, { url: 'https://github.com/x/2', number: 9 });
  });

  it('commits every file it was given, under their own paths', async () => {
    const seen = stub([
      { body: { object: { sha: 'head1' } } },
      { body: {} }, { body: {} }, { body: {} },
      { body: { html_url: 'https://github.com/x/2', number: 9 } },
    ]);
    await library().submit('b', files, 'Add Daibi', 'by pat');

    const committed = seen.filter((s) => s.method === 'PUT')
                          .map((s) => decodeURI(s.url.split('/contents/')[1]!));
    assert.deepEqual(committed.sort(), Object.keys(files).sort());
  });

  it('stops at the first failure rather than carrying on', async () => {
    // Committing onto a branch that was never created is a pile of 404s, and
    // the pull request would open against nothing.
    const seen = stub([
      { body: { object: { sha: 'head1' } } },
      { status: 422, body: { message: 'Reference already exists' } },
    ]);
    await assert.rejects(() => library().submit('b', files, 't', 'b'),
                         (e: GitHubError) => e.status === 422);
    assert.equal(seen.length, 2,
                 'nothing was committed after the branch failed');
  });
});

describe('when GitHub says no', () => {
  it('carries the status, and which call it was, into the message', async () => {
    stub([{ status: 404, body: { message: 'Not Found' } }]);
    await assert.rejects(() => library().headSha(), (e: GitHubError) => {
      assert.equal(e.status, 404);
      assert.match(e.message, /Not Found/);
      assert.match(e.message, /git\/ref\/heads\/main/);
      return true;
    });
  });

  it('reports a network failure as status 0', async () => {
    stub([new TypeError('fetch failed')]);
    await assert.rejects(() => library().headSha(), (e: GitHubError) => {
      assert.equal(e.status, 0);
      assert.equal(e.name, 'GitHubError');
      return true;
    });
  });

  it('never puts the token in the error', async () => {
    // These get read from logs and pasted into issues.
    stub([{ status: 401, body: { message: 'Bad credentials' } }]);
    await assert.rejects(() => library().headSha(), (e: GitHubError) => {
      assert.ok(!e.message.includes(TOKEN), `token leaked: ${e.message}`);
      assert.ok(!String(e.stack).includes(TOKEN), 'token leaked via stack');
      return true;
    });
  });

  it('does not choke on a success with an empty body', async () => {
    // createBranch and putFile are called for their effect, and GitHub may
    // answer with nothing at all - where JSON.parse('') would throw.
    stub([{ body: undefined }]);
    await assert.doesNotReject(() => library().createBranch('b', 'sha'));
  });
});
