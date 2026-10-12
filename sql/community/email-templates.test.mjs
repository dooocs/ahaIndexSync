import assert from 'node:assert/strict';
import { test } from 'node:test';
import { communityEmailTemplates, communityEmailSettings } from './email-templates.mjs';

test('all 13 supported Auth email subjects and bodies are Chinese', () => {
  assert.equal(communityEmailTemplates.length, 13);
  assert.equal(new Set(communityEmailTemplates.map(template => template.type)).size, 13);
  for (const template of communityEmailTemplates) {
    assert.match(template.subject, /[\u4e00-\u9fff]/);
    assert.match(template.content, /<html lang="zh-CN">/);
    assert.match(template.content, /请勿直接回复/);
    assert.doesNotMatch(template.content, /<script|<img|https?:\/\//i);
  }
});

test('link emails retain the Auth-generated confirmation URL and do not hardcode tokens or origins', () => {
  for (const template of communityEmailTemplates.filter(template => ['confirmation', 'magic_link', 'invite', 'recovery', 'email_change'].includes(template.type))) {
    assert.match(template.content, /href="\{\{ \.ConfirmationURL \}\}"/);
    assert.match(template.content, /仅可使用一次/);
    assert.doesNotMatch(template.content, /\.TokenHash|\.RedirectTo|127\.0\.0\.1/);
  }
});

test('reauthentication uses a code without assuming its length or exposing it in the subject', () => {
  const template = communityEmailTemplates.find(template => template.type === 'reauthentication');
  assert.match(template.content, /\{\{ \.Token \}\}/);
  assert.doesNotMatch(template.subject, /Token/);
  assert.doesNotMatch(template.content, /ConfirmationURL/);
});

test('notification templates contain no actionable verification credential', () => {
  for (const template of communityEmailTemplates.filter(template => template.type.endsWith('_notification'))) {
    assert.doesNotMatch(template.content, /ConfirmationURL|Token|<a /);
    assert.match(template.content, /如果这不是你本人的操作/);
  }
});

test('the settings payload touches only subjects and bodies, not SMTP secrets or Auth permissions', () => {
  const settings = communityEmailSettings();
  assert.equal(Object.keys(settings).length, 26);
  for (const key of Object.keys(settings)) assert.match(key, /^mailer_(subjects_[a-z_]+|templates_[a-z_]+_content)$/);
  settings.mailer_subjects_confirmation = 'changed';
  assert.notEqual(communityEmailSettings().mailer_subjects_confirmation, 'changed');
});
