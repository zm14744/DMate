package app.dmate.client;

import android.annotation.TargetApi;
import android.Manifest;
import android.app.Activity;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.pm.PackageManager;
import android.os.Environment;
import android.provider.MediaStore;
import android.media.MediaScannerConnection;
import android.util.Base64;
import androidx.webkit.WebMessageCompat;
import androidx.webkit.JavaScriptReplyProxy;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.io.IOException;
import java.util.Collections;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.SafeBrowsingResponse;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.net.http.SslError;
import android.widget.Toast;

public final class MainActivity extends Activity {
    private static final int FILE_CHOOSER_REQUEST = 1001;
    private static final int LEGACY_SAVE_PERMISSION_REQUEST = 1002;
    private static final int MAX_PNG_BYTES = 20 * 1024 * 1024;
    private static final byte[] PNG_MAGIC = {(byte)0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
    private static final String HOME_URL = BuildConfig.DMATE_URL;
    private static final String HOME_HOST = "dmate.zeabur.app";

    private WebView webView;
    private ValueCallback<Uri[]> pendingFileCallback;
    private final ExecutorService imageSaver = Executors.newSingleThreadExecutor();
    private PendingSave pendingLegacySave;

    private static final class PendingSave {
        final String id;
        final String filename;
        final byte[] png;
        final JavaScriptReplyProxy reply;
        PendingSave(String id, String filename, byte[] png, JavaScriptReplyProxy reply) {
            this.id = id;
            this.filename = filename;
            this.png = png;
            this.reply = reply;
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webview);
        configureWebView();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                this::handleBack
            );
        }

