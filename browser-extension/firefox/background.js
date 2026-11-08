// Toggle the native Firefox sidebar when the user clicks the DMate toolbar button.
browser.action.onClicked.addListener(() => {
  browser.sidebarAction.toggle().catch((error) => {
    console.error("DMate: unable to toggle the Firefox sidebar.", error);
  });
});
