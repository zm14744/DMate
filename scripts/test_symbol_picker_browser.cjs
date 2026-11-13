/* Regression: Mac Safari, desktop Chromium, iPad and Split View. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium,webkit}=require('playwright');
const root=path.resolve(__dirname,'..');
const style=fs.readFileSync(path.join(root,'static/chat-composer.css'),'utf8');
const source=fs.readFileSync(path.join(root,'static/chat-composer.js'),'utf8');
const uiSources=['language-catalog.js','language-knowledge.js','language.js','ui-tooltip.js']
 .map(name=>fs.readFileSync(path.join(root,'static',name),'utf8'));
const tooltipStyle=fs.readFileSync(path.join(root,'static/ui-tooltip.css'),'utf8');

// Independent UI/Unicode oracle: do not obtain expected translations or values
// from the implementation under test. Duplicate glyphs have category meanings.
const symbols=[
 {id:'logic',zh:'逻辑',en:'Logic',items:[
 ['¬','逻辑非','Negation'],['∧','合取','Conjunction'],['∨','析取','Disjunction'],
 ['⊕','异或','Exclusive or'],['→','蕴含','Implication'],['↔','等价','Biconditional'],
 ['⇒','推出','Implies'],['⇔','等价推出','Logical equivalence'],
 ['∀','全称量词','Universal quantifier'],['∃','存在量词','Existential quantifier'],
 ['∄','不存在','Does not exist'],['⊤','永真','Tautology / true'],
 ['⊥','矛盾／假','Contradiction / false'],['⊢','语法可证','Syntactic derivability'],
 ['⊨','语义蕴含','Semantic entailment'],['⊭','不语义蕴含','Does not entail'],
 ['∴','所以','Therefore'],['∵','因为','Because']
 ]},
 {id:'sets',zh:'集合',en:'Sets',items:[
 ['∈','属于','Element of'],['∉','不属于','Not an element of'],
 ['∋','包含元素','Contains as an element'],['∌','不包含元素','Does not contain as an element'],
 ['⊆','子集或等于','Subset or equal'],['⊊','真子集','Proper subset'],
 ['⊂','子集（依教材约定）','Subset (textbook convention)'],['⊇','超集或等于','Superset or equal'],
 ['⊋','真超集','Proper superset'],['⊃','超集（依教材约定）','Superset (textbook convention)'],
 ['∪','并集','Union'],['∩','交集','Intersection'],['∅','空集','Empty set'],
 ['∖','集合差','Set difference'],['℘','幂集','Power Set'],['×','笛卡尔积','Cartesian Product'],
 ['∁','补集','Complement'],['⊄','非子集','Not a subset'],
 ['⊈','非子集或等于','Not a subset or equal'],['∣','整除／集合关系符号','Divides / set relation symbol']
 ]},
 {id:'relations',zh:'关系',en:'Relations',items:[
 ['≠','不等于','Not equal'],['≡','恒等／同余','Identical / congruent'],
 ['≢','不恒等','Not identical'],['≈','约等于','Approximately equal'],
 ['≉','不约等于','Not approximately equal'],['∼','等价／相似关系','Equivalence / similarity relation'],
 ['≃','相似','Similar'],['≤','小于等于','Less than or equal'],['≥','大于等于','Greater than or equal'],
 ['≪','远小于','Much less than'],['≫','远大于','Much greater than'],
 ['∝','正比于','Proportional to'],['∥','平行','Parallel'],['⊥','垂直','Perpendicular'],
 ['∘','关系复合','Relation composition'],['≺','先于','Precedes'],['≼','不严格先于','Precedes or equals']
 ]},
 {id:'number',zh:'数论',en:'Number Theory',items:[
 ['ℕ','自然数集','Natural numbers'],['ℤ','整数集','Integers'],['ℚ','有理数集','Rational numbers'],
 ['ℝ','实数集','Real numbers'],['ℂ','复数集','Complex numbers'],['∣','整除','Divides'],
 ['∤','不整除','Does not divide'],['≡','同余','Congruent'],['∞','无穷大','Infinity'],
 ['⌊x⌋','向下取整','Floor'],['⌈x⌉','向上取整','Ceiling'],['√n','平方根','Square root']
 ]},
 {id:'count',zh:'计数',en:'Counting',items:[
 ...Array.from('⁰¹²³⁴⁵⁶⁷⁸⁹',(value,i)=>[value,'上标 '+i,'Superscript '+i]),
 ...Array.from('₀₁₂₃₄₅₆₇₈₉',(value,i)=>[value,'下标 '+i,'Subscript '+i]),
 ['∑','求和','Summation'],['∏','连乘','Product'],['ⁿ','上标 n','Superscript n'],
 ['ₙ','下标 n','Subscript n'],['…','省略号','Ellipsis']
 ]},
 {id:'greek',zh:'希腊',en:'Greek',items:[
 ['α','小写阿尔法','Lowercase alpha'],['β','小写贝塔','Lowercase beta'],
 ['γ','小写伽马','Lowercase gamma'],['δ','小写德尔塔','Lowercase delta'],
 ['ε','小写艾普西龙','Lowercase epsilon'],['ζ','小写泽塔','Lowercase zeta'],
 ['η','小写伊塔','Lowercase eta'],['θ','小写西塔','Lowercase theta'],
 ['ι','小写约塔','Lowercase iota'],['κ','小写卡帕','Lowercase kappa'],
 ['λ','小写拉姆达','Lowercase lambda'],['μ','小写缪','Lowercase mu'],
 ['ν','小写纽','Lowercase nu'],['ξ','小写克西','Lowercase xi'],
 ['π','小写派','Lowercase pi'],['ρ','小写柔','Lowercase rho'],
 ['σ','小写西格马','Lowercase sigma'],['τ','小写陶','Lowercase tau'],
 ['υ','小写宇普西龙','Lowercase upsilon'],['φ','小写斐','Lowercase phi'],
 ['χ','小写希','Lowercase chi'],['ψ','小写普西','Lowercase psi'],
 ['ω','小写欧米伽','Lowercase omega'],['Γ','大写伽马','Uppercase Gamma'],
 ['Δ','大写德尔塔','Uppercase Delta'],['Θ','大写西塔','Uppercase Theta'],
 ['Λ','大写拉姆达','Uppercase Lambda'],['Π','大写派','Uppercase Pi'],
 ['Σ','大写西格马','Uppercase Sigma'],['Φ','大写斐','Uppercase Phi'],
 ['Ψ','大写普西','Uppercase Psi'],['Ω','大写欧米伽','Uppercase Omega']
 ]}
];
assert.equal(symbols.reduce((n,group)=>n+group.items.length,0),124);
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

async function verifyTranslations(browser,engine,size){
 const context=await browser.newContext({
  viewport:{width:size.width,height:size.height},hasTouch:size.compact,isMobile:size.compact
 });
 const label=engine+'/'+size.name+'/i18n';
 try {
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  // Exercise the real delayed tooltip without spending 360 ms per symbol.
  await page.clock.install();
  await page.setContent(fixture.replace('</head>','<style>'+tooltipStyle+'</style></head>'));
  await page.evaluate(()=>{
   const content=document.createElement('div');
   content.id='protected-math';content.dataset.i18nContent='';content.hidden=true;
   content.textContent='等价 集合 ∣ α Γ 上标 2';document.body.append(content);
  });
  // Match the page's catalog registration order, including knowledge labels
  // that can override an identically named generic catalog entry.
  for(const content of uiSources.slice(0,3))await page.addScriptTag({content});
  await page.addScriptTag({content:source});
  await page.addScriptTag({content:uiSources[3]});
  await page.evaluate(()=>{
   window.DMateChatComposer.mount({input:document.getElementById('text'),onSend:()=>{}});
   document.getElementById('text').addEventListener('input',event=>{
    window.lastSymbolInput={data:event.data,inputType:event.inputType};
   });
  });
  await page.locator('.dmate-symbol-keyboard').click();
  const panel=page.locator('.dmate-symbol-panel');
  const tab=id=>page.locator('.dmate-symbol-tab[data-symbol-category="'+id+'"]');
  const keyAt=index=>page.locator('.dmate-symbol-key').nth(index);
  const tooltip=page.locator('.dm-ui-tooltip:not([hidden])');
  async function showTooltip(key,expected){
   // Scrolling dismisses a real tooltip. Finish Playwright's key auto-scroll
   // before initiating a fresh hover, particularly for the last Greek row.
   await key.scrollIntoViewIfNeeded();
   await page.clock.fastForward(50);
   // Returning from outside also clears tooltip dismissal after insertion.
   await page.mouse.move(1,1);
   await key.hover();
   await page.clock.fastForward(400);
   assert.equal(await tooltip.count(),1,label+': missing hover tooltip '+expected);
   assert.equal(await tooltip.textContent(),expected,label+': stale/incorrect tooltip');
   assert.equal(await key.getAttribute('aria-describedby'),await tooltip.getAttribute('id'),label+': inaccessible tooltip');
  }

  // Switch languages while a key owns the suppressed native title. This
  // catches stale tooltip caches and accidental rerenders/caret loss.
  await tab('greek').click();
  const gamma=keyAt(23);
  await gamma.focus();
  await page.evaluate(()=>{
   const input=document.getElementById('text');
   input.value='Before αΓ_² after';input.setSelectionRange(7,9,'backward');
   window.savedSymbolKey=document.activeElement;
   window.savedSymbolTab=document.querySelector('.dmate-symbol-tab[aria-selected="true"]');
   window.savedSymbolState={value:input.value,start:input.selectionStart,end:input.selectionEnd,direction:input.selectionDirection};
  });
  await showTooltip(gamma,'大写伽马');
  for(const language of ['en','zh-CN','en']){
   await page.evaluate(value=>window.DMateI18n.setLanguage(value,false),language);
   const retained=await page.evaluate(()=>{
    const input=document.getElementById('text');
    return {state:{value:input.value,start:input.selectionStart,end:input.selectionEnd,direction:input.selectionDirection},
     saved:window.savedSymbolState,sameKey:document.activeElement===window.savedSymbolKey,
     sameTab:document.querySelector('.dmate-symbol-tab[aria-selected="true"]')===window.savedSymbolTab,
     category:document.querySelector('.dmate-symbol-tab[aria-selected="true"]').dataset.symbolCategory,
     open:!document.querySelector('.dmate-symbol-panel').hidden};
   });
   assert.deepEqual(retained.state,retained.saved,label+': language switch changed draft/selection');
   assert.equal(retained.sameKey,true,label+': language switch lost the focused key');
   assert.equal(retained.sameTab,true,label+': language switch recreated the current tab');
   assert.equal(retained.category,'greek');assert.equal(retained.open,true);
   await showTooltip(gamma,language==='en'?'Uppercase Gamma':'大写伽马');
  }
  await page.locator('#outside').focus();
  await page.mouse.move(1,1);
  assert.equal(await gamma.getAttribute('title'),'Uppercase Gamma',label+': hover cache restored an old-language title');

  let insertions=0;
  for(const language of ['zh-CN','en']){
   const english=language==='en';
   await page.evaluate(value=>window.DMateI18n.setLanguage(value,false),language);
   assert.equal(await page.locator('.dmate-symbol-panel-title').textContent(),english?'Math symbols':'数学符号');
   assert.equal(await panel.getAttribute('aria-label'),english?'Math symbol keyboard':'数学符号键盘');
   assert.equal(await page.locator('.dmate-symbol-keyboard').getAttribute('aria-label'),english?'Math symbol keyboard':'数学符号键盘');
   assert.equal(await page.locator('.dmate-symbol-tabs').getAttribute('aria-label'),english?'Symbol categories':'符号分类');
   assert.equal(await page.locator('.dmate-symbol-grid').getAttribute('aria-label'),english?'Insertable math symbols':'可插入的数学符号');
   for(const group of symbols){
    await tab(group.id).click();
    await page.mouse.move(1,1);
    await page.locator('#outside').focus();
    assert.deepEqual(await page.locator('.dmate-symbol-tab').allTextContents(),symbols.map(item=>english?item.en:item.zh));
    assert.equal(await tab(group.id).getAttribute('aria-selected'),'true');
    const actual=await page.locator('.dmate-symbol-key').evaluateAll(keys=>keys.map(key=>({
     text:key.textContent,value:key.dataset.symbolValue,title:key.getAttribute('title'),
     aria:key.getAttribute('aria-label'),protectedGlyph:key.querySelector('span')?.getAttribute('translate')
    })));
    const expected=group.items.map(([value,zh,en])=>({
     text:value,value,title:english?en:zh,aria:(english?en+': ':zh+'：')+value,protectedGlyph:'no'
    }));
    assert.deepEqual(actual,expected,label+'/'+language+'/'+group.id+': incomplete/incorrect symbol names or values');
    for(let index=0;index<group.items.length;index++){
     const [value,zh,en]=group.items[index],key=keyAt(index),name=english?en:zh;
     assert.equal(await page.locator('.dmate-symbol-grid').getByRole('button',{name:(english?name+': ':name+'：')+value,exact:true}).count(),1);
     await showTooltip(key,name);
     await page.evaluate(()=>{
      const input=document.getElementById('text');input.value='Before αΓ_² after';
      input.setSelectionRange(7,9,'backward');window.lastSymbolInput=null;
     });
     await key.click();
     const inserted=await page.locator('#text').evaluate(input=>({
      value:input.value,start:input.selectionStart,end:input.selectionEnd,event:window.lastSymbolInput
     }));
     assert.deepEqual(inserted,{value:'Before '+value+'_² after',start:7+value.length,end:7+value.length,
      event:{data:value,inputType:'insertText'}},label+'/'+language+'/'+group.id+': altered inserted Unicode '+value);
     assert.equal(await panel.getAttribute('hidden'),null,label+': inserting a symbol closed the panel');
     insertions++;
    }
   }
   assert.equal(await page.locator('#protected-math').textContent(),'等价 集合 ∣ α Γ 上标 2',label+': language pass rewrote content');
  }
  assert.equal(insertions,248);
  assert.deepEqual(errors,[],label+': JavaScript page errors');
  console.log('PASS '+label+' all 124 symbols in both languages, hover names, insertion, open-panel language switching');
 } finally {await context.close();}
}
(async()=>{
 const requested=(process.env.SYMBOL_PICKER_BROWSERS||'chromium,webkit').split(',');
 assert.ok(requested.length && requested.every(name=>['chromium','webkit'].includes(name)),'Unknown SYMBOL_PICKER_BROWSERS engine');
 for(const [id,engine,type] of [['chromium','Chromium',chromium],['webkit','WebKit Safari',webkit]]){
  if(!requested.includes(id))continue;
  const options={headless:true};
  if(id==='chromium' && process.env.CHROMIUM_EXECUTABLE_PATH)options.executablePath=process.env.CHROMIUM_EXECUTABLE_PATH;
  const browser=await type.launch(options);
  try {
   for(const size of sizes)await verify(browser,engine,size);
   for(const size of [sizes[0],sizes.at(-1)])await verifyTranslations(browser,engine,size);
  }
  finally {await browser.close();}
 }
 console.log('All browser regressions passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
