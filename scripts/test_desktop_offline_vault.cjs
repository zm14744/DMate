#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "desktop/src-tauri/src/offline-vault.js"), "utf8");
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
})().catch(error => {console.error(error);process.exitCode=1;});
