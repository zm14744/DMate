#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "desktop/src-tauri/src/offline-vault.js"), "utf8");
const startup = fs.readFileSync(path.join(root, "desktop/src-tauri/src/offline-start.js"), "utf8");
const token = "a".repeat(64);

function document(url, options = {}) {
    const calls = [];
    const window = {};
    window.top = options.frame ? {} : window;
    window.__TAURI_INTERNALS__ = {invoke: options.invoke || (async (command, args) => {
        calls.push({command, args}); return {version:1};
    })};
    vm.runInNewContext(source.replace("__DMATE_OFFLINE_VAULT_TOKEN__", token), {window, location:{href:url}, URL});
    return {window, calls};
}

function desktopPage(url, options = {}) {
    const home = "https://dmate.zeabur.app/";
    const calls = [], handlers = {}, navigator = {onLine: options.online ?? true};
    const window = {
        addEventListener(type, handler) { handlers[type] = handler; },
        dispatchEvent(event) { calls.push(event.type); },
    };
    window.top = options.frame ? {} : window;
    const settle = () => new Promise(resolve => setImmediate(resolve));
    vm.runInNewContext(startup, {
        window, navigator, URL, AbortController, setTimeout, clearTimeout,
        CustomEvent: class { constructor(type) { this.type = type; } },
        location: {href:url, replace(next) { calls.push(next); }},
        fetch(probe, actual) {
            assert.equal(probe, home + "web-version");
            assert.equal(actual.credentials, "omit");
            calls.push("network-probe");
            return options.failedProbe ? Promise.reject(Error("unreachable")) : Promise.resolve();
        },
    });
    return {navigator, window, calls, handlers, settle};
}

(async () => {
    for (const url of [
        "http://dmate.zeabur.app/offline", "https://dmate.zeabur.app.evil.test/offline",
        "https://dmate.zeabur.app:444/offline", "https://dmate.zeabur.app/",
        "https://user@dmate.zeabur.app/offline", "https://dmate.zeabur.app/%6fffline"
    ]) assert.equal(document(url).window.DMateOfflineVaultDesktop, undefined, url);
    assert.equal(document("https://dmate.zeabur.app/offline", {frame:true}).window.DMateOfflineVaultDesktop, undefined);

    for (const url of ["https://dmate.zeabur.app/offline", "https://dmate.zeabur.app:443/static/offline.html?v=2"]) {
        const page = document(url);
        assert.ok(Object.isFrozen(page.window.DMateOfflineVaultDesktop));
        assert.equal(Object.getOwnPropertyDescriptor(page.window, "DMateOfflineVaultDesktop").writable, false);
        assert.deepEqual(Object.keys(page.window.DMateOfflineVaultDesktop), ["request"]);
        const result = await page.window.DMateOfflineVaultDesktop.request({op:"capabilities"});
        assert.equal(result.version, 1);
        assert.equal(page.calls[0].command, "dmate_offline_vault");
        assert.equal(page.calls[0].args.bridgeToken, token);
        assert.equal(page.calls[0].args.request.op, "capabilities");
        assert.equal(String(page.window.DMateOfflineVaultDesktop.request).includes(token), false);
    }
    const unexpected = document("https://dmate.zeabur.app/offline", {invoke:async () => {throw "bad request containing PRIVATE DATA";}});
    await assert.rejects(unexpected.window.DMateOfflineVaultDesktop.request({op:"capabilities"}), error => error.code === "NATIVE_UNAVAILABLE" && !error.message.includes("PRIVATE DATA"));
    const expected = document("https://dmate.zeabur.app/offline", {invoke:async () => {throw {code:"KEY_MISSING",message:"The offline vault key is missing"};}});
    await assert.rejects(expected.window.DMateOfflineVaultDesktop.request({op:"decrypt"}), error => error.code === "KEY_MISSING");

    const config = JSON.parse(fs.readFileSync(path.join(root,"desktop/src-tauri/tauri.conf.json"),"utf8"));
    const capability = JSON.parse(fs.readFileSync(path.join(root,"desktop/src-tauri/capabilities/offline-vault.json"),"utf8"));
    assert.deepEqual(config.app.security.capabilities,["offline-vault"]);
    assert.deepEqual(capability.permissions,["allow-dmate-offline-vault"]);
    assert.equal(capability.local,false);
    assert.deepEqual(capability.windows,["main"]);
    assert.deepEqual(capability.remote.urls,["https://dmate.zeabur.app/offline","https://dmate.zeabur.app/static/offline.html"]);
    console.log("Desktop vault bridge: origin/frame isolation, private capability, safe errors and least-privilege config passed");

    const home = "https://dmate.zeabur.app/", offline = home + "offline";
    for (const startupUrl of ["dmate-offline://localhost/start", "http://dmate-offline.localhost/start"]) {
        const unconnected = desktopPage(startupUrl,{online:false});
        assert.deepEqual(unconnected.calls,[offline],"Cold startup must never need a network request");
        const inaccessible = desktopPage(startupUrl,{failedProbe:true});
        await inaccessible.settle();
        assert.deepEqual(inaccessible.calls,["network-probe",offline]);
        const connected = desktopPage(startupUrl);
        await connected.settle();
        assert.deepEqual(connected.calls,["network-probe",home]);
        assert.equal(document(startupUrl).window.DMateOfflineVaultDesktop,undefined);
    }
    const running = desktopPage(home);
    running.window.DMateAccountOcrDrafts = {async flush() { running.calls.push("saved-draft"); }};
    running.navigator.onLine = false;
    await running.handlers.offline();
    assert.deepEqual(running.calls,["dmate:before-offline-navigation","saved-draft",offline]);
    const workspace = desktopPage(offline,{online:false});
    assert.deepEqual(workspace.calls,[]);
    assert.equal(workspace.handlers.offline,undefined);
    assert.equal(workspace.handlers.online,undefined);
    for (const url of ["https://dmate.zeabur.app.evil.test/", "dmate-offline://localhost/other", "http://dmate-offline.localhost:8080/start"]) {
        const untrusted = desktopPage(url,{online:false});
        assert.deepEqual(untrusted.calls,[]);
        assert.equal(untrusted.window.__DMATE_NATIVE_OFFLINE_AVAILABLE__,undefined);
    }
    assert.deepEqual(desktopPage(home,{online:false,frame:true}).calls,[]);
    console.log("Desktop network transition: no-cache startup, failed probe, live draft checkpoint and trusted URLs passed");
})().catch(error => {console.error(error);process.exitCode=1;});
