/* Start Flask first; exercises the actual mobile drawer controls without AI. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const near = (actual, expected, message, tolerance = 2) => assert.ok(Math.abs(actual - expected) <= tolerance,
  message + ': ' + actual + ' vs ' + expected);

async function openDrawer(page, kind) {
  await page.locator(kind === 'tools' ? '#mobileToolsBtn' : '#mobileNavBtn').tap();
  await page.waitForFunction(value => document.body.classList.contains(value),
    kind === 'tools' ? 'mobile-tools-open' : 'mobile-left-open');
  await page.locator(kind === 'tools' ? '#learningToolsPanel' : '#conversationSidebar').evaluate(async node => {
    await Promise.all(node.getAnimations().map(animation => animation.finished.catch(() => {})));
  });
}

async function closeDrawer(page, kind) {
  await page.locator(kind === 'tools' ? '#mobileToolsClose' : '#mobileNavClose').tap();
  await page.waitForFunction(() => !document.body.classList.contains('mobile-left-open')
    && !document.body.classList.contains('mobile-tools-open'));
}

async function checkHeader(page, sidebar) {
  const state = await page.locator(sidebar + ' > .mobile-drawer-head').evaluate(head => {
    const button = head.querySelector('button'), box = head.getBoundingClientRect(), rect = button.getBoundingClientRect();
    const style = getComputedStyle(button), walker = document.createTreeWalker(head, NodeFilter.SHOW_TEXT);
    let node, visibleText = '';
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim() || node.parentElement.closest('button')) continue;
      const range = document.createRange(); range.selectNode(node);
      const bounds = range.getBoundingClientRect();
      if (bounds.width && bounds.height) visibleText += node.textContent.trim();
    }
    return { text: visibleText, width: rect.width, height: rect.height,
      rightGap: box.right - rect.right, left: rect.left, background: style.backgroundColor, radius: style.borderRadius };
  });
  assert.equal(state.text, '', sidebar + ': top row contains only its close control');
  assert.ok(state.width >= 12 && state.height >= 12, sidebar + ': close dot is visible');
  near(state.width, state.height, sidebar + ': close dot is round', .5);
  assert.ok(state.rightGap >= -1 && state.rightGap <= 8, sidebar + ': close stays at the right edge');
  const [red, green, blue] = state.background.match(/[\d.]+/g).map(Number);
  assert.ok(red > 180 && green < 120 && blue < 120, sidebar + ': close dot remains red');
}

async function checkTools(page, empty) {
  await page.waitForFunction(() => !document.getElementById('conversationInfoSection').hasAttribute('data-info-animating'));
  const state = await page.evaluate(() => {
    const section = document.getElementById('conversationInfoSection');
    const info = document.getElementById('info'), box = info.getBoundingClientRect(), css = getComputedStyle(info);
    const range = document.createRange(); range.selectNodeContents(info);
    const text = range.getBoundingClientRect();
    const heading = document.getElementById('conversationInfoHeading');
    const first = heading.firstElementChild || heading;
    const second = document.querySelector('#learningToolsPanel .learning-title').firstElementChild;
    const firstBox = first.getBoundingClientRect(), secondBox = second.getBoundingClientRect();
    const style = node => Object.fromEntries(['fontSize', 'fontWeight', 'fontFamily', 'color', 'lineHeight']
      .map(key => [key, getComputedStyle(node)[key]]));
    const panel = document.querySelector('#learningToolsPanel .learning-panel'), panelBox = panel.getBoundingClientRect();
    const lines = [...info.querySelectorAll('.conversation-info-line')].map(line => {
      const lineRange = document.createRange(); lineRange.selectNodeContents(line);
      const bounds = lineRange.getBoundingClientRect();
      return bounds.left + bounds.width / 2;
    });
    return { sectionHidden:section.hidden, ariaHidden:section.getAttribute('aria-hidden'),
      infoVisible:Boolean(box.width && box.height), text: info.textContent.trim(), center: box.x + box.width / 2, textCenter: text.x + text.width / 2,
      centerY: box.y + box.height / 2, textCenterY: text.y + text.height / 2,
      contentLeft: box.left + info.clientLeft + parseFloat(css.paddingLeft), lines,
      infoBottom: box.bottom, separatorTop: panelBox.top, border: parseFloat(getComputedStyle(panel).borderTopWidth),
      headingTop: secondBox.top, firstLeft: firstBox.left, secondLeft: secondBox.left,
      firstStyle: style(first), secondStyle: style(second), firstText: first.textContent.trim(), secondText: second.textContent.trim(),
      secondVisible: Boolean(secondBox.width && secondBox.height) };
  });
  assert.equal(state.firstText, '对话信息');
  assert.equal(state.secondText, '学习工具');
  assert.ok(state.secondVisible, 'Learning tools section heading remains visible');
  assert.deepEqual(state.secondStyle, state.firstStyle, 'Section headings use matching typography');
  if (empty) {
    assert.equal(state.sectionHidden,true,'Empty conversation information, including its heading, is removed');
    assert.equal(state.ariaHidden,'true','Empty information stays out of the accessibility tree');
    assert.equal(state.infoVisible,false,'No empty information placeholder remains visible');
    assert.equal(state.border,0,'There is no orphaned separator above learning tools');
    assert.notEqual(state.text,'无','Empty information does not render the old None placeholder');
  } else {
    assert.equal(state.sectionHidden,false,'A real message makes conversation information available');
    assert.ok(state.border > 0 && state.separatorTop >= state.infoBottom, 'Section separator follows conversation information');
    assert.ok(state.headingTop > state.separatorTop + state.border, 'Learning tools heading sits below the separator');
    near(state.firstLeft, state.secondLeft, 'Section headings share the same left alignment');
    assert.ok(state.lines.length >= 2, 'New conversation produces real information lines');
    for (const center of state.lines) near(center, state.center, 'Conversation information lines are centered');
  }
  for (const id of ['wrongBookBtn','conceptNotebookBtn','knowledgeGraphBtn','graphDrawingBtn','learningReviewBtn']) {
    assert.equal(await page.locator('#'+id).isVisible(),true,id+': learning action remains visible');
    assert.equal(await page.locator('#'+id).isEnabled(),true,id+': learning action remains usable');
  }
}

async function checkStationaryBackground(page) {
  await page.evaluate(() => {
    getCurrent().messages.push({role:'ai',text:'背景聊天文字和位置保持不变。\n\n'.repeat(60)});
    renderChat();
  });
  const settle = () => page.evaluate(async () => {
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  const snapshot = () => page.evaluate(() => {
    const result = {};
    for (const selector of ['.center','.center > .input-wrap','.msg.ai .msg-content','#appearanceBackgroundLayer','.appearance-mask-layer']) {
      const node = document.querySelector(selector), rect = node.getBoundingClientRect(), css = getComputedStyle(node);
      result[selector] = { x:rect.x,y:rect.y,width:rect.width,height:rect.height,backgroundPosition:css.backgroundPosition };
    }
    result.scrollTop = document.getElementById('chat').scrollTop;
    return result;
  });
  const unchanged = async (before, label) => {
    const after = await snapshot();
    near(after.scrollTop, before.scrollTop, label + ': chat scroll is preserved', .5);
    for (const selector of Object.keys(before).filter(key => key !== 'scrollTop')) {
      for (const key of ['x','y','width','height']) near(after[selector][key], before[selector][key], label + '/' + selector + '/' + key, .5);
      assert.equal(after[selector].backgroundPosition, before[selector].backgroundPosition, label + ': wallpaper position is preserved');
    }
  };
  await settle();
  for (const wallpaper of [false,true]) {
    if (wallpaper) await page.evaluate(async () => {
      const canvas = document.createElement('canvas');canvas.width=canvas.height=16;
      const ctx=canvas.getContext('2d');ctx.fillStyle='#587483';ctx.fillRect(0,0,16,16);
      setAppearanceBackgroundVisual(await new Promise(resolve => canvas.toBlob(resolve)));
    });
    await page.locator('#chat').evaluate(chat => {chat.scrollTop=(chat.scrollHeight-chat.clientHeight)/3;});
    await settle();
    const before = await snapshot();
    for (const kind of ['left','tools']) {
      await openDrawer(page,kind);
      await settle();
      await unchanged(before,kind + '/open/' + wallpaper);
      await closeDrawer(page,kind);
      await settle();
      await unchanged(before,kind + '/close/' + wallpaper);
      let previousLeft;
      for (const progress of [.25,.75]) {
        const left = await page.evaluate(({kind,progress}) => {
          paintMobileDrawerDragProgress(kind,progress);
          return document.querySelector(kind === 'left' ? '.left' : '.right').getBoundingClientRect().left;
        },{kind,progress});
        await unchanged(before,kind + '/drag/' + progress);
        if (previousLeft !== undefined) assert.ok(Math.abs(left-previousLeft)>20, 'The drawer itself still follows the gesture');
        previousLeft=left;
      }
      await page.evaluate(kind => settleMobileDrawerGesture(kind,false),kind);
      await settle();
      await unchanged(before,kind + '/cancel/' + wallpaper);
    }
  }
}

async function checkDesktopInfo(browser,theme) {
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.evaluate(theme => {
      appearanceSettings.mode=theme;applyAppearanceSettings({save:false});newChat();
      getCurrent().messages.push({role:'user',text:'核对有实际消息时的对话信息。'});renderInfo();
    },theme);
    await page.locator('#desktopToolsBtn').click();
    await page.waitForFunction(() => !document.getElementById('conversationInfoSection').hasAttribute('data-info-animating'));
    const lines=await page.locator('#info').evaluate(info => {
      const box=info.getBoundingClientRect();
      return [...info.querySelectorAll('.conversation-info-line')].map(line=>{
        const range=document.createRange();range.selectNodeContents(line);const text=range.getBoundingClientRect();
        return {textCenter:text.left+text.width/2,center:box.left+box.width/2};
      });
    });
    assert.ok(lines.length>=2,'Desktop conversation information is populated');
    for(const line of lines)near(line.textCenter,line.center,'Desktop information is centered');
    console.log('PASS desktop/'+theme+': centered conversation information');
  } finally {await page.close();}
}

async function runCase(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, isMobile: true, hasTouch: true });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(value => {
      appearanceSettings.mode = value;
      applyAppearanceSettings({save:false});
    }, theme);
    await page.waitForFunction(() => document.getElementById('conversationInfoSection')?.hidden);
    await openDrawer(page, 'tools');
    await checkHeader(page, '#learningToolsPanel');
    await checkTools(page, true);
    await closeDrawer(page, 'tools');
    await openDrawer(page, 'left');
    await checkHeader(page, '#conversationSidebar');
    const button = page.locator('#newChatBtn');
    const label = await button.evaluate(node => {
      const icon = node.querySelector('svg'), text = node.querySelector('.dmate-ui-label');
      const bounds = node.getBoundingClientRect(), style = getComputedStyle(node);
      return { icon: icon.dataset.icon, text: text.textContent,
        inset: icon.getBoundingClientRect().left - bounds.left,
        padding: parseFloat(style.paddingLeft) + parseFloat(style.borderLeftWidth) };
    });
    assert.equal(label.text, '新对话');
    assert.equal(label.icon, 'square-pen');
    near(label.inset, label.padding, 'New conversation icon and label start at the left inset');
    const oldCount = await page.locator('#sessions .session').count();
    await button.tap();
    await page.waitForFunction(count => document.querySelectorAll('#sessions .session').length === count + 1, oldCount);
    await page.waitForFunction(() => !document.body.classList.contains('mobile-left-open'));
    await openDrawer(page, 'tools');
    await checkTools(page, true);
    await page.evaluate(() => {
      getCurrent().messages.push({role:'user',text:'这条消息让当前对话的信息可供显示。'});renderInfo();
    });
    await checkTools(page, false);
    if (process.env.MOBILE_DRAWER_SCREENSHOT_DIR) {
      await page.screenshot({ path: process.env.MOBILE_DRAWER_SCREENSHOT_DIR + '/' + width + '-' + theme + '-tools.png' });
    }
    await closeDrawer(page, 'tools');
    await openDrawer(page, 'left');
    assert.equal(await page.locator('#sessions .session.active').count(), 1);
    if (process.env.MOBILE_DRAWER_SCREENSHOT_DIR) {
      await page.screenshot({ path: process.env.MOBILE_DRAWER_SCREENSHOT_DIR + '/' + width + '-' + theme + '-left.png' });
    }
    await closeDrawer(page, 'left');
    await checkStationaryBackground(page);
    assert.deepEqual(errors, [], 'No drawer script errors');
    console.log('PASS ' + width + '/' + theme + ': centered info, drawer controls and stationary transcript/wallpaper through opening and dragging');
  } catch (error) {
    if (process.env.MOBILE_DRAWER_SCREENSHOT_DIR) {
      await page.screenshot({ path: process.env.MOBILE_DRAWER_SCREENSHOT_DIR + '/FAILED-' + width + '-' + theme + '.png' }).catch(() => {});
    }
    throw error;
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 620, 820]) for (const theme of ['dark', 'navy']) await runCase(browser, width, theme);
    for (const theme of ['dark','navy']) await checkDesktopInfo(browser,theme);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
