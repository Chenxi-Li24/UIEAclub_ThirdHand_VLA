'use strict';

function createBrowserCommandRouter({ handleGrounding, handleLegacy }) {
  if (typeof handleGrounding !== 'function') {
    throw new TypeError('handleGrounding must be a function');
  }
  if (typeof handleLegacy !== 'function') {
    throw new TypeError('handleLegacy must be a function');
  }

  return function handleBrowserCommand(message, operator) {
    if (message && message.cmd === 'ground_language_target') {
      return handleGrounding(message, operator);
    }
    return handleLegacy(message, operator);
  };
}

module.exports = { createBrowserCommandRouter };
