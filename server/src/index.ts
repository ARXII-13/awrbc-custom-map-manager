/**
 * The intake endpoint.
 *
 * Discord sign-in, and an upload that becomes a pull request. No database, no
 * ratings, no server-side rendering - those are in docs/app-architecture.md
 * and are not built.
 *
 * Everything secret lives here and nowhere else: the Discord client secret,
 * the GitHub bot token, the session key. The editor is static and holds none
 * of it.
 *
 * What this does *not* contain is any opinion about what a valid map is. That
 * is `awrbc prepare`, which is Python - see prepare.ts for why.
 */
import express from 'express';
import cookieSession from 'cookie-session';
import multer from 'multer';
import { randomBytes } from 'node:crypto';

import { corsFor, parseOrigins } from './cors.js';
import * as discord from './discord.js';
import * as github from './github.js';
import { Store, type Submission } from './db.js';
import { available, filesToCommit, prepare, PrepareFailed } from './prepare.js';

const env = (name: string, fallback = '') => process.env[name] ?? fallback;

export const config = {
  discordId: env('DISCORD_CLIENT_ID'),
  discordSecret: env('DISCORD_CLIENT_SECRET'),
  githubToken: env('GITHUB_TOKEN'),
  libraryRepo: env('LIBRARY_REPO', 'ARXII-13/awrbc-custom-map-library'),
  publicUrl: env('PUBLIC_URL', 'http://127.0.0.1:5000'),
  editorUrl: env('EDITOR_URL', 'http://127.0.0.1:8731/'),
  awrbc: env('AWRBC_COMMAND', 'awrbc'),
  // A file, on a volume that outlives the container. Inside the image it
  // would be destroyed by every deploy, silently and completely.
  dbPath: env('DB_PATH', '/data/awrbc.db'),
  // A fresh key per restart signs everybody out, which is the right failure
  // for a missing setting. A hardcoded default is the kind of thing that
  // survives into production and lets anyone forge a session.
  sessionSecret: env('SESSION_SECRET') || randomBytes(32).toString('hex'),
  insecureCookies: env('INSECURE_COOKIES') === '1',
  // The editor is a different origin, so it has to be named. EDITOR_URL is
  // included automatically because it is already the one origin we know for
  // certain is ours.
  allowedOrigins: parseOrigins(process.env['ALLOWED_ORIGINS'],
                               env('EDITOR_URL', 'http://127.0.0.1:8731/')),
  // Accept submissions with nobody signed in. Off unless asked for, because
  // what it turns off is not decoration:
  //
  //   - The author becomes whatever the file says. A signed-in submission
  //     is credited to the account that signed in precisely because a file
  //     is a claim (decision #28); open, there is nothing behind the name.
  //   - A revision of somebody else's map is checked by comparing one claim
  //     against another, so the only real gate is a person reading the pull
  //     request. `pull_request_text` says so in the body.
  //   - Rate limiting falls back to the client address, which is weaker and
  //     is shared by everyone behind one NAT.
  //
  // It exists because standing up an identity provider to find out whether
  // anyone wants the thing is the wrong order. Reachable from the internet,
  // this lets any stranger make the bot open pull requests; merging is still
  // a person, so the cost is noise rather than a corrupted archive.
  openSubmissions: env('OPEN_SUBMISSIONS') === '1',
};

/** Bigger than any real bundle; past this something is wrong or hostile. */
const MAX_UPLOAD = 8 * 1024 * 1024;

/**
 * Who to treat a submission from nobody as.
 *
 * There is no identity here, so this is two things only: a rate-limit key,
 * and an empty username. The username is empty on purpose - `awrbc prepare`
 * reads that as "nobody vouched" and publishes the name inside the file
 * instead, which keeps one source for it rather than inventing a second.
 *
 * The key is the client address, which is weaker than an account in both
 * directions: everyone behind one NAT shares a bucket, and anyone with more
 * than one address has more than one bucket. Behind a proxy it needs
 * `trust proxy` set, or every request looks like it came from the proxy.
 */
export function anonymousFrom(req: { ip?: string | undefined }) {
  return { id: `ip:${req.ip ?? 'unknown'}`, username: '' };
}

/** One a minute, ten an hour, per account. A speed bump, not a wall.
 *
 *  Counted from the submissions themselves rather than a tally beside them:
 *  two records of one fact is two things that can disagree, and the tally
 *  would be the one that is wrong. It also now survives a restart, which the
 *  in-memory version it replaces did not - that limit reset every deploy. */
const PER_MINUTE = 1;
const PER_HOUR = 10;

