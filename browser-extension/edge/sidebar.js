(() => {
  "use strict";

  // Navigate the side-panel tab itself instead of embedding the app in an
  // iframe. This keeps DMate first-party for login cookies and browser storage.
  const appUrl = "https://dmate.zeabur.app/";
  const fallbackLink = document.getElementById("openDmate");
  if (fallbackLink) fallbackLink.href = appUrl;

  window.location.replace(appUrl);
})();