        if (savedInstanceState == null) {
            webView.loadUrl(HOME_URL);
        } else {
            webView.restoreState(savedInstanceState);
        }
    }

    private void configureWebView() {
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        final WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setGeolocationEnabled(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSafeBrowsingEnabled(true);

        String ua = settings.getUserAgentString();
        if (ua == null) ua = "";
        if (!ua.contains(BuildConfig.DMATE_USER_AGENT)) {
            settings.setUserAgentString((ua + " " + BuildConfig.DMATE_USER_AGENT).trim());
        }

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, false);

        installGallerySaveBridge();
        webView.setWebViewClient(new DmateWebViewClient());
        webView.setWebChromeClient(new DmateChromeClient());
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            openExternal(Uri.parse(url));
        });
    }

    /** Only the HTTPS DMate main frame may request saving a PNG to Photos. */
    private void installGallerySaveBridge() {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return;
        WebViewCompat.addWebMessageListener(
            webView,
            "DMateGallery",
            Collections.singleton("https://" + HOME_HOST),
            (view, message, sourceOrigin, isMainFrame, replyProxy) -> {
                if (!isMainFrame || view != webView ||
                    !"https".equalsIgnoreCase(sourceOrigin.getScheme()) ||
                    !HOME_HOST.equalsIgnoreCase(sourceOrigin.getHost()) ||
                    message.getType() != WebMessageCompat.TYPE_STRING ||
                    !isTrustedPage()) {
                    return;
                }
                String raw = message.getData();
                if (raw == null || raw.length() > MAX_PNG_BYTES * 4 / 3 + 4096) {
                    sendGalleryReply(replyProxy, "", false, "图片过大，无法保存");
                    return;
                }
                try {
                    JSONObject request = new JSONObject(raw);
                    String id = request.optString("id", "");
                    String filename = request.optString("filename", "DMate-图片.png");
                    String base64 = request.optString("base64", "");
                    if (id.length() < 1 || id.length() > 128 || base64.isEmpty() ||
                        base64.length() > MAX_PNG_BYTES * 4 / 3 + 1024) {
                        sendGalleryReply(replyProxy, id, false, "图片数据不正确");
                        return;
                    }
                    // Decode away from UI thread; never put 20 MiB PNG into Intent URLs.
                    imageSaver.execute(() -> {
                        try {
                            byte[] png = Base64.decode(base64, Base64.DEFAULT);
                            if (!isValidPng(png)) throw new IOException("图片不是有效 PNG 或文件过大");
                            PendingSave save = new PendingSave(id, sanitizeFilename(filename), png, replyProxy);
                            runOnUiThread(() -> beginGallerySave(save));
                        } catch (Exception error) {
                            runOnUiThread(() -> sendGalleryReply(replyProxy, id, false, "图片数据无效"));
                        }
                    });
                } catch (Exception error) {
                    sendGalleryReply(replyProxy, "", false, "无法解析图片保存请求");
                }
            }
        );
    }

    private boolean isTrustedPage() {
        if (webView == null || webView.getUrl() == null) return false;
        Uri page = Uri.parse(webView.getUrl());
        return "https".equalsIgnoreCase(page.getScheme()) &&
            HOME_HOST.equalsIgnoreCase(page.getHost());
    }

    private static boolean isValidPng(byte[] bytes) {
        if (bytes == null || bytes.length < PNG_MAGIC.length || bytes.length > MAX_PNG_BYTES) return false;
        for (int i = 0; i < PNG_MAGIC.length; i++) {
            if (bytes[i] != PNG_MAGIC[i]) return false;
        }
        return true;
    }

    private static String sanitizeFilename(String supplied) {
        String filename = (supplied == null ? "" : supplied)
            .replaceAll("[^a-zA-Z0-9\u4e00-\u9fa5._-]", "_");
        if (filename.length() > 90) filename = filename.substring(0, 90);
        if (!filename.toLowerCase(Locale.ROOT).endsWith(".png")) filename += ".png";
        return "DMate-" + System.currentTimeMillis() + "-" + filename;
    }

    private void beginGallerySave(PendingSave save) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q &&
            checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            if (pendingLegacySave != null) {
                sendGalleryReply(save.reply, save.id, false, "请完成前一次图片保存");
                return;
            }
            pendingLegacySave = save;
            requestPermissions(new String[] { Manifest.permission.WRITE_EXTERNAL_STORAGE }, LEGACY_SAVE_PERMISSION_REQUEST);
            return;
        }
        saveImageAsync(save);
    }

    private void saveImageAsync(PendingSave save) {
        imageSaver.execute(() -> {
            try {
                storePngInGallery(save.png, save.filename);
                runOnUiThread(() -> sendGalleryReply(save.reply, save.id, true, "图片已保存到相册 · DMate"));
            } catch (Exception error) {
                runOnUiThread(() -> sendGalleryReply(save.reply, save.id, false, "保存到相册失败，请检查可用空间"));
            }
        });
    }

    private void storePngInGallery(byte[] png, String filename) throws IOException {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentResolver resolver = getContentResolver();
            ContentValues values = new ContentValues();
            values.put(MediaStore.Images.Media.DISPLAY_NAME, filename);
            values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
            values.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/DMate");
            values.put(MediaStore.Images.Media.IS_PENDING, 1);
            Uri target = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
            if (target == null) throw new IOException("无法创建相册文件");
            boolean complete = false;
            try {
                try (OutputStream out = resolver.openOutputStream(target, "w")) {
                    if (out == null) throw new IOException("无法写入相册");
                    out.write(png);
                    out.flush();
                }
                values.clear();
                values.put(MediaStore.Images.Media.IS_PENDING, 0);
                if (resolver.update(target, values, null, null) <= 0) {
                    throw new IOException("相册未确认文件保存");
                }
                complete = true;
            } finally {
                if (!complete) resolver.delete(target, null, null);
            }
        } else {
            File directory = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "DMate");
            if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("无法创建图片文件夹");
            File file = new File(directory, filename);
            try (FileOutputStream out = new FileOutputStream(file)) {
                out.write(png);
                out.flush();
            }
            MediaScannerConnection.scanFile(this, new String[] {file.getAbsolutePath()}, new String[] {"image/png"}, null);
        }
    }

    private void sendGalleryReply(JavaScriptReplyProxy reply, String id, boolean ok, String message) {
        try {
            JSONObject response = new JSONObject();
            response.put("id", id);
            response.put("ok", ok);
            response.put("message", message);
            reply.postMessage(response.toString());
        } catch (Exception ignored) {
            // The page might have navigated during a long save; do not crash.
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != LEGACY_SAVE_PERMISSION_REQUEST) return;
        PendingSave save = pendingLegacySave;
        pendingLegacySave = null;
        if (save == null) return;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            saveImageAsync(save);
        } else {
            sendGalleryReply(save.reply, save.id, false, "没有存储权限，无法保存到相册");
        }
    }

    private final class DmateWebViewClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            return handleNavigation(request.getUrl());
        }

        @SuppressWarnings("deprecation")
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return handleNavigation(Uri.parse(url));
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            CookieManager.getInstance().flush();
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            // 不允许“继续访问”无效证书；避免中间人攻击。
            handler.cancel();
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            super.onReceivedError(view, request, error);
            if (request.isForMainFrame()) {
                showOfflinePage();
            }
        }

        @TargetApi(Build.VERSION_CODES.O_MR1)
        @Override
        public void onSafeBrowsingHit(
            WebView view,
            WebResourceRequest request,
            int threatType,
            SafeBrowsingResponse callback
        ) {
            // Android Safe Browsing 判定为恶意/钓鱼时绝不绕过系统保护。
            callback.backToSafety(true);
        }
    }

    private final class DmateChromeClient extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(
            WebView webView,
            ValueCallback<Uri[]> filePathCallback,
            FileChooserParams fileChooserParams
        ) {
            if (pendingFileCallback != null) {
                pendingFileCallback.onReceiveValue(null);
            }
            pendingFileCallback = filePathCallback;

            Intent intent;
            try {
                intent = fileChooserParams.createIntent();
            } catch (Exception ignored) {
                intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("image/*");
            }

            try {
                startActivityForResult(intent, FILE_CHOOSER_REQUEST);
                return true;
            } catch (ActivityNotFoundException error) {
                pendingFileCallback = null;
                Toast.makeText(MainActivity.this, "没有可用的文件选择器", Toast.LENGTH_SHORT).show();
                return false;
            }
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            // v1 不索取摄像头、麦克风、定位等 Web 权限；图片识题走系统文件选择器。
            request.deny();
        }

        @Override
        public void onGeolocationPermissionsShowPrompt(
            String origin,
            GeolocationPermissions.Callback callback
        ) {
            callback.invoke(origin, false, false);
        }
    }

    private boolean handleNavigation(Uri uri) {
        if (uri == null) return true;
        String scheme = uri.getScheme();
        String host = uri.getHost();

        if ("https".equalsIgnoreCase(scheme) && HOME_HOST.equalsIgnoreCase(host)) {
            return false;
        }

        openExternal(uri);
        return true;
    }

    private void openExternal(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException error) {
            Toast.makeText(this, "无法打开此链接", Toast.LENGTH_SHORT).show();
        }
    }

    private void showOfflinePage() {
        final String html = "<!doctype html><html><head><meta charset='utf-8'>"
            + "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            + "<style>body{margin:0;background:#111;color:#eee;font:16px sans-serif;display:grid;"
            + "place-items:center;min-height:100vh}.c{text-align:center;padding:28px}button{border:0;border-radius:12px;"
            + "padding:12px 18px;font-size:16px}</style></head><body><div class='c'><h2>DMate 暂时无法连接</h2>"
            + "<p>请检查网络后重试。</p><button onclick=\"location.href='" + HOME_URL + "'\">重新连接</button>"
            + "</div></body></html>";
        webView.loadDataWithBaseURL(HOME_URL, html, "text/html", "UTF-8", null);
    }

    private void handleBack() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            finish();
        }
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            handleBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != FILE_CHOOSER_REQUEST || pendingFileCallback == null) return;

        Uri[] result = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
        pendingFileCallback.onReceiveValue(result);
        pendingFileCallback = null;
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        if (webView != null) webView.saveState(outState);
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onPause() {
        if (webView != null) webView.onPause();
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override
    protected void onDestroy() {
        if (pendingFileCallback != null) {
            pendingFileCallback.onReceiveValue(null);
            pendingFileCallback = null;
        }
        imageSaver.shutdown();
        if (webView != null) {
            webView.stopLoading();
            webView.setWebChromeClient(null);
            webView.setWebViewClient(null);
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
