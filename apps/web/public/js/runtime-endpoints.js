'use strict';

(function initializeRuntimeEndpoints(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ThirdHandRuntimeEndpoints = api;
})(typeof globalThis === 'undefined' ? null : globalThis, () => {
  function voiceEndpoint(port, locationLike = {}) {
    const numericPort = Number(port);
    if (!Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) {
      throw new TypeError('voice endpoint port must be an integer within [1, 65535]');
    }
    const protocol = locationLike.protocol === 'https:' ? 'wss:' : 'ws:';
    let hostname = String(locationLike.hostname || '127.0.0.1').trim();
    if (hostname.includes(':') && !hostname.startsWith('[')) hostname = `[${hostname}]`;
    return `${protocol}//${hostname}:${numericPort}/v1/voice`;
  }

  return { voiceEndpoint };
});