export function limitFrom(times: string[], now = Date.now()): string | null {
  const ms = times.map((t) => Date.parse(t)).filter(Number.isFinite);
  if (ms.filter((t) => now - t < 60_000).length >= PER_MINUTE) {
    return 'one submission a minute, please';
  }
  if (ms.filter((t) => now - t < 3_600_000).length >= PER_HOUR) {
    return 'ten submissions an hour, please';
  }
  return null;
}

/** What is missing, so a misconfigured deploy says so rather than failing at
 *  somebody's first click. */
export function missingConfig(): string[] {
  const missing: string[] = [];
  // Only needed to sign anybody in. An open server never does, so reporting
  // them missing would mean /health said "not configured" about a server that
  // is working exactly as asked.
  if (!config.openSubmissions) {
    if (!config.discordId) missing.push('DISCORD_CLIENT_ID');
    if (!config.discordSecret) missing.push('DISCORD_CLIENT_SECRET');
  }
  // Needed either way: without it nothing can be pushed anywhere.
  if (!config.githubToken) missing.push('GITHUB_TOKEN');
  return missing;
}

/** Only a path is accepted. An absolute URL would make the sign-in button an
 *  open redirect, which is how a legitimate domain ends up a phishing hop. */
export function safeNext(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') &&
         !value.startsWith('//') ? value : '';
}

