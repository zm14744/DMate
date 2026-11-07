/* Route DMate API requests to the existing backend while keeping all UI code local. */
(() => {
  'use strict';
  const API_ORIGIN = 'https://dmate.zeabur.app';
  const extensionOrigin = window.location.origin;
  const nativeFetch = window.fetch.bind(window);

  function isLocalApiRequest(url) {
    if (url.origin !== extensionOrigin) return false;
    if (/^\/(?:static\/|extension\/|icons\/|sidebar\.html(?:$|\/)|favicon(?:\.|\/)|robots\.txt|sitemap\.xml)/i.test(url.pathname)) return false;
    return true;
  }

  window.fetch = function(input, init) {
    let sourceUrl;
    try {
      sourceUrl = input instanceof Request
        ? input.url
        : (input instanceof URL ? input.href : String(input));
      const url = new URL(sourceUrl, window.location.href);
      if (!isLocalApiRequest(url)) return nativeFetch(input, init);

      const backendUrl = API_ORIGIN + url.pathname + url.search + url.hash;
      const options = { ...(init || {}), credentials: 'include' };
      if (input instanceof Request) {
        return nativeFetch(new Request(backendUrl, input), options);
      }
      return nativeFetch(backendUrl, options);
    } catch (error) {
      return Promise.reject(error);
    }
  };
})();
