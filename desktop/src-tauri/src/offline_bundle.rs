use std::borrow::Cow;
use tauri::{
    http::{Method, Request, Response, StatusCode},
    Builder, Manager, Runtime, Url, WebviewWindow,
};

#[cfg(not(target_os = "windows"))]
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

include!(concat!(env!("OUT_DIR"), "/dmate_offline_assets.rs"));

const HOST: &str = "dmate.zeabur.app";
const ORIGIN: &str = "https://dmate.zeabur.app";
const SCHEME: &str = "dmate-offline";
const START_HTML: &[u8] = b"<!doctype html><meta charset=utf-8><meta name=color-scheme content='light dark'><title>DMate</title>";

fn offline_document(url: &Url) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some(HOST)
        && url.port_or_known_default() == Some(443)
        && url.username().is_empty()
        && url.password().is_none()
        && matches!(url.path(), "/offline" | "/static/offline.html")
}

pub fn startup_document(url: &Url) -> bool {
    let origin_matches = if cfg!(target_os = "windows") {
        url.scheme() == "http"
            && url.host_str() == Some("dmate-offline.localhost")
            && url.port_or_known_default() == Some(80)
    } else {
        url.scheme() == SCHEME && url.host_str() == Some("localhost") && url.port().is_none()
    };
    origin_matches
        && url.path() == "/start"
        && url.username().is_empty()
        && url.password().is_none()
        && url.query().is_none()
        && url.fragment().is_none()
}

fn startup_url() -> Url {
    let url = if cfg!(target_os = "windows") {
        "http://dmate-offline.localhost/start"
    } else {
        "dmate-offline://localhost/start"
    };
    Url::parse(url).expect("DMate startup URL must be valid")
}

fn content_type(path: &str) -> &'static str {
    match path.rsplit('.').next() {
        Some("css") => "text/css; charset=utf-8",
        Some("js") => "text/javascript; charset=utf-8",
        Some("json") => "application/json; charset=utf-8",
        Some("svg") => "image/svg+xml",
        Some("png") => "image/png",
        Some("ico") => "image/x-icon",
        Some("woff") => "font/woff",
        Some("woff2") => "font/woff2",
        _ => "application/octet-stream",
    }
}

fn asset_response(request: Request<Vec<u8>>) -> Response<Cow<'static, [u8]>> {
    let path = request.uri().path();
    let response = Response::builder()
        .header("Cache-Control", "no-store")
        .header("X-Content-Type-Options", "nosniff")
        // Only public, embedded workspace assets can be requested, and only
        // the genuine HTTPS page can read them cross-origin from JavaScript.
        .header("Access-Control-Allow-Origin", ORIGIN);
    let found = if request.method() != Method::GET {
        None
    } else if path == "/start" {
        Some(("text/html; charset=utf-8", START_HTML))
    } else if path.starts_with("/static/") && path != "/static/offline.html" {
        bundled_asset(path).map(|bytes| (content_type(path), bytes))
    } else {
        None
    };
    match found {
        Some((mime, bytes)) => response
            .header("Content-Type", mime)
            .body(Cow::Borrowed(bytes)),
        None => response
            .status(StatusCode::NOT_FOUND)
            .body(Cow::Borrowed(&[][..])),
    }
    .expect("DMate protocol response uses static headers")
}

fn bundled_html() -> &'static str {
    // The main document keeps its HTTPS address. Only resource resolution is
    // redirected to the private scheme, so offline IndexedDB and native keys
    // are the same as in earlier installations.
    static HTML: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    HTML.get_or_init(|| {
        let html = bundled_asset("/offline").expect("DMate offline document is packaged");
        let html = std::str::from_utf8(html).expect("DMate offline document is UTF-8");
        let base = if cfg!(target_os = "windows") {
            "<head><base href=\"http://dmate-offline.localhost/\">"
        } else {
            "<head><base href=\"dmate-offline://localhost/\">"
        };
        html.replacen("<head>", base, 1)
    })
}

pub fn configure<R: Runtime>(builder: Builder<R>) -> Builder<R> {
    let builder = builder
        .register_uri_scheme_protocol(SCHEME, |_context, request| asset_response(request))
        .append_invoke_initialization_script(include_str!("offline-start.js"))
        .setup(|app| {
            let main = app
                .get_webview_window("main")
                .expect("DMate main window is configured");
            initialize(&main)?;
            Ok(())
        });

    #[cfg(not(target_os = "windows"))]
    let builder = {
        let replacing = Arc::new(AtomicBool::new(false));
        builder.plugin(
            tauri::plugin::Builder::<R>::new("bundled-offline-workspace")
                .on_navigation(move |webview, url| {
                    if webview.label() != "main" || !offline_document(url) {
                        return true;
                    }
                    // A WebKit substitute-data load also triggers the ordinary
                    // navigation policy. Allow that callback through once.
                    if replacing.swap(true, Ordering::SeqCst) {
                        replacing.store(false, Ordering::SeqCst);
                        return true;
                    }
                    let url = url.clone();
                    let webview = webview.clone();
                    let pending = Arc::clone(&replacing);
                    // Dispatch from a worker so WebKit can finish cancelling
                    // the original request before the substitute load begins.
                    tauri::async_runtime::spawn(async move {
                        if webview
                            .with_webview(move |handle| load_html(handle, url))
                            .is_err()
                        {
                            pending.store(false, Ordering::SeqCst);
                        }
                    });
                    false
                })
                .build(),
        )
    };
    builder
}

