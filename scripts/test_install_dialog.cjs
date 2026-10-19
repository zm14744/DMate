#!/usr/bin/env node
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const js = fs.readFileSync("static/script.js", "utf8");
const start = js.indexOf("function installGuideForCurrentPlatform()");
const end = js.indexOf("\nfunction dmatePwaSiteAndBrowserSupport()", start);
assert(start >= 0 && end > start, "Install guide not found");
const script = js.slice(start, end);

function guide(platform, urls={}) {
    const config = {
        androidApkUrl:"", desktopWindowsUrl:"", desktopMacosUrl:"",
        desktopLinuxDebUrl:"", desktopLinuxAppImageUrl:"", ...urls
    };
    const context={
        dmateClientConfig:()=>config,
        detectDmateInstallPlatform:()=>platform
    };
    vm.runInNewContext(script, context);
    return vm.runInNewContext("installGuideForCurrentPlatform()", context);
}
const urls=(p, config) => guide(p, config).actions.map(x=>x.url);
const gitcodeBase="https://api.gitcode.com/api/v5/repos/zm14744/DMate/releases/v1.0.1/attach_files/";
const githubBase="https://github.com/zm14744/DMate/releases/latest/download/";
const file={
    android:"DMate.apk",
    windows:"DMate_1.0.0_x64-setup.exe",
    macos:"DMate_1.0.0_universal.dmg",
    deb:"DMate_1.0.0_amd64.deb",
    appimage:"DMate_1.0.0_amd64.AppImage"
};
const envKey={
    android:"androidApkUrl",
    windows:"desktopWindowsUrl",
    macos:"desktopMacosUrl"
};
for(const platform of ["android","windows","macos"]){
    const name=file[platform];
    const gitcode=gitcodeBase+name+"/download";
    const github=githubBase+name;
    const legacy={ [envKey[platform]]: github };
    assert.equal(urls(platform)[0],gitcode,"GitCode primary without env");
    assert.equal(urls(platform,legacy)[0],gitcode,"Legacy GitHub env must not displace GitCode");
    assert(urls(platform,legacy).includes(github),"GitHub direct backup preserved");
    assert.equal(urls(platform,{[envKey[platform]]:gitcode})[0],gitcode);
}
const linuxURLs=urls("linux",{
    desktopLinuxDebUrl:githubBase+file.deb,
    desktopLinuxAppImageUrl:githubBase+file.appimage
});
assert.equal(linuxURLs[0],gitcodeBase+file.deb+"/download");
assert.equal(linuxURLs[1],githubBase+file.deb);
assert.equal(linuxURLs[2],gitcodeBase+file.appimage+"/download");
assert.equal(linuxURLs[3],githubBase+file.appimage);
assert(linuxURLs.some(x=>x.includes("snapcraft.io")));
const custom="https://mirror.example/DMate.apk";
assert.equal(urls("android",{androidApkUrl:custom})[0],custom,"Custom mirror still supported");
assert(urls("android",{androidApkUrl:custom}).includes(gitcodeBase+file.android+"/download"));
assert(urls("android",{androidApkUrl:custom}).includes(githubBase+file.android));
assert.equal(urls("ios")[0],"/DMate.mobileconfig");
assert.equal(urls("ios")[1],gitcodeBase+"DMate-iPhone-iPad.mobileconfig/download");
assert(!urls("ios").some(x=>/\.ipa$/i.test(x)));
const html=fs.readFileSync("templates/index.html","utf8");
const modal=html.split('<div id="installHelpModal"')[1].split('<div id="accountModal"')[0];
assert(!modal.includes('id="installHelpNativeButton"'));
assert(!modal.includes('id="installHelpNote"'));
assert(html.includes("dmate-gitcode-github-install-v28-20261019"));
console.log("PASS: GitCode direct primary, GitHub individual file fallback, stores, iOS profile, custom mirrors.");
