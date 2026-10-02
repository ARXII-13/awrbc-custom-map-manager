// Signing in, and submitting a map to the archive.
//
// The whole of the contributor path that does not involve git: sign in with
// Discord, upload, get a pull request link back. The editor holds nothing
// secret - the session is a cookie the intake server set, and this only ever
// asks it who you are.
//
// Deliberately small, and deliberately free of DOM: the editor is being
// rebuilt as a framework application (decision #47), and this should port by
// changing who calls it rather than by being rewritten.

/**
 * Where the intake server is.
 *
 * `?intake=` exists so the editor can be pointed at a local server while
 * developing without editing a file. Only an origin is taken from it - a full
 * URL with a path would let a link decide where somebody's map gets uploaded.
 */
export function intakeBase(search = location.search, fallback = '') {
  const given = new URLSearchParams(search).get('intake');
  if (!given) return fallback;
  try {
    return new URL(given).origin;
  } catch {
    return fallback;
  }
}

/** Nobody is signed in, and that is not an error. */
export const SIGNED_OUT = Object.freeze({ signedIn: false, user: null });

/**
 * Who is signed in, as far as the server is concerned.
 *
 * Never throws. An intake server that is down, misconfigured or simply not
 * running must leave the editor working - editing a map has never needed one
 * (decision #50), so a failure here is "signed out", not a broken page.
 */
export async function whoAmI(base, fetchImpl = fetch) {
  if (!base) return SIGNED_OUT;
  try {
    const res = await fetchImpl(`${base}/auth/me`, {
      credentials: 'include',
      headers: { accept: 'application/json' },
    });
    if (!res.ok) return SIGNED_OUT;
    const body = await res.json();
    return body?.signedIn
      ? { signedIn: true, user: body.user }
      : SIGNED_OUT;
  } catch {
    return SIGNED_OUT;
  }
}

/** Where to send the browser to sign in, returning to this page afterwards. */
export function signInUrl(base) {
  return `${base}/auth/login`;
}

export async function signOut(base, fetchImpl = fetch) {
  try {
    await fetchImpl(`${base}/auth/logout`, {
      method: 'POST', credentials: 'include',
    });
  } catch { /* already effectively signed out */ }
}

/**
 * What came back from a submission that was not accepted.
 *
 * `findings` carries every validation problem at once, because fixing one
 * thing per round trip is miserable when the round trip is a person opening
 * their editor again.
 */
export class SubmitRejected extends Error {
  constructor(message, code, findings) {
    super(message);
    this.name = 'SubmitRejected';
    this.code = code;
    this.findings = findings ?? [];
  }
}

/**
 * Upload a bundle.
 *
 * `agree` is the licence confirmation and is passed through rather than
 * assumed: the server refuses without it, and a client that quietly sent
 * `true` on somebody's behalf would be manufacturing consent to publish their
 * work under CC BY.
 */
export async function submit(base, { bundle, agree, update, fetchImpl = fetch }) {
  const form = new FormData();
  form.set('file', bundle, 'bundle.zip');
  form.set('agree', agree === true ? 'true' : 'false');
  if (update) form.set('update', update);

  let res;
  try {
    res = await fetchImpl(`${base}/submit`, {
      method: 'POST', body: form, credentials: 'include',
    });
  } catch (e) {
    throw new SubmitRejected(
      `could not reach the submission server: ${e.message}`, 'unreachable');
  }

  let body = null;
  try {
    body = await res.json();
  } catch { /* a proxy error page, most likely */ }

  if (!res.ok) {
    throw new SubmitRejected(
      body?.error || `the server said ${res.status}`,
      body?.code || String(res.status),
      body?.findings);
  }
  return body;
}

/**
 * One line per problem, for showing a person.
 *
 * Severity is dropped on purpose: everything in `findings` on a rejection is
 * blocking, and labelling some of them "error" invites the question of what
 * the others are.
 */
export function explain(rejection) {
  if (!rejection.findings.length) return rejection.message;
  return [rejection.message, ...rejection.findings.map(
    (f) => `  ${f.code}: ${f.message}`)].join('\n');
}
