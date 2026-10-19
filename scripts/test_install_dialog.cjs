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
        detectDmateInstallPlatform:()=>platform,
        detectDmateBrowserName:()=>"Test Browser"
    };
    vm.runInNewContext(script, context);
    return vm.runInNewContext("installGuideForCurrentPlatform()", context);
}
const direct=(g)=>g.actions.map(x=>x.url);
const apk="https://example.invalid/DMate.apk";
const exe="https://example.invalid/DMate.exe";
const dmg="https://example.invalid/DMate.dmg";
const deb="https://example.invalid/DMate.deb";
const appimage="https://example.invalid/DMate.AppImage";
const gitcode="https://gitcode.com/zm14744/DMate";
const gAndroid=guide("android",{androidApkUrl:apk});
assert.equal(direct(gAndroid)[0],apk);
assert(direct(gAndroid).includes(gitcode));
assert.equal(direct(guide("android"))[0],gitcode);
assert.equal(direct(guide("windows",{desktopWindowsUrl:exe}))[0],exe);
assert(direct(guide("windows")).some(x=>x.includes("apps.microsoft.com")));
assert.equal(direct(guide("macos",{desktopMacosUrl:dmg}))[0],dmg);
const gLinux=guide("linux",{desktopLinuxDebUrl:deb,desktopLinuxAppImageUrl:appimage});
assert.equal(direct(gLinux)[0],deb);
assert.equal(direct(gLinux)[1],appimage);
assert(direct(guide("linux")).some(x=>x.includes("snapcraft.io")));
assert.equal(direct(guide("ios"))[0],"/DMate.mobileconfig");
assert(!guide("ios").actions.some(x=>/\.ipa$/i.test(x.url)));
// The Web installation popup is now about downloads, not PWA instructions.
// Keep the rest of the site PWA code untouched.
const html=fs.readFileSync("templates/index.html","utf8");
const modal=html.split('<div id="installHelpModal"')[1].split('<div id="accountModal"')[0];
assert(!modal.includes('id="installHelpNativeButton"'));
assert(!modal.includes('id="installHelpNote"'));
assert(html.includes("dmate-gitcode-install-dialog-v26-20261019"));
console.log("PASS: correct installers and fallbacks on all five platforms; PWA controls absent from download modal.");
