package app.dmate.client;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.webkit.WebView;
import android.widget.Toast;

import androidx.core.content.FileProvider;
import androidx.webkit.JavaScriptReplyProxy;
import androidx.webkit.WebMessageCompat;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

/**
 * Sideloaded DMate's internal update channel: opt-in download in the Android
 * DownloadManager, SHA-256/package/version validation and OS-approved install.
 * Never bypass Android's installer or silently replace the signed application.
 */
final class NativeUpdateManager {
    private static final String PREFS = "dmate_native_updates";
    private static final String ID = "download_id";
    private static final String VERSION = "version";
    private static final String HASH = "sha256";
    private static final String DOWNLOAD_URL = "download_url";
    private static final String INSTALL_ATTEMPTED = "install_attempted";
    private static final long POLL_MS = 4500L;
    private static final long MAX_APK_BYTES = 150L * 1024L * 1024L;
    private static final Pattern RELEASE_URL = Pattern.compile(
        "^https://github\\.com/zm14744/DMate/releases/download/v[0-9]+\\.[0-9]+\\.[0-9]+/DMate\\.apk$");
    private static final Pattern SHA256 = Pattern.compile("^[0-9a-f]{64}$");
    private static final Pattern SEMVER = Pattern.compile("^[0-9]+\\.[0-9]+\\.[0-9]+$");