#[cfg(not(target_os = "windows"))]
fn initialize<R: Runtime>(window: &WebviewWindow<R>) -> tauri::Result<()> {
    window.navigate(startup_url())
}

#[cfg(target_os = "linux")]
fn load_html(platform: tauri::webview::PlatformWebview, url: Url) {
    use webkit2gtk::WebViewExt;
    platform
        .inner()
        .load_html(bundled_html(), Some(url.as_str()));
}

#[cfg(target_os = "macos")]
fn load_html(platform: tauri::webview::PlatformWebview, url: Url) {
    use objc2::{msg_send, runtime::AnyObject};
    use objc2_foundation::{NSString, NSURL};

    let html = NSString::from_str(bundled_html());
    let url = NSString::from_str(url.as_str());
    if let Some(base) = NSURL::URLWithString(&url) {
        // with_webview dispatches this closure to the main thread, and the
        // retained handle is a WKWebView for the lifetime of the closure.
        unsafe {
            let webview = &*platform.inner().cast::<AnyObject>();
            let _: *mut AnyObject = msg_send![webview, loadHTMLString: &*html, baseURL: &*base];
        }
    }
}

#[cfg(target_os = "windows")]
fn initialize<R: Runtime>(window: &WebviewWindow<R>) -> tauri::Result<()> {
    use webview2_com::CallDevToolsProtocolMethodCompletedHandler;
    use windows::core::HSTRING;

    let main = window.clone();
    window.with_webview(move |handle| {
        let installed = install_windows_document_handler(&handle);
        if let Ok(webview) = installed {
            // Prior versions installed a web service worker in this same
            // WebView2 profile. Pass its navigations to the native handler
            // without deleting cached assets or any origin storage.
            let window = main.clone();
            let ready =
                CallDevToolsProtocolMethodCompletedHandler::create(Box::new(move |_, _| {
                    let _ = window.navigate(startup_url());
                    Ok(())
                }));
            if unsafe {
                webview.CallDevToolsProtocolMethod(
                    &HSTRING::from("Network.setBypassServiceWorker"),
                    &HSTRING::from(r#"{"bypass":true}"#),
                    &ready,
                )
            }
            .is_err()
            {
                let _ = main.navigate(startup_url());
            }
        } else {
            // If an OEM runtime cannot attach the native handler, retain the
            // web application's previous cache-based route for this launch.
            let url = Url::parse("https://dmate.zeabur.app/?dmate_native_offline_unavailable=1")
                .expect("DMate fallback URL must be valid");
            let _ = main.navigate(url);
        }
    })
}

#[cfg(target_os = "windows")]
fn install_windows_document_handler(
    platform: &tauri::webview::PlatformWebview,
) -> windows::core::Result<webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2> {
    use webview2_com::{
        take_pwstr,
        Microsoft::Web::WebView2::Win32::{
            ICoreWebView2_22, COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL,
            COREWEBVIEW2_WEB_RESOURCE_REQUEST_SOURCE_KINDS_ALL,
        },
        WebResourceRequestedEventHandler,
    };
    use windows::{
        core::{Interface, HSTRING, PWSTR},
        Win32::UI::Shell::SHCreateMemStream,
    };

    // WebView2 has a first-class interception hook for HTTPS navigations. For
    // the two exact offline URLs return only the installed document. Subresource
    // URLs use our separate scheme and never intercept the public HTTPS site.
    unsafe {
        let webview = platform.controller().CoreWebView2()?;
        for path in ["/offline*", "/static/offline.html*"] {
            let filter = HSTRING::from(format!("{ORIGIN}{path}"));
            if let Ok(view) = webview.cast::<ICoreWebView2_22>() {
                view.AddWebResourceRequestedFilterWithRequestSourceKinds(
                    &filter,
                    COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL,
                    COREWEBVIEW2_WEB_RESOURCE_REQUEST_SOURCE_KINDS_ALL,
                )?;
            } else {
                webview.AddWebResourceRequestedFilter(
                    &filter,
                    COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL,
                )?;
            }
        }
        let environment = platform.environment();
        webview.add_WebResourceRequested(
            &WebResourceRequestedEventHandler::create(Box::new(move |_, args| {
                let Some(args) = args else { return Ok(()) };
                let request = args.Request()?;
                let mut uri = PWSTR::null();
                request.Uri(&mut uri)?;
                let Ok(url) = Url::parse(&take_pwstr(uri)) else { return Ok(()) };
                let mut method = PWSTR::null();
                request.Method(&mut method)?;
                let method = take_pwstr(method);
                if offline_document(&url) && method == "GET" {
                    let body = SHCreateMemStream(Some(bundled_html().as_bytes()));
                    let response = environment.CreateWebResourceResponse(body.as_ref(), 200,
                        &HSTRING::from("OK"),
                        &HSTRING::from("Content-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n"),
                    )?;
                    args.SetResponse(&response)?;
                }
                Ok(())
            })),
            &mut 0,
        )?;
        Ok(webview)
    }
}
