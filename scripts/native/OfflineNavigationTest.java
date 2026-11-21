package app.dmate.client;

import java.io.StringReader;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** Executes production routing policy on a JDK; it is not a WebView test. */
public final class OfflineNavigationTest {
    private static int checks;
    private static final String HOME = "https://dmate.zeabur.app";

    private static void equal(Object actual, Object expected, String message) {
        checks++;
        if (!java.util.Objects.equals(actual, expected)) {
            throw new AssertionError(message + ": " + actual + " != " + expected);
        }
    }

    private static void invalidManifest(String... paths) {
        checks++;
        try {
            new OfflineBundle(new HashSet<>(Arrays.asList(paths)));
            throw new AssertionError("Invalid bundle manifest was accepted: " + Arrays.toString(paths));
        } catch (IllegalArgumentException expected) {}
    }

    private static void routing() throws Exception {
        OfflineBundle bundle = OfflineBundle.read(new StringReader(
            "\n/offline\n/static/offline.html\n/static/offline.js\n/static/offline.css\n"
            + "/static/offline-content/questions.zh-CN.json\n/static/vendor/font.woff2\n\n"));
        equal(bundle.assetPath(HOME + "/offline?native_offline=1", "GET", true), "offline.html",
            "A cold native launch serves the packaged document at the vault's canonical path");
        equal(bundle.assetPath(HOME + "/static/offline.html?v=2", "GET", true), "offline.html", "Document alias");
        equal(bundle.assetPath(HOME + "/static/offline.js?v=10#latest", "GET", true), "static/offline.js", "Queries do not create a second asset namespace");
        equal(bundle.assetPath(HOME + ":443/static/offline.css", "GET", true), "static/offline.css", "Default HTTPS port");
        equal(bundle.assetPath(HOME + "/static/offline-content/questions.zh-CN.json?v=34", "GET", true),
            "static/offline-content/questions.zh-CN.json", "Offline content pack");
        equal(bundle.assetPath(HOME + "/static/vendor/font.woff2", "GET", true), "static/vendor/font.woff2", "Bundled font");
        for (String url : new String[] {
            HOME + "/", HOME + "/auth/me", HOME + "/sync", HOME + "/chat", HOME + "/offline-service-worker.js",
            HOME + "/static/script.js", HOME + "/static/missing.js", HOME + "/offline/", HOME + "/static/offline.js/extra",
            "https://dmate.zeabur.app.evil.test/static/offline.js", "https://evil.test/static/offline.js",
            "http://dmate.zeabur.app/static/offline.js", "file:///static/offline.js",
            "https://user@dmate.zeabur.app/static/offline.js", "https://dmate.zeabur.app:444/static/offline.js",
            HOME + "/static/../static/offline.js", HOME + "/static/./offline.js", HOME + "//static/offline.js",
            HOME + "/static/%6fffline.js", HOME + "/static/%2e%2e/auth/me", HOME + "/static/offline.js%2f..%2fscript.js",
            HOME + "/static\\offline.js", "javascript:alert(1)", "", null
        }) equal(bundle.assetPath(url, "GET", true), null, "Only exact public allowlisted resources are intercepted: " + url);
        for (String method : new String[] {"POST", "PUT", "PATCH", "DELETE", "HEAD", "get", null}) {
            equal(bundle.assetPath(HOME + "/static/offline.js", method, true), null, "Non-GET requests are never served from the package");
        }
        equal(bundle.assetPath(HOME + "/offline", "GET", false), null, "Online mode does not intercept page loads");
        equal(bundle.assetPath(HOME + "/static/offline.js", "GET", false), null, "Online assets stay on their normal path");
        invalidManifest();
        invalidManifest("/static/offline.js");
        for (String invalid : new String[] {"/", "/auth/me", "/sync", "/anything.js", "/static/../auth/me",
            "/static//offline.js", "/static/%6fffline.js", "/static/offline.js?version=1", "/static/offline.js#fragment",
            "https://evil.test/static/offline.js", null}) invalidManifest("/offline", invalid);
    }

    private static void lifecycle() {
        equal(OfflineBundle.initialUrl(false), OfflineBundle.OFFLINE_URL, "No validated connection starts locally without depending on web cache");
        equal(OfflineBundle.initialUrl(true), HOME + "/", "Validated connection starts online");
        equal(OfflineBundle.isOfflinePage(OfflineBundle.OFFLINE_URL), true, "Native URL is recognized as offline");
        equal(OfflineVaultProtocol.trustedPage(OfflineBundle.OFFLINE_URL), true, "Canonical native fallback retains OS-vault authorization");
        equal(OfflineBundle.shouldSwitchOffline(HOME + "/", false), true, "A loaded online page switches when the validated connection disappears");
        equal(OfflineBundle.shouldSwitchOffline(HOME + "/?conversation=two", false), true, "Online query does not prevent fallback");
        equal(OfflineBundle.shouldSwitchOffline(HOME + "/", true), false, "A working connection leaves online work alone");
        equal(OfflineBundle.shouldSwitchOffline(OfflineBundle.OFFLINE_URL, false), false, "Repeated loss while offline is idempotent");
        equal(OfflineBundle.shouldSwitchOffline(HOME + "/static/offline.html", false), false, "Offline document alias is idempotent");
        equal(OfflineBundle.shouldSwitchOffline(OfflineBundle.OFFLINE_URL, true), false, "Network recovery alone does not leave the offline workspace");
        for (String url : new String[] {"https://outside.test/", "http://dmate.zeabur.app/", "about:blank", "file:///offline", null}) {
            equal(OfflineBundle.shouldSwitchOffline(url, false), false, "Connectivity changes never redirect an untrusted page");
        }
        for (String url : new String[] {HOME + "/offline/", HOME + "/off%6cine", HOME + "/static/../offline"}) {
            equal(OfflineBundle.isOfflinePage(url), false, "Only canonical offline routes carry vault privileges");
        }
        for (int code : new int[] {-1, -2, -6, -7, -8}) {
            equal(OfflineBundle.isConnectionError(code), true, "Connection failures permit bundled fallback: " + code);
        }
        for (int code : new int[] {-3, -4, -5, -9, -10, -11, -12, -13, -14, -15, -16, 0, 200, 401, 403, 500}) {
            equal(OfflineBundle.isConnectionError(code), false,
                "Authentication, TLS, unsafe content and other failures must not be bypassed: " + code);
        }
        equal(OfflineBundle.contentType("offline.html"), "text/html", "Document MIME");
        equal(OfflineBundle.contentType("static/offline.js"), "application/javascript", "Script MIME");
        equal(OfflineBundle.contentType("static/offline.css"), "text/css", "Stylesheet MIME");
        equal(OfflineBundle.contentType("static/questions.json"), "application/json", "Content MIME");
        equal(OfflineBundle.contentType("static/logo.svg"), "image/svg+xml", "Vector MIME");
        equal(OfflineBundle.contentType("static/font.woff2"), "font/woff2", "Font MIME");
        equal(OfflineBundle.contentType("static/unknown.bin"), "application/octet-stream", "Unknown resource MIME");
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("marker")) {
            System.out.print(OfflineBundle.markerScript());
            return;
        }
        routing();
        lifecycle();
        System.out.println("PASS Android bundled offline policy: " + checks + " routing, lifecycle, allowlist and vault-origin assertions");
    }
}
