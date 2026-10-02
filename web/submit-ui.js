// The Submit button.
//
// Separated from index.html because this is the one piece of the editor that
// talks to a server, and because the editor is being rebuilt as a framework
// application (decision #47) - this should port by changing who calls
// `attachSubmit` rather than by being rewritten.
//
// Everything here degrades to "no Submit button". Editing a map has never
// needed a server (decision #50), so an intake server that is down, absent or
// unconfigured must leave the editor exactly as useful as it was.

import * as intake from './intake.js';

/**
 * Wire up sign-in and submission.
 *
 * Takes what it needs rather than reaching for globals: `bundle()` builds the
 * same zip Export bundle produces, and `currentDoc()` returns the document
 * being edited. The caller owns both, which is what keeps this portable.
 */
export function attachSubmit({ base, button, label, bundle, currentDoc, stats }) {
  // No intake server configured: no Submit button. A checkout, or a deploy
  // without one, is edit-and-export only - which is a complete tool on its
  // own. A button that cannot work is worse than no button.
  if (!base) return { refresh: async () => {} };

  let who = intake.SIGNED_OUT;

  function show() {
    button.hidden = false;
    if (who.signedIn) {
      button.textContent = 'Submit';
      label.hidden = false;
      label.textContent = 'as ' + who.user.username;
      label.title = 'Submitting opens a pull request on the archive';
    } else {
      button.textContent = 'Sign in to submit';
      label.hidden = true;
    }
  }

  async function refresh() {
    who = await intake.whoAmI(base);
    show();
  }

  /** Reasons the archive would refuse this, checked before uploading.
   *
   *  Not a substitute for the server's answer - the browser is not trusted and
   *  the server checks again. It is here so the common mistakes cost a dialog
   *  rather than a round trip and a rejection. */
  function localProblems(doc) {
    const problems = [];
    const s = stats(doc);
    if (!s.valid) {
      problems.push('This map is not playable yet:\n  ' +
                    s.reasons.join('\n  '));
    }
    if (!doc.name || doc.name === 'Untitled') {
      problems.push('Give the map a name first. It becomes the map’s ' +
                    'address in the archive, and "Untitled" would collide ' +
                    'with the next unnamed map somebody submits.');
    }
    if (!doc.author || doc.author === 'anonymous') {
      problems.push('Fill in the author field, so the map is credited to ' +
                    'you rather than to "anonymous".');
    }
    return problems;
  }

  /** The licence confirmation.
   *
   *  Asked plainly, every time. This is the grant of rights that lets the
   *  archive redistribute the map at all, and it cannot be taken back once a
   *  map is merged - so a checkbox nobody reads would not be consent. */
  function confirmLicence(name) {
    return confirm(
      'Submit "' + name + '" to the public archive?\n\n' +
      'By submitting you confirm this map is your own work, and you license ' +
      'it under CC BY 4.0 so anyone may share and adapt it with credit.\n\n' +
      'The archive is public and permanent: a merged map stays in its ' +
      'history even if the file is later removed.');
  }

  button.onclick = async () => {
    if (!who.signedIn) {
      location.href = intake.signInUrl(base);
      return;
    }

    const doc = currentDoc();
    const problems = localProblems(doc);
    if (problems.length) {
      alert(problems.join('\n\n'));
      return;
    }
    if (!confirmLicence(doc.name)) return;

    button.disabled = true;
    button.textContent = 'Submitting…';
    try {
      const result = await intake.submit(base, {
        bundle: await bundle(), agree: true,
      });
      if (confirm('Submitted. A pull request is open for review:\n\n' +
                  result.pullRequest + '\n\nOpen it now?')) {
        open(result.pullRequest, '_blank', 'noopener');
      }
    } catch (err) {
      alert(err instanceof intake.SubmitRejected
        ? intake.explain(err)
        : 'Submission failed: ' + err.message);
    } finally {
      button.disabled = false;
      show();
    }
  };

  refresh();
  return { refresh };
}
