(() => {
    const page = new URL(location.href);
    if (window !== window.top || page.origin !== 'https://dmate.zeabur.app' || page.username || page.password) return;
    window.__DMATE_NATIVE_GUEST_SESSION__ = '__DMATE_GUEST_SESSION_TOKEN__';
})();
