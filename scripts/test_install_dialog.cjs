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

// itch.io and official store links must follow platform-specific GitCode/GitHub downloads.
const itch = "https://zm14744.itch.io/dmate";
for (const platform of ["android", "macos"]) {
    const actions = guide(platform).actions;
    assert.equal(actions.at(-1).url, itch, platform + " itch.io must follow GitCode/GitHub");
    assert.match(actions.at(-1).label, /itch\.io/);
}
const windowsActions = guide("windows").actions;
assert.equal(windowsActions.at(-2).url, "https://apps.microsoft.com/detail/9pk5td2w5m40?hl=zh-CN&gl=HK",
    "Microsoft Store must follow GitCode/GitHub downloads");
assert.equal(windowsActions.at(-1).url, itch, "Windows itch.io must be last");
const linuxActions = guide("linux").actions;
assert.equal(linuxActions.at(-1).url, "https://snapcraft.io/dmate",
    "Snap Store must follow all Linux GitCode/GitHub packages");
const otherActions = guide("other").actions;
assert.equal(otherActions[0].label, "GitCode · 国内发行版");
assert.equal(otherActions[1].label, "GitHub · 海外备用发行版",
    "Generic fallback must list GitHub before store options");
assert.equal(otherActions[2].url, "https://apps.microsoft.com/detail/9pk5td2w5m40?hl=zh-CN&gl=HK");
assert.equal(otherActions[3].url, "https://snapcraft.io/dmate");

const html=fs.readFileSync("templates/index.html","utf8");
const modal=html.split('<div id="installHelpModal"')[1].split('<div id="accountModal"')[0];
assert(!modal.includes('id="installHelpNativeButton"'));
assert(!modal.includes('id="installHelpNote"'));
assert(html.includes("dmate-install-links-stores-v32-20261019"), "Install dialog JS cache key must change when store links change");
for(const platform of ["android", "windows", "macos", "linux"]) {
    assert(!guide(platform).actions.some(a => /查看全部安装文件|查看所有安装文件/.test(a.label)),
           "Do not show a generic all-installers button on " + platform);
    assert(!guide(platform).actions.some(a => a.url === "https://gitcode.com/zm14744/DMate/releases/v1.0.1"),
           "Download dialog should link directly to platform installers");
}
console.log("PASS: GitCode direct primary, GitHub individual file fallback, stores, iOS profile, custom mirrors.");
