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
export function attachSubmit({ base, button, label, signOut, bundle,
                               currentDoc, stats }) {
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
    // Only offered while there is something to sign out of. Optional, so an
    // embedder that lays the toolbar out differently can leave it out.
    if (signOut) signOut.hidden = !who.signedIn;
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

  /** Send one bundle, and report the pull request.
   *
   *  `update` names an existing folder when this is a revision of it. Whether
   *  that revision is allowed is the archive's decision, not this one: a map
   *  published by somebody else is refused again, for a different reason. */
  async function send(zip, update) {
    const result = await intake.submit(base, {
      bundle: zip, agree: true, update,
    });
    if (confirm('Submitted. A pull request is open for review:\n\n' +
                result.pullRequest + '\n\nOpen it now?')) {
      open(result.pullRequest, '_blank', 'noopener');
    }
  }

  /** Ask whether a name clash is a revision, and say what each answer means.
   *
   *  Asked rather than assumed, because neither the archive nor this can tell
   *  the two cases apart: the common one is your own map edited and sent
   *  again, and the one that matters is a stranger's name taken by accident.
   *  Answering yes to the second is refused by the server, which knows who
   *  published it - this does not. */
  function confirmRevision(folder, name) {
    return confirm(
      'The archive already has a map at ' + folder + '.\n\n' +
      'If that one is yours and "' + name + '" is a newer version of it, ' +
      'submit this as its next version.\n\n' +
      'If it belongs to somebody else, cancel and rename yours instead - ' +
      'revising their map needs a maintainer to approve it.');
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
      // Built once. A second attempt sends the same bytes, so what reaches
      // the archive is the map that was confirmed rather than whatever is on
      // screen by the time the question gets answered.
      const zip = await bundle();
      try {
        await send(zip);
      } catch (err) {
        // A name clash is the one refusal with something to offer: most
        // often the submitter simply did not say this was a new version.
        if (!(err instanceof intake.SubmitRejected) ||
            err.code !== 'conflict' || !err.folder) throw err;
        if (!confirmRevision(err.folder, doc.name)) throw err;
        button.textContent = 'Submitting revision…';
        await send(zip, err.folder);
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

  if (signOut) {
    signOut.onclick = async () => {
      // No confirmation: signing out costs one click to undo, and the risk
      // worth guarding against is the opposite one - a shared browser left
      // signed in, where asking twice is what stops people bothering.
      signOut.disabled = true;
      try {
        await intake.signOut(base);
      } finally {
        signOut.disabled = false;
        // Ask the server rather than assuming. `signOut` swallows a failure,
        // so believing it would leave the toolbar saying "signed out" over a
        // session that is still live.
        await refresh();
      }
    };
  }

  refresh();
  return { refresh };
}
