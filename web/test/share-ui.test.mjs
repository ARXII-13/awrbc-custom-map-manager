// Submitting a map with no intake server to submit it to.
//
// The map goes out as an Export bundle and the contributor uploads it to a
// form; whoever runs the archive works through those by hand. It is a
// stand-in, so the thing worth pinning is that it stands aside the moment
// the real path is available.

import assert from 'node:assert/strict';
import { afterEach, describe, it } from 'node:test';

import { attachShare, shareUrl } from '../share-ui.js';

const FORM = 'https://forms.example/submit-a-map';

/** Just enough of an anchor. */
function anchor() {
  const clicks = [];
  return {
    tag: 'a', href: '', hidden: true, clicks,
    addEventListener(kind, fn) { if (kind === 'click') clicks.push(fn); },
    async click() { for (const fn of [...clicks]) await fn(); },
  };
}

function wire({ url = FORM, intakeBase = '', bundle, name = 'Twin_Rivers.zip' } = {}) {
  const link = anchor();
  const saved = [];
  const said = [];
  const got = attachShare({
    link,
    url,
    intakeBase,
    baseName: () => name,
    bundle: bundle ?? (async () => ({ bundle: true })),
    download: (blob, filename) => saved.push([blob, filename]),
    notify: (m) => said.push(m),
  });
  return { link, saved, said, handle: got };
}

describe('where the form is', () => {
  it('takes an https form', () => {
    assert.equal(shareUrl(FORM), FORM);
  });

  it('refuses a plain http one', () => {
    // The editor is served over https, so an http form is a link that opens
    // a page the browser will not let post anything useful back.
    assert.equal(shareUrl('http://forms.example/submit'), '');
  });

  it('refuses something that is not a url', () => {
    assert.equal(shareUrl('forms.example'), '');
    assert.equal(shareUrl('javascript:alert(1)'), '');
  });

  it('treats absent as absent', () => {
    assert.equal(shareUrl(''), '');
    assert.equal(shareUrl(undefined), '');
    assert.equal(shareUrl('   '), '');
  });
});

describe('the manual submission link', () => {
  it('stays hidden when there is no form to point at', () => {
    const { link, handle } = wire({ url: '' });
    assert.equal(link.hidden, true);
    assert.equal(handle, null);
  });

  it('stands aside when a real intake server is configured', () => {
    // One route at a time. Two would only ask somebody to choose between a
    // thing that works and a thing that works more slowly.
    const { link, handle } = wire({ intakeBase: 'https://intake.example' });
    assert.equal(link.hidden, true);
    assert.equal(handle, null);
  });

  it('appears, pointing at the form, when there is one', () => {
    const { link } = wire();
    assert.equal(link.hidden, false);
    assert.equal(link.href, FORM);
  });

  it('saves the bundle when clicked', async () => {
    const { link, saved } = wire();
    await link.click();
    assert.equal(saved.length, 1);
    assert.equal(saved[0][1], 'Twin_Rivers.zip');
  });

  it('says which file to attach', async () => {
    const { link, said } = wire();
    await link.click();
    assert.ok(said.some((m) => m.includes('Twin_Rivers.zip')), said.join(' | '));
  });

  it('says that nothing was sent from here', async () => {
    // It is a download and a link, and somebody who thinks their map has
    // been submitted will not upload it.
    const { link, said } = wire();
    await link.click();
    assert.ok(said.some((m) => /nothing is sent/i.test(m)), said.join(' | '));
  });

  it('says so when the map could not be packaged, and claims nothing', async () => {
    const { link, said, saved } = wire({
      bundle: async () => { throw new Error('canvas is tainted'); },
    });
    await link.click();
    assert.equal(saved.length, 0);
    assert.ok(said.some((m) => m.includes('canvas is tainted')), said.join(' | '));
    assert.ok(!said.some((m) => /attach/i.test(m)),
              'it told them to attach a file it never produced');
  });
});
