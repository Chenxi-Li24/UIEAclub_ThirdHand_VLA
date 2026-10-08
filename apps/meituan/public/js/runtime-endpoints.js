'use strict';

(function initializeRuntimeEndpoints(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ThirdHandRuntimeEndpoints = api;
})(typeof globalThis === 'undefined' ? null : globalThis, () => {
  function voiceEndpoint(locationLike = {}) {
    const protocol = locationLike.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = String(locationLike.host || '127.0.0.1:9983').trim();
    return `${protocol}//${host}/voice`;
  }

  return { voiceEndpoint };
});
