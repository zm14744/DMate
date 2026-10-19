#!/usr/bin/env node
// Run: node scripts/test_pwa_install_support.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("static/script.js", "utf8");
const first = source.indexOf("function detectDmateInstallPlatform()");
const last = source.indexOf("\nlet dmateCurrentInstallGuide", first);
assert(first >= 0 && last > first, "PWA support code not found");
const implementation = source.slice(first, last);
let count = 0;
function check(label, userAgent, expect, opts={}) {
    const navigator = {
        userAgent, platform: opts.platform || "Linux arm", maxTouchPoints:0,
        standalone:false, ...(opts.worker === false ? {} : {serviceWorker:{}})
    };
    const window = {
        isSecureContext: opts.secure !== false,
        matchMedia: () => ({matches: Boolean(opts.standalone)})
    };
    const document = {querySelector:()=>opts.manifest === false ? null : {}};
    const ctx={window,navigator,document,
        dmateClientConfig:()=>({isAndroidApp:Boolean(opts.native),isDesktopApp:false})};
    vm.runInNewContext(implementation,ctx);
    const response=vm.runInNewContext("dmatePwaSiteAndBrowserSupport()",ctx);
    assert.equal(Boolean(response),expect,label);
    if(response)assert(response.steps.length > 0);
    count++;
}
const androidChrome="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36";
const androidFirefox="Mozilla/5.0 (Android 14; Mobile; rv:129.0) Gecko/129.0 Firefox/129.0";
const iosSafari="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1";
const macSafari="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15";
const winEdge="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0";
check("Chrome Android supports manual installation",androidChrome,true);
check("Android Firefox supports manual installation",androidFirefox,true,{worker:false});
check("Android Fennec UA recognized",androidFirefox.replace("Firefox","Fennec"),true,{worker:false});
check("QQ Browser retains native menu guidance",androidChrome+" MQQBrowser/14.0",true,{worker:false});
check("Quark retains native menu guidance",androidChrome+" Quark/7.1",true,{worker:false});
check("Unknown browser cannot be assumed supported","Mozilla/5.0 (Linux; Android 14) UnnamedBrowser/1",false);
check("Chromium lacking PWA capability",androidChrome,false,{worker:false});
check("Insecure context",androidChrome,false,{secure:false});
check("No manifest",androidChrome,false,{manifest:false});
check("Standalone already installed",androidChrome,false,{standalone:true});
check("Native app cannot install itself",androidChrome,false,{native:true});
check("WeChat in-app browser",androidChrome+" MicroMessenger/8.0",false);
check("Android WebView",androidChrome+" wv",false);
check("iOS Safari",iosSafari,true,{platform:"iPhone"});
check("iOS unsupported generic browser",iosSafari.replace("Version/18.0 Mobile Safari/604.1","FooBrowser/2.0"),false,{platform:"iPhone"});
check("macOS Safari with Add to Dock",macSafari,true,{platform:"MacIntel"});
check("Windows Edge",winEdge,true,{platform:"Win32"});
check("macOS Firefox unsupported",macSafari.replace("Version/18.0 Safari/605.1.15","Firefox/128.0"),false,{platform:"MacIntel"});
console.log("PASS",count,"PWA manual-install/unsupported cases");
