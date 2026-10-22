#!/usr/bin/env python3
"""Read-only Playwright checks of the deployed DMate UI; never sends AI requests."""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def exercise(browser, url, output_dir, mode):
    is_mobile = mode == "mobile"
    context = browser.new_context(
        viewport={"width": 390, "height": 844} if is_mobile else {"width": 1440, "height": 900},
        is_mobile=is_mobile,
        has_touch=is_mobile,
        device_scale_factor=1,
        locale="zh-CN",
        color_scheme="light",
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    result = {"mode": mode, "steps": [], "page_errors": [], "server_errors": [], "screenshots": []}
    target_host = urlsplit(url).netloc
    page.on("pageerror", lambda exc: result["page_errors"].append(str(exc)[:1200]))
    page.on("response", lambda response: (
        result["server_errors"].append({"status": response.status, "url": response.url[:260]})
        if response.status >= 500 and urlsplit(response.url).netloc == target_host else None
    ))

    def screenshot(name):
        path = output_dir / f"{mode}-{name}.png"
        page.screenshot(path=str(path), full_page=False, animations="disabled", timeout=15000)
        result["screenshots"].append(path.name)

    def step(name, callback):
        try:
            callback()
            result["steps"].append({"name": name, "status": "passed"})
            return True
        except Exception as exc:
            result["steps"].append({"name": name, "status": "failed", "error": str(exc)[:1400]})
            try:
                screenshot(name + "-failed")
            except Exception:
                pass
            return False

    def open_home():
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if response is None or not 200 <= response.status < 400:
            raise AssertionError(f"Homepage HTTP status: {response.status if response else 'no response'}")
        page.locator("#text").wait_for(state="visible", timeout=20000)
        page.locator("#sendBtn").wait_for(state="visible", timeout=10000)
        if "DMate" not in page.title():
            raise AssertionError(f"Unexpected page title: {page.title()!r}")
        if urlsplit(page.url).netloc != target_host:
            raise AssertionError(f"Unexpected redirect: {page.url}")
        screenshot("home")

    def modal_test(button, modal, close_button, name):
        if is_mobile:
            page.locator("#mobileToolsBtn").click()
            page.locator("#mobileToolsClose").wait_for(state="visible", timeout=10000)
        page.locator(button).click(timeout=10000)
        page.locator(modal).wait_for(state="visible", timeout=12000)
        if name == "knowledge-graph":
            page.locator("#knowledgeGraphCanvas").wait_for(state="visible", timeout=12000)
            page.wait_for_function("""() => {
              const el = document.querySelector('#knowledgeGraphCanvas');
              return el && (el.querySelector('svg, canvas, .kg-mobile-stage') ||
                  (el.textContent && !el.textContent.includes('加载中')));
            }""", timeout=12000)
        screenshot(name)
        page.locator(close_button).click(timeout=10000)
        page.locator(modal).wait_for(state="hidden", timeout=10000)

    try:
        loaded = step("homepage", open_home)
        if loaded:
            if is_mobile:
                def tools_drawer():
                    page.locator("#mobileToolsBtn").click()
                    page.locator("#knowledgeGraphBtn").wait_for(state="visible", timeout=10000)
                    screenshot("tools")
                    page.locator("#mobileToolsClose").click()
                step("mobile-tools-drawer", tools_drawer)
            else:
                step("appearance", lambda: modal_test("#appearanceBtn", "#appearanceModal", "#appearanceClose", "appearance"))
            step("knowledge-graph", lambda: modal_test("#knowledgeGraphBtn", "#knowledgeGraphModal", "#knowledgeGraphClose", "knowledge-graph"))
            step("wrong-book", lambda: modal_test("#wrongBookBtn", "#wrongBookModal", "#wrongBookClose", "wrong-book"))
            step("learning-review", lambda: modal_test("#learningReviewBtn", "#learningReviewModal", "#learningReviewClose", "learning-review"))
        result["final_url"] = page.url
    except Exception:
        result["steps"].append({"name": "unexpected", "status": "failed", "error": traceback.format_exc()[-2000:]})
    finally:
        try:
            context.tracing.stop(path=str(output_dir / f"{mode}-trace.zip"))
        except Exception as exc:
            result["trace_error"] = str(exc)
        context.close()
    result["passed"] = all(item["status"] == "passed" for item in result["steps"])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("DMATE_TEST_URL", "https://dmate.zeabur.app/"))
    parser.add_argument("--output", default="artifacts/browser-smoke")
    args = parser.parse_args()
    if urlsplit(args.url).scheme != "https":
        parser.error("Only HTTPS targets are supported")
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"url": args.url, "started_at": datetime.now(timezone.utc).isoformat(), "results": []}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for mode in ("desktop", "mobile"):
                report["results"].append(exercise(browser, args.url, output_dir, mode))
            browser.close()
    except Exception:
        report["fatal_error"] = traceback.format_exc()[-2500:]
    report["passed"] = bool(report["results"]) and all(r["passed"] for r in report["results"]) and not report.get("fatal_error")
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in report["results"]:
        for test in result["steps"]:
            print(f"[{result['mode']}] {test['name']}: {test['status']}", flush=True)
            if test.get("error"):
                print("  " + test["error"][:400], flush=True)
    if report.get("fatal_error"):
        print(report["fatal_error"], file=sys.stderr)
    print(f"Report: {output_dir / 'report.json'}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
