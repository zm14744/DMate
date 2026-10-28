'use strict';
// Four-position/mode contract:
// macOS light: LARGE URL black, SMALL tab black.
// macOS dark:  LARGE URL white candidate, SMALL tab black.
// Safari's native chrome may cache one favicon for both UI surfaces.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
const found = html.match(/<script id="dmateSafariFaviconSwitch">([\s\S]*?)<\/script>/);
assert.ok(found, 'Safari favicon head handler is missing');
const code = found[1];
assert.match(code, /dmate-safari-position-v47-20261028/);
assert.match(code, /prefers-color-scheme: dark/);
assert.ok(!code.includes('dmate-safari-black-v44'));

function environment(initialDark, modernListener) {
    const children = [], events = {};
    const appearance = {
        matches: initialDark,
        addEventListener: modernListener
            ? (type, cb) => { assert.equal(type, 'change'); events.appearance = cb; }
            : undefined,
        addListener: modernListener ? undefined : cb => { events.appearance = cb; },
    };
    const document = {
        hidden: false,
        head: { appendChild(node) {
            children.push(node);
            node.remove = () => {
                const at = children.indexOf(node);
                if (at >= 0) children.splice(at, 1);
            };
        }},
        createElement(tag) { assert.equal(tag, 'link'); return {}; },
        getElementById(id) { return children.find(x => x.id === id) || null; },
        addEventListener(type, cb) { events['doc:' + type] = cb; },
    };
    const window = {
        matchMedia(query) {
            assert.equal(query, '(prefers-color-scheme: dark)');
            return appearance;
        },
        addEventListener(type, cb) { events[type] = cb; },
    };
    vm.runInNewContext(code, { window, document });
    return { children, events, document, appearance };
}
function assertIcon(page, wanted) {
    assert.equal(page.children.length, 2, 'exactly one PNG + SVG pair');
    assert.equal(page.children[0].id, 'dmateSafariFaviconPng');
    assert.equal(page.children[1].id, 'dmateSafariFavicon');
    assert.equal(page.children[0].type, 'image/png');
    assert.equal(page.children[1].type, 'image/svg+xml');
    assert.equal(page.children[0].sizes, '64x64');
    assert.ok(page.children[0].href.includes('dmate-safari-' + wanted + '-v46-64.png?v=dmate-safari-position-v47'));
    assert.ok(page.children[1].href.includes('dmate-safari-' + wanted + '-v46.svg?v=dmate-safari-position-v47'));
}
for (const modern of [true, false]) {
    for (const dark of [false, true]) {
        const page = environment(dark, modern);
        // SMALL tab in both macOS appearances is BLACK.
        assertIcon(page, 'tab-black');
        // The LARGE address candidate is WHITE only in dark mode.
        page.events.blur();
        assertIcon(page, dark ? 'address-white' : 'tab-black');
        page.events.focus();
        assertIcon(page, 'tab-black');
        page.events.blur();
        page.document.hidden = true;
        page.events['doc:visibilitychange']();
        assertIcon(page, 'tab-black');
        page.document.hidden = false;
        page.events.pageshow();
        assertIcon(page, 'tab-black');
    }
}
// A macOS appearance change while Safari has focused its URL field also
// updates the candidate; returning focus restores the SMALL black icon.
const change = environment(false, true);
change.events.blur();
assertIcon(change, 'tab-black');
change.appearance.matches = true;
change.events.appearance();
assertIcon(change, 'address-white');
change.appearance.matches = false;
change.events.appearance();
assertIcon(change, 'tab-black');
change.events.focus();
assertIcon(change, 'tab-black');

// The assets themselves are fixed-color vectors and have no background tile.
const icon = name => fs.readFileSync(path.join(root, 'static/icons', name), 'utf8');
const black = icon('dmate-safari-tab-black-v46.svg');
const white = icon('dmate-safari-address-white-v46.svg');
assert.equal(black, icon('dmate-safari-contrast-light-v43.svg'));
assert.equal(white, icon('dmate-transparent.svg'));
assert.match(black, /stroke="#000"/);
assert.match(white, /stroke="#fff"/);
assert.doesNotMatch(black, /<rect\b/);
assert.doesNotMatch(white, /<rect\b/);
console.log('Safari light/dark x URL/tab favicon contract: all cases passed');
