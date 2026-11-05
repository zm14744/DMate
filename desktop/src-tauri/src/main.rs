#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(any(target_os = "windows", target_os = "macos"))]
mod system_theme {
    use tauri::{
        webview::PageLoadEvent, Builder, Manager, Runtime, Theme, Url, WebviewWindow, WindowEvent,
    };

    fn trusted_page(url: &Url) -> bool {
        url.scheme() == "https"
            && url.host_str() == Some("dmate.zeabur.app")
            && url.port_or_known_default() == Some(443)
            && url.username().is_empty()
            && url.password().is_none()
    }

    fn publish<R: Runtime>(window: &WebviewWindow<R>) {
        if window.label() != "main" {
            return;
        }
        let Ok(url) = window.url() else {
            return;
        };
        if !trusted_page(&url) {
            return;
        }
        // The window configuration leaves theme unset, so this is the native
        // system appearance, independent of the webpage's manual theme choice.
        let Ok(theme) = window.theme() else {
            return;
        };
        let theme = match theme {
            Theme::Dark => "dark",
            Theme::Light => "light",
            _ => return,
        };
        // Recheck the origin at execution time: navigation can happen between
        // url() and eval(). Only signal the main frame; never force page styles.
        let script = format!(
            r#"(() => {{
                const page = new URL(location.href);
                if (window !== window.top || page.origin !== "https://dmate.zeabur.app" || page.username || page.password) return;
                const theme = "{theme}";
                window.__DMATE_NATIVE_SYSTEM_THEME__ = theme;
                window.dispatchEvent(new CustomEvent("dmate:native-system-theme", {{
                    detail: {{ theme, source: "desktop" }}
                }}));
            }})();"#
        );
        // A page/window may disappear during navigation or shutdown. A missing
        // signal falls back to CSS media queries, without reloading active work.
        let _ = window.eval(script);
    }

    pub fn configure<R: Runtime>(builder: Builder<R>) -> Builder<R> {
        builder
            .on_page_load(|webview, payload| {
                if webview.label() == "main"
                    && matches!(payload.event(), PageLoadEvent::Finished)
                    && trusted_page(payload.url())
                {
                    if let Some(window) = webview.app_handle().get_webview_window("main") {
                        publish(&window);
                    }
                }
            })
            .on_window_event(|window, event| {
                if window.label() == "main"
                    && matches!(
                        event,
                        WindowEvent::ThemeChanged(_) | WindowEvent::Focused(true)
                    )
                {
                    if let Some(webview) = window.app_handle().get_webview_window("main") {
                        publish(&webview);
                    }
                }
            })
    }
}

fn main() {
    let builder = tauri::Builder::default();
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    let builder = system_theme::configure(builder);
    // Linux has no Tauri ThemeChanged event. Keep its live media-query path
    // rather than overriding it with a native snapshot that could become stale.
    builder
        .run(tauri::generate_context!())
        .expect("DMate desktop failed to start");
}
