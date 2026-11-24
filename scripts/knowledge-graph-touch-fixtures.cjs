'use strict';

async function touchGraph(page, points) {
  const view = page.locator('#knowledgeGraphCanvas .kg-mobile-viewport');
  await view.waitFor();
  const area = await view.evaluate(node => {
    const rect = node.getBoundingClientRect(), modal = node.closest('#knowledgeGraphModal');
    const sheet = modal.dataset.kgSheet && modal.querySelector('.knowledge-graph-side');
    const left = Math.max(0, rect.left), right = Math.min(innerWidth, rect.right);
    const top = Math.max(0, rect.top), bottom = Math.min(innerHeight, rect.bottom, sheet ? sheet.getBoundingClientRect().top : Infinity);
    if (bottom - top < 12 || right - left < 24) throw new Error('No visible graph surface for a touch gesture');
    return {x:(left + right) / 2, y:(top + bottom) / 2, width:right - left};
  });
  const [start, end] = points(area);
  const cdp = await page.context().newCDPSession(page);
  const touch = (type, touchPoints) => cdp.send('Input.dispatchTouchEvent', {type, touchPoints});
  try {
    await touch('touchStart', start);
    await touch('touchMove', end);
    await page.evaluate(() => new Promise(requestAnimationFrame));
    await touch('touchEnd', []);
    await page.evaluate(() => new Promise(requestAnimationFrame));
  } finally { await cdp.detach(); }
}

async function pinchGraph(page, factor) {
  await touchGraph(page, ({x,y,width}) => {
    const span = Math.min(60, (width / 2 - 8) / Math.max(1, factor));
    const fingers = distance => [{id:1, x:x-distance, y}, {id:2, x:x+distance, y}];
    return [fingers(span), fingers(span * factor)];
  });
}

async function panGraph(page, dx, dy) {
  await touchGraph(page, ({x,y}) => [[{id:1,x,y}], [{id:1,x:x+dx,y:y+dy}]]);
}

async function expandGraphDetails(page) {
  if (page.viewportSize().width > 760) return;
  const modal = page.locator('#knowledgeGraphModal');
  if (!await modal.getAttribute('data-kg-sheet')) {
    await modal.locator('.kg-mobile-node.selected').click();
  }
  if (await modal.getAttribute('data-kg-sheet') === 'peek') await modal.locator('.kg-sheet-handle').click();
  await page.locator('#knowledgeGraphModal[data-kg-sheet="expanded"] #knowledgeGraphDetail').waitFor();
}

module.exports = {pinchGraph, panGraph, expandGraphDetails};
