/* Compare the real online/offline wallpaper layers, then exercise the copied
 * appearance controls and their persisted preview/confirm behavior.
 * Start Flask first; each run uses an isolated browser context.
 */
'use strict';
const assert = require('node:assert/strict');
const {inflateSync} = require('node:zlib');
const { chromium } = require('playwright');
const {installStorageProbe, revealInterface, row} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const profile = { mode:'dark', accent:'purple', backgroundFit:'contain',
  mask:17, blur:3, panelOpacity:80, bubbleOpacity:70 };

async function ready(page) {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await revealInterface(page);
}
async function openAppearance(page) {
  if (await page.locator('#offlineAppearanceBtn').count()) {
    const mobile = page.viewportSize().width <= 1100;
    const opener = page.locator(mobile ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
    if (await opener.getAttribute('aria-expanded') !== 'true') await opener.click();
    await page.locator('#offlineAppearanceBtn').click();
  } else {
    if (await page.locator('html').getAttribute('data-desktop-sidebar') === 'collapsed') {
      await page.locator('#desktopSidebarOpen').click();
    }
    await page.locator('#appearanceBtn').click();
  }
  await page.locator('#appearanceModal').waitFor({ state:'visible' });
}
async function settledWallpaper(page) {
  await page.waitForFunction(() => {
    const style = getComputedStyle(document.getElementById('appearanceBackgroundLayer'));
    return style.opacity === '1' && style.filter === 'blur(3px)';
  });
}
async function appearance(page) {
  return page.evaluate(() => {
    const result = {};
    for (const key of ['--panel-alpha','--workspace-alpha','--shell-alpha','--composer-alpha',
      '--bubble-alpha','--font-scale','--background-mask-alpha','--background-blur','--background-size','--accent']) {
      result[key] = document.documentElement.style.getPropertyValue(key);
    }
    // The offline workspace retains its four-panel layout. Only shared wallpaper
    // layers and appearance settings must match the online application.
    for (const [name,selector] of [['background','#appearanceBackgroundLayer'],['mask','.appearance-mask-layer']]) {
      const node = document.querySelector(selector);
      if (!node) throw new Error('Missing shared visual element: ' + selector);
      const style = getComputedStyle(node);
      result[name] = { background:style.backgroundColor, opacity:style.opacity,
        filter:style.filter, backgroundSize:style.backgroundSize };
    }
    result.hasBackground = document.body.classList.contains('has-custom-background');
    return result;
  });
}
async function appearanceControls(page) {
  await checkSliders(page);
  assert.equal(await page.locator('#appearanceModal [data-appearance-font]').count(), 0);
  const dialog = page.locator('#appearanceModal');
  assert.equal(await dialog.getByText(/^(显示模式|Display mode)$/i).count(), 0);
  assert.equal(await dialog.locator('[data-appearance-mode]').count(), 0);
  assert.deepEqual(await page.locator('#appearanceModal [data-appearance-accent]').evaluateAll(nodes =>
    nodes.map(node => node.dataset.appearanceAccent).sort()), ['blue', 'purple']);
  const separators = await page.locator('#appearanceModal').evaluate(dialog => [
    ...[...dialog.querySelectorAll('.modal-head, .appearance-section')].map(node => getComputedStyle(node).borderBottomWidth),
    ...[...dialog.querySelectorAll('.appearance-apply-hint, .appearance-footer')].map(node => getComputedStyle(node).borderTopWidth)
  ]);
  assert.ok(separators.length > 0 && separators.every(width => width === '0px'),
    'Appearance groups and dialog chrome have no internal divider lines');
  return page.locator('#appearanceModal').evaluate(dialog => {
    const selectors = ['.appearance-card', '.modal-head', '.appearance-section-title',
      '[data-appearance-accent="blue"]', '[data-appearance-accent="purple"]',
      '[data-appearance-fit="contain"]', '#appearanceMaskRange', '#appearanceBlurRange',
      '#appearancePanelRange', '#appearanceBubbleRange', '#appearanceDone', '#appearanceClose'];
    return Object.fromEntries(selectors.map(selector => {
      const node = dialog.querySelector(selector), style = getComputedStyle(node);
      return [selector, Object.fromEntries(['backgroundColor', 'color', 'fontFamily', 'fontSize', 'fontWeight',
        'borderTopColor', 'borderTopWidth', 'borderRadius', 'boxShadow'].map(key => [key, style[key]]))];
    }));
  });
}

async function filledAppearanceActions(page) {
  const surface = await page.locator('#appearanceModal .appearance-card').evaluate(node => getComputedStyle(node).backgroundColor);
  const enabledPalettes = [];
  for (const id of ['appearanceBackgroundUpload','appearanceBackgroundRemove','appearanceReset','appearanceDone']) {
    const button = page.locator('#' + id);
    const paint = () => button.evaluate(node => {
      const style = getComputedStyle(node);
      return { border:style.borderWidth, background:style.backgroundColor, color:style.color, image:style.backgroundImage, shadow:style.boxShadow };
    });
    await page.mouse.move(0, 0);
    await page.waitForTimeout(150);
    const idle = await paint();
    assert.equal(idle.border, '0px', id + ' has no outlined edge');
    assert.equal(idle.image, 'none');
    assert.equal(idle.shadow, 'none');
    assert.notEqual(idle.background, 'rgba(0, 0, 0, 0)', id + ' retains a filled surface');
    assert.notEqual(idle.background, surface, id + ' stays distinct from the dialog surface');
    if (await button.isEnabled()) {
      enabledPalettes.push([idle.background, idle.color]);
      await button.hover();
      await page.waitForFunction(({ id, color }) => getComputedStyle(document.getElementById(id)).backgroundColor !== color,
        { id, color:idle.background });
    }
  }
  for (const palette of enabledPalettes) assert.deepEqual(palette, enabledPalettes[0],
    'Choose image, remove background and the footer actions share the same neutral palette');
  await page.mouse.move(0, 0);
  await page.waitForTimeout(150);
}

async function settlePalette(page) {
  await page.evaluate(async()=>{
    await Promise.all(document.getAnimations().filter(animation=>
      animation.effect?.getComputedTiming().iterations!==Infinity).map(animation=>animation.finished.catch(()=>{})));
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  });
}

async function surfacePixel(page,locator,{left=7,top}={}) {
  const box=await locator.boundingBox();
  const png=await page.screenshot({clip:{x:Math.floor(box.x+(left??box.width/2)),y:Math.floor(box.y+(top??box.height/2)),width:1,height:1}});
  assert.ok([2,6].includes(png[25]),'The screenshot stores RGB pixels');
  const chunks=[];
  for(let offset=8;offset<png.length;){
    const size=png.readUInt32BE(offset);
    if(png.toString('ascii',offset+4,offset+8)==='IDAT')chunks.push(png.subarray(offset+8,offset+8+size));
    offset+=size+12;
  }
  // A one-pixel first scanline has no left/up pixel; every PNG filter's
  // predictor is zero, so these bytes are the actual visible RGB.
  return [...inflateSync(Buffer.concat(chunks)).subarray(1,4)];
}

async function checkSliders(page) {
  const sliders=page.locator('#appearanceModal input[type="range"]'), bubble=page.locator('#appearanceBubbleRange');
  const checkProgress=async()=> {
    const values=await sliders.evaluateAll(nodes=>nodes.map(node=>({
      id:node.id, progress:getComputedStyle(node).getPropertyValue('--appearance-range-progress').trim(),
      expected:100*(node.valueAsNumber-Number(node.min))/(Number(node.max)-Number(node.min))
    })));
    assert.equal(values.length,4);
    for(const {id,progress,expected} of values) {
      assert.ok(progress.endsWith('%') && Math.abs(parseFloat(progress)-expected)<.001,id+' normalizes its fill between min and max');
    }
  };
  assert.equal(await bubble.inputValue(),String(profile.bubbleOpacity));
  await checkProgress();
  for(const [accent,color] of [['purple',[139,92,246]],['blue',[59,130,246]]]) {
    await page.locator('[data-appearance-accent="'+accent+'"]').click();
    await bubble.scrollIntoViewIfNeeded();
    await settlePalette(page);
    const box=await bubble.boundingBox(), fraction=await bubble.evaluate(node=>
      (node.valueAsNumber-Number(node.min))/(Number(node.max)-Number(node.min)));
    const thumbX=box.height/2+fraction*(box.width-box.height);
    assert.deepEqual(await surfacePixel(page,bubble,{left:thumbX/2}),color,accent+' fills the selected part of the slider');
    assert.deepEqual(await surfacePixel(page,bubble,{left:(thumbX+box.width)/2}),[59,59,59],accent+' leaves the remaining rail neutral');
    assert.deepEqual(await surfacePixel(page,bubble,{left:thumbX,top:box.height/5}),color,accent+' paints the thumb above the track');
  }
  await bubble.press('ArrowRight');
  assert.equal(await bubble.inputValue(),String(profile.bubbleOpacity+1));
  assert.ok(await bubble.evaluate(node=>node===document.activeElement && node.matches(':focus-visible')),
    'The slider retains keyboard focus after an arrow-key adjustment');
  await checkProgress();
  await page.locator('#appearanceClose').click();
  await openAppearance(page);
  assert.equal(await bubble.inputValue(),String(profile.bubbleOpacity),'Cancelling restores the previous slider value');
  assert.equal(await bubble.evaluate(node=>getComputedStyle(node).accentColor),'rgb(139, 92, 246)','Cancelling restores the saved purple accent');
  await checkProgress();
}

async function sharedThemeSurfaces(browser,width,offline) {
  const context=await browser.newContext({viewport:{width,height:900},deviceScaleFactor:1,serviceWorkers:'block'});
  const page=await context.newPage(),edition=offline?'offline':'online';
  const paint=locator=>locator.evaluate(node=>{
    const css=getComputedStyle(node),rgba=css.backgroundColor.match(/[\d.]+/g).map(Number);
    return {rgb:rgba.slice(0,3),alpha:rgba[3]??1,opacity:Number(css.opacity),image:css.backgroundImage};
  });
  const checkPaint=async(locator,base,alpha,label)=>{
    const value=await paint(locator);
    assert.deepEqual(value.rgb,base,label+': the panel uses the theme dialog color');
    assert.ok(Math.abs(value.alpha-alpha)<.001,label+': panel transparency remains adjustable');
    assert.equal(value.opacity,1,label+': text and controls do not inherit panel transparency');
    assert.equal(value.image,'none',label+': no image or gradient overrides the panel base');
  };
  try{
    await page.goto(baseURL+(offline?'/offline':''),{waitUntil:'networkidle'});
    if(offline)await ready(page);
    else await page.evaluate(()=>{
      newChat();getCurrent().name='主题验证';getCurrent().nameSource='user';
      getCurrent().messages=[{role:'user',text:'颜色验证'},{role:'ai',text:'这是一段普通讲解。'}];renderChat();
    });
    await page.evaluate(async offline=>{
      if(offline)await DMateOfflineAppearance.apply({...DMateOfflineAppearance.getSettings(),mode:'dark',panelOpacity:100},null);
      else{clearAppearanceBackgroundVisual();appearanceSettings={...APPEARANCE_DEFAULTS,mode:'dark',panelOpacity:100};applyAppearanceSettings({save:true});}
    },offline);
    await settlePalette(page);
    const base=await surfacePixel(page,page.locator(offline?'#offlineMain':'#chat'),{left:null,...(offline?{top:3}:{})});
    assert.deepEqual(base,[13,13,13],edition+'/'+width+': actual visible workspace color');
    const modalColor=[34,34,34];
    const opener=page.locator(offline?(width<=1100?'#offlineNavToggle':'#offlineDesktopSidebarOpen')
      :(width<=1100?'#mobileNavBtn':'#desktopSidebarOpen'));
    if(await opener.getAttribute('aria-expanded')!=='true')await opener.click();
    await settlePalette(page);
    const sidebar=page.locator(offline?'#offlineSidebar':'#conversationSidebar');
    const sidebarPaint=await paint(sidebar);
    assert.equal(sidebarPaint.alpha,1);
    assert.deepEqual(await surfacePixel(page,sidebar),sidebarPaint.rgb,edition+'/'+width+': visible sidebar pixels match its theme');
    if(width<=1100){
      if(offline)await page.locator('#offlineNavClose').click();
      else await page.evaluate(()=>closeMobileShellDrawers());
      await settlePalette(page);
    }
    await page.evaluate(offline=>offline?DMateOfflineAppearance.open():openAppearance(),offline);
    const card=page.locator('#appearanceModal .appearance-card');
    await card.waitFor({state:'visible'});await settlePalette(page);
    for(const alpha of [1,.8]){
      if(alpha<1){
        await page.locator('#appearancePanelRange').evaluate(node=>{node.value='80';node.dispatchEvent(new Event('input',{bubbles:true}));});
        await settlePalette(page);
      }
      const label=edition+'/'+width+'/'+alpha;
      await checkPaint(card,modalColor,alpha,label+' appearance');
      if(alpha===1)assert.deepEqual(await surfacePixel(page,card),modalColor,label+': actual appearance pixels match the dialog color');
      await page.evaluate(()=>{void DMateDeleteConfirm.request(document.getElementById('appearanceModal'),
        {title:'颜色核对',body:'用于验证弹窗背景。',noticeOnly:true});});
      const notice=page.locator('.dmate-delete-confirm[open]');
      await notice.waitFor({state:'visible'});await settlePalette(page);
      await checkPaint(notice,modalColor,alpha,label+' native notice');
      assert.equal(await notice.locator('.dmate-delete-confirm-title').evaluate(node=>getComputedStyle(node).opacity),'1');
      if(alpha===1)assert.deepEqual(await surfacePixel(page,notice),modalColor,label+': native dialog pixels match the dialog color');
      await notice.locator('.dmate-delete-confirm-close').click();
      await notice.waitFor({state:'detached'});
    }
    await page.locator('#appearanceClose').click();
    await page.waitForFunction(()=>document.documentElement.style.getPropertyValue('--panel-alpha').trim()==='1');
    console.log('PASS '+edition+' '+width+': actual chat/sidebar pixels, shared modal/native colors and live panel opacity');
  }finally{await context.close();}
}

(async () => {
  const browser = await chromium.launch({ headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath:process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  const context = await browser.newContext({ viewport:{ width:1440, height:900 } });
  await installStorageProbe(context);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    for(const width of [1440,390])for(const offline of [false,true])await sharedThemeSurfaces(browser,width,offline);
    await page.goto(baseURL + '/', { waitUntil:'networkidle' });
    await page.evaluate(async settings => {
      appearanceSettings = { ...APPEARANCE_DEFAULTS, ...settings };
      applyAppearanceSettings({ save:true });
      const canvas = document.createElement('canvas'); canvas.width = 80; canvas.height = 60;
      const drawing = canvas.getContext('2d'); drawing.fillStyle = '#326a8f'; drawing.fillRect(0,0,80,60);
      const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/png'));
      await writeAppearanceBackgroundBlob(blob);
      setAppearanceBackgroundVisual(blob);
      const snapshot = await window.DMateOfflineBridge.snapshot();
      snapshot.appearance.settings.fontSize = 'small';
      if (Array.isArray(snapshot.drawings)) snapshot.drawings = JSON.stringify({version:2,activeId:snapshot.drawings[0]?.id || '',pages:snapshot.drawings});
      await DMateOfflineHandoff.stage(snapshot);
    }, { ...profile, fontSize:'large' });
    await settledWallpaper(page);
    const online = await appearance(page);
    assert.equal(online['--font-scale'], '1', 'A legacy size uses standard text in the online application');
    await openAppearance(page);
    await filledAppearanceActions(page);
    const onlineControls = await appearanceControls(page);
    await page.locator('#appearanceClose').click();
    await page.goto(baseURL + '/offline', { waitUntil:'networkidle' });
    await ready(page);
    await settledWallpaper(page);
    assert.equal((await row(page, 'settings', 'appearance')).settings.fontSize, 'small',
      'Opening existing device settings leaves the stored record intact');
    assert.deepEqual(await appearance(page), online,
      'Offline wallpaper, theme, font, opacity, and shared background layers must match online');
    console.log('PASS online/offline custom wallpaper, ten appearance variables, and both background layers match');

    await openAppearance(page);
    await filledAppearanceActions(page);
    assert.deepEqual(await appearanceControls(page), onlineControls, 'The full appearance dialog retains online control styles');
    const png = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 8;
      const drawing = canvas.getContext('2d'); drawing.fillStyle = '#c78336'; drawing.fillRect(0,0,8,8);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.locator('#appearanceBackgroundInput').setInputFiles({
      name:'background.png', mimeType:'image/png', buffer:Buffer.from(png,'base64')
    });
    await page.waitForFunction(() => document.getElementById('appearanceBackgroundPreview').dataset.hasBackground === 'true'
      && !document.getElementById('appearanceDone').disabled);
    await page.locator('#appearanceBackgroundPreview').click();
    await page.locator('#appearanceBackgroundViewer').waitFor({ state:'visible' });
    await page.locator('#appearanceBackgroundViewerClose').click();
    await page.locator('#appearanceDone').click();
    await page.locator('#appearanceModal').waitFor({ state:'hidden' });
    await page.reload({ waitUntil:'networkidle' }); await ready(page); await settledWallpaper(page);
    assert.deepEqual(await page.evaluate(() => window.DMateOfflineAppearance.getSettings()), profile);
    assert.deepEqual((await row(page, 'settings', 'appearance')).settings, profile,
      'Confirming appearance removes the legacy size and preserves the other settings');
    assert.equal(await page.evaluate(() => window.DMateOfflineAppearance.getBackground()?.type), 'image/webp');
    assert.equal(await page.evaluate(() => document.body.classList.contains('has-custom-background')), true);
    console.log('PASS uploaded PNG is prepared, previewed, confirmed, and retained with settings after reload');

    await openAppearance(page);
    await page.locator('#appearanceBackgroundRemove').click();
    assert.equal(await page.evaluate(() => document.body.classList.contains('has-custom-background')), false);
    await page.locator('#appearanceClose').click();
    assert.equal(await page.evaluate(() => document.body.classList.contains('has-custom-background')), true);
    await settledWallpaper(page);
    console.log('PASS closing a removal preview restores the confirmed wallpaper');

    // Fail only this isolated context's appearance write, then retry through
    // the real controls. The failed draft must remain editable and uncommitted.
    await openAppearance(page);
    await page.locator('[data-appearance-accent="blue"]').click();
    await page.evaluate(() => { window.__failOfflineAppearanceSave = true; });
    await page.locator('#appearanceDone').click();
    await page.locator('.dmate-delete-confirm[open]').waitFor({ state:'visible' });
    assert.equal(await page.locator('#appearanceDone').isDisabled(), false, 'Saving failure must permit retry');
    assert.equal(await page.evaluate(() => window.DMateOfflineAppearance.getSettings().accent), 'purple');
    await page.keyboard.press('Escape');
    await page.locator('.dmate-delete-confirm[open]').waitFor({ state:'detached' });
    assert.equal(await page.locator('#appearanceModal').isVisible(), true, 'Notice dismissal must preserve the draft');
    await page.evaluate(() => { window.__failOfflineAppearanceSave = false; });
    await page.locator('#appearanceDone').click();
    await page.locator('#appearanceModal').waitFor({ state:'hidden' });
    await page.reload({ waitUntil:'networkidle' }); await ready(page);
    assert.equal(await page.evaluate(() => window.DMateOfflineAppearance.getSettings().accent), 'blue');
    assert.equal(await page.evaluate(() => document.body.classList.contains('has-custom-background')), true);
    assert.deepEqual(errors, [], 'Appearance interactions must not produce page errors');
    console.log('PASS failed storage preserves the draft and wallpaper; retry persists successfully');
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
