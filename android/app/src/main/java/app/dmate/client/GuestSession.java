package app.dmate.client;

import java.util.UUID;
import java.util.HashSet;
import java.util.Set;

/** Identifies one app window lifetime, never an account or a device. */
final class GuestSession {
    private static final String PROCESS = UUID.randomUUID().toString();
    private static final Set<String> LIVE = new HashSet<>();

    private GuestSession() {}

    static String processToken() {
        return PROCESS;
    }

    static synchronized String start(String savedProcess, String savedSession) {
        // Activity recreation within this process keeps its guest workspace.
        // An OS process restore or a fresh launch starts an empty workspace.
        if (PROCESS.equals(savedProcess) && valid(savedSession) && LIVE.contains(savedSession)) return savedSession;
        String token = UUID.randomUUID().toString();
        LIVE.add(token);
        return token;
    }

    static synchronized void end(String token) {
        LIVE.remove(token);
    }

    private static boolean valid(String token) {
        return token != null && token.matches("[A-Za-z0-9-]{16,80}");
    }

    static String script(String token) {
        if (!valid(token)) throw new IllegalArgumentException("Invalid guest session token");
        return "(()=>{const page=new URL(location.href);"
            + "if(window!==window.top||page.origin!=='https://dmate.zeabur.app'||page.username||page.password)return;"
            + "window.__DMATE_NATIVE_GUEST_SESSION__='" + token + "';})();";
    }
}
