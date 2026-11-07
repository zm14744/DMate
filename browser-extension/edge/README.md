# DMate for Microsoft Edge

DMate for Edge is a native Edge Side Panel chat client. It keeps the compact dark DMate layout and sends text conversations to the existing DMate chat API.

## Install locally

1. Download this repository ZIP, or check out the `feature/edge-side-panel` branch.
2. Open `edge://extensions` in Microsoft Edge.
3. Turn on **Developer mode**.
4. Choose **Load unpacked**.
5. Select the `browser-extension/edge` directory.
6. Pin DMate to the toolbar if desired, then click its toolbar icon to open the side panel.

## Included in this first build

- Native Edge Side Panel opened from the toolbar action.
- Dark DMate-style header, conversation area, question marker, and rounded composer.
- Text chat through the existing `POST /chat` endpoint.
- Local conversation persistence using `chrome.storage.local`.
- Enter to send; Shift+Enter for a new line.
- Only requests `sidePanel` and `storage`, plus host access to the DMate production API.

## Important scope and privacy notes

This first side-panel build runs as a local extension page and calls the DMate API in guest mode. It deliberately does not embed or redirect the full website into the side panel: browser side panels are extension pages, and navigating them to an external website can leave the side panel or open a normal tab.

Because the current DMate API uses same-origin HttpOnly session cookies and does not provide a general third-party Bearer-token/CORS account API, this initial extension does **not** sign in to DMate accounts or access cloud-synced chat history. Its side-panel conversation is stored locally in the browser. The question marker is a local UI label; it does not add an item to the website's formal question bank.

For account login, image recognition, notebooks, graph tools, and cross-device sync, use the full DMate website from the menu.

## Store release

This is a local development package, not yet submitted to Microsoft Edge Add-ons. Before store submission, prepare the final raster extension icon sizes, store screenshots, privacy disclosures, and listing text, then test the packaged build in Edge.
