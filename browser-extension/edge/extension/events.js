/* Replaces inline onclick attributes removed for Manifest V3 CSP compliance. */
document.addEventListener('click', event => {
  const element = event.target instanceof Element
    ? event.target.closest('[data-dmate-action]')
    : null;
  if (!element) return;
  switch (element.dataset.dmateAction) {
    case 'new-chat':
      if (typeof window.newChat === 'function') window.newChat();
      break;
    case 'send-or-stop':
      if (typeof window.handleSendOrStop === 'function') window.handleSendOrStop();
      break;
    case 'close-wrong-retest-review':
      if (typeof window.closeWrongRetestReview === 'function') window.closeWrongRetestReview();
      break;
  }
});
