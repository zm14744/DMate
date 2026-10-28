'use strict';
// Exact inline Safari head script: default SMALL TAB black, URL field white
// only while the page is blurred and visible. Safari's native UI may ignore
// dynamic favicon changes, but the source/DOM contract must not regress.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
const match = html.match(/<script id="dmateSafariFaviconSwitch">([\s\S]*?)<\/script>/);
assert.ok(match, 'Safari head must contain a dedicated icon handler');
const code = match[1];
assert.match(code, /dmate-safari-position-v46-20261028/);
assert.doesNotMatch(code, /prefers-color-scheme/);

function makePage() {
    const children = [], events = {};
    const document = {
        hidden:false,
        head:{appendChild(node) {
            children.push(node);
            node.remove = () => {
                const idx=children.indexOf(node);
                if(idx>=0)children.splice(idx,1);
            };
        }},
        createElement(tag) {assert.equal(tag,'link');return {};},
        getElementById(id) {return children.find(n=>n.id===id)||null;},
        addEventListener(name, fn) {events['doc:'+name]=fn;}
    };
    const window = {addEventListener(name, fn){events[name]=fn;}};
    vm.runInNewContext(code,{document,window});
    return {children,events,document};
}
function assertMode(page,mode) {
    assert.equal(page.children.length,2, 'one PNG and one SVG');
    assert.equal(page.children[0].type,'image/png');
    assert.equal(page.children[1].type,'image/svg+xml');
    for(const node of page.children)
        assert.match(node.href,new RegExp('dmate-safari-'+mode+'-v46'));
}
const page=makePage();
assertMode(page,'tab-black');
page.events.blur();
assertMode(page,'address-white');
page.events.focus();
assertMode(page,'tab-black');
// Background tabs must not retain the large-field white candidate.
page.events.blur();
page.document.hidden=true;
page.events['doc:visibilitychange']();
assertMode(page,'tab-black');
page.events.blur();
assertMode(page,'tab-black');
page.document.hidden=false;
page.events.pageshow();
assertMode(page,'tab-black');
// The two SVGs are exactly the previous white/black vector assets.
const file=name=>fs.readFileSync(path.join(root,'static/icons',name));
assert.deepEqual(file('dmate-safari-address-white-v46.svg'),file('dmate-transparent.svg'));
assert.deepEqual(file('dmate-safari-tab-black-v46.svg'),file('dmate-safari-contrast-light-v43.svg'));
assert.doesNotMatch(file('dmate-safari-tab-black-v46.svg').toString(),/<rect\b/);
assert.doesNotMatch(file('dmate-safari-address-white-v46.svg').toString(),/<rect\b/);
console.log('Safari focus-state favicon candidate switching: passed');
