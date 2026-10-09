'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const publicRoot = process.env.THIRDHAND_WEB_PUBLIC ||
  path.resolve(__dirname, '../../../apps/web/public');

function harness(saved, blocked = false) {
  const writes = [];
  const context = vm.createContext({
    localStorage: {
      getItem() { if (blocked) throw new Error('blocked'); return saved; },
      setItem(key, value) { if (blocked) throw new Error('blocked'); writes.push([key, value]); },
    },
  });
  for (const file of ['i18n-catalog.js', 'i18n-voice-catalog.js', 'i18n.js']) {
    const filename = path.join(publicRoot, 'js', file);
    // An absent language layer is the intended pre-implementation failure.
    if (fs.existsSync(filename)) vm.runInContext(fs.readFileSync(filename, 'utf8'), context);
  }
  assert.ok(context.ThirdHandI18n, 'The public bilingual language layer is available');
  return { api: context.ThirdHandI18n, writes };
}

test('a fresh browser displays English and an explicit choice persists', () => {
  const { api, writes } = harness(null);
  assert.equal(api.locale, 'en');
  assert.equal(api.translate('关节控制'), 'Joint Control');
  assert.equal(api.setLocale('zh-CN'), true);
  assert.equal(api.translate('关节控制'), '关节控制');
  assert.equal(writes.at(-1)[1], 'zh-CN');
  assert.equal(api.setLocale('invalid'), false);
  assert.equal(api.locale, 'zh-CN');
});

test('saved Chinese is restored; unsupported preferences and blocked storage default to English', () => {
  assert.equal(harness('zh-CN').api.locale, 'zh-CN');
  assert.equal(harness('fr').api.locale, 'en');
  const { api } = harness(null, true);
  assert.equal(api.locale, 'en');
  assert.doesNotThrow(() => api.setLocale('zh-CN'));
  assert.equal(api.translate('软件停止'), '软件停止');
});

test('switching updates safety text without weakening the hardware emergency stop warning', () => {
  const { api } = harness(null);
  assert.equal(api.translate('⏹ 软件停止'), '⏹ Software Stop');
  const source = '请确认运动范围已清空、现场有人看护，且独立硬件急停可用。停止 Dummy 不等于硬件急停。';
  assert.match(api.translate(source), /independent hardware emergency stop/i);
  assert.match(api.translate(source), /not.*hardware emergency stop/i);
  api.setLocale('zh-CN');
  assert.equal(api.translate(source), source);
});

test('dynamic messages retain numbers, units, target IDs and literal quoted user content', () => {
  const { api } = harness(null);
  assert.equal(api.translate('已选 L3'), 'Selected L3');
  assert.equal(api.translate('帧 247 · locked'), 'Frame 247 · locked');
  assert.equal(api.translate('X超出限位（150～660）'), 'X is outside limits (150–660)');
  assert.equal(api.translate('来自：“打开夹爪”'), 'Source: “打开夹爪”');
  assert.equal(api.translate('J1 目标 170.0° 超出机械关节限位（允许 -162°～162°）'),
    'J1 target 170.0° is outside joint limits (allowed -162°–162°)');
  assert.equal(api.translate('unknown_backend_reason: 42'), 'unknown_backend_reason: 42');
});

test('English-origin vision hints also switch back to Chinese', () => {
  const { api } = harness('zh-CN');
  assert.equal(api.translate('No objects detected'), '未检测到物体');
  assert.equal(api.translate('depth: unavailable'), '深度：不可用');
});

test('multi-joint limit warnings translate individually without swallowing adjacent warnings', () => {
  const { api } = harness(null);
  const source = '机械限位禁止执行：J1 目标 170.0° 超出机械关节限位（允许 -162°～162°）；J2 目标 210.0° 超出机械关节限位（允许 -12°～201°）';
  const translated = 'Execution blocked by mechanical limits: J1 target 170.0° is outside joint limits (allowed -162°–162°); J2 target 210.0° is outside joint limits (allowed -12°–201°)';
  assert.equal(api.translate(source), translated);
  api.setLocale('zh-CN');
  assert.equal(api.translate(translated), source);
  api.setLocale('en');
  assert.equal(api.translate('Home 机械限位禁止执行：J1 限位或目标数据无效；J2 限位或目标数据无效'),
    'Home execution blocked by mechanical limits: J1 limit or target data is invalid; J2 limit or target data is invalid');
});

function fixture() {
  const document = {
    createTreeWalker(root) {
      const nodes = [];
      const visit = node => { for (const child of node.children || []) { nodes.push(child); visit(child); } };
      visit(root);
      return { nextNode: () => nodes.shift() || null };
    },
  };
  function element(attrs = {}, children = []) {
    const node = { nodeType: 1, ownerDocument: document, children, value: '37.5', checked: true,
      disabled: true, validationMessage: '',
      closest() { return attrs['data-i18n-skip'] !== undefined ? node : this.parentElement?.closest() || null; },
      getAttribute: name => attrs[name] ?? null,
      setAttribute: (name, value) => { attrs[name] = value; },
      setCustomValidity(value) { this.validationMessage = value; },
    };
    for (const child of children) child.parentElement = node;
    return node;
  }
  const text = value => ({ nodeType: 3, nodeValue: value, ownerDocument: document });
  return { element, text };
}

test('language changes update existing and new UI nodes but preserve controls and excluded content', () => {
  const { api } = harness(null);
  const { element, text } = fixture();
  const label = text('关节控制');
  const user = text('打开夹爪');
  const number = text('J1:37.5°');
  const input = element({ 'aria-label': '夹爪目标开度' });
  const root = element({}, [element({}, [label]), element({ 'data-i18n-skip': '' }, [user]),
    element({}, [number]), input]);
  api.translateTree(root);
  assert.equal(label.nodeValue, 'Joint Control');
  assert.equal(user.nodeValue, '打开夹爪');
  assert.equal(number.nodeValue, 'J1:37.5°');
  assert.equal(input.getAttribute('aria-label'), 'Gripper target opening');
  assert.equal(input.value, '37.5');
  assert.equal(input.checked, true);
  assert.equal(input.disabled, true);
  api.setLocale('zh-CN');
  api.translateTree(root);
  assert.equal(label.nodeValue, '关节控制');
  assert.equal(input.getAttribute('aria-label'), '夹爪目标开度');
  label.nodeValue = '软件停止';
  api.setLocale('en');
  api.translateTree(root);
  assert.equal(label.nodeValue, 'Software Stop');
});

test('native validation follows language selection without reviving a cleared error', () => {
  const { api } = harness(null);
  const input = fixture().element();
  api.setValidity(input, 'X超出限位（150～660）');
  assert.equal(input.validationMessage, 'X is outside limits (150–660)');
  api.setLocale('zh-CN');
  api.translateTree(input);
  assert.equal(input.validationMessage, 'X超出限位（150～660）');
  input.setCustomValidity('');
  api.setLocale('en');
  api.translateTree(input);
  assert.equal(input.validationMessage, '');
  assert.equal(input.value, '37.5');
});

test('textarea placeholders translate without translating user text or changing its value', () => {
  const { api } = harness(null);
  const { element, text } = fixture();
  const draft = text('关节控制');
  const textarea = element({ placeholder: '输入文字指令…' }, [draft]);
  textarea.closest = selector => selector === 'textarea' ? textarea : null;
  textarea.value = '打开夹爪';
  api.translateTree(textarea);
  assert.equal(textarea.getAttribute('placeholder'), 'Enter a text command…');
  assert.equal(textarea.value, '打开夹爪');
  assert.equal(draft.nodeValue, '关节控制');
});
