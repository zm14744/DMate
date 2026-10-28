'use strict';
// Browser-chrome limitations: preserve Safari's existing BLACK tab favicon
// in both appearances; never pretend page blur controls the URL field.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
const start = html.indexOf('{% elif is_mac_safari %}');
const end = html.indexOf('{% elif is_android_browser %}', start);
assert.ok(start >= 0 && end > start);
const safari = html.slice(start, end);
const svg = '/static/icons/dmate-safari-tab-black-v46.svg?v=dmate-safari-stable-black-v48-20261028';
const png = '/static/icons/dmate-safari-tab-black-v46-64.png?v=dmate-safari-stable-black-v48-20261028';
assert.ok(safari.includes(svg));
assert.ok(safari.includes(png));
assert.equal((safari.match(/rel="icon"/g) || []).length, 2);
assert.ok(!safari.includes('dmateSafariFaviconSwitch'));
assert.ok(!safari.includes('addEventListener'));
assert.ok(!safari.includes('address-white'));
assert.ok(!safari.includes('prefers-color-scheme'));
assert.ok(!safari.includes('dmate-safari-position-v47'));

const icon = name => fs.readFileSync(path.join(root, 'static/icons', name));
const darkTab = icon('dmate-safari-tab-black-v46.svg');
const earlierBlack = icon('dmate-safari-contrast-light-v43.svg');
assert.deepEqual(darkTab, earlierBlack);
assert.deepEqual(icon('dmate-safari-tab-black-v46-64.png'),
                 icon('dmate-safari-contrast-light-v43-64.png'));
assert.match(darkTab.toString(), /stroke="#000"/);
assert.match(darkTab.toString(), /stroke-width="23"/);
assert.doesNotMatch(darkTab.toString(), /<rect\b/);
console.log('Safari small tab fixed black, no unreliable blur-based recoloring: passed');
