/**
 * Discord sign-in.
 *
 * The editor is static and holds nothing secret, so the OAuth exchange happens
 * here and the browser only ever gets a session cookie.
 *
 * Only the `identify` scope - id, username, avatar. Not email, not guilds. An
 * endpoint that asks for more than it uses leaks more than it needs to when it
 * is breached.
 *
 * The Discord id never reaches the archive (decision #44). It lives in the
 * session and in the pull request body for a reviewer; what gets committed is
 * a display name.
 */
import { randomBytes, timingSafeEqual } from 'node:crypto';

const AUTHORIZE = 'https://discord.com/api/oauth2/authorize';
const TOKEN = 'https://discord.com/api/oauth2/token';
const ME = 'https://discord.com/api/v10/users/@me';

const SCOPE = 'identify';
const TIMEOUT = 20_000;

export interface Identity {
  id: string;
  username: string;
  avatar: string | null;
}

export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuthError';
  }
}

export function newState(): string {
  return randomBytes(24).toString('base64url');
}

/**
 * Compare a returned `state` against the stored one.
 *
 * Constant time, and false when either side is missing. Without this check a
 * crafted callback URL signs a victim into the attacker's account, and every
 * map they then upload carries the attacker's name. It costs one random string
 * and one comparison.
 */
export function stateMatches(expected: unknown, got: unknown): boolean {
  if (typeof expected !== 'string' || typeof got !== 'string') return false;
  // Compare the buffers' lengths, not the strings'. timingSafeEqual throws
  // when its inputs differ in *bytes*, and one multibyte character makes two
  // strings of equal length differ in bytes - so `?state=` with an accent in
  // it used to raise a RangeError out of the callback instead of answering
  // false. `got` comes straight off the query string, so it is a stranger's
  // to choose.
  const a = Buffer.from(expected, 'utf8');
  const b = Buffer.from(got, 'utf8');
  if (a.length === 0 || a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export function loginUrl(clientId: string, redirectUri: string,
                         state: string): string {
  const q = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: SCOPE,
    state,
  });
  return `${AUTHORIZE}?${q.toString()}`;
}

async function withTimeout(url: string, init: RequestInit): Promise<Response> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT);
  try {
    return await fetch(url, { ...init, signal: abort.signal });
  } catch (e) {
    throw new AuthError(`could not reach Discord: ${(e as Error).message}`);
  } finally {
    clearTimeout(timer);
  }
}

/** Authorization code -> access token. */
export async function exchange(code: string, clientId: string,
                               clientSecret: string,
                               redirectUri: string): Promise<string> {
  const res = await withTimeout(TOKEN, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      grant_type: 'authorization_code',
      code,
      redirect_uri: redirectUri,
    }).toString(),
  });
  if (!res.ok) {
    throw new AuthError(
      `Discord refused the exchange (${res.status}): ` +
      `${(await res.text()).slice(0, 200)}`);
  }
  const body = await res.json() as { access_token?: string };
  if (!body.access_token) throw new AuthError('no access token in the reply');
  return body.access_token;
}

/** Who signed in. The token is used once here and then dropped - a token held
 *  is a token that can leak. */
export async function identity(accessToken: string): Promise<Identity> {
  const res = await withTimeout(ME, {
    headers: { authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    throw new AuthError(`Discord would not say who this is (${res.status})`);
  }
  const who = await res.json() as {
    id?: string; username?: string; global_name?: string; avatar?: string | null;
  };
  if (!who.id) throw new AuthError('Discord returned no user id');
  return {
    id: String(who.id),
    username: who.global_name || who.username || 'someone',
    avatar: who.avatar ?? null,
  };
}
