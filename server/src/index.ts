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
};

/** Bigger than any real bundle; past this something is wrong or hostile. */
const MAX_UPLOAD = 8 * 1024 * 1024;

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
  if (!config.discordId) missing.push('DISCORD_CLIENT_ID');
  if (!config.discordSecret) missing.push('DISCORD_CLIENT_SECRET');
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
    res.json(user ? { signedIn: true, user } : { signedIn: false });
  });

  // --- submitting --------------------------------------------------------

  app.post('/submit', upload.single('file'), async (req, res) => {
    const user = req.session?.user;
    if (!user) {
      res.status(401).json({ error: 'sign in first', code: 'unauthenticated' });
      return;
    }

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
      res.status(422).json({ error: outcome.error, code: outcome.code,
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
