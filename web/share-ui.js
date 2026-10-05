// Submitting a map without an intake server.
//
// The real path is submit-ui.js: sign in, upload, get a pull request link
// back. It needs a server to be running somewhere, and while none is, the
// editor deploys with that button hidden - a button that cannot work being
// worse than none.
//
// This is the manual stand-in. The map goes out as an Export bundle and the
// contributor uploads it to a form; whoever runs the archive works through
// those by hand with `awrbc prepare` and `awrbc publish`, which is the same
// code the server would have called.
//
// Deliberately kept to the same shape as submit-ui: handed what it needs,
// no DOM lookups of its own, so decision #47's rebuild ports it by changing
// the caller.

/**
 * Only an origin and path we produced, never one a link chose.
 *
 * The share URL arrives from a meta tag the deploy writes, so this is belt
 * and braces - but `?share=` would otherwise let a link decide where
 * somebody's map gets uploaded, which is the same reasoning intake.js
 * applies to `?intake=`.
 */
export function shareUrl(meta) {
  const given = (meta || '').trim();
  if (!given) return '';
  try {
    const url = new URL(given);
    return url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
}

/**
 * Wire up the manual submission link.
 *
 * Shows nothing at all when there is no form to point at, or when the real
 * intake server is configured - one route at a time, and the better one
 * wins.
 */
export function attachShare({ link, url, intakeBase, bundle, baseName,
                              download, notify = alert }) {
  const where = shareUrl(url);
  if (!where || intakeBase) return null;

  link.href = where;
  link.hidden = false;

  // The download is started here and the navigation is left to the anchor.
  // Awaiting the bundle first and then calling window.open would be a popup
  // by the time it ran, and blocked.
  link.addEventListener('click', async () => {
    const name = baseName();
    try {
      download(await bundle(), name);
    } catch (err) {
      notify(`Could not package the map: ${err.message}`);
      return;
    }
    notify(`Your map was saved as ${name}.\n\n` +
           'Attach that file on the page that just opened. Nothing is sent ' +
           'from here - the file is on your computer until you upload it.');
  });

  return { url: where };
}