export function createApp(store: Store) {
  const app = express();
  const upload = multer({
    storage: multer.memoryStorage(),
    limits: { fileSize: MAX_UPLOAD },
  });

  app.set('trust proxy', 1);
  app.use(corsFor(config.allowedOrigins));
  app.use(cookieSession({
    name: 'awrbc',
    keys: [config.sessionSecret],
    httpOnly: true,
    // The editor is served from a different site than this API - GitHub Pages
    // and this domain - so a Lax cookie would never be sent on its fetches
    // and nobody would ever appear signed in. None requires Secure, which is
    // the other reason INSECURE_COOKIES must not be set anywhere public.
    //
    // What Lax was doing for free, cors.ts now does on purpose: a
    // state-changing request from an origin not on the list is refused.
    sameSite: config.insecureCookies ? 'lax' : 'none',
    secure: !config.insecureCookies,
    maxAge: 7 * 24 * 3600 * 1000,
  }));

  app.get('/health', (_req, res) => {
    const missing = missingConfig();
    // The allowed origins are reported because getting them wrong is the
    // failure that looks like nothing happening at all.
    res.json({ ok: true, configured: missing.length === 0, missing,
               allowedOrigins: config.allowedOrigins });
  });

  // --- sign in -----------------------------------------------------------

  app.get('/auth/login', (req, res) => {
    const missing = missingConfig();
    if (missing.length) {
      res.status(503).json({ error: 'server is not configured', missing });
      return;
    }
    const state = discord.newState();
    req.session!.oauthState = state;
    req.session!.afterLogin = safeNext(req.query.next);
    res.redirect(discord.loginUrl(
      config.discordId, `${config.publicUrl.replace(/\/$/, '')}/auth/callback`,
      state));
  });

  app.get('/auth/callback', async (req, res) => {
    const expected = req.session?.oauthState;
    // Cleared before anything else, so a state cannot be replayed even if the
    // exchange below fails.
    if (req.session) req.session.oauthState = undefined;

    if (!discord.stateMatches(expected, req.query.state)) {
      res.status(400).json({ error: 'that sign-in did not come from here' });
      return;
    }
    const code = req.query.code;
    if (typeof code !== 'string' || !code) {
      res.status(400).json({ error: 'Discord sent no code' });
      return;
    }

    try {
      const token = await discord.exchange(
        code, config.discordId, config.discordSecret,
        `${config.publicUrl.replace(/\/$/, '')}/auth/callback`);
      req.session!.user = await discord.identity(token);
    } catch (e) {
      res.status(502).json({ error: (e as Error).message });
      return;
    }

    const next = req.session!.afterLogin;
    req.session!.afterLogin = undefined;
    res.redirect(next || config.editorUrl);
  });

  app.post('/auth/logout', (req, res) => {
    req.session = null;
    res.json({ ok: true });
  });

  app.get('/auth/me', (req, res) => {
    const user = req.session?.user;
    // `openSubmissions` is reported so the editor can offer Submit to someone
    // who is not signed in. It asks rather than being told at build time,
    // because the same deployed editor may point at either kind of server.
    res.json(user
      ? { signedIn: true, user, openSubmissions: config.openSubmissions }
      : { signedIn: false, openSubmissions: config.openSubmissions });
  });

  // --- submitting --------------------------------------------------------

  // Signed in *before* multer, not after. The upload middleware buffers the
  // whole file into memory as it runs, so checking afterwards meant anyone at
  // all could make this process hold 8MB per request, and meant an oversized
  // upload failed inside multer before the 401 was ever reached.
  //
  // Unless submissions are open, in which case there is nobody to check - see
  // `openSubmissions` in the config for what that gives up.
  const signedIn: express.RequestHandler = (req, res, next) => {
    if (!req.session?.user && !config.openSubmissions) {
      res.status(401).json({ error: 'sign in first', code: 'unauthenticated' });
      return;
    }
    next();
  };

  app.post('/submit', signedIn, upload.single('file'), async (req, res) => {
    const user = req.session?.user ?? anonymousFrom(req);

    const hourAgo = new Date(Date.now() - 3_600_000).toISOString();
    const slow = limitFrom(await store.submissionTimesSince(user.id, hourAgo));
    if (slow) {
      res.status(429).json({ error: slow, code: 'rate-limited' });
      return;
    }

    // The checkbox is the whole of the licence grant. Without it the archive
    // has no right to redistribute the map, and it cannot be retrofitted
    // across contributors later.
    if (req.body?.agree !== 'true') {
      res.status(400).json({ error: 'the licence confirmation is required',
                             code: 'no-licence' });
      return;
    }
    if (!req.file) {
      res.status(400).json({ error: 'no file', code: 'no-file' });
      return;
    }

    let outcome;
    try {
      outcome = await prepare(req.file.buffer, user,
                              typeof req.body?.update === 'string'
                                ? req.body.update : undefined,
                              { command: config.awrbc });
    } catch (e) {
      const detail = e instanceof PrepareFailed ? e.detail : '';
      // Ours, not theirs: say so plainly rather than blaming the upload.
      res.status(503).json({ error: `could not check that map: ` +
                                    `${(e as Error).message}`,
                             code: 'validator-unavailable', detail });
      return;
    }

    if (!outcome.ok) {
      // `folder` goes back so the editor can offer "submit as a new
      // version of that one" instead of asking somebody to retype a path
      // out of a sentence. Whether that revision is allowed is decided by
      // prepare on the next request, not here.
      res.status(422).json({ error: outcome.error, code: outcome.code,
                             folder: outcome.folder ?? '',
                             findings: outcome.findings });
      return;
    }

    const library = new github.Library(config.libraryRepo, config.githubToken);
    let pr;
    try {
      pr = await library.submit(outcome.branch, filesToCommit(outcome),
                                outcome.title, outcome.body);
    } catch (e) {
      // Already waiting for review is the submitter's situation, not a
      // server fault, so it is answered as one: 409 with the pull request
      // they already have. It used to arrive as a bare 502 "could not open
      // the pull request", which gave somebody who had simply sent the same
      // map twice nothing to act on - and no way back to a link they may
      // never have seen.
      if (e instanceof github.AlreadySubmitted) {
        res.status(409).json({
          error: 'that map is already waiting for review',
          code: 'already-submitted',
          pullRequest: e.pullRequest,
          number: e.number,
        });
        return;
      }
      res.status(502).json({
        error: `could not open the pull request: ${(e as Error).message}`,
        code: 'github' });
      return;
    }

    // Recorded after the pull request exists, not before: a row claiming a
    // submission that was never opened would show the contributor a link to
    // nothing, and would count against their rate limit for an hour.
    //
    // A failure here must not fail the submission. The pull request is open
    // either way and that is the thing that matters; losing the row costs
    // this person their list, which is worth a log line and not a 500 on a
    // map that was accepted.
    try {
      await store.recordSubmission({
        discordId: user.id,
        username: user.username,
        mapName: outcome.name,
        folder: outcome.folder,
        version: outcome.version,
        contentHash: outcome.id,
        branch: outcome.branch,
        prNumber: pr.number,
        prUrl: pr.url,
        createdAt: new Date().toISOString(),
      });
    } catch (e) {
      console.error(`could not record submission ${pr.number}:`,
                    (e as Error).message);
    }

    res.json({
      ok: true,
      pullRequest: pr.url,
      number: pr.number,
      path: outcome.path,
      kind: outcome.kind,
      warnings: outcome.warnings,
      hasPreview: outcome.hasPreview,
    });
  });

  /**
   * What this account has submitted, and where each one got to.
   *
   * The rows are ours; the outcomes are GitHub's. Asked fresh on each call
   * and cached only as a fallback - a `state` stored as though it were a fact
   * would drift from the pull request it describes, and the copy people read
   * would be the wrong one (decision #49).
   *
   * `asOf` is returned rather than hidden: a list that cannot say how old it
   * is invites being believed when it should not be.
   */
  app.get('/submissions', signedIn, async (req, res) => {
    const user = req.session?.user;
    if (!user) {
      // Only reachable with OPEN_SUBMISSIONS on, where `signedIn` lets
      // everyone through. There is no account to list anything for.
      res.json({ submissions: [], asOf: null, live: false });
      return;
    }

    const mine = await store.submissionsFor(user.id);
    const numbers = mine.map((m) => m.prNumber);

    let states = new Map<number, 'open' | 'merged' | 'closed'>();
    let live = false;
    try {
      const library = new github.Library(config.libraryRepo,
                                         config.githubToken);
      states = await library.pullRequestStates();
      live = true;
      const checkedAt = new Date().toISOString();
      await store.cachePrStates(
        numbers.filter((n) => states.has(n))
               .map((n) => ({ prNumber: n, state: states.get(n)!, checkedAt })));
    } catch {
      // GitHub unreachable, or the token is unhappy. Answer from what was
      // last seen rather than failing the page - a stale list with its age
      // on it is more use than an error.
    }

    const cached = await store.cachedPrStates(numbers);
    res.json({
      live,
      asOf: live ? new Date().toISOString() : null,
      submissions: mine.map((m) => {
        const known = states.get(m.prNumber);
        const fallback = cached.get(m.prNumber);
        return {
          mapName: m.mapName,
          folder: m.folder,
          version: m.version,
          prNumber: m.prNumber,
          pullRequest: m.prUrl,
          createdAt: m.createdAt,
          // Never seen is not the same as open, and saying "open" about a
          // pull request nobody has looked up is how a list starts lying.
          state: known ?? fallback?.state ?? 'unknown',
          stateAsOf: known ? new Date().toISOString()
                           : fallback?.checkedAt ?? null,
        };
      }),
    });
  });

  // An unknown route answers JSON too. Express's default is an HTML page,
  // and a client that only ever parses JSON reads that as a transport
  // failure rather than as "no such endpoint".
  app.use((_req, res) => {
    res.status(404).json({ error: 'no such endpoint', code: 'not-found' });
  });

  // Errors answer JSON, like every other response here. Without this Express
  // falls back to its own handler, which sends an HTML page with a stack
  // trace in it - unreadable to the editor, which parses JSON, and more than
  // a stranger needs to know about the inside of this process.
  //
  // Multer's "file too large" arrives here rather than at the route, because
  // it is thrown while the middleware reads the body.
  app.use((err: Error & { code?: string }, _req: express.Request,
           res: express.Response, _next: express.NextFunction) => {
    if (err?.code === 'LIMIT_FILE_SIZE') {
      res.status(413).json({ error: `that upload is larger than the ${MAX_UPLOAD} byte limit`,
                             code: 'too-large' });
      return;
    }
    if (err?.name === 'MulterError') {
      res.status(400).json({ error: 'that upload was not readable as a file',
                             code: 'bad-upload' });
      return;
    }
    console.error('unhandled:', err);
    res.status(500).json({ error: 'something went wrong', code: 'internal' });
  });

  return app;
}

/* c8 ignore start -- the entry point, exercised by running it */
const isMain = process.argv[1] &&
  import.meta.url === new URL(`file://${process.argv[1]}`).href;

if (isMain) {
  const missing = missingConfig();
  if (missing.length) {
    console.warn(`warning: not configured; missing ${missing.join(', ')}`);
  }
  const problem = await available(config.awrbc);
  if (problem) {
    // The validator being absent is not something to discover at the first
    // upload, when somebody has already written a map.
    console.error(`fatal: cannot run '${config.awrbc}': ${problem}`);
    console.error('Install the tool: pip install -e . (or set AWRBC_COMMAND)');
    process.exit(1);
  }
  let store: Store;
  try {
    store = await Store.open(config.dbPath);
  } catch (e) {
    // Same reasoning as the validator check above: a database that cannot be
    // opened is not something to find out at somebody's first submission.
    console.error(`fatal: cannot open ${config.dbPath}: ${(e as Error).message}`);
    console.error('DB_PATH must be on a writable volume that outlives the '
                  + 'container.');
    process.exit(1);
  }
  const port = Number(process.env.PORT ?? 5000);
  createApp(store).listen(port, () => console.log(`intake on :${port}`));
}
/* c8 ignore stop */