    private final Activity activity;
    private final WebView webView;
    private final String officialHost;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService verifier = Executors.newSingleThreadExecutor();
    private final SharedPreferences preferences;
    private boolean resumed;
    private boolean verifying;
    private boolean waitingForInstallPermission;
    private boolean disposed;

    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (resumed && !disposed) checkPendingDownload();
        }
    };

    NativeUpdateManager(Activity activity, WebView webView, String officialHost) {
        this.activity = activity;
        this.webView = webView;
        this.officialHost = officialHost;
        preferences = activity.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    void installBridge() {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return;
        WebViewCompat.addWebMessageListener(
            webView, "DMateUpdate", Collections.singleton("https://" + officialHost),
            (view, message, sourceOrigin, isMainFrame, reply) -> {
                if (!isMainFrame || view != webView || disposed || sourceOrigin == null ||
                    !"https".equalsIgnoreCase(sourceOrigin.getScheme()) ||
                    !officialHost.equalsIgnoreCase(sourceOrigin.getHost()) ||
                    message.getType() != WebMessageCompat.TYPE_STRING || !trustedPage()) return;
                String json = message.getData();
                if (json == null || json.length() > 1024) {
                    reply(reply, "", false, "更新请求无效");
                    return;
                }
                try {
                    JSONObject request = new JSONObject(json);
                    String id = request.optString("id", "");
                    String url = request.optString("url", "");
                    String version = request.optString("version", "");
                    String sha256 = request.optString("sha256", "").toLowerCase(Locale.ROOT);
                    if (id.length() < 1 || id.length() > 120 ||
                        !RELEASE_URL.matcher(url).matches() ||
                        !SEMVER.matcher(version).matches() ||
                        !SHA256.matcher(sha256).matches() ||
                        compareVersion(version, BuildConfig.VERSION_NAME) <= 0) {
                        reply(reply, id, false, "更新包来源、版本或校验信息无效");
                        return;
                    }
                    activity.runOnUiThread(() -> beginDownload(id, version, url, sha256, reply));
                } catch (Exception ignored) {
                    reply(reply, "", false, "无法处理更新请求");
                }
            });
    }

    private boolean trustedPage() {
        Uri current = Uri.parse(String.valueOf(webView.getUrl()));
        return "https".equalsIgnoreCase(current.getScheme()) &&
            officialHost.equalsIgnoreCase(current.getHost());
    }

    private static int compareVersion(String candidate, String installed) {
        if (!SEMVER.matcher(candidate).matches() || !SEMVER.matcher(installed).matches()) return -1;
        try {
            String[] a = candidate.split("\\."), b = installed.split("\\.");
            for (int i = 0; i < 3; i++) {
                int ai = Integer.parseInt(a[i]), bi = Integer.parseInt(b[i]);
                if (ai != bi) return ai > bi ? 1 : -1;
            }
        } catch (NumberFormatException ignored) { return -1; }
        return 0;
    }

    private void beginDownload(String id, String version, String url,
                               String expectedSha256, JavaScriptReplyProxy reply) {
        if (disposed) return;
        DownloadManager manager = (DownloadManager) activity.getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager == null) {
            reply(reply, id, false, "安卓系统下载服务不可用");
            return;
        }
        long oldId = preferences.getLong(ID, -1L);
        if (oldId > 0 && version.equals(preferences.getString(VERSION, "")) &&
            url.equals(preferences.getString(DOWNLOAD_URL, "")) &&
            expectedSha256.equals(preferences.getString(HASH, ""))) {
            preferences.edit().putBoolean(INSTALL_ATTEMPTED, false).apply();
            waitingForInstallPermission = false;
            reply(reply, id, true, "已在下载或等待安装；完成后将在应用内提示");
            checkPendingDownload();
            return;
        }
        if (oldId > 0) manager.remove(oldId);
        File dest = apkFile(version);
        if (dest == null) {
            reply(reply, id, false, "没有可用的更新缓存目录");
            return;
        }
        if (dest.exists() && !dest.delete()) {
            reply(reply, id, false, "无法清理旧的安装包缓存");
            return;
        }
        try {
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url))
                .setTitle("DMate " + version)
                .setDescription("正在后台下载已发布的安全更新")
                .setMimeType("application/vnd.android.package-archive")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setAllowedOverRoaming(false)
                .setDestinationInExternalFilesDir(activity, Environment.DIRECTORY_DOWNLOADS,
                    "updates/DMate-" + version + ".apk");
            long newId = manager.enqueue(request);
            preferences.edit().putLong(ID, newId).putString(VERSION, version)
                .putString(DOWNLOAD_URL, url).putString(HASH, expectedSha256)
                .putBoolean(INSTALL_ATTEMPTED, false).apply();
            reply(reply, id, true, "系统正在后台下载，下载完毕会请求安装确认");
            if (resumed) schedulePoll();
        } catch (Exception error) {
            reply(reply, id, false, "无法开始后台下载，请使用官方安装包链接");
        }
    }

    private File apkFile(String version) {
        if (version == null || !SEMVER.matcher(version).matches()) return null;
        File root = activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
        if (root == null) return null;
        File directory = new File(root, "updates");
        if (!directory.isDirectory() && !directory.mkdirs()) return null;
        return new File(directory, "DMate-" + version + ".apk");
    }

    void onResume() {
        resumed = true;
        checkPendingDownload();
    }

    void onPause() {
        resumed = false;
        handler.removeCallbacks(poll);
    }

    void onDestroy() {
        disposed = true;
        resumed = false;
        handler.removeCallbacks(poll);
        verifier.shutdown();
    }

    private void schedulePoll() {
        handler.removeCallbacks(poll);
        if (resumed && !disposed) handler.postDelayed(poll, POLL_MS);
    }

    private void checkPendingDownload() {
        if (disposed || !resumed) return;
        long id = preferences.getLong(ID, -1L);
        if (id <= 0) return;
        DownloadManager manager = (DownloadManager) activity.getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager == null) return;
        int status;
        try (Cursor cursor = manager.query(new DownloadManager.Query().setFilterById(id))) {
            if (cursor == null || !cursor.moveToFirst()) {
                clearDownload();
                return;
            }
            status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
        } catch (RuntimeException e) {
            schedulePoll();
            return;
        }
        if (status == DownloadManager.STATUS_SUCCESSFUL) {
            if (!preferences.getBoolean(INSTALL_ATTEMPTED, false)) verifyAndOfferInstall(id);
        } else if (status == DownloadManager.STATUS_FAILED) {
            clearDownload();
            Toast.makeText(activity, "更新下载失败，可稍后重试", Toast.LENGTH_LONG).show();
        } else schedulePoll();
    }

    private void verifyAndOfferInstall(long id) {
        if (verifying || disposed) return;
        String version = preferences.getString(VERSION, "");
        String digest = preferences.getString(HASH, "");
        File file = apkFile(version);
        if (file == null || !SHA256.matcher(digest).matches()) {
            clearDownload();
            return;
        }
        verifying = true;
        verifier.execute(() -> {
            boolean valid = validateApk(file, digest);
            handler.post(() -> {
                verifying = false;
                if (disposed || id != preferences.getLong(ID, -1L)) return;
                if (!valid) {
                    clearDownload();
                    Toast.makeText(activity, "更新包校验失败，已取消安装", Toast.LENGTH_LONG).show();
                } else if (resumed) requestInstall(file);
            });
        });
    }

    private boolean validateApk(File apk, String expectedSha256) {
        if (!apk.isFile() || apk.length() == 0 || apk.length() > MAX_APK_BYTES) return false;
        try {
            MessageDigest sha = MessageDigest.getInstance("SHA-256");
            try (FileInputStream in = new FileInputStream(apk)) {
                byte[] buffer = new byte[32768];
                int n;
                while ((n = in.read(buffer)) != -1) sha.update(buffer, 0, n);
            }
            byte[] value = sha.digest();
            char[] digits = "0123456789abcdef".toCharArray();
            char[] hex = new char[value.length * 2];
            for (int i = 0; i < value.length; i++) {
                hex[2 * i] = digits[(value[i] >>> 4) & 15];
                hex[2 * i + 1] = digits[value[i] & 15];
            }
            if (!MessageDigest.isEqual(new String(hex).getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                expectedSha256.getBytes(java.nio.charset.StandardCharsets.US_ASCII))) return false;
            PackageInfo candidate = activity.getPackageManager().getPackageArchiveInfo(apk.getAbsolutePath(), 0);
            return candidate != null && activity.getPackageName().equals(candidate.packageName)
                && candidate.versionCode > BuildConfig.VERSION_CODE;
        } catch (Exception error) {
            return false;
        }
    }

    private void requestInstall(File apk) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !activity.getPackageManager().canRequestPackageInstalls()) {
            if (waitingForInstallPermission) {
                waitingForInstallPermission = false;
                preferences.edit().putBoolean(INSTALL_ATTEMPTED, true).apply();
                Toast.makeText(activity, "未授权从此来源安装，更新包已保留", Toast.LENGTH_LONG).show();
                return;
            }
            waitingForInstallPermission = true;
            try {
                Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName()));
                activity.startActivity(settings);
            } catch (ActivityNotFoundException error) {
                waitingForInstallPermission = false;
                preferences.edit().putBoolean(INSTALL_ATTEMPTED, true).apply();
                Toast.makeText(activity, "无法打开安装授权设置", Toast.LENGTH_LONG).show();
            }
            return;
        }
        waitingForInstallPermission = false;
        try {
            Uri uri = FileProvider.getUriForFile(activity,
                activity.getPackageName() + ".updates", apk);
            Intent install = new Intent(Intent.ACTION_VIEW);
            install.setDataAndType(uri, "application/vnd.android.package-archive");
            install.setClipData(android.content.ClipData.newUri(activity.getContentResolver(), "DMate 安装包", uri));
            install.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            preferences.edit().putBoolean(INSTALL_ATTEMPTED, true).apply();
            activity.startActivity(install);
        } catch (Exception error) {
            preferences.edit().putBoolean(INSTALL_ATTEMPTED, true).apply();
            Toast.makeText(activity, "无法打开系统安装界面，可使用官方链接安装", Toast.LENGTH_LONG).show();
        }
    }

    private void clearDownload() {
        preferences.edit().remove(ID).remove(VERSION).remove(HASH)
            .remove(DOWNLOAD_URL).remove(INSTALL_ATTEMPTED).apply();
    }

    private void reply(JavaScriptReplyProxy target, String id, boolean ok, String message) {
        try {
            JSONObject response = new JSONObject();
            response.put("id", id);
            response.put("ok", ok);
            response.put("message", message);
            target.postMessage(response.toString());
        } catch (Exception ignored) {}
    }
}
