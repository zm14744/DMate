package app.dmate.client;

import android.app.Activity;
import android.webkit.WebView;
import androidx.webkit.JavaScriptReplyProxy;
import androidx.webkit.WebMessageCompat;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import java.util.Collections;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.json.JSONObject;

/** Origin-bound asynchronous transport; there is no addJavascriptInterface. */
final class OfflineVaultBridge {
    private static final String NAME = "DMateOfflineVaultAndroid";
    private final Activity activity;
    private final WebView webView;
    private final OfflineVault vault = new OfflineVault(new OfflineVaultKeystore());
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
        new ArrayBlockingQueue<>(8));
    private final AtomicLong document = new AtomicLong();
    private volatile boolean closed;
    // Read and changed only on the UI thread. Together with the bounded queue,
    // this prevents a burst of large requests retaining many plaintext copies.
    private long pendingChars;

    private OfflineVaultBridge(Activity activity, WebView webView) {
        this.activity = activity;
        this.webView = webView;
        WebViewCompat.addWebMessageListener(webView, NAME,
            Collections.singleton("https://dmate.zeabur.app"),
            (view, message, sourceOrigin, isMainFrame, reply) -> {
                if (!isMainFrame || view != webView || !current(document.get())
                    || !OfflineVaultProtocol.trustedOrigin(sourceOrigin == null ? null : sourceOrigin.toString())
                    || message.getType() != WebMessageCompat.TYPE_STRING) return;
                receive(message.getData(), reply);
            });
    }

    static OfflineVaultBridge install(Activity activity, WebView webView) {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return null;
        return new OfflineVaultBridge(activity, webView);
    }

    void navigated() { document.incrementAndGet(); }

    void close() {
        closed = true;
        navigated();
        worker.shutdownNow();
        WebViewCompat.removeWebMessageListener(webView, NAME);
    }

    private boolean current(long generation) {
        return !closed && generation == document.get() && !activity.isFinishing() && !activity.isDestroyed()
            && OfflineVaultProtocol.trustedPage(webView.getUrl());
    }

    private void receive(String raw, JavaScriptReplyProxy reply) {
        final long generation = document.get();
        if (raw == null || raw.length() > OfflineVault.MAX_MESSAGE_CHARS) {
            send(reply, generation, failure(OfflineVaultProtocol.leadingId(raw), OfflineVault.invalid()));
            return;
        }
        if (pendingChars + raw.length() > OfflineVault.MAX_MESSAGE_CHARS) {
            send(reply, generation, failure(OfflineVaultProtocol.leadingId(raw), busy()));
            return;
        }
        pendingChars += raw.length();
        final int requestChars = raw.length();
        try {
            worker.execute(() -> {
                String id = "";
                String response;
                try {
                    if (closed || document.get() != generation) return;
                    Map<String, Object> request = OfflineVaultProtocol.parse(raw);
                    id = OfflineVault.requestId(request);
                    Map<String, Object> result = vault.execute(request);
                    response = new JSONObject(OfflineVault.result("id", id, "ok", true, "result", result)).toString();
                } catch (OfflineVault.Failure error) {
                    response = failure(id.isEmpty() ? OfflineVaultProtocol.leadingId(raw) : id, error);
                } catch (Exception error) {
                    // Never expose exception messages, aliases or submitted data.
                    response = failure(id, OfflineVault.unavailable());
                } finally {
                    activity.runOnUiThread(() -> pendingChars -= requestChars);
                }
                final String completed = response;
                activity.runOnUiThread(() -> send(reply, generation, completed));
            });
        } catch (RejectedExecutionException error) {
            pendingChars -= requestChars;
            send(reply, generation, failure(OfflineVaultProtocol.leadingId(raw), busy()));
        }
    }

    private static OfflineVault.Failure busy() {
        return new OfflineVault.Failure("BUSY", "The offline vault is busy; retry after pending operations finish.");
    }

    private static String failure(String id, OfflineVault.Failure error) {
        return new JSONObject(OfflineVault.result("id", id, "ok", false,
            "error", OfflineVault.result("code", error.code, "message", error.getMessage()))).toString();
    }

    private void send(JavaScriptReplyProxy reply, long generation, String response) {
        // Replies belong to the originating JS object. The document generation
        // also prevents a same-origin navigation receiving an old plaintext.
        if (!current(generation)) return;
        try { reply.postMessage(response); }
        catch (IllegalStateException ignored) { /* The original renderer was disposed. */ }
    }
}
