/* Account preferences are applied only after authentication. Until then the
   first frame follows the OS without trusting a previous account's storage. */
(function () {
    var theme = "light";
    try {
        var nativeTheme = window.__DMATE_NATIVE_SYSTEM_THEME__;
        if (nativeTheme === "dark" || nativeTheme === "light") {
            theme = nativeTheme;
        } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
            theme = "dark";
        }
    } catch (_) {}
    var root = document.documentElement;
    var scheme = theme === "light" ? "only light" : "dark";
    root.dataset.appearanceTheme = theme;
    root.style.colorScheme = scheme;
    document.querySelector('meta[name="color-scheme"]').content = scheme;
    document.querySelector('meta[name="supported-color-schemes"]').content = theme;
    document.querySelector('meta[name="theme-color"]').content = theme === "light" ? "#f8fafc" : "#171717";
})();
