const entries = [
  ['confirmation', '确认注册', '感谢注册 AmazingIndex 相亲社区。请确认邮箱，完成注册并登录。', '确认邮箱并登录'],
  ['magic_link', '登录相亲社区', '你正在登录 AmazingIndex 相亲社区。请点击下方按钮完成登录。', '确认登录'],
  ['invite', '相亲社区邀请', '你收到了 AmazingIndex 相亲社区的邀请。请确认邮箱并创建账号。', '接受邀请'],
  ['recovery', '重置账号密码', '我们收到了重置密码的请求。请点击下方按钮继续。', '重置密码'],
  ['email_change', '确认新邮箱', '你正在更换账号邮箱。请确认本次邮箱变更。', '确认邮箱变更'],
  ['reauthentication', '账号安全验证码', '你正在执行需要再次验证身份的操作。请在发起操作的页面输入以下验证码。'],
  ['password_changed_notification', '账号密码已修改', '你的 AmazingIndex 账号密码已修改。'],
  ['email_changed_notification', '账号邮箱已修改', '你的 AmazingIndex 账号邮箱已修改。'],
  ['phone_changed_notification', '账号手机号已修改', '你的 AmazingIndex 账号手机号已修改。'],
  ['identity_linked_notification', '已添加登录方式', '你的 AmazingIndex 账号已关联新的登录方式。'],
  ['identity_unlinked_notification', '已移除登录方式', '你的 AmazingIndex 账号已移除一项登录方式。'],
  ['mfa_factor_enrolled_notification', '已添加身份验证方式', '你的 AmazingIndex 账号已添加新的身份验证方式。'],
  ['mfa_factor_unenrolled_notification', '已移除身份验证方式', '你的 AmazingIndex 账号已移除一项身份验证方式。'],
];

function content([type, title, description, action]) {
  const verification = action
    ? `<p><a href="{{ .ConfirmationURL }}" style="display:inline-block;background:#215d50;color:#fff;padding:12px 20px;border-radius:4px;text-decoration:none">${action}</a></p><p>按钮无法打开时，请将下面的完整链接复制到浏览器地址栏：</p><p style="overflow-wrap:anywhere">{{ .ConfirmationURL }}</p><p>链接仅可使用一次，请尽快完成验证，不要转发给他人。</p>`
    : type === 'reauthentication'
      ? '<p style="font-size:28px;font-weight:bold">{{ .Token }}</p><p>验证码仅供本人使用，请勿向他人透露。</p>'
      : '<p>如果这不是你本人的操作，请立即检查账号安全，并通过网站联系方式联系管理员。</p>';
  const warning = action || type === 'reauthentication'
    ? '<p>如果你没有发起这次操作，请忽略本邮件。不要将验证链接或验证码交给任何人。</p>'
    : '';
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#fff;color:#252a27;font-family:Arial,sans-serif;line-height:1.7"><main style="max-width:560px;margin:0 auto;padding:28px 20px"><p>AmazingIndex 相亲社区</p><h1 style="font-size:24px">${title}</h1><p>${description}</p>${verification}${warning}<hr style="border:0;border-top:1px solid #d7ded9"><p style="color:#666;font-size:13px">本邮件由系统自动发送，请勿直接回复。</p></main></body></html>`;
}

export const communityEmailTemplates = Object.freeze(entries.map(entry => Object.freeze({
  type: entry[0],
  subject: `【AmazingIndex】${entry[1]}`,
  content: content(entry),
})));

export function communityEmailSettings() {
  return Object.fromEntries(communityEmailTemplates.flatMap(template => [
    [`mailer_subjects_${template.type}`, template.subject],
    [`mailer_templates_${template.type}_content`, template.content],
  ]));
}
