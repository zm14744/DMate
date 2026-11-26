/* Account preferences stay private until authentication; first paint is dark. */
(function () {
    var root = document.documentElement;
    root.dataset.appearanceTheme = "dark";
    root.style.colorScheme = "dark";
    document.querySelector('meta[name="color-scheme"]').content = "dark";
    document.querySelector('meta[name="supported-color-schemes"]').content = "dark";
    document.querySelector('meta[name="theme-color"]').content = "#171717";
})();
