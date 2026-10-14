/**
 * Cross-origin access for the editor.
 *
 * The editor and this server are different origins - different ports in
 * development, probably different subdomains in production - so the browser
 * will not send the session cookie, or read the reply, without being told to.
 *
 * This failure is worth understanding because it is invisible. `whoAmI` in the
 * editor treats an unreachable server as "signed out", which is right: editing
 * a map must work with no server. But with CORS missing, a *present* server
 * looks unreachable, so the button says "Sign in to submit" forever - including
 * immediately after a successful sign-in. Nothing errors. It just never works.
 *
 * Two rules here are not style:
 *
 * - **Never `*` with credentials.** Browsers refuse the combination, and if
 *   they did not it would mean any site could read authenticated replies.
 * - **Never reflect an arbitrary Origin.** Echoing whatever asked, with
 *   credentials allowed, lets any page on the internet act as a signed-in
 *   user. The allowlist is the whole protection.
 */
import type { NextFunction, Request, Response } from 'express';

/** Parse `ALLOWED_ORIGINS`: a comma-separated list of origins. */
export function parseOrigins(value: string | undefined,
                             ...extra: string[]): string[] {
  const all = [...(value ?? '').split(','), ...extra];
  const origins = new Set<string>();
  for (const raw of all) {
    const trimmed = raw.trim();
    if (!trimmed) continue;
    try {
      // Normalised to an origin, so a trailing slash or a stray path in
      // configuration cannot stop a legitimate editor from matching.
      origins.add(new URL(trimmed).origin);
    } catch {
      // Ignored rather than fatal: one typo in a list should not take the
      // server down, and `allowed()` refusing is visible soon enough.
    }
  }
  return [...origins];
}

export function corsFor(allowed: string[]) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const origin = req.headers.origin;

    // Set whichever way this goes, and before the decision: the response
    // differs by origin either way, and it is the *refused* case that a cache
    // most needs told - storing a reply with no allow-origin header and then
    // handing it to the editor breaks sign-in in a way that looks like
    // nothing is wrong. `vary` appends rather than replacing, so an existing
    // Vary from anywhere else survives.
    res.vary('Origin');

    if (typeof origin === 'string' && allowed.includes(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Access-Control-Allow-Credentials', 'true');
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'content-type, accept');
      res.setHeader('Access-Control-Max-Age', '600');
    }

    // A preflight is answered whether or not the origin was allowed; an
    // origin that is not on the list simply gets no headers and the browser
    // stops there, which is the correct refusal.
    if (req.method === 'OPTIONS') {
      res.status(204).end();
      return;
    }

    // Everything above only governs what a browser will let a page *read*.
    // The request still ran. That was harmless while the session cookie was
    // SameSite=Lax and simply never travelled on a cross-site POST - but the
    // editor is served from a different site than this API, so the cookie has
    // to be SameSite=None for signing in to work at all, and the protection
    // Lax was quietly providing has to be made explicit.
    //
    // So: a state-changing request that declares an origin we do not know is
    // refused outright. `multipart/form-data` is CORS-safelisted, which means
    // a form on any page can POST to /submit without a preflight; without
    // this, such a page could open a pull request in the name of whoever is
    // signed in.
    //
    // Only when an origin is present. A browser always sends one on a
    // cross-site POST; curl and the tests send none, and they carry no
    // ambient session to abuse.
    if (req.method !== 'GET' && req.method !== 'HEAD' &&
        typeof origin === 'string' && !allowed.includes(origin)) {
      res.status(403).json({ error: 'origin not allowed', code: 'bad-origin' });
      return;
    }
    next();
  };
}
