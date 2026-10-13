// A message that does not stop the editor.
//
// Replaces `confirm()` and `alert()` for things that are announcements rather
// than questions. The native dialogs block the page, steal focus, and - the
// reason this exists - destroy their own contents when dismissed, which is
// fine for "saved" and wrong for anything the reader might want afterwards.
//
// Questions stay as dialogs. The licence confirmation and the "is this a
// revision?" prompt both need an answer before anything can continue, and a
// toast cannot ask for one.

const WRAP_ID = 'toasts';

function wrap(doc) {
  let el = doc.getElementById(WRAP_ID);
  if (!el) {
    el = doc.createElement('div');
    el.id = WRAP_ID;
    doc.body.appendChild(el);
  }
  return el;
}

/**
 * Show a message. Returns a function that removes it early.
 *
 * `action` adds one link - the submission's pull request, in practice. It is
 * an anchor rather than a button so it can be middle-clicked, copied and
 * opened in a new tab like any other link, and so a popup blocker has no
 * opinion about it.
 */
export function toast(message, { action, ms = 9000, doc = document } = {}) {
  const el = doc.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');

  const text = doc.createElement('span');
  text.textContent = message;
  el.appendChild(text);

  if (action && action.href) {
    const a = doc.createElement('a');
    a.href = action.href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = action.label ?? 'Open';
    el.appendChild(a);
  }

  const close = doc.createElement('button');
  close.className = 'x';
  close.title = 'Dismiss';
  close.textContent = '×';
  el.appendChild(close);

  wrap(doc).appendChild(el);

  let timer = 0;
  const remove = () => {
    if (timer) clearTimeout(timer);
    timer = 0;
    el.remove();
  };
  close.onclick = remove;
  // Reading stops the clock. A toast carrying a link is worth more than the
  // few seconds a timer would give someone who is still looking at it.
  el.onmouseenter = () => { if (timer) { clearTimeout(timer); timer = 0; } };
  el.onmouseleave = () => { timer = setTimeout(remove, 2500); };
  if (ms) timer = setTimeout(remove, ms);
  return remove;
}
