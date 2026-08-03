'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const PACKAGING_DIR = path.join(__dirname, '..', 'packaging', 'linux');
const postinst = fs.readFileSync(path.join(PACKAGING_DIR, 'postinst.sh'), 'utf8');
const postrm = fs.readFileSync(path.join(PACKAGING_DIR, 'postrm.sh'), 'utf8');

test('postinst fails closed when the Electron sandbox cannot be secured', () => {
  assert.match(postinst, /if \[ ! -f "\$SANDBOX" \]; then/);
  assert.match(postinst, /chown root:root "\$SANDBOX"\nchmod 4755 "\$SANDBOX"/);

  const sandboxSection = postinst.slice(
    postinst.indexOf('SANDBOX='),
    postinst.indexOf('SERVICE_SRC='),
  );
  assert.doesNotMatch(sandboxSection, /\|\| true/);
});

test('postrm removes the copied user service only on final uninstall', () => {
  assert.match(postrm, /remove\|purge\|disappear\|0\|""/);
  assert.match(postrm, /rm -f \/etc\/systemd\/user\/wanwei-shuyi-desktop\.service/);
  assert.doesNotMatch(postrm, /upgrade\|1/);
});
