// Open the native Edge side panel when the user clicks the DMate toolbar action.
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({
    openPanelOnActionClick: true
  }).catch((error) => {
    console.error("DMate: unable to enable action-click side panel behavior.", error);
  });
});
