# DMate for Firefox

Firefox-specific build of DMate. It reuses the original DMate front-end, CSS, JavaScript, MathJax assets, fonts, and rounded product icon from the Edge package. The interface is bundled locally and is not embedded from a remote iframe.

## Firefox integration

- Manifest V3.
- Uses Firefox's native `sidebar_action` and `browser.sidebarAction` APIs.
- The toolbar button toggles the DMate sidebar.
- The same local DMate interface is used; the Firefox sidebar is positioned and sized by Firefox.
- Firefox 140 or later is required for the built-in data-collection consent declaration.
- Desktop Firefox is the target. Firefox Android's UI does not provide the desktop sidebar experience.

## Backend and data

The original DMate backend remains at https://dmate.zeabur.app/. The packaged API bridge sends application requests to that host. User-submitted prompts, images, audio, and account information may be processed by DMate and the configured service providers as described in the DMate privacy documentation. The extension does not read browsing history or automatically inspect the active webpage.

## Install for local testing

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…**.
3. Select the `manifest.json` file from the extracted Firefox extension folder.
4. Click the DMate toolbar button to toggle the sidebar.

For normal user installation, submit the ZIP to Mozilla Add-ons (AMO). Firefox release builds require Mozilla-signed extensions.

## Review notes

The manifest declares the data categories needed for account authentication, user-submitted chat messages, and personally identifying information such as email addresses and voice recordings. It does not request browsing-history, tab-content, or all-sites permissions.

The front-end files are packaged locally. Network access is limited to the DMate backend host declared in `host_permissions`; the backend may forward specific user-submitted content to configured AI and email providers. Confirm the public privacy-policy URL and the production provider configuration before submitting the AMO listing.
