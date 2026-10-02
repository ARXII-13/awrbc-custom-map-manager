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

    if (typeof origin === 'string' && allowed.includes(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Access-Control-Allow-Credentials', 'true');
      // Without this, a cache can serve one origin's response to another.
      res.setHeader('Vary', 'Origin');
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
    next();
  };
}
