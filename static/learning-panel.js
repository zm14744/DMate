/* Animate the existing details in flow, including interrupted conversation changes. */
(() => {
    'use strict';
    const panel = document.getElementById('learningToolsPanel');
    const section = document.getElementById('conversationInfoSection');
    const content = document.getElementById('conversationInfoContent');
    if (!panel || !section || !content) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let animation = null, initialized = false, visible = false, targetHeight = 0;
    const height = node => Number.parseFloat(getComputedStyle(node).height) || 0;
    function finish() {
        const previous = animation;
        animation = null;
        section.style.height = visible ? '' : '0px';
        section.style.opacity = visible ? '' : '0';
        section.hidden = !visible;
        section.removeAttribute('data-info-animating');
        previous?.cancel();
    }
    function update(show,render) {
        // Read the painted position before changing content or cancelling a
        // previous animation; rapid switches continue from that same frame.
        const fromHeight = section.hidden ? 0 : height(section);
        const fromOpacity = section.hidden ? 0 : Number.parseFloat(getComputedStyle(section).opacity);
        const wasVisible = visible;
        render?.();
        visible = Boolean(show);
        section.inert = !visible;
        section.setAttribute('aria-hidden',String(!visible));
        panel.dataset.hasConversationInfo = String(visible);
        if (visible) section.hidden = false;
        const nextHeight = visible ? height(content) : 0;
        if (initialized && wasVisible === visible && Math.abs(nextHeight-targetHeight) < .25) {
            if (!animation) finish();
            return;
        }
        targetHeight = nextHeight;
        const animate = initialized && !reduced.matches && !document.hidden && typeof section.animate === 'function'
            && (Math.abs(fromHeight-nextHeight) > .25 || Math.abs(fromOpacity-(visible ? 1 : 0)) > .01);
        initialized = true;
        section.style.height = fromHeight+'px';
        section.style.opacity = String(fromOpacity);
        animation?.cancel(); animation = null;
        if (!animate) { finish(); return; }
        section.hidden = false;
        section.style.height = nextHeight+'px';
        section.style.opacity = visible ? '1' : '0';
        section.setAttribute('data-info-animating','');
        const current = section.animate([
            {height:fromHeight+'px',opacity:fromOpacity},
            {height:nextHeight+'px',opacity:visible ? 1 : 0}
        ],{duration:220,easing:'cubic-bezier(.2,.8,.2,1)',fill:'both'});
        animation = current;
        current.finished.then(() => { if (animation === current) finish(); }).catch(() => {});
    }
    if (window.ResizeObserver) new ResizeObserver(() => {
        if (initialized && visible && Math.abs(height(content)-targetHeight) > .25) update(true);
    }).observe(content);
    reduced.addEventListener('change',() => { if (reduced.matches) finish(); });
    document.addEventListener('visibilitychange',() => { if (document.hidden) finish(); });
    window.DMateLearningPanel = Object.freeze({update,finish});
})();
