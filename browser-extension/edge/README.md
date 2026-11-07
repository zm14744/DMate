# DMate for Microsoft Edge

DMate runs its **complete interface locally inside the Edge extension**. The original DMate HTML, CSS, JavaScript, MathJax, fonts, and image assets are bundled in this package. The extension does not embed the live website in an iframe and does not download or execute remote JavaScript.

The existing DMate backend remains online at https://dmate.zeabur.app/ for authenticated API operations such as AI chat, OCR, account login, and cloud sync. API requests are routed by the packaged extension bridge and use the declared host permission. Session cookies remain on the DMate backend.

## Install for testing

1. Download and extract `DMate_Edge_Original_UI.zip`.
2. Open `edge://extensions` in Microsoft Edge.
3. Turn on **Developer mode**.
4. Select **Load unpacked**.
5. Choose the extracted folder that directly contains `manifest.json`.

Click the DMate toolbar icon to open the native Edge side panel.

## Package

- Manifest V3; Edge 116 or later.
- Original DMate interface and front-end assets are packaged locally.
- Existing DMate rounded product icon is used at 16, 32, 48, and 128 pixels.
- Remote access is limited to the DMate HTTPS backend API.
- No iframe, remotely hosted executable code, or separate replacement chat UI.

## Test before store submission

Verify login, chat streaming, image/OCR upload, voice input, cloud sync, and file export in the target Edge profile. The package is designed to preserve the website's behavior, but those browser-specific flows still require an actual Edge test.
