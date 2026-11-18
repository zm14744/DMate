package app.dmate.client;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.LinkedHashMap;
import java.util.Map;

/** Strict flat-string JSON request parser and native bridge origin policy. */
final class OfflineVaultProtocol {
    private static final String HOST = "dmate.zeabur.app";

    static boolean trustedOrigin(String value) {
        try {
            URI uri = new URI(value);
            return "https".equalsIgnoreCase(uri.getScheme()) && HOST.equalsIgnoreCase(uri.getHost())
                && uri.getRawUserInfo() == null && (uri.getPort() == -1 || uri.getPort() == 443);
        } catch (URISyntaxException | NullPointerException error) {
            return false;
        }
    }

    static boolean trustedPage(String value) {
        if (!trustedOrigin(value)) return false;
        try {
            String path = new URI(value).getRawPath();
            return "/offline".equals(path) || "/static/offline.html".equals(path);
        } catch (URISyntaxException error) {
            return false;
        }
    }

    static Map<String, Object> parse(String raw) throws OfflineVault.Failure {
        if (raw == null || raw.length() > OfflineVault.MAX_MESSAGE_CHARS) throw OfflineVault.invalid();
        Cursor cursor = new Cursor(raw);
        Map<String, Object> request = new LinkedHashMap<>();
        cursor.take('{');
        if (!cursor.next('}')) {
            do {
                String name = cursor.string(24);
                cursor.take(':');
                // Every protocol input is a string. Reject nested objects,
                // arrays, duplicates and non-string coercions without recursion.
                String value = cursor.string(OfflineVault.MAX_MESSAGE_CHARS);
                if (request.containsKey(name) || request.size() >= 7) throw OfflineVault.invalid();
                request.put(name, value);
            } while (cursor.next(','));
            cursor.take('}');
        }
        cursor.space();
        if (cursor.index != raw.length()) throw OfflineVault.invalid();
        return request;
    }

    // Overload responses must not parse/copy a whole multi-MiB payload on the
    // UI thread. The JS adapter emits its short request id as the first field.
    static String leadingId(String raw) {
        if (raw == null) return "";
        try {
            Cursor cursor = new Cursor(raw.substring(0, Math.min(raw.length(), 512)));
            cursor.take('{');
            if (!"id".equals(cursor.string(24))) return "";
            cursor.take(':');
            String id = cursor.string(80);
            return OfflineVault.requestId(OfflineVault.result("id", id));
        } catch (OfflineVault.Failure error) {
            return "";
        }
    }

    private static final class Cursor {
        final String raw;
        int index;
        Cursor(String raw) { this.raw = raw; }

        void space() {
            while (index < raw.length()) {
                char c = raw.charAt(index);
                if (c != ' ' && c != '\n' && c != '\r' && c != '\t') break;
                index++;
            }
        }

        boolean next(char value) {
            space();
            if (index < raw.length() && raw.charAt(index) == value) { index++; return true; }
            return false;
        }

        void take(char value) throws OfflineVault.Failure {
            if (!next(value)) throw OfflineVault.invalid();
        }

        String string(int maximum) throws OfflineVault.Failure {
            take('"');
            int start = index;
            StringBuilder escaped = null;
            while (index < raw.length()) {
                char c = raw.charAt(index++);
                if (c == '"') {
                    String value = escaped == null ? raw.substring(start, index - 1) : escaped.toString();
                    if (value.length() > maximum) throw OfflineVault.invalid();
                    return value;
                }
                if (c < 0x20) throw OfflineVault.invalid();
                if (c == '\\') {
                    if (escaped == null) escaped = new StringBuilder(raw.substring(start, index - 1));
                    if (index >= raw.length()) throw OfflineVault.invalid();
                    char escape = raw.charAt(index++);
                    switch (escape) {
                        case '"': case '\\': case '/': c = escape; break;
                        case 'b': c = '\b'; break;
                        case 'f': c = '\f'; break;
                        case 'n': c = '\n'; break;
                        case 'r': c = '\r'; break;
                        case 't': c = '\t'; break;
                        case 'u':
                            if (index + 4 > raw.length()) throw OfflineVault.invalid();
                            int code = 0;
                            for (int offset = 0; offset < 4; offset++) {
                                char hex = raw.charAt(index++);
                                int digit = hex >= '0' && hex <= '9' ? hex - '0'
                                    : hex >= 'a' && hex <= 'f' ? hex - 'a' + 10
                                    : hex >= 'A' && hex <= 'F' ? hex - 'A' + 10 : -1;
                                if (digit < 0) throw OfflineVault.invalid();
                                code = code * 16 + digit;
                            }
                            c = (char) code;
                            break;
                        default: throw OfflineVault.invalid();
                    }
                }
                if (escaped != null) escaped.append(c);
                int length = escaped == null ? index - start : escaped.length();
                if (length > maximum) throw OfflineVault.invalid();
            }
            throw OfflineVault.invalid();
        }
    }
}
