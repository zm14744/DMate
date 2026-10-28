'use strict';
// Validate the SAME inline head script Safari executes at page parse time.
// A distinct actual SVG is used for each scheme (not an SVG-internal media rule).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
const found = html.match(/<script id="dmateSafariFaviconSwitch">([\s\S]*?)<\/script>/);
assert.ok(found, 'Safari must choose its icons in a synchronous head script');
const code = found[1];
assert.ok(code.includes('dmate-safari-v45-20261028'), 'new version invalidates Safari cached black v44 icon');
assert.ok(!code.includes('dmate-safari-black-v44'), 'dark Safari must not use the black-only v44 icon');

function environment(initialDark, modernListener = true) {
    const children = [];
    const callbacks = {};
    const media = {
        matches: initialDark,
        addEventListener: modernListener
            ? (type, fn) => { assert.equal(type, 'change'); callbacks.change = fn; }
            : undefined,
        addListener: modernListener
            ? undefined : fn => { callbacks.change = fn; },
    };
    const document = {
        hidden: false,
        head: {
            appendChild(node) {
                children.push(node);
                node.remove = () => {
                    const index = children.indexOf(node);
                    if (index !== -1) children.splice(index, 1);
                };
            },
        },
        createElement(name) {
            assert.equal(name, 'link');
            return {};
        },
        getElementById(id) { return children.find(x => x.id === id) || null; },
        addEventListener(type, fn) { callbacks['document:' + type] = fn; },
    };
    const window = {
        matchMedia(query) {
            assert.equal(query, '(prefers-color-scheme: dark)');
            return media;
        },
        addEventListener(type, fn) { callbacks['window:' + type] = fn; },
    };
    vm.runInNewContext(code, {window, document});
    return {children, callbacks, media, document};
}
function check(env, appearance) {
    assert.equal(env.children.length, 2, 'one PNG and one SVG only');
    assert.equal(env.children[0].rel, 'icon');
    assert.equal(env.children[0].type, 'image/png');
    assert.equal(env.children[0].sizes, '64x64');
    assert.ok(env.children[0].href.includes('/dmate-safari-contrast-' + appearance + '-v43-64.png?v='));
    assert.equal(env.children[1].type, 'image/svg+xml');
    assert.ok(env.children[1].href.includes(appearance === 'dark'
        ? '/dmate-transparent.svg?v=' : '/dmate-safari-contrast-light-v43.svg?v='));
    assert.ok(!env.children.some(x => /dmate-site-v36|favicon\.ico/.test(x.href)));
}
for (const modern of [true, false]) {
    const env = environment(false, modern);
    check(env, 'light');
    env.media.matches = true;
    env.callbacks.change();
    check(env, 'dark');
    env.callbacks['window:pageshow']();
    check(env, 'dark');
    env.media.matches = false;
    env.document.hidden = false;
    env.callbacks['document:visibilitychange']();
    check(env, 'light');
    assert.equal(env.children.length, 2);
}
const directDark = environment(true);
check(directDark, 'dark');
console.log('Safari transparent appearance-aware favicon contract: passed');
