/* Regression: Mac Safari, desktop Chromium, iPad and Split View. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium,webkit}=require('playwright');
const root=path.resolve(__dirname,'..');
const style=fs.readFileSync(path.join(root,'static/chat-composer.css'),'utf8');
const source=fs.readFileSync(path.join(root,'static/chat-composer.js'),'utf8');
const base=[
'html,body{width:100%;height:100%;margin:0;overflow:hidden}',
'body[data-appearance-theme="dark"]{--text-primary:#ececec;--text-secondary:#c7c7c7;--text-muted:#9a9a9a;--text-strong:#f4f4f4;--surface-1:#171717;--surface-2:#242424;--surface-3:#313131;--border-strong:#3a3a3a;--accent:#3b82f6;--accent-bg:#26394c;background:#101010;color:#ececec}',
'body[data-appearance-theme="light"]{--text-primary:#1e293b;--text-secondary:#334155;--text-muted:#64748b;--text-strong:#0f172a;--surface-1:#f8fafc;--surface-2:#e2e8f0;--surface-3:#cbd5e1;--border-strong:#cbd5e1;--accent:#3b82f6;--accent-bg:#dbeafe;background:#eef3f8;color:#1e293b}',
'body[data-appearance-theme="navy"]{--text-primary:#e2e8f0;--text-secondary:#cbd5e1;--text-muted:#94a3b8;--text-strong:#f8fafc;--surface-1:#0b1220;--surface-2:#1f2937;--surface-3:#334155;--border-strong:#475569;--accent:#3b82f6;--accent-bg:#1f2937;background:#0f172a;color:#e2e8f0}',
'.layout{position:relative;overflow:hidden;height:100dvh;transform:translateZ(0)}',
'.center{position:relative;height:100%;overflow:hidden;transform:translateZ(0);display:flex;align-items:center;justify-content:center}',
'.center.chat-empty>.input-wrap:not([hidden]){position:absolute;inset:50% 24px auto 24px;max-width:760px;margin:auto;transform:translateY(-50%)}',
'.input-wrap{box-sizing:border-box;position:relative;width:100%;padding:0}',
'.input{position:relative;box-sizing:border-box;display:flex;align-items:center;width:100%;min-height:58px;padding:8px;border-radius:29px;background:var(--surface-2)}',
'.manual-question-composer{box-sizing:border-box;position:relative;flex:1 1 0;width:0;height:42px}',
'#text{box-sizing:border-box;width:100%;height:42px;min-height:42px;max-height:42px;border:0;background:transparent;color:inherit;font:16px/24px system-ui;padding:9px 45px 9px 10px}',
'.mobile-topbar{display:none}',
'#outside{position:fixed;top:90px;left:10px;z-index:2}',
'#sessions{display:none}',
'@media(max-width:1100px){.mobile-topbar{display:block;position:absolute;top:0;left:0;right:0;height:56px;background:var(--surface-1);z-index:70}.center.chat-empty>.input-wrap:not([hidden]){left:12px;right:12px}}'
].join('\n');
const fixture='<!doctype html><html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>'
+base+'</style><style>'+style+'</style></head><body data-appearance-theme="dark"><div class="layout">'
+'<div class="mobile-topbar">DMate</div><div class="center chat-empty"><div class="input-wrap">'
+'<div class="manual-question-mode interaction-mode-switch" data-mode="chat"><button>Chat</button><button>Solve</button></div>'
+'<div class="input"><div class="manual-question-composer"><textarea id="text"></textarea></div></div>'
+'</div></div></div><div id="sessions"><div class="session active">新对话</div></div>'
+'<button id="outside" type="button">outside</button></body></html>';
const sizes=[
{name:'Mac desktop',width:1440,height:900,compact:false},
{name:'Mac small window',width:1200,height:700,compact:false},
{name:'iPad landscape',width:1024,height:768,compact:true},
{name:'iPad portrait',width:820,height:1180,compact:true},
{name:'iPad split view',width:620,height:820,compact:true},
{name:'phone',width:390,height:844,compact:true}
];
async function verify(browser,engine,size){
 const context=await browser.newContext({
   viewport:{width:size.width,height:size.height},
   hasTouch:size.compact,isMobile:size.compact
 });
 try {
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.setContent(fixture);
  await page.addScriptTag({content:source});
  const geometry=()=>page.evaluate(()=>{
    const rect=selector=>{
      const {x,y,width,height}=document.querySelector(selector).getBoundingClientRect();
      return {x,y,width,height};
    };
    return {input:rect('.input'),text:rect('#text'),mode:rect('.manual-question-mode')};
  });
  await page.evaluate(()=>window.DMateChatComposer.mount({input:document.getElementById('text'),onSend:()=>{}}));
  const unfocused=await geometry();
  await page.locator('#text').focus();
  const focused=await geometry();
  assert.deepEqual(focused.input,unfocused.input,engine+'/'+size.name+': focus moved or resized the capsule');
  assert.deepEqual(focused.text,unfocused.text,engine+'/'+size.name+': focus moved or resized the textarea');
  if(size.compact){
    assert.equal(focused.mode.x,focused.input.x,engine+'/'+size.name+': initial mode switch must align left');
    await page.evaluate(()=>document.body.classList.add('mobile-keyboard-open'));
    assert.deepEqual((await geometry()).input,focused.input,engine+'/'+size.name+': keyboard class changed capsule geometry');
    await page.evaluate(()=>{
      document.body.classList.remove('mobile-keyboard-open');
      document.querySelector('.center').classList.remove('chat-empty');
    });
    const conversation=await geometry();
    assert.equal(conversation.mode.x,conversation.input.x,engine+'/'+size.name+': new conversation mode switch must align left');
    await page.evaluate(()=>document.querySelector('.center').classList.add('chat-empty'));
  }
  await page.evaluate(()=>{
    const input=document.getElementById('text');
    input.value='AB';input.focus();input.setSelectionRange(1,1);
  });
  await page.locator('.dmate-symbol-keyboard').click();
  const box=await page.evaluate(()=>{
    const p=document.querySelector('.dmate-symbol-panel');
    const i=document.querySelector('.input').getBoundingClientRect();
    const r=p.getBoundingClientRect(),h=p.querySelector('.dmate-symbol-panel-head').getBoundingClientRect();
    return {portal:p.parentElement===document.body,hidden:p.hidden,
       pos:getComputedStyle(p).position,x:r.left,y:r.top,right:r.right,bottom:r.bottom,
       headTop:h.top,headBottom:h.bottom,inputTop:i.top,inputBottom:i.bottom,
       vw:innerWidth,vh:innerHeight};
  });
  const label=engine+'/'+size.name;
  assert.equal(box.portal,true,label+': panel must belong to body');
  assert.equal(box.hidden,false);
  assert.equal(box.pos,'fixed');
  assert.ok(box.x>=5 && box.right<=box.vw-5,label+': horizontal '+JSON.stringify(box));
  assert.ok(box.y>=5 && box.bottom<=box.vh-5,label+': vertical '+JSON.stringify(box));
  assert.ok(box.headTop>=5 && box.headBottom<=box.vh-5,label+': header clipped '+JSON.stringify(box));
  if(!size.compact && box.inputTop>200) {
    assert.ok(box.bottom<=box.inputTop,label+': desktop should open above input');
  }
  if(size.compact && box.vh-box.inputBottom>=160) {
    assert.ok(box.y>=box.inputBottom,label+': compact should open below if space permits');
  }
  await page.locator('.dmate-symbol-tab[data-symbol-category="sets"]').click();
  const key=page.locator('.dmate-symbol-key[data-symbol-value="∈"]');
  assert.equal(await key.count(),1,label+': cannot select Sets tab');
  const hit=await page.evaluate(()=>{
    const el=document.querySelector('.dmate-symbol-key[data-symbol-value="∈"]'),r=el.getBoundingClientRect();
    const t=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
    return t===el || el.contains(t);
  });
  assert.equal(hit,true,label+': key covered by another layer');
  await key.click();
  assert.equal(await page.locator('#text').inputValue(),'A∈B',label+': click did not insert');
  await page.locator('#outside').click();
  assert.equal(await page.locator('.dmate-symbol-panel').getAttribute('hidden'),'',label+': outside click did not close');
  for(const theme of ['light','dark','navy']){
    await page.evaluate(t=>document.body.dataset.appearanceTheme=t,theme);
    await page.locator('.dmate-symbol-keyboard').click();
    const visible=await page.locator('.dmate-symbol-panel').evaluate(el=>{
      const style=getComputedStyle(el);
      return el.getBoundingClientRect().height>0 && style.backgroundColor!=='transparent' && style.backgroundColor!=='rgba(0, 0, 0, 0)';
    });
    assert.equal(visible,true,label+'/'+theme+': palette invisible');
    await page.locator('.dmate-symbol-keyboard').click();
  }
  assert.deepEqual(errors,[],label+': JavaScript page errors');
  console.log('PASS '+label+' '+box.vw+'x'+box.vh+' at '+Math.round(box.x)+','+Math.round(box.y));
 } finally {await context.close();}
}
(async()=>{
 for(const [engine,type] of [['Chromium',chromium],['WebKit Safari',webkit]]){
  const browser=await type.launch({headless:true});
  try {for(const size of sizes)await verify(browser,engine,size);}
  finally {await browser.close();}
 }
 console.log('All browser regressions passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
