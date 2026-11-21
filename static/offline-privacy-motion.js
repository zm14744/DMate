/* Topology growth from ui/privacy-cover-responsive (44c3fd5). The original
   v52 logo grows once along its edges, then remains still. No preview controls. */
(() => {
  'use strict';
  const vertices = {
    A:[59,73], B:[103,48], C:[154,39], D:[205,84], E:[215,129],
    F:[201,188], G:[139,215], H:[94,217], I:[51,170], J:[41,126],
    K:[69,82], L:[127,66], M:[61,145], N:[162,116], O:[119,165],
    S:[140.5,140.5]
  };
  const pairs = ['AB','BC','CD','DE','EF','FG','GH','HI','IJ','JA',
    'AK','KL','LC','KM','MI','LN','NE','NS','SO','OM','OG'];
  const geometry = pairs.map(([a,b]) => {
    const [ax,ay] = vertices[a], [bx,by] = vertices[b];
    return {a,b,ax,ay,bx,by,length:Math.hypot(bx-ax,by-ay)};
  });
  const distances = Object.fromEntries(Object.keys(vertices).map(key => [key,Infinity]));
  distances.S = 0;
  const visited = new Set();
  while (visited.size < Object.keys(vertices).length) {
    const next = Object.keys(vertices).filter(key => !visited.has(key))
      .sort((a,b) => distances[a]-distances[b])[0];
    if (!next || !Number.isFinite(distances[next])) break;
    visited.add(next);
    for (const edge of geometry) {
      const neighbor = edge.a === next ? edge.b : edge.b === next ? edge.a : null;
      if (neighbor) distances[neighbor] = Math.min(distances[neighbor],distances[next]+edge.length);
    }
  }
  // Include meeting points within edges so the outer contour closes fully.
  const maxDistance = Math.max(...geometry.map(edge =>
    (distances[edge.a]+distances[edge.b]+edge.length)/2));
  const clamp = (value,min,max) => Math.min(max,Math.max(min,value));

  function create(cover) {
    const mark = cover.querySelector('.offline-privacy-mark');
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns,'svg');
    svg.setAttribute('class','offline-privacy-mark-growth');
    svg.setAttribute('viewBox','0 0 256 256');
    svg.setAttribute('aria-hidden','true');
    svg.setAttribute('focusable','false');
    const group = document.createElementNS(ns,'g');
    group.setAttribute('fill','none');
    group.setAttribute('stroke','var(--privacy-ink)');
    group.setAttribute('stroke-width','4.5');
    group.setAttribute('stroke-linecap','round');
    group.setAttribute('stroke-linejoin','round');
    svg.append(group);
    const edges = geometry.map(edge => {
      const forward = document.createElementNS(ns,'line');
      const backward = document.createElementNS(ns,'line');
      for (const [line,ax,ay,bx,by] of [
        [forward,edge.ax,edge.ay,edge.bx,edge.by],
        [backward,edge.bx,edge.by,edge.ax,edge.ay]
      ]) {
        line.setAttribute('x1',ax); line.setAttribute('y1',ay);
        line.setAttribute('x2',bx); line.setAttribute('y2',by);
        group.append(line);
      }
      return {...edge,forward,backward};
    });
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let raf = 0, resolvePlayback = null;
    function showPart(line,visible,length) {
      if (visible < 0.15) { line.style.display = 'none'; return; }
      line.style.display = '';
      line.setAttribute('stroke-dasharray',`${Math.min(visible,length)} ${length*2}`);
    }
    function render(radius) {
      for (const edge of edges) {
        const fromA = clamp(radius-distances[edge.a],0,edge.length);
        const fromB = clamp(radius-distances[edge.b],0,edge.length);
        if (fromA+fromB >= edge.length-0.01) {
          showPart(edge.forward,edge.length,edge.length);
          edge.backward.style.display = 'none';
        } else {
          showPart(edge.forward,fromA,edge.length);
          showPart(edge.backward,fromB,edge.length);
        }
      }
    }
    function finish() {
      cancelAnimationFrame(raf);
      raf = 0;
      render(maxDistance+1);
      const resolve = resolvePlayback;
      resolvePlayback = null;
      resolve?.();
    }
    function play() {
      finish();
      const completed = new Promise(resolve => { resolvePlayback = resolve; });
      if (!cover.open || document.hidden || reducedMotion.matches) { finish(); return completed; }
      render(0);
      let start = null;
      function tick(now) {
        raf = 0;
        if (!cover.open || document.hidden || reducedMotion.matches) { finish(); return; }
        if (start === null) start = now;
        const progress = clamp((now-start)/740,0,1);
        if (progress === 1) { finish(); return; }
        render(maxDistance*(1-Math.pow(1-progress,1.65)));
        raf = requestAnimationFrame(tick);
      }
      raf = requestAnimationFrame(tick);
      return completed;
    }
    finish();
    mark.append(svg);
    // Keep the original theme-aware images as a fallback until setup succeeds.
    mark.classList.add('offline-privacy-topology-ready');
    document.addEventListener('visibilitychange',() => { if (document.hidden) finish(); });
    window.addEventListener('pagehide',finish);
    reducedMotion.addEventListener('change',() => { if (reducedMotion.matches) finish(); });
    return Object.freeze({play,finish});
  }
  window.DMateOfflinePrivacyMotion = Object.freeze({create});
})();
