// The Submissions button.
//
// Separate from the Submit button because it outlives it: Submit is about the
// map on screen right now, this is about maps sent earlier, possibly in a
// session that ended days ago. Keeping them apart also means the editor with
// no intake server still shows this one - a contributor who submitted
// yesterday against a server that is down today has not stopped wanting their
// link.
//
// Two sources, in order of authority:
//
//   1. The server, when somebody is signed in. It knows the whole history and
//      what each pull request actually came to, and it follows them to
//      another machine.
//   2. This browser's localStorage, otherwise. Per-browser and forgetful, but
//      it is what there is without an identity - and it is still the only
//      thing that works when the server is unreachable.
//
// Takes its elements rather than reaching for globals, like `attachSubmit`
// and for the same reason (decision #47): this should port to the framework
// app by changing who calls it.

import * as intake from './intake.js';
import { clear, load, remember } from './submissions.js';

/** Relative where it helps, absolute once it stops helping. */
function when(iso) {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return '';
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  if (mins < 60 * 24) return Math.floor(mins / 60) + 'h ago';
  const days = Math.floor(mins / 1440);
  if (days < 7) return days + 'd ago';
  return new Date(then).toISOString().slice(0, 10);
}

/** What the archive did with it, in a word somebody would use.
 *
 *  `unknown` is its own state and not quietly rendered as "open": the server
 *  reports it when it has never managed to ask GitHub, and a list that says
 *  "waiting for review" about a pull request nobody looked up is a list that
 *  lies. */
const WORDS = {
  open: 'waiting for review',
  merged: 'published',
  closed: 'not accepted',
  unknown: 'status unknown',
};

export function attachSubmissions({ button, panel, base, storage,
                                    doc = document }) {
  if (!button || !panel) return { remember: () => {}, refresh: async () => {} };

  // What was last rendered, so opening the panel does not blank it while the
  // server is asked again.
  let rows = [];
  let fromServer = false;

  function localRows() {
    return load(storage).map((i) => ({
      mapName: i.name, pullRequest: i.url, prNumber: i.number,
      createdAt: i.at, kind: i.kind, state: null,
    }));
  }

  function render() {
    button.hidden = rows.length === 0;
    button.textContent = 'Submissions (' + rows.length + ')';
    panel.replaceChildren();
    if (!rows.length) {
      panel.hidden = true;
      return;
    }

    for (const item of rows) {
      const row = doc.createElement('div');
      row.className = 'srow';

      const a = doc.createElement('a');
      a.href = item.pullRequest;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = item.mapName + (item.prNumber ? ' #' + item.prNumber : '');
      row.appendChild(a);

      const sub = doc.createElement('span');
      sub.className = 'sub';
      // Status first: it is the thing somebody opened this to find out.
      sub.textContent = [
        item.state ? (WORDS[item.state] ?? item.state) : '',
        item.state ? '' : (item.kind === 'revised' ? 'revision' : ''),
        when(item.createdAt),
      ].filter(Boolean).join(' · ');
      row.appendChild(sub);
      panel.appendChild(row);
    }

    const foot = doc.createElement('div');
    foot.className = 'sfoot';
    const note = doc.createElement('span');
    note.className = 'sub';
    // Said plainly either way, because the two lists have very different
    // lifetimes and somebody deciding whether to write a link down deserves
    // to know which one they are looking at.
    note.textContent = fromServer
      ? 'From your account.'
      : 'Kept in this browser only.';
    foot.appendChild(note);

    if (!fromServer) {
      const wipe = doc.createElement('button');
      wipe.textContent = 'Clear';
      wipe.title = 'Forget these links. The pull requests stay open.';
      wipe.onclick = () => { clear(storage); rows = localRows(); render(); };
      foot.appendChild(wipe);
    }
    panel.appendChild(foot);
  }

  /** Ask the server, fall back to this browser. */
  async function refresh() {
    const mine = await intake.mySubmissions(base);
    if (mine && mine.submissions.length) {
      rows = mine.submissions;
      fromServer = true;
    } else if (mine) {
      // Signed in with nothing submitted yet. Still the server's answer, so
      // an empty list here is the truth rather than a failure to look.
      rows = [];
      fromServer = true;
    } else {
      rows = localRows();
      fromServer = false;
    }
    render();
  }

  button.onclick = () => {
    panel.hidden = !panel.hidden;
    // Opened is when somebody cares whether a pull request moved, so that is
    // when it is worth asking again rather than on a timer nobody sees.
    if (!panel.hidden) refresh();
  };

  // Clicking anywhere else closes it. A panel that can only be dismissed by
  // the button that opened it is the kind of thing people leave open and then
  // report as the editor being broken.
  doc.addEventListener('click', (e) => {
    if (panel.hidden) return;
    if (panel.contains(e.target) || e.target === button) return;
    panel.hidden = true;
  });

  rows = localRows();
  render();
  refresh();

  return {
    /** Record one accepted submission. `result` is the intake response.
     *
     *  Written to the browser's list even when signed in: the server is the
     *  better record, but this costs nothing and is what remains if somebody
     *  signs out, or submits while the server is having a bad minute. */
    remember(result, name) {
      remember({ url: result.pullRequest, number: result.number, name,
                 path: result.path, kind: result.kind }, storage);
      panel.hidden = true;
      refresh();
    },
    refresh,
  };
}
