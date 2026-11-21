package app.dmate.client;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.Reader;
import java.net.URI;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Routing policy for public, build-time offline resources, never online records. */
final class OfflineBundle {
    static final String ORIGIN = "https://dmate.zeabur.app";
    static final String OFFLINE_URL = ORIGIN + "/offline?native_offline=1";
    private final Set<String> paths;

    OfflineBundle(Set<String> paths) {
        HashSet<String> checked = new HashSet<>();
        for (String path : paths) {
            if (!validAssetPath(path)) throw new IllegalArgumentException("Invalid bundled offline path");
            checked.add(path);
        }
        if (!checked.contains("/offline")) throw new IllegalArgumentException("Missing bundled offline page");
        this.paths = Collections.unmodifiableSet(checked);
    }

    static OfflineBundle read(Reader reader) throws IOException {
        HashSet<String> paths = new HashSet<>();
        BufferedReader lines = new BufferedReader(reader);
        for (String line; (line = lines.readLine()) != null;) {
            if (!line.trim().isEmpty()) paths.add(line.trim());
        }
        return new OfflineBundle(paths);
    }

    private static URI trusted(String value) {
        try {
            URI uri = new URI(value);
            String path = uri.getRawPath();
            if (!"https".equalsIgnoreCase(uri.getScheme())
                || !"dmate.zeabur.app".equalsIgnoreCase(uri.getHost())
                || uri.getRawUserInfo() != null || uri.getPort() != -1 && uri.getPort() != 443
                || path == null || path.indexOf('%') >= 0 || path.indexOf('\\') >= 0
                || path.contains("//") || !uri.normalize().getRawPath().equals(path)) return null;
            return uri;
        } catch (Exception ignored) { return null; }
    }

    private static boolean validAssetPath(String path) {
        if (path == null || path.indexOf('?') >= 0 || path.indexOf('#') >= 0) return false;
        URI uri = trusted(ORIGIN + path);
        return uri != null && ("/offline".equals(path) || path.startsWith("/static/"));
    }

    static boolean isTrustedPage(String url) { return trusted(url) != null; }

    static boolean isOfflinePage(String url) {
        URI uri = trusted(url);
        return uri != null && ("/offline".equals(uri.getRawPath()) || "/static/offline.html".equals(uri.getRawPath()));
    }

    static String initialUrl(boolean validatedNetwork) {
        return validatedNetwork ? ORIGIN + "/" : OFFLINE_URL;
    }

    static boolean shouldSwitchOffline(String currentUrl, boolean validatedNetwork) {
        return !validatedNetwork && isTrustedPage(currentUrl) && !isOfflinePage(currentUrl);
    }

    static boolean isConnectionError(int code) {
        // Android WebViewClient network failures; SSL/auth/unsafe-resource errors
        // are deliberately excluded rather than bypassing their protection.
        return code == -1 || code == -2 || code == -6 || code == -7 || code == -8;
    }

    String assetPath(String url, String method, boolean enabled) {
        if (!enabled || !"GET".equals(method)) return null;
        URI uri = trusted(url);
        if (uri == null || !paths.contains(uri.getRawPath())) return null;
        return isOfflinePage(url) ? "offline.html" : uri.getRawPath().substring(1);
    }

    static String contentType(String asset) {
        String name = asset.toLowerCase(Locale.ROOT);
        if (name.endsWith(".html")) return "text/html";
        if (name.endsWith(".js")) return "application/javascript";
        if (name.endsWith(".css")) return "text/css";
        if (name.endsWith(".json")) return "application/json";
        if (name.endsWith(".svg")) return "image/svg+xml";
        if (name.endsWith(".png")) return "image/png";
        if (name.endsWith(".ico")) return "image/x-icon";
        if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "image/jpeg";
        if (name.endsWith(".gif")) return "image/gif";
        if (name.endsWith(".woff")) return "font/woff";
        if (name.endsWith(".woff2")) return "font/woff2";
        if (name.endsWith(".ttf")) return "font/ttf";
        if (name.endsWith(".wasm")) return "application/wasm";
        return "application/octet-stream";
    }

    static String markerScript() {
        return "(()=>{const p=new URL(location.href);"
            + "if(window!==window.top||p.origin!=='" + ORIGIN + "'||p.username||p.password)return;"
            + "Object.defineProperty(window,'__DMATE_NATIVE_OFFLINE_AVAILABLE__',{value:true,configurable:false});})();";
    }

    static String networkStatusScript(boolean online) {
        // The page can change after Java schedules the script. Check the exact
        // offline document again before publishing the host's connectivity.
        return "(()=>{const p=new URL(location.href);"
            + "if(window!==window.top||p.origin!=='" + ORIGIN + "'||p.username||p.password"
            + "||(p.pathname!=='/offline'&&p.pathname!=='/static/offline.html'))return;"
            + "const online=" + online + ";"
            + "if(window.__DMATE_NATIVE_NETWORK_ONLINE__===online)return;"
            + "window.__DMATE_NATIVE_NETWORK_ONLINE__=online;"
            + "window.dispatchEvent(new CustomEvent('dmate:native-network-change',{detail:{online}}));})();";
    }
}
