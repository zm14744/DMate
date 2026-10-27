'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const code = fs.readFileSync(require('node:path').join(__dirname, '../static/web-sync.js'), 'utf8');
const a = 'a'.repeat(64), b = 'b'.repeat(64);
function environment({installed = true, busy = false, current = a, latest = b} = {}) {
    const navigation = [];
    let calls = 0;
    const storage = new Map();
    const doc = {
        readyState: 'loading', hidden: false,
        addEventListener() {},
        getElementById(id) {
            if (id === 'ocrTaskPanel') return {hidden:!busy};
            if (id === 'text') return {value:''};
            return null;
        },
        querySelector() {return null;},
        activeElement:null,
    };
    const root = {
        document:doc,
        navigator:{userAgent:installed ? 'DMateAndroid/1.0.1' : 'Chrome/120'},
        DMATE_CLIENT_CONFIG: installed ? {isAndroidApp:true} : {},
        DMATE_WEB_REVISION:current,
        location:{origin:'https://dmate.zeabur.app', replace(url){navigation.push(url);}},
        fetch:async (url, options) => {
            calls += 1;
            assert.match(url, /^\/web-version\?t=/);
            assert.equal(options.cache, 'no-store');
            return {ok:true, json:async() => ({revision:latest})};
        },
        sessionStorage:{
            getItem(key){return storage.get(key) || null;},
            setItem(key,value){storage.set(key,value);}
        },
        setInterval(){}, addEventListener(){}, URL,
    };
    vm.runInNewContext(code, vm.createContext(root));
    return {root, doc, navigation, get calls(){return calls;}};
}
async function run() {
    const old=environment();
    assert.equal(await old.root.DMateWebSync.checkNow(true), true);
    assert.equal(old.navigation.length, 1);
    assert.match(old.navigation[0], /^\/\?dmate_web_revision=bbbbbbbbbbbbbbbb$/);
    assert.equal(await old.root.DMateWebSync.checkNow(true), false);
    assert.equal(old.navigation.length, 1, 'avoid stale-page reload loops');

    const editing=environment({busy:true});
    assert.equal(await editing.root.DMateWebSync.checkNow(true), false);
    assert.equal(editing.navigation.length, 0);
    editing.doc.getElementById = id => {
        if(id === 'ocrTaskPanel') return {hidden:true};
        if(id === 'text') return {value:''};
        return null;
    };
    assert.equal(await editing.root.DMateWebSync.checkNow(false), true);
    assert.equal(editing.navigation.length, 1);

    const current=environment({current:b,latest:b});
    assert.equal(await current.root.DMateWebSync.checkNow(true), false);
    assert.equal(current.navigation.length, 0);

    assert.match(code, /addEventListener\\?\.\('pageshow'/);
    assert.match(code, /addEventListener\\?\.\('online'/);
    const browser=environment({installed:false});
    assert.equal(await browser.root.DMateWebSync.checkNow(true), false);
    assert.equal(browser.calls, 0);
    // Run the actual retired worker's activation handler against historical
    // CacheStorage names, checking user/application-owned caches are preserved.
    const oldWorker = fs.readFileSync(require('node:path').join(__dirname,
        '../static/legacy-worker-retire.js'), 'utf8');
    const removed = [];
    const history = [
        'dmate-pwa-20261001',
        'dmate-ios-webapp-v6-15-20261009',
        'dmate-store-pwa-20261012',
        'dmate-sessions-preserve',
        'other-app-cache',
    ];
    let activation;
    const workerScope = {
        self: {
            skipWaiting:async () => {},
            registration:{unregister:async () => true},
            clients:{matchAll:async () => [{postMessage:() => {}}]},
            addEventListener(type, cb) { if (type === 'activate') activation = cb; },
        },
        caches:{
            keys:async () => history,
            delete:async key => {removed.push(key);return true;},
        },
        URL, Promise,
    };
    vm.runInNewContext(oldWorker,vm.createContext(workerScope));
    assert.equal(typeof activation, 'function');
    let activationWork;
    activation({waitUntil(promise){activationWork = promise;}});
    await activationWork;
    assert.deepEqual(removed, history.slice(0,3));

    console.log('DMate old-installed-shell web sync: passed');
}
run().catch(error => {console.error(error);process.exitCode=1;});
