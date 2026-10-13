// The Submissions button.
//
// Separate from the Submit button because it outlives it: Submit is about the
// map on screen right now, this is about maps sent earlier, possibly in a
// session that ended days ago. Keeping them apart also means the editor with
// no intake server still shows this one - a contributor who submitted
// yesterday against a server that is down today has not stopped wanting their
// link.
//
// Takes its elements rather than reaching for globals, like `attachSubmit`
// and for the same reason (decision #47): this should port to the framework
// app by changing who calls it.

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

export function attachSubmissions({ button, panel, storage,
                                    doc = document }) {
  if (!button || !panel) return { remember: () => {}, refresh: () => {} };

  function render() {
    const items = load(storage);
    button.hidden = items.length === 0;
    button.textContent = 'Submissions (' + items.length + ')';
    panel.replaceChildren();
    if (!items.length) {
      panel.hidden = true;
      return;
    }

    for (const item of items) {
      const row = doc.createElement('div');
      row.className = 'srow';

      const a = doc.createElement('a');
      a.href = item.url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      // The number is what a maintainer will call it, so lead with the name
      // the submitter knows and carry the number alongside.
      a.textContent = item.name + (item.number ? ' #' + item.number : '');
      row.appendChild(a);

      const sub = doc.createElement('span');
      sub.className = 'sub';
      sub.textContent = [item.kind === 'revised' ? 'revision' : '',
                         when(item.at)].filter(Boolean).join(' · ');
      row.appendChild(sub);
      panel.appendChild(row);
    }

    const foot = doc.createElement('div');
    foot.className = 'sfoot';
    const note = doc.createElement('span');
    note.className = 'sub';
    // Said plainly, because the list looks like an account and is not one.
    note.textContent = 'Kept in this browser only.';
    foot.appendChild(note);

    const wipe = doc.createElement('button');
    wipe.textContent = 'Clear';
    wipe.title = 'Forget these links. The pull requests stay open.';
    wipe.onclick = () => { clear(storage); render(); };
    foot.appendChild(wipe);
    panel.appendChild(foot);
  }

  button.onclick = () => { panel.hidden = !panel.hidden; };

  // Clicking anywhere else closes it. A panel that can only be dismissed by
  // the button that opened it is the kind of thing people leave open and then
  // report as the editor being broken.
  doc.addEventListener('click', (e) => {
    if (panel.hidden) return;
    if (panel.contains(e.target) || e.target === button) return;
    panel.hidden = true;
  });

  render();

  return {
    /** Record one accepted submission. `result` is the intake response. */
    remember(result, name) {
      remember({ url: result.pullRequest, number: result.number, name,
                 path: result.path, kind: result.kind }, storage);
      render();
      panel.hidden = true;
    },
    refresh: render,
  };
}
