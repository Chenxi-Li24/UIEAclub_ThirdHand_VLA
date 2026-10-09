/* Presentation only: never writes input values, control state or wire payloads. */
(() => {
  'use strict';
  const STORAGE_KEY = 'thirdhand.ui-language';
  const supported = new Set(['en', 'zh-CN']);
  let locale = 'en';
  try {
    const saved = globalThis.localStorage?.getItem(STORAGE_KEY);
    if (supported.has(saved)) locale = saved;
  } catch { /* A blocked storage area must not prevent robot UI startup. */ }

  const exact = new Map();
  const patterns = [];
  const numberCapture = '([+\\u2212-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?)';
  const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [zh, en] of globalThis.ThirdHandI18nCatalog || []) {
    const pair = { 'zh-CN': zh, en };
    for (const source of [zh, en]) {
      const names = [];
      let cursor = 0;
      let expression = '^';
      for (const token of source.matchAll(/\{(\w+)\}/g)) {
        const capture = /^(joint|target|min|max)$/.test(token[1]) ? numberCapture : '(.*?)';
        expression += escape(source.slice(cursor, token.index)) + capture;
        names.push(token[1]);
        cursor = token.index + token[0].length;
      }
      if (names.length) {
        expression += escape(source.slice(cursor)) + '$';
        patterns.push({ regex: new RegExp(expression, 's'), names, pair });
      } else {
        exact.set(source, pair);
      }
    }
  }

  function translate(source, language = locale, depth = 0) {
    if (typeof source !== 'string' || !supported.has(language)) return source;
    const match = /^(\s*)([\s\S]*?)(\s*)$/.exec(source);
    const text = match[2];
    let translated = exact.get(text)?.[language];
    if (translated === undefined && depth < 4) {
      for (const pattern of patterns) {
        const found = pattern.regex.exec(text);
        if (!found) continue;
        const values = Object.fromEntries(pattern.names.map((name, index) => [name, found[index + 1]]));
        translated = pattern.pair[language].replace(/\{(\w+)\}/g, (_, name) => {
          const value = values[name];
          if (name === 'warnings') {
            return value.split(/；|; /).map(warning => translate(warning, language, depth + 1))
              .join(language === 'en' ? '; ' : '；');
          }
          // User quotations, names, backend reason codes and IDs stay literal.
          return /^(source|raw|name|id|frame|status|reason|code|hash)$/.test(name)
            ? value : translate(value, language, depth + 1);
        });
        break;
      }
    }
    return translated === undefined ? source : match[1] + translated + match[3];
  }

  const textSources = new WeakMap();
  const attributeSources = new WeakMap();
  const validitySources = new WeakMap();
  const skipSelector = 'script,style,[data-i18n-skip],#log-area,' +
    '.voice-message--user .voice-message-text,.voice-message--ai .voice-message-text';
  const attributes = ['title', 'alt', 'aria-label', 'placeholder'];
  let observer = null;

  function skipped(node) {
    const element = node.nodeType === 1 ? node : node.parentElement;
    return Boolean(element?.closest(skipSelector));
  }

  function renderText(node) {
    if (skipped(node) || node.parentElement?.closest('textarea')) return;
    const previous = textSources.get(node);
    const source = previous && node.nodeValue === previous.rendered ? previous.source : node.nodeValue;
    const rendered = translate(source);
    if (rendered !== source || previous) textSources.set(node, { source, rendered });
    if (node.nodeValue !== rendered) node.nodeValue = rendered;
  }

  function renderAttributes(element) {
    if (skipped(element)) return;
    const cached = attributeSources.get(element) || new Map();
    for (const name of attributes) {
      const current = element.getAttribute(name);
      if (current === null) { cached.delete(name); continue; }
      const previous = cached.get(name);
      const source = previous && current === previous.rendered ? previous.source : current;
      const rendered = translate(source);
      if (rendered !== source || previous) cached.set(name, { source, rendered });
      if (current !== rendered) element.setAttribute(name, rendered);
    }
    if (cached.size) attributeSources.set(element, cached);
    const validity = validitySources.get(element);
    if (validity) {
      if (element.validationMessage !== validity.rendered) validitySources.delete(element);
      else {
        validity.rendered = translate(validity.source);
        element.setCustomValidity(validity.rendered);
      }
    }
  }

  function translateTree(root) {
    if (!root || skipped(root)) return;
    if (root.nodeType === 3) { renderText(root); return; }
    if (root.nodeType === 1) renderAttributes(root);
    const walker = root.ownerDocument.createTreeWalker(root, 5); // Elements and text, not comments.
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeType === 3) renderText(node);
      else renderAttributes(node);
    }
  }

  function setValidity(input, source) {
    const rendered = translate(source);
    if (source) validitySources.set(input, { source, rendered });
    else validitySources.delete(input);
    input.setCustomValidity(rendered);
  }

  function setLocale(next) {
    if (!supported.has(next)) return false;
    locale = next;
    try { globalThis.localStorage?.setItem(STORAGE_KEY, next); } catch { /* Session-only selection. */ }
    if (globalThis.document) {
      document.documentElement.lang = locale;
      translateTree(document.head);
      translateTree(document.body);
      const selector = document.getElementById('language-select');
      if (selector) selector.value = locale;
    }
    return true;
  }

  globalThis.ThirdHandI18n = Object.freeze({
    get locale() { return locale; }, translate, translateTree, setLocale, setValidity,
  });

  function initialize() {
    document.documentElement.lang = locale;
    translateTree(document.head);
    translateTree(document.body);
    const selector = document.getElementById('language-select');
    if (selector) {
      selector.value = locale;
      selector.addEventListener('change', () => setLocale(selector.value));
    }
    observer = new MutationObserver(records => {
      // Process only changed UI nodes; high-rate joint numbers are never rescanned globally.
      const roots = new Set();
      for (const record of records) {
        if (record.type === 'childList') record.addedNodes.forEach(node => roots.add(node));
        else roots.add(record.target);
      }
      for (const root of roots) translateTree(root);
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true,
      attributes: true, attributeFilter: attributes });
  }

  if (globalThis.document) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true });
    else initialize();
  }
})();
