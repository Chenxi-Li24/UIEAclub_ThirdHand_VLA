import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('the primary demo CTA and navigation point to the in-page demo section', () => {
  const content = read('../src/content/site.ts');

  assert.match(content, /id: 'demos', label: 'Demos'/);
  assert.match(content, /demoCta:[\s\S]*href: '#demos'/);
  assert.match(content, /heroLabel: 'View project introduction'/);
  assert.doesNotMatch(content, /下滑查看项目介绍/);
  assert.doesNotMatch(content, /chatgpt\.site/);
});

test('the app renders one demo section containing all three local videos', () => {
  const app = read('../src/App.tsx');
  const demos = read('../src/components/Demos.tsx');
  const content = read('../src/content/site.ts');
  const media = read('../src/content/media.ts');

  assert.match(app, /<Demos \/>/);
  assert.match(demos, /id="demos"/);
  assert.match(demos, /<source src=\{video\.src\} type="video\/mp4" \/>/);
  assert.doesNotMatch(content, /\/media\/demos/);

  const videoFiles = [
    '01-bottle-pickup.mp4',
    '02-voice-pickup.mp4',
    '03-dummy-follow.mp4',
  ];

  for (const filename of videoFiles) {
    assert.match(media, new RegExp(`/media/demos/${filename}`));
    const url = new URL(`../public/media/demos/${filename}`, import.meta.url);
    assert.equal(existsSync(url), true, `${filename} should exist locally`);
    assert.ok(statSync(url).size > 0, `${filename} should not be empty`);
  }
});
