package app.dmate.client;

import android.annotation.TargetApi;
import android.Manifest;
import android.app.Activity;
import android.content.ContentResolver;
import android.content.ClipData;
import android.content.ContentValues;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.os.Environment;
import android.provider.MediaStore;
import android.media.MediaScannerConnection;
import android.os.SystemClock;
import android.util.Base64;
import androidx.webkit.WebMessageCompat;
import androidx.webkit.JavaScriptReplyProxy;
import androidx.webkit.ScriptHandler;
import androidx.webkit.WebSettingsCompat;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.io.IOException;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
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
    private static final int MICROPHONE_PERMISSION_REQUEST = 1003;
    private static final int MAX_PNG_BYTES = 20 * 1024 * 1024;
    private static final byte[] PNG_MAGIC = {(byte)0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
    private static final String HOME_URL = BuildConfig.DMATE_URL;
    private static final String HOME_HOST = "dmate.zeabur.app";
    private static final String LANGUAGE_PREFERENCES = "dmate_native_language";
    private static final String LANGUAGE_KEY = "ui_language";

    private WebView webView;
    private ScriptHandler systemThemeStartScript;
    private String documentStartSystemTheme;
    private ValueCallback<Uri[]> pendingFileCallback;
    private boolean filePickerTriedDocuments;
    private boolean filePickerMultiple;
    private long filePickerLaunchedAt;
    private final ExecutorService imageSaver = Executors.newSingleThreadExecutor();
    private PendingSave pendingLegacySave;
    private PermissionRequest pendingMicrophoneRequest;
    // Do not attach a new WebView request to an older Android permission dialog.
    private boolean microphonePermissionInFlight;

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
        // WebView derives prefers-color-scheme from the Activity's light/dark
        // theme, so choose it before constructing the WebView.
        setTheme(systemAppearanceTheme(getResources().getConfiguration()));
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

    private int systemAppearanceTheme(Configuration configuration) {
        return (configuration.uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
            ? R.style.Theme_DMate_Dark : R.style.Theme_DMate;
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        // uiMode is handled here instead of recreating the Activity. Change
        // the actual theme ID so the Activity context's isLightTheme updates.
        setTheme(systemAppearanceTheme(newConfig));
        super.onConfigurationChanged(newConfig);
        if (webView != null) {
            // Refresh media queries in the existing page without a reload,
            // preserving unsent text, image selections and guest state.
            webView.dispatchConfigurationChanged(newConfig);
            refreshSystemThemeBridge();
        }
    }

    private String currentSystemTheme() {
        return (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
            == Configuration.UI_MODE_NIGHT_YES ? "dark" : "light";
    }

    private String systemThemeScript(String theme) {
        // The additional runtime guard covers a navigation between the native
        // origin check and evaluateJavascript. No privileged JS interface is exposed.
        return "(function(){if(window.top!==window||location.origin!=='https://" + HOME_HOST + "')return;"
            + "var theme='" + theme + "';window.__DMATE_NATIVE_SYSTEM_THEME__=theme;"
            + "window.dispatchEvent(new CustomEvent('dmate:native-system-theme',"
            + "{detail:{theme:theme,source:'android'}}));})();";
    }

    private void refreshSystemThemeBridge() {
        if (webView == null || isFinishing() || isDestroyed()) return;
        String theme = currentSystemTheme();
        String script = systemThemeScript(theme);
        // The document-start snapshot must be replaced when the OS changes,
        // otherwise the next navigation could briefly restore the previous theme.
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)
            && !theme.equals(documentStartSystemTheme)) {
            if (systemThemeStartScript != null) systemThemeStartScript.remove();
            systemThemeStartScript = WebViewCompat.addDocumentStartJavaScript(
                webView, script, Collections.singleton("https://" + HOME_HOST));
            documentStartSystemTheme = theme;
        }
        String url = webView.getUrl();
        if (url != null) {
            Uri page = Uri.parse(url);
            if ("https".equalsIgnoreCase(page.getScheme())
                && HOME_HOST.equalsIgnoreCase(page.getHost())
                && page.getUserInfo() == null && (page.getPort() == -1 || page.getPort() == 443)) {
                // Keep the existing document, drafts, streams and permission flows.
                // The webpage applies this hint only when "follow system" is selected.
                webView.evaluateJavascript(script, null);
            }
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
        // DMate supplies its own light/dark CSS, including explicit user choices.
        if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
            WebSettingsCompat.setAlgorithmicDarkeningAllowed(settings, false);
        }

        String ua = settings.getUserAgentString();
        if (ua == null) ua = "";
        if (!ua.contains(BuildConfig.DMATE_USER_AGENT)) {
            settings.setUserAgentString((ua + " " + BuildConfig.DMATE_USER_AGENT).trim());
        }

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, false);

        installGallerySaveBridge();
        installLanguageBridge();
        refreshSystemThemeBridge();
        webView.setWebViewClient(new DmateWebViewClient());
        webView.setWebChromeClient(new DmateChromeClient());
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            openExternal(Uri.parse(url));
        });
    }

    private boolean usesEnglish() {
        String selected = getSharedPreferences(LANGUAGE_PREFERENCES, MODE_PRIVATE)
            .getString(LANGUAGE_KEY, "");
        if ("en".equals(selected)) return true;
        if ("zh-CN".equals(selected)) return false;
        Configuration configuration = getResources().getConfiguration();
        Locale locale = configuration.getLocales().isEmpty()
            ? Locale.getDefault() : configuration.getLocales().get(0);
        // English is the fallback for device languages other than Chinese.
        return !"zh".equalsIgnoreCase(locale.getLanguage());
    }

    private String nativeText(String chinese, String english) {
        return usesEnglish() ? english : chinese;
    }

    /** The trusted website may select a language, never request native actions. */
    private void installLanguageBridge() {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return;
        WebViewCompat.addWebMessageListener(
            webView,
            "DMateLanguage",
            Collections.singleton("https://" + HOME_HOST),
            (view, message, sourceOrigin, isMainFrame, replyProxy) -> {
                if (!isMainFrame || view != webView || isFinishing() || isDestroyed()
                    || message.getType() != WebMessageCompat.TYPE_STRING
                    || !isTrustedMicrophoneOrigin(sourceOrigin)
                    || view.getUrl() == null
                    || !isTrustedMicrophoneOrigin(Uri.parse(view.getUrl()))) return;
                String raw = message.getData();
                if (raw == null || raw.length() > 100) return;
                try {
                    String language = new JSONObject(raw).optString("language", "");
                    if (!"en".equals(language) && !"zh-CN".equals(language)) return;
                    getSharedPreferences(LANGUAGE_PREFERENCES, MODE_PRIVATE)
                        .edit().putString(LANGUAGE_KEY, language).apply();
                } catch (Exception ignored) {
                    // Ignore malformed messages without changing the saved choice.
                }
            }
        );
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
                    !isTrustedPage() || !canSaveToGallery()) {
                    return;
                }
                String raw = message.getData();
                if (raw == null || raw.length() > MAX_PNG_BYTES * 4 / 3 + 4096) {
                    sendGalleryReply(replyProxy, "", false, nativeText("图片过大，无法保存", "The image is too large to save."));
                    return;
                }
                try {
                    JSONObject request = new JSONObject(raw);
                    String id = request.optString("id", "");
                    String filename = request.optString("filename", nativeText("DMate-图片.png", "DMate-image.png"));
                    String base64 = request.optString("base64", "");
                    if (id.length() < 1 || id.length() > 128 || base64.isEmpty() ||
                        base64.length() > MAX_PNG_BYTES * 4 / 3 + 1024) {
                        sendGalleryReply(replyProxy, id, false, nativeText("图片数据不正确", "The image data is invalid."));
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
                            runOnUiThread(() -> sendGalleryReply(replyProxy, id, false, nativeText("图片数据无效", "The image data is invalid.")));
                        }
                    });
                } catch (RejectedExecutionException ignored) {
                    // Activity teardown may close the executor before a late bridge callback.
                } catch (Exception error) {
                    sendGalleryReply(replyProxy, "", false, nativeText("无法解析图片保存请求", "The image save request could not be read."));
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

    private boolean isTrustedMicrophoneOrigin(Uri origin) {
        if (origin == null || !"https".equalsIgnoreCase(origin.getScheme()) ||
            !HOME_HOST.equalsIgnoreCase(origin.getHost()) || origin.getUserInfo() != null) return false;
        Uri home = Uri.parse(HOME_URL);
        int expectedPort = home.getPort() == -1 ? 443 : home.getPort();
        int actualPort = origin.getPort() == -1 ? 443 : origin.getPort();
        return "https".equalsIgnoreCase(home.getScheme()) &&
            HOME_HOST.equalsIgnoreCase(home.getHost()) && actualPort == expectedPort;
    }

    private boolean isTrustedMicrophoneRequest(PermissionRequest request) {
        return request != null && !isFinishing() && !isDestroyed() && webView != null &&
            webView.getUrl() != null && isTrustedMicrophoneOrigin(request.getOrigin()) &&
            isTrustedMicrophoneOrigin(Uri.parse(webView.getUrl()));
    }

    private void denyMicrophone(PermissionRequest request) {
        if (request == null) return;
        try { request.deny(); } catch (IllegalStateException ignored) {
            // The renderer may already have cancelled its request.
        }
    }

    private void cancelPendingMicrophoneRequest() {
        PermissionRequest request = pendingMicrophoneRequest;
        pendingMicrophoneRequest = null;
        denyMicrophone(request);
    }

    private void grantMicrophone(PermissionRequest request) {
        if (!isTrustedMicrophoneRequest(request) ||
            checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            denyMicrophone(request);
            return;
        }
        // Never grant request.getResources(): camera and future permissions
        // are outside this feature even when Android microphone access exists.
        try { request.grant(new String[] { PermissionRequest.RESOURCE_AUDIO_CAPTURE }); }
        catch (IllegalStateException ignored) { /* A cancelled renderer cannot receive a grant. */ }
    }

    private void requestMicrophone(PermissionRequest request) {
        String[] resources = request.getResources();
        if (resources == null || resources.length != 1 ||
            !PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[0]) ||
            !isTrustedMicrophoneRequest(request) || pendingMicrophoneRequest != null ||
            microphonePermissionInFlight) {
            denyMicrophone(request);
            return;
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            grantMicrophone(request);
            return;
        }
        pendingMicrophoneRequest = request;
        microphonePermissionInFlight = true;
        requestPermissions(new String[] { Manifest.permission.RECORD_AUDIO }, MICROPHONE_PERMISSION_REQUEST);
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

    private boolean canSaveToGallery() {
        return !isFinishing() && !isDestroyed() && webView != null && !imageSaver.isShutdown();
    }

    private void beginGallerySave(PendingSave save) {
        // Decoding runs off the UI thread. Its posted callback can arrive after
        // onDestroy has closed the executor and disposed the WebView.
        if (!canSaveToGallery()) return;
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q &&
            checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            if (pendingLegacySave != null) {
                sendGalleryReply(save.reply, save.id, false, nativeText("请完成前一次图片保存", "Please finish the previous image save first."));
                return;
            }
            pendingLegacySave = save;
            requestPermissions(new String[] { Manifest.permission.WRITE_EXTERNAL_STORAGE }, LEGACY_SAVE_PERMISSION_REQUEST);
            return;
        }
        saveImageAsync(save);
    }

    private void saveImageAsync(PendingSave save) {
        if (!canSaveToGallery()) return;
        try {
            imageSaver.execute(() -> {
                try {
                    storePngInGallery(save.png, save.filename);
                    runOnUiThread(() -> sendGalleryReply(save.reply, save.id, true, nativeText("图片已保存到相册 · DMate", "Image saved to Photos · DMate")));
                } catch (Exception error) {
                    runOnUiThread(() -> sendGalleryReply(save.reply, save.id, false, nativeText("保存到相册失败，请检查可用空间", "Could not save to Photos. Check the available storage space.")));
                }
            });
        } catch (RejectedExecutionException ignored) {
            // Closing the Activity cancels saves that have not started yet.
        }
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
        if (requestCode == MICROPHONE_PERMISSION_REQUEST) {
            microphonePermissionInFlight = false;
            PermissionRequest request = pendingMicrophoneRequest;
            pendingMicrophoneRequest = null;
            if (request == null) return;
            if (permissions.length == 1 && Manifest.permission.RECORD_AUDIO.equals(permissions[0]) &&
                grantResults.length == 1 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                grantMicrophone(request); // Recheck both origins after the Android dialog.
            } else {
                denyMicrophone(request);
            }
            return;
        }
        if (requestCode != LEGACY_SAVE_PERMISSION_REQUEST) return;
        PendingSave save = pendingLegacySave;
        pendingLegacySave = null;
        if (save == null) return;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            saveImageAsync(save);
        } else {
            sendGalleryReply(save.reply, save.id, false, nativeText("没有存储权限，无法保存到相册", "Storage permission is required to save to Photos."));
        }
    }

    private final class DmateWebViewClient extends WebViewClient {
        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            cancelPendingMicrophoneRequest();
            super.onPageStarted(view, url, favicon);
        }

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
            if (view == webView) refreshSystemThemeBridge();
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

    private Intent createImagePickerIntent(boolean documents, boolean multiple) {
        Intent intent = new Intent(documents ? Intent.ACTION_OPEN_DOCUMENT : Intent.ACTION_GET_CONTENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        return Intent.createChooser(intent, nativeText("选择图片", "Choose images"));
    }

    private boolean launchImagePicker(boolean documents) {
        try {
            filePickerLaunchedAt = SystemClock.elapsedRealtime();
            startActivityForResult(createImagePickerIntent(documents, filePickerMultiple), FILE_CHOOSER_REQUEST);
            filePickerTriedDocuments = documents;
            return true;
        } catch (ActivityNotFoundException | SecurityException error) {
            return false;
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

            // Huawei and some other Android WebViews may immediately close the
            // ACTION_OPEN_DOCUMENT UI. Prefer the content chooser, and allow one
            // document-picker retry when an OEM picker exits almost instantly.
            filePickerMultiple = fileChooserParams.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE;
            filePickerTriedDocuments = false;
            if (!launchImagePicker(false) && !launchImagePicker(true)) {
                pendingFileCallback = null;
                filePathCallback.onReceiveValue(null);
                Toast.makeText(MainActivity.this, nativeText("无法打开系统图片选择器", "Could not open the system image picker."), Toast.LENGTH_SHORT).show();
            }
            return true;
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            requestMicrophone(request);
        }

        @Override
        public void onPermissionRequestCanceled(PermissionRequest request) {
            if (pendingMicrophoneRequest == request) pendingMicrophoneRequest = null;
            super.onPermissionRequestCanceled(request);
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
        cancelPendingMicrophoneRequest();
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
            Toast.makeText(this, nativeText("无法打开此链接", "Could not open this link."), Toast.LENGTH_SHORT).show();
        }
    }

    private void showOfflinePage() {
        final String html = "<!doctype html><html lang='" + (usesEnglish() ? "en" : "zh-CN") + "'><head><meta charset='utf-8'>"
            + "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            + "<style>body{margin:0;background:#111;color:#eee;font:16px sans-serif;display:grid;"
            + "place-items:center;min-height:100vh}.c{text-align:center;padding:28px}button{border:0;border-radius:12px;"
            + "padding:12px 18px;font-size:16px}</style></head><body><div class='c'><h2>"
            + nativeText("DMate 暂时无法连接", "DMate is temporarily unavailable") + "</h2><p>"
            + nativeText("请检查网络后重试。", "Check your connection and try again.")
            + "</p><button onclick=\"location.href='" + HOME_URL + "'\">" + nativeText("重新连接", "Reconnect") + "</button>"
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

        // An immediate empty result often means the OEM chooser failed to
        // launch, not that the user deliberately cancelled a normal dialog.
        if (resultCode != RESULT_OK && !filePickerTriedDocuments &&
            SystemClock.elapsedRealtime() - filePickerLaunchedAt < 450 &&
            launchImagePicker(true)) {
            return;
        }

        ValueCallback<Uri[]> callback = pendingFileCallback;
        pendingFileCallback = null;
        Uri[] result = null;
        if (resultCode == RESULT_OK && data != null) {
            LinkedHashSet<Uri> selected = new LinkedHashSet<>();
            ClipData clips = data.getClipData();
            if (clips != null) {
                for (int i = 0; i < clips.getItemCount(); i++) {
                    Uri uri = clips.getItemAt(i).getUri();
                    if (uri != null && "content".equalsIgnoreCase(uri.getScheme())) selected.add(uri);
                }
            }
            if (data.getData() != null && "content".equalsIgnoreCase(data.getData().getScheme())) {
                selected.add(data.getData());
            }
            // The origin only receives URIs intentionally granted by the user.
            // Reject file:// and other schemes rather than handing an untrusted
            // provider's raw local path to a remote web page.
            if (!selected.isEmpty()) result = selected.toArray(new Uri[0]);
        }
        callback.onReceiveValue(result);
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
        setTheme(systemAppearanceTheme(getResources().getConfiguration()));
        if (webView != null) {
            webView.onResume();
            refreshSystemThemeBridge();
        }
    }

    @Override
    protected void onDestroy() {
        cancelPendingMicrophoneRequest();
        if (pendingFileCallback != null) {
            pendingFileCallback.onReceiveValue(null);
            pendingFileCallback = null;
        }
        pendingLegacySave = null;
        imageSaver.shutdown();
        if (webView != null) {
            if (systemThemeStartScript != null) {
                systemThemeStartScript.remove();
                systemThemeStartScript = null;
                documentStartSystemTheme = null;
            }
            webView.stopLoading();
            webView.setWebChromeClient(null);
            webView.setWebViewClient(null);
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
