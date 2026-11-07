# DMate for Microsoft Edge

DMate for Edge opens the existing DMate web application in Edge's native Side Panel. The panel uses the existing website and backend; it does not create a second chat client or a separate account store.

## Install locally

1. Download this repository, or check out the `feature/edge-side-panel` branch.
2. Open `edge://extensions` in Microsoft Edge.
3. Turn on **Developer mode**.
4. Choose **Load unpacked**.
5. Select this `browser-extension/edge` directory.
6. Pin DMate to the toolbar if desired, then click its toolbar icon to open the side panel.

## What this version does

- Uses the native Edge Side Panel rather than a popup or a new tab.
- Opens the live DMate website as a top-level page in the side panel (not an iframe), so the website remains first-party for its normal login cookies and browser storage.
- Reuses the current DMate web UI, account system, chat history, and backend.
- Keeps the extension permissions minimal: only `sidePanel` is requested.

## Current scope

This is the first Edge side-panel build. It is a browser-side entry point to the existing DMate web application. It does not yet inject into arbitrary pages, read page contents, or add a “Ask DMate about selection” context-menu command. Those features should be added separately with explicit permissions and a clear user action.

The extension is not yet submitted to Microsoft Edge Add-ons. Before store submission, prepare and verify the store listing assets (including the required raster icon sizes), screenshots, privacy disclosures, and final package.

## Development notes

- Manifest V3.
- Uses the Edge/Chromium Side Panel API (Edge 116 or later).
- The app URL is defined in `sidebar.js`.
