# DMate for Microsoft Edge

This is the installable Edge extension package for DMate. It opens the existing DMate website in Edge's native Side Panel; the original website remains responsible for the interface, styling, chat behavior, and backend.

## Download

[Download DMate_Edge_Original_UI.zip](../DMate_Edge_Original_UI.zip)

## Install

1. Download and extract the ZIP.
2. Open `edge://extensions` in Microsoft Edge.
3. Turn on **Developer mode**.
4. Select **Load unpacked**.
5. Choose the extracted folder that directly contains `manifest.json`.

Click the DMate toolbar icon to open the native side panel.

## Package details

- Manifest V3; Edge 116 or later.
- Uses the existing DMate v52 product icon in 16, 32, 48, and 128 pixel sizes.
- Loads `https://dmate.zeabur.app/` directly in the side panel.
- Does not ship a second chat interface or a separate local chat implementation.

The embedded site may be subject to the browser's third-party-cookie and frame-embedding rules. Sign-in and media permissions should be tested in the target Edge profile before store submission.
