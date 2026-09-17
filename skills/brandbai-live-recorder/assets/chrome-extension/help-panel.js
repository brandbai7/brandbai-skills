/* Local, user-triggered contact copying. No page access or collection side effects. */
(() => {
  'use strict';
  const status = document.getElementById('contact-status');
  const contacts = [
    ['copy-official-account', '公众号', '布兰德老白BrandBai'],
    ['copy-support-email', '邮箱', 'brandlaobai@163.com'],
  ];
  let latestCopy = 0;
  for (const [id, label, value] of contacts) {
    const button = document.getElementById(id);
    if (!button || !status) continue;
    button.addEventListener('click', async () => {
      const request = ++latestCopy;
      try {
        await navigator.clipboard.writeText(value);
        if (request !== latestCopy) return;
        status.textContent = `${label}已复制`;
      } catch (_) {
        if (request !== latestCopy) return;
        status.textContent = `未能自动复制，请手动复制：${value}`;
      }
      status.hidden = false;
    });
  }
})();
