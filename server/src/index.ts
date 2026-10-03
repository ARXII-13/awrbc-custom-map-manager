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

/** One a minute, ten an hour, per account. In memory, so it resets on restart
 *  and does not survive two processes - honest for one small instance, and
 *  the first thing to replace when there is a database. A speed bump, not a
 *  wall. */
const PER_MINUTE = 1;
const PER_HOUR = 10;
const recent = new Map<string, number[]>();

export function rateLimited(userId: string, now = Date.now()): string | null {
  const seen = (recent.get(userId) ?? []).filter((t) => now - t < 3_600_000);
  recent.set(userId, seen);
  if (seen.filter((t) => now - t < 60_000).length >= PER_MINUTE) {
    return 'one submission a minute, please';
  }
  if (seen.length >= PER_HOUR) return 'ten submissions an hour, please';
  return null;
}

export function recordSubmission(userId: string, now = Date.now()): void {
  recent.set(userId, [...(recent.get(userId) ?? []), now]);
}

export function resetLimits(): void {
  recent.clear();
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

export function createApp() {
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
    sameSite: 'lax',
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

    const slow = rateLimited(user.id);
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
      res.status(502).json({
        error: `could not open the pull request: ${(e as Error).message}`,
        code: 'github' });
      return;
    }

    recordSubmission(user.id);
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
  const port = Number(process.env.PORT ?? 5000);
  createApp().listen(port, () => console.log(`intake on :${port}`));
}
/* c8 ignore stop */
