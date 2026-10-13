// What this browser remembers about maps it has sent.
//
// A contributor submits without an account - the open-submissions path does
// not sign anyone in at all, and even Discord sign-in (decision #28) gives the
// archive an identity, not the submitter a dashboard. So the pull request URL
// that comes back is the only handle they will ever have on their own
// submission. It used to be announced in a `confirm()` and lost the instant
// that was dismissed, which for an anonymous contributor means lost for good:
// no account to look it up from, no email, and the archive deliberately does
// not know who they are.
//
// This is a convenience, not a record. localStorage is per-browser: it does
// not follow anyone to another device, and clearing site data empties it. The
// pull request is the durable thing and this only points at it, so nothing
// here is ever authoritative about anything.
//
// No DOM, so it is testable the way the rest of the editor is (decision #48).

const KEY = 'awrbc.submissions';
const SCHEMA = 1;

// Enough to cover anyone's session, small enough that a corrupt or hostile
// value cannot grow without bound. Oldest falls off the end.
const LIMIT = 25;

/** The browser's store, or null where there isn't one.
 *
 *  Private windows, disabled site data and sandboxed frames all make this
 *  throw on *access*, not on use - so it is reached for inside a try, and
 *  everything below treats "no storage" as "no history" rather than failing.
 */
function store(storage) {
  try {
    return storage ?? globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/**
 * Every remembered submission, newest first.
 *
 * Anything unreadable reads as empty rather than throwing. The value is
 * user-writable and survives across versions of this code, so it is treated as
 * untrusted input: wrong schema, wrong shape, or a half-written string all
 * mean "nothing remembered" - which costs a list and breaks nothing.
 */
export function load(storage) {
  const s = store(storage);
  if (!s) return [];
  let raw;
  try {
    raw = s.getItem(KEY);
  } catch {
    return [];
  }
  if (!raw) return [];
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!parsed || parsed.schema !== SCHEMA || !Array.isArray(parsed.items)) {
    return [];
  }
  return parsed.items.filter(ok).slice(0, LIMIT);
}

/** One entry worth showing: somewhere to go, and something to call it. */
function ok(item) {
  return !!item && typeof item.url === 'string' &&
         // Only ever a link out to the archive's host. A stored value is
         // user-writable, and this ends up in an href - `javascript:` in
         // there would run on click.
         (item.url.startsWith('https://') || item.url.startsWith('http://')) &&
         typeof item.name === 'string';
}

/**
 * Record one submission and return the new list.
 *
 * Keyed on the pull request URL: submitting a revision opens a second pull
 * request and earns a second row, but the same one recorded twice (a retry, a
 * double click) replaces rather than duplicates.
 */
export function remember(entry, storage) {
  const item = {
    url: String(entry.url ?? ''),
    number: Number(entry.number) || 0,
    name: String(entry.name ?? 'map'),
    path: String(entry.path ?? ''),
    kind: String(entry.kind ?? ''),
    at: entry.at ?? new Date().toISOString(),
  };
  if (!ok(item)) return load(storage);

  const items = [item, ...load(storage).filter((i) => i.url !== item.url)]
    .slice(0, LIMIT);
  const s = store(storage);
  if (s) {
    try {
      s.setItem(KEY, JSON.stringify({ schema: SCHEMA, items }));
    } catch {
      // Full, or storage refused. The list is still right for this page, and
      // the pull request is open either way - which is the thing that
      // actually matters. Nothing to tell the user about.
    }
  }
  return items;
}

/** Forget everything. Offered because this is the submitter's own history on
 *  what may be a shared browser, and there is no account to delete it from. */
export function clear(storage) {
  const s = store(storage);
  if (!s) return;
  try {
    s.removeItem(KEY);
  } catch {
    // Nothing to do and nothing to say: the caller re-renders from load(),
    // which will report whatever actually survived.
  }
}
