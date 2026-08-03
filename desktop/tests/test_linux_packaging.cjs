'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const PACKAGING_DIR = path.join(__dirname, '..', 'packaging', 'linux');
const packageJson = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'),
);
const linuxPackWorkflow = fs.readFileSync(
  path.join(__dirname, '..', '..', '.github', 'workflows', 'desktop-linux-pack.yml'),
  'utf8',
);
const postinst = fs.readFileSync(path.join(PACKAGING_DIR, 'postinst.sh'), 'utf8');
const postrm = fs.readFileSync(path.join(PACKAGING_DIR, 'postrm.sh'), 'utf8');

test('desktop package includes the Arena report consumed by the overview', () => {
  assert.ok(
    packageJson.build.extraResources.some((resource) =>
      resource.from === '../reports/production_memory_eval_metrics.json'
      && resource.to === 'reports/production_memory_eval_metrics.json'),
  );
  assert.equal(
    (linuxPackWorkflow.match(/memory_arena\/metrics_contract\.py/g) || []).length,
    2,
    'deb and rpm payloads must both pass the shared Arena contract',
  );
});

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
