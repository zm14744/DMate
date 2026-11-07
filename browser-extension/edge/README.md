# DMate for Microsoft Edge

This extension displays the **existing DMate website** inside Edge's native Side Panel. It does not implement a replacement chat UI. The page, styles, scripts, and application features are served by the existing DMate deployment.

## Install

1. Extract this ZIP to a folder.
2. Open `edge://extensions` in Edge.
3. Enable **Developer mode**.
4. Click **Load unpacked**.
5. Select the extracted folder that directly contains `manifest.json`.

## Notes

- Edge 116+; Manifest V3.
- Opens from the extension toolbar icon.
- Embeds `https://dmate.zeabur.app/` directly, so the original DMate HTML/CSS/JavaScript and backend remain the source of the interface and behavior.
- No separate chat renderer, custom composer, or duplicate local chat store is included.
- Test sign-in, microphone, uploads, and browser permissions in Edge before store submission. Since the original site is embedded cross-origin, third-party-cookie and frame-embedding policies may affect sign-in; if so, the correct fix is to adapt the existing site's embedding/auth policy, not rebuild its UI.
