'use strict';
// Safari's tab favicon must be the exact same transparent BLACK wireframe in
// both appearances; the browser never chooses a white icon on dark macOS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
const start = html.indexOf('{% elif is_mac_safari %}');
const end = html.indexOf('{% elif is_android_browser %}', start);
assert.ok(start >= 0 && end > start, 'Safari must have a dedicated favicon branch');
const safari = html.slice(start, end);

const targetSvg = '/static/icons/dmate-safari-black-v44.svg?v=dmate-safari-black-v44-20261028';
const targetPng = '/static/icons/dmate-safari-black-v44-64.png?v=dmate-safari-black-v44-20261028';
assert.ok(safari.includes(targetSvg), 'Safari SVG icon must be the new black wireframe');
assert.ok(safari.includes(targetPng), 'Safari PNG fallback must also be black');
assert.equal((safari.match(/rel="icon"/g) || []).length, 2);
assert.ok(!safari.includes('prefers-color-scheme'), 'both macOS appearances must use one asset');
assert.ok(!safari.includes('dmateSafariFaviconSwitch'), 'do not dynamically reinsert a white icon');
assert.ok(!safari.includes('dmate-transparent.svg'), 'Edge SVG is white, not black');
assert.ok(!safari.includes('dmate-safari-contrast-dark-v43'), 'old white icon must be unused');

const latest = fs.readFileSync(path.join(root, 'static/icons/dmate-safari-black-v44.svg'), 'utf8');
const earlierLight = fs.readFileSync(path.join(root, 'static/icons/dmate-safari-contrast-light-v43.svg'), 'utf8');
assert.equal(latest, earlierLight, 'new Safari favicon must match the existing light appearance');
assert.match(latest, /stroke="#000"/);
assert.match(latest, /stroke-width="23"/);
assert.doesNotMatch(latest, /<rect\b/); // transparent, no square background

console.log('Safari black favicon in both macOS appearances: passed');
